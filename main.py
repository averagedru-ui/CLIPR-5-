"""CLIPR entry point.

Usage:
    python main.py                 launch the GUI
    python main.py --version       print version and exit
    python main.py --render P O     headless render (implemented in M6)
"""
from __future__ import annotations

import sys

__version__ = "0.0.1"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--version" in argv:
        print(f"CLIPR {__version__}")
        return 0

    if "--render" in argv:
        i = argv.index("--render")
        rest = argv[i + 1:]
        if len(rest) < 2:
            print("usage: main.py --render <project.vcproj> <output.mp4>", file=sys.stderr)
            return 2
        return _render_cli(rest[0], rest[1])

    from vcomp.app import run

    return run()


def _render_cli(project_path: str, out_path: str) -> int:
    import logging
    import time

    from PySide6.QtWidgets import QApplication

    from vcomp.core.project import Project
    from vcomp.export.job import ExportJob, ExportRequest
    from vcomp.media.probe import probe
    from vcomp.nodes.registry import load_builtin_nodes
    from vcomp.util import logging as vlog

    vlog.setup_logging(logging.INFO)
    load_builtin_nodes()
    app = QApplication.instance() or QApplication([])

    proj = Project.load(project_path)
    clip = next(iter(proj.graph.clip_source_nodes()), None)
    if not clip or not clip.params["file_path"].value:
        print("project has no clip", file=sys.stderr)
        return 3
    src = clip.params["file_path"].value
    info = probe(src)
    fps = int(proj.graph.output_node().params["fps"].value) \
        if str(proj.graph.output_node().params["fps"].value).isdigit() else int(round(info.fps))
    cw, ch, rs = proj.graph.canvas_params()

    req = ExportRequest(
        graph_dict=proj.graph.to_dict(), source_path=src, out_path=out_path,
        width=cw, height=ch, fps=fps,
        in_point=proj.in_point / info.fps if info.fps else 0.0,
        out_point=(proj.out_point + 1) / info.fps if proj.out_point else info.duration,
        render_scale=rs, speed=float(clip.params["speed"].value),
    )
    result: dict = {}
    job = ExportJob(req)
    job.progress.connect(lambda n, tot, f, _t: print(f"\r{n}/{tot}  {f:.1f} fps", end=""))
    job.finished.connect(lambda ok, msg: result.update(ok=ok, msg=msg))
    job.start()
    while "ok" not in result:
        app.processEvents()
        time.sleep(0.02)
    job.wait()
    print()
    print(result["msg"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
