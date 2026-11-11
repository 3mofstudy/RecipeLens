"""RecipeLens 共用 Qt 配色與元件樣式。"""
from pathlib import Path
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


STYLE = """
QWidget { font-family: 'Microsoft JhengHei UI', 'Microsoft JhengHei', sans-serif;
    font-size: 13px; color: #24344b; }
QMainWindow, QDialog { background: #f3f6fb; }
QWidget#header { background: #ffffff; border-bottom: 1px solid #e3eaf3; }
QLabel#brand { font-size: 24px; font-weight: 800; color: #163d6b; }
QLabel#heading { font-size: 22px; font-weight: 700; color: #18395e; }
QLabel#subtitle, QLabel#muted { color: #65778f; }
QLabel#eyebrow { color: #2777c9; font-size: 11px; font-weight: 700; }
QLabel#cardTitle { font-size: 16px; font-weight: 700; color: #193b62; }
QFrame#card { background: white; border: 1px solid #e0e8f2; border-radius: 16px; }
QLabel#badge { color: #256fb0; background: #eaf3ff; border-radius: 10px; padding: 5px 12px; }
QLineEdit, QComboBox { background: #f9fbfe; border: 1px solid #d6e1ee;
    border-radius: 8px; padding: 9px 10px; min-height: 19px; selection-background-color: #cce5ff; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #368cdd; background: white; }
QLineEdit:read-only { color: #63788e; background: #f0f4f9; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url(@UI@/chevron.svg); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #e2efff; selection-color: #18395e; }
QPushButton { background: #edf4fc; color: #245e98; border: 1px solid #dbe6f3;
    border-radius: 8px; padding: 9px 14px; font-weight: 600; }
QPushButton:hover { background: #deedff; border-color: #a9ccee; }
QPushButton:pressed { background: #cce2fa; }
QPushButton#primary { background: #ed8337; color: white; border: none;
    font-size: 16px; font-weight: 700; padding: 14px 20px; border-radius: 10px; }
QPushButton#primary:hover { background: #da7028; }
QPushButton#primary:pressed { background: #c66020; }
QPushButton:disabled, QPushButton#primary:disabled { background: #e8edf3; color: #98a5b6; border-color: #e8edf3; }
QPushButton#link { border: none; background: transparent; color: #317bc0; padding: 4px 0; text-align: left; }
QCheckBox, QRadioButton { spacing: 8px; padding: 3px 0; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox::indicator { border: 1px solid #b3c3d6; border-radius: 4px; background: white; }
QCheckBox::indicator:checked { background: #257bc1; border-color: #257bc1; image: url(@UI@/check.svg); }
QRadioButton::indicator { border: 1px solid #b3c3d6; border-radius: 8px; background: white; }
QRadioButton::indicator:checked { image: url(@UI@/radio.svg); border: none; background: transparent; }
QLabel:disabled, QCheckBox:disabled { color: #9aa8b8; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 0; }
QScrollBar::handle:vertical { background: #c6d3e2; border-radius: 4px; min-height: 32px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QTextBrowser { background: white; border: none; padding: 16px; font-size: 14px; }
QProgressBar { border: none; background: #e9f0f8; height: 5px; border-radius: 2px; }
QProgressBar::chunk { background: #368bdd; border-radius: 2px; }
QPlainTextEdit { background: #f8fafd; border: 1px solid #e3ebf4; border-radius: 8px;
    color: #667b92; padding: 8px; font-size: 12px; }
QTreeWidget { background: white; border: 1px solid #e0e8f2; border-radius: 8px;
    alternate-background-color: #f8fbff; outline: none; }
QTreeWidget::item { padding: 10px; }
QTreeWidget::item:selected { background: #deedff; color: #1d527f; }
QHeaderView::section { background: #edf4fc; padding: 10px; border: none; color: #4f6b88; }
QSplitter::handle { background: transparent; }
QToolTip { background: #173e66; color: white; border: none; padding: 6px; }
"""


def apply_style(app: QApplication):
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft JhengHei UI", 10))
    app.setStyleSheet(STYLE.replace("@UI@", (Path(__file__).resolve().parent.parent / "assets" / "ui").as_posix()))
