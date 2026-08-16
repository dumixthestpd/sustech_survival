# =============================================================================
# Wiley Online Library — Cloudscraper Authorizer
# =============================================================================

from pathlib import Path
from typing import Optional

import cloudscraper

from ..authorizer import Authorizer

WILEY_BASE = "https://onlinelibrary.wiley.com"
WILEY_SSO = f"{WILEY_BASE}/action/ssostart?redirecturi=%2f"


class WileyAuth(Authorizer):
    BASE_URL = WILEY_BASE
    SsoEntry_URL = WILEY_SSO

    def __init__(self, skill_dir: Optional[str] = None):
        super().__init__(skill_dir=skill_dir)
        self.scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        self.scraper.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })

    def check(self) -> tuple[bool, str]:
        r = self.scraper.get(WILEY_BASE, timeout=15)
        if r.status_code == 200 and len(r.text) > 5000 and "wiley" in r.text.lower():
            return True, "Wiley Online Library accessible via cloudscraper"
        return False, f"Wiley returned {r.status_code}"

    def login(self, username: str, password: str) -> bool:
        from ..providers.cas import CASAuthorizer
        cas = CASAuthorizer(skill_dir=self.skill_dir)
        cas.SERVICE_URL = WILEY_SSO
        if cas.login(username, password):
            for name, value in cas.session_cookies().items():
                self.scraper.cookies.set(name, value)
            return True
        return False

    def search(self, query: str, max_results: int = 25) -> dict:
        params = {"query": query, "pageSize": min(max_results, 100)}
        r = self.scraper.get(f"{WILEY_BASE}/search/searchall", params=params, timeout=20)
        return {"results": [], "count": 0, "note": "Wiley HTML search not yet parsed"} if r.status_code == 200 else {"error": f"HTTP {r.status_code}", "results": []}

    @property
    def submodule_dir(self):
        return self.skill_dir / "wiley"


_wiley = WileyAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
