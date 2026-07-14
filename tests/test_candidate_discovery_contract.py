#!/usr/bin/env python3
"""Focused semantic tests for discovery candidates and saturation closure."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "validate_review.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
SPEC = importlib.util.spec_from_file_location("validate_candidate_contract", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def refresh_finalization_receipt(target: Path) -> None:
    """Re-sign a copied fixture after an intentional semantic mutation."""
    coverage_path = target / "evidence" / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    (target / "evidence" / "coverage.md").write_text(
        MODULE.render_coverage(coverage), encoding="utf-8"
    )

    receipt_path = target / "finalization.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["artifacts"] = {
        item.relative_to(target).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(target.rglob("*"))
        if item.is_file()
        and item.name != ".DS_Store"
        and item.relative_to(target).as_posix()
        not in {"finalization.json", "review-actions.json"}
    }
    write_json(receipt_path, receipt)


def install_candidate_contract(target: Path) -> None:
    """Upgrade a copied canonical fixture to the discovery-ledger contract."""
    run = json.loads((target / "run.json").read_text(encoding="utf-8"))
    coverage_path = target / "evidence" / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    findings_path = target / "findings.json"
    findings = json.loads(findings_path.read_text(encoding="utf-8"))

    unit_ids = [
        row["id"] for row in coverage["units"]
        if row.get("status") != "not_applicable"
    ]
    burden_ids = [
        row["id"] for row in run["activated_burdens"]
        if row.get("status") == "active"
    ]
    passes = [
        {
            "id": "PASS-01",
            "kind": "source_order",
            "role": "source-order discovery",
            "scope": "Read every in-scope coverage unit in source order.",
            "coverage_unit_ids": unit_ids,
            "burden_ids": burden_ids,
            "status": "completed",
            "boundary": None,
        },
        {
            "id": "PASS-02",
            "kind": "cross_unit",
            "role": "cross-unit discovery",
            "scope": "Reconcile claims, methods, evidence, and writing across units.",
            "coverage_unit_ids": unit_ids,
            "burden_ids": burden_ids,
            "status": "completed",
            "boundary": None,
        },
        {
            "id": "PASS-03",
            "kind": "low_count_recovery",
            "role": "low-count recovery",
            "scope": "Recheck minor correctness and cross-section consistency.",
            "coverage_unit_ids": unit_ids,
            "burden_ids": burden_ids,
            "status": "completed",
            "boundary": None,
        },
        {
            "id": "PASS-04",
            "kind": "saturation",
            "role": "saturation sweep",
            "scope": "Repeat the full audit after dispositioning prior candidates.",
            "coverage_unit_ids": unit_ids,
            "burden_ids": burden_ids,
            "status": "completed",
            "boundary": None,
        },
    ]
    candidates = []
    for index, finding in enumerate(findings["findings"], start=1):
        candidate_id = f"CND-{index:03d}"
        finding["candidate_ids"] = [candidate_id]
        candidates.append({
            "id": candidate_id,
            "pass_id": "PASS-01" if index == 1 else "PASS-02",
            "coverage_unit_ids": unit_ids,
            "burden_ids": [],
            "locator": (
                f"{finding['evidence'][0]['source']}:"
                f"{finding['evidence'][0]['locator'].get('section', 'unknown')}"
            ),
            "provisional_issue": finding["title"],
            "consequence": finding["why_it_matters"],
            "proposed_repair": finding["minimum_repair"],
            "strongest_author_reply": finding["counterargument"]["author_reply"],
            "disposition": "admitted",
            "disposition_reason": "Independent verification retained this issue.",
            "finding_id": finding["id"],
            "merged_into_candidate_id": None,
        })

    write_json(findings_path, findings)
    write_json(target / "evidence" / "candidates.json", {
        "schema_version": "0.1",
        "review_id": run["review_id"],
        "passes": passes,
        "candidates": candidates,
    })
    coverage["second_sweep"].update({
        "bounded_candidate_count": 0,
        "merged_candidate_count": 0,
        "saturation_reached": True,
        "rounds": [{
            "id": "SWEEP-01",
            "pass_id": "PASS-04",
            "scope": "All in-scope units and activated burdens.",
            "coverage_unit_ids": unit_ids,
            "new_finding_ids": [],
        }],
    })
    write_json(coverage_path, coverage)
    refresh_finalization_receipt(target)


class CandidateDiscoveryContractTests(unittest.TestCase):
    def copy_review(self, directory: str) -> Path:
        target = Path(directory) / "review"
        shutil.copytree(FIXTURE, target)
        install_candidate_contract(target)
        return target

    def test_complete_candidate_contract_validates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_review(tmp)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_final_saturation_round_must_yield_zero_new_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_review(tmp)
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            finding_id = json.loads(
                (target / "findings.json").read_text(encoding="utf-8")
            )["findings"][0]["id"]
            coverage["second_sweep"]["new_finding_ids"] = [finding_id]
            coverage["second_sweep"]["rounds"][-1]["new_finding_ids"] = [finding_id]
            write_json(coverage_path, coverage)
            candidates_path = target / "evidence" / "candidates.json"
            candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
            candidates["candidates"][0]["pass_id"] = "PASS-03"
            write_json(candidates_path, candidates)
            refresh_finalization_receipt(target)

            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("final saturation round" in error and "zero" in error for error in errors),
                errors,
            )

    def test_finding_cannot_reference_unknown_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_review(tmp)
            findings_path = target / "findings.json"
            findings = json.loads(findings_path.read_text(encoding="utf-8"))
            findings["findings"][0]["candidate_ids"] = ["CND-999"]
            write_json(findings_path, findings)
            refresh_finalization_receipt(target)

            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("CND-999" in error and "candidate" in error for error in errors),
                errors,
            )

    def test_admitted_candidate_must_be_listed_by_its_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_review(tmp)
            findings_path = target / "findings.json"
            findings = json.loads(findings_path.read_text(encoding="utf-8"))
            findings["findings"][0].pop("candidate_ids")
            write_json(findings_path, findings)
            refresh_finalization_receipt(target)

            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("LOGIC-01" in error and "candidate_id" in error for error in errors),
                errors,
            )

    def test_candidate_must_reference_a_declared_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_review(tmp)
            candidates_path = target / "evidence" / "candidates.json"
            candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
            candidates["candidates"][0]["pass_id"] = "PASS-99"
            write_json(candidates_path, candidates)
            refresh_finalization_receipt(target)

            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("PASS-99" in error and "pass" in error for error in errors),
                errors,
            )

    def test_pass_must_reference_known_coverage_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_review(tmp)
            candidates_path = target / "evidence" / "candidates.json"
            candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
            candidates["passes"][0]["coverage_unit_ids"] = ["missing-unit"]
            write_json(candidates_path, candidates)
            refresh_finalization_receipt(target)

            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("missing-unit" in error and "coverage unit" in error for error in errors),
                errors,
            )

    def test_low_substantive_count_requires_recovery_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_review(tmp)
            candidates_path = target / "evidence" / "candidates.json"
            candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
            candidates["passes"] = [
                row for row in candidates["passes"]
                if row["kind"] != "low_count_recovery"
            ]
            write_json(candidates_path, candidates)
            refresh_finalization_receipt(target)

            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("low-count recovery pass" in error for error in errors),
                errors,
            )


if __name__ == "__main__":
    unittest.main()
