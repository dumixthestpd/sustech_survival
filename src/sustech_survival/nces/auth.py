"""NCESAuth — CAS SSO for ncesnext.com via Keycloak OIDC + cas-proxy.

The actual auth surface is a 3-party dance:

    1. GET /login/oauth/
       → 302 to Keycloak auth URL
       https://sso.cra.ac.cn/realms/cra-service-realm/protocol/openid-connect/auth
         ?response_type=code
         &client_id=cra-nces
         &redirect_uri=https://ncesnext.com/login/oauth/callback/
         &scope=profile
         &state=...

    2. GET Keycloak auth URL
       → 200 page with "Login with SUSTech CAS" link:
         /realms/cra-service-realm/broker/cra-cas-proxy-direct/login?...

    3. GET broker init URL  (Keycloak's IdP init for the CAS via cas-proxy)
       → 303 to cas-proxy authorize:
         https://cas-proxy.cra.moe/authorize?scope=openid&state=...

    4. cas-proxy → 302 to CAS:
         https://cas.sustech.edu.cn/cas/login
           ?service=https%3A%2F%2Fcas-proxy.cra.moe%2Fcallback

    5. POST credentials to CAS
       → 302 to cas-proxy/callback?ticket=ST-...

    6. cas-proxy validates ticket with CAS, exchanges for Keycloak token,
       redirects back to Keycloak broker endpoint

    7. Keycloak issues OIDC code, redirects to:
         https://ncesnext.com/login/oauth/callback/?code=...&state=...

    8. ncesnext.com validates code, sets its session cookie,
       redirects to https://ncesnext.com/

After step 8 the session is established. Subsequent requests use the
ncesnext.com session cookie — no re-auth needed until expiry.

Direct CAS → cas-proxy/callback DOES NOT WORK (no Keycloak session
context). Must go through the full chain.

This is what NCESAuth.login() walks.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

import requests

from ..sso.providers.cas import CASAuthorizer

if TYPE_CHECKING:
    pass


class NCESAuth(CASAuthorizer):
    """CAS SSO for NCES via Keycloak OIDC + cas-proxy.cra.moe.

    Subclasses CASAuthorizer (same pattern as TISAuth, BBAuth).
    Reads credentials from <skill_root>/credentials.txt.

    Usage:
        auth = NCESAuth()
        ok, reason = auth.login()
        if ok:
            r = auth.session.get("https://ncesnext.com/")
    """
    BASE_URL = "https://ncesnext.com"

    # Used by CASAuthorizer._build_session() as a no-op fallback.
    # Real login() bypasses the parent class — it walks the full
    # Keycloak + cas-proxy + CAS dance.
    SERVICE_URL = "https://cas-proxy.cra.moe/callback"
    XHR_MODE = False

    # User-Agent must look like a real browser — Keycloak returns 403
    # for headless UAs on some endpoints.
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # -- Override session handling for multi-domain cookies ----------------
    #
    # The base Authorizer._apply_cookies() scopes all cookies to BASE_URL's
    # domain. NCES auth spans THREE domains (ncesnext.com, sso.cra.ac.cn,
    # cas.sustech.edu.cn), so we override _build_session() to keep a
    # dedicated requests.Session with its full multi-domain cookie jar.

    def _set_session(self, cookies: dict):
        """Override: the parent's _set_session() doesn't invalidate
        _cached_session, but the parent's _refresh() sets it to None
        right after calling _set_session(). Override _refresh() too.
        """
        self._session_cache = cookies
        import time
        self._session_time = time.time()

    def _refresh(self) -> bool:
        """Override the parent's _refresh() — keep our persistent session.

        Parent's flow invalidates _cached_session after we walk the chain.
        For NCES we need to KEEP the multi-domain session alive, so we
        do the chain walk ourselves and skip the parent's session cache.
        """
        try:
            username, password = self._read_creds()
        except Exception as e:
            print(f"❌ NCESAuth refresh skipped: {e}")
            return False
        sess = self._cached_session
        if sess is None:
            sess = requests.Session()
            sess.headers["User-Agent"] = self.USER_AGENT
            self._cached_session = sess
        if not self._login_chain(sess, username, password):
            print(f"❌ NCESAuth login chain failed")
            return False
        # Set a sentinel in _session_cache so the parent's check()
        # thinks we're fresh (TTL is 25min; we keep session warm manually).
        self._session_cache = {"_": "sentinel"}
        import time
        self._session_time = time.time()
        cls = self.__class__.__name__
        print(f"✅ {cls} session refreshed "
              f"({len(sess.cookies)} multi-domain cookies)")
        return True

    def _build_session(self) -> requests.Session:
        """Return the persistent session (one per Authorizer singleton).

        Override: instead of building a fresh Session from cached cookies
        (which would lose the cross-domain jar), we keep one session
        object across calls. The session may be unauth'd (first call
        before _get_ticket_cookies walks the chain) — callers should
        invoke ensure()/refresh() to authenticate.
        """
        if self._cached_session is None:
            self._cached_session = requests.Session()
            self._cached_session.headers["User-Agent"] = self.USER_AGENT
        return self._cached_session

    def _login_chain(
        self,
        sess: "requests.Session",
        username: str,
        password: str,
    ) -> dict[str, str]:
        """Walk the full OIDC + cas-proxy + CAS chain.

        Returns a dict of cookies to install in the Authorizer session.
        Empty dict on failure.

        ncesnext.com (and its auth endpoints) are behind Anubis PoW. We
        solve it once before walking the chain so subsequent redirects
        don't get blocked.
        """
        # Step 0: Solve Anubis if needed (gets 7-day cookie)
        self._solve_anubis_if_needed(sess)

        # Step 1: GET /login/oauth/ — 302 to Keycloak auth URL
        r = sess.get(
            "https://ncesnext.com/login/oauth/",
            allow_redirects=False,
            timeout=15,
        )
        if r.status_code != 302:
            return {}
        kc_url = r.headers.get("Location", "")
        if "sso.cra.ac.cn" not in kc_url:
            return {}

        # Step 2: Use kc_idp_hint to skip the Keycloak login form and go
        # directly to the CAS broker (cra-cas-proxy-direct).
        hint_url = kc_url + "&kc_idp_hint=cra-cas-proxy-direct"
        r_broker = sess.get(hint_url, timeout=15, allow_redirects=False)
        if r_broker.status_code not in (302, 303):
            return {}

        # Step 3: Follow broker → cas-proxy/authorize → CAS login page
        r = sess.get(r_broker.headers["Location"], allow_redirects=True, timeout=15)
        if r.status_code != 200:
            return {}

        # Extract execution token from CAS login page
        execution_m = re.search(
            r'name="execution"\s+value="([^"]+)"', r.text
        )
        if not execution_m:
            return {}
        execution = execution_m.group(1)
        # The service URL is in the final redirect that landed us at CAS
        service_m = re.search(r"service=([^&\"]+)", r.url)
        if not service_m:
            return {}
        from urllib.parse import unquote
        service_decoded = unquote(service_m.group(1))

        # Walk the CAS POST through cas-proxy → Keycloak → ncesnext.com
        # callback → final landing page (with session cookie).
        r = sess.post(
            "https://cas.sustech.edu.cn/cas/login",
            params={"service": service_decoded},
            data={
                "username": username,
                "password": password,
                "execution": execution,
                "_eventId": "submit",
                "submit": "登录",
            },
            allow_redirects=True,
            timeout=30,
        )
        # Verify: landed on ncesnext.com AND navbar shows a logged-in user
        # link (e.g. `<a href="/user/2862">Lynn_Reed</a>`). The "登录"
        # text in the navbar is a permanent UI element, NOT a logged-out
        # indicator — only the user profile link is reliable.
        if r.status_code != 200 or "ncesnext.com" not in r.url:
            return {}
        if not re.search(r'href="/user/\d+"', r.text):
            return {}

        # Flatten all cookies set during the chain
        cookies = {}
        for c in sess.cookies:
            cookies[c.name] = c.value
        return cookies

    @staticmethod
    def _solve_anubis_if_needed(sess: "requests.Session") -> None:
        """Solve Anubis PoW on ncesnext.com so the auth chain isn't blocked.

        Same algorithm as NCESScraper._solve_anubis() — kept inline here
        so NCESAuth can be used independently of the scraper (and so the
        [nces] extra isn't required for auth — only for scraping).
        """
        r = sess.get("https://ncesnext.com/course/?sort_by=rating", timeout=15)
        m = re.search(
            r'"id":"([0-9a-f-]{36})"[^}]*"randomData":"([0-9a-f]+)"'
            r'[^}]*"difficulty":(\d+)',
            r.text,
        )
        if not m:
            return  # already past Anubis or no challenge
        import hashlib as _hl
        ch_id, ch_data, diff = m.group(1), m.group(2), int(m.group(3))
        prefix = "0" * diff
        n = 0
        while True:
            h = _hl.sha256((ch_data + str(n)).encode()).hexdigest()
            if h.startswith(prefix):
                break
            n += 1
        sess.get(
            "https://ncesnext.com/.within.website/x/cmd/anubis/api/pass-challenge",
            params={
                "id": ch_id,
                "response": h,
                "nonce": n,
                "redir": "https://ncesnext.com/course/?sort_by=rating",
                "elapsedTime": 50,
            },
            timeout=15,
        )