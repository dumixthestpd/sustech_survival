"""sustech_survival.lib.search — SUSTech Library Primo book/article search.

Authentication uses the shared CAS provider and a session-scoped TLS adapter
that supports both direct and proxy connections. Playwright renders Primo's
JavaScript search/detail pages. Read failures raise LibraryError; only a
confirmed empty search window returns an empty list.

Public API:

    from sustech_survival.lib.search import search, detail

    results = search("aspirin", scope="catalog", limit=10)
    for r in results:
        print(f"{r.rank}. {r.title} [{r.format}]  full_text={r.full_text}")
        print(f"   {r.detail_url}")

    full = detail(results[0].docid)
    print(full.title, full.authors, full.publisher, full.year, full.subjects)

CLI:

    python -m sustech_survival.lib.search "aspirin"
    python -m sustech_survival.lib.search --detail "cdi_proquest_miscellaneous_1901310093"
"""
from __future__ import annotations
from .. import _net

import re
import contextlib
import sys
import urllib.parse
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Lazy imports inside functions to keep this module import-clean
# (Playwright is a heavy optional dep — only loaded when search() is called).

# -- Data classes ----------------------------------------------------------


@dataclass
class SearchResult:
    """One row from a Primo search results page.

    All fields are best-effort — Primo sometimes doesn't expose a
    particular field (e.g., no ISBN on a journal article), in which
    case the field is empty string.
    """
    rank: int
    title: str = ""
    format: str = ""              # 文章 (article) / 图书 (book) / etc.
    detail_url: str = ""
    docid: str = ""               # extracted from detail_url (?docid=...)
    full_text: bool = False
    peer_reviewed: bool = False
    snippet: str = ""             # the brief description line


@dataclass
class BookDetail:
    """Full metadata for a single Primo record (from the detail page).

    Matches what Primo's brief-result / full-view components render.
    Field names follow the on-page labels where possible (English +
    Chinese, since the library uses both).
    """
    title: str = ""
    format: str = ""
    authors: List[str] = field(default_factory=list)
    publisher: str = ""
    year: str = ""
    language: str = ""
    subjects: List[str] = field(default_factory=list)
    abstract: str = ""
    isbn: str = ""
    full_text_availability: str = ""  # raw text of the availability section
    online_url: str = ""
    detail_url: str = ""


class LibraryError(RuntimeError):
    """Authentication, browser or Primo read failed; never an empty result."""


PRIMO_BASE = "https://sustc.primo.exlibrisgroup.com.cn"
RESULT_SELECTOR = "prm-brief-result-container, .list-item-primary-content.result-item-primary-content"
EMPTY_SELECTOR = "prm-no-search-result, .no-results, .no-results-container"


# -- Internal helpers ------------------------------------------------------


def _ensure_auth():
    """Lazy-import CAS auth; diagnostics go to stderr, never JSON stdout."""
    from sustech_survival.sso import LibAuth
    auth = LibAuth()
    with contextlib.redirect_stdout(sys.stderr):
        ok, reason = auth.ensure()
    return auth, ok, reason


