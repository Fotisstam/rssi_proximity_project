"""Causal smoothing filters (usable offline on whole arrays and live sample by sample).

"Causal" means output[i] only uses samples up to i, so the offline result for a
recorded run is identical to what the live view would have shown.
"""

from __future__ import annotations

from collections import deque
from typing import Deque

import numpy as np


def warmup_length(kind: str, window: int) -> int:
    """Leading outputs computed from fewer than `window` samples (dropped in statistics)."""
    return 0 if kind == "none" else max(0, int(window) - 1)


def smooth(values, kind: str, window: int) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    n = x.size
    window = max(1, int(window))
    if kind == "none" or n == 0 or window == 1:
        return x.copy()
    if kind == "moving_average":
        csum = np.concatenate(([0.0], np.cumsum(x)))
        idx = np.arange(1, n + 1)
        lo = np.maximum(0, idx - window)
        return (csum[idx] - csum[lo]) / (idx - lo)
    if kind == "median":
        return np.array([np.median(x[max(0, i - window + 1): i + 1]) for i in range(n)])
    raise ValueError(f"unknown filter kind: {kind!r}")


class StreamFilter:
    """Sample-by-sample version of `smooth` for the live view."""

    def __init__(self, kind: str, window: int):
        self.kind = kind
        self.window = max(1, int(window))
        self._buf: Deque[float] = deque(maxlen=self.window)

    def reset(self) -> None:
        self._buf.clear()

    @property
    def warmed_up(self) -> bool:
        return self.kind == "none" or len(self._buf) >= self.window

    def push(self, value: float) -> float:
        self._buf.append(float(value))
        if self.kind == "none" or self.window == 1:
            return float(value)
        if self.kind == "moving_average":
            return float(sum(self._buf) / len(self._buf))
        if self.kind == "median":
            return float(np.median(self._buf))
        raise ValueError(f"unknown filter kind: {self.kind!r}")
