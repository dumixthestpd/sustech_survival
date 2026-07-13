"""
fetch_paper.py — Script-pipeline for fetching full academic papers.

Databases:
  RSC        → Shibboleth/CARSI cookies from Playwright → http.client GET
  CNKI       → FSSO/Shibboleth cookies from Playwright → http.client GET
  WoS        → CARSI/Shibboleth cookies from Playwright → http.client GET
  (internal) → LibAuth session (CAS) for Primo/LibProxy

Why http.client instead of requests?
  RSC (and some others) reject urllib3/requests TLS handshake while
  accepting curl/http.client. Root cause: different default SSL context.

Usage:
  from fetch_paper import fetch_rsc_paper, fetch_cnki_paper, fetch_wos_paper
  html = fetch_rsc_paper("10.1039/D5MH00719D")
  pdf  = fetch_rsc_paper("10.1039/D5MH00719D", format="pdf")
"""

import http.client
import json
import re
import sys
import time
import os
from pathlib import Path
from typing import Optional, Literal

# ── Cookie directories ────────────────────────────────────────────────────────
_COOKIE_DIR = Path(__file__).parent / "cookies"


# ── RSC ────────────────────────────────────────────────────────────────────────
def fetch_rsc_paper(
    doi: str,
    cookies_path: str = None,
    use_playwright: bool = False,
    headless: bool = True,
) -> dict:
    """
    Fetch full paper from RSC (pubs.rsc.org).

    Auth: Shibboleth/CARSI via SUSTech CAS.
    Result: {title, authors, abstract, body_text, body_len, url}
    """
    if cookies_path is None:
        cookies_path = _COOKIE_DIR / "rsc_cookies.json"

    cookies = _load_cookies(cookies_path)
    if not cookies:
        if not use_playwright:
            raise PermissionError("RSC: no cookies found. Run `login_rsc()` first or use_playwright=True.")
        cookies = _login_rsc(headless=headless)
        _save_cookies(cookies, cookies_path)

    cookie_str = _build_cookie_header(cookies)

    # Normalise DOI
    doi = doi.strip()
    if doi.startswith("https://doi.org/"):
        doi = doi.replace("https://doi.org/", "")
    if not doi.startswith("10."):
        raise ValueError(f"RSC: unexpected DOI format: {doi}")

# RSC DOI format: 10.1039/D5MH00719D → /content/articlehtml/{year}/{journal_code}/{doi_suffix_lower}
    # Strategy: (1) try xlink.rsc.org redirect to get the actual URL, (2) extract year/journal from it
    doi_suffix = doi.replace("https://doi.org/", "").replace("10.1039/", "").strip()
    doi_lower = doi_suffix.lower()

    # Step 1: use xlink redirect to discover the real article URL
    xlink_url = f"https://xlink.rsc.org/?DOI={doi_suffix}"
    discovered_url = _resolve_redirect(xlink_url, cookie_str)
    if discovered_url and "/articlehtml/" in discovered_url:
        article_url = discovered_url
    elif discovered_url:
        # e.g. https://pubs.rsc.org/en/content/articlelanding/2025/mh/d5mh00719d
        article_url = discovered_url.replace("/articlelanding/", "/articlehtml/")
    else:
        # Fallback: construct from DOI (works for RSC pattern 10.1039/CCXX-XXXXX)
        # DOI encodes: year=CC+20 (2-char year), journal code, article ID
        article_url = f"https://pubs.rsc.org/en/content/articlehtml/{doi_lower}"
    result = _http_get(
        article_url,
        cookies=cookie_str,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://pubs.rsc.org/",
        },
        parse_fn=_parse_rsc_article,
        max_redirects=5,
    )
    return result


def login_rsc(headless: bool = True) -> list:
    """Playwright login to RSC via Shibboleth/SUSTech CAS. Returns cookies list."""
    sys.path.insert(0, str(Path(__file__).parent))
    from sustech_survival.sso.authlib.rsc import RSCAuthorizer

    auth = RSCAuthorizer()
    ok = auth.login(headless=headless)
    if not ok:
        raise PermissionError("RSC login failed.")
    cookies = auth.browser.contexts[0].cookies()
    auth.browser.close()
    return cookies