def _build_search_url(
    *,
    # Query
    query: Optional[str] = None,             # single-field shortcut: `any,contains,<query>`
    queries: Optional[List[Tuple[str, str, str]]] = None,  # multi-field: [(field, operator, value), ...]
    # Filters
    scope: str = "catalog",
    material_types: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    languages: Optional[List[str]] = None,
    peer_reviewed: bool = False,
    full_text_online: bool = False,
    date_from: Optional[str] = None,        # e.g. "2018" or "2018-01"
    date_to: Optional[str] = None,
    # Display
    limit: int = 10,
    offset: int = 0,
    sort_by: str = "relevance",             # relevance | date | title | author
    lang: str = "zh_CN",                    # interface language
    mode: str = "basic",                    # basic | advanced
    display_mode: str = "full",
    highlight: bool = True,
    pc_availability_mode: bool = True,
) -> str:
    """Build the Primo NG search URL with the full parameter surface.

    The URL params map to the standard Primo discovery/search endpoint.
    Multi-field queries are encoded as
    "field1,op1,value1;field2,op2,value2;..."  — Primo's URL query syntax
    is `field,operator,value` per term joined by `;`.

    Args:
        query: convenience — single-field query as `any,contains,<query>`.
            Use either `query` OR `queries`, not both.
        queries: list of (field, operator, value) tuples for combined
            search across fields. Fields: any, title, creator, subject,
            publisher, isbn, issn, description, date, lang, callNumber, doi.
            Operators: contains, exact, beginsWith, etc.
        scope: catalog (全部资源), eresource (电子资源), default (纸本书目)
        material_types: rtype filter. Values: Article, Book, Journal,
            Newspaper, Audio, Video, Database, Reference, etc.
        libraries: physical library filter. Values: 86SUSTC_MAIN,
            琳恩图书馆, 一丹图书馆, etc.
        languages: publication language filter. Values: eng, chi, jpn, etc.
        peer_reviewed: only peer-reviewed items (tlevel filter)
        full_text_online: only items with online full text available
            (pcAvailability filter — Note: pcAvailabiltyMode typo is in
            Primo's URL — kept verbatim)
        date_from, date_to: publication date range, "YYYY" or "YYYY-MM" form
        limit: bulkSize (results per page)
        offset: pagination start position (0-based)
        sort_by: relevance | date | title | author
        lang: interface language (zh_CN, en)
        mode: basic | advanced
        display_mode: full | brief
    """
    # Multi-field query: build the "field,op,value;field,op,value" string.
    if queries is not None and query is None:
        query_str = ";".join(
            f"{field},{op},{val}" for field, op, val in queries
        )
    elif query is not None:
        query_str = f"any,contains,{query}"
    else:
        raise ValueError("provide either `query` (single) or `queries` (multi-field)")

    # Map our enum values to Primo's URL values.
    scope_map = {
        "catalog": "MyInst_and_CI",
        "eresource": "CentralIndex",
        "default": "MyInstitution",
    }
    sort_map = {
        "relevance": "rank",
        "date": "date_desc",
        "title": "title_asc",
        "author": "creator_asc",
    }

    params = {
        "vid": "86SUSTC_INST:86SUSTC",
        "lang": lang,
        "tab": "Everything",
        "search_scope": scope_map.get(scope, "MyInst_and_CI"),
        "mode": mode,
        "displayMode": display_mode,
        "bulkSize": str(limit),
        "highlight": "true" if highlight else "false",
        "dum": "true",
        "query": query_str,
        "displayField": "all",
        "pcAvailabiltyMode": "true" if pc_availability_mode else "false",
        "sortby": sort_map.get(sort_by, "rank"),
        "offset": str(offset),
    }

    # Filter params use Primo's facet syntax: facet=<name>,include=<values>.
    if material_types:
        params["facet"] = params.get("facet", "") + "rtype,include,"
        # Primo accepts comma-separated values inside facet: facet=rtype,include,Article,Book
        params["facet"] = "rtype,include," + ",".join(material_types) + ";" + params["facet"].lstrip("rtype,include,")
        # Cleaner: build facets dict separately (below)
        params.pop("facet")  # we'll rebuild from facets dict below
    # NOTE: Primo URL facet format is `facet=rtype,include,Article,Book&facet=library,include,...`
    # Use a dict that supports duplicate keys — we'll emit multiple facet= params.

    base = f"{PRIMO_BASE}/discovery/search"
    qs = urllib.parse.urlencode(params)

    # Add duplicate-key facet params (urllib.urlencode drops dup keys).
    facet_parts = []
    if material_types:
        facet_parts.append(("facet", "rtype,include," + ",".join(material_types)))
    if libraries:
        facet_parts.append(("facet", "library,include," + ",".join(libraries)))
    if languages:
        facet_parts.append(("facet", "language,include," + ",".join(languages)))
    if peer_reviewed:
        facet_parts.append(("facet", "tlevel,include,peer_reviewed"))
    if full_text_online:
        facet_parts.append(("facet", "pcavailability,include,true"))
    if date_from:
        facet_parts.append(("facet", "date,include," + urllib.parse.quote(f"[{date_from} TO {date_to or '*'}]")))
    if facet_parts:
        qs += "&" + urllib.parse.urlencode(facet_parts)

    return f"{base}?{qs}"


def _extract_docid(url: str) -> str:
    m = re.search(r"[?&]docid=([^&]+)", url or "")
    return urllib.parse.unquote(m.group(1)) if m else ""


