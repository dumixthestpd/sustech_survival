# =============================================================================
# IEEE Xplore — Cloudscraper Authorizer
# =============================================================================
# IEEE Xplore is accessible via cloudscraper (bypasses Cloudflare).
# On campus (SUSTech IP), no login needed — IP authentication works.
# Off campus: institutional SSO via Shibboleth.
#
# The cloudscraper session persists JSESSIONID and AWSALB cookies which
# represent the IEEE application session (not CAS).
# =============================================================================

import json
import time
from pathlib import Path
from typing import Optional

import cloudscraper

from ..authorizer import Authorizer, register_auth

IEEE_BASE = "https://ieeexplore.ieee.org"
IEEE_SEARCH = f"{IEEE_BASE}/search/searchresult"
IEEE_SSO = f"{IEEE_BASE}/action/login"


class IEEEAuth(Authorizer):
    """
    Headless IEEE Xplore access via cloudscraper.
    On-campus: direct access (no auth needed).
    Off-campus: uses Shibboleth/CAS via SUSTech.
    """

    BASE_URL = IEEE_BASE
    SsoEntry_URL = IEEE_SSO

    def __init__(self, skill_dir: Optional[str] = None):
        super().__init__(skill_dir=skill_dir)
        self._scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        self._scraper.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })

    def check(self) -> tuple[bool, str]:
        r = self._scraper.get(IEEE_BASE, timeout=15)
        if r.status_code == 200 and len(r.text) > 5000:
            return True, "IEEE Xplore accessible via cloudscraper"
        return False, f"IEEE returned {r.status_code}"

    def login(self, username: str, password: str) -> bool:
        """
        Attempt Shibboleth SSO login via CAS.
        Uses the standard CAS flow: execution token → POST credentials → ticket.
        Then the cloudscraper session should carry the Shibboleth session.
        """
        # CAS login for IEEE (institutional SSO)
        from ..providers.cas import CASAuthorizer
        cas = CASAuthorizer(skill_dir=self.skill_dir)
        cas.SERVICE_URL = IEEE_SSO
        if cas.login(username, password):
            # Transfer CAS cookies to cloudscraper session
            session_cookies = cas.session_cookies()
            for name, value in session_cookies.items():
                self._scraper.cookies.set(name, value)
            return True
        return False

    def search(self, query: str, max_results: int = 25) -> dict:
        """
        Search IEEE Xplore. Returns dict with 'results' list.
        Note: Without auth, results may be limited. With Shibboleth login,
        full access is available.
        """
        params = {
            "QueryText": query,
            "rowsPerPage": str(min(max_results, 100)),
            "pageNumber": "1",
        }
        r = self._scraper.get(IEEE_SEARCH, params=params, timeout=20)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "results": []}

        # IEEE returns JSON for API calls
        try:
            data = r.json()
        except Exception:
            return {"error": "Could not parse response", "results": []}

        results = []
        for item in data.get("records", []):
            results.append({
                "title": item.get("title", ""),
                "authors": [a.get("name","") for a in item.get("authors", [])],
                "year": item.get("publicationYear", ""),
                "journal": item.get("publicationTitle", ""),
                "doi": item.get("doi", ""),
                "abstract": item.get("abstract", ""),
            })
        return {"results": results, "query": query, "count": len(results)}

    def fetch_pdf(self, article_id: str, output_path: str) -> bool:
        """Download an article PDF by IEEE article ID."""
        pdf_url = f"{IEEE_BASE}/stampPDF/getPDF?arnumber={article_id}"
        r = self._scraper.get(pdf_url, timeout=30, stream=True)
        if r.status_code != 200:
            return False
        Path(output_path).write_bytes(r.content)
        return True

    @property
    def session_file(self):
        return self.skill_root / "ieee" / "session.json"

    @property
    def submodule_dir(self):
        return self.skill_root / "ieee"


_ieee = IEEEAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
register_auth("ieee", _ieee)