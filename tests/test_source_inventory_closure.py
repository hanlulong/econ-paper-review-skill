#!/usr/bin/env python3
"""Adversarial tests for syntax- and PDF-derived source inventory closure."""

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
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
VALIDATOR = ROOT / "econ-review" / "scripts" / "validate_review.py"
PROPOSER = ROOT / "econ-review" / "scripts" / "propose_source_inventory.py"
SPEC = importlib.util.spec_from_file_location("source_inventory_validator", VALIDATOR)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class SourceInventoryClosureTests(unittest.TestCase):
    def test_markdown_outline_ignores_front_matter_fences_and_escaped_hash(self) -> None:
        text = (
            "---\n# metadata, not a heading\n---\n"
            "# Repeated\nBody.\n"
            "```text\n# code, not a heading\n```\n"
            "<!--\n# comment, not a heading\n-->\n"
            "\\# escaped prose\n"
            "# Repeated\nMore.\n"
        )
        rows = MODULE.discover_source_outline("SRC-01", text, "text/markdown", "paper.md")
        headings = [row for row in rows if row["object_type"] == "outline_heading"]
        self.assertEqual([row["object_id"] for row in headings], [
            "SRC-01-OUT-H001", "SRC-01-OUT-H002",
        ])
        self.assertEqual([row["locator"].split(": ", 1)[1] for row in headings], [
            "Repeated", "Repeated",
        ])
        self.assertTrue(all(row["parser_uncertain"] is False for row in headings))

    def test_unclosed_markdown_and_latex_constructs_are_bounded_candidates(self) -> None:
        markdown = "# Section\nText\n```text\n# hidden\n"
        rows = MODULE.discover_source_outline("SRC-01", markdown, "text/markdown", "paper.md")
        self.assertTrue(any(row["parser_uncertain"] is True for row in rows))

        html_comment = "# Section\nText\n<!--\n# hidden\n"
        rows = MODULE.discover_source_outline(
            "SRC-01", html_comment, "text/markdown", "paper.md"
        )
        self.assertEqual(
            1,
            len([row for row in rows if row["object_type"] == "outline_heading"]),
        )
        self.assertTrue(any(
            "Unclosed Markdown HTML comment" in row["locator"]
            and row["parser_uncertain"] is True
            for row in rows
        ))

        latex = (
            "% \\section{Commented}\n"
            "\\section{Repeated}\n"
            "\\begin{verbatim}\n\\section{Literal}\n\\end{verbatim}\n"
            "\\section{Repeated}\n"
            "\\begin{proof}Unclosed"
        )
        rows = MODULE.discover_source_outline("SRC-01", latex, "application/x-tex", "paper.tex")
        headings = [row for row in rows if row["object_type"] == "outline_heading"]
        self.assertEqual(len(headings), 2)
        self.assertEqual([row["object_id"] for row in headings], [
            "SRC-01-OUT-H001", "SRC-01-OUT-H002",
        ])
        proof = next(row for row in rows if row["locator"].endswith(": proof"))
        self.assertTrue(proof["parser_uncertain"])

    def test_lone_scope_anchor_cannot_certify_multisection_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "review"
            shutil.copytree(FIXTURE, target)
            manifest_path = target / "evidence" / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["anchors"] = [
                row for row in manifest["anchors"] if row["kind"] == "scope"
            ]
            write_json(manifest_path, manifest)
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage["units"][0]["anchor_ids"] = ["ANC-03"]
            coverage.pop("source_inventory", None)
            write_json(coverage_path, coverage)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "whole-source scope anchor cannot certify source coverage" in error
                for error in errors
            ), errors)
            self.assertTrue(any(
                "current full coverage requires source_inventory" in error
                for error in errors
            ), errors)

    def test_parser_uncertainty_cannot_be_certified_as_covered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            text = "# Section\nBody\n```text\n# hidden\n"
            (review / "paper.md").write_text(text, encoding="utf-8")
            outline = MODULE.discover_source_outline(
                "SRC-01", text, "text/markdown", "paper.md"
            )
            anchors: dict[str, dict] = {}
            inventory: list[dict] = []
            anchor_ids: list[str] = []
            for index, item in enumerate(outline, start=1):
                anchor_id = f"ANC-{index:02d}"
                anchor_ids.append(anchor_id)
                anchors[anchor_id] = {
                    "id": anchor_id,
                    "source_id": "SRC-01",
                    "kind": "text_span",
                    "start_char": item["start"],
                    "end_char": item["end"],
                    "content_sha256": item["sha256"],
                }
                inventory.append({
                    "id": f"INV-{index:03d}",
                    "source_id": "SRC-01",
                    "object_type": item["object_type"],
                    "object_id": item["object_id"],
                    "locator": item["locator"],
                    "state": "covered",
                    "anchor_ids": [anchor_id],
                    "coverage_unit_ids": ["paper"],
                    "audit_record_id": None,
                    "duplicate_of": None,
                    "reason": None,
                })
            write_json(review / "evidence/figures.json", {"figures": []})
            write_json(review / "evidence/tables.json", {"tables": []})
            errors: list[str] = []
            MODULE.validate_source_inventory_closure(
                review,
                {"source_inventory": inventory},
                {"SRC-01": {
                    "id": "SRC-01", "role": "manuscript", "path": "paper.md",
                    "media_type": "text/markdown", "extraction": None,
                }},
                anchors,
                [{
                    "id": "paper", "source_id": "SRC-01",
                    "anchor_ids": anchor_ids, "type": "section",
                }],
                errors,
            )
            self.assertTrue(any(
                "parser-uncertain source object" in error and "must be bounded" in error
                for error in errors
            ), errors)

    def test_injected_pdf_page_table_and_figure_require_explicit_closure_and_audits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            text = "Canonical PDF block."
            (review / "paper.txt").write_text(text, encoding="utf-8")
            ingestion = {
                "pages": [{"page": 1}],
                "blocks": [{
                    "id": "SRC-01-PDF-B0001", "page": 1,
                    "markdown_start": 0, "markdown_end": len(text),
                    "sha256": hashlib.sha256(text.encode()).hexdigest(),
                }],
                "tables": [{
                    "id": "SRC-01-PDF-TBL-001", "page": 1,
                    "status": "candidate_needs_visual_verification",
                }],
                "figures": [{
                    "id": "SRC-01-PDF-FIG-001", "page": 1,
                    "status": "candidate_needs_visual_verification",
                }],
                "equations": [],
            }
            write_json(review / "evidence/pdf-ingestion/SRC-01/ingestion.json", ingestion)
            write_json(review / "evidence/figures.json", {"figures": []})
            write_json(review / "evidence/tables.json", {"tables": []})
            source = {
                "id": "SRC-01", "role": "manuscript", "path": "paper.pdf",
                "media_type": "application/pdf",
                "extraction": {
                    "path": "paper.txt",
                    "ingestion_manifest_path": "evidence/pdf-ingestion/SRC-01/ingestion.json",
                },
            }
            anchor = {
                "id": "ANC-01", "source_id": "SRC-01", "kind": "text_span",
                "start_char": 0, "end_char": len(text),
                "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
            units = [{
                "id": "paper", "source_id": "SRC-01", "anchor_ids": ["ANC-01"],
                "type": "section",
            }, {
                "id": "table", "source_id": "SRC-01", "anchor_ids": ["ANC-01"],
                "type": "table",
            }, {
                "id": "figure", "source_id": "SRC-01", "anchor_ids": ["ANC-01"],
                "type": "figure",
            }]
            coverage = {"source_inventory": [{
                "id": "INV-001", "source_id": "SRC-01", "object_type": "pdf_block",
                "object_id": "SRC-01-PDF-B0001",
                "locator": "PDF page 1, block SRC-01-PDF-B0001", "state": "covered",
                "anchor_ids": ["ANC-01"], "coverage_unit_ids": ["paper"],
                "audit_record_id": None, "duplicate_of": None, "reason": None,
            }]}
            errors: list[str] = []
            MODULE.validate_source_inventory_closure(
                review, coverage, {"SRC-01": source}, {"ANC-01": anchor}, units, errors
            )
            joined = "\n".join(errors)
            self.assertIn("SRC-01/pdf_page/SRC-01-PDF-P0001", joined)
            self.assertIn("SRC-01/pdf_table/SRC-01-PDF-TBL-001", joined)
            self.assertIn("SRC-01/pdf_figure/SRC-01-PDF-FIG-001", joined)

            coverage["source_inventory"].extend([{
                "id": "INV-002", "source_id": "SRC-01", "object_type": "pdf_page",
                "object_id": "SRC-01-PDF-P0001", "locator": "PDF page 1",
                "state": "covered", "anchor_ids": [], "coverage_unit_ids": ["paper"],
                "audit_record_id": None, "duplicate_of": None, "reason": None,
            }, {
                "id": "INV-003", "source_id": "SRC-01", "object_type": "pdf_table",
                "object_id": "SRC-01-PDF-TBL-001",
                "locator": "PDF page 1, pdf table SRC-01-PDF-TBL-001",
                "state": "covered", "anchor_ids": [], "coverage_unit_ids": ["table"],
                "audit_record_id": None, "duplicate_of": None, "reason": None,
            }, {
                "id": "INV-004", "source_id": "SRC-01", "object_type": "pdf_figure",
                "object_id": "SRC-01-PDF-FIG-001",
                "locator": "PDF page 1, pdf figure SRC-01-PDF-FIG-001",
                "state": "covered", "anchor_ids": [], "coverage_unit_ids": ["figure"],
                "audit_record_id": None, "duplicate_of": None, "reason": None,
            }])
            errors = []
            MODULE.validate_source_inventory_closure(
                review, coverage, {"SRC-01": source}, {"ANC-01": anchor}, units, errors
            )
            self.assertTrue(any(
                "covered SRC-01-PDF-TBL-001 requires its rendered-audit record" in error
                for error in errors
            ), errors)
            self.assertTrue(any(
                "covered SRC-01-PDF-FIG-001 requires its rendered-audit record" in error
                for error in errors
            ), errors)

            write_json(review / "evidence/source-manifest.json", {
                "sources": [source], "anchors": [anchor],
            })
            write_json(review / "evidence/coverage.json", {
                "units": units, "source_inventory": [],
            })
            proposal = subprocess.run(
                [sys.executable, str(PROPOSER), str(review), "SRC-01", "paper"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proposal.returncode, 0, proposal.stderr)
            proposed_rows = json.loads(proposal.stdout)["source_inventory_rows_to_add"]
            proposed_by_type = {row["object_type"]: row for row in proposed_rows}
            self.assertEqual(
                {"pdf_page", "pdf_block", "pdf_table", "pdf_figure"},
                set(proposed_by_type),
            )
            self.assertEqual(proposed_by_type["pdf_table"]["state"], "bounded")
            self.assertEqual(proposed_by_type["pdf_figure"]["state"], "bounded")

    def test_proposer_runs_before_coverage_and_uses_canonical_pdf_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            text = "Canonical PDF block."
            (review / "paper.txt").write_text(text, encoding="utf-8")
            digest = hashlib.sha256(text.encode()).hexdigest()
            ingestion = {
                "pages": [{"page": 1, "status": "extracted"}],
                "blocks": [{
                    "id": "SRC-01-PDF-B0001", "page": 1, "kind": "paragraph",
                    "markdown_start": 0, "markdown_end": len(text), "sha256": digest,
                }],
                "tables": [{"id": "SRC-01-PDF-TBL-001", "page": 1}],
                "figures": [{"id": "SRC-01-PDF-FIG-001", "page": 1}],
                "equations": [{"id": "SRC-01-PDF-EQ-001", "page": 1}],
            }
            write_json(review / "evidence/pdf-ingestion/SRC-01/ingestion.json", ingestion)
            write_json(review / "evidence/source-manifest.json", {
                "sources": [{
                    "id": "SRC-01", "role": "manuscript", "path": "paper.pdf",
                    "media_type": "application/pdf", "extraction": {
                        "path": "paper.txt",
                        "ingestion_manifest_path": "evidence/pdf-ingestion/SRC-01/ingestion.json",
                    },
                }],
                "anchors": [{
                    "id": "ANC-01", "source_id": "SRC-01", "kind": "text_span",
                    "start_char": 0, "end_char": len(text), "content_sha256": digest,
                    "locator": "PDF p. 1, bbox 0,0,10,10, block SRC-01-PDF-B0001",
                }, {
                    "id": "ANC-02", "source_id": "SRC-01", "kind": "scope",
                    "start_char": 0, "end_char": len(text), "content_sha256": digest,
                    "locator": "Complete authenticated PDF extraction",
                }],
            })

            proposal = subprocess.run(
                [sys.executable, str(PROPOSER), str(review), "SRC-01", "paper"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proposal.returncode, 0, proposal.stderr)
            payload = json.loads(proposal.stdout)
            self.assertEqual(payload["coverage_unit_status"], "planned")
            self.assertEqual(payload["coverage_unit_anchor_ids_to_add"], ["ANC-01", "ANC-02"])
            rows = {
                (row["object_type"], row["object_id"]): row
                for row in payload["source_inventory_rows_to_add"]
            }
            self.assertEqual(set(rows), {
                ("pdf_page", "SRC-01-PDF-P0001"),
                ("pdf_block", "SRC-01-PDF-B0001"),
                ("pdf_table", "SRC-01-PDF-TBL-001"),
                ("pdf_figure", "SRC-01-PDF-FIG-001"),
                ("pdf_equation", "SRC-01-PDF-EQ-001"),
            })
            self.assertEqual(rows[("pdf_page", "SRC-01-PDF-P0001")]["locator"], "PDF page 1")
            self.assertEqual(
                rows[("pdf_block", "SRC-01-PDF-B0001")]["locator"],
                "PDF page 1, block SRC-01-PDF-B0001",
            )
            self.assertEqual(
                rows[("pdf_equation", "SRC-01-PDF-EQ-001")]["locator"],
                "PDF page 1, pdf equation SRC-01-PDF-EQ-001",
            )
            self.assertNotIn("PDF-PAGE", proposal.stdout)

            manifest = json.loads(
                (review / "evidence/source-manifest.json").read_text(encoding="utf-8")
            )
            all_anchors = [*manifest["anchors"], *payload["anchors_to_add"]]
            write_json(review / "evidence/figures.json", {"figures": []})
            write_json(review / "evidence/tables.json", {"tables": []})
            errors: list[str] = []
            MODULE.validate_source_inventory_closure(
                review,
                {"source_inventory": payload["source_inventory_rows_to_add"]},
                {"SRC-01": manifest["sources"][0]},
                {anchor["id"]: anchor for anchor in all_anchors},
                [{
                    "id": "paper", "source_id": "SRC-01", "type": "section",
                    "anchor_ids": payload["coverage_unit_anchor_ids_to_add"],
                }],
                errors,
            )
            self.assertEqual(errors, [])

    def test_pdf_math_fragment_heading_is_explicitly_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            text = (
                "## Abstract\nNarrative.\n"
                "## y w,t\nEquation continuation.\n"
                "## β convergence\nSubstantive discussion.\n"
                "## (a) Baseline results\nMain specification.\n"
                "## (b) Robustness checks\nAlternative specification.\n"
                "## (i) Introduction\nOpening discussion.\n"
            )
            (review / "manuscript.md").write_text(text, encoding="utf-8")
            digest = hashlib.sha256(text.encode()).hexdigest()
            write_json(review / "evidence/pdf-ingestion/SRC-01/ingestion.json", {
                "pages": [], "blocks": [], "tables": [], "figures": [], "equations": [],
            })
            write_json(review / "evidence/source-manifest.json", {
                "sources": [{
                    "id": "SRC-01", "role": "manuscript", "path": "paper.pdf",
                    "media_type": "application/pdf", "extraction": {
                        "path": "manuscript.md",
                        "ingestion_manifest_path": "evidence/pdf-ingestion/SRC-01/ingestion.json",
                    },
                }],
                "anchors": [{
                    "id": "ANC-01", "source_id": "SRC-01", "kind": "scope",
                    "start_char": 0, "end_char": len(text), "content_sha256": digest,
                    "locator": "Complete authenticated PDF extraction",
                }],
            })

            proposal = subprocess.run(
                [sys.executable, str(PROPOSER), str(review), "SRC-01", "paper"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proposal.returncode, 0, proposal.stderr)
            rows = {
                row["object_id"]: row
                for row in json.loads(proposal.stdout)["source_inventory_rows_to_add"]
                if row["object_type"] == "outline_heading"
            }
            self.assertEqual(rows["SRC-01-OUT-H001"]["state"], "covered")
            math_row = rows["SRC-01-OUT-H002"]
            self.assertEqual(math_row["state"], "excluded")
            self.assertEqual(math_row["anchor_ids"], [])
            self.assertEqual(math_row["coverage_unit_ids"], [])
            self.assertIn("math-dominated display fragment", math_row["reason"])
            greek_heading = rows["SRC-01-OUT-H003"]
            self.assertEqual(greek_heading["state"], "covered")
            self.assertTrue(greek_heading["anchor_ids"])
            self.assertEqual(greek_heading["coverage_unit_ids"], ["paper"])
            for object_id in (
                "SRC-01-OUT-H004",
                "SRC-01-OUT-H005",
                "SRC-01-OUT-H006",
            ):
                with self.subTest(object_id=object_id):
                    self.assertEqual(rows[object_id]["state"], "covered")
                    self.assertTrue(rows[object_id]["anchor_ids"])

    def test_candidate_command_is_read_only(self) -> None:
        before_manifest = (FIXTURE / "evidence/source-manifest.json").read_bytes()
        before_coverage = (FIXTURE / "evidence/coverage.json").read_bytes()
        result = subprocess.run(
            [sys.executable, str(PROPOSER), str(FIXTURE), "SRC-01", "paper"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["read_only"])
        self.assertEqual((FIXTURE / "evidence/source-manifest.json").read_bytes(), before_manifest)
        self.assertEqual((FIXTURE / "evidence/coverage.json").read_bytes(), before_coverage)


if __name__ == "__main__":
    unittest.main()