def _playwright_page(*, headless=True):
    """Launch the read-only Primo renderer; report missing dependencies clearly."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise LibraryError(
            "Library search requires the [playwright] extra and Chromium: "
            "python -m pip install 'sustech_survival[playwright]'; "
            "python -m playwright install chromium"
        ) from None
    pw = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=headless)
        return pw, browser.new_context()
    except Exception as exc:
        if pw is not None:
            pw.stop()
        raise LibraryError(
            f"Library browser startup failed ({type(exc).__name__}); "
            "run python -m playwright install chromium"
        ) from None


def _copy_cookies(auth, ctx):
    """Preserve each cookie's actual domain instead of assigning .sustech.edu.cn."""
    cookies = []
    for cookie in auth.session.cookies:
        if not cookie.value or not cookie.domain:
            continue
        item = {
            "name": cookie.name, "value": cookie.value,
            "domain": cookie.domain, "path": cookie.path or "/",
            "secure": cookie.secure,
        }
        if cookie.expires is not None:
            item["expires"] = cookie.expires
        cookies.append(item)
    if cookies:
        ctx.add_cookies(cookies)


def _apply_search_window(page, *, offset, limit):
    """Primo resets deep-link offsets; apply the window to its actual read API."""
    def window(route):
        url = urllib.parse.urlsplit(route.request.url)
        params = [
            (key, value) for key, value in urllib.parse.parse_qsl(url.query, keep_blank_values=True)
            if key not in {"offset", "limit"}
        ]
        params.extend([("offset", str(offset)), ("limit", str(limit))])
        route.continue_(url=urllib.parse.urlunsplit(
            url._replace(query=urllib.parse.urlencode(params))
        ))

    page.route(f"{PRIMO_BASE}/primaws/rest/pub/pnxs?*", window)


def _search_response(page, url):
    """Confirm the requested window using Primo's own search response."""
    def matches(response):
        target = urllib.parse.urlsplit(response.url)
        return target.hostname == urllib.parse.urlsplit(PRIMO_BASE).hostname and target.path == "/primaws/rest/pub/pnxs"

    with page.expect_response(matches, timeout=_net.page_timeout_ms("library")) as pending:
        response = page.goto(url, wait_until="domcontentloaded", timeout=_net.page_timeout_ms("library"))
        _check_page(page, response)
    api = pending.value
    if api.status != 200:
        raise LibraryError(f"Primo search API returned HTTP {api.status}")
    try:
        data = api.json()
    except Exception:
        raise LibraryError("Primo search API returned invalid JSON") from None
    if (
        not isinstance(data, dict) or not isinstance(data.get("docs"), list)
        or not isinstance(data.get("info"), dict)
        or not isinstance(data["info"].get("total"), (int, float))
    ):
        raise LibraryError("Primo search API returned incomplete data")
    return len(data["docs"])


def _read_error(operation, exc):
    network = re.search(r"net::ERR_[A-Z_]+", str(exc))
    method = re.match(r"(?:BrowserContext|Page|Locator|Browser)\.[a-z_]+", str(exc))
    detail = network.group(0) if network else method.group(0) if method else type(exc).__name__
    return LibraryError(f"Primo {operation} failed ({detail})")


def _check_page(page, response):
    if response is not None and response.status >= 400:
        raise LibraryError(f"Primo page returned HTTP {response.status}")
    host = urllib.parse.urlsplit(page.url).hostname or ""
    if host == "cas.sustech.edu.cn" or page.query_selector(
        'input[name="captcha"], .g-recaptcha, .h-captcha, input[name="otp"]'
    ):
        raise LibraryError("Primo redirected to login or an interactive challenge; stopped")


# -- Public API ------------------------------------------------------------


