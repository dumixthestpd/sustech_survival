"""Offline regressions for availability-aware BB content discovery."""

import importlib
import socket

import pytest
from requests import HTTPError


ROOT = "/learn/api/public/v1/courses/_9_1/contents"


def item(number, *, available="Yes", children=False, title=None):
    return {
        "id": f"_{number}_1", "title": title or f"Content {number}",
        "hasChildren": children, "availability": {"available": available},
        "contentHandler": {"id": "resource/x-bb-folder" if children else "resource/x-bb-file"},
    }


@pytest.fixture
def discovery(monkeypatch, tmp_path):
    monkeypatch.setenv("SUSTECH_HOME", str(tmp_path))
    monkeypatch.setenv("SUSTECH_CREDENTIALS", str(tmp_path / "absent-credentials"))

    def forbid_network(*args, **kwargs):
        raise AssertionError("external network forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    query = importlib.import_module("sustech_survival.bb.query")
    cache = importlib.import_module("sustech_survival.bb._cache")
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    sess = object()
    authentications = []
    calls = []
    routes = {}

    def session():
        authentications.append(True)
        return sess

    def api(path, session=None):
        assert session is sess
        calls.append(path)
        response = routes[path]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(query, "_session", session)
    monkeypatch.setattr(query, "api", api)
    return query, cache, routes, calls, authentications


def test_hidden_folders_and_files_never_reach_children_or_detail(discovery, monkeypatch, capsys):
    query, _, routes, calls, _ = discovery
    routes[ROOT] = {"results": [item(1, available="No", children=True),
                                item(2, children=True, title="Lectures")]}
    routes[ROOT + "/_2_1/children"] = {"results": [item(3, available="No"), item(4)]}
    scraped = []
    monkeypatch.setattr(query, "discover_courses", lambda: [("9", "Course")])
    monkeypatch.setattr(query.time, "sleep", lambda _: None)

    def scrape(content_id, course_id, course_name):
        scraped.append(content_id)
        return [{"id": content_id, "type": "file"}]

    monkeypatch.setattr(query, "scrape_page_items", scrape)
    result = query.discover_all_items(refresh=True)
    assert {row["id"] for row in result} == {"2", "4"}
    assert scraped == ["2", "4"]
    assert calls == [ROOT, ROOT + "/_2_1/children"]
    assert "2 content item(s) marked unavailable" in capsys.readouterr().err


@pytest.mark.parametrize("availability", [None, {}, {"available": "Yes"},
    {"available": "PartiallyVisible"}, {"available": False}, "No"])
def test_ambiguous_availability_is_not_filtered(discovery, availability):
    query, _, routes, calls, _ = discovery
    folder = item(1, children=True)
    folder["availability"] = availability
    routes[ROOT] = {"results": [folder]}
    routes[ROOT + "/_1_1/children"] = {"results": [item(2)]}
    assert [row[0] for row in query.walk_contents("9")] == ["1", "2"]
    assert calls == [ROOT, ROOT + "/_1_1/children"]


def test_refresh_detects_newly_available_folder_without_modified_timestamp(discovery):
    query, _, routes, calls, _ = discovery
    folder = item(1, available="No", children=True)
    folder["modified"] = "2026-01-01T00:00:00Z"
    routes[ROOT] = {"results": [folder]}
    assert query.discover_pages("9", refresh=True) == []
    folder["availability"]["available"] = "Yes"
    routes[ROOT + "/_1_1/children"] = {"results": [item(2)]}
    assert [row[0] for row in query.discover_pages("9", refresh=True)] == ["1", "2"]
    assert calls.count(ROOT) == 2


def test_single_root_read_pagination_and_nested_sections_share_session(discovery):
    query, _, routes, calls, authentications = discovery
    routes[ROOT] = {"results": [item(1, children=True, title="Lectures")],
                    "paging": {"nextPage": ROOT + "?offset=1"}}
    routes[ROOT + "?offset=1"] = {"results": [item(4, available="No", children=True)]}
    routes[ROOT + "/_1_1/children"] = {"results": [item(2, children=True)]}
    routes[ROOT + "/_2_1/children"] = {"results": [item(3)]}
    rows = query.discover_pages("9", refresh=True)
    assert rows == [("1", "Lectures", ""), ("2", "Content 2", "Lectures"),
                    ("3", "Content 3", "Lectures")]
    assert calls.count(ROOT) == 1
    assert len(authentications) == 1
    assert ROOT + "?offset=1" in calls
    # Preserve the existing public tuple's BB-formatted parent ID.
    assert list(query.walk_contents("9"))[1][4] == "_1_1"


def test_old_discovery_cache_is_not_reused_and_new_cache_keeps_notice(discovery, capsys):
    query, cache, routes, calls, _ = discovery
    cache.set("discover_pages", [("1", "Hidden", "")], "9")
    routes[ROOT] = {"results": [item(1, available="No", children=True), item(2)]}
    assert [row[0] for row in query.discover_pages("9")] == ["2"]
    assert len(calls) == 1
    capsys.readouterr()
    assert [row[0] for row in query.discover_pages("9")] == ["2"]
    assert len(calls) == 1
    assert "1 content item(s) marked unavailable" in capsys.readouterr().err
    cache.invalidate_all("discover_pages_9")
    assert query.discover_pages("9")
    assert len(calls) == 2


@pytest.mark.parametrize("failure", [HTTPError("403 Forbidden"), {"unexpected": []}])
def test_failed_discovery_is_not_cached_as_empty_or_partial(discovery, failure):
    query, cache, routes, _, _ = discovery
    routes[ROOT] = {"results": [item(1, children=True)]}
    routes[ROOT + "/_1_1/children"] = failure
    with pytest.raises((HTTPError, ValueError)):
        query.discover_pages("9", refresh=True)
    assert cache.get("discover_pages", "9", "availability_v1")[1] is False


@pytest.mark.parametrize("next_page", [ROOT, "https://example.com/contents"])
def test_unsafe_or_looping_pagination_is_rejected(discovery, next_page):
    query, _, routes, calls, _ = discovery
    routes[ROOT] = {"results": [], "paging": {"nextPage": next_page}}
    with pytest.raises(ValueError):
        list(query.walk_contents("9"))
    assert calls == [ROOT]
