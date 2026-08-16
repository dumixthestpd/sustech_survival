# =============================================================================
# Web of Science (WoS) — Shibboleth SP Authorizer
# =============================================================================
# Uses Shibboleth WAYF/DS federation to authenticate via SUSTech CAS.
#
# WoS flow (SP-initiated):
#   1. Browser goes to SP_INIT_URL → redirect to Clarivate access portal
#   2. Select "CHINA CERNET Federation" from institution combobox
#   3. Click "Go to institution" → redirect to CARSI DS WAYF
#   4. Search for SUSTech in CARSI WAYF → redirect to SUSTech CAS
#   5. SUSTech CAS login → redirect to SUSTech IdP consent page
#   6. Accept consent → IdP posts SAMLResponse back to WoS ACS
#   7. WoS validates SAMLResponse → session cookie set
#
# The Clarivate portal uses a Material combobox (mat-select) for institution
# selection; the "Go to institution" button only enables after selection.
# CARSI DS WAYF uses a search input + <li> with onclick=selectidp().
# =============================================================================

from pathlib import Path
from ..providers.shibboleth import ShibbolethAuthorizer
WOS_BASE = "https://www.webofscience.com"
WOS_INIT = "https://www.webofscience.com/wos/woscc/summary/basic"
WOS_ACS = "https://www.webofscience.com/Shibboleth.sso/SAML2/POST"
WOS_CAS = "https://cas.sustech.edu.cn/cas/login"
WOS_IDP_ENTITYID = "https://idp.sustech.edu.cn/idp/shibboleth"


class WoSAuth(ShibbolethAuthorizer):
    """Web of Science via CARSI/Shibboleth SSO — no session file, login every time."""
    SP_INIT_URL = WOS_INIT
    ACS_URL = WOS_ACS
    IDP_LOGIN_URL = WOS_CAS
    WAYF_SEARCH_TERM = "CHINA CERNET Federation"
    LOGIN_TIMEOUT = 120
    SUSTECH_IDP = WOS_IDP_ENTITYID

    @property
    def submodule_dir(self):
        return self.skill_dir / "wos"

    def find_institution_link(self, page):
        return None

    def handle_wayf(self, page) -> bool:
        """
        Handle Clarivate access portal institution selection.
        Clicks mat-select combobox → selects "CHINA CERNET Federation" →
        clicks "Go to institution" button.
        Returns True once redirected to CARSI WAYF page.
        """
        import time

        # Step 1: Click the Institution combobox
        try:
            combobox = page.locator(
                "mat-select[formcontrolname='federationName']"
            ).first
            combobox.click(timeout=10000)
            time.sleep(1.5)
        except Exception as e:
            print(f"  ⚠ Could not click Institution combobox: {e}")
            return False

        # Step 2: Select "CHINA CERNET Federation"
        try:
            cernet = page.get_by_text("CHINA CERNET Federation", exact=True).first
            cernet.click(timeout=10000)
            time.sleep(0.8)
            print("  → Selected: CHINA CERNET Federation")
        except Exception as e:
            print(f"  ⚠ Could not select 'CHINA CERNET Federation': {e}")
            return False

        # Step 3: Click "Go to institution" (English in headless, Chinese in visible)
        try:
            if page.get_by_text("Go to institution", exact=True).count() > 0:
                go_btn = page.get_by_text("Go to institution", exact=True).first
            else:
                go_btn = page.get_by_text("转到机构", exact=True).first
            go_btn.click(timeout=10000)
            time.sleep(1.0)
        except Exception as e:
            print(f"  ⚠ Could not click 'Go to institution' button: {e}")
            return False

        print("  → Clicked 'Go to institution'")
        return True

    def login(self, *, headless: bool = False, username: str = None, password: str = None):
        """See docs/wos.md."""
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
            print("⚠ WoS credentials not found in credentials.txt")
            return False

        # Launch browser — store on self so caller can use page after return
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=headless)
        self.ctx = self.browser.new_context()
        self.page = self.ctx.new_page()
        page = self.page

        try:
            # ── Step 1: Clarivate access portal ───────────────────────────────
            print(f"[WoS] Navigating to {self.SP_INIT_URL} ...")
            page.goto(self.SP_INIT_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            print(f"  → {page.url}")

            # ── Step 2: Institution combobox → CARSI WAYF ───────────────────
            wayf_ok = self.handle_wayf(page)
            if not wayf_ok:
                print("⚠ Failed to select institution in WoS portal")
                self.browser.close()
                return False

            # Wait for redirect to CARSI DS WAYF
            try:
                page.wait_for_url("**ds.carsi.edu.cn**", timeout=15000)
                page.wait_for_timeout(2000)
                print(f"  → CARSI WAYF: {page.url}")
            except Exception as e:
                print(f"⚠ Was not redirected to CARSI WAYF: {e}")
                self.browser.close()
                return False

            # ── Step 3: CARSI WAYF → search SUSTech + submit ───────────────
            from ..providers.carsi import login_via_carsi

            print("  → Handling CARSI WAYF ...")
            carsi_ok = login_via_carsi(
                page,
                target_entity_id="https://sp.tshhosting.com/shibboleth",
                target_return_url="https://www.webofknowledge.com",
            )
            if not carsi_ok:
                print("⚠ CARSI WAYF handling failed")
                self.browser.close()
                return False

            # Wait for SUSTech CAS
            try:
                page.wait_for_url("**cas.sustech.edu.cn**", timeout=30000)
                page.wait_for_timeout(2000)
                print(f"  → SUSTech CAS: {page.url}")
            except Exception as e:
                print(f"⚠ Was not redirected to SUSTech CAS: {e}")
                self.browser.close()
                return False

            # ── Step 4: CAS login ──────────────────────────────────────────
            print(f"  → Logging in as {username} ...")
            page.fill('input[name="username"]', username)
            page.fill('input[name="password"]', password)
            page.get_by_role("button", name="登录", exact=True).click()

            # Wait for IdP consent or ACS redirect
            try:
                page.wait_for_url("**idp.sustech.edu.cn**", timeout=30000)
                page.wait_for_timeout(3000)
                print(f"  → At SUSTech IdP consent page: {page.url}")
            except Exception:
                if self.ACS_URL.split('/')[2] in page.url:
                    print(f"  → ACS reached directly: {page.url}")
                else:
                    print(f"  → Unexpected URL: {page.url}")

            # ── Step 5: IdP consent — accept ───────────────────────────────
            if "idp.sustech.edu.cn" in page.url:
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
                        page.wait_for_timeout(8000)
                except Exception as e:
                    print(f"  ⚠ Could not click Accept: {e}")

            # ── Done ────────────────────────────────────────────────────────
            final_url = page.url
            cookies = {c['name']: c['value'] for c in self.ctx.cookies()}
            wos_cookies = [k for k in cookies if any(
                x in k.lower() for x in ['wos', 'webof', 'shib', 'sid', 'sess']
            )]

            if wos_cookies:
                print(f"✅ WoS login succeeded ({len(cookies)} total cookies, "
                      f"{len(wos_cookies)} WoS-specific)")
                print(f"   Landing: {final_url}")
            else:
                print(f"⚠️  WoS login may have failed — no WoS cookies found")
                print(f"   URL: {final_url}")

            return True

        except Exception as e:
            print(f"⚠ WoS login error: {e}")
            self.browser.close()
            return False


_auth = WoSAuth(skill_dir=str(Path(__file__).resolve().parent.parent.parent.parent))
