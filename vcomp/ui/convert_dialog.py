"""Convert for Mobile: batch re-encode clips to H.264 so they play on any
phone. Straight ffmpeg transcode (no compositing/node graph involved) -
exists because AV1/HEVC recordings (common NVENC defaults on newer GPUs)
don't decode on most iPhones, which the mobile web client can't work
around from inside the browser.
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from vcomp.export.encoder import _ENCODER_TABLE, detect_encoders
from vcomp.util import paths

_PREFERRED_ORDER = ["nvenc", "amf", "qsv", "x264"]


def _pick_encoder():
    available = {e.key: e for e in detect_encoders()}
    for key in _PREFERRED_ORDER:
        if key in available:
            return available[key]
    return _ENCODER_TABLE[0]


class ConvertWorker(QThread):
    fileDone = Signal(int, bool, str)  # index, ok, message
    allDone = Signal()

    def __init__(self, files: list[str], out_dir: str | None):
        super().__init__()
        self._files = files
        self._out_dir = out_dir
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None

    def cancel(self) -> None:
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def run(self) -> None:
        enc = _pick_encoder()
        exe = str(paths.ffmpeg_exe())
        for i, src in enumerate(self._files):
            if self._stop.is_set():
                break
            src_path = Path(src)
            out_dir = Path(self._out_dir) if self._out_dir else src_path.parent
            out_path = out_dir / f"{src_path.stem}_h264.mp4"
            args = [
                exe, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(src_path),
                "-c:v", enc.codec, *enc.extra,
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(out_path),
            ]
            try:
                self._proc = subprocess.Popen(
                    args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
                )
                _, stderr = self._proc.communicate()
                ok = self._proc.returncode == 0
                msg = str(out_path) if ok else (stderr or "ffmpeg failed").strip().splitlines()[-1:]
                msg = msg if isinstance(msg, str) else (msg[0] if msg else "ffmpeg failed")
                self.fileDone.emit(i, ok, msg)
            except OSError as exc:
                self.fileDone.emit(i, False, str(exc))
            finally:
                self._proc = None
        self.allDone.emit()


class ConvertDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Convert for Mobile")
        self.resize(560, 420)
        self._worker: ConvertWorker | None = None
        self._out_dir: str | None = None

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Re-encodes clips to H.264 (via the fastest available hardware "
            "encoder) so they play on any phone - AV1/HEVC recordings often "
            "don't decode on iOS."
        ))

        self.list = QListWidget()
        lay.addWidget(self.list)

        row = QHBoxLayout()
        add = QPushButton("Add clips...")
        add.clicked.connect(self._add_clips)
        rm = QPushButton("Remove")
        rm.clicked.connect(lambda: self.list.takeItem(self.list.currentRow()))
        row.addWidget(add)
        row.addWidget(rm)
        lay.addLayout(row)

        self.out_label = QLabel("output: <same folder as each clip>")
        pick = QPushButton("Choose output folder...")
        pick.clicked.connect(self._pick_out)
        lay.addWidget(self.out_label)
        lay.addWidget(pick)

        self.bar = QProgressBar()
        lay.addWidget(self.bar)
        self.status = QLabel("")
        lay.addWidget(self.status)

        self.btn = QPushButton("Start")
        self.btn.clicked.connect(self._toggle)
        lay.addWidget(self.btn)

    def _add_clips(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add clips", "", "Video (*.mp4 *.mov *.mkv *.webm *.avi)"
        )
        for f in files:
            self.list.addItem(f)

    def _pick_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Output folder")
        if d:
            self._out_dir = d
            self.out_label.setText(f"output: {d}")

    def _toggle(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self.btn.setText("Start")
            return
        files = [self.list.item(i).text() for i in range(self.list.count())]
        if not files:
            self.status.setText("add some clips first")
            return
        self.bar.setMaximum(len(files))
        self.bar.setValue(0)
        self.btn.setText("Stop")
        self._worker = ConvertWorker(files, self._out_dir)
        self._worker.fileDone.connect(self._on_file_done)
        self._worker.allDone.connect(self._on_all_done)
        self._worker.start()

    def _on_file_done(self, index: int, ok: bool, msg: str) -> None:
        self.bar.setValue(index + 1)
        name = Path(self.list.item(index).text()).name
        self.status.setText(f"{'done' if ok else 'FAILED'}: {name}" + ("" if ok else f" - {msg}"))

    def _on_all_done(self) -> None:
        self.btn.setText("Start")
        if self.status.text().startswith("FAILED"):
            return
        self.status.setText("conversion complete")
