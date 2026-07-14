#!/usr/bin/env python3
"""Evaluate completed synthetic review packages without inventing an aggregate score."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "econ-review" / "scripts"))
from safe_io import strict_json_load  # noqa: E402

CASES_PATH = Path(__file__).with_name("cases.json")
REVIEWS = Path(__file__).with_name("reviews")
FINALIZER = ROOT / "econ-review" / "scripts" / "finalize_review.py"


def load_json(path: Path) -> dict:
    value = strict_json_load(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


DIAGNOSIS_FIELDS = (
    "title",
    "dimension",
    "issue",
    "why_it_matters",
    "reader_effect",
    "evidence_boundary",
)


def concept_matches(finding_payloads: list[tuple[str, str]], patterns: list[str]) -> list[dict]:
    """Return auditable per-finding matches; never join diagnoses across findings."""

    matches: list[dict] = []
    for finding_id, payload in finding_payloads:
        for pattern_index, pattern in enumerate(patterns):
            if re.search(pattern, payload, flags=re.IGNORECASE | re.DOTALL):
                matches.append({"finding_id": finding_id, "pattern_index": pattern_index})
                break
    return matches


def parent_states(burdens: list[dict]) -> tuple[set[str], set[str]]:
    """Aggregate stable parents; active wins and absence remains unassessed."""

    rows_by_parent: dict[str, list[str]] = {}
    for burden in burdens:
        if not isinstance(burden, dict) or not isinstance(burden.get("parent_id"), str):
            continue
        rows_by_parent.setdefault(burden["parent_id"], []).append(burden.get("status"))
    active = {
        parent_id for parent_id, states in rows_by_parent.items() if "active" in states
    }
    not_applicable = {
        parent_id
        for parent_id, states in rows_by_parent.items()
        if states and all(state == "not_applicable" for state in states)
    }
    return active, not_applicable


def evaluate_case(case: dict, *, reviews: Path = REVIEWS, finalizer: Path = FINALIZER) -> dict:
    review_dir = reviews / case["id"]
    if not review_dir.is_dir():
        return {
            "id": case["id"],
            "rubric_source": case.get("paper"),
            "status": "not_run",
        }

    try:
        run = load_json(review_dir / "run.json")
        findings = load_json(review_dir / "findings.json")["findings"]
        if not isinstance(findings, list) or not all(
            isinstance(finding, dict) for finding in findings
        ):
            raise ValueError("findings.json.findings must be an array of objects")
    except (OSError, KeyError, json.JSONDecodeError, ValueError) as exc:
        return {
            "id": case["id"],
            "rubric_source": case.get("paper"),
            "status": "invalid_input",
            "error": str(exc),
        }

    raw_burdens = run.get("activated_burdens", [])
    burdens = [
        burden for burden in raw_burdens if isinstance(burden, dict)
    ] if isinstance(raw_burdens, list) else []
    active = {
        burden["id"]
        for burden in burdens
        if burden.get("status") == "active"
    }
    not_applicable = {
        burden["id"]
        for burden in burdens
        if burden.get("status") == "not_applicable"
    }
    active_parents, not_applicable_parents = parent_states(burdens)
    finding_payloads = [
        (
            str(finding.get("id", "<unnamed>")),
            " ".join(
            str(finding.get(field, ""))
                for field in DIAGNOSIS_FIELDS
            ),
        )
        for finding in findings
        if (
            finding.get("status") in {"open", "challenged"}
            and finding.get("report_channel", "substance") == "substance"
        )
    ]

    required_matches = {
        concept["id"]: concept_matches(finding_payloads, concept["patterns"])
        for concept in case["required_issue_concepts"]
    }
    forbidden_matches = {
        concept["id"]: concept_matches(finding_payloads, concept["patterns"])
        for concept in case["forbidden_issue_concepts"]
    }
    required = {concept_id: bool(matches) for concept_id, matches in required_matches.items()}
    forbidden = {concept_id: bool(matches) for concept_id, matches in forbidden_matches.items()}
    finalization = subprocess.run(
        [sys.executable, str(finalizer), str(review_dir), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "id": case["id"],
        "rubric_source": case.get("paper"),
        "status": "evaluated",
        "completion_valid": run.get("status") == "complete",
        "contract_valid": run.get("status") == "complete" and finalization.returncode == 0,
        "missing_active_burdens": sorted(set(case.get("required_active_burdens", [])) - active),
        "missing_not_applicable_burdens": sorted(
            set(case.get("required_not_applicable_burdens", [])) - not_applicable
        ),
        "missing_active_parent_burdens": sorted(
            set(case.get("required_active_parent_burdens", [])) - active_parents
        ),
        "missing_not_applicable_parent_burdens": sorted(
            set(case.get("required_not_applicable_parent_burdens", []))
            - not_applicable_parents
        ),
        "forbidden_active_burdens": sorted(
            set(case.get("forbidden_active_burden_ids", [])) & active
        ),
        "required_issue_concepts": required,
        "required_issue_matches": required_matches,
        "forbidden_false_positives": forbidden,
        "forbidden_issue_matches": forbidden_matches,
    }


def result_failed(result: dict, *, require_all: bool) -> bool:
    status = result.get("status")
    if status == "not_run":
        return require_all
    if status != "evaluated":
        # A present but unreadable package is never a successful benchmark run.
        return True
    return bool(
        not result["contract_valid"]
        or result["missing_active_burdens"]
        or result["missing_not_applicable_burdens"]
        or result["missing_active_parent_burdens"]
        or result["missing_not_applicable_parent_burdens"]
        or result["forbidden_active_burdens"]
        or not all(result["required_issue_concepts"].values())
        or any(result["forbidden_false_positives"].values())
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate any completed packages for the synthetic review rubrics."
    )
    parser.add_argument(
        "--require-all",
        action="store_true",
        help=(
            "fail when any rubric case lacks benchmarks/reviews/<case-id>/; "
            "use this for end-to-end benchmark claims"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cases = load_json(CASES_PATH)["cases"]
    results = [evaluate_case(case, reviews=REVIEWS, finalizer=FINALIZER) for case in cases]
    missing = [result["id"] for result in results if result.get("status") == "not_run"]
    evaluated = [result["id"] for result in results if result.get("status") == "evaluated"]
    print(
        json.dumps(
            {
                "schema_version": "0.3",
                "mode": "require_all" if args.require_all else "available_only",
                "rubric_case_count": len(cases),
                "executed_package_count": len(evaluated),
                "missing_review_packages": missing,
                "results": results,
            },
            indent=2,
        )
    )
    failed = any(result_failed(result, require_all=args.require_all) for result in results)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