# ── CNKI ──────────────────────────────────────────────────────────────────────
def fetch_cnki_paper(
    cnki_id: str,
    cookies_path: str = None,
    use_playwright: bool = False,
    headless: bool = True,
) -> dict:
    """
    Fetch paper from CNKI (cnki.net).

    Auth: FSSO/Shibboleth via SUSTech CAS.
    cnki_id: CNKI article ID (e.g. '10.16339/j.cnki.cjdx.2023.0102')
             or full URL like https://kns.cnki.net/kcms/detail/.../filename.html
    """
    if cookies_path is None:
        cookies_path = _COOKIE_DIR / "cnki_cookies.json"

    cookies = _load_cookies(cookies_path)
    if not cookies:
        if not use_playwright:
            raise PermissionError("CNKI: no cookies found. Run `login_cnki()` first or use_playwright=True.")
        cookies = _login_cnki(headless=headless)
        _save_cookies(cookies, cookies_path)

    cookie_str = _build_cookie_header(cookies)

    # Normalise CNKI ID to KNS URL
    if cnki_id.startswith("http"):
        article_url = cnki_id
    else:
        article_url = f"https://kns.cnki.net/kcms/detail/detail.aspx?filename={cnki_id}"

    return _http_get(
        article_url,
        cookies=cookie_str,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html",
            "Referer": "https://cnki.net/",
        },
        parse_fn=_parse_cnki_article,
    )


def login_cnki(headless: bool = True) -> list:
    """Playwright login to CNKI via FSSO/Shibboleth. Returns cookies list."""
    sys.path.insert(0, str(Path(__file__).parent))
    from sustech_survival.sso.authlib.cnki import CNKIAuth

    auth = CNKIAuth()
    ok = auth.login(headless=headless)
    if not ok:
        raise PermissionError("CNKI login failed.")
    cookies = auth.browser.contexts[0].cookies()
    auth.browser.close()
    return cookies


# ── WoS ──────────────────────────────────────────────────────────────────────
def fetch_wos_paper(
    wos_id: str,
    cookies_path: str = None,
    use_playwright: bool = False,
    headless: bool = True,
) -> dict:
    """
    Fetch paper from Web of Science.

    Auth: CARSI/Shibboleth via SUSTech CAS.
    wos_id: WoS UT identifier (e.g. 'WOS:000123456700001')
    """
    if cookies_path is None:
        cookies_path = _COOKIE_DIR / "wos_cookies.json"

    cookies = _load_cookies(cookies_path)
    if not cookies:
        if not use_playwright:
            raise PermissionError("WoS: no cookies found. Run `login_wos()` first or use_playwright=True.")
        cookies = _login_wos(headless=headless)
        _save_cookies(cookies, cookies_path)

    cookie_str = _build_cookie_header(cookies)

    # WoS article view
    article_url = f"https://www.webofscience.com/wos/woscc/article/abstract/{wos_id}"

    return _http_get(
        article_url,
        cookies=cookie_str,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "text/html",
        },
        parse_fn=_parse_wos_article,
    )


def login_wos(headless: bool = True) -> list:
    """Playwright login to WoS via CARSI/Shibboleth. Returns cookies list."""
    sys.path.insert(0, str(Path(__file__).parent))
    from sustech_survival.sso.authlib.wos import WoSAuth

    auth = WoSAuth()
    ok = auth.login(headless=headless)
    if not ok:
        raise PermissionError("WoS login failed.")
    cookies = auth.browser.contexts[0].cookies()
    auth.browser.close()
    return cookies


