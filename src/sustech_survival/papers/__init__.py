# Paper Research Tool — unified workflow
#
# Usage:
#   from sustech_survival.sso.authlib.papers import research
#   results = research.search_and_fetch(["electrochromic WPU"], dest_dir="papers/")
#
# Or use individual modules:
#   from sustech_survival.sso.authlib.papers import search, fetch, openaccess
#   papers = search.crossref_search("electrochromic polymer", max_results=10)
#   fetch.fetch_batch(papers, dest_dir="papers/")

import json
from pathlib import Path
from typing import Optional

from .search import crossref_search, search_multi
from .fetch import fetch_pdf, fetch_batch, save_manifest
from .openaccess import resolve_oa_pdf
from .models import Paper


def search_and_fetch(
    queries: list[str],
    dest_dir: str | Path,
    max_per_query: int = 15,
    fetch_pdfs: bool = True,
    openaccess_only: bool = False,
    min_year: Optional[int] = None,
) -> list[Paper]:
    """
    Full workflow: search CrossRef → resolve OA PDFs → download PDFs → save manifest.

    Args:
        queries: List of search query strings
        dest_dir: Local directory to save PDFs and manifest
        max_per_query: Max results per query
        fetch_pdfs: If True, download OA PDFs. If False, just search.
        openaccess_only: If True, only return OA papers. If False, return all.
        min_year: Filter by minimum publication year

    Returns:
        List of Paper objects with metadata + pdf_path populated
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Search
    papers = search_multi(queries, max_per_query=max_per_query, min_year=min_year)

    # Filter OA if requested
    if openaccess_only:
        papers = [p for p in papers if p.oa_status]

    # Filter by year if requested
    if min_year:
        papers = [p for p in papers if p.year and p.year >= min_year]

    # Step 2: Fetch PDFs
    if fetch_pdfs:
        fetch_batch(papers, dest_dir)

        # Update pdf_path in papers objects
        for paper in papers:
            fname = f"{paper.year or 'unknown'}_{paper.title[:50].replace('/', '-').replace(':', '-')[:60].replace(' ', '_')}.pdf"
            pdf_path = dest_dir / fname
            if pdf_path.exists():
                paper.pdf_path = str(pdf_path)

    # Step 3: Save manifest
    save_manifest(papers, dest_dir)

    return papers


def load_manifest(dest_dir: str | Path) -> list[Paper]:
    """Load previously saved papers from manifest."""
    manifest_path = Path(dest_dir) / "papers_manifest.json"
    if not manifest_path.exists():
        return []
    data = json.loads(manifest_path.read_text())
    return [Paper.from_dict(d) for d in data]


def print_results(papers: list[Paper], show_pdf: bool = True) -> None:
    """Print papers in a readable format."""
    print(f"\n{'='*80}")
    print(f"  {len(papers)} papers found")
    print(f"{'='*80}")
    for i, p in enumerate(papers, 1):
        oa_icon = "🔓" if p.oa_status else "🔒"
        year_str = str(p.year) if p.year else "?"
        title_trunc = p.title[:75]
        authors_str = p.authors_str
        print(f"\n[{i}] {oa_icon} [{year_str}] {title_trunc}")
        print(f"     Authors: {authors_str}")
        print(f"     Journal: {p.journal or '?'} | Citations: {p.citations}")
        print(f"     DOI: {p.doi or 'n/a'}")
        if p.pdf_url:
            print(f"     OA PDF: {p.pdf_url[:80]}")
        if p.pdf_path:
            print(f"     Saved: {p.pdf_path}")


# Convenience aliases
search = crossref_search
fetch = fetch_pdf
fetch_all = fetch_batch