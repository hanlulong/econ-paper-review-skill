#!/usr/bin/env python3
"""Start the current immutable Review Desk version from its stable launcher."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    pointer = root / "current.json"
    if pointer.is_symlink() or not pointer.is_file():
        raise ValueError("Review Desk current-version pointer is missing or unsafe; rerun the installer")
    value = json.loads(pointer.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"digest", "schema_version"}:
        raise ValueError("Review Desk current-version pointer is malformed; rerun the installer")
    digest = value.get("digest")
    if value.get("schema_version") != "1" or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Review Desk current-version pointer is invalid; rerun the installer")
    version = root / "versions" / digest
    launcher = version / "launch_review_desk.py"
    if version.is_symlink() or launcher.is_symlink() or not launcher.is_file():
        raise ValueError("the selected Review Desk version is missing or unsafe; rerun the installer")
    os.execv(sys.executable, [sys.executable, str(launcher), *sys.argv[1:]])
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Review Desk could not start: {exc}", file=sys.stderr)
        raise SystemExit(1)
