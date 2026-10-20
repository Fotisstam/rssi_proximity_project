"""Pop-up that scans for Wi-Fi networks and lets the user choose the access point."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from rssi_proximity.acquisition.backends import Target
from rssi_proximity.gui.theme import hint
from rssi_proximity.gui.workers import AccessPointListThread

COLUMNS = ("SSID", "BSSID", "Signal", "≈ dBm", "Band", "Ch")


class SsidDialog(QDialog):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select access point")
        self.resize(720, 420)
        self._backend = backend
        self._aps = []
        self._thread = None
        self._target = None

        layout = QVBoxLayout(self)
        layout.addWidget(hint(
            "Pick the access point to measure. Networks with several radios (2.4 GHz / 5 GHz, "
            "mesh nodes) appear once per BSSID - choose the one you will stand near."
        ))

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 150)
        self.table.itemDoubleClicked.connect(lambda _item: self._accept())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.table, stretch=1)

        self.lock_bssid = QCheckBox("Lock to this exact BSSID (recommended)")
        self.lock_bssid.setChecked(True)
        self.lock_bssid.setToolTip(
            "Unchecked: follow the strongest BSSID of the chosen SSID, "
            "which may switch between radios."
        )
        layout.addWidget(self.lock_bssid)

        self.status = QLabel("")
        layout.addWidget(self.status)

        row = QHBoxLayout()
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.clicked.connect(self.rescan)
        row.addWidget(self.rescan_btn)
        row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        self.select_btn = QPushButton("Select")
        self.select_btn.setObjectName("PrimaryAction")
        self.select_btn.clicked.connect(self._accept)
        row.addWidget(self.select_btn)
        layout.addLayout(row)

        self._update_buttons()
        self.rescan()

    # ── scanning ───────────────────────────────────────────────────────────
    def rescan(self):
        if self._thread is not None and self._thread.isRunning():
            return
        self.status.setText("Scanning for networks...")
        self.rescan_btn.setEnabled(False)
        self._thread = AccessPointListThread(self._backend, self)
        self._thread.found.connect(self._on_found)
        self._thread.failed.connect(self._on_failed)
        self._thread.finished.connect(lambda: self.rescan_btn.setEnabled(True))
        self._thread.start()

    def _on_found(self, aps):
        self._aps = sorted(aps, key=lambda ap: (ap.ssid.lower(), -ap.signal_pct))
        self.table.setRowCount(len(self._aps))
        for row, ap in enumerate(self._aps):
            cells = (ap.ssid, ap.bssid, f"{ap.signal_pct} %", f"{ap.rssi_dbm:.1f}",
                     ap.band, "" if ap.channel is None else str(ap.channel))
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col >= 2:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)
        self.status.setText(f"{len(self._aps)} access point(s) found.")
        if self._aps:
            self.table.selectRow(0)

    def _on_failed(self, message):
        self.status.setText(message)

    # ── result ─────────────────────────────────────────────────────────────
    def _update_buttons(self):
        self.select_btn.setEnabled(bool(self.table.selectedItems()))

    def _accept(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        ap = self._aps[rows[0].row()]
        bssid = ap.bssid if self.lock_bssid.isChecked() else None
        self._target = Target(ssid=ap.ssid, bssid=bssid, band=ap.band)
        self.accept()

    def selected_target(self):
        return self._target

    def done(self, result):
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(9000)
        super().done(result)
