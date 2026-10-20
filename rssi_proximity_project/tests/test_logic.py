"""Tests for the Qt-free logic. Run with `python -m pytest` or `python -m unittest`."""

import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rssi_proximity.acquisition.backends import NetshBackend, SimulatedBackend, Target
from rssi_proximity.acquisition import netsh
from rssi_proximity.classify.commentary import build_commentary
from rssi_proximity.classify.evaluate import evaluate
from rssi_proximity.classify.model import (
    LiveClassifier, ModelError, ProximityModel, compute_thresholds, fit_model,
)
from rssi_proximity.config import ZONES
from rssi_proximity.processing.filters import StreamFilter, smooth, warmup_length
from rssi_proximity.storage.csv_logger import (
    RunWriter, find_run_files, load_runs, new_session_id, summarize_folder,
)

NETWORKS_EN = """
Interface name : Wi-Fi
There are 3 networks currently visible.

SSID 1 : HomeNet
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : AA:BB:CC:00:00:01
         Signal             : 88%
         Radio type         : 802.11ax
         Band               : 5 GHz
         Channel            : 36
         Basic rates (Mbps) : 6 12 24
         Channel Utilization: 31 (12 %)
    BSSID 2                 : aa:bb:cc:00:00:02
         Signal             : 64%
         Radio type         : 802.11n
         Band               : 2.4 GHz
         Channel            : 6

SSID 2 :
    Network type            : Infrastructure
    BSSID 1                 : de:ad:be:ef:00:01
         Signal             : 30%
         Band               : 2.4 GHz
         Channel            : 11
"""

# Same structure, translated labels (Greek-style), to prove the parser is language independent.
NETWORKS_GR = """
SSID 1 : Σπίτι
    Τύπος δικτύου           : Υποδομή
    BSSID 1                 : 11:22:33:44:55:66
         Σήμα               : 72%
         Ζώνη               : 5 GHz
         Κανάλι             : 100
"""

INTERFACES_EN = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Physical address       : 00:11:22:33:44:55
    State                  : connected
    SSID                   : HomeNet
    AP BSSID               : aa:bb:cc:00:00:01
    Band                   : 5 GHz
    Channel                : 36
    Receive rate (Mbps)    : 866
    Signal                 : 91%
