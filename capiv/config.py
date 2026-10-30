"""Paths and environment knobs. Everything lives under CAPIV_HOME (default ~/.capiv)."""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("CAPIV_HOME", Path.home() / ".capiv")).expanduser()


def raw_dir() -> Path:
    return home() / "raw"


def db_path() -> Path:
    return Path(os.environ.get("CAPIV_DB", home() / "capiv.duckdb")).expanduser()


def out_dir() -> Path:
    return Path(os.environ.get("CAPIV_OUT", Path.cwd() / "capiv_out")).expanduser()


MODEL = os.environ.get("CAPIV_MODEL", "claude-opus-5-5")
