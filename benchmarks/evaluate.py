#!/usr/bin/env python3
"""Evaluate completed synthetic review packages without inventing an aggregate score."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = Path(__file__).with_name("cases.json")
REVIEWS = Path(__file__).with_name("reviews")
VALIDATOR = ROOT / "econ-review" / "scripts" / "validate_review.py"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in patterns)


def evaluate_case(case: dict) -> dict:
    review_dir = REVIEWS / case["id"]
    if not review_dir.is_dir():
        return {"id": case["id"], "status": "not_run"}

    try:
        run = load_json(review_dir / "run.json")
        findings = load_json(review_dir / "findings.json")["findings"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        return {"id": case["id"], "status": "invalid_input", "error": str(exc)}

    active = {
        burden["id"]
        for burden in run.get("activated_burdens", [])
        if burden.get("status") == "active"
    }
    not_applicable = {
        burden["id"]
        for burden in run.get("activated_burdens", [])
        if burden.get("status") == "not_applicable"
    }
    finding_text = "\n".join(
        " ".join(
            str(finding.get(field, ""))
            for field in ("title", "dimension", "issue", "why_it_matters", "reader_effect")
        )
        for finding in findings
        if finding.get("status") in {"open", "challenged"}
    )

    required = {
        concept["id"]: any_pattern(finding_text, concept["patterns"])
        for concept in case["required_issue_concepts"]
    }
    forbidden = {
        concept["id"]: any_pattern(finding_text, concept["patterns"])
        for concept in case["forbidden_issue_concepts"]
    }
    validation = subprocess.run(
        [sys.executable, str(VALIDATOR), str(review_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "id": case["id"],
        "status": "evaluated",
        "contract_valid": validation.returncode == 0,
        "missing_active_burdens": sorted(set(case["required_active_burdens"]) - active),
        "missing_not_applicable_burdens": sorted(set(case["required_not_applicable_burdens"]) - not_applicable),
        "required_issue_concepts": required,
        "forbidden_false_positives": forbidden,
    }


def main() -> int:
    cases = load_json(CASES_PATH)["cases"]
    results = [evaluate_case(case) for case in cases]
    print(json.dumps({"schema_version": "0.1", "results": results}, indent=2))
    failed = any(
        result.get("status") == "evaluated"
        and (
            not result["contract_valid"]
            or result["missing_active_burdens"]
            or result["missing_not_applicable_burdens"]
            or not all(result["required_issue_concepts"].values())
            or any(result["forbidden_false_positives"].values())
        )
        for result in results
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
