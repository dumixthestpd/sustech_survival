"""
Shared SUSTech campus-firewall off-campus 403 detection.

Every SUSTech-internal service (PMS, booking, BB, faculty, library, TIS,
transit, RSC, ...) sits behind the campus firewall. From off-campus
(home, most VPNs) the edge returns the same plain-text body **before any
auth runs**:

    HTTP 403: "Access forbidden, please contact administrator."

This module centralises the detection so every submodule raises an
actionable error instead of a confusing ``JSONDecodeError`` on the plain
text. Previously inlined in ``pms/pms.py`` and ``booking/booking.py``;
deduplicated here as of 2026-06-22.

Why a shared helper:
- The literal body string is identical across services — keep the canonical
  copy in one place.
- The check itself is two lines — pointless to copy into every submodule.
- The user-facing hint varies by module name (PMS / Booking / Faculty / …),
  so we generate it from a name argument.
"""

from __future__ import annotations

import requests

# Canonical body string. If this changes, every submodule breaks at once.
# Don't change it without a coordinated rollout across all SUSTech clients.
OFF_CAMPUS_BODY = "Access forbidden, please contact administrator."


def looks_off_campus(r: requests.Response) -> bool:
    """True iff ``r`` is the SUSTech firewall's off-campus 403 response.

    Matches on **both** the status code AND the literal body string —
    matching either alone would yield false positives:
      * ``status_code == 403`` is also returned by auth failures
        (the body is then a JSON error, not this plain-text marker).
      * The body could theoretically appear inside a 200/500 payload
        (extremely unlikely, but defensive).

    Args:
        r: a ``requests.Response`` that has just been received. The body
           must be readable (callers usually have not called ``r.json()``
           yet — that's the whole point of this helper).

    Returns:
        ``True`` if the response is the off-campus firewall block.
    """
    if r.status_code != 403:
        return False
    return OFF_CAMPUS_BODY in (r.text or "")


def off_campus_hint(module: str) -> str:
    """Build the user-facing error message for an off-campus response.

    Args:
        module: short human-readable module name (e.g. ``"PMS"``,
                ``"Booking"``, ``"Faculty"``). Used as the leading word
                of the message so users know which subsystem fired.

    Returns:
        A multi-sentence hint telling the user to connect to campus
        network. Kept stable: tests assert on substrings (``"SUSTech"``,
        ``"campus"``, ``"Wi-Fi"``).
    """
    return (
        f"{module} server blocked the request (HTTP 403: 'Access forbidden, "
        f"please contact administrator.'). You are most likely NOT on the "
        f"SUSTech campus network — connect to campus Wi-Fi / wired, or this "
        f"module will not work."
    )