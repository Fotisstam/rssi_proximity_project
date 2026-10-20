"""Background threads, so `netsh` calls (0.1-4 s each) never block the UI."""

import time

from PyQt5.QtCore import QThread, pyqtSignal

from rssi_proximity.acquisition.netsh import ScanError


class ScannerThread(QThread):
    """Reads the tracked AP every `interval_s` seconds and emits each Reading."""

    reading = pyqtSignal(object)   # acquisition.backends.Reading
    failed = pyqtSignal(str)

    def __init__(self, backend, target, interval_s, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._target = target
        self._interval_s = float(interval_s)
        self._running = False

    def set_interval(self, seconds):
        self._interval_s = max(0.2, float(seconds))

    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            started = time.monotonic()
            try:
                self.reading.emit(self._backend.read(self._target))
            except ScanError as error:
                self.failed.emit(str(error))
            except Exception as error:  # keep the loop alive on parser surprises
                self.failed.emit(f"Unexpected error: {error}")
            while self._running and time.monotonic() - started < self._interval_s:
                self.msleep(30)


class AccessPointListThread(QThread):
    """One-shot scan used by the 'Select access point' dialog."""

    found = pyqtSignal(object)   # list[AccessPoint]
    failed = pyqtSignal(str)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend

    def run(self):
        try:
            self.found.emit(self._backend.list_access_points())
        except ScanError as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(f"Unexpected error: {error}")
