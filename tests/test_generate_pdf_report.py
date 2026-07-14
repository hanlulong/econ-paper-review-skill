#!/usr/bin/env python3
"""Regression tests for the professional PDF and clean delivery projection."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "generate_pdf_report.py"
FINALIZER = ROOT / "econ-review" / "scripts" / "finalize_review.py"
DELIVERY = ROOT / "econ-review" / "scripts" / "create_delivery.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
SPEC = importlib.util.spec_from_file_location("generate_pdf_report", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
DELIVERY_SPEC = importlib.util.spec_from_file_location("create_delivery_test", DELIVERY)
assert DELIVERY_SPEC and DELIVERY_SPEC.loader
DELIVERY_MODULE = importlib.util.module_from_spec(DELIVERY_SPEC)
sys.modules[DELIVERY_SPEC.name] = DELIVERY_MODULE
DELIVERY_SPEC.loader.exec_module(DELIVERY_MODULE)


class GeneratePdfReportTests(unittest.TestCase):
    def copy_fixture(self, temporary: str, name: str = "review") -> Path:
        target = Path(temporary) / name
        shutil.copytree(FIXTURE, target)
        return target

    def test_pdf_is_deterministic_and_contains_every_reader_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            first = Path(temporary) / "first.pdf"
            second = Path(temporary) / "second.pdf"
            first_bytes = MODULE.build_pdf(target, first, page_size="letter", font_dir=None)
            second_bytes = MODULE.build_pdf(target, second, page_size="letter", font_dir=None)
            self.assertEqual(first_bytes, second_bytes)
            first.write_bytes(first_bytes)
            reader = PdfReader(first)
            self.assertGreater(len(reader.pages), 3)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            normalized_text = " ".join(text.split())
            for expected in (
                "A Boundary Case in a Static Signaling Model",
                "Referee Report",
                "Referee report",
                "Detailed Comments (1)",
                "Editing comments",
                "Detailed Editing Comments (1)",
                "Revision plan",
            ):
                self.assertIn(expected, normalized_text)
            for excluded in (
                "Paper reconstruction",
                "Package verification",
                "Reader and claim audit",
                "schema_version",
                "SHA-256",
                "finalization receipt",
                "LOGIC-01",
                "WRT-01",
                "Linked findings",
                "verified render",
                "Result: Issue",
                "Checked:",
                "Economic Paper Review",
                "Full review",
                "Author revision",
                "Prepared for author revision",
                "Pending",
            ):
                self.assertNotIn(excluded, text)
            contents = reader.pages[1].extract_text() or ""
            for destination in (
                "Referee report", "Detailed Comments (1)", "Editing comments",
                "Detailed Editing Comments (1)", "Revision plan",
                "Overall assessment", "Recommendation and main grounds",
                "Editing assessment", "Highest-return editing revisions",
                "How to use this plan", "P0 - essential before submission",
            ):
                self.assertIn(destination, contents)

    def test_round_progress_follows_referee_report_in_pdf_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            round_path = target / "evidence" / "round-reconciliation.md"
            sentinel = "The reviewer independently rechecked every prior comment."
            round_path.write_text(
                "# What Changed Since the Prior Review\n\n" + sentinel + "\n",
                encoding="utf-8",
            )
            manifest_path = target / "review-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["documents"].append({
                "id": "round-progress",
                "title": "What changed since the prior review",
                "group": "overview",
                "path": "evidence/round-reconciliation.md",
                "order": 20,
            })
            manifest_path.write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="utf-8",
            )

            entries = MODULE.document_entries(target)
            paths = [entry.path for entry in entries]
            self.assertLess(paths.index("report.md"), paths.index("evidence/round-reconciliation.md"))
            self.assertLess(paths.index("evidence/round-reconciliation.md"), paths.index("editing-comments.md"))

            output = Path(temporary) / "round-progress.pdf"
            output.write_bytes(MODULE.build_pdf(target, output, page_size="letter", font_dir=None))
            text = "\n".join(page.extract_text() or "" for page in PdfReader(output).pages)
            self.assertIn("What changed since the prior review", text)
            self.assertIn(sentinel, text)

    def test_default_pdf_font_source_and_reportlab_version_are_fixed(self) -> None:
        import reportlab

        requirements = (ROOT / "econ-review" / "requirements-core.txt").read_text(encoding="utf-8")
        self.assertIn("reportlab==4.5.1", requirements)
        self.assertEqual(reportlab.__version__, "4.5.1")
        packaged = tuple(MODULE._safe_font_file(path) for path in MODULE._packaged_font_paths())
        self.assertTrue(all(packaged))
        with mock.patch.object(MODULE.platform, "system", return_value="Windows"):
            windows = MODULE.register_fonts(None)
        with mock.patch.object(MODULE.platform, "system", return_value="Darwin"):
            mac = MODULE.register_fonts(None)
        self.assertEqual(windows, mac)
        self.assertEqual(windows.body, "ERBody")

    def test_check_detects_stale_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            output = Path(temporary) / "report.pdf"
            generated = subprocess.run(
                [sys.executable, str(SCRIPT), str(target), "--output", str(output)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            with (target / "report.md").open("a", encoding="utf-8") as handle:
                handle.write("\nA newly verified comment.\n")
            checked = subprocess.run(
                [sys.executable, str(SCRIPT), str(target), "--output", str(output), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("not synchronized", checked.stderr)

    def test_manifest_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            manifest_path = target / "review-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["documents"][0]["path"] = "../outside.md"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsafe|canonical relative"):
                MODULE.document_entries(target)

    def test_font_discovery_has_native_mac_windows_and_linux_candidates(self) -> None:
        candidates = [str(path).replace("\\", "/") for row in MODULE._font_candidates() for path in row]
        self.assertTrue(any("/System/Library/Fonts/" in path for path in candidates))
        self.assertTrue(any(path.startswith("C:/Windows/Fonts/") for path in candidates))
        self.assertTrue(any("/usr/share/fonts/" in path for path in candidates))

    def test_windows_font_discovery_honors_nondefault_system_and_user_roots(self) -> None:
        with mock.patch.object(MODULE.platform, "system", return_value="Windows"), \
                mock.patch.dict(MODULE.os.environ, {
                    "WINDIR": "D:/Windows",
                    "LOCALAPPDATA": "D:/Profiles/reviewer/AppData/Local",
                }, clear=True):
            candidates = [
                str(path).replace("\\", "/")
                for row in MODULE._font_candidates()
                for path in row
            ]
        self.assertIn("D:/Windows/Fonts/arial.ttf", candidates)
        self.assertIn(
            "D:/Profiles/reviewer/AppData/Local/Microsoft/Windows/Fonts/DejaVuSans.ttf",
            candidates,
        )

    def test_pdf_builder_does_not_create_the_requested_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            output = Path(temporary) / "absent" / "paper-review.pdf"
            data = MODULE.build_pdf(target, output, page_size="letter", font_dir=None)
            self.assertTrue(data.startswith(b"%PDF-"))
            self.assertFalse(output.parent.exists())

    def test_revision_plan_pdf_distinguishes_unordered_and_ordered_lists_and_hides_relative_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            plan = target / "fix-plan.md"
            plan.write_text(
                plan.read_text(encoding="utf-8")
                + "\n\n## Rendering regression\n\n"
                + "- Alpha bullet\n- Beta bullet\n\n"
                + "1. First ordered\n2. Second ordered\n3. Third ordered\n\n"
                + "Read the [revision plan](fix-plan.md).\n",
                encoding="utf-8",
            )
            output = Path(temporary) / "rendering.pdf"
            output.write_bytes(MODULE.build_pdf(target, output, page_size="letter", font_dir=None))
            text = "\n".join(page.extract_text() or "" for page in PdfReader(output).pages)
            self.assertIn("Alpha bullet", text)
            self.assertIn("Beta bullet", text)
            self.assertIn("Read the revision plan.", " ".join(text.split()))
            self.assertNotIn("[revision plan](fix-plan.md)", text)
            self.assertRegex(text, r"(?m)^-\s*$\nAlpha bullet$")
            self.assertRegex(text, r"(?m)^-\s*$\nBeta bullet$")
            self.assertRegex(text, r"(?m)^1\s*$\nFirst ordered$")
            self.assertRegex(text, r"(?m)^2\s*$\nSecond ordered$")
            self.assertRegex(text, r"(?m)^3\s*$\nThird ordered$")
            self.assertNotRegex(text, r"(?m)^1\s*$\n(?:Alpha|Beta) bullet$")
            self.assertNotRegex(
                text,
                r"(?m)^1\s*$\n(?:Severity|Action|Payoff|Done when|Effort|Dependencies):",
            )

    def test_detailed_comment_headings_do_not_fill_the_contents_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            report = target / "report.md"
            sentinel = "TOC sentinel detailed comment"
            report.write_text(
                report.read_text(encoding="utf-8") + f"\n\n### 99. Appendix: {sentinel}\n\nBody.\n",
                encoding="utf-8",
            )
            output = Path(temporary) / "toc.pdf"
            output.write_bytes(MODULE.build_pdf(target, output, page_size="letter", font_dir=None))
            pages = [page.extract_text() or "" for page in PdfReader(output).pages]
            body_page = next(index for index, text in enumerate(pages) if sentinel in text)
            self.assertGreater(body_page, 1)
            self.assertNotIn(sentinel, "\n".join(pages[1:body_page]))

    def test_legacy_audit_documents_are_excluded_from_pdf_and_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            sentinel = "INTERNAL AUDIT SENTINEL MUST NOT APPEAR"
            audit_path = target / "evidence" / "verification.md"
            audit_path.write_text(audit_path.read_text(encoding="utf-8") + f"\n\n## {sentinel}\n", encoding="utf-8")
            manifest_path = target / "review-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["documents"].append({
                "id": "legacy-audit",
                "title": "Package verification",
                "group": "audit",
                "path": "evidence/verification.md",
                "order": 99,
            })
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            output = Path(temporary) / "author-only.pdf"
            output.write_bytes(MODULE.build_pdf(target, output, page_size="letter", font_dir=None))
            text = "\n".join(page.extract_text() or "" for page in PdfReader(output).pages)
            self.assertNotIn("Package verification", text)
            self.assertNotIn(sentinel, text)

    def test_oversized_markdown_table_row_splits_across_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            report = target / "report.md"
            long_cell = " ".join(["explanation"] * 1800)
            report.write_text(
                report.read_text(encoding="utf-8")
                + f"\n\n## Long-cell regression\n\n| Item | Explanation |\n|---|---|\n| One | {long_cell} |\n",
                encoding="utf-8",
            )
            output = Path(temporary) / "long-table.pdf"
            data = MODULE.build_pdf(target, output, page_size="letter", font_dir=None)
            self.assertTrue(data.startswith(b"%PDF-"))

    @unittest.skipIf(os.name == "nt", "symlink creation is privilege-dependent on Windows")
    def test_direct_pdf_generation_rejects_symlinked_package_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            run = target / "run.json"
            outside = Path(temporary) / "outside-run.json"
            outside.write_bytes(run.read_bytes())
            run.unlink()
            run.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "links or junctions"):
                MODULE.build_pdf(target, Path(temporary) / "unsafe.pdf", page_size="letter", font_dir=None)

    def test_pdf_hides_legacy_internal_evidence_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            report_path = target / "report.md"
            report_path.write_text(
                report_path.read_text(encoding="utf-8")
                + "\n\n## Legacy display check\n\n"
                + "**Relevant text**:\n\n"
                + "> [Reviewer observation] A reviewer-derived comparison.\n\n"
                + "> [Rendered transcription] An authenticated source transcription.\n",
                encoding="utf-8",
            )
            output = Path(temporary) / "legacy.pdf"
            output.write_bytes(MODULE.build_pdf(target, output, page_size="letter", font_dir=None))
            text = "\n".join(page.extract_text() or "" for page in PdfReader(output).pages)
            self.assertIn("A reviewer-derived comparison.", text)
            self.assertIn("An authenticated source transcription.", text)
            self.assertNotIn("[Reviewer observation]", text)
            self.assertNotIn("[Rendered transcription]", text)

    def test_cover_omits_internal_mode_audience_and_recommendation_cards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            synthesis_path = target / "synthesis.json"
            synthesis = json.loads(synthesis_path.read_text(encoding="utf-8"))
            synthesis["review_posture"] = "weak_r_and_r"
            synthesis_path.write_text(json.dumps(synthesis, indent=2) + "\n", encoding="utf-8")
            output = Path(temporary) / "posture.pdf"
            output.write_bytes(MODULE.build_pdf(target, output, page_size="letter", font_dir=None))
            cover = PdfReader(output).pages[0].extract_text() or ""
            normalized_cover = " ".join(cover.split())
            self.assertIn("A Boundary Case in a Static Signaling Model", normalized_cover)
            self.assertIn("Referee Report", cover)
            for excluded in (
                "Weak R&R", "Economic Paper Review", "Full review",
                "Author revision", "Prepared for author revision",
            ):
                self.assertNotIn(excluded, cover)

    def test_legacy_title_fallback_prefers_title_page_prose_over_bare_hash_equation(self) -> None:
        markdown = (
            "<!-- PDF page 1 -->\n\n"
            "Imperfect Banking Competition and Macroeconomic\n"
            "Volatility: A DSGE Framework\n\n"
            "Author Name\n\n"
            "## Abstract\n\nText.\n\n"
            "#\n\nα_k [k -1] α_l\n"
        )
        self.assertEqual(
            MODULE._markdown_title(markdown),
            "Imperfect Banking Competition and Macroeconomic Volatility: A DSGE Framework",
        )
        self.assertIsNone(MODULE._markdown_title("#\n\nα_k [k -1] α_l\n"))

    def test_finalizer_builds_pdf_and_clean_nested_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            delivery_root = Path(temporary) / "review"
            target = delivery_root / "supporting"
            shutil.copytree(FIXTURE, target)
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((target / "paper-review.pdf").is_file())
            self.assertTrue((delivery_root / "paper-review.pdf").is_file())
            self.assertTrue((delivery_root / "reports" / "referee-report.md").is_file())
            self.assertTrue((delivery_root / "reports" / "editing-comments.md").is_file())
            self.assertTrue((delivery_root / "reports" / "revision-plan.md").is_file())
            root_files = sorted(path.name for path in delivery_root.iterdir())
            self.assertEqual(root_files, ["README.md", "paper-review.pdf", "reports", "supporting"])
            self.assertFalse(any(path.name == ".DS_Store" for path in target.rglob("*")))

    def test_current_finalization_rejects_missing_generic_or_equation_titles(self) -> None:
        for invalid_title in (None, "Untitled manuscript", "α_k [k -1] α_l"):
            with self.subTest(invalid_title=invalid_title), tempfile.TemporaryDirectory() as temporary:
                target = self.copy_fixture(temporary)
                run_path = target / "run.json"
                run = json.loads(run_path.read_text(encoding="utf-8"))
                if invalid_title is None:
                    run.pop("paper_title", None)
                else:
                    run["paper_title"] = invalid_title
                run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(FINALIZER), str(target)],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("clean run.json.paper_title", result.stderr)

    def test_clean_delivery_surfaces_round_progress_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary, "supporting")
            round_markdown = target / "evidence" / "round-reconciliation.md"
            round_markdown.write_text(
                "# What Changed Since the Prior Review\n\nOne issue remains active.\n",
                encoding="utf-8",
            )
            destination = Path(temporary) / "delivery"
            (destination / "reports").mkdir(parents=True)
            DELIVERY_MODULE.copy_reader_files(target, destination, b"%PDF synthetic")
            projected = destination / "reports" / "round-progress.md"
            self.assertEqual(projected.read_text(encoding="utf-8"), round_markdown.read_text(encoding="utf-8"))
            readme = (destination / "README.md").read_text(encoding="utf-8")
            self.assertIn("[Round progress](reports/round-progress.md)", readme)
            self.assertIn("prior-round progress", readme)

    def test_in_place_delivery_removes_safe_operating_system_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            delivery_root = Path(temporary) / "review"
            target = delivery_root / "supporting"
            shutil.copytree(FIXTURE, target)
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            (delivery_root / ".DS_Store").write_bytes(b"metadata")
            (delivery_root / "reports" / "Thumbs.db").write_bytes(b"metadata")
            rebuilt = subprocess.run(
                [sys.executable, str(DELIVERY), str(target), str(delivery_root), "--replace"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr)
            self.assertFalse((delivery_root / ".DS_Store").exists())
            self.assertFalse((delivery_root / "reports" / "Thumbs.db").exists())

    def test_in_place_delivery_rolls_back_managed_files_on_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            delivery_root = Path(temporary) / "review"
            target = delivery_root / "supporting"
            shutil.copytree(FIXTURE, target)
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            readme = delivery_root / "README.md"
            pdf = delivery_root / "paper-review.pdf"
            readme.write_text("original reader landing page\n", encoding="utf-8")
            pdf.write_bytes(b"original reader PDF bytes")
            before = {readme: readme.read_bytes(), pdf: pdf.read_bytes()}
            with mock.patch.object(
                DELIVERY_MODULE,
                "atomic_write_text",
                side_effect=OSError("injected delivery write failure"),
            ):
                with self.assertRaisesRegex(OSError, "injected delivery write failure"):
                    DELIVERY_MODULE.create_delivery(target, delivery_root, replace=True)
            self.assertEqual(readme.read_bytes(), before[readme])
            self.assertEqual(pdf.read_bytes(), before[pdf])

    def test_structurally_invalid_signed_pdf_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            malformed = b"%PDF-1.7\nnot a real PDF\n%%EOF\n"
            (target / "paper-review.pdf").write_bytes(malformed)
            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["artifacts"]["paper-review.pdf"] = hashlib.sha256(malformed).hexdigest()
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            delivered = subprocess.run(
                [sys.executable, str(DELIVERY), str(target), str(Path(temporary) / "reader")],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(delivered.returncode, 0)
            self.assertIn("structurally readable PDF", delivered.stderr)

    def test_external_delivery_requires_replace_and_keeps_canonical_support(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            finalized = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(finalized.returncode, 0, finalized.stderr)
            destination = Path(temporary) / "reader"
            first = subprocess.run(
                [sys.executable, str(DELIVERY), str(target), str(destination)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            second = subprocess.run(
                [sys.executable, str(DELIVERY), str(target), str(destination)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("--replace", second.stderr)
            replaced = subprocess.run(
                [sys.executable, str(DELIVERY), str(target), str(destination), "--replace"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(replaced.returncode, 0, replaced.stderr)
            self.assertTrue((destination / "supporting" / "finalization.json").is_file())

    def test_external_delivery_renders_pdf_without_mutating_legacy_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            finalized = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(finalized.returncode, 0, finalized.stderr)
            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["artifacts"].pop("paper-review.pdf")
            receipt["artifacts"].pop("evidence/pdf-render-profile.json", None)
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            (target / "paper-review.pdf").unlink()
            profile_path = target / "evidence" / "pdf-render-profile.json"
            if profile_path.exists():
                profile_path.unlink()
            original_receipt = receipt_path.read_bytes()

            destination = Path(temporary) / "reader"
            delivered = subprocess.run(
                [sys.executable, str(DELIVERY), str(target), str(destination)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(delivered.returncode, 0, delivered.stderr)
            self.assertTrue((destination / "paper-review.pdf").read_bytes().startswith(b"%PDF-"))
            self.assertFalse((target / "paper-review.pdf").exists())
            self.assertEqual(receipt_path.read_bytes(), original_receipt)

    def test_delivery_rejects_ancestor_without_mutating_user_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "user-folder"
            target = base / "canonical-review"
            base.mkdir()
            shutil.copytree(FIXTURE, target)
            finalized = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(finalized.returncode, 0, finalized.stderr)
            unrelated = base / "important-user-file.txt"
            unrelated.write_text("preserve me", encoding="utf-8")
            receipt_before = (target / "finalization.json").read_bytes()

            delivered = subprocess.run(
                [sys.executable, str(DELIVERY), str(target), str(base), "--replace"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(delivered.returncode, 0)
            self.assertIn("must not contain", delivered.stderr)
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "preserve me")
            self.assertEqual((target / "finalization.json").read_bytes(), receipt_before)

    def test_quick_legacy_receipt_checks_without_pdf_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_fixture(temporary)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["mode"] = "quick"
            run["comment_policy"]["exhaustive"] = False
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            (target / "evidence" / "coverage.json").unlink()
            (target / "evidence" / "coverage.md").unlink()
            manifest_path = target / "review-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["documents"] = [
                row
                for row in manifest["documents"]
                if row.get("path") != "evidence/coverage.md"
            ]
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            finalized = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(finalized.returncode, 0, finalized.stderr)
            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema_version"], "0.2")
            receipt["artifacts"].pop("paper-review.pdf")
            receipt["artifacts"].pop("evidence/pdf-render-profile.json", None)
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            (target / "paper-review.pdf").unlink()
            profile_path = target / "evidence" / "pdf-render-profile.json"
            if profile_path.exists():
                profile_path.unlink()

            checked = subprocess.run(
                [sys.executable, str(FINALIZER), str(target), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertFalse((target / "paper-review.pdf").exists())

    def test_in_place_delivery_rejects_dirty_parent_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            delivery_root = Path(temporary) / "review"
            target = delivery_root / "supporting"
            shutil.copytree(FIXTURE, target)
            finalized = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(finalized.returncode, 0, finalized.stderr)
            unrelated = delivery_root / "important-user-file.txt"
            unrelated.write_text("preserve me", encoding="utf-8")
            obsolete = delivery_root / "reports" / "obsolete-report.md"
            obsolete.write_text("old output", encoding="utf-8")
            pdf_before = (delivery_root / "paper-review.pdf").read_bytes()

            rebuilt = subprocess.run(
                [sys.executable, str(DELIVERY), str(target), str(delivery_root), "--replace"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rebuilt.returncode, 0)
            self.assertIn("unexpected root entries", rebuilt.stderr)
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "preserve me")
            self.assertEqual(obsolete.read_text(encoding="utf-8"), "old output")
            self.assertEqual((delivery_root / "paper-review.pdf").read_bytes(), pdf_before)


if __name__ == "__main__":
    unittest.main()
