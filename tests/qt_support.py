"""測試共用唯一 QApplication，離屏執行避免測試視窗干擾使用者。"""
import os
import atexit
import gc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent
import shiboken6
from src.qt_style import apply_style

QT_APP = QApplication.instance() or QApplication([])
QT_APP.setQuitOnLastWindowClosed(False)
apply_style(QT_APP)


def shutdown_qt():
    """在 Python 模組解構前釋放 Qt 視窗，避免 Windows 偶發 shutdown crash。"""
    for widget in QT_APP.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    shiboken6.delete(QT_APP)


atexit.register(shutdown_qt)
