"""Evaluation of a model on measurements that were NOT used to set the thresholds."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

import numpy as np

from rssi_proximity.classify.model import ProximityModel, smoothed_samples
from rssi_proximity.config import ZONES
from rssi_proximity.storage.csv_logger import Run


@dataclass
class ConditionStats:
    condition: str
    n: int
    accuracy: float
    mean_rssi: float
    std_rssi: float
    zone_means: Dict[str, float] = field(default_factory=dict)   # mean smoothed RSSI per zone


@dataclass
class EvalResult:
    n: int
    correct: int
    accuracy: float                      # 0..1
    confusion: np.ndarray                # rows = true zone, cols = predicted zone
    per_zone_accuracy: Dict[str, float]
    per_condition: List[ConditionStats]
    true_labels: List[str] = field(repr=False, default_factory=list)
    predicted: List[str] = field(repr=False, default_factory=list)
    rssi: List[float] = field(repr=False, default_factory=list)
    conditions: List[str] = field(repr=False, default_factory=list)
    warnings: List[str] = field(default_factory=list)


def evaluate(model: ProximityModel, runs: Sequence[Run]) -> EvalResult:
    warnings: List[str] = []
    true_labels: List[str] = []
    predicted: List[str] = []
    rssi: List[float] = []
    conditions: List[str] = []

    leaked = [r for r in runs if r.session in set(model.calibration_sessions)]
    if leaked:
        warnings.append(
            f"{len(leaked)} run(s) share a session with the calibration data; "
            "accuracy will be optimistic. Use separately recorded test data."
        )
    non_test = [r for r in runs if r.dataset != "test"]
    if non_test:
        warnings.append(
            f"{len(non_test)} run(s) are not marked as 'test' data; "
            "make sure they were not used to compute the thresholds."
        )
    mismatched = [r for r in runs if r.bssid and model.bssid and r.bssid != model.bssid]
    if mismatched:
        warnings.append(f"{len(mismatched)} run(s) were recorded for a different access point than the model.")

    for run in runs:
        values = smoothed_samples(run, model.filter_kind, model.window)
        labels = model.classify_many(values)
        true_labels.extend([run.zone] * len(values))
        predicted.extend(labels)
        rssi.extend(values.tolist())
        conditions.extend([run.condition or "(unlabelled)"] * len(values))

    n = len(true_labels)
    confusion = np.zeros((len(ZONES), len(ZONES)), dtype=int)
    for truth, pred in zip(true_labels, predicted):
        confusion[ZONES.index(truth), ZONES.index(pred)] += 1
    correct = int(np.trace(confusion))
    per_zone = {
        zone: (confusion[i, i] / confusion[i].sum() if confusion[i].sum() else float("nan"))
        for i, zone in enumerate(ZONES)
    }

    per_condition: List[ConditionStats] = []
    cond_arr = np.array(conditions) if n else np.array([])
    for cond in sorted(set(conditions)):
        mask = cond_arr == cond
        idx = np.flatnonzero(mask)
        hits = sum(1 for i in idx if true_labels[i] == predicted[i])
        vals = np.asarray(rssi)[mask]
        truth_arr = np.asarray(true_labels)[mask]
        zone_means = {zone: float(vals[truth_arr == zone].mean())
                      for zone in ZONES if np.any(truth_arr == zone)}
        per_condition.append(ConditionStats(
            condition=cond, n=int(idx.size), accuracy=hits / idx.size,
            mean_rssi=float(vals.mean()), std_rssi=float(vals.std(ddof=1)) if vals.size > 1 else 0.0,
            zone_means=zone_means,
        ))

    return EvalResult(
        n=n, correct=correct, accuracy=(correct / n) if n else float("nan"),
        confusion=confusion, per_zone_accuracy=per_zone, per_condition=per_condition,
        true_labels=true_labels, predicted=predicted, rssi=rssi, conditions=conditions,
        warnings=warnings,
    )
