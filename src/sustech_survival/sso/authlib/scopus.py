# =============================================================================
# Scopus — Cloudscraper Authorizer
# =============================================================================
# Scopus (Elsevier) uses Shibboleth for institutional login.
# SSO entry: /pages/signin (redirects to RefProx/DeepDyve or direct Shibboleth)
# =============================================================================

from pathlib import Path
from typing import Optional

import cloudscraper

from ..authorizer import Authorizer

SCOPUS_BASE = "https://www.scopus.com"
SCOPUS_SSO = f"{SCOPUS_BASE}/pages/signin?referralurl=https%3a%2f%2fwww.scopus.com%2fpages%2fhome"


class ScopusAuth(Authorizer):
    BASE_URL = SCOPUS_BASE
    SsoEntry_URL = SCOPUS_SSO

    def __init__(self, skill_dir: Optional[str] = None):
        super().__init__(skill_dir=skill_dir)
        self.scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        self.scraper.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })

    def check(self) -> tuple[bool, str]:
        r = self.scraper.get(SCOPUS_BASE, timeout=15)
        if r.status_code == 200 and len(r.text) > 5000 and "scopus" in r.text.lower():
            return True, "Scopus accessible via cloudscraper"
        return False, f"Scopus returned {r.status_code}"

    def login(self, username: str, password: str) -> bool:
        from ..providers.cas import CASAuthorizer
        cas = CASAuthorizer(skill_dir=self.skill_dir)
        cas.SERVICE_URL = SCOPUS_SSO
        if cas.login(username, password):
            for name, value in cas.session_cookies().items():
                self.scraper.cookies.set(name, value)
            return True
        return False

    def search(self, query: str, max_results: int = 25) -> dict:
        params = {"term": query, "sort": "relevancy"}
        r = self.scraper.get(f"{SCOPUS_BASE}/search/scopus", params=params, timeout=20)
        return {"results": [], "count": 0, "note": "Scopus HTML search not yet parsed"} if r.status_code == 200 else {"error": f"HTTP {r.status_code}", "results": []}

    @property
    def submodule_dir(self):
        return self.skill_root / "scopus"


_scopus = ScopusAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
