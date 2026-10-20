"""Summary statistics for a set of RSSI values."""

from __future__ import annotations

import numpy as np


def describe(values) -> dict:
    x = np.asarray(values, dtype=float)
    if x.size == 0:
        return {"n": 0, "mean": float("nan"), "median": float("nan"),
                "std": float("nan"), "min": float("nan"), "max": float("nan")}
    return {
        "n": int(x.size),
        "mean": float(np.mean(x)),
        "median": float(np.median(x)),
        "std": float(np.std(x, ddof=1)) if x.size > 1 else 0.0,
        "min": float(np.min(x)),
        "max": float(np.max(x)),
    }
