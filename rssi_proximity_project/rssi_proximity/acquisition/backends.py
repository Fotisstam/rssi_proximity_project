"""RSSI backends. All are Qt-free so they can be tested from a plain script."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from rssi_proximity.acquisition import netsh
from rssi_proximity.acquisition.netsh import AccessPoint, ScanError, normalize_bssid, pct_to_dbm
from rssi_proximity.config import DEFAULT_DISTANCES_M


@dataclass(frozen=True)
class Target:
    """The access point being tracked. bssid=None follows the strongest BSSID of the SSID."""
    ssid: str
    bssid: Optional[str] = None
    band: str = ""

    def describe(self) -> str:
        parts = [self.ssid]
        if self.bssid:
            parts.append(self.bssid)
        if self.band:
            parts.append(self.band)
        return "  ·  ".join(parts)


@dataclass(frozen=True)
class Reading:
    t: float            # epoch seconds
    signal_pct: float
    rssi_dbm: float
    ssid: str
    bssid: str
    source: str         # "interface" | "scan" | "simulated"


class Backend:
    name = "base"

    def list_access_points(self) -> List[AccessPoint]:
        raise NotImplementedError

    def read(self, target: Target) -> Reading:
        raise NotImplementedError


def _matches(ap: AccessPoint, target: Target) -> bool:
    if target.bssid:
        return normalize_bssid(ap.bssid) == normalize_bssid(target.bssid)
    return ap.ssid == target.ssid


class NetshBackend(Backend):
    """Windows backend.

    read() first asks `show interfaces` (fast, refreshed about once a second) and
    uses it when we are connected to the target AP. Otherwise it falls back to
    `show networks mode=bssid`, which works for any visible AP but Windows only
    refreshes it every few seconds, so consecutive samples may repeat.
    """

    name = "netsh"

    def list_access_points(self) -> List[AccessPoint]:
        text = netsh.run_netsh("show", "networks", "mode=bssid")
        aps = netsh.parse_networks(text)
        if not aps:
            raise ScanError(netsh.explain_empty_scan(text))
        return aps

    def read(self, target: Target) -> Reading:
        connected = netsh.parse_interfaces(netsh.run_netsh("show", "interfaces"))
        if connected is not None and _matches(connected, target):
            return self._reading(connected, "interface")

        text = netsh.run_netsh("show", "networks", "mode=bssid")
        candidates = [ap for ap in netsh.parse_networks(text) if _matches(ap, target)]
        if not candidates:
            raise ScanError(f"'{target.ssid}' is not visible right now.")
        best = max(candidates, key=lambda ap: ap.signal_pct)
        return self._reading(best, "scan")

    @staticmethod
    def _reading(ap: AccessPoint, source: str) -> Reading:
        return Reading(time.time(), float(ap.signal_pct), ap.rssi_dbm, ap.ssid, ap.bssid, source)


class SimControls:
    """Mutable knobs for the simulator (the GUI toolbar edits these)."""

    def __init__(self) -> None:
        self.zone = "near"
        self.obstacle_db = 0.0


class SimulatedBackend(Backend):
    """Synthetic RSSI from a log-distance model: handy for trying the app off Windows.

    The 'true' position is chosen with `zone` (near/medium/far -> a distance), and
    `obstacle_db` adds extra attenuation so the effect of obstacles can be demoed.
    """

    name = "simulated"
    FAKE_APS = (
        AccessPoint("Lab-WiFi", "aa:bb:cc:00:00:01", 80, "5 GHz", 36),
        AccessPoint("Lab-WiFi", "aa:bb:cc:00:00:02", 70, "2.4 GHz", 6),
        AccessPoint("Neighbour-AP", "de:ad:be:ef:00:01", 45, "2.4 GHz", 11),
    )

    def __init__(self, seed: Optional[int] = None,
                 zone_getter: Optional[Callable[[], str]] = None,
                 obstacle_getter: Optional[Callable[[], float]] = None):
        self._rng = random.Random(seed)
        self._zone_getter = zone_getter or (lambda: "near")
        self._obstacle_getter = obstacle_getter or (lambda: 0.0)
        self._fade = 0.0

    def list_access_points(self) -> List[AccessPoint]:
        return list(self.FAKE_APS)

    def read(self, target: Target) -> Reading:
        distance = DEFAULT_DISTANCES_M[self._zone_getter()]
        mean = -52.0 - 25.0 * math.log10(max(distance, 0.3)) - self._obstacle_getter()
        # slow fading (AR(1)) plus fast measurement noise, like a real indoor channel
        self._fade = 0.8 * self._fade + self._rng.gauss(0.0, 1.0)
        value = mean + self._fade + self._rng.gauss(0.0, 1.5)
        pct = max(0, min(100, round((value + 100.0) * 2.0)))
        bssid = target.bssid or self.FAKE_APS[0].bssid
        return Reading(time.time(), float(pct), pct_to_dbm(pct), target.ssid, bssid, "simulated")
