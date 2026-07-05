"""NCESAuth — CAS SSO for ncesnext.com via cas-proxy.cra.moe.

NCES doesn't directly use SUSTech CAS. Instead, the login flow is:

    1. GET /login/oauth/              → 302 to sso.cra.ac.cn (Keycloak OIDC)
       OR
    1'. GET cas.sustech.edu.cn/cas/login?service=https://cas-proxy.cra.moe/callback
    2'. CAS validates credentials, redirects to cas-proxy with ticket
    3'. cas-proxy exchanges ticket, sets NCES session cookie
    4'. Redirects to ncesnext.com with the session

The cas-proxy pattern is the supported CAS path for NCES.

The full Keycloak OIDC dance (via sso.cra.ac.cn) is what the web browser
hits; headless via cas-proxy is simpler and is what NCESAuth implements.

For now, NCESAuth provides the Authorizer scaffolding + login() that
walks the cas-proxy CAS flow. Anubis (for the listing scraper) is
handled by NCESScraper separately.
"""
from __future__ import annotations

from typing import Optional

from ..sso.providers.cas import CASAuthorizer


class NCESAuth(CASAuthorizer):
    """CAS SSO for NCES via cas-proxy.cra.moe.

    Subclasses CASAuthorizer (same pattern as TISAuth, BBAuth).
    Reads credentials.txt from <skill_root>/credentials.txt.

    Usage:
        auth = NCESAuth()
        ok, reason = auth.ensure()
        if ok:
            r = auth.session.get("https://ncesnext.com/course/?sort_by=rating")
    """
    BASE_URL = "https://ncesnext.com"
    # The cas-proxy is what CAS redirects to. It exchanges the CAS ticket
    # for an NCES session cookie and 302s to ncesnext.com.
    SERVICE_URL = "https://cas-proxy.cra.moe/callback"
    XHR_MODE = False

    def _get_ticket_cookies(self, username: str, password: str) -> dict:
        """Walk CAS → cas-proxy → ncesnext.com. Return all cookies set.

        This is what CASAuthorizer.refresh() calls after we read credentials.
        Returns a dict of cookie_name → value covering CAS TGC +
        cas-proxy session + ncesnext.com session.
        """
        import requests as _req

        sess = _req.Session()
        sess.headers["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        # Step 1: GET CAS login page (no Anubis on CAS)
        r = sess.get(
            "https://cas.sustech.edu.cn/cas/login",
            params={"service": self.SERVICE_URL},
            allow_redirects=True,
        )
        r.raise_for_status()
        import re
        m = re.search(r'name="execution"\s+value="([^"]+)"', r.text)
        if not m:
            raise RuntimeError(
                "CAS execution token not found — login page format changed?"
            )
        execution = m.group(1)

        # Step 2: POST credentials
        r = sess.post(
            "https://cas.sustech.edu.cn/cas/login",
            params={"service": self.SERVICE_URL},
            data={
                "username": username,
                "password": password,
                "execution": execution,
                "_eventId": "submit",
                "submit": "登录",
            },
            allow_redirects=True,
        )
        r.raise_for_status()
        # After successful login, CAS sets TGC + redirects to service URL.
        # cas-proxy validates ticket, exchanges it, redirects to NCES.

        # Step 3: Visit a ncesnext.com page to ensure session is set.
        # cas-proxy's last redirect lands us here with a session cookie.
        r = sess.get(self.BASE_URL + "/", allow_redirects=True)
        r.raise_for_status()

        # Flatten all cookies from session jar into a single dict.
        # Note: Authorizer._build_session() handles per-host scoping.
        cookies = {}
        for c in sess.cookies:
            cookies[c.name] = c.value
        if not cookies:
            raise RuntimeError(
                "NCESAuth login succeeded but no cookies were set. "
                "CAS may have rejected credentials."
            )
        return cookies