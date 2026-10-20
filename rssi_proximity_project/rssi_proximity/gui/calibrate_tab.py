"""Calibrate tab: record RSSI per zone to CSV, then compute representative values and thresholds."""

import os
from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QRadioButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from rssi_proximity.classify.model import ModelError, fit_model, smoothed_samples
from rssi_proximity.config import (
    DEFAULT_CONDITIONS, DEFAULT_DISTANCES_M, DEFAULT_FILTER, DEFAULT_SAMPLES_PER_RUN,
    DEFAULT_WINDOW, FILTER_KINDS, FILTER_LABELS, REPRESENTATIVES, THRESHOLD_LABELS,
    THRESHOLD_METHODS, ZONE_COLORS, ZONE_LABELS, ZONES,
)
from rssi_proximity.gui.plots import make_plot
from rssi_proximity.gui.theme import hint, qcolor, section_label, set_button, set_property
from rssi_proximity.processing.filters import StreamFilter
from rssi_proximity.processing.stats import describe
from rssi_proximity.storage.csv_logger import (
    RunWriter, find_run_files, load_runs, summarize_folder,
)

PLOT_POINTS = 300


class ZoneRow(QFrame):
    record_clicked = pyqtSignal(str)

    def __init__(self, zone, parent=None):
        super().__init__(parent)
        self.setObjectName("ZoneRow")
        self.zone = zone
        greek, english = ZONE_LABELS[zone]
        color = ZONE_COLORS[zone]

        title = QLabel(f"<b style='color:{color}; font-size:14px'>{greek}</b>"
                       f"<br><span style='color:#9aadb1'>{english}</span>")
        title.setMinimumWidth(135)

        self.distance = QDoubleSpinBox()
        self.distance.setRange(0.1, 100.0)
        self.distance.setDecimals(1)
        self.distance.setSingleStep(0.5)
        self.distance.setSuffix(" m")
        self.distance.setValue(DEFAULT_DISTANCES_M[zone])
        self.distance.setToolTip("Distance from the access point (saved with the data).")

        self.summary = QLabel("no data yet")
        self.summary.setObjectName("Hint")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("%v / %m")

        self.button = QPushButton()
        set_button(self.button, "Record", "record", color="#e25c5c")
        self.button.clicked.connect(lambda: self.record_clicked.emit(self.zone))

        middle = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(QLabel("Distance"))
        top.addWidget(self.distance)
        top.addStretch(1)
        middle.addLayout(top)
        middle.addWidget(self.summary)
        middle.addWidget(self.progress)

        row = QHBoxLayout(self)
        row.addWidget(title)
        row.addLayout(middle, stretch=1)
        row.addWidget(self.button)

    def set_recording(self, active):
        if active:
            set_button(self.button, "Stop", "stop", color="#ffd7d7")
        else:
            set_button(self.button, "Record", "record", color="#e25c5c")
        set_property(self.button, "recording", active)

    def set_progress(self, done, total):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(done, total))


def _cell(table, row, col, text, align=Qt.AlignCenter):
    item = QTableWidgetItem(text)
    item.setTextAlignment(align)
    table.setItem(row, col, item)