# ── Internal helper ──────────────────────────────────────────────────────────
def fetch_primo_paper(primo_id: str) -> dict:
    """
    Fetch paper metadata from Primo (SUSTech library search).
    Headless — no Playwright needed, uses LibAuth CAS session.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    from sustech_survival.sso import LibAuth

    auth = LibAuth()
    ok, err = auth.check()
    if not ok:
        raise PermissionError(f"LibAuth failed: {err}")

    # Primo API for bib record
    api_url = (
        f"https://sustc.primo.exlibrisgroup.com/primaws/record/"
        f"{primo_id}?vid=sustc&lang=zh_CN&country=cn"
    )
    resp = auth.session.get(api_url, timeout=15, verify=False)
    if resp.status_code != 200:
        return {"status_code": resp.status_code, "error": f"Primo API: {resp.status_code}"}
    data = resp.json()
    return _parse_primo_record(data)


# ── Core HTTP engine ──────────────────────────────────────────────────────────
def _http_get(url: str, cookies: str, headers: dict, parse_fn, max_redirects: int = 10) -> dict:
    """Make HTTPS request via http.client, following up to max_redirects 302s."""
    from urllib.parse import urlparse

    current_url = url
    for _ in range(max_redirects):
        parsed = urlparse(current_url)
        host = parsed.netloc
        path = parsed.path + ("?" + parsed.query if parsed.query else "")

        conn = http.client.HTTPSConnection(host, 443, timeout=20)
        req_headers = {
            "Host": host,
            "User-Agent": headers.get("User-Agent", "Mozilla/5.0"),
            "Accept": headers.get("Accept", "text/html"),
            "Referer": headers.get("Referer", f"https://{host}/"),
            "Cookie": cookies,
        }

        try:
            conn.request("GET", path, headers=req_headers)
            resp = conn.getresponse()
        except Exception as e:
            return {"error": str(e), "url": current_url}

        body = resp.read()
        status = resp.status

        if resp.status in (301, 302, 303, 307, 308):
            location = resp.getheader("Location", "")
            # Relative URL?
            if location and not location.startswith("http"):
                from urllib.parse import urljoin
                location = urljoin(current_url, location)
            current_url = location
            conn.close()
            continue  # follow redirect

        # Non-redirect: parse body
        if status != 200:
            return {"status_code": status, "url": current_url, "body_len": len(body)}

        text = body.decode("utf-8", errors="replace")
        result = parse_fn(text)
        result["url"] = current_url
        result["status_code"] = 200
        return result

    # Exceeded max redirects
    return {"error": f"Too many redirects ({max_redirects})", "url": current_url}


# ── HTML parsers ─────────────────────────────────────────────────────────────
def _parse_rsc_article(html: str) -> dict:
    """Extract title, authors, abstract, body from RSC article HTML (articlelanding or articlehtml formats)."""
    import re

    # Title — try articlehtml first (span.title_heading), then articlelanding (meta og:title)
    title_m = re.search(r'<span class="title_heading"[^>]*>(.*?)</span>', html, re.S | re.I)
    if not title_m:
        title_m = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', html, re.I)
    if not title_m:
        title_m = re.search(r'<h1[^>]*class="[^"]*article__title[^"]*"[^>]*>(.*?)</h1>', html, re.S | re.I)
    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""

    # Abstract — articlehtml: <h2>Abstract</h2><p>...; articlelanding: buried in body text
    abstract_m = re.search(r'<h2[^>]*>\s*Abstract\s*</h2>\s*<p[^>]*>(.*?)</p>', html, re.S | re.I)
    if not abstract_m:
        # Try meta description
        abstract_m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]+)"', html, re.I)
    if not abstract_m:
        # Extract from first paragraph that contains "nanozyme" or "abstract" signals
        paras = re.findall(r'<p[^>]*>(.*?)</p>', html, re.S | re.I)
        for p in paras:
            clean = re.sub(r'<[^>]+>', '', p).strip()
            if len(clean) > 100 and any(kw in clean.lower() for kw in ['abstract', 'nanozyme', 'machine learning', 'introduction']):
                abstract_m = type('obj', (object,), {'group': lambda _: clean})()
                break
    abstract = re.sub(r'<[^>]+>', '', abstract_m.group(1)).strip() if abstract_m else ""

    # Authors — <a href="...author...">Name</a> pattern (handles \r\n in names)
    author_links = re.findall(r'<a[^>]*href="[^"]*author[^"]*"[^>]*>(.*?)</a>', html, re.S | re.I)
    authors = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', a)).strip() for a in author_links]
    # Filter out non-name entries (e.g. "For Authors and Editors", "correctly acknowledge")
    authors = [a for a in authors if a and len(a) > 2 and not any(k in a.lower() for k in ['acknowledge', 'author', 'permission', 'for '])]
    # Deduplicate while preserving order
    seen_lower = set()
    authors_deduped = []
    for a in authors:
        key = a.lower()
        if key not in seen_lower:
            seen_lower.add(key)
            authors_deduped.append(a)
    authors = authors_deduped

    # Body — articlehtml uses chapter divs; articlelanding uses different structure
    chapter_matches = re.findall(r'<div[^>]*class="[^"]*chapter[^"]*"[^>]*>(.*?)</div>', html, re.S | re.I)
    if chapter_matches:
        body = re.sub(r'<[^>]+>', ' ', ' '.join(chapter_matches)).strip()
    else:
        # Fallback: get all paragraph text after the abstract region
        abstract_pos = html.lower().find('abstract')
        start_pos = abstract_pos + 200 if abstract_pos > 0 else len(html) // 2
        remaining = html[start_pos:]
        paras = re.findall(r'<p[^>]*>(.*?)</p>', remaining, re.S | re.I)
        body = ' '.join([re.sub(r'<[^>]+>', '', p).strip() for p in paras if re.sub(r'<[^>]+>', '', p).strip()])

    body = re.sub(r'\s+', ' ', body).strip()

    return {
        "title": title,
        "authors": authors[:20],  # cap at 20 authors
        "abstract": abstract[:2000],
        "body_text": body[:5000],
        "body_len": len(body),
        "source": "RSC",
    }


def _parse_cnki_article(html: str) -> dict:
    """Extract from CNKI article page."""
    title_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""
    abstract_m = re.search(r'<div[^>]*class="abstract"[^>]*>(.*?)</div>', html, re.S)
    abstract = re.sub(r'<[^>]+>', '', abstract_m.group(1)).strip() if abstract_m else ""
    return {"title": title, "abstract": abstract, "source": "CNKI", "body_len": len(html)}


def _parse_wos_article(html: str) -> dict:
    """Extract from WoS article page."""
    title_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""
    return {"title": title, "source": "WoS", "body_len": len(html)}


def _parse_primo_record(data: dict) -> dict:
    """Parse Primo API JSON response."""
    try:
        record = data.get("primoRecord", {}).get("display", {})
        return {
            "title": record.get("title", [""])[0],
            "authors": record.get("creator", []),
            "abstract": record.get("description", [""])[0],
            "source": "Primo",
        }
    except Exception as e:
        return {"error": str(e), "source": "Primo"}


def _resolve_redirect(url: str, cookies: str) -> Optional[str]:
    """Follow a 302 redirect chain and return the final URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path + ("?" + parsed.query if parsed.query else "")
    conn = http.client.HTTPSConnection(host, 443, timeout=15)
    conn.request("GET", path, headers={"Host": host, "Cookie": cookies, "User-Agent": "Mozilla/5.0"})
    resp = conn.getresponse()
    if resp.status in (301, 302, 303, 307, 308):
        return resp.getheader("Location")
    return None


