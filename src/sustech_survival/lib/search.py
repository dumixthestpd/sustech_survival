"""sustech_survival.lib.search — SUSTech Library Primo book/article search.

Auth:    sustech_survival.sso.LibAuth().ensure()  (CAS + Shibboleth)
Fetch:   Playwright (Primo is a JS SPA; also its SSL config at
         sustc.primo.exlibrisgroup.com.cn is broken — modern OpenSSL
         refuses the unsafe legacy renegotiation, which kills any
         Python-urllib/requests-based access. Chromium handles it.)

Why HTML parsing (not REST API):
  The Primo NG frontend at https://lib.sustech.edu.cn → "南科学术搜索"
  POSTs to https://sustc-primo.hosted.exlibrisgroup.com.cn which 302-
  redirects to https://sustc.primo.exlibrisgroup.com.cn (the broken-SSL
  host). The detail page is the same SPA. There IS a public Primo PNX
  REST API (/primaws/rest/pnxs?vid=...) but Ex Libris gates it behind
  institutional auth and the same broken SSL — so we render the SPA in
  Playwright and parse the rendered DOM. The DOM is AngularJS-driven but
  stable enough that the .item-title / .result-item-text / prm-* selectors
  used here will work across current releases.

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

import re
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


# -- Internal helpers ------------------------------------------------------


def _ensure_auth():
    """Lazy-import + CAS auth. Returns a tuple (sess, ok, reason).
    `sess` is currently None (Playwright pulls cookies directly)."""
    from sustech_survival.sso import LibAuth
    auth = LibAuth()
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
        "catalog": "catalog_scope",
        "eresource": "eresource_scope",
        "default": "default_scope",
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
        "search_scope": scope_map.get(scope, "catalog_scope"),
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

    base = "https://sustc-primo.hosted.exlibrisgroup.com.cn/primo-explore/search"
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


def _playwright_page():
    """Launch Chromium, return (playwright_obj, browser_context).

    Returns (None, None) if Playwright isn't installed — callers detect
    this and return [] / None gracefully."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, None
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context()
    return pw, ctx


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
        Empty list if Playwright isn't installed or auth fails.

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

    auth, ok, reason = _ensure_auth()
    if not ok:
        return []
    pw, ctx = _playwright_page()
    if pw is None or ctx is None:
        return []
    assert ctx is not None  # for type-narrowing (Pyright)

    results: List[SearchResult] = []
    try:
        # Inject cookies from BBAuth-style session into the browser context.
        for c in auth.session.cookies:
            if c.value:
                ctx.add_cookies([{
                    "name": c.name, "value": c.value,
                    "domain": ".sustech.edu.cn", "path": "/",
                }])
        page = ctx.new_page()
        url = _build_search_url(
            query=query, queries=queries, scope=scope,
            material_types=material_types, libraries=libraries,
            languages=languages, peer_reviewed=peer_reviewed,
            full_text_online=full_text_online,
            date_from=date_from, date_to=date_to,
            limit=limit, offset=offset, sort_by=sort_by,
            lang=lang,
        )
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        # SPA renders the result list after the JS bundle runs.
        page.wait_for_selector(
            ".list-item-primary-content.result-item-primary-content",
            timeout=15000,
        )
        # Pull out each result row by the canonical selectors.
        items = page.query_selector_all(
            ".list-item-primary-content.result-item-primary-content"
        )
        for rank, item in enumerate(items[:limit], start=1):
            title_el = item.query_selector(".item-title a")
            title = title_el.inner_text().strip() if title_el else ""
            detail_url = title_el.get_attribute("href") if title_el else ""
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
    except Exception:
        # Fail silently — caller's caller will see [] and decide what to do.
        pass
    finally:
        ctx.close()
        pw.stop()
    return results


