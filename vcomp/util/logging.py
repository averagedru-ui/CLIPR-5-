"""Logging setup and the global exception hook.

Logs go to the console and to a rotating file under ``%APPDATA%/VCOMP/logs/``.
The exception hook logs the traceback, shows a Qt dialog with a Copy button,
and attempts an emergency project save if a hook is registered.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from typing import Callable, Optional

from vcomp.util import paths

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_emergency_save: Optional[Callable[[], None]] = None


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(console)

    logfile = paths.logs_dir() / "vcomp.log"
    fileh = logging.handlers.RotatingFileHandler(
        logfile, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    fileh.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(fileh)

    logging.getLogger("vcomp").info("Logging initialised -> %s", logfile)
    return logging.getLogger("vcomp")


def register_emergency_save(fn: Callable[[], None]) -> None:
    """Register a callable invoked from the exception hook before the dialog."""
    global _emergency_save
    _emergency_save = fn


def install_excepthook() -> None:
    log = logging.getLogger("vcomp")

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.critical("Unhandled exception:\n%s", text)

        if _emergency_save is not None:
            try:
                _emergency_save()
                log.info("Emergency save completed")
            except Exception:  # noqa: BLE001 - last-ditch, must not raise
                log.exception("Emergency save failed")

        _show_dialog(text)

    sys.excepthook = hook


def _show_dialog(text: str) -> None:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is None:
            return
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("VCOMP - Unexpected Error")
        box.setText("An unexpected error occurred. The app tried to save your work.")
        box.setDetailedText(text)
        copy_btn = box.addButton("Copy", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is copy_btn:
            QApplication.clipboard().setText(text)
    except Exception:  # noqa: BLE001
        logging.getLogger("vcomp").exception("Failed to show error dialog")
