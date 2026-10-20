"""Look and feel, adapted from EEG Studio's theme.py (same dark teal palette and icon helper)."""

from PyQt5.QtCore import QByteArray, QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QFrame, QLabel

try:  # QtSvg ships with the PyQt5 wheel; degrade to text-only buttons if missing
    from PyQt5.QtSvg import QSvgRenderer
except ImportError:  # pragma: no cover
    QSvgRenderer = None

ACCENT = "#46b8a8"
TEXT = "#cccccc"
BG = "#111416"

BASE_STYLESHEET = """
QMainWindow, QDialog { background-color: #111416; }
QWidget { color: #cccccc; font-family: 'Segoe UI', Arial; font-size: 13px; }
QToolBar { background-color: #171c20; border-bottom: 1px solid #334047; padding: 4px 8px; spacing: 8px; }
QLabel { color: #cccccc; }
QComboBox { background-color: #252526; color: #cccccc; border: 1px solid #3e3e42;
            border-radius: 3px; padding: 5px 8px; min-width: 80px; }
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #46b8a8; }
QComboBox QAbstractItemView { background-color: #252526; color: #cccccc; selection-background-color: #164a49; }
QPushButton { background-color: #20282d; color: #d7e0e3; font-weight: 500;
              border: 1px solid #3b4a51; border-radius: 4px; padding: 7px 12px; }
QPushButton:hover { background-color: #29363d; border-color: #46b8a8; }
QPushButton:pressed { background-color: #164a49; }
QPushButton:disabled { color: #5c6b70; background-color: #181e22; border-color: #2a353a; }
QPushButton[toggle="true"]:checked { background-color: #164a49; border: 1px solid #46b8a8; color: #ffffff; }
QPushButton[recording="true"] { background-color: #4a1f24; border: 1px solid #e25c5c; color: #ffd7d7; }
QPushButton[recording="true"]:hover { background-color: #5c262c; }
QPushButton#PrimaryAction { background-color:#238f83; color:white; border:1px solid #46b8a8; font-weight:bold; padding:9px 16px; }
QPushButton#PrimaryAction:hover { background-color:#2eaa9b; }
QStatusBar { background-color: #171c20; border-top: 1px solid #334047; color: #9aadb1; }
QStatusBar::item { border: none; }
QToolTip { background-color: #20282d; color: #d7e0e3; border: 1px solid #405159; padding: 4px 6px; }
QCheckBox, QRadioButton { color: #cccccc; padding: 3px; }
QCheckBox:hover, QRadioButton:hover { color: white; }
QDoubleSpinBox, QSpinBox { background-color: #252526; color: white; border: 1px solid #3e3e42;
                           border-radius: 3px; padding: 4px; min-width: 65px; }
QLineEdit, QPlainTextEdit { background-color: #1b2227; color: #d7e0e3; border: 1px solid #35434a;
                            border-radius: 4px; padding: 4px; selection-background-color: #164a49; }
QProgressBar { background-color: #1b2227; border: 1px solid #35434a; border-radius: 3px;
               text-align: center; color: #d7e0e3; height: 14px; }
QProgressBar::chunk { background-color: #238f83; border-radius: 2px; }
QTabWidget::pane { border: 1px solid #334047; border-radius: 4px; top: -1px; background: #111416; }
QTabBar::tab { background: #171c20; color: #9aadb1; padding: 9px 22px; border: 1px solid #334047;
               border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }
QTabBar::tab:selected { background: #164a49; color: white; border-color: #46b8a8; }
QTabBar::tab:hover:!selected { color: white; border-color: #46b8a8; }
QTableWidget { background-color: #151a1d; alternate-background-color: #1a2125; gridline-color: #2d363c;
               border: 1px solid #334047; border-radius: 4px; selection-background-color: #164a49; }
QHeaderView::section { background-color: #1b2227; color: #9aadb1; padding: 5px; border: none;
                       border-right: 1px solid #2d363c; border-bottom: 1px solid #2d363c; font-weight: bold; }
QFrame#ZoneRow { background:#1b2227; border:1px solid #2d363c; border-radius:5px; }
QFrame#ZoneRow:hover { border-color:#46b8a8; }
QFrame#Card { background-color:#1b252a; border:1px solid #35434a; border-radius:5px; }
QLabel#Metric { color:#f1f7f6; font-size:22px; font-weight:bold; }
QLabel#Caption { color:#769096; font-size:10px; font-weight:bold; letter-spacing:0.8px; }
QLabel#Hint { color:#9aadb1; font-size:12px; }
QLabel#Warning { color:#d9b36c; background:#2b2616; border:1px solid #5a4d22; border-radius:4px; padding:6px 8px; }
QLabel#Badge { color:#68d6bd; background:#173b3a; border:1px solid #28685f; border-radius:4px;
               padding:4px 8px; font-family:'Consolas'; font-size:11px; font-weight:bold; }
"""

DEFAULT_COLOR = "#c9d4d7"

_SHAPES = {
    "record": '<circle cx="12" cy="12" r="6.5" fill="COLOR" stroke="none"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="COLOR" stroke="none"/>',
    "play": '<path d="M7 4.5v15l12-7.5z" fill="COLOR" stroke="none"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19.5 7"/>',
    "reset": '<path d="M4.5 12a7.5 7.5 0 1 0 2.4-5.5"/><path d="M4.5 4.5V9H9"/>',
    "wave": '<path d="M2 12h3.5l2.5-7 4 14 3-10 2 3h5"/>',
    "settings": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
}
_cache = {}


def icon(name, color=DEFAULT_COLOR, size=32):
    key = (name, color, size)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    shape = _SHAPES.get(name)
    if QSvgRenderer is None or shape is None:
        return QIcon()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
        + shape.replace("COLOR", color) + "</svg>"
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    result = QIcon(pixmap)
    _cache[key] = result
    return result


def set_button(button, text=None, icon_name=None, color=DEFAULT_COLOR, icon_px=16):
    if text is not None:
        button.setText(text)
    if icon_name is not None:
        button.setIcon(icon(icon_name, color))
        button.setIconSize(QSize(icon_px, icon_px))


def set_property(widget, name, value):
    """Set a dynamic property and re-polish so [name="value"] stylesheet selectors update."""
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def section_label(text):
    label = QLabel(text)
    label.setStyleSheet(
        "font-weight: bold; color: #b8d8d5; font-size: 11px; letter-spacing: 1.2px;"
        " padding: 5px 7px; background:#26363b; border-left:3px solid #46b8a8; border-radius:2px;"
    )
    return label


def caption(text):
    label = QLabel(text)
    label.setObjectName("Caption")
    return label


def hint(text):
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(True)
    return label


def qcolor(hex_color, alpha=255):
    color = QColor(hex_color)
    color.setAlpha(alpha)
    return color


def hline():
    sep = QFrame()
    sep.setFrameShape(QFrame.HLine)
    sep.setStyleSheet("color: #2b2b2b; background-color: #2b2b2b; max-height: 1px;")
    return sep
