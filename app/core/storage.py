from __future__ import annotations

import json
from pathlib import Path

from app.core.models import TestSuite


def app_data_dir() -> Path:
    base = Path.home() / "AppData" / "Roaming" / "JAQA"
    base.mkdir(parents=True, exist_ok=True)
    return base


def session_path() -> Path:
    return app_data_dir() / "session.json"


def reports_dir() -> Path:
    path = app_data_dir() / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def screenshots_dir() -> Path:
    path = app_data_dir() / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_json(suite: TestSuite, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = suite.to_dict()
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def import_json(path: str | Path) -> TestSuite:
    target = Path(path)
    raw = json.loads(target.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return TestSuite.from_dict({"test_cases": raw})
    return TestSuite.from_dict(raw)


def save_session(suite: TestSuite) -> None:
    export_json(suite, session_path())


def load_session() -> TestSuite | None:
    path = session_path()
    if not path.exists():
        return None
    try:
        return import_json(path)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
