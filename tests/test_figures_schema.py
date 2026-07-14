#!/usr/bin/env python3
"""Focused compatibility and integrity tests for the figure-audit schema."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "econ-review" / "assets" / "figures.schema.json"
LEGACY_FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "valid-review" / "evidence" / "figures.json"
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class FigureAuditSchemaTests(unittest.TestCase):
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
    def valid_v02_payload() -> dict:
        return {
            "schema_version": "0.2",
            "review_id": "schema-test",
            "source_render": "Rendered manuscript",
            "inventory_complete_within_assessment_boundary": True,
            "no_figures_confirmed": False,
            "figures": [
                {
                    "id": "FIG-01",
                    "source_id": "SRC-01",
                    "coverage_unit_id": "U-FIG-01",
                    "label": "Figure 1: Synthetic relationship",
                    "pdf_pages": [4],
                    "source_locator": {
                        "source_id": "SRC-01",
                        "pages": [4],
                        "context": "Rendered manuscript page containing the figure.",
                    },
                    "identity_keys": [
                        "Figure 1",
                        "Synthetic relationship",
                        "Outcome",
                        "Treatment group",
                    ],
                    "rendered_assets": [
                        {
                            "path": "evidence/renders/pages/page-04.png",
                            "sha256": "a" * 64,
                            "pdf_page": 4,
                            "render_type": "full_page",
                            "source_object_id": None,
                            "visible_identity": {
                                "basis": "figure_label",
                                "text": "Figure 1: Synthetic relationship",
                                "status": "matched",
                                "notes": "The visible label and caption agree with the audit row.",
                            },
                        },
                        {
                            "path": "evidence/figures/fig-01.png",
                            "sha256": "b" * 64,
                            "pdf_page": 4,
                            "render_type": "crop",
                            "source_object_id": "SRC-01-PDF-FIG-001",
                            "visible_identity": {
                                "basis": "panel_or_axis_text",
                                "text": "Outcome; Treatment group",
                                "status": "matched",
                                "notes": "The axes and panel structure match the full-page render.",
                            },
                        },
                    ],
                    "kind": "plot",
                    "visual_status": "clear",
                    "caption_text_status": "consistent",
                    "claim_correspondence_status": "consistent",
                    "checks": {
                        "axes_scales_units": "Axes, scales, and units were checked.",
                        "legend_series_panels": "Series and panel identities were checked.",
                        "uncertainty": "The uncertainty display was checked.",
                        "legibility_accessibility": "Legibility and accessibility were checked.",
                        "visual_integrity": "The visual encoding was checked for distortion.",
                    },
                    "assessment_boundary": None,
                    "finding_ids": [],
                    "notes": "Both immutable assets were opened and reconciled.",
                }
            ],
            "boundary_notes": "The synthetic figure inventory is complete.",
        }

    def test_schema_is_valid_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(self.schema)

    def test_v01_fixture_remains_valid(self) -> None:
        fixture = load_json(LEGACY_FIXTURE_PATH)
        self.assertEqual("0.1", fixture["schema_version"])
        self.assert_valid(fixture)

    def test_no_figure_fixture_is_v02_compatible_without_row_changes(self) -> None:
        fixture = load_json(LEGACY_FIXTURE_PATH)
        fixture["schema_version"] = "0.2"
        self.assertEqual([], fixture["figures"])
        self.assert_valid(fixture)

    def test_v02_hashed_full_page_and_crop_assets_are_valid(self) -> None:
        self.assert_valid(self.valid_v02_payload())

    def test_v02_requires_coverage_unit_binding(self) -> None:
        payload = self.valid_v02_payload()
        del payload["figures"][0]["coverage_unit_id"]
        self.assert_invalid(payload)

    def test_v02_requires_structured_source_binding(self) -> None:
        payload = self.valid_v02_payload()
        del payload["figures"][0]["source_id"]
        self.assert_invalid(payload)

    def test_v02_requires_identity_keys(self) -> None:
        payload = self.valid_v02_payload()
        del payload["figures"][0]["identity_keys"]
        self.assert_invalid(payload)

    def test_v02_requires_sha256_for_every_asset(self) -> None:
        payload = self.valid_v02_payload()
        del payload["figures"][0]["rendered_assets"][1]["sha256"]
        self.assert_invalid(payload)

    def test_v02_requires_source_object_binding_field_for_every_asset(self) -> None:
        payload = self.valid_v02_payload()
        del payload["figures"][0]["rendered_assets"][1]["source_object_id"]
        self.assert_invalid(payload)

    def test_v02_full_page_source_object_id_must_be_null(self) -> None:
        payload = self.valid_v02_payload()
        payload["figures"][0]["rendered_assets"][0]["source_object_id"] = (
            "SRC-01-PDF-FIG-001"
        )
        self.assert_invalid(payload)

    def test_v02_requires_structured_source_locator(self) -> None:
        payload = self.valid_v02_payload()
        payload["figures"][0]["source_locator"] = "Rendered PDF page 4"
        self.assert_invalid(payload)

    def test_v02_requires_explicit_assessment_boundary_state(self) -> None:
        payload = self.valid_v02_payload()
        del payload["figures"][0]["assessment_boundary"]
        self.assert_invalid(payload)

    def test_v02_rejects_malformed_sha256(self) -> None:
        payload = self.valid_v02_payload()
        payload["figures"][0]["rendered_assets"][0]["sha256"] = "not-a-digest"
        self.assert_invalid(payload)

    def test_v02_rejects_parent_traversal_in_asset_path(self) -> None:
        payload = self.valid_v02_payload()
        payload["figures"][0]["rendered_assets"][0]["path"] = "../outside.png"
        self.assert_invalid(payload)

    def test_v02_rejects_nonportable_asset_paths(self) -> None:
        for unsafe_path in (
            "..\\outside.png",
            "C:\\outside.png",
            "\\\\server\\share.png",
            "file://outside.png",
            "\x00.png",
        ):
            with self.subTest(path=unsafe_path):
                payload = self.valid_v02_payload()
                payload["figures"][0]["rendered_assets"][0]["path"] = unsafe_path
                self.assert_invalid(payload)

    def test_v02_requires_at_least_one_full_page_asset(self) -> None:
        payload = self.valid_v02_payload()
        for asset in payload["figures"][0]["rendered_assets"]:
            asset["render_type"] = "crop"
        self.assert_invalid(payload)

    def test_v02_requires_complete_visible_identity(self) -> None:
        payload = self.valid_v02_payload()
        del payload["figures"][0]["rendered_assets"][0]["visible_identity"]["text"]
        self.assert_invalid(payload)

    def test_v02_rejects_legacy_extraction_paths(self) -> None:
        payload = self.valid_v02_payload()
        payload["figures"][0]["extraction_paths"] = ["evidence/figures/fig-01.png"]
        self.assert_invalid(payload)

    def test_v01_does_not_accept_v02_row_contract(self) -> None:
        payload = copy.deepcopy(self.valid_v02_payload())
        payload["schema_version"] = "0.1"
        self.assert_invalid(payload)


if __name__ == "__main__":
    unittest.main()
