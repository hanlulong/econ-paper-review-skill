#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "pdf_ingestion.py"
SPEC = importlib.util.spec_from_file_location("pdf_ingestion", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_pdf(
    path: Path, *, blank_second_page: bool = False, active_content: bool = False,
) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    })
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
    })
    commands = b"""
BT /F1 18 Tf 72 748 Td (1 Introduction) Tj ET
BT /F1 11 Tf 72 720 Td (This paper studies a synthetic economic question.) Tj ET
BT /F1 12 Tf 72 675 Td (y = a + b x   (1)) Tj ET
BT /F1 11 Tf 72 620 Td (Table 1: Summary statistics) Tj ET
72 590 m 372 590 l 372 500 l 72 500 l h S
72 560 m 372 560 l S 72 530 m 372 530 l S
172 590 m 172 500 l S 272 590 m 272 500 l S
BT /F1 10 Tf 82 570 Td (Variable) Tj 100 0 Td (Mean) Tj 100 0 Td (N) Tj ET
BT /F1 10 Tf 82 540 Td (Outcome) Tj 100 0 Td (2.0) Tj 100 0 Td (100) Tj ET
BT /F1 10 Tf 82 510 Td (Treatment) Tj 100 0 Td (0.5) Tj 100 0 Td (100) Tj ET
100 315 m 330 315 l 330 455 l 100 455 l h S
110 330 m 160 390 l 210 350 l 270 430 l 320 370 l S
BT /F1 11 Tf 100 290 Td (Figure 1: Synthetic trend) Tj ET
BT /F1 9 Tf 72 60 Td (Synthetic footer) Tj ET
"""
    stream = DecodedStreamObject()
    stream.set_data(commands)
    page[NameObject("/Contents")] = writer._add_object(stream)
    if blank_second_page:
        writer.add_blank_page(width=612, height=792)
    if active_content:
        writer.add_js("app.alert('not executed')")
        writer.add_attachment("note.txt", b"attachment is never opened")
        writer._root_object[NameObject("/OpenAction")] = DictionaryObject({
            NameObject("/S"): NameObject("/URI"),
            NameObject("/URI"): TextStringObject("https://example.invalid/document-open-action"),
        })
        for active_page in writer.pages:
            page_action = DictionaryObject({
                NameObject("/O"): DictionaryObject({
                    NameObject("/S"): NameObject("/URI"),
                    NameObject("/URI"): TextStringObject("https://example.invalid/page-action"),
                }),
            })
            active_page[NameObject("/AA")] = page_action
            annotation = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Link"),
                NameObject("/Rect"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(10), NumberObject(10)]),
                NameObject("/A"): DictionaryObject({
                    NameObject("/S"): NameObject("/URI"),
                    NameObject("/URI"): TextStringObject("https://example.invalid/annotation-action"),
                }),
            })
            active_page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    with path.open("wb") as handle:
        writer.write(handle)


def package(review: Path, source_id: str = "SRC-01") -> Path:
    return review / "evidence" / "pdf-ingestion" / source_id


def compatible_pdf_runtime() -> bool:
    try:
        MODULE.ensure_core_python_runtime()
    except MODULE.IngestionError:
        return False
    return all(shutil.which(command) for command in ("pdfinfo", "pdftotext", "pdftoppm"))


