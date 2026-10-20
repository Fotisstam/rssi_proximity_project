"""Main window: toolbar (access point, scanning) and the Calibrate / Live / Evaluate tabs."""

from PyQt5.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QLabel, QMainWindow, QPushButton, QTabWidget, QToolBar,
)

from rssi_proximity.config import DEFAULT_POLL_S, ZONE_LABELS, ZONES
from rssi_proximity.gui.calibrate_tab import CalibrateTab
from rssi_proximity.gui.evaluate_tab import EvaluateTab
from rssi_proximity.gui.live_tab import LiveTab
from rssi_proximity.gui.ssid_dialog import SsidDialog
from rssi_proximity.gui.theme import BASE_STYLESHEET, set_button, set_property


class MainWindow(QMainWindow):
    def __init__(self, state, sim_controls=None):
        super().__init__()
        self.state = state
        self.sim = sim_controls
        self.setWindowTitle("RSSI Proximity" + ("  [simulated signal]" if sim_controls else ""))
        self.resize(1380, 880)
        self.setStyleSheet(BASE_STYLESHEET)

        self._build_toolbar()
        self.tabs = QTabWidget()
        self.calibrate_tab = CalibrateTab(state)
        self.live_tab = LiveTab(state)
        self.evaluate_tab = EvaluateTab(state)
        self.tabs.addTab(self.calibrate_tab, "1 · Calibrate")
        self.tabs.addTab(self.live_tab, "2 · Live")
        self.tabs.addTab(self.evaluate_tab, "3 · Evaluate")
        self.setCentralWidget(self.tabs)

        self.status_label = QLabel("Select an access point to begin.")
        self.reading_label = QLabel("")
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.reading_label)

        state.status.connect(self._set_status)
        state.reading.connect(self._on_reading)
        state.target_changed.connect(self._on_target_changed)
        state.scanning_changed.connect(self._on_scanning_changed)
        state.load_model()          # after the tabs exist, so they receive model_changed

    # ── toolbar ────────────────────────────────────────────────────────────
    def _build_toolbar(self):
        bar = QToolBar("Main")
        bar.setMovable(False)
        self.addToolBar(bar)

        self.select_btn = QPushButton("Select access point...")
        set_button(self.select_btn, icon_name="search")
        self.select_btn.clicked.connect(self.select_access_point)
        bar.addWidget(self.select_btn)

        self.ap_label = QLabel("no access point selected")
        self.ap_label.setObjectName("Badge")
        bar.addWidget(self.ap_label)
        bar.addSeparator()

        self.scan_btn = QPushButton("Start scanning")
        set_button(self.scan_btn, icon_name="play", color="#68d6bd")
        self.scan_btn.setCheckable(True)
        self.scan_btn.setProperty("toggle", True)
        self.scan_btn.clicked.connect(self._toggle_scanning)
        bar.addWidget(self.scan_btn)

        bar.addWidget(QLabel("every"))
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.5, 10.0)
        self.interval.setSingleStep(0.5)
        self.interval.setSuffix(" s")
        self.interval.setValue(DEFAULT_POLL_S)
        self.interval.setToolTip("Time between RSSI reads. Windows only refreshes its Wi-Fi "
                                 "scan list every few seconds, so very short intervals can "
                                 "repeat values for access points you are not connected to.")
        self.interval.valueChanged.connect(self.state.set_interval)
        bar.addWidget(self.interval)

        if self.sim is not None:
            bar.addSeparator()
            bar.addWidget(QLabel("Simulated position"))
            zone_box = QComboBox()
            for zone in ZONES:
                zone_box.addItem(ZONE_LABELS[zone][1], zone)
            zone_box.currentIndexChanged.connect(
                lambda _i: setattr(self.sim, "zone", zone_box.currentData()))
            bar.addWidget(zone_box)
            bar.addWidget(QLabel("obstacle"))
            obstacle = QDoubleSpinBox()
            obstacle.setRange(0.0, 30.0)
            obstacle.setSuffix(" dB")
            obstacle.setToolTip("Extra attenuation, to see what an obstacle does to accuracy.")
            obstacle.valueChanged.connect(lambda v: setattr(self.sim, "obstacle_db", float(v)))
            bar.addWidget(obstacle)

    # ── actions ────────────────────────────────────────────────────────────
    def select_access_point(self):
        dialog = SsidDialog(self.state.backend, self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_target() is not None:
            self.state.set_target(dialog.selected_target())
            model = self.state.model
            target = dialog.selected_target()
            if model is not None and model.bssid and target.bssid and model.bssid != target.bssid:
                self.state.status.emit(
                    "This is a different access point than the saved model was calibrated for - "
                    "recalibrate before trusting the Live tab.", "#D9B36C")

    def _toggle_scanning(self, checked):
        if not checked:
            self.state.stop_scanning()
            return
        if self.state.target is None:
            self.select_access_point()
        if self.state.target is None:
            self.scan_btn.setChecked(False)
            return
        self.state.start_scanning()

    # ── state reactions ────────────────────────────────────────────────────
    def _on_target_changed(self, target):
        self.ap_label.setText(target.describe() if target is not None else "no access point selected")

    def _on_scanning_changed(self, scanning):
        self.scan_btn.setChecked(scanning)
        if scanning:
            set_button(self.scan_btn, "Stop scanning", "stop", color="#ffd7d7")
        else:
            set_button(self.scan_btn, "Start scanning", "play", color="#68d6bd")
        set_property(self.scan_btn, "recording", scanning)
        if not scanning:
            self.reading_label.setText("")

    def _on_reading(self, reading):
        self.reading_label.setText(
            f"{reading.rssi_dbm:.1f} dBm  ({reading.signal_pct:.0f} %)  ·  source: {reading.source}")

    def _set_status(self, message, color):
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color: {color};")

    def closeEvent(self, event):
        self.state.shutdown()
        super().closeEvent(event)
