#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import tempfile
import unittest
from difflib import SequenceMatcher as LegacySequenceMatcher
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "pdf_reconciliation.py"
SPEC = importlib.util.spec_from_file_location("pdf_reconciliation", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def legacy_block_candidate(
    block: dict, proposal_id: str, proposal_page: dict, page: dict,
    *, prepared_elements: object = None,
) -> dict | None:
    """Frozen pre-optimization matcher used only for output-equivalence tests."""
    del prepared_elements
    canonical = MODULE._text_key(block["raw_text"])
    ranked: list[tuple[float, float, dict, list[float] | None]] = []
    for element in proposal_page.get("elements", []):
        if not isinstance(element, dict):
            continue
        text = MODULE._text_key(str(element.get("text") or ""))
        bbox = MODULE._scaled_bbox(element, proposal_page, page)
        overlap = MODULE._overlap_ratio(block["bbox"], bbox) if bbox else 0.0
        similarity = (
            LegacySequenceMatcher(None, canonical, text, autojunk=False).ratio()
            if canonical or text else 1.0
        )
        if overlap > 0 or similarity >= 0.35:
            ranked.append((overlap, similarity, element, bbox))
    if not ranked:
        return None
    overlap, similarity, element, bbox = max(
        ranked, key=lambda row: (row[0] >= 0.25, row[0], row[1]),
    )
    text = str(element.get("text") or "")
    return {
        "proposal_id": proposal_id,
        "element_id": element.get("id"),
        "type": element.get("type"),
        "bbox": bbox,
        "text": text,
        "exact_text": MODULE._text_key(text) == canonical,
        "text_similarity": round(similarity, 4),
        "target_overlap": overlap,
        "critical_tokens": MODULE._critical_tokens(text),
        "critical_tokens_match": (
            MODULE._critical_tokens(text) == MODULE._critical_tokens(block["raw_text"])
        ),
    }


def packet_fixture() -> dict:
    pages = [
        {
            "page": 1,
            "width_points": 100.0,
            "height_points": 100.0,
            "status": "ready",
            "render_path": "renders/page-0001.png",
            "render_sha256": "r1",
            "text_path": "pages/page-0001.txt",
            "text_sha256": "t1",
            "text_method": "native",
            "native_text_path": "pages/page-0001.native.txt",
            "native_text_sha256": "n1",
            "ocr_text_path": None,
            "ocr_text_sha256": None,
            "replacement_character_count": 0,
            "private_use_character_count": 0,
        },
        {
            "page": 2,
            "width_points": 100.0,
            "height_points": 100.0,
            "status": "bounded",
            "render_path": "renders/page-0002.png",
            "render_sha256": "r2",
            "text_path": "pages/page-0002.txt",
            "text_sha256": "t2",
            "text_method": "none",
            "native_text_path": "pages/page-0002.native.txt",
            "native_text_sha256": "n2",
            "ocr_text_path": "pages/page-0002.ocr.txt",
            "ocr_text_sha256": "o2",
            "replacement_character_count": 1,
            "private_use_character_count": 0,
        },
    ]
    blocks = [
        {
            "id": "BLOCK-01", "page": 1, "kind": "paragraph",
            "bbox": [0.0, 0.0, 20.0, 10.0], "raw_text": "Estimate = -1.25",
            "confidence": "high",
        },
        {
            "id": "BLOCK-02", "page": 1, "kind": "paragraph",
            "bbox": [0.0, 20.0, 20.0, 30.0], "raw_text": "alpha beta gamma",
            "confidence": "high",
        },
        {
            "id": "BLOCK-03", "page": 1, "kind": "paragraph",
            "bbox": [0.0, 40.0, 20.0, 50.0], "raw_text": "", "confidence": "high",
        },
        {
            "id": "BLOCK-04", "page": 2, "kind": "paragraph",
            "bbox": [0.0, 0.0, 20.0, 10.0], "raw_text": "bounded text",
            "confidence": "low",
        },
    ]
    proposals = [
        {
            "id": "PROP-01", "engine": "fixture-a", "role": "semantic",
            "artifacts": [{
                "path": "proposals/a/normalized.json", "sha256": "a1",
                "media_type": "application/json",
            }],
        },
        {
            "id": "PROP-02", "engine": "fixture-b", "role": "semantic",
            "artifacts": [{
                "path": "proposals/b/normalized.json", "sha256": "b1",
                "media_type": "application/json",
            }],
        },
    ]
    proposal_page_index = {
        "PROP-01": {1: {
            "page": 1, "width": 100.0, "height": 100.0,
            "elements": [
                {
                    "id": "E-EXACT", "type": "text", "bbox": [0.0, 0.0, 20.0, 10.0],
                    "text": "Estimate = -1.25",
                },
                {
                    "id": "E-SIMILAR", "type": "text", "bbox": [60.0, 60.0, 90.0, 70.0],
                    "text": "alpha beta delta",
                },
                {
                    "id": "E-REVERSED", "type": "text", "bbox": [60.0, 75.0, 90.0, 85.0],
                    "text": "dcba",
                },
                {
                    "id": "E-UNRELATED", "type": "text", "bbox": [60.0, 85.0, 90.0, 95.0],
                    "text": "unrelated tokens",
                },
                {"id": "E-EMPTY", "type": "text", "text": ""},
                {
                    "id": "E-TABLE", "type": "table", "subtype": "grid",
                    "bbox": [50.0, 0.0, 80.0, 20.0], "text": "cell 42",
                    "table_cells": [["cell", "42"]],
                },
            ],
        }},
        "PROP-02": {1: {
            "page": 1, "width": 200.0, "height": 200.0,
            "elements": [
                {
                    "id": "E-ALT", "type": "text", "bbox": [0.0, 0.0, 40.0, 20.0],
                    "text": "Estimate = 1.25",
                },
                {"id": "E-BETA", "type": "text", "text": "alpha beta gamma"},
            ],
        }},
    }
    return {
        "source_sha256": "source-hash",
        "pages": pages,
        "blocks": blocks,
        "tables": [{
            "id": "TABLE-01", "page": 1, "bbox": [50.0, 0.0, 80.0, 20.0],
            "caption": "Fixture table", "crop_path": "objects/table.png",
            "crop_sha256": "c1", "status": "detected", "transcription": None,
        }],
        "figures": [],
        "equations": [],
        "proposals": proposals,
        "proposal_page_index": proposal_page_index,
    }


class ProposalIndexPathTests(unittest.TestCase):
    @staticmethod
    def proposal(path: str) -> list[dict]:
        return [{
            "id": "PROP-01",
            "artifacts": [{"path": path}],
        }]

    def test_reads_only_canonical_normalized_index_inside_declared_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relative = Path("evidence/pdf-ingestion/SRC-01/proposals/tool/normalized.json")
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"pages": [{"page": 1, "elements": []}]}),
                encoding="utf-8",
            )
            index = MODULE.load_proposal_page_index(
                root,
                "evidence/pdf-ingestion/SRC-01",
                self.proposal(relative.as_posix()),
            )
            self.assertEqual(index["PROP-01"][1]["elements"], [])

    def test_rejects_traversal_alias_reserved_and_symlink_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "root"
            root.mkdir()
            outside = base / "normalized.json"
            outside.write_text('{"pages":[{"page":99}]}', encoding="utf-8")
            unsafe_paths = (
                "../normalized.json",
                "evidence/pdf-ingestion/SRC-01/./normalized.json",
                "evidence/pdf-ingestion/SRC-01/NUL/normalized.json",
            )
            for unsafe in unsafe_paths:
                with self.subTest(path=unsafe):
                    self.assertEqual(
                        MODULE.load_proposal_page_index(
                            root,
                            "evidence/pdf-ingestion/SRC-01",
                            self.proposal(unsafe),
                        ),
                        {},
                    )

            inside = root / "evidence/pdf-ingestion/SRC-01/proposals/tool/normalized.json"
            inside.parent.mkdir(parents=True)
            try:
                inside.symlink_to(outside)
            except OSError:
                if os.name == "nt":
                    self.skipTest("symlink creation requires Windows Developer Mode or elevated privileges")
                raise
            self.assertEqual(
                MODULE.load_proposal_page_index(
                    root,
                    "evidence/pdf-ingestion/SRC-01",
                    self.proposal(
                        "evidence/pdf-ingestion/SRC-01/proposals/tool/normalized.json"
                    ),
                ),
                {},
            )


