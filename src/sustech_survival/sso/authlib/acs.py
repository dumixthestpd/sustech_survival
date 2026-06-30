# =============================================================================
# ACS Publications — Cloudscraper Authorizer
# =============================================================================
# ACS (American Chemical Society) is accessible via cloudscraper.
# Institutional access: Shibboleth/CAS via CERC WAYF (same as WoS).
# SSO entry: /action/ssostart?redirecturi=%2f
# =============================================================================

from pathlib import Path
from typing import Optional

import cloudscraper

from ..authorizer import Authorizer, register_auth

ACS_BASE = "https://pubs.acs.org"
ACS_SSO = f"{ACS_BASE}/action/ssostart?redirecturi=%2f"


class ACSAuth(Authorizer):
    BASE_URL = ACS_BASE
    SsoEntry_URL = ACS_SSO

    def __init__(self, skill_dir: Optional[str] = None):
        super().__init__(skill_dir=skill_dir)
        self.scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        self.scraper.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })

    def fresh_session(self):
        """Return a new cloudscraper session to avoid stale cookies triggering 403s."""
        return cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )

    def check(self) -> tuple[bool, str]:
        scraper = self.fresh_session()
        r = scraper.get(ACS_BASE, timeout=15)
        if r.status_code == 200 and len(r.text) > 5000 and "acs" in r.text.lower():
            return True, "ACS Publications accessible via cloudscraper"
        return False, f"ACS returned {r.status_code}"

    def login(self, username: str, password: str) -> bool:
        from ..providers.cas import CASAuthorizer
        cas = CASAuthorizer(skill_dir=self.skill_dir)
        cas.SERVICE_URL = ACS_SSO
        if cas.login(username, password):
            for name, value in cas.session_cookies().items():
                self.scraper.cookies.set(name, value)
            return True
        return False

    def search(self, query: str, max_results: int = 25) -> dict:
        params = {"query": query, "pageSize": min(max_results, 100)}
        # ACS does not have a simple public API; HTML search may work
        r = self.scraper.get(f"{ACS_BASE}/action/doSearch", params=params, timeout=20)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "results": []}
        return {"results": [], "count": 0, "note": "ACS HTML search not yet parsed"}

    @property
    def submodule_dir(self):
        return self.skill_root / "acs"


_acm = ACSAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
register_auth("acs", _acm)