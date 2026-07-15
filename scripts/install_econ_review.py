#!/usr/bin/env python3
"""Source-checkout entry point for the canonical econ-review setup tool."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


CANONICAL_INSTALLER = (
    Path(__file__).resolve().parents[1]
    / "econ-review"
    / "scripts"
    / "setup_econ_review.py"
)


if __name__ == "__main__":
    sys.path.insert(0, str(CANONICAL_INSTALLER.parent))
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    runpy.run_path(str(CANONICAL_INSTALLER), run_name="__main__")
