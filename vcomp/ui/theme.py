"""Dark theme: a Qt stylesheet plus a small palette of named colors.

Colors follow spec section 7.8: ~#1a1a1e background, #2a2a30 panels, one accent
used sparingly.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BACKGROUND = "#1a1a1e"
PANEL = "#2a2a30"
PANEL_LIGHT = "#33333b"
BORDER = "#3d3d46"
TEXT = "#d8d8dc"
TEXT_DIM = "#8a8a92"
ACCENT = "#4c8dff"

_QSS = f"""
QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT};
    font-size: 12px;
}}
QMainWindow::separator {{ background: {BORDER}; width: 3px; height: 3px; }}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{
    background: {PANEL};
    padding: 5px 8px;
    border-bottom: 1px solid {BORDER};
}}
QDockWidget > QWidget {{ background: {PANEL}; }}
QMenuBar {{ background: {PANEL}; }}
QMenuBar::item:selected {{ background: {PANEL_LIGHT}; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
QPushButton {{
    background: {PANEL_LIGHT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 10px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT}; color: white; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {BACKGROUND};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 2px 4px;
}}
QScrollBar:vertical {{ background: {BACKGROUND}; width: 12px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar:horizontal {{ background: {BACKGROUND}; height: 12px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 24px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BACKGROUND))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor(BACKGROUND))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(PANEL_LIGHT))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(PANEL))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    app.setPalette(pal)
    app.setStyleSheet(_QSS)
