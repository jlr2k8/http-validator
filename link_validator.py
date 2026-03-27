#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys

# Allow running from repo root without installation.
ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from http_validator.cli import run


if __name__ == "__main__":
    raise SystemExit(run())
