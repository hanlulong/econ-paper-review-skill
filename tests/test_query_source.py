#!/usr/bin/env python3
"""Focused security, integrity, and output tests for query_source.py."""

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


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "query_source.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
SPEC = importlib.util.spec_from_file_location("query_source_tests", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def save_json(path: Path, value: dict) -> bytes:
    data = json.dumps(value, indent=2).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


class QuerySourceTests(unittest.TestCase):
    def copy_fixture(self, temporary: str) -> Path:
        target = Path(temporary) / "review"
        shutil.copytree(FIXTURE, target)
        return target

    def make_pdf_review(self, temporary: str) -> Path:
        root = Path(temporary) / "review"
        evidence = root / "evidence"
        pdf_dir = evidence / "pdf-ingestion" / "SRC-01"
        source_bytes = b"%PDF-1.7\nsynthetic read-only fixture\n"
        markdown = "Alpha a.* beta.\nAlpha second occurrence.\nGamma.\n"
        page_text = "Alpha a.* beta.\nAlpha second occurrence.\n"
        render = b"synthetic-png-bytes"
        paths = {
            "source": pdf_dir / "source" / "original.pdf",
            "markdown": pdf_dir / "manuscript.md",
            "page": pdf_dir / "pages" / "page-0001.native.txt",
            "render": pdf_dir / "renders" / "page-0001.png",
        }
        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        paths["source"].write_bytes(source_bytes)
        paths["markdown"].write_text(markdown, encoding="utf-8")
        paths["page"].write_text(page_text, encoding="utf-8")
        paths["render"].write_bytes(render)
        first = "Alpha a.* beta."
        second = "Alpha second occurrence."
        second_start = markdown.index(second)
        pipeline = "f" * 64
        ingestion = {
            "review_id": "query-pdf-001",
            "source_id": "SRC-01",
            "pipeline_fingerprint": pipeline,
            "source": {"sha256": digest(source_bytes)},
            "markdown": {
                "path": "evidence/pdf-ingestion/SRC-01/manuscript.md",
                "sha256": digest(markdown.encode()),
            },
            "pages": [{
                "page": 1,
                "text_path": "evidence/pdf-ingestion/SRC-01/pages/page-0001.native.txt",
                "text_sha256": digest(page_text.encode()),
                "render_path": "evidence/pdf-ingestion/SRC-01/renders/page-0001.png",
                "render_sha256": digest(render),
                "status": "extracted",
                "text_method": "pdf_text_layer",
            }],
            "blocks": [
                {
                    "id": "SRC-01-PDF-B0001",
                    "page": 1,
                    "bbox": [1, 2, 3, 4],
                    "kind": "paragraph",
                    "raw_text": first,
                    "markdown_start": 0,
                    "markdown_end": len(first),
                    "sha256": digest(first.encode()),
                },
                {
                    "id": "SRC-01-PDF-B0002",
                    "page": 1,
                    "bbox": [2, 3, 4, 5],
                    "kind": "paragraph",
                    "raw_text": second,
                    "markdown_start": second_start,
                    "markdown_end": second_start + len(second),
                    "sha256": digest(second.encode()),
                },
            ],
        }
        ingestion_path = pdf_dir / "ingestion.json"
        ingestion_bytes = save_json(ingestion_path, ingestion)
        anchors = [
            {
                "id": "ANC-01",
                "source_id": "SRC-01",
                "kind": "text_span",
                "start_char": 0,
                "end_char": len(first),
                "content_sha256": digest(first.encode()),
                "locator": "PDF p. 1, block SRC-01-PDF-B0001",
            },
            {
                "id": "ANC-02",
                "source_id": "SRC-01",
                "kind": "text_span",
                "start_char": second_start,
                "end_char": second_start + len(second),
                "content_sha256": digest(second.encode()),
                "locator": "PDF p. 1, block SRC-01-PDF-B0002",
            },
            {
                "id": "ANC-03",
                "source_id": "SRC-01",
                "kind": "scope",
                "start_char": 0,
                "end_char": len(markdown),
                "content_sha256": digest(markdown.encode()),
                "locator": "Complete PDF extraction",
            },
        ]
        save_json(evidence / "source-manifest.json", {
            "schema_version": "0.1",
            "review_id": "query-pdf-001",
            "sources": [{
                "id": "SRC-01",
                "role": "manuscript",
                "path": "evidence/pdf-ingestion/SRC-01/source/original.pdf",
                "media_type": "application/pdf",
                "sha256": digest(source_bytes),
                "extraction": {
                    "path": "evidence/pdf-ingestion/SRC-01/manuscript.md",
                    "sha256": digest(markdown.encode()),
                    "normalization": "none",
                    "ingestion_manifest_path": "evidence/pdf-ingestion/SRC-01/ingestion.json",
                    "ingestion_manifest_sha256": digest(ingestion_bytes),
                    "pipeline_fingerprint": pipeline,
                },
            }],
            "anchors": anchors,
        })
        save_json(evidence / "coverage.json", {
            "schema_version": "0.2",
            "review_id": "query-pdf-001",
            "units": [{
                "id": "paper",
                "source_id": "SRC-01",
                "anchor_ids": ["ANC-01", "ANC-02", "ANC-03"],
                "type": "section",
                "label": "Complete paper",
                "status": "findings",
                "finding_ids": ["FND-01"],
                "notes": "Synthetic query fixture.",
            }],
        })
        return root

    @staticmethod
    def tree_hashes(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): digest(path.read_bytes())
            for path in root.rglob("*") if path.is_file()
        }

    def test_exact_anchor_is_authenticated_and_query_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            before = self.tree_hashes(target)
            payload = MODULE.SourceQuery(target).query_anchors(
                ["ANC-01"], context_chars=20, max_content_chars=1_000
            )
            self.assertEqual(before, self.tree_hashes(target))
            result = payload["results"][0]
            self.assertEqual(
                result["content"],
                "The equilibrium action is unique for every parameter value.",
            )
            self.assertTrue(result["verification"]["source_file_sha256"])
            self.assertTrue(result["verification"]["exact_span_sha256"])
            self.assertTrue(result["context"]["navigation_only"])

    def test_pdf_anchor_locator_is_derived_from_authenticated_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.make_pdf_review(temporary)
            manifest_path = target / "evidence" / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["anchors"][0]["locator"] = "PDF p. 999, block FABRICATED"
            save_json(manifest_path, manifest)
            result = MODULE.SourceQuery(target).query_anchors(
                ["ANC-01"], context_chars=0, max_content_chars=1_000
            )["results"][0]
            self.assertIn("PDF p. 1", result["locator"])
            self.assertIn("SRC-01-PDF-B0001", result["locator"])
            self.assertNotIn("999", result["locator"])
            self.assertTrue(
                result["verification"]["pdf_locator_from_authenticated_block"]
            )

    def test_coverage_lists_units_and_paginates_authenticated_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.make_pdf_review(temporary)
            query = MODULE.SourceQuery(target)
            listing = query.query_coverage(
                None, offset=0, limit=1, context_chars=0, max_content_chars=1_000
            )
            self.assertEqual(listing["results"][0]["id"], "paper")
            payload = query.query_coverage(
                "paper", offset=1, limit=1, context_chars=10, max_content_chars=1_000
            )
            self.assertEqual(payload["results"][0]["anchor"]["id"], "ANC-02")
            self.assertEqual(payload["pagination"]["next_offset"], 2)
            self.assertTrue(payload["results"][0]["verification"]["extraction_sha256"])

    def test_pdf_page_returns_verified_locator_render_and_exact_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.make_pdf_review(temporary)
            payload = MODULE.SourceQuery(target).query_page(
                "SRC-01", 1, offset=0, limit=1, max_content_chars=1_000
            )
            self.assertEqual(payload["page"]["locator"], "PDF p. 1")
            self.assertTrue(payload["page"]["verification"]["page_render_sha256"])
            result = payload["results"][0]
            self.assertEqual(result["content"], "Alpha a.* beta.")
            self.assertEqual(result["anchor"]["id"], "ANC-01")
            self.assertTrue(result["verification"]["exact_span_sha256"])

    def test_pdf_page_rejects_tampered_text_or_render(self) -> None:
        paths = (
            "evidence/pdf-ingestion/SRC-01/pages/page-0001.native.txt",
            "evidence/pdf-ingestion/SRC-01/renders/page-0001.png",
        )
        for relative in paths:
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as temporary:
                target = self.make_pdf_review(temporary)
                path = target / relative
                path.write_bytes(path.read_bytes() + b"tamper")
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    MODULE.SourceQuery(target).query_page(
                        "SRC-01", 1, offset=0, limit=1, max_content_chars=1_000
                    )

    def test_literal_search_escapes_regex_and_is_navigation_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.make_pdf_review(temporary)
            payload = MODULE.SourceQuery(target).query_search(
                "a.*", source_ids=["SRC-01"], ignore_case=False,
                offset=0, limit=5, context_chars=12,
            )
            self.assertTrue(payload["navigation_only"])
            self.assertEqual(len(payload["results"]), 1)
            result = payload["results"][0]
            self.assertEqual(result["content"], "a.*")
            self.assertTrue(result["context"]["navigation_only"])
            self.assertTrue(result["verification"]["literal_match_in_authenticated_source"])

    def test_tampering_in_each_authentication_layer_is_rejected(self) -> None:
        cases = (
            ("extraction", "evidence/pdf-ingestion/SRC-01/manuscript.md"),
            ("source", "evidence/pdf-ingestion/SRC-01/source/original.pdf"),
            ("ingestion", "evidence/pdf-ingestion/SRC-01/ingestion.json"),
        )
        for label, relative in cases:
            with self.subTest(layer=label), tempfile.TemporaryDirectory() as temporary:
                target = self.make_pdf_review(temporary)
                path = target / relative
                path.write_bytes(path.read_bytes() + b"tamper")
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    MODULE.SourceQuery(target).query_anchors(
                        ["ANC-01"], context_chars=0, max_content_chars=1_000
                    )

    def test_unsafe_source_paths_fail_closed_on_all_platforms(self) -> None:
        unsafe_paths = (
            "../outside.md",
            "/tmp/outside.md",
            "C:\\Temp\\paper.md",
            "evidence/bad?.md",
            "evidence/bad*.md",
            "evidence/bad<name>.md",
            "evidence/bad|name.md",
            'evidence/bad"name.md',
            "evidence/COM¹.txt",
            "evidence/LPT³.json",
        )
        for unsafe in unsafe_paths:
            with self.subTest(path=unsafe), tempfile.TemporaryDirectory() as temporary:
                target = self.copy_fixture(temporary)
                manifest_path = target / "evidence" / "source-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["sources"][0]["path"] = unsafe
                save_json(manifest_path, manifest)
                with self.assertRaisesRegex(ValueError, "unsafe.*path"):
                    MODULE.SourceQuery(target).query_anchors(
                        ["ANC-01"], context_chars=0, max_content_chars=1_000
                    )

    def test_coverage_unit_cannot_borrow_another_sources_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            manifest_path = target / "evidence" / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            second = {**manifest["sources"][0], "id": "SRC-02"}
            manifest["sources"].append(second)
            save_json(manifest_path, manifest)
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage["units"][0]["source_id"] = "SRC-02"
            save_json(coverage_path, coverage)
            with self.assertRaisesRegex(ValueError, "borrows anchor"):
                MODULE.SourceQuery(target).query_coverage(
                    None, offset=0, limit=1,
                    context_chars=0, max_content_chars=1_000,
                )

    def test_pdf_artifact_paths_cannot_cross_source_roots(self) -> None:
        cases = ("source", "extraction", "ingestion", "page_text", "page_render")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                target = self.make_pdf_review(temporary)
                evidence = target / "evidence"
                source_two = evidence / "pdf-ingestion" / "SRC-02"
                manifest_path = evidence / "source-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                source = manifest["sources"][0]
                ingestion_path = evidence / "pdf-ingestion" / "SRC-01" / "ingestion.json"
                ingestion = json.loads(ingestion_path.read_text(encoding="utf-8"))

                if case == "source":
                    destination = source_two / "source" / "original.pdf"
                    destination.parent.mkdir(parents=True)
                    destination.write_bytes((target / source["path"]).read_bytes())
                    source["path"] = "evidence/pdf-ingestion/SRC-02/source/original.pdf"
                elif case == "extraction":
                    destination = source_two / "manuscript.md"
                    destination.parent.mkdir(parents=True)
                    data = (target / source["extraction"]["path"]).read_bytes()
                    destination.write_bytes(data)
                    borrowed = "evidence/pdf-ingestion/SRC-02/manuscript.md"
                    source["extraction"]["path"] = borrowed
                    source["extraction"]["sha256"] = digest(data)
                    ingestion["markdown"]["path"] = borrowed
                    ingestion["markdown"]["sha256"] = digest(data)
                    ingestion_bytes = save_json(ingestion_path, ingestion)
                    source["extraction"]["ingestion_manifest_sha256"] = digest(ingestion_bytes)
                elif case == "ingestion":
                    destination = source_two / "ingestion.json"
                    destination.parent.mkdir(parents=True)
                    data = ingestion_path.read_bytes()
                    destination.write_bytes(data)
                    source["extraction"]["ingestion_manifest_path"] = (
                        "evidence/pdf-ingestion/SRC-02/ingestion.json"
                    )
                    source["extraction"]["ingestion_manifest_sha256"] = digest(data)
                else:
                    field = "text_path" if case == "page_text" else "render_path"
                    hash_field = "text_sha256" if case == "page_text" else "render_sha256"
                    original = target / ingestion["pages"][0][field]
                    destination = source_two / original.name
                    destination.parent.mkdir(parents=True)
                    data = original.read_bytes()
                    destination.write_bytes(data)
                    ingestion["pages"][0][field] = (
                        f"evidence/pdf-ingestion/SRC-02/{original.name}"
                    )
                    ingestion["pages"][0][hash_field] = digest(data)
                    ingestion_bytes = save_json(ingestion_path, ingestion)
                    source["extraction"]["ingestion_manifest_sha256"] = digest(ingestion_bytes)
                save_json(manifest_path, manifest)

                query = MODULE.SourceQuery(target)
                with self.assertRaisesRegex(ValueError, "canonical ingestion root"):
                    if case in {"page_text", "page_render"}:
                        query.query_page(
                            "SRC-01", 1, offset=0, limit=1, max_content_chars=1_000
                        )
                    else:
                        query.query_anchors(
                            ["ANC-01"], context_chars=0, max_content_chars=1_000
                        )

    def test_output_cap_returns_valid_bounded_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.make_pdf_review(temporary)
            payload = MODULE.SourceQuery(target).query_search(
                "a", source_ids=["SRC-01"], ignore_case=True,
                offset=0, limit=50, context_chars=2_000,
            )
            output = MODULE.bounded_json(payload, 2_048)
            self.assertLessEqual(len(output), 2_048)
            parsed = json.loads(output)
            self.assertTrue(parsed["navigation_only"])
            self.assertTrue(all(
                row["context"]["navigation_only"] for row in parsed["results"]
            ))
            self.assertTrue(all(
                "match_start_char" in row["context"]
                and "match_end_char" in row["context"]
                for row in parsed["results"]
            ))

    def test_output_cap_never_silently_drops_requested_anchor_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            payload = MODULE.SourceQuery(target).query_anchors(
                ["ANC-01", "ANC-02", "ANC-03", "ANC-100", "ANC-101"],
                context_chars=2_000,
                max_content_chars=32_000,
            )
            with self.assertRaisesRegex(ValueError, "narrow the query"):
                MODULE.bounded_json(payload, 2_048)

    def test_cli_emits_compact_json_and_rejects_invalid_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(target), "anchor", "ANC-01"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("\n  ", result.stdout)
            self.assertEqual(json.loads(result.stdout)["command"], "anchor")
            rejected = subprocess.run(
                [
                    sys.executable, str(SCRIPT), str(target), "anchor", "ANC-01",
                    "--max-output-bytes", "1000000",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("max_output_bytes", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
