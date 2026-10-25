# =============================================================================
# WSProvider — SUSTech Student Exchange System (ws.sustech.edu.cn)
# =============================================================================
# CAS login + session for the 外事工作服务系统 (Student Exchange/Abroad Portal).
#
# Auth flow (3-step CAS ticket exchange):
#   GET  /cas/login?service=ws.sustech.edu.cn/SUSTechHome.aspx
#   POST /cas/login  (execution + credentials + _eventId=submit)
#   GET  /SUSTechHome.aspx?ticket=...  鈫?JSESSIONID+ASP.NET_SessionId set here
#
# After login the session has cookies:
#   TGC               — CAS ticket-granting cookie
#   ASP.NET_SessionId — WS application session
#   SUserCode         — user ID (e.g. <sid>)
#   SUserRole         — role ID (e.g. 1007)
#
# Key API (cookies only, no auth header):
#   GET /Main/GetSmartLeftMenuTData.do                    鈫?JSON menu
#   GET /StudentExchange_2247/GetShortProjectListForStudent.do  鈫?program list
#   GET /StudentExchange_2247/GetShortProjectListCountForStudent.do 鈫?count
#   GET /StudentExchange_2247/ProjectDetail2247.do?ID=&Code=&token=  鈫?HTML detail
# =============================================================================
from __future__ import annotations
from sustech_survival import _net

import re
from urllib.parse import quote

import requests

from ..authorizer import Authorizer, AuthorizerError, CAS_BASE, UA

__all__ = ["WSProvider"]


def make_ws_session() -> requests.Session:
    """Return a requests.Session on the shared campus TLS adapter.

    WS needs ``OP_LEGACY_SERVER_CONNECT`` so TLS session resumption works
    against ws.sustech.edu.cn. That option — and the verification policy that
    goes with it — lives in ``sso._tls.LegacyTLSAdapter``, so every campus
    service shares one implementation instead of its own private one.
    """
    from .._tls import LegacyTLSAdapter

    sess = requests.Session()
    sess.mount("https://", LegacyTLSAdapter())
    return sess


class WSProvider(Authorizer):
    """
    CAS-based authorizer for ws.sustech.edu.cn.
    The WS system uses standard CAS 3.0 but sets ASP.NET-specific cookies
    (ASP.NET_SessionId, SUserCode, SUserRole).
    """

    BASE_URL = "https://ws.sustech.edu.cn"
    SERVICE_URL = "https://ws.sustech.edu.cn/SUSTechHome.aspx"

    cookie_names = ["ASP.NET_SessionId", "SUserCode", "SUserRole"]

    @property
    def cas_url(self) -> str:
        encoded = quote(self.SERVICE_URL, safe="")
        return f"{CAS_BASE}?service={encoded}"

    # -- Auth -----------------------------------------------------------------

    def _get_ticket_cookies(self, username: str, password: str) -> dict:
        """
        Perform the full CAS ticket exchange for WS.
        Uses LegacyAdapter throughout to avoid TLS errors.
        """
        sess = make_ws_session()
        sess.headers["User-Agent"] = UA

        # Step 1 — fetch CAS login page 鈫?extract execution token
        resp = sess.get(self.cas_url, timeout=_net.timeouts().service_timeout("ws"))
        if resp.status_code == 200 and "execution" in resp.text:
            m = re.search(r'name="execution"\s+value="([^"]+)"', resp.text)
            execution = m.group(1) if m else None
            if not execution:
                raise AuthorizerError("CAS execution token not found")
        elif resp.status_code >= 400:
            raise AuthorizerError(f"CAS login page returned {resp.status_code}")
        else:
            raise AuthorizerError("Unexpected CAS login page response")

        # Step 2 — POST credentials 鈫?receive ticket
        resp2 = sess.post(
            self.cas_url,
            data={
                "username": username,
                "password": password,
                "execution": execution,
                "_eventId": "submit",
            },
            allow_redirects=False,
            timeout=_net.timeouts().service_timeout("ws"),
        )

        ticket = None
        if resp2.status_code in (302, 303):
            loc = resp2.headers.get("Location", "")
            m = re.search(r"ticket=([^&]+)", loc)
            if m:
                ticket = m.group(1)

        if not ticket:
            body = resp2.text[:500] if resp2.text else "(empty)"
            raise AuthorizerError(f"No ticket ({resp2.status_code}): {body}")

        # Step 3 — exchange ticket at WS service URL
        sess.get(
            f"{self.SERVICE_URL}?ticket={ticket}",
            headers={"Accept": "text/html"},
            timeout=_net.timeouts().service_timeout("ws"),
            allow_redirects=True,
        )

        cookies = {c.name: c.value for c in sess.cookies}

        if "ASP.NET_SessionId" not in cookies:
            sess.get(
                f"{self.BASE_URL}/SUSTechHome.aspx",
                headers={"Accept": "text/html"},
                timeout=_net.timeouts().service_timeout("ws"),
                allow_redirects=True,
            )
            for c in sess.cookies:
                if c.name not in cookies:
                    cookies[c.name] = c.value

        missing = [n for n in self.cookie_names if n not in cookies]
        if missing:
            raise AuthorizerError(f"CAS OK but WS cookies missing: {missing}")

        return cookies

    def login(self, *, headless: bool = False) -> bool:
        """Read credentials, perform CAS ticket exchange, store cookies."""
        try:
            username, password = self.read_creds()
        except AuthorizerError:
            raise
        cookies = self._get_ticket_cookies(username, password)
        self._set_session(cookies)
        return True

    # -- Session ---------------------------------------------------------------

    def _build_session(self) -> requests.Session:
        """Return a WS session on the shared campus TLS adapter."""
        sess = make_ws_session()
        self._apply_cookies(sess, self._session_cache)
        return sess

    def check(self) -> tuple[bool, str]:
        """
        Verify WS session by hitting the menu API.
        Auto-refreshes if no session cached.
        """
        # Ensure we have a session first
        if not self._session_cache:
            if not self._refresh():
                return False, "WSAuth session not available"
        try:
            r = self.session.get(
                f"{self.BASE_URL}/Main/GetSmartLeftMenuTData.do",
                timeout=_net.timeouts().service_timeout("ws"),
            )
            if r.status_code == 200 and r.text.startswith("["):
                return True, ""
            return False, f"Menu API returned {r.status_code}"
        except Exception as e:
            return False, f"Could not reach WS: {e}"

