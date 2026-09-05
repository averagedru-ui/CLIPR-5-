"""Template browser + Save-as-Template dialog."""
from __future__ import annotations

import base64
import os
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vcomp.templates.io import (
    Template, TemplateMeta, load_template, save_template, template_from_graph,
)
from vcomp.util import paths


def _thumb_b64(arr: np.ndarray | None) -> str:
    if arr is None:
        return ""
    a = np.ascontiguousarray(arr[..., :3])
    h, w = a.shape[:2]
    img = QImage(a.data, w, h, 3 * w, QImage.Format.Format_RGB888).scaledToWidth(
        240, Qt.TransformationMode.SmoothTransformation)
    from PySide6.QtCore import QBuffer, QByteArray

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return base64.b64encode(bytes(ba)).decode("ascii")


_NEW_TEMPLATE = "New template..."


class SaveTemplateDialog(QDialog):
    """Save the current graph as a template - either a new file, or picked
    from the 'Overwrite' dropdown to save back over an existing one."""

    def __init__(self, parent, graph, reference_resolution, thumb: np.ndarray | None):
        super().__init__(parent)
        self.setWindowTitle("Save as Template")
        self._graph = graph
        self._ref = reference_resolution
        self._thumb = thumb
        self.saved_path: Path | None = None
        self._existing: dict[str, Path] = {
            p.stem: p for p in sorted(paths.templates_dir().glob("*.vctpl"))
        }

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Overwrite"))
        self.cb_target = QComboBox()
        self.cb_target.addItem(_NEW_TEMPLATE)
        self.cb_target.addItems(list(self._existing))
        self.cb_target.currentTextChanged.connect(self._on_target_changed)
        lay.addWidget(self.cb_target)

        self.ed_name = QLineEdit("My Template")
        self.ed_game = QLineEdit()
        self.ed_tags = QLineEdit()
        self.ed_notes = QPlainTextEdit()
        for label, w in [("Name", self.ed_name), ("Game", self.ed_game),
                         ("Tags (comma)", self.ed_tags), ("Notes", self.ed_notes)]:
            lay.addWidget(QLabel(label))
            lay.addWidget(w)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _on_target_changed(self, name: str) -> None:
        if name == _NEW_TEMPLATE:
            return
        path = self._existing.get(name)
        if not path:
            return
        try:
            tpl = load_template(path)
        except (ValueError, OSError):
            return
        self.ed_name.setText(tpl.meta.name)
        self.ed_game.setText(tpl.meta.game)
        self.ed_tags.setText(", ".join(tpl.meta.tags))
        self.ed_notes.setPlainText(tpl.meta.notes)

    def _save(self) -> None:
        meta = TemplateMeta(
            name=self.ed_name.text().strip() or "Untitled",
            game=self.ed_game.text().strip(),
            tags=[t.strip() for t in self.ed_tags.text().split(",") if t.strip()],
            notes=self.ed_notes.toPlainText().strip(),
            thumbnail_b64=_thumb_b64(self._thumb),
        )
        tpl = template_from_graph(self._graph, meta, self._ref)

        target = self.cb_target.currentText()
        if target != _NEW_TEMPLATE and target in self._existing:
            # explicit overwrite of the picked template's own file
            self.saved_path = save_template(tpl, self._existing[target])
            self.accept()
            return

        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in meta.name)
        dest = paths.templates_dir() / f"{safe}.vctpl"
        if dest.exists() and QMessageBox.question(
                self, "Save as Template",
                f"'{safe}.vctpl' already exists. Overwrite it?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.saved_path = save_template(tpl, dest)
        self.accept()


class TemplateBrowser(QDialog):
    def __init__(self, parent, on_apply):
        super().__init__(parent)
        self.setWindowTitle("Template Browser")
        self.resize(720, 480)
        self._on_apply = on_apply
        self._templates: list[Template] = []

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("search name / game / tag")
        self.search.textChanged.connect(self._refill)
        left.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show_detail)
        left.addWidget(self.list)
        imp = QPushButton("Import .vctpl")
        imp.clicked.connect(self._import)
        left.addWidget(imp)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        self.thumb = QLabel()
        self.thumb.setFixedSize(260, 320)
        self.thumb.setStyleSheet("background:#111; border:1px solid #333;")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(self.thumb)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        right.addWidget(self.detail)
        right.addStretch(1)
        for name, fn in [("Apply", self._apply), ("Duplicate", self._duplicate),
                         ("Rename", self._rename), ("Delete", self._delete),
                         ("Reveal in Explorer", self._reveal), ("Export", self._export)]:
            b = QPushButton(name)
            b.clicked.connect(fn)
            right.addWidget(b)
        root.addLayout(right, 0)

        self._reload()

    # ------------------------------------------------------------- data
    def _reload(self) -> None:
        from vcomp.templates.builtin import install_builtins

        install_builtins(paths.templates_dir())
        self._templates = []
        for p in sorted(paths.templates_dir().glob("*.vctpl")):
            try:
                self._templates.append(load_template(p))
            except (ValueError, OSError):
                pass
        self._refill()

    def _refill(self) -> None:
        q = self.search.text().lower()
        self.list.clear()
        self._filtered = []
        for t in self._templates:
            hay = f"{t.meta.name} {t.meta.game} {' '.join(t.meta.tags)}".lower()
            if q in hay:
                self._filtered.append(t)
                QListWidgetItem(f"{t.meta.name}"
                                + (f"  ·  {t.meta.game}" if t.meta.game else ""), self.list)

    def _current(self) -> Template | None:
        i = self.list.currentRow()
        return self._filtered[i] if 0 <= i < len(self._filtered) else None

    def _show_detail(self, _i) -> None:
        t = self._current()
        if not t:
            self.thumb.clear()
            self.detail.clear()
            return
        n_regions = sum(1 for n in t.graph["nodes"] if n["type"] == "HUD Region")
        self.detail.setText(
            f"<b>{t.meta.name}</b><br>{t.meta.game}<br>"
            f"reference {t.reference_resolution[0]}x{t.reference_resolution[1]}<br>"
            f"{n_regions} HUD regions<br><br>{t.meta.notes}")
        if t.meta.thumbnail_b64:
            pm = QPixmap()
            pm.loadFromData(base64.b64decode(t.meta.thumbnail_b64))
            self.thumb.setPixmap(pm.scaled(self.thumb.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        else:
            self.thumb.setText("no thumbnail")

    # ---------------------------------------------------------- actions
    def _apply(self) -> None:
        t = self._current()
        if t:
            self._on_apply(t)
            self.accept()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import template", "", "Template (*.vctpl)")
        if path:
            try:
                tpl = load_template(path)
                safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in tpl.meta.name)
                save_template(tpl, paths.templates_dir() / f"{safe}.vctpl")
                self._reload()
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, "Import", str(exc))

    def _export(self) -> None:
        t = self._current()
        if not t or not t.path:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export template",
                                              str(t.path.name), "Template (*.vctpl)")
        if path:
            save_template(t, path)

    def _duplicate(self) -> None:
        t = self._current()
        if t and t.path:
            t.meta.name += " copy"
            save_template(t, t.path.with_name(t.path.stem + "_copy.vctpl"))
            self._reload()

    def _rename(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        t = self._current()
        if not t or not t.path:
            return
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=t.meta.name)
        if ok and name:
            t.meta.name = name
            save_template(t, t.path)
            self._reload()

    def _delete(self) -> None:
        t = self._current()
        if t and t.path and QMessageBox.question(
                self, "Delete", f"Delete '{t.meta.name}'?") == QMessageBox.StandardButton.Yes:
            t.path.unlink(missing_ok=True)
            self._reload()

    def _reveal(self) -> None:
        t = self._current()
        if t and t.path and os.name == "nt":
            os.startfile(str(t.path.parent))  # noqa: S606
