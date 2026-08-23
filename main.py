from __future__ import annotations

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    sys.path.insert(0, str(bundle))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.gui.main_window import run_app


if __name__ == "__main__":
    run_app()
