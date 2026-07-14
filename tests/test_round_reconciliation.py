from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "round_reconciliation.py"
HANDOFF_SCRIPT = ROOT / "econ-review" / "scripts" / "validate_revision_handoff.py"
RUN_SCHEMA = ROOT / "econ-review" / "assets" / "run.schema.json"
VALIDATE_REVIEW_SCRIPT = ROOT / "econ-review" / "scripts" / "validate_review.py"
FINALIZER_SCRIPT = ROOT / "econ-review" / "scripts" / "finalize_review.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_module("round_reconciliation", SCRIPT)
HANDOFF = load_module("round_reconciliation_handoff", HANDOFF_SCRIPT)
REVIEW_VALIDATOR = load_module("round_reconciliation_review_validator", VALIDATE_REVIEW_SCRIPT)
FINALIZER = load_module("round_reconciliation_finalizer", FINALIZER_SCRIPT)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def action_entry(
    finding_id: str,
    disposition: str,
    note: str,
    priority: str | None,
    serial: int,
) -> dict:
    events = []

    def event(event_type: str, minute: int, **values) -> None:
        number = serial * 100 + len(events) + 1
        events.append({
            "event_id": f"00000000-0000-4000-8000-{number:012d}",
            "type": event_type,
            "at": f"2026-07-13T10:{minute:02d}:00Z",
            "parent_event_id": events[-1]["event_id"] if events else None,
            "origin": "import" if event_type == "imported" else "local",
            **values,
        })

    event("imported", 0)
    event("disposition_changed", 1, disposition="open")
    event("note_revised", 2, note=note)
    event("priority_changed", 3, user_priority=priority)
    event("reviewed_changed", 4, reviewed=True)
    if disposition != "open":
        event("disposition_changed", 5, disposition=disposition)
    status_history = [{"disposition": "open", "at": "2026-07-13T10:01:00Z"}]
    if disposition != "open":
        status_history.append({"disposition": disposition, "at": "2026-07-13T10:05:00Z"})
    return {
        "finding_id": finding_id,
        "disposition": disposition,
        "response_note": note,
        "changed_locations": [],
        "updated_at": events[-1]["at"],
        "status_history": status_history,
        "events": events,
        "user_priority": priority,
        "reviewed": True,
    }


def plan_task(finding_id: str, disposition: str, note: str, priority: str) -> dict:
    return {
        "finding_id": finding_id,
        "user_priority": priority,
        "reviewed": True,
        "disposition": disposition,
        "user_comment": note,
        "title": "Boundary qualification remains necessary",
        "issue": "The current statement still includes an unsupported boundary case.",
        "relevant_text": "The proposition states uniqueness at equality.",
        "suggestions": "Align the proposition and proof with the supported boundary.",
        "done_when": "The proposition and proof state the same supported domain.",
        "source_location": "Section 3, Proposition 1",
    }


def excluded_task(finding_id: str, disposition: str, note: str) -> dict:
    return {
        "finding_id": finding_id,
        "disposition": disposition,
        "user_priority": None,
        "reviewed": True,
        "user_comment": note,
        "title": "Local language convention",
    }


def check(result: str, anchor: str = "ANC-01") -> dict:
    return {
        "type": "claim_scope",
        "result": result,
        "anchor_ids": [anchor],
        "computation_ids": [],
        "notes": "The current manuscript was checked at the stated proposition and proof.",
    }


