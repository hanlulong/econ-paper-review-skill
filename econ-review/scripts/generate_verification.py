#!/usr/bin/env python3
"""Render the readable verification audit from verification.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import atomic_write_text, strict_json_load  # noqa: E402


def load(path: Path) -> dict[str, Any]:
    value = strict_json_load(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def cell(value: Any) -> str:
    return " ".join(str(value or "").split()).replace("|", "\\|") or "—"


def render(payload: dict[str, Any]) -> str:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("verification.json.records must be an array")
    lines = [
        "# Verification",
        "",
        "This audit is generated from the structured source-grounded verification ledger.",
        "",
        "| Finding | Finding status | Evidence | Check | Result | Anchor or source | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for record_index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"verification.json.records[{record_index}] must be an object")
        checks = record.get("checks")
        if not isinstance(checks, list) or not checks:
            raise ValueError(f"verification.json.records[{record_index}].checks must be non-empty")
        for check_index, check in enumerate(checks):
            if not isinstance(check, dict):
                raise ValueError(
                    f"verification.json.records[{record_index}].checks[{check_index}] must be an object"
                )
            reference = check.get("anchor_id") or check.get("computation_id") or check.get("source_record_id")
            lines.append(
                "| " + " | ".join([
                    cell(record.get("finding_id")), cell(record.get("status")), cell(check.get("evidence_id")),
                    cell(check.get("check_type")), cell(check.get("result")), cell(reference), cell(check.get("notes")),
                ]) + " |"
            )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        output = render(load(args.review_dir / "evidence" / "verification.json"))
        destination = args.review_dir / "evidence" / "verification.md"
        if args.check:
            if not destination.exists() or destination.read_text(encoding="utf-8") != output:
                raise ValueError(f"{destination} is not synchronized with verification.json")
        else:
            atomic_write_text(args.review_dir, "evidence/verification.md", output)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        parser.exit(1, f"verification generation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
