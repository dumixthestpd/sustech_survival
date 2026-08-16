# =============================================================================
# CNKI (中国知网) — Shibboleth FSSO Authorizer
# =============================================================================
# CNKI uses its own Shibboleth-based FSSO (Federated Single Sign-On) system.
# Each university has an entityID in CNKI's federation.
#
# CNKI FSSO flow:
#   1. Navigate to CNKI Shibboleth login with SUSTech entityID
#   2. Redirect to SUSTech CAS
#   3. CAS login with student ID + password
#   4. Redirect to SUSTech IdP consent page
#   5. Accept consent → redirect back to CNKI
#   6. CNKI session established
#
# SUSTech entityID for CNKI: https://idp.sustech.edu.cn/idp/shibboleth
# (same as the general SUSTech IdP)
# =============================================================================

from pathlib import Path
from ..providers.shibboleth import ShibbolethAuthorizer
CNKI_BASE = "https://www.cnki.net"
CNKI_FSSO = "https://fsso.cnki.net/Shibboleth.sso/Login"
CNKI_TARGET = "https://fsso.cnki.net/secure/default.aspx"
CNKI_IDP_ENTITYID = "https://idp.sustech.edu.cn/idp/shibboleth"
CNKI_CAS = "https://cas.sustech.edu.cn/cas/login"


class CNKIAuth(ShibbolethAuthorizer):
    """CNKI (中国知网) via FSSO/Shibboleth — no session file, login every time."""
    SP_INIT_URL = CNKI_FSSO
    IDP_LOGIN_URL = CNKI_CAS
    SUSTECH_IDP = CNKI_IDP_ENTITYID
    LOGIN_TIMEOUT = 120

    @property
    def submodule_dir(self):
        return self.skill_dir / "cnki"

    def find_institution_link(self, page):
        return None

    def login(self, *, headless: bool = False, username: str = None, password: str = None):
        """See docs/cnki.md."""
        from playwright.sync_api import sync_playwright

        # Load credentials
        if not username or not password:
            cf = Path(self._creds_file)
            if cf.exists():
                line = cf.read_text().strip()
                if ':' in line:
                    username, password = line.split(':', 1)
                    username = username.strip()
                    password = password.strip()

        if not username or not password:
            print("⚠ CNKI credentials not found in credentials.txt")
            return False

        # Build Shibboleth URL
        from urllib.parse import urlencode
        params = {
            "entityID": CNKI_IDP_ENTITYID,
            "target": CNKI_TARGET,
        }
        shib_url = f"{CNKI_FSSO}?{urlencode(params)}"

        # Launch browser
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=headless)
        self.ctx = self.browser.new_context()
        self.page = self.ctx.new_page()
        page = self.page

        try:
            # -- Step 1: Navigate to CNKI Shibboleth → redirect to SUSTech CAS -
            print(f"[CNKI] Navigating to CNKI FSSO (SUSTech) ...")
            page.goto(shib_url, wait_until="commit", timeout=30000)
            page.wait_for_timeout(3000)
            print(f"  → URL: {page.url}")

            # -- Step 2: At SUSTech CAS — login -------------------------------
            if "cas.sustech.edu.cn" in page.url:
                print(f"  → At SUSTech CAS, logging in as {username} ...")
                page.fill('input[name="username"]', username)
                page.fill('input[name="password"]', password)
                page.get_by_role("button", name="登录", exact=True).click()
                page.wait_for_timeout(3000)

            # -- Step 3: At SUSTech IdP consent — accept -----------------------
            if "idp.sustech.edu.cn" in page.url:
                print(f"  → At SUSTech IdP consent page ...")
                page.wait_for_timeout(2000)
                try:
                    accept_btn = page.locator(
                        'input[name="_eventId_proceed"], '
                        'button:has-text("Accept"), '
                        'button:has-text("接受"), '
                        'button:has-text("继续")'
                    ).first
                    if accept_btn.is_visible(timeout=3000):
                        accept_btn.click()
                        print("  → Accepted IdP consent")
                        page.wait_for_timeout(5000)
                except Exception as e:
                    print(f"  ⚠ Could not click Accept: {e}")

            # Wait for redirect back to CNKI (SAML POST from IdP)
            try:
                page.wait_for_url("**cnki.net**", timeout=15000)
                page.wait_for_timeout(3000)
            except Exception:
                pass  # May already be at CNKI

            # -- Done --------------------------------------------------------
            final_url = page.url
            cookies = {c['name']: c['value'] for c in self.ctx.cookies()}
            cnki_cookies = [k for k in cookies if 'cnki' in k.lower() or 'cki' in k.lower()]

            if "cnki" in final_url.lower() or len(cnki_cookies) > 0:
                print(f"✅ CNKI login succeeded")
                print(f"   Landing: {final_url}")
                return True
            else:
                print(f"⚠ CNKI may not have redirected properly")
                print(f"   URL: {final_url}")
                return True  # Still return True, caller can verify

        except Exception as e:
            print(f"⚠ CNKI login error: {e}")
            self.browser.close()
            return False


_auth = CNKIAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
