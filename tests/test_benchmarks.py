#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "evaluate.py"
SPEC = importlib.util.spec_from_file_location("benchmark_evaluate", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BenchmarkHarnessTests(unittest.TestCase):
    @staticmethod
    def minimal_case(case_id: str = "synthetic-case") -> dict:
        return {
            "id": case_id,
            "paper": f"papers/{case_id}.md",
            "required_active_burdens": [],
            "required_not_applicable_burdens": [],
            "required_active_parent_burdens": [],
            "required_not_applicable_parent_burdens": [],
            "forbidden_active_burden_ids": [],
            "required_issue_concepts": [],
            "forbidden_issue_concepts": [],
        }

    def test_available_only_and_require_all_distinguish_missing_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases_path = root / "cases.json"
            reviews = root / "reviews"
            reviews.mkdir()
            cases_path.write_text(
                json.dumps({"schema_version": "0.2", "cases": [self.minimal_case()]}),
                encoding="utf-8",
            )
            with (
                mock.patch.object(MODULE, "CASES_PATH", cases_path),
                mock.patch.object(MODULE, "REVIEWS", reviews),
                contextlib.redirect_stdout(io.StringIO()) as available_output,
            ):
                self.assertEqual(MODULE.main([]), 0)
            available = json.loads(available_output.getvalue())
            self.assertEqual(available["mode"], "available_only")
            self.assertEqual(available["rubric_case_count"], 1)
            self.assertEqual(available["executed_package_count"], 0)
            self.assertEqual(available["missing_review_packages"], ["synthetic-case"])

            with (
                mock.patch.object(MODULE, "CASES_PATH", cases_path),
                mock.patch.object(MODULE, "REVIEWS", reviews),
                contextlib.redirect_stdout(io.StringIO()) as strict_output,
            ):
                self.assertEqual(MODULE.main(["--require-all"]), 1)
            strict = json.loads(strict_output.getvalue())
            self.assertEqual(strict["mode"], "require_all")
            self.assertEqual(strict["missing_review_packages"], ["synthetic-case"])

    def test_present_but_unreadable_package_always_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reviews = Path(temporary)
            (reviews / "synthetic-case").mkdir()
            result = MODULE.evaluate_case(self.minimal_case(), reviews=reviews)
            self.assertEqual(result["status"], "invalid_input")
            self.assertTrue(MODULE.result_failed(result, require_all=False))
            self.assertTrue(MODULE.result_failed(result, require_all=True))

    def test_draft_package_cannot_count_as_a_completed_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reviews = Path(temporary)
            review = reviews / "synthetic-case"
            review.mkdir(parents=True)
            (review / "run.json").write_text(
                json.dumps({"status": "draft", "activated_burdens": []}),
                encoding="utf-8",
            )
            (review / "findings.json").write_text(
                json.dumps({"findings": []}), encoding="utf-8"
            )
            with mock.patch.object(
                MODULE.subprocess, "run", return_value=mock.Mock(returncode=0)
            ) as finalizer:
                result = MODULE.evaluate_case(self.minimal_case(), reviews=reviews)
            self.assertEqual(result["status"], "evaluated")
            self.assertFalse(result["completion_valid"])
            self.assertFalse(result["contract_valid"])
            self.assertTrue(MODULE.result_failed(result, require_all=False))
            self.assertEqual(finalizer.call_args.args[0][-1], "--check")

    def test_ambiguous_rubric_and_review_json_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rubric = root / "cases.json"
            rubric.write_text(
                '{"schema_version":"0.1","schema_version":"0.2","cases":[]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON key: schema_version"):
                MODULE.load_json(rubric)

            reviews = root / "reviews"
            review = reviews / "synthetic-case"
            review.mkdir(parents=True)
            (review / "run.json").write_text(
                '{"review_id":"first","review_id":"second"}',
                encoding="utf-8",
            )
            (review / "findings.json").write_text('{"findings":[]}', encoding="utf-8")
            result = MODULE.evaluate_case(self.minimal_case(), reviews=reviews)
            self.assertEqual(result["status"], "invalid_input")
            self.assertIn("duplicate JSON key: review_id", result["error"])

    def test_verified_evidence_boundary_counts_as_issue_diagnosis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reviews = Path(temporary)
            review = reviews / "synthetic-case"
            review.mkdir(parents=True)
            (review / "run.json").write_text(
                json.dumps({"activated_burdens": []}), encoding="utf-8"
            )
            (review / "findings.json").write_text(
                json.dumps({
                    "findings": [{
                        "status": "open",
                        "title": "Changing support weakens the interpretation",
                        "issue": "The reported movement mixes price and composition changes.",
                        "evidence_boundary": "The promised decomposition is absent from the reported results.",
                    }],
                }),
                encoding="utf-8",
            )
            case = self.minimal_case()
            case["required_issue_concepts"] = [{
                "id": "promised-object",
                "patterns": ["promised decomposition.*absent"],
            }]
            with mock.patch.object(
                MODULE.subprocess, "run", return_value=mock.Mock(returncode=0)
            ):
                result = MODULE.evaluate_case(case, reviews=reviews)
            self.assertTrue(result["required_issue_concepts"]["promised-object"])
            self.assertEqual(
                result["required_issue_matches"]["promised-object"][0]["finding_id"],
                "<unnamed>",
            )

    def test_concept_terms_cannot_match_across_different_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reviews = Path(temporary)
            review = reviews / "synthetic-case"
            review.mkdir(parents=True)
            (review / "run.json").write_text(
                json.dumps({"activated_burdens": []}), encoding="utf-8"
            )
            (review / "findings.json").write_text(
                json.dumps({
                    "findings": [
                        {"id": "ONE-01", "status": "open", "issue": "The paper promised a result."},
                        {"id": "TWO-01", "status": "open", "issue": "The decomposition is absent."},
                    ],
                }),
                encoding="utf-8",
            )
            case = self.minimal_case()
            case["required_issue_concepts"] = [{
                "id": "promised-object",
                "patterns": ["promised.*decomposition.*absent"],
            }]
            with mock.patch.object(
                MODULE.subprocess, "run", return_value=mock.Mock(returncode=0)
            ):
                result = MODULE.evaluate_case(case, reviews=reviews)
            self.assertFalse(result["required_issue_concepts"]["promised-object"])
            self.assertEqual(result["required_issue_matches"]["promised-object"], [])

    def test_source_quote_without_reviewer_diagnosis_cannot_satisfy_rubric(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reviews = Path(temporary)
            review = reviews / "synthetic-case"
            review.mkdir(parents=True)
            (review / "run.json").write_text(
                json.dumps({"activated_burdens": []}), encoding="utf-8"
            )
            (review / "findings.json").write_text(
                json.dumps({
                    "findings": [{
                        "id": "QUOTE-01",
                        "status": "open",
                        "issue": "The presentation needs clarification.",
                        "evidence": [{"content": "The promised decomposition is absent."}],
                    }],
                }),
                encoding="utf-8",
            )
            case = self.minimal_case()
            case["required_issue_concepts"] = [{
                "id": "promised-object",
                "patterns": ["promised decomposition.*absent"],
            }]
            with mock.patch.object(
                MODULE.subprocess, "run", return_value=mock.Mock(returncode=0)
            ):
                result = MODULE.evaluate_case(case, reviews=reviews)
            self.assertFalse(result["required_issue_concepts"]["promised-object"])

    def test_parent_aggregation_uses_active_precedence_and_not_absence(self) -> None:
        burdens = [
            {"id": "causal_identification", "parent_id": "identification_validity", "status": "active"},
            {"id": "structural_identification", "parent_id": "identification_validity", "status": "not_applicable"},
            {"id": "formal_proof", "parent_id": "formal_validity", "status": "not_applicable"},
        ]
        active, not_applicable = MODULE.parent_states(burdens)
        self.assertIn("identification_validity", active)
        self.assertNotIn("identification_validity", not_applicable)
        self.assertIn("formal_validity", not_applicable)
        self.assertNotIn("measurement_validity", active | not_applicable)

    def test_writing_channel_cannot_satisfy_a_substance_rubric(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reviews = Path(temporary)
            review = reviews / "synthetic-case"
            review.mkdir(parents=True)
            (review / "run.json").write_text(
                json.dumps({"activated_burdens": []}), encoding="utf-8"
            )
            (review / "findings.json").write_text(
                json.dumps({
                    "findings": [{
                        "status": "open",
                        "report_channel": "writing",
                        "issue": "The promised decomposition is absent.",
                    }],
                }),
                encoding="utf-8",
            )
            case = self.minimal_case()
            case["required_issue_concepts"] = [{
                "id": "promised-object",
                "patterns": ["promised decomposition.*absent"],
            }]
            with mock.patch.object(
                MODULE.subprocess, "run", return_value=mock.Mock(returncode=0)
            ):
                result = MODULE.evaluate_case(case, reviews=reviews)
            self.assertFalse(result["required_issue_concepts"]["promised-object"])

    def test_cross_family_connective_rubrics_and_clean_traps_are_declared(self) -> None:
        contract = MODULE.load_json(ROOT / "benchmarks" / "cases.json")
        self.assertEqual(contract["case_contract"], "rubric_only_seed")
        cases = {case["id"]: case for case in contract["cases"]}
        expected_required = {
            "descriptive-index": {
                "index-interpretation-bridge",
                "promised-unreported-decomposition",
                "cross-summary-coherence",
            },
            "structural-counterfactual": {
                "promised-unreported-objects",
                "fit-counterfactual-coherence",
                "alternative-policy-channel",
                "welfare-magnitude-definition",
                "counterfactual-transport-scope",
            },
            "macro-transition": {
                "direct-alternative-channel",
                "promised-unreported-objects",
                "cross-result-coherence",
                "calibration-transport-scope",
            },
            "formal-theory-existence": {
                "delay-mechanism-bridge",
                "promised-unmodeled-welfare",
                "cross-proposition-coherence",
            },
        }
        expected_forbidden = {
            "descriptive-index": {"invented-alternative-causal-channel", "invented-transport-overreach"},
            "structural-counterfactual": {"mandatory-randomized-trial"},
            "macro-transition": {"invented-causal-design-demand"},
            "formal-theory-existence": {"mandatory-empirical-validation", "invented-magnitude-benchmark"},
        }
        for case_id, concept_ids in expected_required.items():
            case = cases[case_id]
            declared = {concept["id"] for concept in case["required_issue_concepts"]}
            self.assertTrue(concept_ids <= declared, (case_id, concept_ids - declared))
            for concept in case["required_issue_concepts"] + case["forbidden_issue_concepts"]:
                for pattern in concept["patterns"]:
                    re.compile(pattern)
            self.assertTrue((ROOT / "benchmarks" / case["paper"]).is_file())
        for case_id, concept_ids in expected_forbidden.items():
            declared = {concept["id"] for concept in cases[case_id]["forbidden_issue_concepts"]}
            self.assertTrue(concept_ids <= declared, (case_id, concept_ids - declared))


if __name__ == "__main__":
    unittest.main()
