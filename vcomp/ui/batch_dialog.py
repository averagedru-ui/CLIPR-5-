"""Batch export: apply one template (or the current graph) to many clips and
render them sequentially.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from vcomp.core.graph import Graph
from vcomp.export.job import ExportJob, ExportRequest
from vcomp.media.probe import probe
from vcomp.templates.io import apply_template, load_template
from vcomp.util import paths


class BatchDialog(QDialog):
    def __init__(self, parent, base_graph: Graph):
        super().__init__(parent)
        self.setWindowTitle("Batch Export")
        self.resize(560, 420)
        self._base = base_graph
        self._jobs: list[ExportRequest] = []
        self._running = False
        self._idx = 0
        self._job: ExportJob | None = None

        lay = QVBoxLayout(self)
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

        self.cb_template = QComboBox()
        self.cb_template.addItem("Current graph (no template)", "")
        for p in sorted(paths.templates_dir().glob("*.vctpl")):
            self.cb_template.addItem(p.stem, str(p))
        lay.addWidget(QLabel("Template"))
        lay.addWidget(self.cb_template)

        self.out_dir = QLabel("output: <same folder as each clip>")
        pick = QPushButton("Choose output folder...")
        pick.clicked.connect(self._pick_out)
        lay.addWidget(self.out_dir)
        lay.addWidget(pick)
        self._outdir: str | None = None

        self.bar = QProgressBar()
        lay.addWidget(self.bar)
        self.lbl = QLabel("")
        lay.addWidget(self.lbl)

        self.btn = QPushButton("Start")
        self.btn.clicked.connect(self._toggle)
        lay.addWidget(self.btn)

    def _add_clips(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add clips", "",
                                                "Video (*.mp4 *.mov *.mkv *.webm)")
        for f in files:
            self.list.addItem(f)

    def _pick_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Output folder")
        if d:
            self._outdir = d
            self.out_dir.setText(f"output: {d}")

    # ------------------------------------------------------------- run
    def _toggle(self) -> None:
        if self._running:
            self._running = False
            if self._job:
                self._job.cancel()
            self.btn.setText("Start")
            return
        clips = [self.list.item(i).text() for i in range(self.list.count())]
        if not clips:
            self.lbl.setText("add some clips first")
            return
        tpl_path = self.cb_template.currentData()
        tpl = load_template(tpl_path) if tpl_path else None

        self._jobs = []
        for c in clips:
            try:
                info = probe(c)
            except Exception as exc:  # noqa: BLE001
                self.lbl.setText(f"skip {Path(c).name}: {exc}")
                continue
            g = Graph()
            g.load_dict(self._base.to_dict())
            for n in g.clip_source_nodes():
                n.params["file_path"].set(c)
                n.set_media_info(info.width, info.height, info.fps, info.duration)
            if tpl:
                apply_template(g, tpl, (info.width, info.height))
                for n in g.clip_source_nodes():
                    n.params["file_path"].set(c)
            out_dir = Path(self._outdir) if self._outdir else Path(c).parent
            self._jobs.append(ExportRequest(
                graph_dict=g.to_dict(), source_path=c,
                out_path=str(out_dir / (Path(c).stem + "_vertical.mp4")),
                width=1080, height=1920, fps=30,
                in_point=0.0, out_point=info.duration, render_scale=2.0,
            ))
        self._idx = 0
        self._running = True
        self.btn.setText("Stop")
        self.bar.setMaximum(len(self._jobs))
        self._next()

    def _next(self) -> None:
        if not self._running or self._idx >= len(self._jobs):
            self._running = False
            self.btn.setText("Start")
            self.lbl.setText("batch complete" if self._idx >= len(self._jobs) else "stopped")
            return
        req = self._jobs[self._idx]
        self.lbl.setText(f"[{self._idx + 1}/{len(self._jobs)}] {Path(req.source_path).name}")
        self._job = ExportJob(req)
        self._job.finished.connect(self._done)
        self._job.start()

    def _done(self, ok: bool, msg: str) -> None:
        if self._job:
            self._job.wait()
        self._idx += 1
        self.bar.setValue(self._idx)
        self._next()