def build_package(*, include_response: bool = True) -> Path:
    root = Path(tempfile.mkdtemp(prefix="econ-review-round-"))

    prior = json.loads((FIXTURE / "findings.json").read_text(encoding="utf-8"))
    prior["review_id"] = "prior-review-001"
    prior_path = root / "evidence/prior-round/prior-findings.json"
    write_json(prior_path, prior)
    prior_fingerprint = digest(prior_path)

    logic_note = "Keep the correction narrow and preserve the main proposition."
    writing_note = "This wording follows the journal's required house style."
    actions = {
        "schema_version": "0.4",
        "kind": "econ-review-actions",
        "source_review_id": "prior-review-001",
        "source_review_fingerprint": prior_fingerprint,
        "source_manuscripts": [{"path": "paper.md", "sha256": None}],
        "exported_at": "2026-07-13T11:00:00Z",
        "entries": [
            action_entry("LOGIC-01", "ready_for_recheck", logic_note, "P0", 1),
            action_entry("WRT-01", "not_relevant", writing_note, None, 2),
        ],
    }
    write_json(root / "evidence/prior-round/review-actions.json", actions)

    tasks = {
        "schema_version": "0.1",
        "kind": "econ-review-revision-tasks",
        "plan_id": "00000000-0000-4000-8000-000000000000",
        "source_review_id": "prior-review-001",
        "source_review_fingerprint": prior_fingerprint,
        "generated_at": "2026-07-13T10:05:00Z",
        "all_comments_reviewed": True,
        "handoff_ready": True,
        "tasks": [plan_task("LOGIC-01", "ready_for_recheck", logic_note, "P0")],
        "excluded": [excluded_task("WRT-01", "not_relevant", writing_note)],
    }
    tasks["plan_id"] = HANDOFF.expected_plan_id(tasks)
    write_json(root / "evidence/prior-round/revision-tasks.json", tasks)

    if include_response:
        response = {
            "schema_version": "0.1",
            "kind": "econ-review-agent-response",
            "plan_id": tasks["plan_id"],
            "source_review_id": "prior-review-001",
            "source_review_fingerprint": prior_fingerprint,
            "responded_at": "2026-07-13T13:00:00Z",
            "entries": [{
                "finding_id": "LOGIC-01",
                "status": "changed",
                "response": "Qualified the proposition and proof.",
                "changed_files": ["paper.md"],
                "changed_locations": [{
                    "path": "paper.md",
                    "locator": "Proposition 1 and proof",
                    "summary": "Added the same boundary qualification in both places.",
                }],
                "verification": [{
                    "check": "Build manuscript",
                    "result": "passed",
                    "details": "The manuscript build completed.",
                }],
                "blocker": None,
            }],
        }
        write_json(root / "evidence/prior-round/agent-response.json", response)

    current = {
        "schema_version": "0.4",
        "review_id": "prior-review-001",
        "findings": [
            {
                "id": "LOGIC-01", "status": "open", "severity": "major",
                "importance_rank": 1,
                "title": "The boundary qualification remains incomplete",
            },
            {
                "id": "NEW-01", "status": "open", "severity": "minor",
                "importance_rank": 2,
                "title": "A new cross-reference points to the wrong proposition",
            },
        ],
    }
    write_json(root / "findings.json", current)
    run = {
        "schema_version": "0.4",
        "review_id": "prior-review-001",
        "prior_round": {
            "prior_findings_path": "evidence/prior-round/prior-findings.json",
            "review_actions_path": "evidence/prior-round/review-actions.json",
            "revision_tasks_path": "evidence/prior-round/revision-tasks.json",
            "agent_response_path": (
                "evidence/prior-round/agent-response.json" if include_response else None
            ),
        },
    }
    write_json(root / "run.json", run)
    write_json(root / "evidence/source-manifest.json", {
        "review_id": "prior-review-001",
        "anchors": [{"id": "ANC-01"}, {"id": "ANC-02"}],
    })
    write_json(root / "evidence/computations.json", {
        "review_id": "prior-review-001",
        "computations": [{"id": "CMP-01"}],
    })
    reconciliation = {
        "schema_version": "0.1",
        "review_id": "prior-review-001",
        "prior_review_id": "prior-review-001",
        "prior_findings_sha256": digest(root / "evidence/prior-round/prior-findings.json"),
        "review_actions_sha256": digest(root / "evidence/prior-round/review-actions.json"),
        "revision_tasks_sha256": digest(root / "evidence/prior-round/revision-tasks.json"),
        "agent_response_sha256": (
            digest(root / "evidence/prior-round/agent-response.json")
            if include_response else None
        ),
        "plan_id": tasks["plan_id"],
        "records": [
            {
                "prior_finding_id": "LOGIC-01",
                "adjudicated_by": "reviewer",
                "outcome": "unchanged",
                "successor_finding_ids": ["LOGIC-01"],
                "rationale": "The edit improves wording but does not resolve the boundary mismatch.",
                "checks": [check("failed")],
            },
            {
                "prior_finding_id": "WRT-01",
                "adjudicated_by": "reviewer",
                "outcome": "user_excluded",
                "successor_finding_ids": [],
                "rationale": "The stated house-style constraint makes the original comment inapplicable.",
                "checks": [check("passed", "ANC-02")],
            },
        ],
        "successor_consolidations": [],
        "new_finding_ids": ["NEW-01"],
    }
    write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
    (root / MODULE.RECONCILIATION_MD).write_text(
        render_round(root, reconciliation), encoding="utf-8"
    )
    return root


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def author_visible(markdown: str) -> str:
    return re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL)


