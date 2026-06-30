# =============================================================================
# RSC (Royal Society of Chemistry) — Shibboleth/CARSI Authorizer
# =============================================================================
# Login flow (2026-05-19 verified):
#   RSC Shibboleth check URL → SUSTech CAS → SUSTech IdP consent → RSC
#
# Direct URL bypasses WAYF entirely:
#   https://www.rsc.org/rsc-id/account/checkfederatedaccess
#     ?instituteurl=https%3A%2F%2Fidp.sustech.edu.cn%2Fidp%2Fshibboleth
#     &returnurl=https%3A%2F%2Fpubs.rsc.org
#     &platformID=1c576962-b994-4139-a186-8120433be7b7
#
# Key entity IDs:
#   RSC SP:        https://shib.rsc.org/shibboleth
#   SUSTech IdP:   https://idp.sustech.edu.cn/idp/shibboleth
#   SUSTech CAS:   https://cas.sustech.edu.cn/cas/login
# =============================================================================

from pathlib import Path
from ..providers.shibboleth import ShibbolethAuthorizer
from ..authorizer import register_auth

# RSC Shibboleth configuration
RSC_BASE = "https://pubs.rsc.org"
RSC_INIT = "https://www.rsc.org/rsc-id/account/federatedaccess"
RSC_ACS = "https://www.rsc.org/rsc-id/account/saml2/sso"
RSC_CAS = "https://cas.sustech.edu.cn/cas/login"
SUSTECH_IDP = "https://idp.sustech.edu.cn/idp/shibboleth"

# Direct login URL — bypasses WAYF selection, goes straight to SUSTech IdP
RSC_DIRECT_LOGIN = (
    "https://www.rsc.org/rsc-id/account/checkfederatedaccess"
    "?instituteurl=https%3A%2F%2Fidp.sustech.edu.cn%2Fidp%2Fshibboleth"
    "&returnurl=https%3A%2F%2Fpubs.rsc.org"
    "&platformID=1c576962-b994-4139-a186-8120433be7b7"
)


class RSCAuthorizer(ShibbolethAuthorizer):
    """RSC via CARSI/Shibboleth SSO — no session file, login every time."""

    BASE_URL = RSC_BASE
    SP_INIT_URL = RSC_INIT
    ACS_URL = RSC_ACS
    IDP_LOGIN_URL = RSC_CAS
    WAYF_SEARCH_TERM = "Southern University"
    LOGIN_TIMEOUT = 90

    @property
    def creds(self):
        """Return (username, password) via Credentials class."""
        from sustech_survival.sso import Credentials
        c = Credentials()
        return c.username, c.password

    def find_institution_link(self, page):
        """
        RSC has an explicit 'Log in via your home institution' link.
        We bypass it entirely by navigating to the direct Shibboleth check URL.
        """
        return None  # signals base.login() to skip WAYF and go direct

    def handle_wayf(self, page):
        """
        Since we navigate directly to the Shibboleth check URL (no WAYF),
        this is not called. The base.login() skips it when _find returns None.
        """
        return True

    def login(self, *, headless: bool = True, username: str = None, password: str = None):
        """See docs/rsc.md."""
        from playwright.sync_api import sync_playwright

        # Load credentials if not provided
        if not username or not password:
            username, password = self.creds

        if not username or not password:
            raise ValueError("RSC login requires username and password. "
                             "Pass them as arguments or store in credentials.txt")

        p = sync_playwright().__enter__()
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            # Step 1: Navigate directly to RSC + SUSTech Shibboleth (no WAYF needed)
            print(f"[1/4] Navigating to RSC+SUSTech Shibboleth...")
            page.goto(RSC_DIRECT_LOGIN, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # Step 2: Should now be at SUSTech CAS
            if "cas.sustech.edu.cn" not in page.url:
                print(f"[2/4] Not at CAS — URL: {page.url}")
                try:
                    page.get_by_text("Log in via your home institution").click(timeout=5000)
                    page.wait_for_timeout(3000)
                except Exception:
                    pass

            print(f"[2/4] At SUSTech CAS — filling credentials...")
            page.fill('input[name="username"]', username)
            page.fill('input[name="password"]', password)
            page.get_by_role("button", name="登录", exact=True).click()
            page.wait_for_timeout(4000)

            # Step 3: IdP consent or back at RSC
            if "idp.sustech.edu.cn" in page.url:
                print("[3/4] At IdP consent — accepting...")
                for selector in [
                    'input[name="_eventId_proceed"]',
                    'button:has-text("Accept")',
                    'button:has-text("继续")',
                    'button:has-text("接受")',
                    'button:has-text("Yes")',
                ]:
                    try:
                        btn = page.locator(selector).first
                        if btn.is_visible(timeout=2000):
                            btn.click()
                            print(f"  → Clicked: {selector}")
                            break
                    except Exception:
                        continue
                page.wait_for_timeout(6000)

            # Step 4: Verify
            if "pubs.rsc.org" in page.url or "rsc.org" in page.url:
                print(f"[4/4] ✅ RSC login succeeded! URL: {page.url}")
                self.browser = browser
                self.page = page
                self.playwright = p
                return True
            else:
                print(f"[4/4] ❌ Not at RSC. URL: {page.url}")
                browser.close()
                p.__exit__(None, None, None)
                return False

        except Exception as e:
            print(f"[!] Login error: {e}")
            browser.close()
            p.__exit__(None, None, None)
            return False


# Module-level singleton + registration
rsc_auth_singleton = RSCAuthorizer()
register_auth("rsc", _auth)
