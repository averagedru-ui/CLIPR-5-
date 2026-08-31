"""QApplication bootstrap: theme, settings, main window wiring."""
from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from vcomp.ui.main_window import MainWindow
from vcomp.ui.theme import apply_theme
from vcomp.util import logging as vlog
from vcomp.util.settings import Settings

log = logging.getLogger("vcomp.app")


def run() -> int:
    vlog.setup_logging()
    log.info("VCOMP starting")

    app = QApplication(sys.argv)
    app.setApplicationName("VCOMP")
    app.setOrganizationName("VCOMP")

    settings = Settings()
    apply_theme(app)

    win = MainWindow(settings)

    def emergency_save() -> None:
        settings.save()

    vlog.register_emergency_save(emergency_save)
    vlog.install_excepthook()

    win.show()
    return app.exec()