class PdfXmlSanitizationTests(unittest.TestCase):
    def test_xml_forbidden_control_is_removed_only_from_parser_input_and_recorded(self) -> None:
        fixture = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><doc>'
            '<page width="612" height="792"><flow><block xMin="72" yMin="72" xMax="300" yMax="100">'
            '<line><word>alpha\x0fbeta</word></line>'
            '</block></flow></page></doc></body></html>'
        ).encode("utf-8")

        def fake_pdftotext(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
            Path(command[-1]).write_bytes(fixture)
            return subprocess.CompletedProcess(command, 0, b"", b"")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(MODULE, "run", side_effect=fake_pdftotext):
            pages, blocks, repairs = MODULE.parse_bbox_layout(
                Path("unused.pdf"), Path(tmp), "SRC-01",
            )
        self.assertEqual(len(pages), 1)
        self.assertEqual(blocks[0]["raw_text"], "alphabeta")
        self.assertEqual(repairs["xml_forbidden_control_count"], 1)
        self.assertEqual(repairs["xml_forbidden_codepoints"], ["U+000F"])
        self.assertNotEqual(repairs["raw_xhtml_sha256"], repairs["parser_input_sha256"])
        self.assertEqual(repairs["action"], "removed_xml_forbidden_controls_from_parser_input")

    def test_portable_paths_and_logical_block_order_fail_closed(self) -> None:
        self.assertEqual(MODULE.safe_relative("evidence/pdf-ingestion/SRC-01"), "evidence/pdf-ingestion/SRC-01")
        for unsafe in (
            "/absolute/path", "../escape", "evidence\\windows", "C:/drive/path",
            "evidence//double", "evidence/./dot", "evidence/\x00control",
            "evidence/decomposed-e\u0301", "evidence/trailing.", "evidence/AUX/file.json",
            "evidence/ padded/file.json",
        ):
            with self.assertRaisesRegex(MODULE.IngestionError, "safe and relative"):
                MODULE.safe_relative(unsafe)

        blocks = [
            {"id": "left-1", "page": 1, "bbox": [10, 10, 100, 20]},
            {"id": "left-2", "page": 1, "bbox": [10, 30, 100, 40]},
            {"id": "right-1", "page": 1, "bbox": [200, 10, 300, 20]},
        ]
        self.assertEqual(
            [row["id"] for row in MODULE.page_blocks(blocks)[1]],
            ["left-1", "left-2", "right-1"],
            "two-column content-stream order must not be interleaved by a global y/x sort",
        )

    def test_ocr_language_is_passed_as_one_non_shell_argument(self) -> None:
        completed = subprocess.CompletedProcess([], 0, b"recognized", b"")
        with mock.patch.object(MODULE, "run", return_value=completed) as runner:
            self.assertEqual(MODULE.extract_ocr(Path("page.png"), "eng+fra"), "recognized")
        self.assertEqual(runner.call_args.args[0][4], "eng+fra")

    def test_image_verification_rejects_disguised_or_truncated_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.png"
            path.write_text("<html>not an image</html>", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.IngestionError, "not a decodable image"):
                MODULE.verified_image_shape(path, "page render")


class PdfCandidateClassificationTests(unittest.TestCase):
    @staticmethod
    def classify(text: str, *, y0: float = 100.0, y1: float = 140.0) -> tuple[str, str]:
        return MODULE.classify_block({
            "raw_text": text,
            "bbox": [72.0, y0, 540.0, y1],
            "page_height": 792.0,
        }, set())

    def test_caption_prefixes_and_identifier_styles_are_design_agnostic(self) -> None:
        cases = {
            "Table 1: Summary statistics": "caption_table",
            "Table 1 Summary statistics": "caption_table",
            "Appendix Table A.1: Matching rate analysis": "caption_table",
            "Online Appendix Figure OA.2 - Robustness results": "caption_figure",
            "Online Supplementary Appendix Table S1 Results": "caption_table",
            "Supplemental Appendix Fig. B-3. Dynamics": "caption_figure",
            "Supporting Information Figure 2b: Sample construction": "caption_figure",
            "Figure IV: Equilibrium regions": "caption_figure",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.classify(text)[0], expected)

    def test_repeated_top_caption_is_not_discarded_as_a_running_header(self) -> None:
        text = "Table 1: Results (continued)"
        block = {
            "raw_text": text,
            "bbox": [72.0, 20.0, 540.0, 50.0],
            "page_height": 792.0,
        }
        normalized = "table #: results (continued)"
        self.assertEqual(
            MODULE.classify_block(block, {("top", normalized)})[0],
            "caption_table",
        )

    def test_narrative_cross_references_are_not_captions(self) -> None:
        prose = (
            "Table A.2 summarizes the ownership-spell dataset constructed from the matched records.",
            "Figure B.1 plots the geographical distribution of the cities.",
            "Appendix Table D.1 reports the corresponding estimates.",
            "Table 2 and Figure 3 provide the remaining results.",
            "Table 4 is discussed in the next section.",
        )
        for text in prose:
            with self.subTest(text=text):
                self.assertEqual(self.classify(text)[0], "paragraph")

    def test_clear_prose_equalities_are_not_equation_candidates(self) -> None:
        prose = (
            "26 The results are robust to alternative lag lengths of p = 2 and p = 6.",
            "The calibration sets p = 2 and q = 6.",
        )
        for text in prose:
            with self.subTest(text=text):
                self.assertNotEqual(self.classify(text, y0=670.0, y1=690.0)[0], "equation_candidate")
        for equation in ("p = 2\nq = 6", "y = a + b x   (1)"):
            with self.subTest(equation=equation):
                self.assertEqual(self.classify(equation)[0], "equation_candidate")

    def test_detector_contract_changes_current_but_not_legacy_fingerprints(self) -> None:
        configuration = {"source_id": "SRC-01", "source_role": "manuscript"}
        toolchain = {"primary": {"name": "pdftotext", "version": "synthetic"}}
        current = MODULE.pipeline_fingerprint(
            configuration, toolchain,
            detector_contract={"version": "1", "source_sha256": "a" * 64},
        )
        changed = MODULE.pipeline_fingerprint(
            configuration, toolchain,
            detector_contract={"version": "1", "source_sha256": "b" * 64},
        )
        self.assertNotEqual(current, changed)
        legacy_a = MODULE.pipeline_fingerprint(
            configuration, toolchain, pipeline_version="0.2",
            detector_contract={"version": "1", "source_sha256": "a" * 64},
        )
        legacy_b = MODULE.pipeline_fingerprint(
            configuration, toolchain, pipeline_version="0.2",
            detector_contract={"version": "1", "source_sha256": "b" * 64},
        )
        self.assertEqual(legacy_a, legacy_b)


class PdfObjectRegionTests(unittest.TestCase):
    @staticmethod
    def block(
        identifier: str, kind: str, bbox: list[float], text: str,
    ) -> dict[str, object]:
        return {
            "id": identifier, "kind": kind, "bbox": bbox, "raw_text": text,
            "page_width": 612.0, "page_height": 792.0,
        }

    def test_caption_above_figure_includes_plot_note_and_excludes_following_prose(self) -> None:
        caption = self.block("caption", "caption_figure", [100, 70, 510, 84], "Figure 1: Results")
        rows = [
            caption,
            self.block("label", "paragraph", [85, 110, 525, 315], "Panel labels"),
            self.block(
                "note", "paragraph", [72, 335, 540, 390],
                "Note: The lines show estimates and the shaded areas show confidence intervals.",
            ),
            self.block(
                "prose", "paragraph", [72, 430, 540, 520],
                "This paragraph begins the manuscript discussion after the exhibit and should not be included "
                "in a crop of the figure because it is ordinary body prose rather than an exhibit note.",
            ),
        ]
        graphics = [{"kind": "rect", "bbox": [82, 102, 530, 326]}]
        bbox = MODULE.region_from_caption(caption, "figure", rows, graphics)
        self.assertLessEqual(bbox[0], 72)
        self.assertLessEqual(bbox[1], 70)
        self.assertGreaterEqual(bbox[2], 540)
        self.assertGreaterEqual(bbox[3], 390)
        self.assertLess(bbox[3], 430)

    def test_caption_below_figure_uses_graphic_above_and_keeps_following_note(self) -> None:
        caption = self.block("caption", "caption_figure", [150, 430, 462, 444], "Figure 2: Dynamics")
        rows = [
            self.block(
                "prose", "paragraph", [72, 60, 540, 155],
                "This paragraph precedes the exhibit and contains enough ordinary prose to be recognized as "
                "manuscript text that should remain outside the resulting figure crop.",
            ),
            self.block("label", "paragraph", [105, 205, 505, 400], "Chart labels"),
            caption,
            self.block("note", "paragraph", [72, 458, 540, 490], "Source: Authors' calculations."),
        ]
        graphics = [{"kind": "image", "bbox": [95, 190, 515, 412]}]
        bbox = MODULE.region_from_caption(caption, "figure", rows, graphics)
        self.assertGreater(bbox[1], 155)
        self.assertLessEqual(bbox[1], 190)
        self.assertGreaterEqual(bbox[3], 490)

    def test_adjacent_captioned_tables_expand_to_cells_without_overlapping(self) -> None:
        first = self.block("caption-1", "caption_table", [180, 90, 430, 104], "Table 1: First")
        second = self.block("caption-2", "caption_table", [180, 390, 430, 404], "Table 2: Second")
        rows = [
            first,
            self.block("first-cells", "paragraph", [70, 125, 542, 300], "Variable values"),
            self.block("first-note", "paragraph", [72, 320, 540, 360], "Robust standard errors in parentheses"),
            second,
            self.block("second-cells", "paragraph", [68, 425, 544, 650], "Variable values"),
        ]
        first_bbox = MODULE.region_from_caption(first, "table", rows)
        second_bbox = MODULE.region_from_caption(second, "table", rows)
        self.assertLessEqual(first_bbox[0], 70)
        self.assertGreaterEqual(first_bbox[2], 542)
        self.assertLess(first_bbox[3], second_bbox[1])

    def test_detector_failures_are_preserved_as_bounded_warnings(self) -> None:
        with mock.patch("pdfplumber.open", side_effect=RuntimeError("synthetic parser failure")):
            tables, table_warnings = MODULE.table_candidates(Path("synthetic.pdf"))
            graphics, graphic_warnings = MODULE.page_graphic_candidates(Path("synthetic.pdf"))
        self.assertEqual(tables, {})
        self.assertEqual(graphics, {})
        self.assertTrue(any("table-grid detector failed" in warning for warning in table_warnings))
        self.assertTrue(any("graphic-extent detector failed" in warning for warning in graphic_warnings))


@unittest.skipUnless(
    compatible_pdf_runtime(),
    "compatible requirements-core.txt environment and Poppler commands are required for PDF integration tests",
)
class PdfIngestionTests(unittest.TestCase):
    def run_cli(
        self, *arguments: str, check: bool = True, cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        if cwd is not None:
            return subprocess.run(
                ["python3", str(SCRIPT), *arguments], text=True, capture_output=True,
                check=check, cwd=cwd, env=environment,
            )
        with tempfile.TemporaryDirectory() as execution_directory:
            return subprocess.run(
                ["python3", str(SCRIPT), *arguments], text=True, capture_output=True,
                check=check, cwd=execution_directory, env=environment,
            )

    def ingest(self, pdf: Path, review: Path, *extra: str, source_id: str = "SRC-01") -> Path:
        backend = () if "--semantic-backend" in extra else ("--semantic-backend", "none")
        self.run_cli(
            "ingest", str(pdf), str(review), "--review-id", "PDF-TEST",
            "--source-id", source_id, "--ocr", "never", "--dpi", "150", *backend, *extra,
        )
        return package(review, source_id)

    def test_clean_runs_are_deterministic_and_same_request_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "synthetic.pdf"
            make_pdf(pdf)
            first = self.ingest(pdf, root / "review-a")
            second = self.ingest(pdf, root / "review-b")
            self.assertEqual((first / "ingestion.json").read_bytes(), (second / "ingestion.json").read_bytes())
            self.assertEqual(
                (first / "source-manifest.generated.json").read_bytes(),
                (second / "source-manifest.generated.json").read_bytes(),
            )
            before = (first / "ingestion.json").read_bytes()
            result = self.run_cli(
                "ingest", str(pdf), str(root / "review-a"), "--review-id", "PDF-TEST",
                "--source-id", "SRC-01", "--ocr", "never", "--dpi", "150",
                "--semantic-backend", "none",
            )
            self.assertIn("already current", result.stdout)
            self.assertEqual((first / "ingestion.json").read_bytes(), before)

    def test_current_ingestion_generates_exactly_one_authenticated_scope_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf, review = root / "synthetic.pdf", root / "review"
            make_pdf(pdf)
            current = self.ingest(pdf, review)
            ingestion = json.loads((current / "ingestion.json").read_text(encoding="utf-8"))
            generated = json.loads(
                (current / "source-manifest.generated.json").read_text(encoding="utf-8")
            )
            markdown_text = (current / "manuscript.md").read_text(encoding="utf-8")
            markdown_bytes = markdown_text.encode("utf-8")

            scope_anchors = [
                row for row in generated["anchors"] if row.get("kind") == "scope"
            ]
            self.assertEqual(len(generated["anchors"]), len(ingestion["blocks"]) + 1)
            self.assertEqual(len(scope_anchors), 1)
            scope = scope_anchors[0]
            self.assertEqual(
                scope["id"],
                MODULE.source_anchor_id("SRC-01", len(ingestion["blocks"]) + 1),
            )
            self.assertEqual(scope["source_id"], "SRC-01")
            self.assertEqual(
                (scope["start_char"], scope["end_char"]),
                (0, len(markdown_text)),
            )
            self.assertEqual(scope["content_sha256"], MODULE.sha256_bytes(markdown_bytes))
            self.assertEqual(scope["content_sha256"], ingestion["markdown"]["sha256"])
            checked = self.run_cli("check", str(current), check=False)
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_scope_anchor_tampering_and_duplicate_scope_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf, review = root / "synthetic.pdf", root / "review"
            make_pdf(pdf)
            current = self.ingest(pdf, review)
            generated_path = current / "source-manifest.generated.json"
            original = json.loads(generated_path.read_text(encoding="utf-8"))

            def duplicate_scope(value: dict[str, Any]) -> None:
                value["anchors"][0]["kind"] = "scope"

            def change_block_kind(value: dict[str, Any]) -> None:
                value["anchors"][0]["kind"] = "figure"

            def change_scope_identity(value: dict[str, Any]) -> None:
                value["anchors"][-1]["source_id"] = "SRC-99"

            def change_scope_span(value: dict[str, Any]) -> None:
                value["anchors"][-1]["end_char"] -= 1

            def change_scope_hash(value: dict[str, Any]) -> None:
                value["anchors"][-1]["content_sha256"] = "0" * 64

            cases = (
                ("duplicate scope", duplicate_scope, "exactly one scope anchor"),
                ("block kind", change_block_kind, "kind differs from its canonical block"),
                ("scope identity", change_scope_identity, "scope anchor differs"),
                ("scope span", change_scope_span, "scope anchor differs"),
                ("scope hash", change_scope_hash, "scope anchor differs"),
            )
            for label, mutate, expected in cases:
                with self.subTest(label=label):
                    tampered = json.loads(json.dumps(original))
                    mutate(tampered)
                    generated_path.write_bytes(MODULE.canonical_json(tampered))
                    checked = self.run_cli("check", str(current), check=False)
                    self.assertNotEqual(checked.returncode, 0)
                    self.assertIn(expected, checked.stderr)
            generated_path.write_bytes(MODULE.canonical_json(original))
            checked = self.run_cli("check", str(current), check=False)
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_legacy_block_only_generated_manifest_remains_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf, review = root / "synthetic.pdf", root / "review"
            make_pdf(pdf)
            current = self.ingest(pdf, review)
            generated_path = current / "source-manifest.generated.json"
            generated = json.loads(generated_path.read_text(encoding="utf-8"))
            removed = generated["anchors"].pop()
            self.assertEqual(removed["kind"], "scope")
            self.assertFalse(any(row["kind"] == "scope" for row in generated["anchors"]))
            generated_path.write_bytes(MODULE.canonical_json(generated))

            checked = self.run_cli("check", str(current), check=False)
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_changed_configuration_requires_force_and_changes_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf, review = root / "synthetic.pdf", root / "review"
            make_pdf(pdf)
            current = self.ingest(pdf, review)
            before = json.loads((current / "ingestion.json").read_text())
            self.assertEqual(before["configuration"]["ocr_language"], "eng")
            refused = self.run_cli(
                "ingest", str(pdf), str(review), "--review-id", "PDF-TEST", "--source-id", "SRC-01",
                "--ocr", "never", "--dpi", "200", check=False,
            )
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("differs", refused.stderr)
            self.run_cli(
                "ingest", str(pdf), str(review), "--review-id", "PDF-TEST", "--source-id", "SRC-01",
                "--ocr", "never", "--dpi", "200", "--force",
            )
            after = json.loads((current / "ingestion.json").read_text())
            self.assertNotEqual(before["pipeline_fingerprint"], after["pipeline_fingerprint"])
            self.assertEqual(after["configuration"]["dpi"], 200)

    def test_ocr_selected_text_drives_markdown_and_native_alternative_is_preserved(self) -> None:
        pages = [{"page": 1, "width": 612.0, "height": 792.0}]
        native = [{
            "id": "SRC-01-PDF-B0001", "page": 1, "bbox": [72, 72, 300, 100],
            "kind": "paragraph", "raw_text": "BROKEN NATIVE", "confidence": "low",
        }]
        markdown, blocks = MODULE.build_markdown(pages, native, {1: ("OCR SELECTED TEXT", "ocr")}, "SRC-01")
        self.assertIn("OCR SELECTED TEXT", markdown)
        self.assertNotIn("BROKEN NATIVE", markdown)
        self.assertEqual(blocks[0]["kind"], "ocr_text")
        self.assertTrue(blocks[0]["id"].startswith("SRC-01-PDF-B"))

    def test_tampering_and_structural_corruption_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf, review = root / "synthetic.pdf", root / "review"
            make_pdf(pdf)
            current = self.ingest(pdf, review)
            checks: list[tuple[Path, str]] = [
                (current / "manuscript.md", "Markdown hash mismatch"),
                (current / "renders/page-0001.png", "page 1 render hash mismatch"),
            ]
            manifest = json.loads((current / "ingestion.json").read_text())
            table = manifest["tables"][0]
            checks.append((review / table["transcription"]["markdown_path"], "candidate Markdown hash mismatch"))
            for path, expected in checks:
                original = path.read_bytes()
                path.write_bytes(original + b"tamper")
                result = self.run_cli("check", str(current), check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                path.write_bytes(original)
            manifest["blocks"][0]["bbox"] = [0, 0, 9999, 9999]
            (current / "ingestion.json").write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_cli("check", str(current), check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("out-of-page bounds", result.stderr)

    def test_multiple_sources_use_disjoint_defaults_ids_and_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_pdf, second_pdf, review = root / "paper.pdf", root / "appendix.pdf", root / "review"
            make_pdf(first_pdf)
            make_pdf(second_pdf)
            first = self.ingest(first_pdf, review, source_id="SRC-01")
            second = self.ingest(second_pdf, review, "--role", "appendix", source_id="SRC-02")
            self.assertNotEqual(first, second)
            first_manifest = json.loads((first / "ingestion.json").read_text())
            second_manifest = json.loads((second / "ingestion.json").read_text())
            self.assertTrue(all(row["id"].startswith("SRC-01-") for row in first_manifest["blocks"]))
            self.assertTrue(all(row["id"].startswith("SRC-02-") for row in second_manifest["blocks"]))
            first_source = json.loads((first / "source-manifest.generated.json").read_text())
            second_source = json.loads((second / "source-manifest.generated.json").read_text())
            self.assertEqual(first_source["sources"][0]["role"], "manuscript")
            self.assertEqual(second_source["sources"][0]["role"], "appendix")
            self.assertTrue(set(row["id"] for row in first_source["anchors"]).isdisjoint(
                row["id"] for row in second_source["anchors"]
            ))
            self.assertEqual(self.run_cli("check", str(first)).returncode, 0)
            self.assertEqual(self.run_cli("check", str(second)).returncode, 0)

    def test_blank_page_boundary_cwd_guard_and_nonexecuting_safety_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf, review, execution = root / "hybrid.pdf", root / "review", root / "execution"
            execution.mkdir()
            guard = execution / "must-survive.txt"
            guard.write_text("guard", encoding="utf-8")
            make_pdf(pdf, blank_second_page=True, active_content=True)
            before = sorted(path.name for path in execution.iterdir())
            self.run_cli(
                "ingest", str(pdf), str(review), "--review-id", "PDF-TEST", "--source-id", "SRC-01",
                "--ocr", "never", "--dpi", "150", cwd=execution,
            )
            self.assertEqual(sorted(path.name for path in execution.iterdir()), before)
            self.assertEqual(guard.read_text(), "guard")
            manifest = json.loads((package(review) / "ingestion.json").read_text())
            self.assertEqual(manifest["pages"][1]["status"], "bounded")
            self.assertEqual(manifest["quality"]["status"], "bounded")
            warnings = " ".join(manifest["quality"]["warnings"])
            self.assertIn("JavaScript", warnings)
            self.assertIn("embedded files", warnings)
            self.assertIn("document OpenAction", warnings)
            self.assertIn("page actions on pages 1-2", warnings)
            self.assertIn("annotation actions on pages 1-2", warnings)
            self.assertNotIn("annotation actions on page 1;", warnings)

    def test_unsafe_output_and_optional_markitdown_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "synthetic.pdf"
            make_pdf(pdf)
            result = self.run_cli(
                "ingest", str(pdf), str(root / "review"), "--review-id", "PDF-SAFE",
                "--output", "../escape", check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("safe and relative", result.stderr)
            if shutil.which("markitdown") is None:
                result = self.run_cli(
                    "ingest", str(pdf), str(root / "review-2"), "--review-id", "PDF-MARKITDOWN",
                    "--markitdown-proposal", check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("optional backend markitdown is unavailable", result.stderr)
        self.assertIn("network: forbidden by default", self.run_cli("doctor").stdout)

    @unittest.skipUnless(shutil.which("markitdown"), "compatible MarkItDown command is not installed")
    def test_pinned_markitdown_proposal_is_non_authoritative_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf, review = root / "synthetic.pdf", root / "review"
            make_pdf(pdf)
            current = self.ingest(pdf, review, "--markitdown-proposal")
            manifest = json.loads((current / "ingestion.json").read_text(encoding="utf-8"))
            proposal = manifest["proposal"]
            self.assertEqual(proposal["engine"], "markitdown")
            self.assertFalse(proposal["authoritative"])
            self.assertTrue((current / "proposals/markitdown.md").is_file())
            checked = self.run_cli("check", str(current), check=False)
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_mathpix_requires_two_explicit_authorizations_before_credentials_or_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "synthetic.pdf"
            make_pdf(pdf)
            missing_upload = self.run_cli(
                "ingest", str(pdf), str(root / "review-a"), "--review-id", "PDF-MATHPIX",
                "--semantic-backend", "none", "--mathpix", check=False,
            )
            self.assertNotEqual(missing_upload.returncode, 0)
            self.assertIn("--authorize-external-upload mathpix", missing_upload.stderr)
            missing_retention = self.run_cli(
                "ingest", str(pdf), str(root / "review-b"), "--review-id", "PDF-MATHPIX",
                "--semantic-backend", "none", "--mathpix",
                "--authorize-external-upload", "mathpix", check=False,
            )
            self.assertNotEqual(missing_retention.returncode, 0)
            self.assertIn("--accept-mathpix-retention", missing_retention.stderr)

    def test_legacy_v01_package_remains_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf, review = root / "synthetic.pdf", root / "review"
            make_pdf(pdf)
            current = self.ingest(pdf, review, "--semantic-backend", "none")
            manifest = json.loads((current / "ingestion.json").read_text())
            manifest["schema_version"] = "0.1"
            manifest.pop("detector_contract")
            manifest.pop("proposals")
            manifest.pop("reconciliation")
            manifest["toolchain"].pop("semantic_backends")
            manifest["configuration"] = {
                key: manifest["configuration"][key]
                for key in ("dpi", "ocr", "max_pages", "max_bytes", "markitdown_proposal", "network_services")
            }
            manifest["pipeline_fingerprint"] = MODULE.pipeline_fingerprint(
                {
                    **manifest["configuration"], "source_id": manifest["source_id"],
                    "source_role": manifest["source_role"],
                },
                manifest["toolchain"], pipeline_version="0.1",
            )
            ingestion_bytes = MODULE.canonical_json(manifest)
            (current / "ingestion.json").write_bytes(ingestion_bytes)
            generated = json.loads((current / "source-manifest.generated.json").read_text())
            scope = generated["anchors"].pop()
            self.assertEqual(scope["kind"], "scope")
            self.assertFalse(any(row["kind"] == "scope" for row in generated["anchors"]))
            extraction = generated["sources"][0]["extraction"]
            extraction["ingestion_manifest_sha256"] = MODULE.sha256_bytes(ingestion_bytes)
            extraction["pipeline_fingerprint"] = manifest["pipeline_fingerprint"]
            (current / "source-manifest.generated.json").write_bytes(MODULE.canonical_json(generated))
            result = self.run_cli("check", str(current), check=False)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_v02_package_remains_verifiable_without_detector_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf, review = root / "synthetic.pdf", root / "review"
            make_pdf(pdf)
            current = self.ingest(pdf, review, "--semantic-backend", "none")
            manifest = json.loads((current / "ingestion.json").read_text())
            manifest["schema_version"] = "0.2"
            manifest.pop("detector_contract")
            manifest["pipeline_fingerprint"] = MODULE.pipeline_fingerprint(
                {
                    **manifest["configuration"], "source_id": manifest["source_id"],
                    "source_role": manifest["source_role"],
                },
                manifest["toolchain"], pipeline_version="0.2",
            )
            ingestion_bytes = MODULE.canonical_json(manifest)
            (current / "ingestion.json").write_bytes(ingestion_bytes)
            generated = json.loads((current / "source-manifest.generated.json").read_text())
            extraction = generated["sources"][0]["extraction"]
            extraction["ingestion_manifest_sha256"] = MODULE.sha256_bytes(ingestion_bytes)
            extraction["pipeline_fingerprint"] = manifest["pipeline_fingerprint"]
            (current / "source-manifest.generated.json").write_bytes(MODULE.canonical_json(generated))
            result = self.run_cli("check", str(current), check=False)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
