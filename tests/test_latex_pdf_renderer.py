#!/usr/bin/env python3
"""Focused safety, layout-contract, and reproducibility tests for LaTeX PDFs."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from pypdf import PdfReader, PdfWriter


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "latex_pdf_renderer.py"
SPEC = importlib.util.spec_from_file_location("latex_pdf_renderer_test", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


PAPER_TITLE = "Banking Competition and Aggregate Volatility"
ASSESSMENT_DATE = date(2026, 7, 13)


def document(
    markdown: str = "# Referee report\n\n## Overall assessment\n\nClear and constructive.\n",
    *,
    title: str = "Referee report",
    role: str = "referee_report",
) -> object:
    return MODULE.ReviewDocument(title=title, markdown=markdown, role=role)


def one_page_pdf() -> bytes:
    """Return stable, valid compiler output for unit tests that mock TeX."""
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(stream)
    return stream.getvalue()


class LatexMarkdownSafetyTests(unittest.TestCase):
    def test_plain_markdown_is_escaped_while_explicit_math_is_preserved(self) -> None:
        rendered = MODULE.render_inline(
            r"Cost_1 is 50% & robust #1 {today}; **key_value**; $x_i=\alpha_i+1$."
        )

        self.assertIn(r"Cost\_1 is 50\% \& robust \#1 \{today\}", rendered)
        self.assertIn(r"\textbf{key\_value}", rendered)
        self.assertIn(r"$x_i=\alpha_i+1$", rendered)
        self.assertNotIn(r"Cost_1", rendered)

    def test_unsafe_tex_is_rejected_inside_explicit_math(self) -> None:
        unsafe_spans = (
            r"$\input{secrets}$",
            r"\(\write18{touch escaped}\)",
            "$$\\begin{document}x\\end{document}$$",
            "$$\\begin{tikzpicture}x\\end{tikzpicture}$$",
        )
        for markdown in unsafe_spans:
            with self.subTest(markdown=markdown):
                with self.assertRaisesRegex(MODULE.LatexRenderError, "unsafe"):
                    MODULE.markdown_to_latex(markdown)

    def test_unmistakable_legacy_math_is_typeset_without_touching_snake_case_prose(self) -> None:
        rendered = MODULE.render_inline(
            "Compare Λ_{t,t+s}, c_{t+1}, dB/dR_b, and Var(MPK_shock,t); keep finding_id as prose."
        )

        for expression in ("Λ_{t,t+s}", "c_{t+1}", "dB/dR_b"):
            self.assertIn("$" + expression + "$", rendered)
        self.assertIn(r"$\operatorname{Var}(MPK_{\mathrm{shock}},t)$", rendered)
        self.assertIn(r"finding\_id", rendered)


class LatexSourceContractTests(unittest.TestCase):
    def source(self, markdown: str, *, role: str = "referee_report", title: str = "Referee report", page_size: str = "letter") -> str:
        return MODULE.build_latex_source(
            paper_title=PAPER_TITLE,
            assessment_date=ASSESSMENT_DATE,
            documents=[document(markdown, title=title, role=role)],
            page_size=page_size,
        )

    def test_cover_and_metadata_use_the_manuscript_title_without_internal_labels(self) -> None:
        source = self.source("# Referee report\n\n## Assessment\n\nText.\n")

        self.assertIn(r"pdftitle={" + PAPER_TITLE + "}", source)
        self.assertIn(r"pdfsubject={Referee Report}", source)
        self.assertIn(PAPER_TITLE, source)
        self.assertIn("Referee Report", source)
        self.assertIn("July 13, 2026", source)
        for forbidden in (
            "Economic Paper Review",
            "Full review",
            "Author revision",
            "Prepared for author revision",
            "Package verification",
        ):
            self.assertNotIn(forbidden, source)

    def test_running_header_shortens_at_a_word_boundary(self) -> None:
        title = "Imperfect Banking Competition and Macroeconomic Volatility"
        source = MODULE.build_latex_source(
            paper_title=title,
            assessment_date=ASSESSMENT_DATE,
            documents=[document()],
        )

        self.assertIn("Imperfect Banking Competition and Macroeconomic…", source)
        self.assertNotIn("Volatil…", source)

    def test_toc_includes_second_level_sections_but_excludes_individual_h3_comments(self) -> None:
        source = self.source(
            "# Referee report\n\n"
            "## Detailed Comments (1)\n\n"
            "### 1. Identification concern sentinel\n\n"
            "**Issue:** Explain the concern.\n"
        )

        self.assertIn(r"\setcounter{tocdepth}{2}", source)
        self.assertIn(r"\subsection{", source)
        self.assertIn("Detailed Comments (1)", source)
        self.assertIn(r"\subsubsection{", source)
        self.assertIn("Identification concern sentinel", source)
        self.assertNotIn(r"\setcounter{tocdepth}{3}", source)

    def test_letter_and_a4_options_reach_document_class_and_geometry(self) -> None:
        letter = self.source("# Referee report\n\nText.\n", page_size="letter")
        a4 = self.source("# Referee report\n\nText.\n", page_size="a4")

        for expected in (
            r"\documentclass[11pt,oneside,letterpaper]{article}",
            r"\usepackage[letterpaper,",
        ):
            self.assertIn(expected, letter)
            self.assertNotIn(expected, a4)
        for expected in (
            r"\documentclass[11pt,oneside,a4paper]{article}",
            r"\usepackage[a4paper,",
        ):
            self.assertIn(expected, a4)
            self.assertNotIn(expected, letter)

    def test_reader_facing_roles_remove_legacy_writing_and_revision_identifiers(self) -> None:
        editing = self.source(
            "# Writing report\n\n## Detailed Writing Comments\n\nEditing text.\n",
            role="editing_comments",
            title="Writing report",
        )
        revision = self.source(
            "# Revision plan\n\n## P0 - essential before submission\n\n"
            "Use Review Desk and export `review-actions.json`.\n\n"
            "### LOGIC-01: Reconcile the equilibrium claim\n\nAction.\n",
            role="revision_plan",
            title="Revision plan",
        )

        self.assertIn(r"\section{\texorpdfstring{Editing comments}", editing)
        self.assertIn("Detailed Editing Comments", editing)
        self.assertNotIn("Writing report", editing)
        self.assertNotIn("Detailed Writing Comments", editing)
        self.assertIn("Reconcile the equilibrium claim", revision)
        self.assertNotIn("LOGIC-01", revision)
        self.assertNotIn("Review Desk", revision)
        self.assertNotIn("review-actions.json", revision)
        self.assertIn(r"\begin{samepage}", revision)
        self.assertIn(r"\end{samepage}", revision)

    def test_comment_fields_and_closing_plan_fields_have_page_break_protection(self) -> None:
        comment = MODULE.markdown_to_latex(
            "**Relevant text**:\n\n> A quoted sentence.\n\n"
            "**Suggestions**: Repair the bridge.\n\n**Status**: [Pending]\n"
        )
        plan = MODULE.markdown_to_latex(
            "- **Payoff:** Clarifies the result.\n"
            "- **Done when:** The benchmark is explicit.\n"
            "- **Effort:** hours\n- **Dependencies:** None\n",
            role="revision_plan",
        )

        self.assertIn(r"\Needspace{8\baselineskip}", comment)
        self.assertIn(r"\Needspace{9\baselineskip}", comment)
        self.assertIn(r"\Needspace{15\baselineskip}", plan)
        self.assertIn(r"\Needspace{10\baselineskip}", plan)
        self.assertIn(r"\Needspace{5\baselineskip}", plan)
        self.assertNotIn("Pending", comment)

    def test_each_revision_priority_heading_stays_with_its_first_action(self) -> None:
        priorities = (
            ("P0 - priority description", "P0 — priority description"),
            ("P1 - priority description", "P1 — priority description"),
            ("P2 - priority description", "P2 — priority description"),
            ("P7 - custom priority", "P7 — custom priority"),
            ("Custom revision tier", "Custom revision tier"),
        )
        for source_priority, rendered_priority in priorities:
            with self.subTest(priority=source_priority):
                rendered = MODULE.markdown_to_latex(
                    "# Revision plan\n\n"
                    f"## {source_priority}\n\n"
                    "### LOGIC-01: First action title\n\n"
                    "- **Severity:** major\n"
                    "- [ ] **Action:** Repair the first issue.\n"
                    "- **Payoff:** Clarifies the result.\n"
                    "- **Done when:** The repair is verified.\n"
                    "- **Effort:** hours\n"
                    "- **Dependencies:** None\n\n"
                    "### LOGIC-02: Second action title\n\n"
                    "- [ ] **Action:** Repair the second issue.\n",
                    role="revision_plan",
                )

                priority_at = rendered.index(rendered_priority)
                first_action_at = rendered.index("First action title")
                first_action_end = rendered.index(r"\end{samepage}", first_action_at)
                group_start = rendered.rfind(r"\begin{samepage}", 0, priority_at)

                self.assertGreaterEqual(group_start, 0)
                self.assertIn(r"\Needspace{28\baselineskip}", rendered[group_start:priority_at])
                self.assertNotIn(r"\end{samepage}", rendered[priority_at:first_action_at])
                self.assertNotIn(r"\Needspace", rendered[priority_at:first_action_at])
                self.assertLess(rendered.index("Dependencies", first_action_at), first_action_end)
                self.assertIn(r"\begin{samepage}", rendered[first_action_end:])

    def test_wide_prose_table_uses_readable_stacked_projection(self) -> None:
        rendered = MODULE.markdown_to_latex(
            "| Section | Job | Works | Friction | Direction |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| Abstract | State result | Clear mechanism | No magnitude | Add benchmark |\n"
        )

        self.assertNotIn(r"\begin{longtable}", rendered)
        self.assertIn(r"{\sffamily\bfseries\color{ReviewInk} Abstract}", rendered)
        self.assertIn(r"\textbf{Direction.} Add benchmark", rendered)


class LatexToolchainAndProfileTests(unittest.TestCase):
    @staticmethod
    def which_with_all_tex_tools(name: str) -> str | None:
        paths = {
            "latexmk": "/test/bin/latexmk",
            "lualatex": "/test/bin/lualatex",
            "tectonic": "/test/bin/tectonic",
        }
        return paths.get(name)

    def test_auto_selects_one_preferred_toolchain(self) -> None:
        with mock.patch.object(MODULE.shutil, "which", side_effect=self.which_with_all_tex_tools):
            selected = MODULE._toolchains("auto")

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].name, "latexmk-lualatex")
        self.assertEqual(selected[0].engine, "LuaLaTeX")

    def test_auto_does_not_try_another_engine_after_a_compile_error(self) -> None:
        with mock.patch.object(MODULE.shutil, "which", side_effect=self.which_with_all_tex_tools), \
                mock.patch.object(MODULE, "_run_toolchain", return_value=(1, "fatal compile error", 9)) as run:
            with self.assertRaisesRegex(MODULE.LatexRenderError, "latexmk-lualatex: compile failed") as raised:
                MODULE.render_review_pdf(
                    paper_title=PAPER_TITLE,
                    assessment_date=ASSESSMENT_DATE,
                    documents=[document()],
                    renderer="auto",
                )

        self.assertEqual(run.call_count, 1)
        self.assertNotIn("tectonic", str(raised.exception).lower())

    def test_render_profile_is_repeatable_and_contains_no_timing_fields(self) -> None:
        pdf_bytes = one_page_pdf()

        def fake_compile(toolchain: object, *, root: Path, build_dir: Path, environment: object, timeout: int) -> tuple[int, str, int]:
            del toolchain, root, environment, timeout
            (build_dir / "review.pdf").write_bytes(pdf_bytes)
            return 0, "clean compile", 314159

        patches = (
            mock.patch.object(MODULE.shutil, "which", side_effect=self.which_with_all_tex_tools),
            mock.patch.object(MODULE, "_run_toolchain", side_effect=fake_compile),
            mock.patch.object(MODULE, "_compiler_version", return_value="LuaHBTeX test version"),
        )
        with patches[0], patches[1], patches[2]:
            first = MODULE.render_review_pdf(
                paper_title=PAPER_TITLE,
                assessment_date=ASSESSMENT_DATE,
                documents=[document()],
                renderer="auto",
            ).profile.to_dict()
            second = MODULE.render_review_pdf(
                paper_title=PAPER_TITLE,
                assessment_date=ASSESSMENT_DATE,
                documents=[document()],
                renderer="auto",
            ).profile.to_dict()

        self.assertEqual(first, second)
        self.assertEqual(
            set(first),
            {
                "renderer",
                "engine",
                "compiler_version",
                "page_count",
                "page_size",
                "document_count",
                "source_date_epoch",
                "template_sha256",
                "latex_sha256",
                "pdf_sha256",
                "diagnostics",
                "attempts",
            },
        )
        serialized = json.dumps(first, sort_keys=True)
        for volatile_key in ("duration", "elapsed", "started_at", "finished_at", "rendered_at"):
            self.assertNotIn(volatile_key, serialized.lower())


@unittest.skipUnless(shutil.which("lualatex"), "LuaLaTeX is not installed")
class RealLuaLatexSmokeTests(unittest.TestCase):
    def test_priority_heading_and_complete_first_action_share_a_page(self) -> None:
        priority_sentinel = "PRIORITYSENTINEL"
        action_sentinel = "ACTIONSENTINEL"
        end_sentinel = "ENDSENTINEL"
        revision = document(
            "# Revision plan\n\n"
            "## How to use this plan\n\n"
            + ("filler " * 419)
            + "\n\n"
            f"## P1 - {priority_sentinel}\n\n"
            f"### PLAN-01: {action_sentinel}\n\n"
            "- **Severity:** major\n"
            "- [ ] **Action:** Repair the complete priority item.\n"
            "- **Payoff:** Keeps the revision workflow readable.\n"
            "- **Done when:** The full item remains together.\n"
            "- **Effort:** hours\n"
            f"- **Dependencies:** {end_sentinel}\n",
            title="Revision plan",
            role="revision_plan",
        )

        result = MODULE.render_review_pdf(
            paper_title=PAPER_TITLE,
            assessment_date=ASSESSMENT_DATE,
            documents=[revision],
            renderer="lualatex",
            page_size="letter",
            timeout=90,
        )
        reader = PdfReader(io.BytesIO(result.pdf_bytes))

        def last_page_containing(sentinel: str) -> int:
            matches = [
                page_number
                for page_number, page in enumerate(reader.pages)
                if sentinel in (page.extract_text() or "")
            ]
            self.assertTrue(matches, f"missing PDF sentinel: {sentinel}")
            return matches[-1]

        pages = {
            last_page_containing(priority_sentinel),
            last_page_containing(action_sentinel),
            last_page_containing(end_sentinel),
        }
        self.assertEqual(len(pages), 1)

    def test_real_compile_is_professional_letter_pdf_and_reproducible(self) -> None:
        comment_sentinel = "Individual concern excluded from contents"
        report = document(
            "# Referee report\n\n"
            "## Overall assessment\n\n"
            "The argument is promising, and the main revision is clearly actionable.\n\n"
            "## Detailed Comments (1)\n\n"
            f"### 1. {comment_sentinel}\n\n"
            "**Issue:** The mechanism needs one additional bridge.\n\n"
            r"**Relevant text:** The response is $y_t=\alpha+\beta x_t$." "\n\n"
            "**Concern and suggestions:** State the benchmark and show the comparison.\n\n"
            "**Status:** Pending\n"
        )

        first = MODULE.render_review_pdf(
            paper_title=PAPER_TITLE,
            assessment_date=ASSESSMENT_DATE,
            documents=[report],
            renderer="lualatex",
            page_size="letter",
            timeout=90,
        )
        second = MODULE.render_review_pdf(
            paper_title=PAPER_TITLE,
            assessment_date=ASSESSMENT_DATE,
            documents=[report],
            renderer="lualatex",
            page_size="letter",
            timeout=90,
        )

        self.assertEqual(first.pdf_bytes, second.pdf_bytes)
        self.assertEqual(first.profile, second.profile)
        reader = PdfReader(io.BytesIO(first.pdf_bytes))
        self.assertGreaterEqual(len(reader.pages), 3)
        self.assertEqual(reader.metadata.title, PAPER_TITLE)
        first_page = reader.pages[0]
        self.assertAlmostEqual(float(first_page.mediabox.width), 612.0, delta=1.0)
        self.assertAlmostEqual(float(first_page.mediabox.height), 792.0, delta=1.0)
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn(PAPER_TITLE, full_text)
        self.assertIn("Referee Report", full_text)
        self.assertIn("Overall assessment", full_text)
        self.assertIn(comment_sentinel, full_text)
        contents_text = reader.pages[1].extract_text() or ""
        self.assertIn("Overall assessment", contents_text)
        self.assertIn("Detailed Comments (1)", contents_text)
        self.assertNotIn(comment_sentinel, contents_text)
        for forbidden in ("Economic Paper Review", "Full review", "Author revision"):
            self.assertNotIn(forbidden, full_text)


if __name__ == "__main__":
    unittest.main()
