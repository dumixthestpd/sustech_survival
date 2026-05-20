# =============================================================================
# Shibboleth SP Provider — SAML 2.0 via WAYF/DS Discovery
# =============================================================================
# Handles "Login via institution" / "SSO" flows for external academic databases
# (Web of Science, JSTOR, IEEE, Scopus, etc.) that use Shibboleth federation.
#
# Flow:
#   1. GET SP init URL → 302 to WAYF/DS discovery service
#   2. DS iframe / POST selects institution → 302 back to SP with SAMLRequest
#   3. SP generates SAML AuthnRequest → 302 to IdP (SUSTech CAS) with SAMLRequest
#   4. User logs in at IdP → 302 back to SP ACS URL with SAMLResponse
#   5. SP validates SAMLResponse → sets session cookie
#
# This provider uses Playwright to automate the browser-based WAYF flow since
# Shibboleth involves redirects across domains, JavaScript execution, and
# form submissions that are difficult to fully replicate with requests.
#
# For a fully headless approach, a Python SAML library (python3-saml,
# onelogin-saml) would parse SP metadata + IdP metadata and sign/verify
# AuthnRequest/SAMLResponse directly.
# =============================================================================

from ..base import Authorizer, AuthorizerError, UA

# Playwright is only needed at runtime, not for import — lazy import in login()
import importlib
import typing


