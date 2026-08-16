# CrossRef search — query CrossRef API for paper metadata

import requests
from typing import Optional
from .models import Paper
from .openaccess import resolve_oa_pdf

CROSSREF_BASE = "https://api.crossref.org/works"
HEADERS = {"User-Agent": "sustech-research/1.0 (mailto:dumix@local)"}

# CrossRef article types we WANT (exclude reviews, book chapters, etc.)
WANTED_TYPES = {"journal-article", "proceedings-article", "posted-content"}
# Types to skip
SKIP_TYPES = {"journal-review-article", "book", "book-chapter", "proceedings-review"}


def parse_authors(authors_raw: list) -> list[str]:
    """Parse CrossRef author list robustly."""
    authors = []
    for a in authors_raw:
        family = a.get("family") or a.get("name") or ""
        given = a.get("given") or ""
        if family:
            name = f"{given} {family}".strip() if given else family
            authors.append(name)
    return authors


def crossref_search(
    query: str,
    max_results: int = 10,
    min_year: Optional[int] = None,
    openaccess_only: bool = False,
) -> list[Paper]:
    """
    Search CrossRef for papers matching query.

    Args:
        query: Search query string
        max_results: Max papers to return (CrossRef limit: 100)
        min_year: Filter to papers from this year onwards
        openaccess_only: If True, only return OA papers
    Returns:
        List of Paper objects (metadata only — no PDF downloaded yet)
    """
    params = {
        "query": query,
        "rows": min(max_results * 4, 100),
        "select": "DOI,title,author,published-print,published-online,container-title,type,is-referenced-by-count",
    }
    if min_year:
        # Filter at API level so recent papers appear in results
        params["filter"] = f"from-pub-date:{min_year}"
        params["sort"] = "relevance"
    else:
        # Without year filter, sort by citations to get most relevant papers
        params["sort"] = "is-referenced-by-count"

    r = requests.get(CROSSREF_BASE, params=params, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"CrossRef API error: {r.status_code} — {r.text[:200]}")

    items = r.json()["message"]["items"]
    papers = []

    for item in items:
        doi = item.get("DOI") or ""
        article_type = item.get("type") or ""

        # Skip book chapters and review articles
        if article_type in SKIP_TYPES:
            continue

        # Skip supplementary material entries (.s001, .s002, etc.)
        if any(doi.endswith(s) for s in [".s001", ".s002", ".s003", ".s004", ".s005"]):
            continue
        if "/suppl" in doi.lower() or "/supplementary" in doi.lower():
            continue

        # Parse year from published-print, fallback to published-online
        year_arr = item.get("published-print", {}).get("date-parts", [[None]])[0]
        year = year_arr[0] if year_arr and year_arr[0] else None
        if year is None:
            online_arr = item.get("published-online", {}).get("date-parts", [[None]])[0]
            year = online_arr[0] if online_arr and online_arr[0] else None

        # Filter by year (belt-and-suspenders since API filter handles it)
        if min_year and (not year or year < min_year):
            continue

        title = (item.get("title") or ["Untitled"])[0]
        journal = (item.get("container-title") or [None])[0]
        authors = parse_authors(item.get("author") or [])
        citations = item.get("is-referenced-by-count", 0)

        paper = Paper(
            title=title,
            doi=doi,
            authors=authors,
            journal=journal,
            year=year,
            citations=citations,
            query_used=query,
        )

        # Resolve OA status (cheap API call)
        if paper.doi:
            is_oa, pdf_url = resolve_oa_pdf(paper.doi)
            paper.oa_status = is_oa
            paper.pdf_url = pdf_url

        # Only include research articles (not just reviews)
        if article_type in WANTED_TYPES or not article_type:
            papers.append(paper)

        if len(papers) >= max_results:
            break

    return papers


def search_multi(queries: list[str], max_per_query: int = 10, min_year: Optional[int] = None) -> list[Paper]:
    """
    Run multiple queries and combine results (deduplicates by DOI).
    """
    seen = set()
    results = []
    for q in queries:
        papers = crossref_search(q, max_results=max_per_query, min_year=min_year)
        for p in papers:
            if p.doi and p.doi not in seen:
                seen.add(p.doi)
                results.append(p)
            elif not p.doi:
                results.append(p)
    return results