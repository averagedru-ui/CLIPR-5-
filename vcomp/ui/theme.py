"""Dark theme - a modern flat palette + Qt stylesheet.

Deep near-black grounds, one blue accent, rounded controls, subtle borders,
clear hover / pressed / checked states.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# Dark ground, forest-green accent, warm cream text, tan highlights.
BG        = "#101210"    # window ground (warm near-black)
SURFACE   = "#181a17"    # panels
SURFACE_2 = "#20231e"    # inputs / raised
SURFACE_3 = "#2b2f28"    # hover
BORDER    = "#343a30"
BORDER_HI = "#47503f"
TEXT      = "#F5F0E6"    # warm cream
TEXT_DIM  = "#BFA880"    # warm tan/khaki
ACCENT    = "#3D6147"    # forest green
ACCENT_HI = "#4f7d5c"    # lighter green (hover)
ACCENT_DN = "#2c4735"    # darker green (pressed)
DANGER    = "#e5484d"

# back-compat aliases used elsewhere
BACKGROUND = BG
PANEL = SURFACE
PANEL_LIGHT = SURFACE_2

_QSS = f"""
* {{ outline: none; }}
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}}
QToolTip {{
    background: {SURFACE_2}; color: {TEXT};
    border: 1px solid {BORDER_HI}; padding: 4px 6px; border-radius: 4px;
}}

/* menu bar */
QMenuBar {{ background: {SURFACE}; padding: 2px 4px; }}
QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 5px; }}
QMenuBar::item:selected {{ background: {SURFACE_3}; }}
QMenu {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}

/* status bar */
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {TEXT_DIM}; }}
QStatusBar::item {{ border: 0; }}

/* buttons */
QPushButton {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 6px 12px;
    color: {TEXT};
}}
QPushButton:hover {{ background: {SURFACE_3}; border-color: {BORDER_HI}; }}
QPushButton:pressed {{ background: {ACCENT_DN}; border-color: {ACCENT_DN}; color: white; }}
QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton:disabled {{ color: {TEXT_DIM}; background: {SURFACE}; }}
QPushButton#primary {{
    background: {ACCENT}; border: 1px solid {ACCENT}; color: white; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {ACCENT_HI}; border-color: {ACCENT_HI}; }}
QPushButton#primary:pressed {{ background: {ACCENT_DN}; }}

/* segmented toggle (viewport switch) */
QPushButton#segL, QPushButton#segR {{ padding: 6px 16px; }}
QPushButton#segL {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
QPushButton#segR {{ border-top-left-radius: 0; border-bottom-left-radius: 0; border-left: 0; }}

/* inputs */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 7px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{ border: 0; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px;
    selection-background-color: {ACCENT};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; border: 0; background: {SURFACE_3}; }}

/* sliders */
QSlider::groove:horizontal {{ height: 4px; background: {SURFACE_3}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {TEXT}; width: 13px; height: 13px; margin: -5px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: white; }}

/* checkboxes */
QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {BORDER_HI}; background: {SURFACE_2};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

/* group boxes (properties sections) - flat divider, no pill behind the title */
QGroupBox {{
    border: 0;
    border-top: 1px solid {BORDER};
    border-radius: 0;
    margin-top: 20px;
    padding: 8px 2px 2px 2px;
    background: transparent;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 0; padding: 2px 0;
    background: transparent;
    color: {TEXT_DIM}; font-weight: 700; text-transform: uppercase; font-size: 10px;
}}

/* scrollbars */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_HI}; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_HI}; border-radius: 5px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* splitter */
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QSplitter::handle:hover {{ background: {ACCENT}; }}

/* toolbar strip */
QWidget#toolbar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QLabel#panelTitle {{ color: {TEXT_DIM}; font-weight: 600; font-size: 10px; text-transform: uppercase; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor(SURFACE_2))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(SURFACE_2))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE_2))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_DIM))
    app.setPalette(pal)
    app.setStyleSheet(_QSS)