# ── Cookie helpers ────────────────────────────────────────────────────────────
def _load_cookies(path) -> list:
    """Load cookies from JSON file. Returns list or empty list."""
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data = json.load(f)
    # Handle both formats: list of {name, value} objects, or dict of {name: value}
    if isinstance(data, list):
        return data  # Already in Playwright cookie format
    if isinstance(data, dict):
        return [{"name": k, "value": v} for k, v in data.items()]
    return []


def _save_cookies(cookies: list, path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cookies, f)


def _build_cookie_header(cookies: list) -> str:
    """Convert cookie list/dict to Cookie header string."""
    if isinstance(cookies, dict):
        cookies = [{"name": k, "value": v} for k, v in cookies.items()]
    return "; ".join([f"{c['name']}={c['value']}" for c in cookies if c.get("value")])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch academic papers")
    parser.add_argument("db", choices=["rsc", "cnki", "wos", "primo"])
    parser.add_argument("id", help="DOI (RSC), CNKI ID, WoS ID, or Primo ID")
    parser.add_argument("--login", action="store_true", help="Force re-authentication")
    parser.add_argument("--headless", action="store_true", default=True)
    args = parser.parse_args()

    if args.db == "rsc":
        if args.login:
            cookies = login_rsc(headless=args.headless)
            _save_cookies(cookies, _COOKIE_DIR / "rsc_cookies.json")
            print(f"✅ RSC login saved {len(cookies)} cookies")
        else:
            result = fetch_rsc_paper(args.id, use_playwright=False)
            print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.db == "cnki":
        if args.login:
            cookies = login_cnki(headless=args.headless)
            _save_cookies(cookies, _COOKIE_DIR / "cnki_cookies.json")
            print(f"✅ CNKI login saved {len(cookies)} cookies")
        else:
            result = fetch_cnki_paper(args.id, use_playwright=False)
            print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.db == "wos":
        if args.login:
            cookies = login_wos(headless=args.headless)
            _save_cookies(cookies, _COOKIE_DIR / "wos_cookies.json")
            print(f"✅ WoS login saved {len(cookies)} cookies")
        else:
            result = fetch_wos_paper(args.id, use_playwright=False)
            print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.db == "primo":
        result = fetch_primo_paper(args.id)
        print(json.dumps(result, indent=2, ensure_ascii=False))