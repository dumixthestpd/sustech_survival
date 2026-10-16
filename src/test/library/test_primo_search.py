"""Offline library read/CLI regressions; errors must never look like no hits."""

import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock

import pytest
import requests
from click.testing import CliRunner

from sustech_survival.cli import cli

module = importlib.import_module("sustech_survival.lib.search")


@pytest.fixture
def browser(monkeypatch):
    session = requests.Session()
    session.cookies.set(
        "JSESSIONID", "fake-primo", domain="sustc.primo.exlibrisgroup.com.cn", path="/primaws"
    )
    session.cookies.set("TGC", "fake-cas", domain="cas.sustech.edu.cn", path="/cas", secure=True)
    auth = SimpleNamespace(session=session)
    monkeypatch.setattr(module, "_ensure_auth", lambda: (auth, True, ""))
    pw, ctx, page = Mock(), Mock(), Mock()
    page.url = "https://sustc.primo.exlibrisgroup.com.cn/discovery/search"
    page.goto.return_value.status = 200
    pending = MagicMock()
    api = pending.__enter__.return_value.value
    api.status = 200
    api.json.return_value = {"docs": [{}], "info": {"total": 1}}
    page.expect_response.return_value = pending
    empty = Mock()
    empty.is_visible.return_value = True
    page.query_selector.side_effect = lambda selector: (
        empty if selector == module.EMPTY_SELECTOR else None
    )
    page.query_selector_all.return_value = []
    ctx.new_page.return_value = page
    launch = Mock(return_value=(pw, ctx))
    monkeypatch.setattr(module, "_playwright_page", launch)
    return SimpleNamespace(pw=pw, ctx=ctx, page=page, launch=launch, api=api)


def test_browser_cookies_keep_real_domains_and_paths(browser):
    browser.api.json.return_value = {"docs": [], "info": {"total": 0}}
    assert module.search("geometry", headless=False) == []
    browser.launch.assert_called_once_with(headless=False)
    cookies = browser.ctx.add_cookies.call_args.args[0]
    assert {(c["name"], c["domain"], c["path"]) for c in cookies} == {
        ("JSESSIONID", "sustc.primo.exlibrisgroup.com.cn", "/primaws"),
        ("TGC", "cas.sustech.edu.cn", "/cas"),
    }
    browser.ctx.close.assert_called_once()
    browser.pw.stop.assert_called_once()


@pytest.mark.parametrize("operation,args", [("search", ["geometry"]), ("detail", ["alma123"])])
def test_auth_failure_propagates_without_browser(monkeypatch, operation, args):
    monkeypatch.setattr(module, "_ensure_auth", lambda: (None, False, "Primo TLS failure"))
    launch = Mock()
    monkeypatch.setattr(module, "_playwright_page", launch)
    with pytest.raises(module.LibraryError, match="Primo TLS failure"):
        getattr(module, operation)(*args)
    launch.assert_not_called()


@pytest.mark.parametrize("operation,args", [("search", ["geometry"]), ("detail", ["alma123"])])
def test_page_read_failure_is_not_empty_and_closes_browser(browser, operation, args):
    browser.page.goto.side_effect = RuntimeError("unsafe browser error with ticket=ST-PRIVATE")
    with pytest.raises(module.LibraryError) as caught:
        getattr(module, operation)(*args)
    assert "ST-PRIVATE" not in str(caught.value)
    browser.ctx.close.assert_called_once()
    browser.pw.stop.assert_called_once()


def test_wait_timeout_is_not_a_confirmed_empty_search(browser):
    browser.page.wait_for_selector.side_effect = TimeoutError("result list never loaded")
    with pytest.raises(module.LibraryError, match="TimeoutError"):
        module.search("geometry")


@pytest.mark.parametrize("status", [403, 500])
def test_http_error_does_not_become_zero_results(browser, status):
    browser.page.goto.return_value.status = status
    with pytest.raises(module.LibraryError, match=f"HTTP {status}"):
        module.search("geometry")


def test_cas_redirect_is_a_failure(browser):
    browser.page.url = "https://cas.sustech.edu.cn/cas/login"
    with pytest.raises(module.LibraryError, match="redirected to login"):
        module.search("geometry")


@pytest.mark.parametrize("command,args", [("search", ["geometry"]), ("detail", ["alma123"])])
def test_json_cli_failure_has_nonzero_exit_and_no_fake_result(monkeypatch, command, args):
    monkeypatch.setattr(module, command, Mock(side_effect=module.LibraryError("Primo read failed")))
    result = CliRunner().invoke(cli, ["lib", command, *args, "--json"])
    assert result.exit_code == 1 and result.stdout == ""
    assert "Primo read failed" in result.stderr


def test_confirmed_empty_json_is_valid_success(monkeypatch):
    monkeypatch.setattr(module, "search", lambda **kwargs: [])
    result = CliRunner().invoke(cli, ["lib", "search", "no-such-book", "--json"])
    assert result.exit_code == 0 and json.loads(result.stdout) == []


def test_auth_diagnostics_are_kept_off_stdout(monkeypatch, capsys):
    from sustech_survival.sso import LibAuth

    def ensure():
        print("fake auth status")
        return False, "test failure"

    monkeypatch.setattr(LibAuth(), "ensure", ensure)
    module._ensure_auth()
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "fake auth status\n"


@pytest.mark.parametrize(
    "scope,expected",
    [("catalog", "MyInst_and_CI"), ("default", "MyInstitution"), ("eresource", "CentralIndex")],
)
def test_search_url_uses_current_route_and_real_scopes(scope, expected):
    from urllib.parse import parse_qs, urlsplit

    url = urlsplit(module._build_search_url(query="geometry", scope=scope, limit=8, offset=10))
    assert url.hostname == "sustc.primo.exlibrisgroup.com.cn"
    assert url.path == "/discovery/search"
    args = parse_qs(url.query)
    assert args["search_scope"] == [expected]
    assert args["offset"] == ["10"] and args["bulkSize"] == ["8"]


