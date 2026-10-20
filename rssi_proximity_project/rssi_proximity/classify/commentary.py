"""Short generated commentary on how obstacles / device orientation affected the results."""

from __future__ import annotations

from typing import List

from rssi_proximity.classify.evaluate import ConditionStats, EvalResult
from rssi_proximity.config import ZONES, ZONE_LABELS

BACKGROUND = (
    "Background (general behaviour, not measured here): walls, furniture and people "
    "absorb or reflect 2.4/5 GHz signals and typically lower RSSI by several dB, "
    "more for dense materials and for 5 GHz. Turning the device changes the antenna's "
    "gain pattern and the body of the person holding it shadows the antenna, which "
    "can also shift RSSI by several dB. Indoor multipath adds fast fading of a few dB "
    "even at a fixed spot. A shift of this size is comparable to the gap between "
    "adjacent zones, so it moves samples across a threshold and lowers accuracy."
)


def _baseline(conditions: List[ConditionStats]) -> ConditionStats:
    for item in conditions:
        if "line" in item.condition.lower() and "sight" in item.condition.lower():
            return item
    return max(conditions, key=lambda item: item.n)


def build_commentary(result: EvalResult) -> str:
    if result.n == 0:
        return "No evaluation samples yet."
    lines = [f"Overall: {result.correct}/{result.n} samples classified correctly "
             f"({result.accuracy * 100:.1f} %)."]

    # most frequent confusion
    worst, worst_count = None, 0
    for i, truth in enumerate(ZONES):
        for j, pred in enumerate(ZONES):
            if i != j and result.confusion[i, j] > worst_count:
                worst, worst_count = (truth, pred), int(result.confusion[i, j])
    if worst:
        lines.append(
            f"Most common error: '{ZONE_LABELS[worst[0]][1]}' read as "
            f"'{ZONE_LABELS[worst[1]][1]}' ({worst_count} samples)."
        )

    if len(result.per_condition) > 1:
        base = _baseline(result.per_condition)
        lines.append(f"\nEffect of recording condition (reference: '{base.condition}'):")
        for item in result.per_condition:
            if item is base:
                lines.append(f"  - {item.condition}: accuracy {item.accuracy * 100:.1f} %, "
                             f"mean {item.mean_rssi:.1f} dBm (n={item.n}).")
                continue
            shared = [z for z in item.zone_means if z in base.zone_means]
            d_acc = (item.accuracy - base.accuracy) * 100
            if shared:
                delta = sum(item.zone_means[z] - base.zone_means[z] for z in shared) / len(shared)
                shift = f"RSSI {delta:+.1f} dB vs reference (same zones)"
            else:
                shift = "no zone in common with the reference, RSSI shift not comparable"
            lines.append(
                f"  - {item.condition}: accuracy {item.accuracy * 100:.1f} % "
                f"({d_acc:+.1f} points), {shift} (n={item.n})."
            )
    else:
        lines.append("\nOnly one recording condition is present. Record test data with "
                     "different obstacles or device orientations (use the 'condition' "
                     "field on the Calibrate tab) to see their effect here.")
    lines.append("\n" + BACKGROUND)
    return "\n".join(lines)
