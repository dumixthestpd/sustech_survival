# =============================================================================
# WiFi Provider — SUSTech campus Wi-Fi (SUSTC-Wifi / SUSTC-Wifi-5G)
# =============================================================================
# Same CAS 3.0 handshake as every other SUSTech service. The only override
# vs the generic `CASAuthorizer` is the `SERVICE_URL` (the campus gateway
# redirect target) and the submit button text (登录, not 提交).
#
# Usage:
#     from sustech_survival.sso import WiFiAuth
#     auth = WiFiAuth()
#     ok, reason = auth.ensure()       # same singleton pattern as TIS
#
# NOTE: This handles the **CAS auth step**. The gateway at
#   `http://172.16.16.20/srun_portal_sso`
# typically requires a **second POST** with the device MAC / IP — the shape
# of that call is still unknown as of 2026-08-09 (it needs a real Wi-Fi
# login + DevTools capture to reverse-engineer). Until then,
# `WiFiAuth().ensure()` only gets you through CAS; the device registration
# on the gateway is a separate step (see `wifi login` CLI which is a
# placeholder for it).
# =============================================================================

from .cas import CASAuthorizer


class WiFiAuth(CASAuthorizer):
    """
    SUSTech campus Wi-Fi — CAS-authenticated.

    Service URLs:
      - Login: https://cas.sustech.edu.cn/cas/login?service=http://172.16.16.20/srun_portal_sso
      - Gateway: http://172.16.16.20  (intranet; only reachable on SUSTC-Wifi or VPN)

    SSIDs (legacy spelling, NOT "SUSTech"):
      - SUSTC-Wifi
      - SUSTC-Wifi-5G
    """

    BASE_URL = "http://172.16.16.20"
    SERVICE_URL = "http://172.16.16.20/srun_portal_sso"
    SUBMIT_VALUE = "登录"  # Wi-Fi login button uses 登录, not 默认 提交