class BlockCandidateEquivalenceTests(unittest.TestCase):
    page = {"page": 1, "width_points": 100.0, "height_points": 100.0}

    @staticmethod
    def block(text: str, bbox: list[float] | None = None) -> dict:
        return {
            "raw_text": text,
            "bbox": bbox or [0.0, 0.0, 10.0, 10.0],
        }

    @staticmethod
    def proposal(text: str, bbox: list[float] | None = None) -> dict:
        element = {"id": "ELEMENT", "type": "text", "text": text}
        if bbox is not None:
            element["bbox"] = bbox
        return {"width": 100.0, "height": 100.0, "elements": [element]}

    def candidate(self, canonical: str, proposed: str, *, overlap: bool = False) -> dict | None:
        bbox = [0.0, 0.0, 10.0, 10.0] if overlap else [50.0, 50.0, 60.0, 60.0]
        return MODULE._block_candidate(
            self.block(canonical), "PROP", self.proposal(proposed, bbox), self.page,
        )

    def test_cutoff_normalization_and_autojunk_goldens(self) -> None:
        at_cutoff = self.candidate("abcdefg", "abcdefg" + "0" * 26)
        self.assertIsNotNone(at_cutoff)
        self.assertEqual(at_cutoff["text_similarity"], 0.35)

        self.assertIsNone(self.candidate("abcdefg", "abcdefg" + "0" * 27))
        self.assertIsNone(self.candidate("abcd", "dcba"))  # quick=1.0, exact=0.25

        autojunk_sensitive = self.candidate("a" * 100 + "b" * 100, "b" * 100 + "a" * 100)
        self.assertIsNotNone(autojunk_sensitive)
        self.assertEqual(autojunk_sensitive["text_similarity"], 0.5)

        normalized = self.candidate("alpha\n beta", "  alpha beta  ")
        self.assertIsNotNone(normalized)
        self.assertTrue(normalized["exact_text"])
        self.assertEqual(normalized["text_similarity"], 1.0)

        empty = self.candidate("", "")
        self.assertIsNotNone(empty)
        self.assertTrue(empty["exact_text"])
        self.assertEqual(empty["text_similarity"], 1.0)

    def test_candidate_outputs_match_frozen_legacy_matcher(self) -> None:
        samples = [
            "", "a", "abcd", "dcba", "abcdefg", "abcdefg" + "0" * 26,
            "abcdefg" + "0" * 27, "alpha beta gamma", "gamma alpha beta",
            "a" * 100 + "b" * 100, "b" * 100 + "a" * 100,
            "Estimate = -1.25", "Estimate = 1.25", "alpha\n beta",
        ]
        for overlap in (False, True):
            bbox = [0.0, 0.0, 10.0, 10.0] if overlap else [50.0, 50.0, 60.0, 60.0]
            for canonical in samples:
                for proposed in samples:
                    block = self.block(canonical)
                    proposal = self.proposal(proposed, bbox)
                    with self.subTest(overlap=overlap, canonical=canonical, proposed=proposed):
                        self.assertEqual(
                            MODULE._block_candidate(block, "PROP", proposal, self.page),
                            legacy_block_candidate(block, "PROP", proposal, self.page),
                        )

    def test_ranking_uses_exact_similarity_overlap_buckets_and_stable_ties(self) -> None:
        block = self.block("abcdefgh")
        proposal = {
            "width": 100.0,
            "height": 100.0,
            "elements": [
                {"id": "QUICK-HIGH", "type": "text", "text": "efghabcd"},
                {"id": "EXACT-HIGH", "type": "text", "text": "abcdefXY"},
            ],
        }
        self.assertEqual(
            MODULE._block_candidate(block, "PROP", proposal, self.page)["element_id"],
            "EXACT-HIGH",
        )

        proposal["elements"] = [
            {
                "id": "NO-OVERLAP-EXACT", "type": "text", "text": "abcdefgh",
                "bbox": [50.0, 50.0, 60.0, 60.0],
            },
            {
                "id": "TINY-OVERLAP", "type": "text", "text": "zzzzzzzz",
                "bbox": [0.0, 0.0, 0.1, 0.1],
            },
        ]
        self.assertEqual(
            MODULE._block_candidate(block, "PROP", proposal, self.page)["element_id"],
            "TINY-OVERLAP",
        )

        wide_block = self.block("abcdefgh", [0.0, 0.0, 100.0, 100.0])
        proposal["elements"] = [
            {
                "id": "BELOW-BUCKET", "type": "text", "text": "abcdefgh",
                "bbox": [0.0, 0.0, 100.0, 24.99],
            },
            {
                "id": "AT-BUCKET", "type": "text", "text": "zzzzzzzz",
                "bbox": [0.0, 0.0, 100.0, 25.0],
            },
        ]
        self.assertEqual(
            MODULE._block_candidate(wide_block, "PROP", proposal, self.page)["element_id"],
            "AT-BUCKET",
        )

        proposal["elements"] = [
            {"id": "FIRST", "type": "text", "text": "abcdefgh"},
            {"id": "SECOND", "type": "text", "text": "abcdefgh"},
        ]
        self.assertEqual(
            MODULE._block_candidate(block, "PROP", proposal, self.page)["element_id"],
            "FIRST",
        )


