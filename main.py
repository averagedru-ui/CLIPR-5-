"""VCOMP entry point.

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
        print(f"VCOMP {__version__}")
        return 0

    if "--render" in argv:
        print("Headless render is not implemented until milestone M6.", file=sys.stderr)
        return 2

    from vcomp.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
