# =============================================================================
# wifi — SUSTech campus Wi-Fi (SUSTC-Wifi / SUSTC-Wifi-5G)
# =============================================================================
# Three capabilities:
#   1. Authentication via CAS — wraps `WiFiAuth().ensure()` for the campus
#      gateway at http://172.16.16.20. Same singleton pattern as TIS.
#   2. Status probe — `airport -I` / `networksetup` for current association;
#      tells you whether you're on SUSTC-Wifi, what signal, what MAC.
#   3. Log watcher — `log show --predicate 'subsystem == "com.apple.wifi"…'`
#      for recent association / roam / disconnect events, filtered to
#      SUSTC-Wifi / SUSTC-Wifi-5G SSIDs.
#
# The device-registration POST (after CAS auth, to the gateway at
# `http://172.16.16.20/srun_portal_sso`) is NOT implemented — needs a real
# Wi-Fi login with DevTools capture to reverse the MAC/IP POST body. Until
# then, `login()` returns a clear "CAS auth done, gateway registration
# pending" message.
# =============================================================================

from .status import current_association, list_recent_events, Event, SUSTECH_SSIDS

__all__ = ["current_association", "list_recent_events", "Event", "SUSTECH_SSIDS"]