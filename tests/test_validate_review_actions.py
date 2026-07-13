from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "validate_review_actions.py"
SPEC = importlib.util.spec_from_file_location("validate_review_actions", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def payload() -> dict:
    return {
        "schema_version": "0.1",
        "kind": "econ-review-actions",
        "source_review_id": "review-001",
        "source_review_fingerprint": "ledger-v1",
        "source_manuscripts": [{"path": "paper.md", "sha256": None}],
        "exported_at": "2026-07-12T14:00:00Z",
        "entries": [{
            "finding_id": "LOGIC-01",
            "disposition": "ready_for_recheck",
            "response_note": "Revised Proposition 1.",
            "changed_locations": ["Proposition 1"],
            "updated_at": "2026-07-12T13:00:00Z",
            "status_history": [
                {"disposition": "open", "at": "2026-07-12T12:00:00Z"},
                {"disposition": "ready_for_recheck", "at": "2026-07-12T13:00:00Z"},
            ],
        }],
    }


def payload_v03() -> dict:
    value = payload()
    value["schema_version"] = "0.3"
    value["entries"][0]["events"] = [
        {
            "event_id": "00000000-0000-4000-8000-000000000001",
            "type": "imported",
            "at": "2026-07-12T11:59:00Z",
            "parent_event_id": None,
            "origin": "import",
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000002",
            "type": "disposition_changed",
            "at": "2026-07-12T12:00:00Z",
            "disposition": "open",
            "parent_event_id": "00000000-0000-4000-8000-000000000001",
            "origin": "local",
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000003",
            "type": "note_revised",
            "at": "2026-07-12T12:30:00Z",
            "note": "Revised Proposition 1.",
            "parent_event_id": "00000000-0000-4000-8000-000000000002",
            "origin": "local",
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000004",
            "type": "disposition_changed",
            "at": "2026-07-12T13:00:00Z",
            "disposition": "ready_for_recheck",
            "parent_event_id": "00000000-0000-4000-8000-000000000003",
            "origin": "local",
        },
    ]
    return value


class ReviewActionsValidationTests(unittest.TestCase):
    def run_payload(self, value: dict) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review-actions.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return MODULE.validate(path)

    def test_valid_handoff_passes(self) -> None:
        self.assertEqual(self.run_payload(payload()), [])

    def test_duplicate_ids_fail(self) -> None:
        value = payload()
        value["entries"].append(dict(value["entries"][0]))
        self.assertTrue(any("duplicate finding IDs" in error for error in self.run_payload(value)))

    def test_final_history_must_match_disposition(self) -> None:
        value = payload()
        value["entries"][0]["disposition"] = "challenged"
        self.assertTrue(any("differs from final history" in error for error in self.run_payload(value)))

    def test_updates_cannot_postdate_export(self) -> None:
        value = payload()
        value["entries"][0]["updated_at"] = "2026-07-12T15:00:00Z"
        self.assertTrue(any("later than exported_at" in error for error in self.run_payload(value)))

    def test_duplicate_source_paths_fail(self) -> None:
        value = payload()
        value["source_manuscripts"].append({"path": "paper.md", "sha256": None})
        self.assertTrue(any("duplicate source manuscript paths" in error for error in self.run_payload(value)))

    def test_source_paths_cannot_collide_by_case(self) -> None:
        value = payload()
        value["source_manuscripts"].append({"path": "PAPER.md", "sha256": None})
        self.assertTrue(any("collide by case" in error for error in self.run_payload(value)))

    def test_history_must_be_chronological(self) -> None:
        value = payload()
        value["entries"][0]["status_history"].reverse()
        self.assertTrue(any("not chronological" in error for error in self.run_payload(value)))

    def test_schema_accepted_noncanonical_datetime_cannot_skip_semantic_checks(self) -> None:
        value = payload_v03()
        value["exported_at"] = value["exported_at"].replace("T", "t").replace("Z", "z")
        errors = self.run_payload(value)
        self.assertTrue(any("semantic action validation failed" in error for error in errors), errors)
        self.assertTrue(any("uppercase T and uppercase Z" in error for error in errors), errors)

    def test_identity_paths_and_locations_must_be_nonblank_trimmed_text(self) -> None:
        mutations = [
            lambda value: value.update(source_review_id="   "),
            lambda value: value.update(source_review_fingerprint=" fingerprint "),
            lambda value: value["source_manuscripts"][0].update(path=" paper.md "),
            lambda value: value["entries"][0].update(changed_locations=["   "]),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                value = payload()
                mutate(value)
                self.assertTrue(any("schema violation" in error for error in self.run_payload(value)))

    def test_recheck_claim_allows_optional_note(self) -> None:
        value = payload()
        value["schema_version"] = "0.2"
        value["entries"][0]["response_note"] = ""
        value["entries"][0]["changed_locations"] = []
        self.assertEqual(self.run_payload(value), [])

    def test_legacy_recheck_still_requires_evidence(self) -> None:
        value = payload()
        value["entries"][0]["response_note"] = ""
        value["entries"][0]["changed_locations"] = []
        self.assertTrue(any("schema violation" in error for error in self.run_payload(value)))

    def test_challenge_allows_optional_explanation(self) -> None:
        value = payload()
        value["schema_version"] = "0.2"
        entry = value["entries"][0]
        entry["disposition"] = "challenged"
        entry["response_note"] = ""
        entry["status_history"][-1]["disposition"] = "challenged"
        self.assertEqual(self.run_payload(value), [])

    def test_v03_append_only_event_log_passes(self) -> None:
        self.assertEqual(self.run_payload(payload_v03()), [])

    def test_v03_requires_events(self) -> None:
        value = payload_v03()
        value["entries"][0].pop("events")
        self.assertTrue(any("events" in error for error in self.run_payload(value)))

    def test_v03_replayed_state_must_match_compatibility_fields(self) -> None:
        value = payload_v03()
        value["entries"][0]["response_note"] = "Different note"
        self.assertTrue(any("response_note differs from replayed events" in error for error in self.run_payload(value)))

    def test_v03_parent_must_reference_preceding_event(self) -> None:
        value = payload_v03()
        value["entries"][0]["events"][3]["parent_event_id"] = (
            "00000000-0000-4000-8000-000000000001"
        )
        self.assertTrue(any("must reference the preceding event" in error for error in self.run_payload(value)))

    def test_v03_event_ids_are_globally_unique_across_findings(self) -> None:
        value = payload_v03()
        second = json.loads(json.dumps(value["entries"][0]))
        second["finding_id"] = "LOGIC-02"
        value["entries"].append(second)
        errors = self.run_payload(value)
        self.assertTrue(any("globally unique across entries" in error for error in errors), errors)

    def test_v03_import_event_is_provenance_only(self) -> None:
        value = payload_v03()
        value["entries"][0]["events"][0]["disposition"] = "open"
        self.assertTrue(any("schema violation" in error for error in self.run_payload(value)))

    def test_source_manuscript_path_must_be_portable(self) -> None:
        for bad_path in (
            "/Users/person/private/paper.pdf",
            "C:/private/paper.pdf",
            "../paper.pdf",
            "folder\\paper.pdf",
            "folder/name:stream.pdf",
            "folder/e\u0301.pdf",
            "folder/trailing.",
        ):
            with self.subTest(path=bad_path):
                value = payload()
                value["source_manuscripts"][0]["path"] = bad_path
                self.assertTrue(self.run_payload(value))

    def test_oversized_handoff_is_rejected_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review-actions.json"
            path.write_bytes(b" " * (MODULE.MAX_ACTIONS_BYTES + 1))
            self.assertTrue(any("exceeds" in error for error in MODULE.validate(path)))

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review-actions.json"
            rendered = json.dumps(payload())
            path.write_text(
                rendered.replace(
                    '{',
                    '{"source_review_id":"shadow",',
                    1,
                ),
                encoding="utf-8",
            )
            errors = MODULE.validate(path)
            self.assertTrue(any("duplicate JSON key: source_review_id" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
