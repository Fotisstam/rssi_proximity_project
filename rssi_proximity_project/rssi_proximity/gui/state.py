"""Shared application state: backend, tracked AP, scanner thread, model, data folder."""

import os
from typing import Optional

from PyQt5.QtCore import QObject, QSettings, pyqtSignal

from rssi_proximity.acquisition.backends import Backend, Target
from rssi_proximity.classify.model import ModelError, ProximityModel
from rssi_proximity.config import DEFAULT_POLL_S, MODEL_FILENAME, default_data_dir
from rssi_proximity.gui.workers import ScannerThread


class AppState(QObject):
    reading = pyqtSignal(object)         # Reading
    scanning_changed = pyqtSignal(bool)
    target_changed = pyqtSignal(object)  # Target | None
    model_changed = pyqtSignal(object)   # ProximityModel | None
    data_dir_changed = pyqtSignal(str)
    status = pyqtSignal(str, str)        # message, colour

    def __init__(self, backend: Backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.target: Optional[Target] = None
        self.model: Optional[ProximityModel] = None
        self.interval_s = DEFAULT_POLL_S
        self._settings = QSettings("RSSIProximity", "RSSIProximity")
        self.data_dir = str(self._settings.value("data_dir", default_data_dir()))
        self._thread: Optional[ScannerThread] = None
        self._retired = []               # stopped threads that may still be finishing a netsh call

    # ── data folder / model file ──────────────────────────────────────────
    def set_data_dir(self, path: str) -> None:
        self.data_dir = path
        self._settings.setValue("data_dir", path)
        self.data_dir_changed.emit(path)
        self.load_model()

    @property
    def model_path(self) -> str:
        return os.path.join(self.data_dir, MODEL_FILENAME)

    def load_model(self) -> None:
        model = None
        if os.path.isfile(self.model_path):
            try:
                with open(self.model_path, encoding="utf-8") as handle:
                    model = ProximityModel.from_json(handle.read())
            except (OSError, ValueError, ModelError) as error:
                self.status.emit(f"Could not load saved model: {error}", "#E25C5C")
        self.set_model(model)

    def set_model(self, model: Optional[ProximityModel], save: bool = False) -> None:
        self.model = model
        if save and model is not None:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.model_path, "w", encoding="utf-8") as handle:
                handle.write(model.to_json())
        self.model_changed.emit(model)

    # ── tracked AP / scanning ─────────────────────────────────────────────
    def set_target(self, target: Optional[Target]) -> None:
        was_scanning = self.is_scanning
        self.stop_scanning()
        self.target = target
        self.target_changed.emit(target)
        if was_scanning and target is not None:
            self.start_scanning()

    @property
    def is_scanning(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def ensure_ready(self) -> bool:
        """True when a target is chosen and scanning is running (starts it if needed)."""
        if self.target is None:
            self.status.emit("Select an access point first.", "#D9B36C")
            return False
        if not self.is_scanning:
            self.start_scanning()
        return True

    def start_scanning(self) -> None:
        if self.target is None or self.is_scanning:
            return
        thread = ScannerThread(self.backend, self.target, self.interval_s)
        thread.reading.connect(self.reading)
        thread.failed.connect(lambda msg: self.status.emit(msg, "#E25C5C"))
        thread.start()
        self._thread = thread
        self.scanning_changed.emit(True)
        self.status.emit("Scanning...", "#68d6bd")

    def stop_scanning(self) -> None:
        thread = self._thread
        if thread is None:
            return
        thread.stop()
        thread.reading.disconnect()
        thread.failed.disconnect()
        self._retired = [t for t in self._retired if t.isRunning()] + [thread]
        self._thread = None
        self.scanning_changed.emit(False)

    def set_interval(self, seconds: float) -> None:
        self.interval_s = float(seconds)
        if self._thread is not None:
            self._thread.set_interval(seconds)

    def shutdown(self) -> None:
        self.stop_scanning()
        for thread in self._retired:
            thread.wait(9000)
