"""Evaluate tab: accuracy of the model on separately recorded test measurements."""

import csv
import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from rssi_proximity.classify.commentary import build_commentary
from rssi_proximity.classify.evaluate import evaluate
from rssi_proximity.config import ZONE_COLORS, ZONE_LABELS, ZONES
from rssi_proximity.gui.theme import caption, hint, section_label
from rssi_proximity.storage.csv_logger import find_run_files, load_runs

NOTES_FILENAME = "evaluation_notes.txt"


def _cell(table, row, col, text, align=Qt.AlignCenter, color=None):
    item = QTableWidgetItem(text)
    item.setTextAlignment(align)
    if color is not None:
        item.setBackground(color)
    table.setItem(row, col, item)


class EvaluateTab(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._runs = []
        self._result = None

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        right = QVBoxLayout()
        root.addLayout(left, stretch=3)
        root.addLayout(right, stretch=2)

        # ── left: load + results ───────────────────────────────────────────
        left.addWidget(section_label("TEST DATA"))
        left.addWidget(hint(
            "Evaluate on measurements that were NOT used to set the thresholds: record a "
            "separate 'Test set' on the Calibrate tab (another time, same zone positions)."))
        buttons = QHBoxLayout()
        folder_btn = QPushButton("Use test CSVs from data folder")
        folder_btn.setObjectName("PrimaryAction")
        folder_btn.clicked.connect(self._load_from_folder)
        files_btn = QPushButton("Choose CSV files...")
        files_btn.clicked.connect(self._choose_files)
        buttons.addWidget(folder_btn)
        buttons.addWidget(files_btn)
        buttons.addStretch(1)
        left.addLayout(buttons)
        self.source_label = QLabel("No test data loaded.")
        self.source_label.setObjectName("Hint")
        left.addWidget(self.source_label)
        self.warning_label = QLabel("")
        self.warning_label.setObjectName("Warning")
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)
        left.addWidget(self.warning_label)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QHBoxLayout(card)
        box = QVBoxLayout()
        box.addWidget(caption("CORRECT CLASSIFICATIONS"))
        self.accuracy_label = QLabel("-")
        self.accuracy_label.setStyleSheet("font-size:40px; font-weight:bold; color:#68d6bd;")
        box.addWidget(self.accuracy_label)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Hint")
        box.addWidget(self.count_label)
        card_layout.addLayout(box)
        card_layout.addStretch(1)
        left.addWidget(card)

        left.addWidget(section_label("CONFUSION MATRIX  (rows = true zone, columns = estimated)"))
        self.confusion = QTableWidget(len(ZONES), len(ZONES) + 1)
        self.confusion.setHorizontalHeaderLabels(
            [ZONE_LABELS[z][1] for z in ZONES] + ["Correct"])
        self.confusion.setVerticalHeaderLabels([ZONE_LABELS[z][1] for z in ZONES])
        self.confusion.setEditTriggers(QTableWidget.NoEditTriggers)
        self.confusion.setFixedHeight(150)
        self.confusion.horizontalHeader().setStretchLastSection(True)
        left.addWidget(self.confusion)

        left.addWidget(section_label("BY RECORDING CONDITION"))
        columns = ("Condition", "Samples", "Correct", "Mean RSSI", "Std")
        self.conditions = QTableWidget(0, len(columns))
        self.conditions.setHorizontalHeaderLabels(columns)
        self.conditions.verticalHeader().setVisible(False)
        self.conditions.setEditTriggers(QTableWidget.NoEditTriggers)
        self.conditions.horizontalHeader().setStretchLastSection(True)
        left.addWidget(self.conditions, stretch=1)

        export_btn = QPushButton("Export predictions CSV...")
        export_btn.clicked.connect(self._export)
        left.addWidget(export_btn, alignment=Qt.AlignLeft)

        # ── right: commentary ──────────────────────────────────────────────
        right.addWidget(section_label("EFFECT OF OBSTACLES AND DEVICE ORIENTATION"))
        self.commentary = QPlainTextEdit()
        self.commentary.setReadOnly(True)
        self.commentary.setPlainText("Load test data to generate a summary.")
        right.addWidget(self.commentary, stretch=3)
        right.addWidget(section_label("YOUR NOTES"))
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText(
            "Write your own observations here, e.g. what happened behind the wall or when the "
            "laptop was rotated.")
        right.addWidget(self.notes, stretch=2)
        save_notes = QPushButton("Save notes")
        save_notes.clicked.connect(self._save_notes)
        right.addWidget(save_notes, alignment=Qt.AlignLeft)

        state.model_changed.connect(lambda _model: self._evaluate())
        state.data_dir_changed.connect(lambda _path: self._load_notes())
        self._load_notes()

    # ── loading ────────────────────────────────────────────────────────────
    def _load_from_folder(self):
        files = find_run_files(self.state.data_dir, "test")
        if not files:
            QMessageBox.information(
                self, "No test data",
                f"No test_*.csv files in {self.state.data_dir}.\n"
                "Record a 'Test set' on the Calibrate tab first.")
            return
        self._load(files)

    def _choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Choose test CSV files", self.state.data_dir, "CSV files (*.csv)")
        if files:
            self._load(files)

    def _load(self, files):
        self._runs, warnings = load_runs(files)
        self.source_label.setText(f"{len(files)} file(s), {sum(r.n for r in self._runs)} samples loaded.")
        self._evaluate(extra_warnings=warnings)

    # ── evaluation ─────────────────────────────────────────────────────────
    def _evaluate(self, extra_warnings=None):
        if not self._runs:
            return
        model = self.state.model
        if model is None:
            self.warning_label.setText("No model yet - compute thresholds on the Calibrate tab.")
            self.warning_label.setVisible(True)
            return
        result = evaluate(model, self._runs)
        self._result = result
        warnings = list(extra_warnings or []) + result.warnings
        self.warning_label.setText("\n".join(warnings))
        self.warning_label.setVisible(bool(warnings))

        if result.n == 0:
            self.accuracy_label.setText("-")
            self.count_label.setText("No usable samples (runs shorter than the filter window?).")
        else:
            self.accuracy_label.setText(f"{result.accuracy * 100:.1f} %")
            self.count_label.setText(f"{result.correct} of {result.n} samples")
        self._fill_confusion(result)
        self._fill_conditions(result)
        self.commentary.setPlainText(build_commentary(result))

    def _fill_confusion(self, result):
        for i, zone in enumerate(ZONES):
            row_total = int(result.confusion[i].sum())
            for j in range(len(ZONES)):
                count = int(result.confusion[i, j])
                color = None
                if count and row_total:
                    base = QColor(ZONE_COLORS[ZONES[j]] if i == j else "#E25C5C")
                    base.setAlpha(int(40 + 160 * count / row_total))
                    color = base
                _cell(self.confusion, i, j, str(count), color=color)
            acc = result.per_zone_accuracy[zone]
            _cell(self.confusion, i, len(ZONES), "-" if acc != acc else f"{acc * 100:.1f} %")

    def _fill_conditions(self, result):
        self.conditions.setRowCount(len(result.per_condition))
        for row, item in enumerate(result.per_condition):
            _cell(self.conditions, row, 0, item.condition, Qt.AlignLeft | Qt.AlignVCenter)
            _cell(self.conditions, row, 1, str(item.n))
            _cell(self.conditions, row, 2, f"{item.accuracy * 100:.1f} %")
            _cell(self.conditions, row, 3, f"{item.mean_rssi:.1f} dBm")
            _cell(self.conditions, row, 4, f"{item.std_rssi:.1f}")
        self.conditions.resizeColumnsToContents()

    # ── export / notes ─────────────────────────────────────────────────────
    def _export(self):
        if self._result is None or self._result.n == 0:
            QMessageBox.information(self, "Nothing to export", "Evaluate some test data first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export predictions", os.path.join(self.state.data_dir, "predictions.csv"),
            "CSV files (*.csv)")
        if not path:
            return
        result = self._result
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(("true_zone", "predicted_zone", "smoothed_rssi_dbm", "condition"))
                for row in zip(result.true_labels, result.predicted, result.rssi, result.conditions):
                    writer.writerow((row[0], row[1], f"{row[2]:.2f}", row[3]))
        except OSError as error:
            QMessageBox.warning(self, "Export failed", str(error))
            return
        self.state.status.emit(f"Predictions exported to {path}", "#68d6bd")

    def _notes_path(self):
        return os.path.join(self.state.data_dir, NOTES_FILENAME)

    def _load_notes(self):
        try:
            with open(self._notes_path(), encoding="utf-8") as handle:
                self.notes.setPlainText(handle.read())
        except OSError:
            self.notes.clear()

    def _save_notes(self):
        try:
            os.makedirs(self.state.data_dir, exist_ok=True)
            with open(self._notes_path(), "w", encoding="utf-8") as handle:
                handle.write(self.notes.toPlainText())
        except OSError as error:
            QMessageBox.warning(self, "Could not save notes", str(error))
            return
        self.state.status.emit(f"Notes saved to {self._notes_path()}", "#68d6bd")