def render_round(root: Path, reconciliation: dict | None = None) -> str:
    run = read_json(root / "run.json")
    activation = run["prior_round"]
    response_path = activation.get("agent_response_path")
    return MODULE.render(
        reconciliation or read_json(root / MODULE.RECONCILIATION_JSON),
        prior_findings=read_json(root / activation["prior_findings_path"]),
        current_findings=read_json(root / "findings.json"),
        revision_tasks=read_json(root / activation["revision_tasks_path"]),
        agent_response=(read_json(root / response_path) if response_path else None),
    )


def synchronize(root: Path, *, plan_changed: bool = False) -> None:
    run = read_json(root / "run.json")
    tasks_path = root / run["prior_round"]["revision_tasks_path"]
    tasks = read_json(tasks_path)
    if plan_changed:
        tasks["plan_id"] = HANDOFF.expected_plan_id(tasks)
        write_json(tasks_path, tasks)
        response_path = run["prior_round"]["agent_response_path"]
        if response_path is not None:
            response = read_json(root / response_path)
            response["plan_id"] = tasks["plan_id"]
            write_json(root / response_path, response)
    reconciliation_path = root / MODULE.RECONCILIATION_JSON
    reconciliation = read_json(reconciliation_path)
    reconciliation["plan_id"] = tasks["plan_id"]
    reconciliation["prior_findings_sha256"] = digest(
        root / run["prior_round"]["prior_findings_path"]
    )
    reconciliation["review_actions_sha256"] = digest(
        root / run["prior_round"]["review_actions_path"]
    )
    reconciliation["revision_tasks_sha256"] = digest(tasks_path)
    response_path = run["prior_round"]["agent_response_path"]
    reconciliation["agent_response_sha256"] = (
        digest(root / response_path) if response_path is not None else None
    )
    write_json(reconciliation_path, reconciliation)
    (root / MODULE.RECONCILIATION_MD).write_text(
        render_round(root, reconciliation), encoding="utf-8"
    )


def configure_many_to_one_consolidation(root: Path) -> None:
    actions_path = root / "evidence/prior-round/review-actions.json"
    tasks_path = root / "evidence/prior-round/revision-tasks.json"
    response_path = root / "evidence/prior-round/agent-response.json"
    actions = read_json(actions_path)
    writing_note = "Address this wording together with the proposition boundary issue."
    actions["entries"][1] = action_entry(
        "WRT-01", "ready_for_recheck", writing_note, "P1", 2
    )
    write_json(actions_path, actions)

    tasks = read_json(tasks_path)
    tasks["tasks"].append(
        plan_task("WRT-01", "ready_for_recheck", writing_note, "P1")
    )
    tasks["excluded"] = []
    write_json(tasks_path, tasks)

    response = read_json(response_path)
    response["entries"].append({
        "finding_id": "WRT-01",
        "status": "response_only",
        "response": "The wording was handled in the same consolidated revision.",
        "changed_files": [],
        "changed_locations": [],
        "verification": [],
        "blocker": None,
    })
    write_json(response_path, response)

    current = read_json(root / "findings.json")
    current["findings"][0]["id"] = "CONSOLIDATED-01"
    write_json(root / "findings.json", current)

    reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
    for record, anchor in zip(reconciliation["records"], ("ANC-01", "ANC-02")):
        record["outcome"] = "superseded"
        record["successor_finding_ids"] = ["CONSOLIDATED-01"]
        record["checks"] = [check("passed", anchor)]
    reconciliation["successor_consolidations"] = [{
        "successor_finding_id": "CONSOLIDATED-01",
        "prior_finding_ids": ["LOGIC-01", "WRT-01"],
        "rationale": "The revised paper exposes one shared boundary diagnosis that subsumes both prior comments.",
    }]
    write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
    synchronize(root, plan_changed=True)


