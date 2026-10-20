"""Calibration model: per-zone representative RSSI, decision thresholds, classifier.

Classification rule (zones are ordered by signal strength, near strongest):

    smoothed >= t_near_medium           -> near
    smoothed >= t_medium_far            -> medium
    otherwise                           -> far
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from rssi_proximity.config import (
    DEFAULT_FILTER, DEFAULT_WINDOW, FILTER_KINDS, MIN_SAMPLES_PER_ZONE,
    REPRESENTATIVES, THRESHOLD_METHODS, ZONES,
)
from rssi_proximity.processing.filters import smooth, warmup_length
from rssi_proximity.processing.stats import describe
from rssi_proximity.storage.csv_logger import Run


class ModelError(ValueError):
    """Calibration data cannot produce a usable model (message is user-facing)."""


def smoothed_samples(run: Run, kind: str, window: int) -> np.ndarray:
    """Run's RSSI after causal smoothing, warm-up samples removed."""
    values = smooth(run.rssi, kind, window)
    return values[warmup_length(kind, window):]


@dataclass
class ProximityModel:
    ssid: str
    bssid: str
    filter_kind: str
    window: int
    representative: str
    threshold_method: str
    values: Dict[str, float]            # representative RSSI per zone
    spreads: Dict[str, float]           # std per zone (of smoothed values)
    counts: Dict[str, int]              # smoothed samples used per zone
    distances: Dict[str, float]         # metres, informational
    t_near_medium: float
    t_medium_far: float
    calibration_sessions: List[str] = field(default_factory=list)
    created: str = ""

    # ── classification ────────────────────────────────────────────────────
    @property
    def thresholds(self) -> Tuple[float, float]:
        return (self.t_near_medium, self.t_medium_far)

    def classify(self, smoothed_dbm: float) -> str:
        if smoothed_dbm >= self.t_near_medium:
            return "near"
        if smoothed_dbm >= self.t_medium_far:
            return "medium"
        return "far"

    def classify_many(self, smoothed_dbm: Sequence[float]) -> List[str]:
        return [self.classify(v) for v in smoothed_dbm]

    # ── persistence ───────────────────────────────────────────────────────
    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "ProximityModel":
        data = json.loads(text)
        try:
            return cls(**data)
        except TypeError as error:
            raise ModelError(f"model file is not compatible: {error}") from error


def compute_thresholds(values: Dict[str, float], spreads: Dict[str, float],
                       method: str) -> Tuple[float, float]:
    near, medium, far = values["near"], values["medium"], values["far"]
    if method == "midpoint":
        return (near + medium) / 2.0, (medium + far) / 2.0

    def weighted(strong: float, s_strong: float, weak: float, s_weak: float) -> float:
        total = s_strong + s_weak
        if total <= 0:
            return (strong + weak) / 2.0
        # equal distance, measured in standard deviations, from both zone values
        return weak + (strong - weak) * s_weak / total

    return (weighted(near, spreads["near"], medium, spreads["medium"]),
            weighted(medium, spreads["medium"], far, spreads["far"]))


def fit_model(runs: Sequence[Run], *, ssid: str = "", bssid: str = "",
              filter_kind: str = DEFAULT_FILTER, window: int = DEFAULT_WINDOW,
              representative: str = "median", threshold_method: str = "midpoint",
              distances: Optional[Dict[str, float]] = None) -> ProximityModel:
    if filter_kind not in FILTER_KINDS:
        raise ModelError(f"unknown filter: {filter_kind}")
    if representative not in REPRESENTATIVES:
        raise ModelError(f"unknown representative value: {representative}")
    if threshold_method not in THRESHOLD_METHODS:
        raise ModelError(f"unknown threshold method: {threshold_method}")

    per_zone: Dict[str, List[np.ndarray]] = {zone: [] for zone in ZONES}
    for run in runs:
        per_zone[run.zone].append(smoothed_samples(run, filter_kind, window))

    values: Dict[str, float] = {}
    spreads: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for zone in ZONES:
        chunks = [c for c in per_zone[zone] if c.size]
        merged = np.concatenate(chunks) if chunks else np.array([])
        if merged.size < MIN_SAMPLES_PER_ZONE:
            raise ModelError(
                f"Zone '{zone}' has {merged.size} usable samples "
                f"(need at least {MIN_SAMPLES_PER_ZONE}). Record more calibration data for it."
            )
        stats = describe(merged)
        values[zone] = stats[representative]
        spreads[zone] = stats["std"]
        counts[zone] = stats["n"]

    if not (values["near"] > values["medium"] > values["far"]):
        raise ModelError(
            "Zone signal strengths are not ordered near > medium > far "
            f"({values['near']:.1f}, {values['medium']:.1f}, {values['far']:.1f} dBm). "
            "Check the zone positions, or re-record the zones that look wrong."
        )

    t1, t2 = compute_thresholds(values, spreads, threshold_method)
    return ProximityModel(
        ssid=ssid, bssid=bssid, filter_kind=filter_kind, window=int(window),
        representative=representative, threshold_method=threshold_method,
        values=values, spreads=spreads, counts=counts,
        distances=dict(distances or {}), t_near_medium=t1, t_medium_far=t2,
        calibration_sessions=sorted({run.session for run in runs}),
        created=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )


class LiveClassifier:
    """Adds hysteresis for the live display so the label does not flicker at a boundary.

    The class only changes once the smoothed RSSI is `margin_db` beyond the threshold.
    (The offline evaluation uses the plain thresholds, i.e. margin 0.)
    """

    def __init__(self, model: ProximityModel, margin_db: float = 1.0):
        self.model = model
        self.margin_db = max(0.0, float(margin_db))
        self.state: Optional[str] = None

    def reset(self) -> None:
        self.state = None

    def update(self, smoothed_dbm: float) -> str:
        if self.state is None:
            self.state = self.model.classify(smoothed_dbm)
            return self.state
        thresholds = self.model.thresholds   # boundary i separates ZONES[i] and ZONES[i+1]
        i = ZONES.index(self.state)
        moved = True
        while moved:
            moved = False
            if i < len(ZONES) - 1 and smoothed_dbm < thresholds[i] - self.margin_db:
                i += 1
                moved = True
            elif i > 0 and smoothed_dbm > thresholds[i - 1] + self.margin_db:
                i -= 1
                moved = True
        self.state = ZONES[i]
        return self.state
