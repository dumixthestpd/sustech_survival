# =============================================================================
# wifi.status — Current association + recent Wi-Fi events for SUSTC SSIDs
# =============================================================================
# macOS-only. Two surfaces:
#
#   current_association() -> dict | None
#       Reads `airport -I` to get the currently-associated SSID, BSSID,
#       signal, MAC, channel. Returns None if not associated.
#
#   list_recent_events(minutes=60, ssid=("SUSTC-Wifi", "SUSTC-Wifi-5G"))
#       -> list[Event]
#       Streams `log show --predicate …` for the past N minutes, filters to
#       the SSIDs of interest (default: SUSTC-Wifi + 5G variant), returns
#       parsed events. Events come from com.apple.wifi / wifid / corewifi
#       subsystems; we surface:
#         - Associate
#         - Disassociate / link down
#         - Roam (between BSSIDs on same SSID)
#         - Auth / EAPOL (auth state changes)
# =============================================================================

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Iterable


SUSTECH_SSIDS = ("SUSTC-Wifi", "SUSTC-Wifi-5G")


@dataclass
class Event:
    timestamp: str   # ISO 8601, e.g. "2026-08-09T03:14:25+08:00"
    category: str    # "associate" | "disassociate" | "roam" | "auth" | "other"
    ssid: str | None
    bssid: str | None
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


# ── Current association ──────────────────────────────────────────────────────

def _wifi_interface() -> str:
    """Auto-discover the Wi-Fi interface (en0 on most Macs, en1 on Mac Mini / Ethernet-first)."""
    try:
        proc = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True, text=True, timeout=5,
        )
        lines = proc.stdout.splitlines()
        # Hardware Port: Wi-Fi  →  Device: enN
        for i, line in enumerate(lines):
            if "Hardware Port: Wi-Fi" in line:
                # Next non-empty line is "Device: enN"
                for nxt in lines[i + 1 : i + 3]:
                    if nxt.strip().startswith("Device:"):
                        return nxt.split(":", 1)[1].strip()
    except Exception:
        pass
    return "en0"  # fallback


def current_association(interface: str | None = None) -> dict | None:
    """
    Run `airport -I` and parse the result. Returns dict with keys:
      ssid, bssid, signal_dbm, channel, mac, security
    or None if not currently associated with any SSID.

    `airport` lives at /System/Library/PrivateFrameworks/Apple80211.framework/...
    — symlinked from the macOS Location Services prompt. Falls back to
    `networksetup -getairportnetwork` if airport is missing or interface
    is not Wi-Fi.

    `interface` defaults to auto-detected Wi-Fi port (en1 on Mac Mini, en0
    on most others).
    """
    if interface is None:
        interface = _wifi_interface()

    airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"

    try:
        proc = subprocess.run(
            [airport, "-I"],
            capture_output=True, text=True, timeout=5,
        )
        text = proc.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # Fallback: just check which SSID we're on (less detail)
        try:
            proc = subprocess.run(
                ["networksetup", "-getairportnetwork", interface],
                capture_output=True, text=True, timeout=5,
            )
            out = proc.stdout.strip()
            m = re.search(r"Current Wi-Fi Network:\s*(.*)", out)
            if m and m.group(1).strip():
                return {"ssid": m.group(1).strip(), "interface": interface}
            return None
        except Exception:
            return None

    info: dict = {"interface": interface}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip().lower()
        v = v.strip()
        if k == "ssid":
            info["ssid"] = v
        elif k == "bssid":
            info["bssid"] = v
        elif k == "agrctlrssi":
            try:
                info["signal_dbm"] = int(v)
            except ValueError:
                pass
        elif k == "channel":
            try:
                info["channel"] = int(v.split()[0])
            except (ValueError, IndexError):
                info["channel"] = v
        elif k == "mac":
            info["mac"] = v
        elif k == "security":
            info["security"] = v

    if not info.get("ssid"):
        return None
    return info


# ── Recent events ────────────────────────────────────────────────────────────

# log show line format (filtered to Wi-Fi subsystem):
#   2026-08-09 03:14:25.123456+0800  wifid  ...some message
_LOG_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+(?:[+-]\d{4})?)\s+(\S+)\s+(.*)$")


def list_recent_events(
    minutes: int = 60,
    ssids: Iterable[str] = SUSTECH_SSIDS,
) -> list[Event]:
    """
    Stream macOS unified log entries from the Wi-Fi subsystems over the last
    `minutes`, filter to lines mentioning any of `ssids`, classify into
    `Event` records. Returns empty list if no matching entries (or if `log`
    isn't available — Linux, sandbox, etc.).
    """
    since = datetime.now() - timedelta(minutes=minutes)
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")

    cmd = [
        "log", "show",
        "--predicate",
        'subsystem == "com.apple.wifi" OR subsystem == "com.apple.wifid"',
        "--start", since_str,
        "--style", "compact",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    ssid_set = set(ssids)
    out: list[Event] = []

    for line in proc.stdout.splitlines():
        if not any(s in line for s in ssid_set):
            continue
        m = _LOG_TS_RE.match(line)
        if not m:
            continue
        ts_raw, _subsystem, message = m.group(1), m.group(2), m.group(3)
        ssid = _extract_ssid(message, ssid_set)
        bssid = _extract_bssid(message)
        category = _classify(message)
        out.append(Event(
            timestamp=ts_raw,
            category=category,
            ssid=ssid,
            bssid=bssid,
            message=message.strip(),
        ))

    return out


def _extract_ssid(message: str, candidates: Iterable[str]) -> str | None:
    for s in candidates:
        if s in message:
            return s
    return None


_BSSID_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")


def _extract_bssid(message: str) -> str | None:
    m = _BSSID_RE.search(message)
    return m.group(0).upper() if m else None


def _classify(message: str) -> str:
    msg = message.lower()
    if "disassoc" in msg or "link down" in msg or "deauth" in msg:
        return "disassociate"
    if "roam" in msg:
        return "roam"
    if "associate" in msg or "joined" in msg or "connected to" in msg:
        return "associate"
    if "eapol" in msg or "auth" in msg or "802.1x" in msg:
        return "auth"
    return "other"