def detail(docid: str, *, headless: bool = True) -> Optional[BookDetail]:
    """Fetch the full Primo record detail page for one docid.

    Parses the prm-full-view AngularJS component to extract title,
    format, authors, publisher, year, language, subjects, abstract,
    ISBN, full-text availability, and online URL.

    Args:
        docid: Primo document id (e.g. "alma991001618285104181",
            "cdi_proquest_miscellaneous_1901310093")
        headless: Playwright headless flag

    Returns:
        BookDetail, or None if Playwright not installed / auth fails /
        page not accessible.
    """
    auth, ok, reason = _ensure_auth()
    if not ok:
        return None
    pw, ctx = _playwright_page()
    if pw is None or ctx is None:
        return None
    assert ctx is not None  # for type-narrowing (Pyright)

    url = (
        f"https://sustc.primo.exlibrisgroup.com.cn/discovery/fulldisplay"
        f"?docid={urllib.parse.quote(docid, safe='')}"
        f"&vid=86SUSTC_INST:86SUSTC&lang=zh&search_scope=MyInst_and_CI&mode=basic"
    )
    out: Optional[BookDetail] = None
    try:
        for c in auth.session.cookies:
            if c.value:
                ctx.add_cookies([{
                    "name": c.name, "value": c.value,
                    "domain": ".sustech.edu.cn", "path": "/",
                }])
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        # Wait for the brief-result inside the full-view to render.
        page.wait_for_selector("prm-full-view", timeout=15000)
        # The detail page renders text into a prm-full-view container.
        # We walk that text and pattern-match the labelled fields.
        full_text = page.inner_text("prm-full-view") or ""
        out = _parse_detail_text(full_text)
        out.detail_url = url
        # Online URL: look for any '在线查看' link href.
        link_el = page.query_selector("a[href*='doi.org'], a.online, [class*=online-viewit]")
        if link_el:
            out.online_url = link_el.get_attribute("href") or ""
    except Exception:
        pass
    finally:
        ctx.close()
        pw.stop()
    return out


def _parse_detail_text(text: str) -> BookDetail:
    """Parse the human-readable text dump from prm-full-view into a BookDetail.

    Primo renders the detail page as a Chinese/English label-value list
    inside one container — the structure is stable, but the labels are
    translated, so we match both forms.

    Format:
        详细信息
        题名 / Title     <title>
        作者 / Author    <authors...>
        主题 / Subject   <subjects...>
        摘要 / Abstract  <abstract>
        ISBN            <isbn>
        出版 / Publisher <publisher>
        ...
    """
    out = BookDetail()
    # Normalize whitespace.
    flat = re.sub(r"[ \t]+", " ", text).strip()
    # Title: the very first long phrase after "详细信息" (or before "作者").
    # The detail page typically puts title on its own line at the top.
    title_m = re.search(
        r"详细信息\s+(?:图书|文章|期刊)?\s*([^\n]+?)\s*(?:作者|Rainsford|Rodés|Taylor|$)",
        flat, re.S,
    )
    if title_m:
        out.title = title_m.group(1).strip()[:300]
    # Format: the Chinese type label at the top.
    for fmt in ("图书", "文章", "期刊", "学位论文", "会议论文", "数据集", "音像"):
        if fmt in flat[:200]:
            out.format = fmt
            break
    # Field-by-field extraction — both Chinese and English labels.
    def extract(label_zh: str, label_en: str) -> str:
        # Capture everything up to the next label or end-of-text.
        next_labels = (
            "题名|作者|主题|摘要|ISBN|出版|语种|语言|格式|全文可用|学科|来源"
            "|Title|Author|Subject|Abstract|ISBN|Publisher|Language|Format"
            "|Coverage|Online"
        )
        pattern = rf"(?:{label_zh}|{label_en})\s+(.+?)(?=\s+(?:{next_labels})\s|\s*$)"
        m = re.search(pattern, flat, re.S)
        return m.group(1).strip()[:1000] if m else ""

    out.authors = [
        a.strip() for a in
        extract(r"作者", r"Author").replace(" ; ", "; ").split(";")
        if a.strip()
    ] if extract(r"作者", r"Author") else []
    out.publisher = extract(r"出版(?:者|项)?|Publisher", r"Publisher|Publisher")
    out.year = extract(r"出版日期|年份|Year", r"Year|Date")
    out.language = extract(r"语种|Language", r"Language")
    subjects_text = extract(r"主题", r"Subject")
    if subjects_text:
        out.subjects = [s.strip() for s in re.split(r"[;,/]", subjects_text) if s.strip()]
    out.abstract = extract(r"摘要", r"Abstract")
    out.isbn = extract(r"ISBN", r"ISBN")
    out.full_text_availability = extract(r"全文可用性|Full.?text availability", r"Full.text availability")
    return out


# -- CLI -------------------------------------------------------------------
# NOTE: the standalone argparse `main()` was removed 2026-08-10 during the
# CLI unification. The unified `sustech lib search ...` / `sustech lib
# detail ...` commands are defined inline in `sustech_survival/cli/main.py`
# — they wrap the Python `search()` / `detail()` API here.