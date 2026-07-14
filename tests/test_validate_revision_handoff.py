from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "validate_revision_handoff.py"
SPEC = importlib.util.spec_from_file_location("validate_revision_handoff", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def tasks() -> dict:
    value = {
        "schema_version": "0.1",
        "kind": "econ-review-revision-tasks",
        "plan_id": "00000000-0000-4000-8000-000000000101",
        "source_review_id": "review-001",
        "source_review_fingerprint": "ledger-v1",
        "generated_at": "2026-07-13T13:00:00Z",
        "all_comments_reviewed": True,
        "handoff_ready": True,
        "tasks": [{
            "finding_id": "LOGIC-01",
            "user_priority": "P0",
            "reviewed": True,
            "disposition": "open",
            "user_comment": "Keep the proposition concise.",
            "title": "Qualify the boundary case",
            "issue": "The proposition claims uniqueness at equality.",
            "relevant_text": "The equilibrium is unique for every value.",
            "suggestions": "Qualify the proposition and proof at equality.",
            "done_when": "The proposition and proof use the same boundary condition.",
            "source_location": "Section 3, paragraph 1",
        }],
        "excluded": [{
            "finding_id": "WRT-01",
            "disposition": "not_relevant",
            "user_priority": None,
            "reviewed": True,
            "user_comment": "House style requires this form.",
            "title": "Local style choice",
        }],
    }
    value["plan_id"] = MODULE.expected_plan_id(value)
    return value


def template() -> dict:
    plan = tasks()
    return {
        "schema_version": "0.1",
        "kind": "econ-review-agent-response",
        "plan_id": plan["plan_id"],
        "source_review_id": plan["source_review_id"],
        "source_review_fingerprint": plan["source_review_fingerprint"],
        "responded_at": None,
        "entries": [{
            "finding_id": "LOGIC-01",
            "status": "not_attempted",
            "response": "",
            "changed_files": [],
            "changed_locations": [],
            "verification": [],
            "blocker": None,
        }],
    }


def completed_response() -> dict:
    response = template()
    response["responded_at"] = "2026-07-13T14:00:00Z"
    response["entries"][0].update({
        "status": "changed",
        "response": "Qualified the proposition and its proof at equality.",
        "changed_files": ["paper.tex"],
        "changed_locations": [{
            "path": "paper.tex",
            "locator": "Proposition 1 and proof",
            "summary": "Added the boundary qualification in both locations.",
        }],
        "verification": [{
            "check": "Compile manuscript",
            "result": "passed",
            "details": "The PDF compiled without errors.",
        }],
        "blocker": None,
    })
    return response


def source_bound_inputs() -> tuple[dict, dict, dict]:
    findings_path = ROOT / "tests/fixtures/valid-review/findings.json"
    findings = json.loads(findings_path.read_text(encoding="utf-8"))
    # The test writes this parsed object in compact form below; bind those
    # exact bytes, as the browser does for the file it actually loaded.
    fingerprint = hashlib.sha256(json.dumps(findings).encode("utf-8")).hexdigest()
    plan = tasks()
    plan["source_review_id"] = findings["review_id"]
    plan["source_review_fingerprint"] = fingerprint
    plan["generated_at"] = "2026-07-13T13:06:00Z"
    plan["plan_id"] = MODULE.expected_plan_id(plan)

    def event(event_id: int, event_type: str, at: str, parent: int | None, **fields: object) -> dict:
        return {
            "event_id": f"00000000-0000-4000-8000-{event_id:012d}",
            "type": event_type,
            "at": at,
            "parent_event_id": None if parent is None else f"00000000-0000-4000-8000-{parent:012d}",
            "origin": "local",
            **fields,
        }

    actions = {
        "schema_version": "0.4",
        "kind": "econ-review-actions",
        "source_review_id": findings["review_id"],
        "source_review_fingerprint": fingerprint,
        "source_manuscripts": [],
        "exported_at": "2026-07-13T13:07:00Z",
        "entries": [
            {
                "finding_id": "LOGIC-01",
                "disposition": "open",
                "response_note": "Keep the proposition concise.",
                "changed_locations": [],
                "user_priority": "P0",
                "reviewed": True,
                "updated_at": "2026-07-13T13:03:00Z",
                "status_history": [{"disposition": "open", "at": "2026-07-13T13:00:00Z"}],
                "events": [
                    event(1, "disposition_changed", "2026-07-13T13:00:00Z", None, disposition="open"),
                    event(2, "note_revised", "2026-07-13T13:01:00Z", 1, note="Keep the proposition concise."),
                    event(3, "priority_changed", "2026-07-13T13:02:00Z", 2, user_priority="P0"),
                    event(4, "reviewed_changed", "2026-07-13T13:03:00Z", 3, reviewed=True),
                ],
            },
            {
                "finding_id": "WRT-01",
                "disposition": "not_relevant",
                "response_note": "House style requires this form.",
                "changed_locations": [],
                "user_priority": None,
                "reviewed": True,
                "updated_at": "2026-07-13T13:06:00Z",
                "status_history": [{"disposition": "not_relevant", "at": "2026-07-13T13:04:00Z"}],
                "events": [
                    event(5, "disposition_changed", "2026-07-13T13:04:00Z", None, disposition="not_relevant"),
                    event(6, "note_revised", "2026-07-13T13:05:00Z", 5, note="House style requires this form."),
                    event(7, "reviewed_changed", "2026-07-13T13:06:00Z", 6, reviewed=True),
                ],
            },
        ],
    }
    return plan, findings, actions


class RevisionHandoffTests(unittest.TestCase):
    def validate(self, plan: dict, response: dict | None = None, *, template_mode: bool = False) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tasks_path = root / "revision-tasks.json"
            tasks_path.write_text(json.dumps(plan), encoding="utf-8")
            if response is None:
                return MODULE.validate(tasks_path)
            response_path = root / "revision-response.json"
            response_path.write_text(json.dumps(response), encoding="utf-8")
            return MODULE.validate(tasks_path, response_path, template=template_mode)

    def test_valid_tasks_template_and_changed_response_pass(self) -> None:
        self.assertEqual(self.validate(tasks()), [])
        self.assertEqual(self.validate(tasks(), template(), template_mode=True), [])
        self.assertEqual(self.validate(tasks(), completed_response()), [])

    def test_plan_orders_priorities_and_has_unique_ids(self) -> None:
        plan = tasks()
        second = json.loads(json.dumps(plan["tasks"][0]))
        second["finding_id"] = "LOGIC-02"
        second["user_priority"] = "P2"
        plan["tasks"] = [second, plan["tasks"][0]]
        errors = self.validate(plan)
        self.assertTrue(any("ordered P0, P1, P2" in error for error in errors), errors)

        plan = tasks()
        plan["excluded"][0]["finding_id"] = "LOGIC-01"
        errors = self.validate(plan)
        self.assertTrue(any("repeat finding IDs" in error for error in errors), errors)

    def test_plan_id_binds_every_task_decision_and_instruction(self) -> None:
        plan = tasks()
        plan["tasks"][0]["user_comment"] = "A silently altered instruction."
        errors = self.validate(plan)
        self.assertTrue(any("plan_id does not match" in error for error in errors), errors)

    def test_response_binds_exact_plan_and_task_ids(self) -> None:
        response = completed_response()
        response["plan_id"] = "00000000-0000-4000-8000-000000000999"
        response["entries"][0]["finding_id"] = "LOGIC-99"
        errors = self.validate(tasks(), response)
        self.assertTrue(any("plan_id does not match" in error for error in errors), errors)
        self.assertTrue(any("omits active revision tasks" in error for error in errors), errors)
        self.assertTrue(any("non-task finding IDs" in error for error in errors), errors)

    def test_response_rejects_private_or_unlisted_paths(self) -> None:
        response = completed_response()
        response["entries"][0]["changed_locations"][0]["path"] = "appendix.tex"
        response["entries"][0]["changed_files"] = ["/absolute/paper.tex"]
        errors = self.validate(tasks(), response)
        self.assertTrue(any("schema violation" in error for error in errors), errors)

        response = completed_response()
        response["entries"][0]["changed_locations"][0]["path"] = "appendix.tex"
        errors = self.validate(tasks(), response)
        self.assertTrue(any("absent from changed_files" in error for error in errors), errors)

    def test_changed_response_requires_successful_verification(self) -> None:
        response = completed_response()
        response["entries"][0]["verification"][0]["result"] = "failed"
        errors = self.validate(tasks(), response)
        self.assertTrue(any("every reported check to pass" in error for error in errors), errors)

    def test_agent_response_requires_a_ready_user_plan(self) -> None:
        plan = tasks()
        plan["all_comments_reviewed"] = False
        plan["handoff_ready"] = False
        plan["tasks"][0]["reviewed"] = False
        plan["plan_id"] = MODULE.expected_plan_id(plan)
        response = completed_response()
        response["plan_id"] = plan["plan_id"]
        errors = self.validate(plan, response)
        self.assertTrue(any("cannot be accepted until every comment" in error for error in errors), errors)

    def test_handoff_readiness_is_recomputed_from_every_comment(self) -> None:
        plan = tasks()
        plan["handoff_ready"] = False
        plan["tasks"][0]["user_comment"] = ""
        plan["plan_id"] = MODULE.expected_plan_id(plan)
        self.assertEqual(self.validate(plan), [])
        plan["tasks"][0]["user_comment"] = "Now complete."
        plan["plan_id"] = MODULE.expected_plan_id(plan)
        errors = self.validate(plan)
        self.assertTrue(any("handoff_ready must reflect" in error for error in errors), errors)

        plan = tasks()
        plan["handoff_ready"] = False
        plan["tasks"][0]["reviewed"] = False
        plan["plan_id"] = MODULE.expected_plan_id(plan)
        errors = self.validate(plan)
        self.assertTrue(any("all_comments_reviewed must equal" in error for error in errors), errors)

    def test_response_only_can_answer_a_challenge_without_fake_file_edits(self) -> None:
        response = template()
        response["responded_at"] = "2026-07-13T14:00:00Z"
        response["entries"][0].update({
            "status": "response_only",
            "response": "No edit was made because the appendix already states the condition; see Appendix A.2.",
        })
        self.assertEqual(self.validate(tasks(), response), [])

    def test_response_template_must_stay_unattempted_and_undated(self) -> None:
        response = template()
        response["responded_at"] = "2026-07-13T14:00:00Z"
        errors = self.validate(tasks(), response, template_mode=True)
        self.assertTrue(any("responded_at must be null" in error for error in errors), errors)

    def test_full_source_binding_matches_findings_and_committed_actions(self) -> None:
        plan, findings, actions = source_bound_inputs()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan_path = root / "revision-tasks.json"
            findings_path = root / "findings.json"
            actions_path = root / "review-actions.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            findings_path.write_text(json.dumps(findings), encoding="utf-8")
            actions_path.write_text(json.dumps(actions), encoding="utf-8")
            self.assertEqual(MODULE.validate(
                plan_path,
                findings_path=findings_path,
                actions_path=actions_path,
            ), [])

            plan["tasks"][0]["user_comment"] = "A different instruction."
            plan["plan_id"] = MODULE.expected_plan_id(plan)
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            errors = MODULE.validate(
                plan_path,
                findings_path=findings_path,
                actions_path=actions_path,
            )
            self.assertTrue(any("does not match the committed review action" in error for error in errors), errors)

    @unittest.skipUnless(shutil.which("node"), "Node is optional for the core skill")
    def test_viewer_and_python_hash_the_same_findings_bytes(self) -> None:
        findings_path = ROOT / "tests/fixtures/valid-review/findings.json"
        module_uri = (ROOT / "review-viewer/lib/review-fingerprint.ts").as_uri()
        script = f"""
import {{ sha256Hex }} from {json.dumps(module_uri)};
const text = {json.dumps(findings_path.read_text(encoding="utf-8"))};
process.stdout.write(sha256Hex(text));
"""
        result = subprocess.run(
            [shutil.which("node") or "node", "--experimental-strip-types", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 and "bad option" in result.stderr.lower():
            self.skipTest("Installed Node does not support erasable TypeScript")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, hashlib.sha256(findings_path.read_bytes()).hexdigest())

    @unittest.skipUnless(shutil.which("node"), "Node is optional for the core skill")
    def test_viewer_generated_plan_id_validates_cross_runtime(self) -> None:
        module_uri = (ROOT / "review-viewer/lib/revision-plan.ts").as_uri()
        script = f"""
import {{ buildRevisionTasks }} from {json.dumps(module_uri)};
const finding = (id, rank, disposition) => ({{
  id, title: `${{id}} title`, importance_rank: rank, status: "open", issue: `${{id}} issue`,
  paper_position: {{ source_id: "SRC-01", anchor_id: `ANC-${{rank}}`, ordinal: rank }},
  display_evidence_id: `EVD-${{id}}`, evidence: [{{ id: `EVD-${{id}}`, type: "quote", content: `${{id}} text`, source: "paper", locator: {{ page: rank }} }}],
  fix: {{ what: "Revise.", how: "Clarify.", resolved_when: "The statement is consistent." }}, verification: "pending", disposition,
}});
const at = "2026-07-13T13:06:00Z";
const entry = (id, disposition, priority, note) => ({{ finding_id: id, disposition, response_note: note, changed_locations: [], user_priority: priority, reviewed: true, updated_at: at, status_history: [], events: [] }});
const payload = buildRevisionTasks({{
  source_review_id: "review-001", source_review_fingerprint: "ledger-v1",
  findings: [finding("LOGIC-01", 1), finding("WRT-01", 2)],
  entries: {{
    "LOGIC-01": entry("LOGIC-01", "open", "P0", "Implement this change."),
    "WRT-01": entry("WRT-01", "not_relevant", null, "This does not apply."),
  }},
}});
process.stdout.write(JSON.stringify(payload));
"""
        result = subprocess.run(
            [shutil.which("node") or "node", "--experimental-strip-types", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 and "bad option" in result.stderr.lower():
            self.skipTest("Installed Node does not support erasable TypeScript")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "revision-tasks.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(MODULE.validate(path), [])


if __name__ == "__main__":
    unittest.main()