"""


class NetshParsing(unittest.TestCase):
    def test_networks_english(self):
        aps = netsh.parse_networks(NETWORKS_EN)
        self.assertEqual(len(aps), 3)
        self.assertEqual((aps[0].ssid, aps[0].bssid, aps[0].signal_pct), ("HomeNet", "aa:bb:cc:00:00:01", 88))
        self.assertEqual((aps[0].band, aps[0].channel), ("5 GHz", 36))
        self.assertEqual(aps[1].bssid, "aa:bb:cc:00:00:02")
        self.assertEqual((aps[1].band, aps[1].channel), ("2.4 GHz", 6))
        self.assertEqual(aps[2].ssid, netsh.HIDDEN_SSID)

    def test_networks_translated_labels(self):
        aps = netsh.parse_networks(NETWORKS_GR)
        self.assertEqual(len(aps), 1)
        self.assertEqual((aps[0].ssid, aps[0].signal_pct, aps[0].band, aps[0].channel),
                         ("Σπίτι", 72, "5 GHz", 100))

    def test_interfaces_uses_ap_bssid_not_adapter_mac(self):
        ap = netsh.parse_interfaces(INTERFACES_EN)
        self.assertEqual((ap.ssid, ap.bssid, ap.signal_pct), ("HomeNet", "aa:bb:cc:00:00:01", 91))

    def test_interfaces_disconnected(self):
        self.assertIsNone(netsh.parse_interfaces("    State : disconnected\n    SSID :\n"))

    def test_pct_to_dbm(self):
        self.assertEqual(netsh.pct_to_dbm(100), -50)
        self.assertEqual(netsh.pct_to_dbm(0), -100)
        self.assertEqual(netsh.pct_to_dbm(80), -60)

    def test_empty_scan_hint(self):
        self.assertIn("Location", netsh.explain_empty_scan("The location permission is required"))


class Filters(unittest.TestCase):
    def test_moving_average_causal(self):
        out = smooth([1, 2, 3, 4, 5], "moving_average", 3)
        np.testing.assert_allclose(out, [1, 1.5, 2, 3, 4])

    def test_median_causal(self):
        out = smooth([1, 10, 2, 3, 100], "median", 3)
        np.testing.assert_allclose(out, [1, 5.5, 2, 3, 3])

    def test_none_and_warmup(self):
        np.testing.assert_allclose(smooth([1, 2], "none", 9), [1, 2])
        self.assertEqual(warmup_length("none", 9), 0)
        self.assertEqual(warmup_length("moving_average", 5), 4)

    def test_stream_matches_offline(self):
        rng = np.random.default_rng(0)
        x = rng.normal(-60, 3, 50)
        for kind in ("moving_average", "median"):
            f = StreamFilter(kind, 5)
            live = [f.push(v) for v in x]
            np.testing.assert_allclose(live, smooth(x, kind, 5))


def record_sim(folder, dataset, seed, n=60, obstacle=0.0, condition="line of sight",
               zones=ZONES, session=None):
    """Record runs from the simulator exactly like the GUI does."""
    state = {"zone": "near", "obstacle": obstacle}
    backend = SimulatedBackend(seed=seed, zone_getter=lambda: state["zone"],
                               obstacle_getter=lambda: state["obstacle"])
    target = Target("Lab-WiFi", "aa:bb:cc:00:00:01")
    session = session or new_session_id()
    for zone in zones:
        state["zone"] = zone
        with RunWriter(folder, dataset, zone, 1.0, condition, session=f"{session}_{seed}") as w:
            for _ in range(n):
                w.write(backend.read(target))


class Pipeline(unittest.TestCase):
    def test_csv_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            record_sim(folder, "calibration", seed=1, n=20)
            files = find_run_files(folder, "calibration")
            self.assertEqual(len(files), 3)
            runs, warnings = load_runs(files)
            self.assertEqual(warnings, [])
            self.assertEqual({r.zone for r in runs}, set(ZONES))
            self.assertTrue(all(r.n == 20 and r.dataset == "calibration" for r in runs))
            self.assertEqual(summarize_folder(folder, "calibration")["near"], (1, 20))

    def test_fit_and_thresholds_ordered(self):
        with tempfile.TemporaryDirectory() as folder:
            record_sim(folder, "calibration", seed=2)
            runs, _ = load_runs(find_run_files(folder, "calibration"))
            model = fit_model(runs, ssid="Lab-WiFi", bssid="aa:bb:cc:00:00:01")
            self.assertGreater(model.values["near"], model.values["medium"])
            self.assertGreater(model.values["medium"], model.values["far"])
            self.assertGreater(model.t_near_medium, model.t_medium_far)
            self.assertEqual(model.classify(model.values["near"]), "near")
            self.assertEqual(model.classify(model.values["medium"]), "medium")
            self.assertEqual(model.classify(model.values["far"]), "far")
            again = ProximityModel.from_json(model.to_json())
            self.assertEqual(again.thresholds, model.thresholds)

    def test_fit_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            record_sim(folder, "calibration", seed=3, zones=("near", "medium"))
            runs, _ = load_runs(find_run_files(folder, "calibration"))
            with self.assertRaises(ModelError):
                fit_model(runs)                       # 'far' missing
            record_sim(folder, "calibration", seed=3, n=5, zones=("far",))
            with self.assertRaises(ModelError):
                fit_model(load_runs(find_run_files(folder, "calibration"))[0])  # far too short

    def test_unordered_zones_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            record_sim(folder, "calibration", seed=4)
            runs, _ = load_runs(find_run_files(folder, "calibration"))
            for r in runs:                            # swap near and far data
                r.zone = {"near": "far", "far": "near"}.get(r.zone, r.zone)
            with self.assertRaises(ModelError):
                fit_model(runs)

    def test_threshold_methods(self):
        values = {"near": -50.0, "medium": -60.0, "far": -80.0}
        t = compute_thresholds(values, {"near": 1, "medium": 1, "far": 1}, "midpoint")
        self.assertEqual(t, (-55.0, -70.0))
        w = compute_thresholds(values, {"near": 1, "medium": 1, "far": 1}, "std_weighted")
        self.assertEqual(w, (-55.0, -70.0))          # equal spreads -> same as midpoint
        w2 = compute_thresholds(values, {"near": 3, "medium": 1, "far": 1}, "std_weighted")
        self.assertLess(w2[0], -55.0)                # wider 'near' pushes boundary toward medium

    def test_evaluation_accuracy_and_confusion(self):
        with tempfile.TemporaryDirectory() as folder:
            record_sim(folder, "calibration", seed=10, n=80)
            record_sim(folder, "test", seed=99, n=80)
            cal, _ = load_runs(find_run_files(folder, "calibration"))
            test, _ = load_runs(find_run_files(folder, "test"))
            model = fit_model(cal, ssid="Lab-WiFi", bssid="aa:bb:cc:00:00:01")
            result = evaluate(model, test)
            self.assertEqual(result.warnings, [])
            self.assertEqual(result.confusion.sum(), result.n)
            self.assertEqual(result.correct, int(np.trace(result.confusion)))
            self.assertGreater(result.accuracy, 0.7)   # synthetic data, well-separated zones
            self.assertIn("Overall", build_commentary(result))

    def test_evaluation_warns_when_calibration_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            record_sim(folder, "calibration", seed=11)
            cal, _ = load_runs(find_run_files(folder, "calibration"))
            model = fit_model(cal)
            result = evaluate(model, cal)
            self.assertTrue(result.warnings)

    def test_obstacle_lowers_accuracy_and_shows_in_commentary(self):
        with tempfile.TemporaryDirectory() as folder:
            record_sim(folder, "calibration", seed=20, n=100)
            record_sim(folder, "test", seed=21, n=100)
            record_sim(folder, "test", seed=22, n=100, obstacle=8.0, condition="behind wall")
            cal, _ = load_runs(find_run_files(folder, "calibration"))
            test, _ = load_runs(find_run_files(folder, "test"))
            result = evaluate(fit_model(cal), test)
            by = {c.condition: c for c in result.per_condition}
            self.assertLess(by["behind wall"].accuracy, by["line of sight"].accuracy)
            self.assertLess(by["behind wall"].zone_means["near"], by["line of sight"].zone_means["near"])
            text = build_commentary(result)
            self.assertIn("behind wall", text)
            self.assertIn("dB vs reference", text)


class LiveHysteresis(unittest.TestCase):
    def setUp(self):
        self.model = ProximityModel(
            ssid="x", bssid="", filter_kind="none", window=1, representative="median",
            threshold_method="midpoint", values={"near": -50, "medium": -60, "far": -80},
            spreads={z: 1.0 for z in ZONES}, counts={z: 10 for z in ZONES},
            distances={}, t_near_medium=-55.0, t_medium_far=-70.0,
        )

    def test_no_flicker_inside_margin(self):
        live = LiveClassifier(self.model, margin_db=2.0)
        self.assertEqual(live.update(-52), "near")
        for v in (-55.5, -54.5, -56.5):             # hovering around the -55 boundary
            self.assertEqual(live.update(v), "near")
        self.assertEqual(live.update(-57.5), "medium")
        self.assertEqual(live.update(-54.0), "medium")
        self.assertEqual(live.update(-52.9), "near")

    def test_can_skip_a_zone(self):
        live = LiveClassifier(self.model, margin_db=1.0)
        live.update(-52)
        self.assertEqual(live.update(-90), "far")


class Backends(unittest.TestCase):
    def test_simulated_backend_orders_zones(self):
        state = {"zone": "near"}
        sim = SimulatedBackend(seed=5, zone_getter=lambda: state["zone"])
        means = {}
        for zone in ZONES:
            state["zone"] = zone
            means[zone] = np.mean([sim.read(Target("Lab-WiFi")).rssi_dbm for _ in range(200)])
        self.assertGreater(means["near"], means["medium"])
        self.assertGreater(means["medium"], means["far"])

    def test_netsh_backend_refuses_off_windows(self):
        if sys.platform.startswith("win"):
            self.skipTest("only meaningful off Windows")
        with self.assertRaises(netsh.ScanError):
            NetshBackend().list_access_points()


if __name__ == "__main__":
    unittest.main()
