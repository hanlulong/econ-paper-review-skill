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


@unittest.skipUnless(
    all(shutil.which(command) for command in ("pdfinfo", "pdftotext", "pdftoppm")),
    "Poppler commands are required for PDF ingestion integration tests",
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
        self.run_cli(
            "ingest", str(pdf), str(review), "--review-id", "PDF-TEST",
            "--source-id", source_id, "--ocr", "never", "--dpi", "150", *extra,
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
            )
            self.assertIn("already current", result.stdout)
            self.assertEqual((first / "ingestion.json").read_bytes(), before)

    def test_changed_configuration_requires_force_and_changes_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf, review = root / "synthetic.pdf", root / "review"
            make_pdf(pdf)
            current = self.ingest(pdf, review)
            before = json.loads((current / "ingestion.json").read_text())
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
                self.assertIn("requires the local markitdown command", result.stderr)
        self.assertIn("network: disabled by design", self.run_cli("doctor").stdout)


if __name__ == "__main__":
    unittest.main()
