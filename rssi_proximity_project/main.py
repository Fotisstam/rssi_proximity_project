"""RSSI Proximity entry point: `python main.py` (add --simulate to try it without Wi-Fi access)."""

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Wi-Fi RSSI proximity estimator")
    parser.add_argument("--simulate", action="store_true",
                        help="use a synthetic signal instead of reading Wi-Fi (default off Windows)")
    args, qt_args = parser.parse_known_args(argv)

    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication([sys.argv[0]] + qt_args)

    from rssi_proximity.acquisition.backends import NetshBackend, SimControls, SimulatedBackend
    from rssi_proximity.gui.main_window import MainWindow
    from rssi_proximity.gui.plots import configure_pyqtgraph
    from rssi_proximity.gui.state import AppState

    configure_pyqtgraph()
    simulate = args.simulate or not sys.platform.startswith("win")
    if simulate:
        controls = SimControls()
        backend = SimulatedBackend(zone_getter=lambda: controls.zone,
                                   obstacle_getter=lambda: controls.obstacle_db)
    else:
        controls = None
        backend = NetshBackend()

    state = AppState(backend)
    window = MainWindow(state, controls)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
