"""Constants shared by every layer (no Qt imports here)."""

import os

# ── Proximity classes ────────────────────────────────────────────────────────
# Order matters: strongest expected signal first.
ZONES = ("near", "medium", "far")

# (Greek label shown big in the UI, English label shown under it)
ZONE_LABELS = {
    "near": ("ΚΟΝΤΑ", "Near"),
    "medium": ("ΜΕΤΡΙΑ ΑΠΟΣΤΑΣΗ", "Medium distance"),
    "far": ("ΜΑΚΡΙΑ", "Far"),
}
ZONE_COLORS = {"near": "#00B37E", "medium": "#D9B36C", "far": "#E25C5C"}

# Rough starting distances (metres) shown in the Calibrate tab; editable there.
DEFAULT_DISTANCES_M = {"near": 1.0, "medium": 4.0, "far": 8.0}

# ── Acquisition ──────────────────────────────────────────────────────────────
DEFAULT_POLL_S = 1.0           # seconds between RSSI reads
DEFAULT_SAMPLES_PER_RUN = 60   # samples recorded per zone per run
NETSH_TIMEOUT_S = 8

# ── Processing / model defaults ──────────────────────────────────────────────
FILTER_KINDS = ("moving_average", "median", "none")
FILTER_LABELS = {
    "moving_average": "Moving average",
    "median": "Moving median",
    "none": "No smoothing",
}
DEFAULT_FILTER = "moving_average"
DEFAULT_WINDOW = 5
REPRESENTATIVES = ("median", "mean")
THRESHOLD_METHODS = ("midpoint", "std_weighted")
THRESHOLD_LABELS = {
    "midpoint": "Midpoint between zone values",
    "std_weighted": "Weighted by zone spread (std)",
}
DEFAULT_HYSTERESIS_DB = 1.0
MIN_SAMPLES_PER_ZONE = 10      # after smoothing warm-up is dropped

# ── Files ────────────────────────────────────────────────────────────────────
DATASETS = ("calibration", "test")
CSV_COLUMNS = (
    "timestamp", "epoch_s", "dataset", "session", "zone", "distance_m",
    "condition", "ssid", "bssid", "signal_pct", "rssi_dbm", "source",
)
MODEL_FILENAME = "model.json"
DEFAULT_CONDITIONS = (
    "line of sight",
    "behind wall",
    "behind person",
    "device flat",
    "device upright",
    "device rotated 90 deg",
)


def default_data_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "RSSI Proximity", "data")
