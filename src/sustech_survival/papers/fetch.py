# PDF fetching — download open-access PDFs

import os
import re
import time
import cloudscraper
import requests
from pathlib import Path
from typing import Optional

from .models import Paper
from .openaccess import resolve_oa_pdf

DOWNLOAD_TIMEOUT = 60
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": USER_AGENT}

# URLs known to block plain requests — use cloudscraper
CLOUDSCRAPER_HOSTS = {"mdpi.com", "wiley.com", "tandf.co.uk", "sagepub.com", "acs.org"}


def _get_scraper():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )


def _safe_filename(title: str, year: Optional[int]) -> str:
    """Create a safe filename from paper title."""
    unsafe = r'[/\\:*?"<>|]'
    safe = re.sub(unsafe, "-", title)
    safe = safe.strip()[:60].replace(" ", "_").replace("--", "-")
    year_str = str(year) if year else "unknown"
    return f"{year_str}_{safe}"


def _is_pdf_content(r: requests.Response) -> bool:
    """Check if response content is actually a PDF."""
    if r.status_code != 200:
        return False
    content_type = r.headers.get("Content-Type", "")
    if "pdf" in content_type.lower():
        return True
    # Also check magic bytes
    first_bytes = r.content[:8]
    if first_bytes.startswith(b'%PDF'):
        return True
    return False


def fetch_pdf(paper: Paper, dest_dir: str | Path, timeout: int = DOWNLOAD_TIMEOUT) -> Optional[Path]:
    """
    Download the OA PDF for a paper.

    Args:
        paper: Paper object with doi and pdf_url populated
        dest_dir: Directory to save PDF
        timeout: Download timeout in seconds

    Returns:
        Path to downloaded PDF, or None if failed
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Resolve OA if not already done
    pdf_url = paper.pdf_url
    if not pdf_url and paper.doi:
        is_oa, pdf_url = resolve_oa_pdf(paper.doi)
        if not pdf_url:
            return None

    if not pdf_url:
        return None

    filename = _safe_filename(paper.title, paper.year) + ".pdf"
    dest_path = dest_dir / filename

    # Don't re-download if already exists
    if dest_path.exists():
        return dest_path

    # Choose HTTP client based on host
    host = paper.pdf_url.split("/")[2] if paper.pdf_url else ""
    use_cloudscraper = any(h in host for h in CLOUDSCRAPER_HOSTS)

    try:
        if use_cloudscraper:
            scraper = _get_scraper()
            r = scraper.get(pdf_url, timeout=timeout, allow_redirects=True)
        else:
            r = requests.get(pdf_url, headers=HEADERS, timeout=timeout, allow_redirects=True)

        if not _is_pdf_content(r):
            # Try alternate URL patterns for known publishers
            alt_urls = _alternate_urls(paper)
            for alt_url in alt_urls:
                alt_host = alt_url.split("/")[2]
                if any(h in alt_host for h in CLOUDSCRAPER_HOSTS):
                    scraper = _get_scraper()
                    r2 = scraper.get(alt_url, timeout=timeout, allow_redirects=True)
                else:
                    r2 = requests.get(alt_url, headers=HEADERS, timeout=timeout, allow_redirects=True)
                if _is_pdf_content(r2):
                    dest_path.write_bytes(r2.content)
                    return dest_path
            return None

        dest_path.write_bytes(r.content)
        return dest_path

    except Exception:
        return None


def _alternate_urls(paper: Paper) -> list[str]:
    """Generate alternate PDF URLs for a paper based on DOI and known publisher patterns."""
    if not paper.doi:
        return []

    doi = paper.doi
    urls = []

    # MDPI patterns
    if "10.3390" in doi:
        article_id = doi.replace("10.3390/", "")
        urls.extend([
            f"https://www.mdpi.com/{article_id}/pdf",
            f"https://www.mdpi.com/{article_id}",
        ])

    # RSC patterns
    if "10.1039" in doi:
        article_id = doi.replace("10.1039/", "")
        urls.extend([
            f"https://pubs.rsc.org/en/content/articlepdf/{article_id}",
            f"https://pubs.rsc.org/en/content/articlehtml/{article_id}",
        ])

    # Wiley patterns
    if "10.1002" in doi:
        article_id = doi.replace("10.1002/", "")
        urls.extend([
            f"https://onlinelibrary.wiley.com/doi/pdfdirect/{article_id}",
            f"https://onlinelibrary.wiley.com/doi/full/{article_id}",
        ])

    # Elsevier / ScienceDirect
    if "10.1016" in doi:
        article_id = doi.replace("10.1016/", "")
        urls.append(f"https://www.sciencedirect.com/science/article/pii/{article_id}/pdfft")

    # ACS
    if "10.1021" in doi:
        article_id = doi.replace("10.1021/", "")
        urls.append(f"https://pubs.acs.org/doi/pdf/{article_id}")

    return urls


def fetch_batch(papers: list[Paper], dest_dir: str | Path, delay: float = 1.5) -> list[Path]:
    """
    Download PDFs for multiple papers. Rate-limited.
    Attempts all papers regardless of OA status — tries Unpaywall URL first,
    then falls back to publisher-specific PDF URLs for non-OA papers.
    Returns list of successfully downloaded file paths.
    """
    dest_dir = Path(dest_dir)
    downloaded = []
    for paper in papers:
        if not paper.pdf_url:
            # For non-OA papers, try to construct URL from DOI
            alt = _alternate_urls(paper)
            if alt:
                paper.pdf_url = alt[0]  # use first alternate URL
        path = fetch_pdf(paper, dest_dir)
        if path:
            downloaded.append(path)
        time.sleep(delay)  # be respectful of servers
    return downloaded


def save_manifest(papers: list[Paper], dest_dir: str | Path) -> Path:
    """Save papers metadata as JSON."""
    import json
    dest_dir = Path(dest_dir)
    manifest_path = dest_dir / "papers_manifest.json"
    data = [p.to_dict() for p in papers]
    manifest_path.write_text(json.dumps(data, indent=2))
    return manifest_path