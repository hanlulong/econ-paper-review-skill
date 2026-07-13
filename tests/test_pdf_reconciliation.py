#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "pdf_reconciliation", ROOT / "econ-review/scripts/pdf_reconciliation.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PdfReconciliationTests(unittest.TestCase):
    def fixture(self):
        page = {
            "page": 1, "status": "extracted", "text_method": "pdf_text_layer",
            "render_path": "evidence/render.png", "render_sha256": "a" * 64,
            "text_path": "evidence/native.txt", "text_sha256": "b" * 64,
            "native_text_path": "evidence/native.txt", "native_text_sha256": "b" * 64,
            "ocr_text_path": None, "ocr_text_sha256": None,
            "width_points": 612, "height_points": 792,
            "replacement_character_count": 0, "private_use_character_count": 0,
        }
        blocks = [{
            "id": "SRC-01-PDF-B0001", "page": 1, "confidence": "high",
            "kind": "paragraph", "bbox": [10, 10, 200, 40], "raw_text": "Evidence text",
        }]
        equations = [{
            "id": "SRC-01-PDF-EQ-001", "page": 1, "bbox": [10, 20, 100, 50],
            "caption": None, "crop_path": "evidence/equation.png", "crop_sha256": "f" * 64,
            "status": "bounded", "transcription": None,
        }]
        proposals = [{
            "id": "PRP-DOCLING", "engine": "docling", "role": "semantic_structure",
            "artifacts": [{
                "path": "evidence/proposals/docling/document.json",
                "sha256": "c" * 64, "media_type": "application/json",
            }],
        }]
        packets = MODULE.build_page_packets(
            source_sha256="d" * 64, pages=[page], blocks=blocks,
            tables=[], figures=[], equations=equations, proposals=proposals,
            proposal_page_index={
                "PRP-DOCLING": {1: {
                    "page": 1, "width": 612, "height": 792,
                    "elements": [{
                        "id": "docling:text:0", "type": "text",
                        "bbox": [10, 10, 200, 40], "text": "Evidence text",
                    }],
                }},
            },
        )
        manifest = {
            "source": {"sha256": "d" * 64}, "pages": [page], "blocks": blocks,
            "tables": [], "figures": [], "equations": equations, "proposals": proposals,
            "reconciliation": {"packets_sha256": "9" * 64},
        }
        return packets, manifest

    def test_packets_route_objects_to_render_without_automatic_promotion(self) -> None:
        packets, manifest = self.fixture()
        self.assertEqual(packets["authority"], "page_render")
        self.assertEqual(packets["canonical_policy"], "no_automatic_promotion")
        self.assertTrue(packets["pages"][0]["adjudication_required"])
        self.assertIn("structured_or_visual_objects", packets["pages"][0]["routing_reasons"])
        self.assertTrue(packets["pages"][0]["targets"][0]["backend_candidates"][0]["exact_text"])
        self.assertEqual(MODULE.packet_errors(packets, manifest), [])

    def test_packet_manifest_cross_check_rejects_tampered_references(self) -> None:
        packets, manifest = self.fixture()
        packets["pages"][0]["render"]["sha256"] = "e" * 64
        packets["proposal_catalog"][0]["artifacts"][0]["path"] = "evidence/wrong.json"
        errors = MODULE.packet_errors(packets, manifest)
        self.assertTrue(any("render differs" in error for error in errors))
        self.assertTrue(any("catalog metadata differs" in error for error in errors))

    def test_decision_ledger_requires_render_and_object_crop_evidence(self) -> None:
        packets, manifest = self.fixture()
        decisions = {
            "schema_version": "0.1", "source_sha256": "d" * 64,
            "packets_sha256": "9" * 64, "protocol_version": "render-adjudication-v1",
            "created_at": "2026-07-12T22:00:00Z", "scope_status": "verified_scope",
            "decisions": [{
                "target_id": "SRC-01-PDF-EQ-001", "page": 1,
                "state": "render_verified", "evidence_hashes": ["a" * 64, "f" * 64],
                "transcription": "x = 1", "alternatives": [], "unreadable_regions": [],
                "verifier": {"kind": "model", "name": "visual verifier", "version": "1"},
                "verification_note": "Compared every sign and subscript with the saved crop.",
            }],
            "summary": {"model_adjudicated": 0, "render_verified": 1, "bounded": 0},
        }
        self.assertEqual(MODULE.decision_errors(decisions, manifest, packets), [])
        decisions["decisions"][0]["evidence_hashes"] = ["a" * 64]
        errors = MODULE.decision_errors(decisions, manifest, packets)
        self.assertTrue(any("omits its crop" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