class PagePacketEquivalenceTests(unittest.TestCase):
    GOLDEN_SHA256 = "3de4b6b8dd5d398f127bfcbb0333d837e0aeb2e8d92970f44fe842e7a0fd43f5"

    def test_page_packet_canonical_bytes_match_golden(self) -> None:
        output = MODULE.build_page_packets(**packet_fixture())
        self.assertEqual(hashlib.sha256(canonical_json(output)).hexdigest(), self.GOLDEN_SHA256)

    def test_page_packets_match_frozen_preoptimization_algorithm(self) -> None:
        with mock.patch.object(MODULE, "_block_candidate", new=legacy_block_candidate):
            legacy_output = MODULE.build_page_packets(**packet_fixture())
        optimized_output = MODULE.build_page_packets(**packet_fixture())
        self.assertEqual(canonical_json(optimized_output), canonical_json(legacy_output))

    def test_matcher_indices_are_reused_and_exact_ratios_are_pruned(self) -> None:
        class CountingSequenceMatcher(LegacySequenceMatcher):
            constructions = 0
            quick_ratio_calls = 0
            ratio_calls = 0

            def __init__(self, *args: object, **kwargs: object) -> None:
                type(self).constructions += 1
                super().__init__(*args, **kwargs)

            def quick_ratio(self) -> float:
                type(self).quick_ratio_calls += 1
                return super().quick_ratio()

            def ratio(self) -> float:
                type(self).ratio_calls += 1
                return super().ratio()

        fixture = packet_fixture()
        element_count = sum(
            len(page["elements"])
            for proposal_pages in fixture["proposal_page_index"].values()
            for page in proposal_pages.values()
        )
        block_element_pairs = sum(
            sum(
                len(proposal_pages.get(block["page"], {}).get("elements", []))
                for proposal_pages in fixture["proposal_page_index"].values()
            )
            for block in fixture["blocks"]
        )
        with mock.patch.object(MODULE, "SequenceMatcher", new=CountingSequenceMatcher):
            output = MODULE.build_page_packets(**fixture)

        self.assertEqual(CountingSequenceMatcher.constructions, element_count)
        self.assertGreater(CountingSequenceMatcher.quick_ratio_calls, 0)
        self.assertLess(CountingSequenceMatcher.ratio_calls, block_element_pairs)
        self.assertLessEqual(CountingSequenceMatcher.ratio_calls, 9)
        self.assertEqual(hashlib.sha256(canonical_json(output)).hexdigest(), self.GOLDEN_SHA256)


if __name__ == "__main__":
    unittest.main()
