"""Rasterize text to an RGBA numpy array with QPainter.

Lives in ``render/`` (not ``nodes/``) so the ``nodes`` package stays Qt-free:
the Text node describes *what* to draw; this module knows *how*. Needs a
``QGuiApplication`` to exist (the app always has one; tests use offscreen).
"""
from __future__ import annotations

import numpy as np


def render_text(
    content: str, *, width: int, height: int,
    font_family: str = "Arial", font_size: int = 72, weight: int = 700,
    color=(1.0, 1.0, 1.0, 1.0), align: str = "center",
    letter_spacing: float = 0.0, line_height: float = 1.2,
    stroke_width: float = 0.0, stroke_color=(0.0, 0.0, 0.0, 1.0),
) -> np.ndarray:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen

    img = QImage(width, height, QImage.Format.Format_RGBA8888)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    font = QFont(font_family, int(font_size))
    font.setWeight(QFont.Weight(min(900, max(100, int(weight)))))
    if letter_spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, float(letter_spacing))
    p.setFont(font)

    flags = {
        "left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
        "right": Qt.AlignmentFlag.AlignRight,
    }.get(align, Qt.AlignmentFlag.AlignHCenter) | Qt.AlignmentFlag.AlignVCenter

    rect = img.rect()
    fill = QColor.fromRgbF(*color)
    if stroke_width > 0:
        path = QPainterPath()
        # approximate: draw text into a path via a temp font metrics baseline
        fm = p.fontMetrics()
        lines = content.split("\n")
        total_h = fm.height() * line_height * len(lines)
        y = (height - total_h) / 2 + fm.ascent()
        for line in lines:
            w = fm.horizontalAdvance(line)
            if align == "left":
                x = 0
            elif align == "right":
                x = width - w
            else:
                x = (width - w) / 2
            path.addText(x, y, font, line)
            y += fm.height() * line_height
        p.setPen(QPen(QColor.fromRgbF(*stroke_color), float(stroke_width)))
        p.setBrush(fill)
        p.drawPath(path)
    else:
        p.setPen(QColor.fromRgbF(*color))
        p.drawText(rect, int(flags), content)
    p.end()

    ptr = img.constBits()
    arr = np.frombuffer(ptr, np.uint8).reshape(height, width, 4).copy()
    return arr
