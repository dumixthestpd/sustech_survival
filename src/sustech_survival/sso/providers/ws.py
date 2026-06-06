# =============================================================================
# WSProvider — SUSTech Student Exchange System (ws.sustech.edu.cn)
# =============================================================================
# CAS login + session for the 外事工作服务系统 (Student Exchange/Abroad Portal).
#
# Auth flow (3-step CAS ticket exchange):
#   GET  /cas/login?service=ws.sustech.edu.cn/SUSTechHome.aspx
#   POST /cas/login  (execution + credentials + _eventId=submit)
#   GET  /SUSTechHome.aspx?ticket=...  ← JSESSIONID+ASP.NET_SessionId set here
#
# After login the session has cookies:
#   TGC               — CAS ticket-granting cookie
#   ASP.NET_SessionId — WS application session
#   SUserCode         — user ID (e.g. 12413021)
#   SUserRole         — role ID (e.g. 1007)
#
# Key API (cookies only, no auth header):
#   GET /Main/GetSmartLeftMenuTData.do                    ← JSON menu
#   GET /StudentExchange_2247/GetShortProjectListForStudent.do  ← program list
#   GET /StudentExchange_2247/GetShortProjectListCountForStudent.do ← count
#   GET /StudentExchange_2247/ProjectDetail2247.do?ID=&Code=&token=  ← HTML detail
# =============================================================================
from __future__ import annotations

import re
import ssl
from urllib.parse import quote

import requests

from ..authorizer import Authorizer, AuthorizerError, CAS_BASE, UA

__all__ = ["WSProvider"]


def build_legacy_adapter():
    """
    Build a LegacyAdapter class that uses OP_LEGACY_SERVER_CONNECT so TLS
    session resumption works reliably against ws.sustech.edu.cn.
    Returned as a class (not instance) so HTTPAdapter can instantiate it.
    """
    _OP_LEGACY = getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    legacy_ctx = ssl.create_default_context()
    legacy_ctx.options |= _OP_LEGACY

    from requests.adapters import (
        HTTPAdapter,
        _urllib3_request_context,
        parse_url,
        prepend_scheme_if_needed,
        select_proxy,
    )

    class LegacyAdapter(HTTPAdapter):
        def get_connection_with_tls_context(
            self, request, verify, proxies=None, cert=None, poolmanager=None
        ):
            proxy = select_proxy(request.url, proxies)
            host_params, pool_kwargs = _urllib3_request_context(
                request, verify, cert, self.poolmanager,
            )
            pool_kwargs["ssl_context"] = legacy_ctx
            pool_kwargs["ssl_context"].check_hostname = False
            if proxy:
                proxy = prepend_scheme_if_needed(proxy, "http")
                proxy_url = parse_url(proxy)
                if not proxy_url.host:
                    from requests.exceptions import InvalidProxyURL
                    raise InvalidProxyURL("Malformed proxy URL")
                proxy_manager = self.proxy_manager_for(proxy)
                return proxy_manager.connection_from_host(**host_params, pool_kwargs=pool_kwargs)
            return self.poolmanager.connection_from_host(**host_params, pool_kwargs=pool_kwargs)

    return LegacyAdapter


def sess() -> requests.Session:
    """Return a requests.Session with LegacyAdapter mounted."""
    sess = requests.Session()
    sess.mount("https://", build_legacy_adapter()())
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

    SESSION_SUBDIR = "ws"

    @property
    def cas_url(self) -> str:
        encoded = quote(self.SERVICE_URL, safe="")
        return f"{CAS_BASE}?service={encoded}"

    @property
    def session_file(self):
        return self.submodule_dir / "session.json"

    # ── Auth ─────────────────────────────────────────────────────────────────

    def get_ticket_cookies(self, username: str, password: str) -> dict:
        """
        Perform the full CAS ticket exchange for WS.
        Uses LegacyAdapter throughout to avoid TLS errors.
        """
        sess = sess()
        sess.headers["User-Agent"] = UA

        # Step 1 — fetch CAS login page → extract execution token
        resp = sess.get(self.cas_url, timeout=10)
        if resp.status_code == 200 and "execution" in resp.text:
            m = re.search(r'name="execution"\s+value="([^"]+)"', resp.text)
            execution = m.group(1) if m else None
            if not execution:
                raise AuthorizerError("CAS execution token not found")
        elif resp.status_code >= 400:
            raise AuthorizerError(f"CAS login page returned {resp.status_code}")
        else:
            raise AuthorizerError("Unexpected CAS login page response")

        # Step 2 — POST credentials → receive ticket
        resp2 = sess.post(
            self.cas_url,
            data={
                "username": username,
                "password": password,
                "execution": execution,
                "_eventId": "submit",
            },
            allow_redirects=False,
            timeout=10,
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
            timeout=10,
            allow_redirects=True,
        )

        cookies = {c.name: c.value for c in sess.cookies}

        if "ASP.NET_SessionId" not in cookies:
            sess.get(
                f"{self.BASE_URL}/SUSTechHome.aspx",
                headers={"Accept": "text/html"},
                timeout=10,
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
        cookies = self.get_ticket_cookies(username, password)
        self.save(cookies)
        return True

    # ── Session ───────────────────────────────────────────────────────────────

    @property
    def session(self) -> requests.Session:
        """
        A requests.Session with LegacyAdapter so TLS session resumption works
        reliably against ws.sustech.edu.cn.
        """
        raw = self.load()
        sess = sess()
        self.apply_cookies(sess, raw)
        return sess

    def check(self) -> tuple[bool, str]:
        """
        Verify WS session by hitting the menu API.
        """
        try:
            r = self.session.get(
                f"{self.BASE_URL}/Main/GetSmartLeftMenuTData.do",
                timeout=10,
            )
            if r.status_code == 200 and r.text.startswith("["):
                return True, ""
            return False, f"Menu API returned {r.status_code}"
        except Exception as e:
            return False, f"Could not reach WS: {e}"