def test_nested_result_wrappers_do_not_duplicate_records(browser):
    item = Mock()
    title = Mock()
    title.text_content.return_value = "Test geometry book"
    title.inner_text.return_value = "Test geometry book"
    title.get_attribute.return_value = "/discovery/fulldisplay?docid=alma123"
    item.query_selector.side_effect = lambda selector: (
        title if selector == ".item-title a" else None
    )
    browser.page.query_selector_all.side_effect = lambda selector: (
        [item] if selector.startswith(".list-item") else [item, item]
    )
    rows = module.search("geometry", limit=8, offset=10)
    assert len(rows) == 1 and rows[0].docid == "alma123" and rows[0].rank == 11
    assert rows[0].detail_url.startswith("https://sustc.primo.exlibrisgroup.com.cn/")


def test_malformed_result_is_not_a_successful_partial_search(browser):
    item = Mock()
    item.query_selector.return_value = None
    browser.page.query_selector_all.return_value = [item]
    with pytest.raises(module.LibraryError, match="missing its title or record ID"):
        module.search("geometry")


def test_detail_fields_are_bounded_and_hidden_duplicates_removed():
    def row(key, value):
        return f'<div><div><span data-details-label="{key}">translated label</span></div><div class="item-details-element-container"><div role="listitem"><div aria-hidden="true">hidden duplicate</div>{value}</div></div></div>'

    html = (
        "<h1>Full display page</h1>"
        + "".join(
            [
                row("title", "Geometry test volume"),
                row("creator", "Example Author"),
                row("publisher", "Example Press"),
                row("creationdate", "2009"),
                row("language", "Chinese"),
                row("subject", "Geometry"),
                row("identifier", "International ISBN: 9787030252319"),
            ]
        )
        + "<div>Related books and recommendations must not enter ISBN</div>"
    )
    d = module._parse_detail_html(html)
    assert d.title == "Geometry test volume" and d.authors == ["Example Author"]
    assert d.publisher == "Example Press" and d.year == "2009"
    assert d.isbn == "9787030252319" and d.language == "Chinese"
    assert d.subjects == ["Geometry"]


def test_disappearing_result_list_is_not_a_confirmed_empty_page(browser):
    browser.page.query_selector.side_effect = None
    browser.page.query_selector.return_value = None
    with pytest.raises(module.LibraryError, match="disappeared"):
        module.search("geometry")


def test_missing_playwright_is_an_explicit_dependency_error(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(module.LibraryError, match=r"requires the \[playwright\] extra"):
        module._playwright_page()


def test_browser_startup_failure_is_bounded_and_releases_runtime(monkeypatch):
    from types import ModuleType
    import sys

    fake = ModuleType("playwright.sync_api")
    pw = Mock()
    pw.chromium.launch.side_effect = RuntimeError("private ticket=ST-PRIVATE")
    fake.sync_playwright = Mock(return_value=SimpleNamespace(start=lambda: pw))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    with pytest.raises(module.LibraryError) as caught:
        module._playwright_page()
    assert "startup failed" in str(caught.value) and "ST-PRIVATE" not in str(caught.value)
    pw.stop.assert_called_once()


def test_timeout_waits_for_rendered_titles_before_reading_rows(browser):
    browser.page.wait_for_function.side_effect = TimeoutError("titles did not render")
    with pytest.raises(module.LibraryError, match="TimeoutError"):
        module.search("geometry")
    browser.page.query_selector_all.assert_not_called()


def test_pagination_is_applied_to_actual_primo_request_without_losing_filters():
    from urllib.parse import urlsplit, parse_qs

    page = Mock()
    module._apply_search_window(page, offset=10, limit=25)
    pattern, handler = page.route.call_args.args
    assert pattern == module.PRIMO_BASE + "/primaws/rest/pub/pnxs?*"
    route = Mock()
    route.request.url = (
        module.PRIMO_BASE
        + "/primaws/rest/pub/pnxs?q=any%2Ccontains%2Cgeometry&scope=MyInstitution&offset=0&limit=10&facet=rtype%2Cinclude%2Cbooks&facet=lang%2Cinclude%2Ceng"
    )
    handler(route)
    url = urlsplit(route.continue_.call_args.kwargs["url"])
    params = parse_qs(url.query)
    assert params["offset"] == ["10"] and params["limit"] == ["25"]
    assert params["scope"] == ["MyInstitution"] and params["q"] == ["any,contains,geometry"]
    assert params["facet"] == ["rtype,include,books", "lang,include,eng"]


def test_empty_page_beyond_last_record_uses_api_receipt_not_missing_dom(browser):
    browser.api.json.return_value = {"docs": [], "info": {"total": 9}}
    assert module.search("geometry", offset=10, limit=2) == []
    browser.page.wait_for_selector.assert_not_called()


@pytest.mark.parametrize(
    "payload", [{"docs": []}, {"info": {"total": 0}}, {"docs": None, "info": {"total": 0}}]
)
def test_incomplete_api_response_cannot_be_zero_results(browser, payload):
    browser.api.json.return_value = payload
    with pytest.raises(module.LibraryError, match="incomplete data"):
        module.search("geometry")


def test_nonempty_api_with_empty_dom_is_not_a_successful_empty_read(browser):
    with pytest.raises(module.LibraryError, match="read incomplete"):
        module.search("geometry")