class CalibrateTab(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._writer = None
        self._rec_zone = None
        self._rec_total = 0
        self._raw = deque(maxlen=PLOT_POINTS)
        self._smooth = deque(maxlen=PLOT_POINTS)
        self._filter = StreamFilter(DEFAULT_FILTER, DEFAULT_WINDOW)

        root = QHBoxLayout(self)
        root.addWidget(self._build_left(), stretch=0)
        root.addWidget(self._build_right(), stretch=1)

        state.reading.connect(self._on_reading)
        state.model_changed.connect(self._on_model_changed)
        state.data_dir_changed.connect(lambda _path: self._on_data_dir_changed())
        self._on_data_dir_changed()

    # ── layout ─────────────────────────────────────────────────────────────
    def _build_left(self):
        panel = QWidget()
        panel.setFixedWidth(430)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)

        layout.addWidget(section_label("1 · RECORD MEASUREMENTS"))
        radios = QWidget()
        radio_row = QHBoxLayout(radios)
        radio_row.setContentsMargins(0, 0, 0, 0)
        self.rb_cal = QRadioButton("Calibration set")
        self.rb_test = QRadioButton("Test set")
        self.rb_cal.setChecked(True)
        self.rb_test.setToolTip("Record these at a different time / positions than the calibration set.")
        radio_row.addWidget(self.rb_cal)
        radio_row.addWidget(self.rb_test)
        radio_row.addStretch(1)
        layout.addWidget(radios)

        form = QFormLayout()
        self.condition = QComboBox()
        self.condition.setEditable(True)
        self.condition.addItems(DEFAULT_CONDITIONS)
        self.condition.setToolTip("Free text stored with every sample: obstacle / device orientation.")
        form.addRow("Condition", self.condition)
        self.samples = QSpinBox()
        self.samples.setRange(10, 5000)
        self.samples.setValue(DEFAULT_SAMPLES_PER_RUN)
        self.samples.setToolTip("Samples per run. The first (window - 1) are filter warm-up and are not used.")
        form.addRow("Samples per run", self.samples)
        layout.addLayout(form)

        self.rows = {}
        for zone in ZONES:
            row = ZoneRow(zone)
            row.record_clicked.connect(self._toggle_record)
            self.rows[zone] = row
            layout.addWidget(row)
        layout.addWidget(hint(
            "Stand at each zone's position with the device in the same orientation, then press "
            "Record. Repeat a zone at other moments for more data; every run is its own CSV file."
        ))

        layout.addWidget(section_label("2 · COMPUTE THRESHOLDS"))
        form2 = QFormLayout()
        self.filter_combo = QComboBox()
        for kind in FILTER_KINDS:
            self.filter_combo.addItem(FILTER_LABELS[kind], kind)
        form2.addRow("Smoothing", self.filter_combo)
        self.window = QSpinBox()
        self.window.setRange(1, 51)
        self.window.setValue(DEFAULT_WINDOW)
        self.window.setToolTip("Number of samples averaged (about this many seconds at 1 Hz).")
        form2.addRow("Window (samples)", self.window)
        self.rep_combo = QComboBox()
        for rep in REPRESENTATIVES:
            self.rep_combo.addItem(rep, rep)
        form2.addRow("Zone value", self.rep_combo)
        self.method_combo = QComboBox()
        for method in THRESHOLD_METHODS:
            self.method_combo.addItem(THRESHOLD_LABELS[method], method)
        form2.addRow("Thresholds", self.method_combo)
        layout.addLayout(form2)
        self.filter_combo.currentIndexChanged.connect(self._rebuild_filter)
        self.window.valueChanged.connect(self._rebuild_filter)

        self.compute_btn = QPushButton("Compute from calibration CSVs")
        self.compute_btn.setObjectName("PrimaryAction")
        self.compute_btn.clicked.connect(self._compute)
        layout.addWidget(self.compute_btn)

        layout.addWidget(section_label("DATA FOLDER"))
        self.folder_label = QLabel()
        self.folder_label.setObjectName("Hint")
        self.folder_label.setWordWrap(True)
        layout.addWidget(self.folder_label)
        folder_row = QHBoxLayout()
        change = QPushButton("Change...")
        change.clicked.connect(self._change_folder)
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.state.data_dir)))
        folder_row.addWidget(change)
        folder_row.addWidget(open_btn)
        layout.addLayout(folder_row)
        layout.addStretch(1)
        return panel

    def _build_right(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(section_label("LIVE SIGNAL"))
        self.live_plot = make_plot("sample")
        self.raw_curve = self.live_plot.plot(
            pen=pg.mkPen("#6b7b80", width=1), name="raw")
        self.smooth_curve = self.live_plot.plot(
            pen=pg.mkPen("#46b8a8", width=2.5), name="smoothed")
        layout.addWidget(self.live_plot, stretch=3)

        layout.addWidget(section_label("CALIBRATION RESULT"))
        self.dist_plot = make_plot("smoothed RSSI (dBm)", "samples")
        layout.addWidget(self.dist_plot, stretch=3)

        self.threshold_label = QLabel("No model yet - record all three zones, then compute.")
        self.threshold_label.setObjectName("Metric")
        self.threshold_label.setStyleSheet("font-size:15px; font-weight:bold; color:#f1f7f6;")
        layout.addWidget(self.threshold_label)

        columns = ("Zone", "Distance", "Samples", "Mean", "Median", "Std", "Min", "Max")
        self.table = QTableWidget(len(ZONES), len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setFixedHeight(130)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        return panel

    # ── live signal / recording ────────────────────────────────────────────
    def _filter_settings(self):
        return self.filter_combo.currentData(), self.window.value()

    def _rebuild_filter(self, *_args):
        kind, window = self._filter_settings()
        self._filter = StreamFilter(kind, window)
        history = list(self._raw)
        self._smooth.clear()
        for value in history:
            self._smooth.append(self._filter.push(value))
        self._update_live_plot()

    def _on_reading(self, reading):
        self._raw.append(reading.rssi_dbm)
        self._smooth.append(self._filter.push(reading.rssi_dbm))
        self._update_live_plot()
        if self._writer is not None:
            self._writer.write(reading)
            self.rows[self._rec_zone].set_progress(self._writer.count, self._rec_total)
            if self._writer.count >= self._rec_total:
                self._finish_recording()

    def _update_live_plot(self):
        self.raw_curve.setData(list(self._raw))
        self.smooth_curve.setData(list(self._smooth))

    def _toggle_record(self, zone):
        if self._writer is not None:
            if zone == self._rec_zone:
                self._finish_recording(aborted=True)
            return
        if not self.state.ensure_ready():
            return
        dataset = "calibration" if self.rb_cal.isChecked() else "test"
        condition = self.condition.currentText().strip() or "line of sight"
        row = self.rows[zone]
        try:
            self._writer = RunWriter(self.state.data_dir, dataset, zone,
                                     row.distance.value(), condition)
        except OSError as error:
            self.state.status.emit(f"Cannot write to the data folder: {error}", "#E25C5C")
            return
        self._rec_zone = zone
        self._rec_total = self.samples.value()
        row.set_progress(0, self._rec_total)
        for z, other in self.rows.items():
            other.button.setEnabled(z == zone)
        row.set_recording(True)
        self.state.status.emit(f"Recording '{zone}' ({dataset} set, {condition})...", "#E25C5C")

    def _finish_recording(self, aborted=False):
        writer, zone = self._writer, self._rec_zone
        self._writer = None
        self._rec_zone = None
        writer.close()
        for other in self.rows.values():
            other.button.setEnabled(True)
            other.set_recording(False)
        if writer.count == 0:
            try:
                os.remove(writer.path)
            except OSError:
                pass
            self.state.status.emit("Recording stopped - no samples were received.", "#D9B36C")
        else:
            verb = "Stopped early" if aborted else "Done"
            self.state.status.emit(
                f"{verb}: {writer.count} samples saved to {os.path.basename(writer.path)}",
                "#68d6bd")
        self.rows[zone].set_progress(0, 1)
        self.refresh_summary()

    def refresh_summary(self):
        cal = summarize_folder(self.state.data_dir, "calibration")
        test = summarize_folder(self.state.data_dir, "test")
        for zone, row in self.rows.items():
            c_runs, c_n = cal[zone]
            t_runs, t_n = test[zone]
            row.summary.setText(f"calibration: {c_runs} run(s), {c_n} samples   |   "
                                f"test: {t_runs} run(s), {t_n} samples")

    # ── model ──────────────────────────────────────────────────────────────
    def _compute(self):
        files = find_run_files(self.state.data_dir, "calibration")
        if not files:
            QMessageBox.information(self, "No calibration data",
                                    "Record the three zones in the calibration set first.")
            return
        runs, warnings = load_runs(files)
        target = self.state.target
        if target is not None and target.bssid:
            runs = [r for r in runs if not r.bssid or r.bssid == target.bssid]
        elif len({r.bssid for r in runs if r.bssid}) > 1:
            QMessageBox.warning(
                self, "Several access points",
                "The calibration files contain more than one access point. "
                "Select the access point you want a model for, then compute again.")
            return
        ssid = target.ssid if target else (runs[0].ssid if runs else "")
        bssid = (target.bssid if target and target.bssid else (runs[0].bssid if runs else "")) or ""
        kind, window = self._filter_settings()
        try:
            model = fit_model(
                runs, ssid=ssid, bssid=bssid, filter_kind=kind, window=window,
                representative=self.rep_combo.currentData(),
                threshold_method=self.method_combo.currentData(),
                distances={zone: row.distance.value() for zone, row in self.rows.items()},
            )
        except ModelError as error:
            QMessageBox.warning(self, "Cannot compute thresholds", str(error))
            return
        self.state.set_model(model, save=True)
        message = (f"Model saved to {self.state.model_path}" if not warnings
                   else "Model saved. Notes: " + "; ".join(warnings))
        self.state.status.emit(message, "#68d6bd")

    def _on_model_changed(self, model):
        self.dist_plot.clear()
        self.table.clearContents()
        if model is None:
            self.threshold_label.setText("No model yet - record all three zones, then compute.")
            return
        # reflect the model's own settings in the controls
        for combo, value in ((self.filter_combo, model.filter_kind),
                             (self.rep_combo, model.representative),
                             (self.method_combo, model.threshold_method)):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        self.window.setValue(model.window)
        self.threshold_label.setText(
            f"near  >= {model.t_near_medium:.1f} dBm   ·   "
            f"medium >= {model.t_medium_far:.1f} dBm   ·   far below")

        runs, _ = load_runs(find_run_files(self.state.data_dir, "calibration"))
        runs = [r for r in runs if r.session in set(model.calibration_sessions)]
        per_zone = {}
        for zone in ZONES:
            chunks = [smoothed_samples(r, model.filter_kind, model.window)
                      for r in runs if r.zone == zone]
            per_zone[zone] = np.concatenate(chunks) if chunks else np.array([])
        self._draw_table(model, per_zone)
        self._draw_distribution(model, per_zone)

    def _draw_table(self, model, per_zone):
        for row, zone in enumerate(ZONES):
            stats = describe(per_zone[zone])
            greek, english = ZONE_LABELS[zone]
            _cell(self.table, row, 0, f"{greek} / {english}", Qt.AlignLeft | Qt.AlignVCenter)
            _cell(self.table, row, 1, f"{model.distances.get(zone, float('nan')):.1f} m")
            _cell(self.table, row, 2, str(stats["n"]))
            for col, key in enumerate(("mean", "median", "std", "min", "max"), start=3):
                _cell(self.table, row, col, f"{stats[key]:.1f}")
        self.table.resizeColumnsToContents()

    def _draw_distribution(self, model, per_zone):
        non_empty = [v for v in per_zone.values() if v.size]
        if not non_empty:
            return
        merged = np.concatenate(non_empty)
        edges = np.arange(np.floor(merged.min()) - 1, np.ceil(merged.max()) + 2, 1.0)
        for zone in ZONES:
            if not per_zone[zone].size:
                continue
            counts, _ = np.histogram(per_zone[zone], bins=edges)
            color = ZONE_COLORS[zone]
            self.dist_plot.plot(
                edges, counts, stepMode=True, fillLevel=0, brush=qcolor(color, 90),
                pen=pg.mkPen(color, width=1.5), name=ZONE_LABELS[zone][1])
        for value in model.thresholds:
            self.dist_plot.addItem(pg.InfiniteLine(
                pos=value, angle=90, pen=pg.mkPen("#d7e0e3", width=1.5, style=Qt.DashLine),
                label=f"{value:.1f}", labelOpts={"position": 0.92, "color": "#d7e0e3"}))

    # ── folder ─────────────────────────────────────────────────────────────
    def _change_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choose data folder", self.state.data_dir)
        if path:
            self.state.set_data_dir(path)

    def _on_data_dir_changed(self):
        self.folder_label.setText(self.state.data_dir)
        self.refresh_summary()
