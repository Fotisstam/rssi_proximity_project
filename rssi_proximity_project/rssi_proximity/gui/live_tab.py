"""Live tab: shows the estimated proximity class for the incoming RSSI stream."""

from collections import deque

import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from rssi_proximity.classify.model import LiveClassifier
from rssi_proximity.config import (
    DEFAULT_DISTANCES_M, DEFAULT_FILTER, DEFAULT_HYSTERESIS_DB, DEFAULT_WINDOW,
    FILTER_LABELS, ZONE_COLORS, ZONE_LABELS, ZONES,
)
from rssi_proximity.gui.plots import make_plot
from rssi_proximity.gui.theme import caption, section_label
from rssi_proximity.processing.filters import StreamFilter

PLOT_POINTS = 300
NEUTRAL = "#9aadb1"


class LiveTab(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._raw = deque(maxlen=PLOT_POINTS)
        self._smooth = deque(maxlen=PLOT_POINTS)
        self._filter = StreamFilter(DEFAULT_FILTER, DEFAULT_WINDOW)
        self._live = None

        layout = QVBoxLayout(self)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(caption("ESTIMATED PROXIMITY"))
        self.zone_label = QLabel("NO MODEL")
        self.zone_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.zone_label)
        self.zone_sub = QLabel("")
        self.zone_sub.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.zone_sub)
        metrics = QHBoxLayout()
        self.smooth_label = QLabel("smoothed: -")
        self.raw_label = QLabel("raw: -")
        self.filter_label = QLabel("")
        for label in (self.smooth_label, self.raw_label, self.filter_label):
            label.setObjectName("Hint")
            label.setAlignment(Qt.AlignCenter)
            metrics.addWidget(label)
        card_layout.addLayout(metrics)
        layout.addWidget(card)
        self._style_zone(None, "NO MODEL", "Compute thresholds on the Calibrate tab first.")

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Hysteresis"))
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0.0, 10.0)
        self.margin.setSingleStep(0.5)
        self.margin.setDecimals(1)
        self.margin.setSuffix(" dB")
        self.margin.setValue(DEFAULT_HYSTERESIS_DB)
        self.margin.setToolTip("The label only changes after the smoothed RSSI is this far "
                               "past a threshold, so it does not flicker at a boundary.")
        self.margin.valueChanged.connect(self._apply_margin)
        controls.addWidget(self.margin)
        reset = QPushButton("Reset filter")
        reset.clicked.connect(self._reset)
        controls.addWidget(reset)
        controls.addStretch(1)
        self.model_label = QLabel("")
        self.model_label.setObjectName("Hint")
        controls.addWidget(self.model_label)
        layout.addLayout(controls)

        layout.addWidget(section_label("SIGNAL AND THRESHOLDS"))
        self.plot = make_plot("sample")
        self.raw_curve = self.plot.plot(pen=pg.mkPen("#6b7b80", width=1), name="raw")
        self.smooth_curve = self.plot.plot(pen=pg.mkPen("#46b8a8", width=2.5), name="smoothed")
        self.lines = []
        for _ in range(2):
            line = pg.InfiniteLine(
                pos=-70, angle=0, pen=pg.mkPen("#d7e0e3", width=1.2, style=Qt.DashLine))
            line.setVisible(False)
            self.plot.addItem(line)
            self.lines.append(line)
        layout.addWidget(self.plot, stretch=1)

        state.reading.connect(self._on_reading)
        state.model_changed.connect(self._on_model_changed)
        state.scanning_changed.connect(self._on_scanning_changed)

    # ── display ────────────────────────────────────────────────────────────
    def _style_zone(self, zone, big, small):
        color = ZONE_COLORS.get(zone, NEUTRAL)
        self.zone_label.setText(big)
        self.zone_label.setStyleSheet(f"font-size:46px; font-weight:bold; color:{color}; padding:8px;")
        self.zone_sub.setText(small)
        self.zone_sub.setStyleSheet(f"font-size:16px; color:{color};")

    def _show_zone(self, zone):
        greek, english = ZONE_LABELS[zone]
        distance = self.state.model.distances.get(zone, DEFAULT_DISTANCES_M[zone])
        self._style_zone(zone, greek, f"{english}  (calibrated at about {distance:g} m)")

    # ── events ─────────────────────────────────────────────────────────────
    def _on_reading(self, reading):
        self._raw.append(reading.rssi_dbm)
        smoothed = self._filter.push(reading.rssi_dbm)
        self._smooth.append(smoothed)
        self.raw_curve.setData(list(self._raw))
        self.smooth_curve.setData(list(self._smooth))
        self.raw_label.setText(f"raw: {reading.rssi_dbm:.1f} dBm ({reading.signal_pct:.0f} %)")
        self.smooth_label.setText(f"smoothed: {smoothed:.1f} dBm")

        model = self.state.model
        if model is None or self._live is None:
            return
        if not self._filter.warmed_up:
            self._style_zone(None, "WARMING UP", "collecting the first samples for the filter...")
            return
        self._show_zone(self._live.update(smoothed))

    def _on_model_changed(self, model):
        self._reset()
        if model is None:
            self._live = None
            self._filter = StreamFilter(DEFAULT_FILTER, DEFAULT_WINDOW)
            for line in self.lines:
                line.setVisible(False)
            self.model_label.setText("")
            self.filter_label.setText("")
            self._style_zone(None, "NO MODEL", "Compute thresholds on the Calibrate tab first.")
            return
        self._filter = StreamFilter(model.filter_kind, model.window)
        self._live = LiveClassifier(model, self.margin.value())
        for line, value in zip(self.lines, model.thresholds):
            line.setValue(value)
            line.setVisible(True)
        self.filter_label.setText(f"{FILTER_LABELS[model.filter_kind]}, window {model.window}")
        self.model_label.setText(f"model: {model.ssid or '?'}")
        self._style_zone(None, "WAITING", "Start scanning to see the estimate.")

    def _on_scanning_changed(self, scanning):
        if scanning:
            self._reset()

    def _apply_margin(self, value):
        if self._live is not None:
            self._live.margin_db = float(value)

    def _reset(self):
        self._raw.clear()
        self._smooth.clear()
        self._filter.reset()
        if self._live is not None:
            self._live.reset()
        self.raw_curve.setData([])
        self.smooth_curve.setData([])
