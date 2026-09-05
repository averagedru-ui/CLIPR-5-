"""QApplication bootstrap: theme, settings, main window wiring."""
from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from vcomp.ui.main_window import MainWindow
from vcomp.ui.splash import SplashScreen
from vcomp.ui.theme import apply_theme
from vcomp.util import logging as vlog
from vcomp.util.settings import Settings

log = logging.getLogger("vcomp.app")


def run() -> int:
    vlog.setup_logging()
    log.info("CLIPR starting")

    app = QApplication(sys.argv)
    app.setApplicationName("CLIPR")
    app.setOrganizationName("CLIPR")
    apply_theme(app)

    splash = SplashScreen()
    splash.show()
    app.processEvents()

    settings = Settings()
    win = MainWindow(settings)   # heavy init happens here, splash stays on screen

    def _reveal() -> None:
        win.show()
        splash.close()

    splash.finished.connect(_reveal)
    splash.start()

    def emergency_save() -> None:
        settings.save()
        try:
            from vcomp.core.autosave import write_autosave
            from vcomp.core.project import Project

            if getattr(win, "graph", None) is not None and len(win.graph.nodes) > 1:
                write_autosave(Project(graph=win.graph))
        except Exception:  # noqa: BLE001
            pass

    vlog.register_emergency_save(emergency_save)
    vlog.install_excepthook()

    return app.exec()
