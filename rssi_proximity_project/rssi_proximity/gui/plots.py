"""Small pyqtgraph helpers shared by the tabs."""

import pyqtgraph as pg


def configure_pyqtgraph():
    pg.setConfigOptions(antialias=True, background="#151a1d", foreground="#9aadb1")


def make_plot(x_label="sample", y_label="RSSI (dBm)"):
    plot = pg.PlotWidget()
    plot.setBackground("#151a1d")
    plot.showGrid(x=True, y=True, alpha=0.15)
    plot.setLabel("left", y_label)
    plot.setLabel("bottom", x_label)
    plot.setMouseEnabled(x=True, y=True)
    plot.addLegend(offset=(10, 10))
    return plot
