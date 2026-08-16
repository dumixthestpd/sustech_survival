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


# -- Current association ------------------------------------------------------

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
    Read current Wi-Fi association. Returns dict with keys:
      ssid, bssid, signal_dbm, channel, mac, security, phy_mode
    or None if not currently associated with any SSID.

    Detection strategy (newer macOS):
      1. `networksetup -getinfo "Wi-Fi"` — if it returns an IP, Wi-Fi is up.
         On newer macOS `networksetup -getairportnetwork` lies ("not associated"
         even when it is); we don't trust it.
      2. `system_profiler SPAirPortDataType` — parses "Current Network
         Information:" block. Slow (~3-5s) but reliable across macOS versions,
         including when the `airport` binary is gone (which it is on 14+).
      3. `ipconfig getsummary <iface>` — fallback for BSSID + DHCP lease
         when system_profiler is unavailable.

    `interface` defaults to the auto-detected Wi-Fi port (en1 on Mac Mini,
    en0 on most others).
    """
    if interface is None:
        interface = _wifi_interface()

    info: dict = {"interface": interface}

    # -- Try system_profiler (most reliable on 14+) --
    try:
        text_proc = subprocess.run(
            ["system_profiler", "SPAirPortDataType"],
            capture_output=True, text=True, timeout=15,
        )
        if text_proc.returncode == 0:
            block = _parse_current_network_block(text_proc.stdout)
            if block:
                info.update(block)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # -- ipconfig fallback for BSSID + DHCP info --
    if "bssid" not in info:
        try:
            proc = subprocess.run(
                ["ipconfig", "getsummary", interface],
                capture_output=True, text=True, timeout=5,
            )
            m = re.search(r"BSSID\s*:\s*(\S+)", proc.stdout)
            if m:
                info["bssid"] = m.group(1).upper()
        except Exception:
            pass

    if not info.get("ssid"):
        return None
    return info


def _parse_current_network_block(text: str) -> dict | None:
    """
    Parse the `system_profiler SPAirPortDataType` text output. The relevant
    block starts at "Current Network Information:" — the next indented line
    is the SSID, then a fixed list of fields. The block ends when we hit
    a line indented LESS than the SSID (i.e. we've left the per-SSID dict).

    Fields captured:
      - PHY Mode: 802.11ac
      - Channel: 52 (5GHz, 40MHz)
      - Security: WPA2 Enterprise  (or "None")
      - Signal / Noise: -52 dBm / -98 dBm  → signal_dbm
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if "Current Network Information" in lines[i] and ":" in lines[i]:
            # Next non-empty line is the SSID — capture its indent depth
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i >= len(lines):
                return None
            ssid_line = lines[i]
            ssid_indent = len(ssid_line) - len(ssid_line.lstrip())
            ssid = ssid_line.strip().rstrip(":")
            info: dict = {"ssid": ssid}
            i += 1
            # Walk indented lines, but stop the moment indent < ssid_indent
            while i < len(lines):
                line = lines[i]
                if not line.strip():
                    i += 1
                    continue
                indent = len(line) - len(line.lstrip())
                if indent < ssid_indent:
                    break  # exited the per-SSID dict
                stripped = line.strip()
                if ":" in stripped:
                    k, _, v = stripped.partition(":")
                    k = k.strip()
                    v = v.strip()
                    if k == "PHY Mode":
                        info["phy_mode"] = v
                    elif k == "Channel":
                        m = re.match(r"(\d+)\s*\(([^)]+)\)", v)
                        if m:
                            info["channel"] = int(m.group(1))
                            info["band"] = m.group(2)
                    elif k == "Security":
                        info["security"] = v
                    elif k.startswith("Signal"):
                        m = re.search(r"(-?\d+)\s*dBm", v)
                        if m:
                            info["signal_dbm"] = int(m.group(1))
                i += 1
            return info
        i += 1
    return None


# -- Recent events ------------------------------------------------------------

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