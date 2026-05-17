from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    return app_root() / "config"


def data_dir() -> Path:
    path = app_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return config_dir() / "settings.json"


def prompts_dir() -> Path:
    return config_dir() / "prompts"


def db_path() -> Path:
    return data_dir() / "flowarchitect.db"


def log_path() -> Path:
    return data_dir() / "flowarchitect.log"