class ShibbolethAuthorizer(Authorizer):
    """
    Shibboleth SP authentication via WAYF/DS discovery + IdP login.

    This is a BROWSER-BASED authorizer (not headless CAS). It opens a Playwright
    browser to handle the multi-step redirect flow:

      Service → WAYF Discovery → SUSTech CAS → Service ACS URL

    Subclasses MUST define:
        BASE_URL       — the SP (database) root URL
        SP_INIT_URL    — URL that starts the Shibboleth login (the "institution login" link)
        ACS_URL        — Assertion Consumer Service URL (where IdP posts back)
        IDP_LOGIN_URL  — SUSTech CAS login page (for wait_for_url targeting)

    Subclasses MAY define:
        WAYF_SEARCH_TERM — text to type in the institution search box
                           Default: "Southern University"
        LOGIN_TIMEOUT    — seconds to wait for IdP login. Default: 60

    Usage:
        class WoSAuthorizer(ShibbolethAuthorizer):
            BASE_URL       = "https://www.webofscience.com"
            SP_INIT_URL    = "https://www.webofscience.com/wos/woscc/summary/basic"
            ACS_URL        = "https://www.webofscience.com/Shibboleth.sso/SAML2/POST"
            IDP_LOGIN_URL  = "https://cas.sustech.edu.cn/cas/login"
            WAYF_SEARCH_TERM = "Southern University"
            XHR_MODE = False

        auth = WoSAuthorizer()
        auth.login()   # browser-based WAYF flow
    """

    SP_INIT_URL: str = ""          # URL that triggers Shibboleth redirect
    ACS_URL: str = ""             # Assertion Consumer Service — where SAML response lands
    IDP_LOGIN_URL: str = ""       # SUSTech CAS login — wait_for_url target
    WAYF_SEARCH_TERM: str = "Southern University"  # institution search text
    LOGIN_TIMEOUT: int = 60       # seconds to wait for full login flow

    @property
    def cas_url(self) -> str:
        # Shibboleth doesn't use a direct CAS service param in the traditional sense.
        # For display purposes only.
        return self.SP_INIT_URL

    def login(self, *, headless: bool = False, username: str = None, password: str = None):
        """
        Run the full Shibboleth WAYF flow in a browser.

        Steps:
          1. Navigate to SP_INIT_URL (database login page)
          2. Click "Login via institution" / "SSO" link
          3. WAYF discovery: search for "Southern University", select it
          4. SUSTech CAS login (credentials from params or browser autofill)
          5. Wait for redirect back to ACS_URL → done

        Agent-friendly: pass username/password for fully programmatic login.
        If credentials are not provided, falls back to browser autofill (human session).
        """
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            ctx = browser.new_context()
            page = ctx.new_page()

            print(f"[1/4] Navigating to {self.SP_INIT_URL} ...")
            page.goto(self.SP_INIT_URL, wait_until="domcontentloaded", timeout=30000)

            # ── Step 2: detect institution login link ────────────────────────
            link_info = self._find_institution_link(page)
            if link_info:
                print(f"[2/4] Clicking institution login: {link_info['text']}")
                link_info['handle'].click()
            else:
                print(f"[2/4] No explicit institution link found — trying direct SP init URL")
                page.goto(self.SP_INIT_URL, wait_until="domcontentloaded", timeout=15000)

            # ── Step 3: WAYF discovery — search for institution ─────────────
            page.wait_for_timeout(2000)
            wayf_ok = self._handle_wayf(page)
            if not wayf_ok:
                print("[3/4] No WAYF page detected — may use embedded IdP picker")

            # ── Step 4: wait for IdP login redirect ──────────────────────────
            print(f"[4/4] Waiting for SUSTech CAS login at {self.IDP_LOGIN_URL} ...")
            try:
                page.wait_for_url(f"**{self.IDP_LOGIN_URL}**", timeout=self.LOGIN_TIMEOUT)
                print("  → CAS login page reached.")
                page.wait_for_timeout(1500)

                # Agent-friendly: fill credentials programmatically if provided
                if username and password:
                    print(f"  → Filling credentials for {username} ...")
                    page.fill('input[name="username"]', username)
                    page.fill('input[name="password"]', password)
                    # Submit the form programmatically — language-agnostic, no button
                    # text needed. Playwright's form.submit() POSTs all hidden fields
                    # (execution, _eventId, geolocation) correctly.
                    page.locator('form').first.submit()
                else:
                    print("  → No credentials provided — relying on browser autofill")
                    page.wait_for_timeout(3000)

            except Exception as e:
                print(f"  ⚠ Did not reach CAS login page within {self.LOGIN_TIMEOUT}s: {e}")
                print(f"  Current URL: {page.url}")

            # Wait for ACS redirect to complete
            try:
                page.wait_for_url(f"**{self.ACS_URL}**", timeout=30)
                print(f"  → ACS URL reached — SAML exchange complete")
            except Exception:
                pass

            page.wait_for_timeout(2000)
            cookies = {c['name']: c['value'] for c in ctx.cookies()}
            self.save(cookies)
            print(f"✅ {len(cookies)} cookies saved: {list(cookies.keys())}")
            print(f"   Final URL: {page.url}")
            return True

    def _find_institution_link(self, page) -> typing.Optional[dict]:
        """
        Find and return a clickable element for "Login via institution" / "SSO".
        Returns dict with 'handle' and 'text' keys, or None.

        Override in subclasses for site-specific selectors.
        Default tries common link text patterns.
        """
        # Common selectors for institution/SSO login links
        candidates = [
            ("a", "Log in via institution"),
            ("a", "Institution login"),
            ("a", "Login via your institution"),
            ("a", "Access through your institution"),
            ("a", "Institutional login"),
            ("a", "SSO"),
            ("a", "Sign in via institution"),
            ("button", "Login via institution"),
        ]
        for tag, text in candidates:
            try:
                el = page.locator(f"{tag}:has-text('{text}')").first
                if el.is_visible(timeout=2000):
                    return {'handle': el, 'text': text}
            except Exception:
                pass

        # Broader: any link/button with "institution" in href or text
        try:
            for el in page.locator("a[href*='institution'], a[href*='sso'], a[href*='shibboleth']").all():
                if el.is_visible(timeout=1000):
                    return {'handle': el, 'text': el.inner_text()}
        except Exception:
            pass

        return None

    def _handle_wayf(self, page) -> bool:
        """
        Handle WAYF/DS discovery page: search for institution, select it, submit.

        Returns True if a WAYF page was handled, False if no WAYF was detected.

        Override in subclasses for custom WAYF implementations.
        """
        current_url = page.url

        # Check if this actually looks like a WAYF page
        body_text = page.inner_text("body") if page.query_selector("body") else ""
        wayf_indicators = [
            "institution", "search", "southern university",
            "find your", "select your institution", "wayf", "ds"
        ]
        is_wayf = any(ind in body_text.lower() for ind in wayf_indicators)

        if not is_wayf:
            return False

        print(f"  → WAYF page detected")
        search_term = self.WAYF_SEARCH_TERM

        # Try to find a search input on the WAYF page
        search_selectors = [
            "input[type='search']",
            "input[placeholder*='institution' i]",
            "input[placeholder*='university' i]",
            "input[placeholder*='search' i]",
            "input[name='query']",
            "input[name='search']",
            "#institution",
            "#uidp_search",
            "input[type='text']",
        ]
        search_input = None
        for sel in search_selectors:
            try:
                inp = page.locator(sel).first
                if inp.is_visible(timeout=1000):
                    search_input = inp
                    break
            except Exception:
                pass

        if not search_input:
            print(f"  ⚠ Could not find institution search input on WAYF page")
            return True  # WAYF was detected but we couldn't interact

        print(f"  → Searching: '{search_term}'")
        search_input.click()
        search_input.fill(search_term)
        page.wait_for_timeout(1000)

        # Select the institution from results
        select_selectors = [
            f"text={search_term}",
            f"a:has-text('{search_term}')",
            f"button:has-text('{search_term}')",
            f"li:has-text('{search_term}')",
            "[data-value*='sustech']",
            "[data-value*='southern']",
        ]
        selected = False
        for sel in select_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.click()
                    selected = True
                    print(f"  → Selected institution")
                    break
            except Exception:
                pass

        if not selected:
            # Last resort: press Enter to submit search, then look for first result
            search_input.press("Enter")
            page.wait_for_timeout(1500)
            try:
                page.locator("li, .result, .item").first.click(timeout=3000)
                selected = True
            except Exception:
                pass

        page.wait_for_timeout(1000)
        return True