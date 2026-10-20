"""CSV storage: one file per recording run, plus loading runs back for fitting/evaluation.

File name:  <dataset>_<session>_<zone>.csv   e.g. calibration_20261020_113000_near.csv
Every row repeats dataset / session / zone / condition, so a file is self-describing
and files can be freely merged or renamed.
"""

from __future__ import annotations

import csv
import glob
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from rssi_proximity.acquisition.backends import Reading
from rssi_proximity.config import CSV_COLUMNS, DATASETS, ZONES


def new_session_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def run_path(folder: str, dataset: str, session: str, zone: str) -> str:
    return os.path.join(folder, f"{dataset}_{session}_{zone}.csv")


class RunWriter:
    """Appends readings to one run file, flushing every row so nothing is lost on a crash."""

    def __init__(self, folder: str, dataset: str, zone: str, distance_m: float,
                 condition: str, session: Optional[str] = None):
        if dataset not in DATASETS:
            raise ValueError(f"dataset must be one of {DATASETS}")
        if zone not in ZONES:
            raise ValueError(f"zone must be one of {ZONES}")
        self.dataset, self.zone = dataset, zone
        self.distance_m, self.condition = float(distance_m), condition.strip()
        self.session = session or new_session_id()
        os.makedirs(folder, exist_ok=True)
        self.path = run_path(folder, dataset, self.session, zone)
        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(CSV_COLUMNS)
        self._file.flush()
        self.count = 0

    def write(self, reading: Reading) -> None:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(reading.t))
        self._writer.writerow([
            stamp, f"{reading.t:.3f}", self.dataset, self.session, self.zone,
            f"{self.distance_m:g}", self.condition, reading.ssid, reading.bssid,
            f"{reading.signal_pct:g}", f"{reading.rssi_dbm:.1f}", reading.source,
        ])
        self._file.flush()
        self.count += 1

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@dataclass
class Run:
    """One contiguous recording: a single zone, in time order."""
    path: str
    dataset: str
    session: str
    zone: str
    condition: str
    distance_m: float
    ssid: str
    bssid: str
    rssi: np.ndarray = field(repr=False)
    epoch: np.ndarray = field(repr=False)

    @property
    def n(self) -> int:
        return int(self.rssi.size)


def read_runs(path: str) -> Tuple[List[Run], List[str]]:
    """Read one CSV file into runs. Returns (runs, warnings)."""
    warnings: List[str] = []
    groups: Dict[Tuple[str, str, str, str], dict] = {}
    skipped = 0
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = {"zone", "rssi_dbm"} - set(reader.fieldnames or [])
        if missing:
            return [], [f"{os.path.basename(path)}: missing column(s) {sorted(missing)}"]
        for row in reader:
            zone = (row.get("zone") or "").strip().lower()
            try:
                rssi = float(row["rssi_dbm"])
            except (TypeError, ValueError):
                skipped += 1
                continue
            if zone not in ZONES:
                skipped += 1
                continue
            dataset = (row.get("dataset") or _dataset_from_name(path)).strip().lower()
            session = (row.get("session") or _session_from_name(path)).strip()
            condition = (row.get("condition") or "").strip()
            key = (dataset, session, zone, condition)
            group = groups.setdefault(key, {"rssi": [], "epoch": [], "row": row})
            group["rssi"].append(rssi)
            try:
                group["epoch"].append(float(row.get("epoch_s") or len(group["epoch"])))
            except ValueError:
                group["epoch"].append(float(len(group["epoch"])))
    if skipped:
        warnings.append(f"{os.path.basename(path)}: skipped {skipped} unreadable row(s)")

    runs: List[Run] = []
    for (dataset, session, zone, condition), group in groups.items():
        row = group["row"]
        try:
            distance = float(row.get("distance_m") or "nan")
        except ValueError:
            distance = float("nan")
        runs.append(Run(
            path=path, dataset=dataset, session=session, zone=zone, condition=condition,
            distance_m=distance, ssid=(row.get("ssid") or "").strip(),
            bssid=(row.get("bssid") or "").strip().lower(),
            rssi=np.asarray(group["rssi"], dtype=float),
            epoch=np.asarray(group["epoch"], dtype=float),
        ))
    return runs, warnings


def load_runs(paths: List[str]) -> Tuple[List[Run], List[str]]:
    runs: List[Run] = []
    warnings: List[str] = []
    for path in paths:
        try:
            file_runs, file_warnings = read_runs(path)
        except OSError as error:
            warnings.append(f"{os.path.basename(path)}: {error}")
            continue
        runs.extend(file_runs)
        warnings.extend(file_warnings)
    return runs, warnings


def find_run_files(folder: str, dataset: str) -> List[str]:
    return sorted(glob.glob(os.path.join(folder, f"{dataset}_*.csv")))


def summarize_folder(folder: str, dataset: str) -> Dict[str, Tuple[int, int]]:
    """zone -> (number of runs, total samples) for the files of one dataset."""
    out = {zone: (0, 0) for zone in ZONES}
    runs, _ = load_runs(find_run_files(folder, dataset))
    for run in runs:
        n_runs, n_samples = out[run.zone]
        out[run.zone] = (n_runs + 1, n_samples + run.n)
    return out


_NAME = re.compile(r"^(?P<dataset>[a-z]+)_(?P<session>\d{8}_\d{6})_(?P<zone>[a-z]+)\.csv$")


def _dataset_from_name(path: str) -> str:
    m = _NAME.match(os.path.basename(path).lower())
    return m.group("dataset") if m else "calibration"


def _session_from_name(path: str) -> str:
    m = _NAME.match(os.path.basename(path).lower())
    return m.group("session") if m else os.path.splitext(os.path.basename(path))[0]
