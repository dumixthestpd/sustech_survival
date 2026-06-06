# =============================================================================
# JSTOR — Cloudscraper Authorizer
# =============================================================================
# JSTOR is accessible via cloudscraper (bypasses Cloudflare).
# On campus: direct access (IP auth).
# Off campus: institutional login via Shibboleth.
#
# JSTOR Shibboleth endpoint: /action/doLogin?isjfePageId=... → redirect to CAS
# =============================================================================

from pathlib import Path
from typing import Optional

import cloudscraper

from ..authorizer import Authorizer, register_auth

JSTOR_BASE = "https://www.jstor.org"
JSTOR_SEARCH = f"{JSTOR_BASE}/search/build-results"


class JSTORAuth(Authorizer):
    """
    JSTOR access via cloudscraper + optional Shibboleth login.
    """

    BASE_URL = JSTOR_BASE

    def __init__(self, skill_dir: Optional[str] = None):
        super().__init__(skill_dir=skill_dir)
        self.scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        self.scraper.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })

    def check(self) -> tuple[bool, str]:
        r = self.scraper.get(JSTOR_BASE, timeout=15)
        if r.status_code == 200 and len(r.text) > 5000:
            if "jstor" in r.text.lower():
                return True, "JSTOR accessible via cloudscraper"
        return False, f"JSTOR returned status {r.status_code}"

    def login(self, username: str, password: str) -> bool:
        """
        JSTOR institutional login — goes through CAS/Shibboleth.
        The JSTOR Shibboleth SSO URL includes a redirect URI back to JSTOR.
        """
        from ..providers.cas import CASAuthorizer

        # JSTOR SSO entry — this URL includes the redirect back to JSTOR
        jstor_sso = (
            "https://www.jstor.org/action/doLogin?"
            "isjfePageId=100013061&redirectUri=/"
        )

        cas = CASAuthorizer(skill_dir=self.skill_dir)
        cas.SERVICE_URL = jstor_sso

        if cas.login(username, password):
            cookies = cas.session_cookies()
            for name, value in cookies.items():
                self.scraper.cookies.set(name, value)
            return True
        return False

    def search(self, query: str, max_results: int = 20) -> dict:
        """
        Search JSTOR. Returns articles matching the query.
        """
        params = {"query": query, "Sort": "relevance"}
        r = self.scraper.get(JSTOR_SEARCH, params=params, timeout=20)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "results": []}

        # Parse results from the HTML response
        import re
        titles = re.findall(r'href="(/article/[^"]+)"[^>]*>\s*<[^>]*>\s*([^<]+)', r.text)
        # Simple extraction — JSTOR page structure varies
        return {"results": [{"query": query, "count": len(titles)}]}

    @property
    def session_file(self):
        return self.skill_root / "jstor" / "session.json"

    @property
    def submodule_dir(self):
        return self.skill_root / "jstor"


_jstor = JSTORAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
register_auth("jstor", _jstor)