#!/usr/bin/env python3
"""Upgrade a v0.2 review ledger to the v0.3 referee-synthesis contract.

The migration is intentionally paper-agnostic. It preserves findings and prose,
adds decision metadata from existing verified state, and re-ranks by severity
and decision role. A human reviewer must still create and verify synthesis.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import atomic_write_bytes, atomic_write_json, safe_read_bytes, strict_json_load  # noqa: E402


ROLE_ORDER = {
    "potentially_dispositive": 0,
    "posture_material": 1,
    "revision_value": 2,
    "polish": 3,
}

SEVERITY_ORDER = {
    "critical": 0,
    "major": 1,
    "minor": 2,
    "info": 3,
}


def load(path: Path) -> dict[str, Any]:
    value = strict_json_load(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def titles_from_report(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^### \d+\. (?P<title>.+?)\s*\n<!-- finding_id: (?P<id>[A-Z][A-Z0-9_-]*-[0-9]{2,}) -->",
        re.MULTILINE,
    )
    titles: dict[str, str] = {}
    for match in pattern.finditer(text):
        title = match.group("title").strip()
        if ": " in title:
            title = title.rsplit(": ", 1)[-1]
        titles[match.group("id")] = title
    return titles


def decision_role(row: dict[str, Any]) -> str:
    if row.get("essential") is True or row.get("severity") == "critical":
        return "potentially_dispositive"
    if row.get("report_channel", "substance") == "writing":
        return "polish"
    if row.get("severity") in {"critical", "major"}:
        return "posture_material"
    return "revision_value"


def repairability(row: dict[str, Any]) -> str:
    fix = row.get("fix", {}) if isinstance(row.get("fix"), dict) else {}
    strategy = fix.get("strategy")
    if strategy == "narrow_claim":
        return "claim_narrowing"
    if strategy == "redesign":
        return "redesign"
    if fix.get("requires_new_data") is True or fix.get("effort") == "new-data":
        return "new_evidence"
    if strategy == "add_analysis":
        return "additional_analysis"
    if fix.get("current_design_can_support_primary_fix") is True:
        return "within_current_design"
    return "unclear"


def rerank(rows: list[Any]) -> None:
    active: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"findings.json.findings[{index}] must be an object")
        finding_id = row.get("id") if isinstance(row.get("id"), str) and row.get("id") else f"index {index}"
        role = row.get("decision_role")
        if role not in ROLE_ORDER:
            raise ValueError(
                f"finding {finding_id} has missing or invalid decision_role {role!r}; "
                "--rerank-only requires explicit v0.3 decision metadata"
            )
        if row.get("status") in {"dismissed", "resolved"} or row.get("severity") not in {
            "critical", "major", "minor"
        }:
            continue
        rank = row.get("importance_rank")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
            raise ValueError(f"finding {finding_id} has invalid importance_rank {rank!r}")
        active.append(row)
    active.sort(key=lambda row: (
        SEVERITY_ORDER.get(str(row.get("severity")), 99),
        ROLE_ORDER[row["decision_role"]],
        row.get("importance_rank", 10**9),
        str(row.get("id") or ""),
    ))
    for rank, row in enumerate(active, start=1):
        row["importance_rank"] = rank


def write_migration(review_dir: Path, run: dict[str, Any], ledger: dict[str, Any]) -> None:
    """Commit the two-file version transition with best-effort rollback."""
    previous = {
        "run.json": safe_read_bytes(review_dir, "run.json"),
        "findings.json": safe_read_bytes(review_dir, "findings.json"),
    }
    try:
        atomic_write_json(review_dir, "run.json", run)
        atomic_write_json(review_dir, "findings.json", ledger)
    except Exception as exc:
        try:
            for relative, content in previous.items():
                atomic_write_bytes(review_dir, relative, content)
        except Exception as rollback_exc:
            raise ValueError(f"migration failed: {exc}; rollback failed: {rollback_exc}") from rollback_exc
        raise


def migrate(review_dir: Path, rerank_only: bool = False) -> None:
    run_path = review_dir / "run.json"
    ledger_path = review_dir / "findings.json"
    run = load(run_path)
    ledger = load(ledger_path)
    if rerank_only:
        version = run.get("schema_version")
        if version not in {"0.3", "0.4"} or ledger.get("schema_version") != version:
            raise ValueError("--rerank-only requires matching v0.3+ run and findings files")
        rows = ledger.get("findings")
        if not isinstance(rows, list):
            raise ValueError("findings.json must contain a findings array")
        rerank(rows)
        atomic_write_json(review_dir, "findings.json", ledger)
        return
    if run.get("schema_version") != "0.2" or ledger.get("schema_version") != "0.2":
        raise ValueError("upgrade_review_v03.py accepts only matching v0.2 run and findings files")

    titles = {}
    titles.update(titles_from_report(review_dir / "report.md"))
    titles.update(titles_from_report(review_dir / "editing-comments.md"))
    rows = ledger.get("findings")
    if not isinstance(rows, list):
        raise ValueError("findings.json must contain a findings array")
    for row in rows:
        if not isinstance(row, dict):
            continue
        finding_id = str(row.get("id", ""))
        row["title"] = titles.get(finding_id) or str(row.get("issue", ""))
        row["decision_role"] = decision_role(row)
        row["repairability"] = repairability(row)
        row["essential"] = row["decision_role"] == "potentially_dispositive"

    rerank(rows)

    run["schema_version"] = "0.3"
    ledger["schema_version"] = "0.3"
    write_migration(review_dir, run, ledger)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument(
        "--rerank-only",
        action="store_true",
        help="Re-rank an already migrated v0.3 ledger without inferring missing decision metadata",
    )
    args = parser.parse_args()
    try:
        migrate(args.review_dir, rerank_only=args.rerank_only)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, IndexError, ValueError) as exc:
        parser.exit(1, f"v0.3 migration failed: {exc}\n")
    return 0


if __name__ == "__main__":
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
