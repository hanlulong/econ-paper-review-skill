#!/usr/bin/env python3
"""Adversarial regressions for coverage v0.2 and source-boundary joins."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
VALIDATOR = ROOT / "econ-review" / "scripts" / "validate_review.py"
FINALIZER = ROOT / "econ-review" / "scripts" / "finalize_review.py"
SPEC = importlib.util.spec_from_file_location("validate_review_coverage_tests", VALIDATOR)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def resign(target: Path, *, receipt_version: str | None = None) -> None:
    path = target / "finalization.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt_version is not None:
        receipt["schema_version"] = receipt_version
    if receipt.get("schema_version") != "0.3":
        receipt["gates"] = [gate for gate in receipt["gates"] if gate != "burden_coverage_v02"]
    receipt["artifacts"] = {
        item.relative_to(target).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(target.rglob("*"))
        if item.is_file()
        and item.name not in {"finalization.json", "review-actions.json", ".DS_Store"}
    }
    write_json(path, receipt)


def resign_quick(target: Path) -> None:
    resign(target, receipt_version="0.2")
    path = target / "finalization.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["gates"] = [
        gate
        for gate in receipt["gates"]
        if gate not in {"structured_audit_v02", "burden_coverage_v02"}
    ]
    write_json(path, receipt)


def convert_to_quick_without_coverage(target: Path) -> None:
    run_path = target / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["mode"] = "quick"
    run["requested_mode"] = "quick"
    run["delivered_mode"] = "quick"
    run["mode_transition"] = "none"
    run["transition_reason"] = None
    run["transition_source_review_id"] = None
    write_json(run_path, run)
    for relative in ("evidence/coverage.json", "evidence/coverage.md"):
        (target / relative).unlink()
    manifest_path = target / "review-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["documents"] = [
        row
        for row in manifest["documents"]
        if row.get("path") != "evidence/coverage.md"
    ]
    write_json(manifest_path, manifest)
    resign_quick(target)


def sync_candidate_discovery_scope(target: Path) -> None:
    """Keep fixture-only discovery passes closed after adding units or burdens."""

    run = json.loads((target / "run.json").read_text(encoding="utf-8"))
    coverage_path = target / "evidence" / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    candidates_path = target / "evidence" / "candidates.json"
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))

    unit_ids = [
        row["id"]
        for row in coverage["units"]
        if row.get("status") != "not_applicable"
    ]
    burden_ids = [
        row["id"]
        for row in run["activated_burdens"]
        if row.get("status") == "active"
    ]
    for discovery_pass in candidates["passes"]:
        if discovery_pass.get("status") == "completed":
            discovery_pass["coverage_unit_ids"] = unit_ids
            discovery_pass["burden_ids"] = burden_ids

    final_round = coverage["second_sweep"]["rounds"][-1]
    final_round["coverage_unit_ids"] = unit_ids
    write_json(candidates_path, candidates)
    write_json(coverage_path, coverage)


def add_replication_package(target: Path, state: str) -> None:
    """Add one internally supplied code source and close every current join."""

    code = "def estimate(value):\n    return value + 1\n"
    code_path = target / "replication.py"
    code_path.write_text(code, encoding="utf-8")
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()

    manifest_path = target / "evidence" / "source-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"].append({
        "id": "SRC-02",
        "role": "code",
        "path": "replication.py",
        "media_type": "text/x-python",
        "sha256": digest,
        "extraction": None,
    })
    next_anchor = 4
    if state in {"static_only", "executed"}:
        manifest["anchors"].append({
            "id": f"ANC-{next_anchor:02d}",
            "source_id": "SRC-02",
            "kind": "code_range",
            "start_char": 0,
            "end_char": len(code),
            "content_sha256": digest,
            "locator": "replication.py lines 1-2",
        })
        next_anchor += 1
    scope_anchor = f"ANC-{next_anchor:02d}"
    manifest["anchors"].append({
        "id": scope_anchor,
        "source_id": "SRC-02",
        "kind": "scope",
        "start_char": 0,
        "end_char": len(code),
        "content_sha256": digest,
        "locator": "Complete supplied code source",
    })
    write_json(manifest_path, manifest)

    run_path = target / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["capabilities"]["replication_code"] = state
    run["assessment_boundary"]["sources"].append({
        "source_id": "SRC-02",
        "path": "replication.py",
        "status": "not_opened" if state == "not_permitted" else "fully_read",
        "notes": (
            "Static and execution review were not authorized."
            if state == "not_permitted"
            else "Supplied code was inspected against the documented entry point."
        ),
        "sha256": digest,
    })
    run["activated_burdens"].append({
        "id": "replication_traceability",
        "parent_id": "reproducibility",
        "object_type": "reproducibility",
        "status": "active",
        "activation_basis": "observed",
        "triggers": [{
            "kind": "anchor",
            "ref": scope_anchor if state == "not_permitted" else "ANC-04",
            "rationale": "Supplied replication code activates a bounded or completed traceability audit.",
        }],
        "nonactivation_reason": None,
    })
    write_json(run_path, run)

    coverage_path = target / "evidence" / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["units"].append({
        "id": "replication-scope",
        "source_id": "SRC-02",
        "anchor_ids": [scope_anchor],
        "type": "other",
        "label": "Complete supplied replication source",
        "status": "bounded" if state == "not_permitted" else "checked_no_issue",
        "finding_ids": [],
        "notes": (
            "Inspection was outside the authorized boundary."
            if state == "not_permitted"
            else "The complete supplied source was inventoried."
        ),
    })
    replication_unit_ids = ["replication-scope"]
    if state in {"static_only", "executed"}:
        coverage["units"].append({
            "id": "replication-code",
            "source_id": "SRC-02",
            "anchor_ids": ["ANC-04"],
            "type": "code",
            "label": "replication.py implementation",
            "status": "checked_no_issue",
            "finding_ids": [],
            "notes": "The supplied implementation was inspected as code.",
        })
        replication_unit_ids.append("replication-code")
    coverage["burden_audits"].append({
        "burden_id": "replication_traceability",
        "parent_id": "reproducibility",
        "status": "bounded" if state == "not_permitted" else "checked_no_issue",
        "coverage_unit_ids": replication_unit_ids,
        "finding_ids": [],
        "notes": (
            "The supplied package was recorded, but inspection was not authorized."
            if state == "not_permitted"
            else "The code source and implementation range were inspected."
        ),
    })
    write_json(coverage_path, coverage)

    for relative, owner in (
        ("evidence/claims.json", "audit_scope"),
        ("evidence/analytical-audit.json", "scope"),
    ):
        path = target / relative
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload[owner]["coverage_unit_ids"].extend(replication_unit_ids)
        write_json(path, payload)

    sync_candidate_discovery_scope(target)
    result = subprocess.run(
        [sys.executable, str(FINALIZER), str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)


class CoverageContractTests(unittest.TestCase):
    def copy_fixture(self, temporary: str) -> Path:
        target = Path(temporary) / "review"
        shutil.copytree(FIXTURE, target)
        return target

    def mutate_coverage(
        self, target: Path, mutation: Callable[[dict], None], *, resign_package: bool = True,
    ) -> list[str]:
        path = target / "evidence" / "coverage.json"
        coverage = json.loads(path.read_text(encoding="utf-8"))
        mutation(coverage)
        write_json(path, coverage)
        if resign_package:
            resign(target)
        return MODULE.validate_review(target)

    def test_current_fixture_passes_exact_burden_and_provenance_contract(self) -> None:
        self.assertEqual(MODULE.validate_review(FIXTURE), [])

    def test_each_supplied_replication_state_has_a_valid_closed_package(self) -> None:
        for state in ("not_permitted", "static_only", "executed"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                target = self.copy_fixture(tmp)
                add_replication_package(target, state)
                self.assertEqual(MODULE.validate_review(target), [])

    def test_supplied_code_states_require_a_manifest_code_source(self) -> None:
        for state in ("not_permitted", "static_only", "executed"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                target = self.copy_fixture(tmp)
                run_path = target / "run.json"
                run = json.loads(run_path.read_text(encoding="utf-8"))
                run["capabilities"]["replication_code"] = state
                write_json(run_path, run)
                resign(target)
                errors = MODULE.validate_review(target)
                self.assertTrue(any(
                    f"replication_code={state} requires at least one code source in the source manifest"
                    in error for error in errors
                ), errors)

    def test_not_supplied_state_cannot_coexist_with_code_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            add_replication_package(target, "static_only")
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["capabilities"]["replication_code"] = "not_supplied"
            write_json(run_path, run)
            resign(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "replication_code=not_supplied conflicts with supplied code sources: SRC-02"
                in error for error in errors
            ), errors)

    def test_quick_run_requires_activation_but_not_full_coverage_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            add_replication_package(target, "static_only")
            convert_to_quick_without_coverage(target)
            self.assertEqual(MODULE.validate_review(target), [])

            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["activated_burdens"] = [
                row
                for row in run["activated_burdens"]
                if row.get("id") != "replication_traceability"
            ]
            write_json(run_path, run)
            resign_quick(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "supplied replication material requires an active reproducibility or computational-validity burden"
                in error for error in errors
            ), errors)

    def test_quick_run_requires_replication_source_in_assessment_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            add_replication_package(target, "static_only")
            convert_to_quick_without_coverage(target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["assessment_boundary"]["sources"] = [
                row
                for row in run["assessment_boundary"]["sources"]
                if row.get("source_id") != "SRC-02"
            ]
            write_json(run_path, run)
            resign_quick(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "assessment boundary omits supplied replication sources: SRC-02"
                in error for error in errors
            ), errors)

    def test_supplied_code_requires_assessment_boundary_membership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            add_replication_package(target, "static_only")
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["assessment_boundary"]["sources"] = [
                row
                for row in run["assessment_boundary"]["sources"]
                if row.get("source_id") != "SRC-02"
            ]
            write_json(run_path, run)
            resign(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "assessment boundary omits in-scope manifest sources: SRC-02" in error
                for error in errors
            ), errors)

    def test_data_dictionary_is_an_internal_source_for_boundary_and_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            dictionary = "variable,definition\ny,outcome\n"
            (target / "data-dictionary.csv").write_text(dictionary, encoding="utf-8")
            digest = hashlib.sha256(dictionary.encode("utf-8")).hexdigest()
            manifest_path = target / "evidence" / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["sources"].append({
                "id": "SRC-02",
                "role": "data_dictionary",
                "path": "data-dictionary.csv",
                "media_type": "text/csv",
                "sha256": digest,
                "extraction": None,
            })
            manifest["anchors"].append({
                "id": "ANC-04",
                "source_id": "SRC-02",
                "kind": "scope",
                "start_char": 0,
                "end_char": len(dictionary),
                "content_sha256": digest,
                "locator": "Complete data dictionary",
            })
            write_json(manifest_path, manifest)
            resign(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "assessment boundary omits in-scope manifest sources: SRC-02" in error
                for error in errors
            ), errors)
            self.assertTrue(any(
                "coverage lacks a scope-anchored unit for in-scope sources: SRC-02" in error
                for error in errors
            ), errors)
            self.assertTrue(any(
                "source anchors missing from coverage units: ANC-04" in error
                for error in errors
            ), errors)

            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["assessment_boundary"]["sources"].append({
                "source_id": "SRC-02",
                "path": "data-dictionary.csv",
                "status": "fully_read",
                "notes": "The supplied dictionary was read as an internal source.",
                "sha256": digest,
            })
            run["activated_burdens"].append({
                "id": "data_documentation",
                "parent_id": "reproducibility",
                "object_type": "reproducibility",
                "status": "active",
                "activation_basis": "observed",
                "triggers": [{
                    "kind": "anchor",
                    "ref": "ANC-04",
                    "rationale": "The supplied data dictionary activates a documentation audit.",
                }],
                "nonactivation_reason": None,
            })
            write_json(run_path, run)
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage["units"].append({
                "id": "data-dictionary",
                "source_id": "SRC-02",
                "anchor_ids": ["ANC-04"],
                "type": "other",
                "label": "Complete supplied data dictionary",
                "status": "checked_no_issue",
                "finding_ids": [],
                "notes": "The complete dictionary was inventoried and read.",
            })
            coverage["burden_audits"].append({
                "burden_id": "data_documentation",
                "parent_id": "reproducibility",
                "status": "checked_no_issue",
                "coverage_unit_ids": ["data-dictionary"],
                "finding_ids": [],
                "notes": "The supplied dictionary was checked as replication documentation.",
            })
            write_json(coverage_path, coverage)
            for relative, owner in (
                ("evidence/claims.json", "audit_scope"),
                ("evidence/analytical-audit.json", "scope"),
            ):
                path = target / relative
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload[owner]["coverage_unit_ids"].append("data-dictionary")
                write_json(path, payload)
            sync_candidate_discovery_scope(target)
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_bibliography_is_an_internal_source_for_boundary_and_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            bibliography = "@article{example2020, title={A Synthetic Reference}}\n"
            (target / "references.bib").write_text(bibliography, encoding="utf-8")
            digest = hashlib.sha256(bibliography.encode("utf-8")).hexdigest()
            manifest_path = target / "evidence" / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["sources"].append({
                "id": "SRC-02",
                "role": "bibliography",
                "path": "references.bib",
                "media_type": "application/x-bibtex",
                "sha256": digest,
                "extraction": None,
            })
            manifest["anchors"].append({
                "id": "ANC-04",
                "source_id": "SRC-02",
                "kind": "scope",
                "start_char": 0,
                "end_char": len(bibliography),
                "content_sha256": digest,
                "locator": "Complete supplied bibliography",
            })
            write_json(manifest_path, manifest)
            resign(target)

            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "assessment boundary omits in-scope manifest sources: SRC-02" in error
                for error in errors
            ), errors)
            self.assertTrue(any(
                "coverage lacks a scope-anchored unit for in-scope sources: SRC-02" in error
                for error in errors
            ), errors)
            self.assertTrue(any(
                "source anchors missing from coverage units: ANC-04" in error
                for error in errors
            ), errors)

    def test_replication_capability_requires_a_qualifying_active_burden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            add_replication_package(target, "static_only")
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            burden = next(
                row for row in run["activated_burdens"]
                if row["id"] == "replication_traceability"
            )
            burden["parent_id"] = "communication_integrity"
            write_json(run_path, run)
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            audit = next(
                row for row in coverage["burden_audits"]
                if row["burden_id"] == "replication_traceability"
            )
            audit["parent_id"] = "communication_integrity"
            write_json(coverage_path, coverage)
            resign(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "supplied replication material requires an active reproducibility or computational-validity burden"
                in error for error in errors
            ), errors)

    def test_replication_burden_must_cover_every_code_source_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            add_replication_package(target, "static_only")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            audit = next(
                row for row in coverage["burden_audits"]
                if row["burden_id"] == "replication_traceability"
            )
            audit["coverage_unit_ids"] = ["replication-scope"]
            write_json(coverage_path, coverage)
            resign(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "replication burden audits omit supplied-material coverage units: replication-code"
                in error for error in errors
            ), errors)

    def test_inspected_code_range_cannot_hide_in_a_generic_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            add_replication_package(target, "static_only")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            unit = next(row for row in coverage["units"] if row["id"] == "replication-code")
            unit["type"] = "other"
            write_json(coverage_path, coverage)
            resign(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "source anchor ANC-04 of kind code_range requires a matching code coverage unit"
                in error for error in errors
            ), errors)
            self.assertTrue(any(
                "replication_code=static_only requires a code coverage unit for each inspected code source: SRC-02"
                in error for error in errors
            ), errors)

    def test_missing_and_unknown_burden_rows_fail_exact_bijection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            errors = self.mutate_coverage(
                target,
                lambda value: value["burden_audits"].pop(0),
            )
            self.assertTrue(any("activated burdens missing from coverage: claim_consistency" in error for error in errors), errors)
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            def add_unknown(value: dict) -> None:
                row = dict(value["burden_audits"][0])
                row["burden_id"] = "unrecorded_burden"
                value["burden_audits"].append(row)
            errors = self.mutate_coverage(target, add_unknown)
            self.assertTrue(any("coverage references unknown burden IDs: unrecorded_burden" in error for error in errors), errors)

    def test_duplicate_parent_and_state_mismatches_fail(self) -> None:
        cases = [
            (
                lambda value: value["burden_audits"].append(dict(value["burden_audits"][0])),
                "duplicate coverage burden IDs: claim_consistency",
            ),
            (
                lambda value: value["burden_audits"][0].__setitem__("parent_id", "technical_validity"),
                "coverage burden claim_consistency parent_id differs from run.json",
            ),
            (
                lambda value: value["burden_audits"][0].update({"status": "not_applicable", "finding_ids": []}),
                "active burden claim_consistency cannot be not_applicable in coverage",
            ),
            (
                lambda value: value["burden_audits"][-1].update({"status": "checked_no_issue"}),
                "not-applicable burden figure_integrity must be not_applicable in coverage",
            ),
        ]
        for mutation, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                errors = self.mutate_coverage(self.copy_fixture(tmp), mutation)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_burden_unit_and_finding_references_are_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            errors = self.mutate_coverage(
                target,
                lambda value: value["burden_audits"][0]["coverage_unit_ids"].append("missing-unit"),
            )
            self.assertTrue(any("references unknown coverage units: missing-unit" in error for error in errors), errors)
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            errors = self.mutate_coverage(
                target,
                lambda value: value["burden_audits"][0].update({"finding_ids": ["BOGUS-99"]}),
            )
            self.assertTrue(any("references unknown finding IDs: BOGUS-99" in error for error in errors), errors)
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            def omit_writing(value: dict) -> None:
                row = next(item for item in value["burden_audits"] if item["burden_id"] == "writing_mechanics")
                row.update({"status": "checked_no_issue", "finding_ids": []})
            errors = self.mutate_coverage(target, omit_writing)
            self.assertTrue(any("active findings missing from burden coverage: WRT-01" in error for error in errors), errors)

    def test_coverage_unit_source_and_anchor_provenance_is_exact(self) -> None:
        cases = [
            (
                lambda value: value["units"][0].__setitem__("source_id", "SRC-99"),
                "coverage unit paper references unknown source SRC-99",
            ),
            (
                lambda value: value["units"][0]["anchor_ids"].append("ANC-99"),
                "coverage unit paper references unknown anchor ANC-99",
            ),
            (
                lambda value: value["units"][0].__setitem__("anchor_ids", ["ANC-01", "ANC-02"]),
                "coverage lacks a scope-anchored unit for in-scope sources: SRC-01",
            ),
            (
                lambda value: value["units"][0].__setitem__("anchor_ids", ["ANC-01", "ANC-03"]),
                "source anchors missing from coverage units: ANC-02",
            ),
        ]
        for mutation, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                errors = self.mutate_coverage(self.copy_fixture(tmp), mutation)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_anchor_from_another_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            manifest_path = target / "evidence" / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            second_source = dict(manifest["sources"][0])
            second_source.update({"id": "SRC-02", "role": "external_source"})
            manifest["sources"].append(second_source)
            second_anchor = dict(manifest["anchors"][-1])
            second_anchor.update({"id": "ANC-04", "source_id": "SRC-02"})
            manifest["anchors"].append(second_anchor)
            write_json(manifest_path, manifest)
            errors = self.mutate_coverage(
                target,
                lambda value: value["units"][0]["anchor_ids"].append("ANC-04"),
            )
            self.assertTrue(any("anchor ANC-04 belongs to another source" in error for error in errors), errors)

    def test_typed_anchor_cannot_hide_inside_a_generic_whole_paper_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            manifest_path = target / "evidence" / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            typed = dict(manifest["anchors"][0])
            typed.update({"id": "ANC-04", "kind": "equation"})
            manifest["anchors"].append(typed)
            write_json(manifest_path, manifest)
            errors = self.mutate_coverage(
                target,
                lambda value: value["units"][0]["anchor_ids"].append("ANC-04"),
            )
            self.assertTrue(any(
                "source anchor ANC-04 of kind equation requires a matching equation coverage unit" in error
                for error in errors
            ), errors)

    def test_readable_coverage_drift_is_rejected_even_when_receipt_is_resigned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "coverage.md"
            path.write_text(path.read_text(encoding="utf-8") + "\nInvented coverage claim.\n", encoding="utf-8")
            resign(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("coverage.md is not synchronized" in error for error in errors), errors)

    def test_current_assessment_boundary_requires_exact_source_join(self) -> None:
        mutations = [
            (lambda source: source.pop("source_id"), "require canonical source_id values"),
            (lambda source: source.__setitem__("source_id", "SRC-99"), "omits in-scope manifest sources: SRC-01"),
            (lambda source: source.__setitem__("path", "another-paper.md"), "path differs from source manifest"),
            (lambda source: source.__setitem__("sha256", "a" * 64), "hash differs from source manifest"),
        ]
        for mutation, expected in mutations:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                target = self.copy_fixture(tmp)
                run_path = target / "run.json"
                run = json.loads(run_path.read_text(encoding="utf-8"))
                mutation(run["assessment_boundary"]["sources"][0])
                write_json(run_path, run)
                resign(target)
                errors = MODULE.validate_review(target)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_receipt_v02_preserves_legacy_coverage_and_boundary_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage["schema_version"] = "0.1"
            coverage.pop("burden_audits")
            for unit in coverage["units"]:
                unit.pop("source_id")
                unit.pop("anchor_ids")
            write_json(coverage_path, coverage)
            (target / "evidence" / "coverage.md").write_text("# Legacy coverage matrix\n", encoding="utf-8")
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["assessment_boundary"]["sources"][0].pop("source_id")
            write_json(run_path, run)
            resign(target, receipt_version="0.2")
            self.assertEqual(MODULE.validate_review(target), [])

    def test_receipt_v02_does_not_retrofit_replication_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            add_replication_package(target, "static_only")

            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["assessment_boundary"]["sources"] = [
                row
                for row in run["assessment_boundary"]["sources"]
                if row.get("source_id") != "SRC-02"
            ]
            run["activated_burdens"] = [
                row
                for row in run["activated_burdens"]
                if row.get("id") != "replication_traceability"
            ]
            write_json(run_path, run)

            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            removed_units = {"replication-scope", "replication-code"}
            coverage["units"] = [
                row for row in coverage["units"] if row.get("id") not in removed_units
            ]
            coverage["burden_audits"] = [
                row
                for row in coverage["burden_audits"]
                if row.get("burden_id") != "replication_traceability"
            ]
            write_json(coverage_path, coverage)
            for relative, owner in (
                ("evidence/claims.json", "audit_scope"),
                ("evidence/analytical-audit.json", "scope"),
            ):
                path = target / relative
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload[owner]["coverage_unit_ids"] = [
                    unit_id
                    for unit_id in payload[owner]["coverage_unit_ids"]
                    if unit_id not in removed_units
                ]
                write_json(path, payload)

            for script in (
                "generate_sources.py", "generate_coverage.py", "generate_reports.py",
            ):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "econ-review" / "scripts" / script), str(target)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            resign(target, receipt_version="0.2")
            self.assertEqual(MODULE.validate_review(target), [])


if __name__ == "__main__":
    unittest.main()
