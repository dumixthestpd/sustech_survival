# =============================================================================
# Springer Nature — Cloudscraper + OAuth2/SpringerIdP Authorizer
# =============================================================================
# Springer uses idp.springer.com for OAuth2/OIDC institutional login.
# This is a different auth flow from CAS/Shibboleth:
#   1. cloudscraper hits Springer → redirect to idp.springer.com
#   2. idp.springer.com → institution selector (WAYF) → SUSTech/CERNET
#   3. SUSTech CAS → ticket → back to idp.springer.com → OAuth token
#   4. Token stored in session for subsequent Springer API calls
#
# The cloudscraper session persists cookies across this flow for headless use.
# =============================================================================

from pathlib import Path
from typing import Optional

import cloudscraper

from ..authorizer import Authorizer

SPRINGER_BASE = "https://link.springer.com"
SPRINGER_IDP = "https://idp.springer.com"
SPRINGER_SSO = f"{SPRINGER_IDP}/auth/personal/springernature?redirect_uri={SPRINGER_BASE}"


class SpringerAuth(Authorizer):
    BASE_URL = SPRINGER_BASE
    SsoEntry_URL = SPRINGER_SSO

    def __init__(self, skill_dir: Optional[str] = None):
        super().__init__(skill_dir=skill_dir)
        self.scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        self.scraper.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def check(self) -> tuple[bool, str]:
        r = self.scraper.get(SPRINGER_BASE, timeout=15)
        if r.status_code == 200 and len(r.text) > 5000 and "springer" in r.text.lower():
            return True, "Springer accessible via cloudscraper"
        return False, f"Springer returned {r.status_code}"

    def login(self, username: str, password: str) -> bool:
        """
        Springer OAuth2 login via idp.springer.com.
        The OAuth2 flow with SUSTech/CAS is complex — cloudscraper handles
        the JS challenge, but the OAuth redirect loop needs browser cookies.
        This is a best-effort approach that may require manual first login.
        """
        from ..providers.cas import CASAuthorizer
        # The service URL for CAS is the Springer IdP
        cas = CASAuthorizer(skill_dir=self.skill_dir)
        cas.SERVICE_URL = SPRINGER_SSO
        if cas.login(username, password):
            for name, value in cas.session_cookies().items():
                self.scraper.cookies.set(name, value)
            return True
        return False

    def search(self, query: str, max_results: int = 25) -> dict:
        """Search Springer via their public API."""
        params = {
            "q": query,
            "numberOfPages": min(max_results // 20, 10),
        }
        r = self.scraper.get(f"{SPRINGER_BASE}/search", params=params, timeout=20)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "results": []}
        # Parse JSON-API response
        try:
            import json
            data = r.json()
            results = []
            for item in data.get("results", [])[:max_results]:
                results.append({
                    "title": item.get("title", ""),
                    "authors": [a.get("creatorName", "") for a in item.get("creators", [])],
                    "year": item.get("publicationDate", "")[:4],
                    "journal": item.get("publicationTitle", ""),
                    "doi": item.get("doi", ""),
                    "url": SPRINGER_BASE + item.get("url", ""),
                })
            return {"results": results, "count": len(results), "query": query}
        except Exception:
            return {"results": [], "count": 0, "note": "Response not parseable as JSON"}

    @property
    def submodule_dir(self):
        return self.skill_root / "springer"


_springer = SpringerAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
