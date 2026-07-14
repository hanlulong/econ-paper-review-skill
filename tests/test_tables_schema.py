#!/usr/bin/env python3
"""Compatibility and immutable-render tests for the table-audit schema."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "econ-review" / "assets" / "tables.schema.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "valid-review" / "evidence" / "tables.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TableAuditSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def assert_valid(self, payload: dict) -> None:
        errors = sorted(self.validator.iter_errors(payload), key=lambda error: list(error.path))
        self.assertEqual([], errors, "\n".join(error.message for error in errors))

    def assert_invalid(self, payload: dict) -> None:
        self.assertTrue(list(self.validator.iter_errors(payload)))

    @staticmethod
    def checks() -> dict:
        return {
            name: {"status": "clear", "result": "The rendered table was checked."}
            for name in (
                "number_title_panels", "row_column_alignment", "cell_completeness",
                "units_transformations", "sample_denominator_support", "uncertainty_inference",
                "definitions_sources", "cross_table_consistency", "calculation_traceability",
                "text_claim_reconciliation",
            )
        }

    @classmethod
    def valid_v02_payload(cls) -> dict:
        return {
            "schema_version": "0.2",
            "review_id": "schema-test",
            "source": "Rendered manuscript",
            "inventory_complete_within_assessment_boundary": True,
            "no_tables_confirmed": False,
            "tables": [{
                "id": "TBL-01",
                "source_id": "SRC-01",
                "coverage_unit_id": "U-TBL-01",
                "label": "Table 1: Synthetic results",
                "pdf_pages": [7],
                "source_locator": {
                    "source_id": "SRC-01",
                    "pages": [7],
                    "context": "Rendered manuscript page containing the table.",
                },
                "identity_keys": ["Table 1", "Synthetic results", "Outcome"],
                "rendered_assets": [
                    {
                        "path": "evidence/renders/pages/page-07.png",
                        "sha256": "a" * 64,
                        "pdf_page": 7,
                        "render_type": "full_page",
                        "source_object_id": None,
                        "visible_identity": {
                            "basis": "table_label",
                            "text": "Table 1: Synthetic results",
                            "status": "matched",
                            "notes": "The visible table label matches the audit row.",
                        },
                    },
                    {
                        "path": "evidence/renders/tables/table-01.png",
                        "sha256": "b" * 64,
                        "pdf_page": 7,
                        "render_type": "crop",
                        "source_object_id": "SRC-01-PDF-TBL-001",
                        "visible_identity": {
                            "basis": "panel_or_header_text",
                            "text": "Outcome",
                            "status": "matched",
                            "notes": "The retained crop shows the declared table header.",
                        },
                    },
                ],
                "render_status": "inspected",
                "extraction_status": "consistent",
                "visual_status": "clear",
                "claim_correspondence_status": "consistent",
                "checks": cls.checks(),
                "assessment_boundary": None,
                "finding_ids": [],
                "notes": "The immutable page and crop assets were inspected.",
            }],
            "boundary_notes": "The rendered table inventory is complete.",
        }

    def test_schema_is_valid_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(self.schema)

    def test_current_empty_fixture_is_valid(self) -> None:
        fixture = load_json(FIXTURE_PATH)
        self.assertEqual("0.2", fixture["schema_version"])
        self.assert_valid(fixture)

    def test_legacy_empty_fixture_remains_valid(self) -> None:
        fixture = load_json(FIXTURE_PATH)
        fixture["schema_version"] = "0.1"
        self.assert_valid(fixture)

    def test_v02_hashed_page_and_crop_assets_are_valid(self) -> None:
        self.assert_valid(self.valid_v02_payload())

    def test_v02_bounded_row_may_preserve_an_explicit_empty_asset_inventory(self) -> None:
        payload = self.valid_v02_payload()
        row = payload["tables"][0]
        row["render_status"] = "bounded"
        row["visual_status"] = "bounded"
        row["rendered_assets"] = []
        row["assessment_boundary"] = {
            "checked_scope": "The available table locator and surrounding prose.",
            "status_basis": "unavailable_source",
            "reason": "No retained table render was available.",
            "missing_input": "A complete render of Table 1.",
            "decisive_evidence_needed": "The source page containing Table 1.",
        }
        self.assert_valid(payload)

    def test_v02_inspected_row_requires_an_asset(self) -> None:
        payload = self.valid_v02_payload()
        payload["tables"][0]["rendered_assets"] = []
        self.assert_invalid(payload)

    def test_v02_requires_source_and_structured_locator_bindings(self) -> None:
        for field in ("source_id", "source_locator", "identity_keys", "assessment_boundary"):
            with self.subTest(field=field):
                payload = self.valid_v02_payload()
                del payload["tables"][0][field]
                self.assert_invalid(payload)

    def test_v02_requires_hash_role_page_and_object_fields(self) -> None:
        for field in ("sha256", "render_type", "pdf_page", "source_object_id", "visible_identity"):
            with self.subTest(field=field):
                payload = self.valid_v02_payload()
                del payload["tables"][0]["rendered_assets"][1][field]
                self.assert_invalid(payload)

    def test_v02_full_page_cannot_claim_a_source_object(self) -> None:
        payload = self.valid_v02_payload()
        payload["tables"][0]["rendered_assets"][0]["source_object_id"] = "SRC-01-PDF-TBL-001"
        self.assert_invalid(payload)

    def test_v02_rejects_nonportable_asset_paths(self) -> None:
        for unsafe_path in (
            "../outside.png", "./inside.png", "a//b.png", "..\\outside.png",
            "C:\\outside.png", "\\\\server\\share.png", "file://outside.png", "\x00.png",
        ):
            with self.subTest(path=unsafe_path):
                payload = self.valid_v02_payload()
                payload["tables"][0]["rendered_assets"][0]["path"] = unsafe_path
                self.assert_invalid(payload)

    def test_v02_rejects_legacy_render_paths(self) -> None:
        payload = self.valid_v02_payload()
        payload["tables"][0]["render_paths"] = ["evidence/renders/tables/table-01.png"]
        self.assert_invalid(payload)

    def test_v01_does_not_accept_v02_rows(self) -> None:
        payload = copy.deepcopy(self.valid_v02_payload())
        payload["schema_version"] = "0.1"
        self.assert_invalid(payload)


if __name__ == "__main__":
    unittest.main()