def validate(root: Path) -> list[str]:
    return MODULE.validate_round_reconciliation(
        root,
        read_json(root / "run.json"),
        read_json(root / "findings.json"),
    )


class RoundReconciliationTests(unittest.TestCase):
    def package(self, *, include_response: bool = True) -> Path:
        root = build_package(include_response=include_response)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    def test_valid_reconciliation_passes_and_agent_status_does_not_decide_outcome(self) -> None:
        root = self.package()
        self.assertEqual(validate(root), [])
        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        self.assertEqual(reconciliation["records"][0]["outcome"], "unchanged")
        response = read_json(root / "evidence/prior-round/agent-response.json")
        self.assertEqual(response["entries"][0]["status"], "changed")

    def test_crlf_action_note_and_lf_task_note_pass_both_handoff_stages(self) -> None:
        root = self.package()
        actions_path = root / "evidence/prior-round/review-actions.json"
        tasks_path = root / "evidence/prior-round/revision-tasks.json"
        response_path = root / "evidence/prior-round/agent-response.json"
        prior_path = root / "evidence/prior-round/prior-findings.json"
        crlf_note = "Keep the correction narrow.\r\nPreserve the main proposition."
        lf_note = crlf_note.replace("\r\n", "\n")

        actions = read_json(actions_path)
        actions["entries"][0]["response_note"] = crlf_note
        next(
            event for event in actions["entries"][0]["events"]
            if event["type"] == "note_revised"
        )["note"] = crlf_note
        write_json(actions_path, actions)
        tasks = read_json(tasks_path)
        tasks["tasks"][0]["user_comment"] = lf_note
        write_json(tasks_path, tasks)
        synchronize(root, plan_changed=True)

        self.assertEqual(
            HANDOFF.validate(
                tasks_path,
                response_path,
                findings_path=prior_path,
                actions_path=actions_path,
            ),
            [],
        )
        self.assertEqual(validate(root), [])
        rendered = (root / MODULE.RECONCILIATION_MD).read_text(encoding="utf-8")
        self.assertIn(lf_note, rendered)
        self.assertNotIn("\r", rendered)

    def test_optional_agent_response_is_bound_as_null(self) -> None:
        root = self.package(include_response=False)
        self.assertEqual(validate(root), [])

    def test_hash_and_identity_mismatches_fail_closed(self) -> None:
        root = self.package()
        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        reconciliation["review_actions_sha256"] = "0" * 64
        reconciliation["prior_review_id"] = "wrong-review"
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(
            render_round(root, reconciliation), encoding="utf-8"
        )
        errors = validate(root)
        self.assertTrue(any("review_actions_sha256" in error for error in errors), errors)
        self.assertTrue(any("prior_review_id differs" in error for error in errors), errors)

    def test_next_round_must_retain_the_same_review_id(self) -> None:
        root = self.package()
        run = read_json(root / "run.json")
        run["review_id"] = "different-current-review"
        write_json(root / "run.json", run)
        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        reconciliation["review_id"] = "different-current-review"
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(
            render_round(root, reconciliation), encoding="utf-8"
        )
        errors = validate(root)
        self.assertTrue(any("must retain the prior review_id" in error for error in errors), errors)

    def test_plan_and_actions_must_partition_every_prior_active_finding(self) -> None:
        root = self.package()
        tasks = read_json(root / "evidence/prior-round/revision-tasks.json")
        tasks["excluded"] = []
        write_json(root / "evidence/prior-round/revision-tasks.json", tasks)
        synchronize(root, plan_changed=True)
        errors = validate(root)
        self.assertTrue(any("omit active source findings" in error for error in errors), errors)

        root = self.package()
        actions = read_json(root / "evidence/prior-round/review-actions.json")
        actions["entries"][0]["response_note"] = "A different instruction."
        note_event = next(
            event for event in actions["entries"][0]["events"]
            if event["type"] == "note_revised"
        )
        note_event["note"] = "A different instruction."
        write_json(root / "evidence/prior-round/review-actions.json", actions)
        synchronize(root)
        errors = validate(root)
        self.assertTrue(any("does not match the committed review action" in error for error in errors), errors)

    def test_plan_fingerprint_binds_semantic_prior_findings(self) -> None:
        root = self.package()
        actions_path = root / "evidence/prior-round/review-actions.json"
        tasks_path = root / "evidence/prior-round/revision-tasks.json"
        response_path = root / "evidence/prior-round/agent-response.json"
        actions = read_json(actions_path)
        tasks = read_json(tasks_path)
        response = read_json(response_path)
        wrong = "f" * 64
        actions["source_review_fingerprint"] = wrong
        tasks["source_review_fingerprint"] = wrong
        response["source_review_fingerprint"] = wrong
        tasks["plan_id"] = HANDOFF.expected_plan_id(tasks)
        response["plan_id"] = tasks["plan_id"]
        write_json(actions_path, actions)
        write_json(tasks_path, tasks)
        write_json(response_path, response)
        synchronize(root)
        errors = validate(root)
        self.assertTrue(any("source findings fingerprint does not match" in error for error in errors), errors)

    def test_known_inactive_action_entries_are_retained_but_unknown_entries_fail(self) -> None:
        root = self.package()
        prior_path = root / "evidence/prior-round/prior-findings.json"
        actions_path = root / "evidence/prior-round/review-actions.json"
        tasks_path = root / "evidence/prior-round/revision-tasks.json"
        response_path = root / "evidence/prior-round/agent-response.json"
        prior = read_json(prior_path)
        closed = copy.deepcopy(prior["findings"][1])
        closed["id"] = "CLOSED-01"
        closed["status"] = "resolved"
        prior["findings"].append(closed)
        write_json(prior_path, prior)
        fingerprint = digest(prior_path)
        actions = read_json(actions_path)
        actions["source_review_fingerprint"] = fingerprint
        actions["entries"].append(
            action_entry("CLOSED-01", "deferred", "Retained for audit history.", None, 3)
        )
        write_json(actions_path, actions)
        tasks = read_json(tasks_path)
        tasks["source_review_fingerprint"] = fingerprint
        tasks["plan_id"] = HANDOFF.expected_plan_id(tasks)
        write_json(tasks_path, tasks)
        response = read_json(response_path)
        response["source_review_fingerprint"] = fingerprint
        response["plan_id"] = tasks["plan_id"]
        write_json(response_path, response)
        synchronize(root)
        self.assertEqual(validate(root), [])

        actions["entries"].append(
            action_entry("UNKNOWN-01", "deferred", "This ID never existed.", None, 4)
        )
        write_json(actions_path, actions)
        synchronize(root)
        errors = validate(root)
        self.assertTrue(any("unknown prior finding IDs" in error for error in errors), errors)

    def test_resolved_and_partly_resolved_require_reviewer_closure_evidence(self) -> None:
        root = self.package()
        current = read_json(root / "findings.json")
        current["findings"] = [row for row in current["findings"] if row["id"] != "LOGIC-01"]
        write_json(root / "findings.json", current)
        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        record = reconciliation["records"][0]
        record["outcome"] = "resolved"
        record["successor_finding_ids"] = []
        record["checks"] = [check("passed")]
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(render_round(root, reconciliation), encoding="utf-8")
        self.assertEqual(validate(root), [])

        record["checks"] = [check("bounded")]
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(render_round(root, reconciliation), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("all closure checks to pass" in error for error in errors), errors)

        root = self.package()
        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        record = reconciliation["records"][0]
        record["outcome"] = "partly_resolved"
        record["checks"] = [check("passed"), check("bounded", "ANC-02")]
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(render_round(root, reconciliation), encoding="utf-8")
        self.assertEqual(validate(root), [])

    def test_superseded_needs_a_passed_check_and_user_exclusions_cannot_return(self) -> None:
        root = self.package()
        current = read_json(root / "findings.json")
        current["findings"][0]["id"] = "REPLACEMENT-01"
        write_json(root / "findings.json", current)
        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        record = reconciliation["records"][0]
        record["outcome"] = "superseded"
        record["successor_finding_ids"] = ["REPLACEMENT-01"]
        record["checks"] = [check("passed")]
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(render_round(root, reconciliation), encoding="utf-8")
        self.assertEqual(validate(root), [])

        record["checks"] = [check("bounded")]
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(render_round(root, reconciliation), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("requires at least one passed" in error for error in errors), errors)

        root = self.package()
        current = read_json(root / "findings.json")
        current["findings"].append({
            "id": "WRT-01", "status": "open", "severity": "minor", "importance_rank": 3,
        })
        write_json(root / "findings.json", current)
        errors = validate(root)
        self.assertTrue(any("user_excluded record WRT-01 cannot remain" in error for error in errors), errors)

        current["findings"] = [
            row for row in current["findings"] if row["id"] != "WRT-01"
        ]
        current["findings"].append({
            "id": "DIFFERENT-01", "status": "open", "severity": "major", "importance_rank": 3,
        })
        write_json(root / "findings.json", current)
        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        reconciliation["new_finding_ids"].append("DIFFERENT-01")
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(render_round(root, reconciliation), encoding="utf-8")
        self.assertEqual(validate(root), [])

    def test_deferred_rows_use_normal_reconciliation_not_exclusion_outcomes(self) -> None:
        root = self.package()
        actions = read_json(root / "evidence/prior-round/review-actions.json")
        actions["entries"][1] = action_entry(
            "WRT-01", "deferred", "Revisit after the substantive revision.", None, 2
        )
        write_json(root / "evidence/prior-round/review-actions.json", actions)
        tasks = read_json(root / "evidence/prior-round/revision-tasks.json")
        tasks["excluded"][0].update({
            "disposition": "deferred",
            "user_comment": "Revisit after the substantive revision.",
        })
        write_json(root / "evidence/prior-round/revision-tasks.json", tasks)
        current = read_json(root / "findings.json")
        current["findings"].append({
            "id": "WRT-01", "status": "open", "severity": "minor", "importance_rank": 3,
        })
        write_json(root / "findings.json", current)
        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        record = reconciliation["records"][1]
        record["outcome"] = "unchanged"
        record["successor_finding_ids"] = ["WRT-01"]
        record["checks"] = [check("bounded", "ANC-02")]
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        synchronize(root, plan_changed=True)
        self.assertEqual(validate(root), [])

        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        reconciliation["records"][1]["outcome"] = "user_excluded"
        reconciliation["records"][1]["successor_finding_ids"] = []
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(render_round(root, reconciliation), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("invalid for prior disposition deferred" in error for error in errors), errors)

    def test_every_current_finding_is_exactly_one_successor_or_new(self) -> None:
        root = self.package()
        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        reconciliation["new_finding_ids"] = []
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(render_round(root, reconciliation), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("absent from reconciliation" in error for error in errors), errors)

        reconciliation["new_finding_ids"] = ["LOGIC-01", "NEW-01"]
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(render_round(root, reconciliation), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("both successors and new" in error for error in errors), errors)
        self.assertTrue(any("must not reuse prior" in error for error in errors), errors)

    def test_explicit_many_to_one_successor_consolidation_is_valid(self) -> None:
        root = self.package()
        configure_many_to_one_consolidation(root)
        self.assertEqual(validate(root), [])
        rendered = (root / MODULE.RECONCILIATION_MD).read_text(encoding="utf-8")
        visible = author_visible(rendered)
        self.assertIn("## Comments combined in this review", visible)
        self.assertIn("### The boundary qualification remains incomplete", visible)
        self.assertIn("The global uniqueness claim fails at the equality boundary", visible)
        self.assertIn("The proposition summary has a subject-verb agreement error", visible)
        self.assertNotIn("CONSOLIDATED-01", visible)
        self.assertNotIn("LOGIC-01", visible)
        self.assertNotIn("WRT-01", visible)
        self.assertIn("<!-- successor_finding_id: CONSOLIDATED-01 -->", rendered)

    def test_repeated_successors_require_one_exact_unambiguous_consolidation(self) -> None:
        root = self.package()
        configure_many_to_one_consolidation(root)
        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        reconciliation["successor_consolidations"] = []
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(
            render_round(root, reconciliation), encoding="utf-8"
        )
        errors = validate(root)
        self.assertTrue(any("require an explicit successor consolidation" in error for error in errors), errors)

        reconciliation["successor_consolidations"] = [{
            "successor_finding_id": "CONSOLIDATED-01",
            "prior_finding_ids": ["LOGIC-01", "UNKNOWN-01"],
            "rationale": "This deliberately incomplete declaration must fail.",
        }]
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(
            render_round(root, reconciliation), encoding="utf-8"
        )
        errors = validate(root)
        self.assertTrue(any("unknown prior plan findings" in error for error in errors), errors)
        self.assertTrue(any("must list exactly the prior findings" in error for error in errors), errors)

        reconciliation["successor_consolidations"] = [
            {
                "successor_finding_id": "CONSOLIDATED-01",
                "prior_finding_ids": ["LOGIC-01", "WRT-01"],
                "rationale": "First declaration.",
            },
            {
                "successor_finding_id": "CONSOLIDATED-01",
                "prior_finding_ids": ["LOGIC-01", "WRT-01"],
                "rationale": "Ambiguous duplicate declaration.",
            },
        ]
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(
            render_round(root, reconciliation), encoding="utf-8"
        )
        errors = validate(root)
        self.assertTrue(any("repeats current finding CONSOLIDATED-01" in error for error in errors), errors)

    def test_current_anchor_and_computation_references_must_resolve(self) -> None:
        root = self.package()
        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        reconciliation["records"][0]["checks"][0]["anchor_ids"] = ["ANC-99"]
        reconciliation["records"][1]["checks"][0] = {
            "type": "calculation",
            "result": "passed",
            "anchor_ids": [],
            "computation_ids": ["CMP-99"],
            "notes": "The reported calculation was recomputed from current inputs.",
        }
        write_json(root / MODULE.RECONCILIATION_JSON, reconciliation)
        (root / MODULE.RECONCILIATION_MD).write_text(render_round(root, reconciliation), encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("unknown current anchors" in error for error in errors), errors)
        self.assertTrue(any("unknown current computations" in error for error in errors), errors)

    def test_markdown_is_deterministic_and_can_be_regenerated(self) -> None:
        root = self.package()
        markdown_path = root / MODULE.RECONCILIATION_MD
        markdown_path.write_text("stale\n", encoding="utf-8")
        errors = validate(root)
        self.assertTrue(any("not synchronized" in error for error in errors), errors)
        self.assertEqual(MODULE.write_markdown(root), [])
        self.assertEqual(validate(root), [])
        rendered = markdown_path.read_text(encoding="utf-8")
        visible = author_visible(rendered)
        self.assertTrue(rendered.startswith("# What Changed Since the Prior Review\n"))
        self.assertNotIn("SHA-256", visible)
        reconciliation = read_json(root / MODULE.RECONCILIATION_JSON)
        self.assertNotIn(reconciliation["prior_findings_sha256"], visible)
        self.assertIn("The global uniqueness claim fails at the equality boundary", visible)
        self.assertIn("The proposition asserts strict uniqueness", visible)
        self.assertIn("**Author's instruction**", visible)
        self.assertIn("Keep the correction narrow and preserve the main proposition.", visible)
        self.assertIn("**What the implementation agent reports**", visible)
        self.assertIn("The implementation agent reports making changes.", visible)
        self.assertIn("Qualified the proposition and proof.", visible)
        self.assertIn("**Locations reported as changed**", visible)
        self.assertIn("`paper.md` — Proposition 1 and proof", visible)
        self.assertIn("**Reviewer's conclusion**", visible)
        self.assertIn("The concern remains unresolved.", visible)
        self.assertIn("The boundary qualification remains incomplete", visible)
        self.assertIn("A new cross-reference points to the wrong proposition", visible)
        self.assertNotIn("Build manuscript", visible)
        response = read_json(root / "evidence/prior-round/agent-response.json")
        self.assertNotIn(response["source_review_fingerprint"], visible)
        self.assertNotIn(response["plan_id"], visible)
        for internal in (
            "LOGIC-01", "WRT-01", "NEW-01", "ANC-01", "CMP-01",
            "reviewer_outcome", "agent_status", "anchor_ids", "computation_ids",
            "ready_for_recheck", "user_excluded", "unchanged",
        ):
            self.assertNotIn(internal, visible)
        self.assertIn("<!-- prior_finding_id: LOGIC-01 -->", rendered)
        self.assertIn("<!-- reviewer_outcome: unchanged -->", rendered)
        self.assertIn("<!-- agent_status: changed -->", rendered)
        self.assertIn("anchor_ids=ANC-01", rendered)
        self.assertIn("<!-- new_finding_id: NEW-01 -->", rendered)

    def test_finalizer_writes_reconciliation_before_reports_and_checks_it_in_place(self) -> None:
        root = self.package()
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(FINALIZER.subprocess, "run", return_value=completed) as invoked:
            FINALIZER.run_generators(root, check=False)
        commands = [call.args[0] for call in invoked.call_args_list]
        names = [Path(command[1]).name for command in commands]
        self.assertLess(names.index("round_reconciliation.py"), names.index("generate_reports.py"))
        round_command = commands[names.index("round_reconciliation.py")]
        self.assertEqual(round_command[-1], "--write")

        with mock.patch.object(FINALIZER.subprocess, "run", return_value=completed) as invoked:
            FINALIZER.run_generators(root, check=True)
        commands = [call.args[0] for call in invoked.call_args_list]
        names = [Path(command[1]).name for command in commands]
        round_command = commands[names.index("round_reconciliation.py")]
        report_command = commands[names.index("generate_reports.py")]
        self.assertNotIn("--write", round_command)
        self.assertNotIn("--check", round_command)
        self.assertEqual(report_command[-1], "--check")

    def test_run_schema_allows_activation_only_for_v04_and_safe_paths(self) -> None:
        schema = json.loads(RUN_SCHEMA.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
        run["prior_round"] = {
            "prior_findings_path": "evidence/prior-round/findings.json",
            "review_actions_path": "evidence/prior-round/review-actions.json",
            "revision_tasks_path": "evidence/prior-round/revision-tasks.json",
            "agent_response_path": None,
        }
        self.assertEqual(list(validator.iter_errors(run)), [])
        legacy = copy.deepcopy(run)
        legacy["schema_version"] = "0.3"
        self.assertTrue(list(validator.iter_errors(legacy)))
        unsafe = copy.deepcopy(run)
        unsafe["prior_round"]["prior_findings_path"] = "../findings.json"
        self.assertTrue(list(validator.iter_errors(unsafe)))
        nested = copy.deepcopy(run)
        nested["prior_round"]["prior_findings_path"] = (
            "evidence/prior-round/nested/findings.json"
        )
        self.assertTrue(list(validator.iter_errors(nested)))

    def test_main_review_validator_activates_reconciliation_and_requires_both_artifacts(self) -> None:
        temporary = Path(tempfile.mkdtemp(prefix="econ-review-round-integration-"))
        self.addCleanup(shutil.rmtree, temporary, ignore_errors=True)
        target = temporary / "review"
        shutil.copytree(FIXTURE, target)
        run = read_json(target / "run.json")
        run["prior_round"] = {
            "prior_findings_path": "evidence/prior-round/findings.json",
            "review_actions_path": "evidence/prior-round/review-actions.json",
            "revision_tasks_path": "evidence/prior-round/revision-tasks.json",
            "agent_response_path": None,
        }
        write_json(target / "run.json", run)
        with mock.patch.object(
            REVIEW_VALIDATOR,
            "validate_round_reconciliation",
            return_value=["round-reconciliation sentinel"],
        ) as reconcile:
            errors = REVIEW_VALIDATOR.validate_review(target)
        reconcile.assert_called_once()
        self.assertIn("round-reconciliation sentinel", errors)
        self.assertTrue(any(
            "complete run missing audit artifact: evidence/round-reconciliation.json" in error
            for error in errors
        ), errors)
        self.assertTrue(any(
            "complete run missing audit artifact: evidence/round-reconciliation.md" in error
            for error in errors
        ), errors)
        self.assertTrue(any(
            "review-manifest.json must declare evidence/round-reconciliation.md" in error
            for error in errors
        ), errors)


if __name__ == "__main__":
    unittest.main()