def search(query: Optional[str] = None, *,
           # Multi-field alternative to `query`
           queries: Optional[List[Tuple[str, str, str]]] = None,
           # Filters
           scope: str = "catalog",
           material_types: Optional[List[str]] = None,
           libraries: Optional[List[str]] = None,
           languages: Optional[List[str]] = None,
           peer_reviewed: bool = False,
           full_text_online: bool = False,
           date_from: Optional[str] = None,
           date_to: Optional[str] = None,
           # Display
           limit: int = 10, offset: int = 0,
           sort_by: str = "relevance",
           lang: str = "zh_CN",
           headless: bool = True) -> List[SearchResult]:
    """Search Primo for `query` (or multi-field `queries`), with full filter + display surface.

    Use either `query` (single-field shortcut `any,contains,<term>`) or
    `queries` (list of `(field, operator, value)` tuples for combined
    multi-field search). See `_build_search_url()` for the full field list.

    Args:
        query: single-field search term (any,contains,<query>)
        queries: list of (field, operator, value) for multi-field search
        scope: catalog (全部资源) | eresource (电子资源) | default (纸本书目)
        material_types: filter to these resource types (e.g. ["Book","Article"])
        libraries: filter to these physical libraries (e.g. ["琳恩图书馆"])
        languages: filter to these publication languages (e.g. ["eng","chi"])
        peer_reviewed: only peer-reviewed items
        full_text_online: only items with online full text available
        date_from, date_to: publication date range, "YYYY" or "YYYY-MM" form
        limit: bulkSize (results per page)
        offset: pagination start position (0-based)
        sort_by: relevance | date | title | author
        lang: interface language (zh_CN, en)
        headless: Playwright headless flag

    Returns:
        list of SearchResult, ordered by `sort_by` ranking.
        Empty list only for a confirmed empty search window. Failures raise LibraryError.

    Example:
        >>> results = search("electrochromic polymer", limit=25)
        >>> for r in results:
        ...     print(f"{r.rank}. {r.title} [{r.format}]  full={r.full_text}")

        >>> # Multi-field: author "Smith" AND title "polymer"
        >>> results = search(
        ...     queries=[("creator", "contains", "Smith"),
        ...               ("title", "contains", "polymer")],
        ...     peer_reviewed=True, sort_by="date",
        ... )

        >>> # Books only, in English, from the 琳恩图书馆, page 2
        >>> page2 = search(
        ...     queries=[("any", "contains", "aspirin")],
        ...     material_types=["Book"], languages=["eng"],
        ...     libraries=["琳恩图书馆"], offset=10, limit=10,
        ... )
    """
    if query is None and queries is None:
        raise ValueError("provide either `query` or `queries`")
    if limit < 1 or offset < 0:
        raise ValueError("limit must be positive and offset nonnegative")

    auth, ok, reason = _ensure_auth()
    if not ok:
        raise LibraryError(reason or "Library authentication failed")
    pw, ctx = _playwright_page(headless=headless)

    results: List[SearchResult] = []
    try:
        _copy_cookies(auth, ctx)
        page = ctx.new_page()
        _apply_search_window(page, offset=offset, limit=limit)
        url = _build_search_url(
            query=query, queries=queries, scope=scope,
            material_types=material_types, libraries=libraries,
            languages=languages, peer_reviewed=peer_reviewed,
            full_text_online=full_text_online,
            date_from=date_from, date_to=date_to,
            limit=limit, offset=offset, sort_by=sort_by,
            lang=lang,
        )
        expected_count = _search_response(page, url)
        if expected_count == 0:
            return []
        page.wait_for_selector(
            f"{RESULT_SELECTOR}, {EMPTY_SELECTOR}", timeout=_net.page_timeout_ms("library")
        )
        _check_page(page, None)
        # Angular inserts wrappers/hrefs before all highlighted titles render.
        page.wait_for_function(
            """limit => {
                let rows = [...document.querySelectorAll(
                    '.list-item-primary-content.result-item-primary-content')];
                if (!rows.length) rows = [...document.querySelectorAll('prm-brief-result-container')];
                if (!rows.length) return [...document.querySelectorAll(
                    'prm-no-search-result, .no-results, .no-results-container'
                )].some(node => node.getClientRects().length);
                return rows.slice(0, limit).every(row => {
                    const a = row.querySelector('.item-title a');
                    return a && a.textContent.trim() && a.href.includes('docid=');
                });
            }""",
            arg=limit, timeout=_net.page_timeout_ms("library"),
        )
        items = page.query_selector_all(".list-item-primary-content.result-item-primary-content")
        if not items:
            items = page.query_selector_all("prm-brief-result-container")
        if not items:
            empty = page.query_selector(EMPTY_SELECTOR)
            if empty is None or not empty.is_visible():
                raise LibraryError("Primo result list disappeared without a no-results state")
        if len(items) < min(expected_count, limit):
            raise LibraryError("Primo rendered fewer records than its search response; read incomplete")
        for rank, item in enumerate(items[:limit], start=offset + 1):
            title_el = item.query_selector(".item-title a")
            title = ""
            if title_el:
                title = title_el.inner_text().strip()
                if not title:
                    title = re.sub(r"^[;\s]+", "", title_el.text_content() or "")
            detail_url = urllib.parse.urljoin(page.url, title_el.get_attribute("href") or "") if title_el else ""
            if not title or not _extract_docid(detail_url):
                raise LibraryError("Primo result is missing its title or record ID")
            type_el = item.query_selector(".media-content-type")
            fmt = type_el.inner_text().strip() if type_el else ""
            full_text = bool(item.query_selector("[class*=fulltext]"))
            peer_reviewed = bool(item.query_selector("prm-peer-reviewed"))
            snippet_el = item.query_selector(".result-item-text")
            snippet = (
                snippet_el.inner_text().strip().replace("\n", " ")
                if snippet_el else ""
            )
            results.append(SearchResult(
                rank=rank, title=title, format=fmt,
                detail_url=detail_url or "",
                docid=_extract_docid(detail_url or ""),
                full_text=full_text, peer_reviewed=peer_reviewed,
                snippet=snippet[:300],
            ))
    except LibraryError:
        raise
    except Exception as exc:
        raise _read_error("search", exc) from None
    finally:
        ctx.close()
        pw.stop()
    return results


