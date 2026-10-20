"""Windows `netsh wlan` access: parsing (pure functions) and the subprocess call.

The parsers deliberately avoid depending on the Windows display language
(a Greek Windows prints translated labels such as the signal/channel names),
so they key on structure instead: "SSID <n> :", "BSSID <n> :", MAC addresses,
`NN%` values and `N.N GHz` values.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

from rssi_proximity.config import NETSH_TIMEOUT_S

HIDDEN_SSID = "<hidden>"
_MAC = r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}"

_SSID_HDR = re.compile(r"^\s*SSID\s+\d+\s*:\s*(.*?)\s*$")
_BSSID_HDR = re.compile(rf"^\s*BSSID\s+\d+\s*:\s*({_MAC})\s*$")
_PERCENT = re.compile(r":\s*(\d{1,3})\s*%\s*$")
_BAND = re.compile(r":\s*(2\.4|5|6)\s*GHz\s*$", re.IGNORECASE)
_NUMBER_ONLY = re.compile(r"^\s*[^:\d][^:]*:\s*(\d{1,3})\s*$")

_IF_BSSID = re.compile(rf"^\s*(?:AP\s+)?BSSID\s*:\s*({_MAC})\s*$", re.IGNORECASE)
_IF_SSID = re.compile(r"^\s*SSID\s*:\s*(.*?)\s*$")


class ScanError(RuntimeError):
    """Raised when RSSI cannot be read (message is shown to the user)."""


def pct_to_dbm(signal_pct: float) -> float:
    """Windows' signal quality (0-100 %) -> approximate dBm.

    Windows documents the mapping 0 % = -100 dBm and 100 % = -50 dBm,
    linear in between, i.e. dBm = pct / 2 - 100. It is an approximation:
    the driver's own dBm value is not exposed by netsh.
    """
    return signal_pct / 2.0 - 100.0


def normalize_bssid(bssid: str) -> str:
    return bssid.strip().lower().replace("-", ":")


@dataclass(frozen=True)
class AccessPoint:
    ssid: str
    bssid: str
    signal_pct: int
    band: str = ""
    channel: Optional[int] = None

    @property
    def rssi_dbm(self) -> float:
        return pct_to_dbm(self.signal_pct)


def parse_networks(text: str) -> List[AccessPoint]:
    """Parse `netsh wlan show networks mode=bssid` into one entry per BSSID."""
    aps: List[AccessPoint] = []
    ssid = HIDDEN_SSID
    cur: Optional[dict] = None

    def flush():
        nonlocal cur
        if cur is not None and cur.get("signal") is not None:
            aps.append(AccessPoint(
                ssid=cur["ssid"], bssid=cur["bssid"], signal_pct=cur["signal"],
                band=cur.get("band", ""), channel=cur.get("channel"),
            ))
        cur = None

    for line in text.splitlines():
        m = _SSID_HDR.match(line)
        if m:
            flush()
            ssid = m.group(1) or HIDDEN_SSID
            continue
        m = _BSSID_HDR.match(line)
        if m:
            flush()
            cur = {"ssid": ssid, "bssid": normalize_bssid(m.group(1)), "signal": None}
            continue
        if cur is None:
            continue
        if cur["signal"] is None:
            m = _PERCENT.search(line)
            if m:
                cur["signal"] = max(0, min(100, int(m.group(1))))
                continue
        m = _BAND.search(line)
        if m and "band" not in cur:
            cur["band"] = f"{m.group(1)} GHz"
            continue
        m = _NUMBER_ONLY.match(line)
        if m and cur["signal"] is not None and "channel" not in cur:
            cur["channel"] = int(m.group(1))
    flush()
    return aps


def parse_interfaces(text: str) -> Optional[AccessPoint]:
    """Parse `netsh wlan show interfaces` -> the AP we are connected to (or None)."""
    ssid: Optional[str] = None
    bssid: Optional[str] = None
    signal: Optional[int] = None
    for line in text.splitlines():
        m = _IF_BSSID.match(line)
        if m:
            bssid = normalize_bssid(m.group(1))
            continue
        m = _IF_SSID.match(line)
        if m and ssid is None:
            ssid = m.group(1) or HIDDEN_SSID
            continue
        m = _PERCENT.search(line)
        if m and signal is None:
            signal = max(0, min(100, int(m.group(1))))
    if bssid is None or signal is None:
        return None
    return AccessPoint(ssid=ssid or HIDDEN_SSID, bssid=bssid, signal_pct=signal)


# ── subprocess ───────────────────────────────────────────────────────────────
def _decode(raw: bytes) -> str:
    # netsh writes in the console's OEM code page (cp737 on Greek Windows).
    for encoding in ("oem", "utf-8"):
        try:
            return raw.decode(encoding, errors="replace")
        except LookupError:
            continue
    return raw.decode("latin-1", errors="replace")


def run_netsh(*args: str, timeout: float = NETSH_TIMEOUT_S) -> str:
    if not sys.platform.startswith("win"):
        raise ScanError("The netsh backend only works on Windows (use --simulate to try the app).")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            ["netsh", "wlan", *args], capture_output=True, timeout=timeout,
            creationflags=flags,
        )
    except FileNotFoundError as exc:
        raise ScanError("netsh was not found on this system.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScanError("netsh timed out - is Wi-Fi turned on?") from exc
    return _decode(proc.stdout) + _decode(proc.stderr)


def explain_empty_scan(text: str) -> str:
    """Best-effort hint for the usual reasons a scan returns nothing."""
    lowered = text.lower()
    if "location" in lowered or "ms-settings" in lowered:
        return ("Windows blocked the scan: turn on Settings > Privacy & security > "
                "Location (and 'Let desktop apps access your location').")
    if "no wireless interface" in lowered or "wlan autoconfig" in lowered:
        return "No Wi-Fi adapter is available (is Wi-Fi switched on?)."
    return "No access points were found. Check that Wi-Fi is on and try again."
