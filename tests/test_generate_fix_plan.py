#!/usr/bin/env python3
"""Regression tests for the canonical revision-plan generator."""

from __future__ import annotations

import importlib.util
import copy
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "generate_fix_plan.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
SPEC = importlib.util.spec_from_file_location("generate_fix_plan", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GenerateFixPlanTests(unittest.TestCase):
    def test_each_finding_id_appears_once_in_a_hidden_link(self) -> None:
        output = MODULE.render(FIXTURE)
        finding_ids = re.findall(r"^<!-- finding_id: ([A-Z][A-Z0-9_-]*-[0-9]{2,}) -->$", output, re.MULTILINE)
        self.assertTrue(finding_ids)
        for finding_id in finding_ids:
            self.assertEqual(
                re.findall(rf"\b{re.escape(finding_id)}\b", output),
                [finding_id],
            )
            self.assertNotRegex(
                output,
                re.compile(rf"^### .*{re.escape(finding_id)}", re.MULTILINE),
            )
        numbers = [int(value) for value in re.findall(r"^### Comment ([0-9]+):", output, re.MULTILINE)]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        self.assertEqual(len(numbers), len(finding_ids))

    def test_actions_are_checkable_and_completion_language_is_explained(self) -> None:
        output = MODULE.render(FIXTURE)
        headings = re.findall(r"^### Comment [0-9]+:", output, re.MULTILINE)
        checkboxes = re.findall(r"^- \[ \] \*\*Action:\*\*", output, re.MULTILINE)
        self.assertEqual(len(checkboxes), len(headings))
        self.assertIn("Work from P0 to P2", output)
        self.assertIn("A later review confirms whether each revision resolves the concern", output)
        self.assertIn("Unless an item says otherwise, the current design can support", output)
        self.assertNotIn("- **Feasibility:** The current design can support", output)
        self.assertNotIn("Audit trail", output)
        self.assertNotIn("review-actions.json", output)
        self.assertNotIn("Review Desk", output)
        self.assertNotIn("**Ready for recheck**", output)

    def test_dependency_order_is_severity_first_then_decision_role(self) -> None:
        base = copy.deepcopy(MODULE.load(FIXTURE / "findings.json")["findings"][0])
        rows = []
        for finding_id, severity, role, rank in (
            ("MINOR-01", "minor", "potentially_dispositive", 1),
            ("CRIT-01", "critical", "potentially_dispositive", 99),
            ("MAJOR-02", "major", "revision_value", 2),
            ("MAJOR-01", "major", "potentially_dispositive", 50),
        ):
            row = copy.deepcopy(base)
            row.update({
                "id": finding_id,
                "severity": severity,
                "decision_role": role,
                "importance_rank": rank,
            })
            row["fix"]["dependencies"] = []
            rows.append(row)
        self.assertEqual(
            [row["id"] for row in MODULE.dependency_order(rows)],
            ["CRIT-01", "MAJOR-01", "MAJOR-02", "MINOR-01"],
        )
        self.assertEqual(MODULE.bucket(rows[1]), "P0")

    def test_render_rejects_critical_finding_without_p0_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            row = ledger["findings"][0]
            row.update({"severity": "critical", "decision_role": "revision_value", "essential": False})
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "critical.*potentially_dispositive.*essential.*P0"):
                MODULE.render(target)

    def test_canonical_resolution_and_payoff_render_without_reconstruction(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        first = ledger["findings"][0]
        output = MODULE.render(FIXTURE)
        self.assertIn(f"- **Payoff:** {first['fix']['publishability']}", output)
        expected_closure = MODULE.without_self_reference(first["fix"]["resolved_when"], first["id"])
        self.assertIn(f"- **Done when:** {expected_closure}", output)

    def test_action_combines_distinct_direction_and_steps_without_duplication(self) -> None:
        action = MODULE.combined_action({
            "what": "State a tie-breaking rule or weaken uniqueness at equality.",
            "how": "Revise Proposition 1 and its proof.",
        }, "LOGIC-01")
        self.assertEqual(
            action,
            "State a tie-breaking rule or weaken uniqueness at equality. Revise Proposition 1 and its proof.",
        )
        self.assertEqual(MODULE.combined_action({
            "what": "Revise Proposition 1.",
            "how": "Revise Proposition 1 and its proof.",
        }, "LOGIC-01"), "Revise Proposition 1 and its proof.")

    def test_migration_boilerplate_is_rejected(self) -> None:
        row = copy.deepcopy(MODULE.load(FIXTURE / "findings.json")["findings"][0])
        row["fix"]["resolved_when"] = f"{row['id']} closes when a change is visible."
        with self.assertRaisesRegex(ValueError, "observable completion evidence"):
            MODULE.reject_generic_plan_text(row)
        row["fix"]["resolved_when"] = "The revision reports the boundary case."
        row["fix"]["publishability"] = f"Closing {row['id']} removes the submission risk."
        with self.assertRaisesRegex(ValueError, "paper-specific benefit"):
            MODULE.reject_generic_plan_text(row)
        row["fix"]["publishability"] = "Clarifies the boundary of the proposition."
        row["fix"]["resolved_when"] = "The revised paper implements this repair in the cited text or exhibit."
        with self.assertRaisesRegex(ValueError, "paper-specific state"):
            MODULE.reject_generic_plan_text(row)


if __name__ == "__main__":
    unittest.main()