def detail(docid: str, *, headless: bool = True) -> Optional[BookDetail]:
    """Fetch the full Primo record detail page for one docid.

    Parses keyed prm-service-details fields to extract title,
    format, authors, publisher, year, language, subjects, abstract,
    ISBN, full-text availability, and online URL.

    Args:
        docid: Primo document id (e.g. "alma991001618285104181",
            "cdi_proquest_miscellaneous_1901310093")
        headless: Playwright headless flag

    Returns:
        BookDetail. Authentication, browser and page failures raise LibraryError.
    """
    auth, ok, reason = _ensure_auth()
    if not ok:
        raise LibraryError(reason or "Library authentication failed")
    pw, ctx = _playwright_page(headless=headless)

    url = (
        f"https://sustc.primo.exlibrisgroup.com.cn/discovery/fulldisplay"
        f"?docid={urllib.parse.quote(docid, safe='')}"
        f"&vid=86SUSTC_INST:86SUSTC&lang=zh&search_scope=MyInst_and_CI&mode=basic"
    )
    out: Optional[BookDetail] = None
    try:
        _copy_cookies(auth, ctx)
        page = ctx.new_page()
        response = page.goto(url, wait_until="domcontentloaded", timeout=_net.page_timeout_ms("library"))
        _check_page(page, response)
        page.wait_for_selector(
            'prm-service-details [data-details-label="title"]',
            timeout=_net.page_timeout_ms("library"),
        )
        _check_page(page, None)
        details = page.query_selector("prm-service-details")
        out = _parse_detail_html(details.inner_html())
        fmt = page.query_selector("prm-full-view .media-content-type")
        out.format = fmt.inner_text().strip() if fmt else ""
        if not out.title:
            raise LibraryError("Primo detail has no readable record title")
        out.detail_url = url
        # Online URL: look for any '在线查看' link href.
        link_el = page.query_selector("a[href*='doi.org'], a.online, [class*=online-viewit]")
        if link_el:
            out.online_url = link_el.get_attribute("href") or ""
    except LibraryError:
        raise
    except Exception as exc:
        raise _read_error("detail", exc) from None
    finally:
        ctx.close()
        pw.stop()
    return out


def _parse_detail_html(html: str) -> BookDetail:
    """Read stable detail field keys; translated labels and nearby widgets vary."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for hidden in soup.select('[aria-hidden="true"], .ng-hide, button'):
        hidden.decompose()
    fields = {}
    for label in soup.select("[data-details-label]"):
        row = label.parent.parent
        values = [
            node.get_text(" ", strip=True)
            for node in row.select('.item-details-element-container [role="listitem"]')
        ]
        fields[label["data-details-label"]] = list(dict.fromkeys(v for v in values if v))

    def text(*keys):
        return "; ".join(value for key in keys for value in fields.get(key, []))

    identifiers = text("isbn", "identifier")
    isbn = re.findall(r"(?<![\d-])(?:97[89][\d-]{10,14}|[\d-]{9,12}[\dXx])(?![\d-])", identifiers)
    return BookDetail(
        title=text("title"),
        authors=fields.get("creator", []),
        publisher=text("publisher"),
        year=text("creationdate", "date"),
        language=text("language"),
        subjects=fields.get("subject", []),
        abstract=text("description"),
        isbn="; ".join(isbn),
    )


# -- CLI -------------------------------------------------------------------
# NOTE: the standalone argparse `main()` was removed 2026-08-10 during the
# CLI unification. The unified `sustech lib search ...` / `sustech lib
# detail ...` commands are defined inline in `sustech_survival/cli/main.py`
# — they wrap the Python `search()` / `detail()` API here.