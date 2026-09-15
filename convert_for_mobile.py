"""Standalone tool: batch re-encode clips to H.264 for phone playback.

AV1/HEVC recordings (common NVENC defaults on newer GPUs) often don't
decode on iOS Safari - this exists so clips can be fixed without touching
the main CLIPR app. Uses the same bundled ffmpeg.

Usage:
    python convert_for_mobile.py
"""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from vcomp.ui.convert_dialog import ConvertDialog

    app = QApplication(sys.argv)
    app.setApplicationName("CLIPR - Convert for Mobile")
    dlg = ConvertDialog(None)
    dlg.setWindowTitle("Convert for Mobile")
    dlg.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
