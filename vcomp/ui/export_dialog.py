"""Export dialog: preset / custom settings, live estimates, progress, cancel,
and a simple batch queue.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vcomp.export.encoder import detect_encoders
from vcomp.export.job import ExportJob, ExportRequest
from vcomp.export.presets import PRESETS


class ExportDialog(QDialog):
    def __init__(self, parent, graph, source_path: str, in_point: float,
                 out_point: float, speed: float = 1.0) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.setMinimumWidth(460)
        self._graph = graph
        self._source = source_path
        self._in = in_point
        self._out = max(out_point, in_point + 0.1)
        self._speed = speed
        self._job: ExportJob | None = None

        self._encoders = detect_encoders()
        self._build()
        self._update_estimate()

    # ---------------------------------------------------------------- build
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        form = QFormLayout()

        default_out = ""
        if self._source:
            p = Path(self._source)
            default_out = str(p.with_name(p.stem + "_vertical.mp4"))
        self.ed_path = QLineEdit(default_out)
        browse = QPushButton("...")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.ed_path)
        row.addWidget(browse)
        rw = QWidget()
        rw.setLayout(row)
        form.addRow("Output", rw)

        self.cb_preset = QComboBox()
        self.cb_preset.addItems(list(PRESETS) + ["Custom"])
        self.cb_preset.currentTextChanged.connect(self._apply_preset)
        form.addRow("Preset", self.cb_preset)

        self.sp_w = QSpinBox()
        self.sp_w.setRange(16, 8192)
        self.sp_h = QSpinBox()
        self.sp_h.setRange(16, 8192)
        self.sp_fps = QSpinBox()
        self.sp_fps.setRange(1, 240)
        for s in (self.sp_w, self.sp_h, self.sp_fps):
            s.valueChanged.connect(self._update_estimate)
        wh = QHBoxLayout()
        wh.addWidget(self.sp_w)
        wh.addWidget(QLabel("x"))
        wh.addWidget(self.sp_h)
        wh.addWidget(QLabel("@"))
        wh.addWidget(self.sp_fps)
        whw = QWidget()
        whw.setLayout(wh)
        form.addRow("Resolution/fps", whw)

        self.cb_enc = QComboBox()
        for e in self._encoders:
            self.cb_enc.addItem(e.label, e.key)
        form.addRow("Encoder", self.cb_enc)

        self.sp_crf = QSpinBox()
        self.sp_crf.setRange(0, 51)
        self.sp_crf.setValue(18)
        self.sp_crf.valueChanged.connect(self._update_estimate)
        form.addRow("Quality (CRF, lower=better)", self.sp_crf)

        self.sp_scale = QDoubleSpinBox()
        self.sp_scale.setRange(1.0, 2.0)
        self.sp_scale.setSingleStep(0.5)
        self.sp_scale.setValue(2.0)
        form.addRow("Supersample", self.sp_scale)

        self.ed_audio = QLineEdit("192k")
        form.addRow("Audio bitrate", self.ed_audio)

        lay.addLayout(form)

        self.lbl_est = QLabel()
        self.lbl_est.setStyleSheet("color:#8a8a92;")
        lay.addWidget(self.lbl_est)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.lbl_prog = QLabel("")
        lay.addWidget(self.lbl_prog)
        self.thumb = QLabel()
        self.thumb.setFixedHeight(120)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.thumb)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        self.buttons.accepted.connect(self._start)
        self.buttons.rejected.connect(self._on_reject)
        lay.addWidget(self.buttons)

        self.cb_preset.setCurrentText("TikTok")
        self._apply_preset("TikTok")

    def _apply_preset(self, name: str) -> None:
        if name in PRESETS:
            p = PRESETS[name]
            self.sp_w.setValue(p.width)
            self.sp_h.setValue(p.height)
            self.sp_fps.setValue(p.fps)
            self.sp_crf.setValue(p.crf)
            self.ed_audio.setText(p.audio_bitrate)
        self._update_estimate()

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export to", self.ed_path.text(),
                                              "MP4 (*.mp4)")
        if path:
            self.ed_path.setText(path)

    def _update_estimate(self) -> None:
        dur = (self._out - self._in)
        frames = max(1, round(dur * self.sp_fps.value()))
        # crude bitrate model for libx264 at a given CRF
        mbps = max(2.0, 18.0 * (28 - self.sp_crf.value()) / 10.0)
        size_mb = mbps * dur / 8.0
        self.lbl_est.setText(
            f"~{frames} frames · ~{size_mb:.0f} MB · source range "
            f"{self._in:.2f}–{self._out:.2f}s")

    # --------------------------------------------------------------- export
    def _start(self) -> None:
        out = self.ed_path.text().strip()
        if not out:
            self.lbl_prog.setText("choose an output path")
            return
        if self.sp_w.value() % 2 or self.sp_h.value() % 2:
            self.lbl_prog.setText("width/height must be even for H.264")
            return

        req = ExportRequest(
            graph_dict=self._graph.to_dict(),
            source_path=self._source,
            out_path=out,
            width=self.sp_w.value(), height=self.sp_h.value(), fps=self.sp_fps.value(),
            in_point=self._in, out_point=self._out,
            render_scale=self.sp_scale.value(),
            encoder_key=self.cb_enc.currentData() or "x264",
            crf=self.sp_crf.value(),
            audio_bitrate=self.ed_audio.text().strip() or "192k",
            speed=self._speed,
        )
        self._job = ExportJob(req)
        self._job.progress.connect(self._on_progress)
        self._job.finished.connect(self._on_finished)
        self.bar.setVisible(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._job.start()

    def _on_progress(self, n, total, fps, thumb) -> None:
        self.bar.setMaximum(total)
        self.bar.setValue(n)
        self.lbl_prog.setText(f"{n}/{total}  ·  {fps:.1f} fps  ·  "
                              f"ETA {max(0, (total - n) / max(fps, 0.1)):.0f}s")
        if isinstance(thumb, np.ndarray):
            h, w = thumb.shape[:2]
            img = QImage(np.ascontiguousarray(thumb).data, w, h, 3 * w,
                         QImage.Format.Format_RGB888).copy()
            self.thumb.setPixmap(QPixmap.fromImage(img).scaledToHeight(
                120, Qt.TransformationMode.SmoothTransformation))

    def _on_finished(self, ok, message) -> None:
        if self._job:
            self._job.wait()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        if ok:
            self.lbl_prog.setText(f"done: {message}")
            self._offer_open(message)
        else:
            self.lbl_prog.setText(f"failed: {message}")

    def _offer_open(self, path: str) -> None:
        btn = QPushButton("Open folder")
        btn.clicked.connect(lambda: os.startfile(str(Path(path).parent))  # noqa: S606
                            if os.name == "nt" else None)
        self.layout().addWidget(btn)

    def _on_reject(self) -> None:
        if self._job:
            self._job.cancel()
            self.lbl_prog.setText("cancelling...")
        else:
            self.reject()
