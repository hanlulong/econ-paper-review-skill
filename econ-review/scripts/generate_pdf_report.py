#!/usr/bin/env python3
"""Generate a deterministic, professional PDF from an econ-review package."""

from __future__ import annotations

import argparse
import html
import json
import os
import platform
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import (  # noqa: E402
    atomic_write_bytes,
    canonical_portable_path,
    is_link_or_junction,
    strict_json_load,
)
from latex_pdf_renderer import (  # noqa: E402
    LatexRenderError,
    RenderProfile,
    ReviewDocument,
    SUPPORTED_RENDERERS as LATEX_RENDERERS,
    render_review_pdf,
    select_healthy_renderer,
)

try:
    import reportlab
    from reportlab import rl_config
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4, LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        BaseDocTemplate,
        Flowable,
        Frame,
        KeepTogether,
        ListFlowable,
        ListItem,
        PageBreak,
        PageTemplate,
        Paragraph,
        Preformatted,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.platypus.tableofcontents import TableOfContents
    from reportlab.platypus.doctemplate import LayoutError
except ImportError as exc:  # pragma: no cover - exercised through the CLI error path
    raise SystemExit(
        "reportlab is required for PDF reports; install the skill's core requirements"
    ) from exc


rl_config.invariant = 1

GROUP_ORDER = {"overview": 0, "reports": 1, "plan": 2, "audit": 3}
PORTABLE_OUTPUT_NAME = "paper-review.pdf"
RENDER_PROFILE_PATH = "evidence/pdf-render-profile.json"
SUPPORTED_RENDERERS = ("auto", "reportlab", *LATEX_RENDERERS[1:])
NAVIGATION_BLOCK = re.compile(
    r"<!-- review-navigation:start -->.*?<!-- review-navigation:end -->",
    re.DOTALL,
)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
DERIVED_EVIDENCE_PREFIX = re.compile(
    r"^\[(?:Reviewer observation|Reviewer comparison|Figure observation|"
    r"Table observation|Checked absence|Computation)\]\s*",
    re.IGNORECASE,
)
RENDERED_TRANSCRIPTION_PREFIX = re.compile(
    r"^\[Rendered transcription\]\s*",
    re.IGNORECASE,
)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s+|(\d+)[.)]\s+)(.+)$")
TABLE_DIVIDER_CELL = re.compile(r"^:?-{3,}:?$")
WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul", "clock$",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class FontSet:
    body: str
    bold: str
    italic: str
    mono: str


@dataclass(frozen=True)
class DocumentEntry:
    title: str
    group: str
    path: str
    order: int


class SectionBreak(Flowable):
    """A compact colored rule used between major report documents."""

    def __init__(self, width: float, color: colors.Color) -> None:
        super().__init__()
        self.width = width
        self.height = 4
        self.color = color

    def draw(self) -> None:
        self.canv.setFillColor(self.color)
        self.canv.roundRect(0, 0, self.width, 3, 1.5, fill=1, stroke=0)


class ReviewDocTemplate(BaseDocTemplate):
    """Document template with deterministic outline entries and a live TOC."""

    def __init__(
        self,
        *args: Any,
        font_set: FontSet,
        metadata_title: str,
        metadata_subject: str,
        **kwargs: Any,
    ) -> None:
        self.font_set = font_set
        self.metadata_title = metadata_title
        self.metadata_subject = metadata_subject
        super().__init__(*args, **kwargs)
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="body",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(PageTemplate(id="review", frames=[frame], onPage=self._page))

    def _page(self, canvas: Any, doc: Any) -> None:
        canvas.setTitle(self.metadata_title)
        canvas.setAuthor("econ-review")
        canvas.setSubject(self.metadata_subject)
        page = canvas.getPageNumber()
        if page == 1:
            return
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D8DEE9"))
        canvas.setLineWidth(0.5)
        canvas.line(self.leftMargin, 0.56 * inch, self.pagesize[0] - self.rightMargin, 0.56 * inch)
        canvas.setFillColor(colors.HexColor("#5A6573"))
        canvas.setFont(self.font_set.body, 8)
        canvas.drawString(self.leftMargin, 0.36 * inch, "ECON REVIEW")
        canvas.drawRightString(self.pagesize[0] - self.rightMargin, 0.36 * inch, f"Page {page}")
        canvas.restoreState()

    def afterFlowable(self, flowable: Flowable) -> None:
        if not isinstance(flowable, Paragraph):
            return
        level = getattr(flowable, "_toc_level", None)
        if level is None:
            return
        text = flowable.getPlainText()
        key = getattr(flowable, "_bookmark_key", None)
        if not isinstance(key, str):
            return
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=max(0, min(int(level), 3)), closed=False)
        if getattr(flowable, "_include_in_toc", False):
            self.notify("TOCEntry", (int(level), text, self.page, key))


def _safe_font_file(path: Path) -> Path | None:
    if is_link_or_junction(path):
        return None
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError:
        return None
    return resolved if resolved.is_file() and not resolved.is_symlink() else None


def _packaged_font_paths() -> tuple[Path, Path, Path]:
    """Return ReportLab's fixed, commercially redistributable Vera fonts."""
    root = Path(reportlab.__file__).resolve().parent / "fonts"
    return root / "Vera.ttf", root / "VeraBd.ttf", root / "VeraIt.ttf"


def _register_font_set(
    body_path: Path,
    bold_path: Path,
    italic_path: Path,
    mono_path: Path | None,
) -> FontSet | None:
    resolved_body = _safe_font_file(body_path)
    resolved_bold = _safe_font_file(bold_path)
    resolved_italic = _safe_font_file(italic_path)
    resolved_mono = _safe_font_file(mono_path) if mono_path is not None else resolved_body
    if not all((resolved_body, resolved_bold, resolved_italic)):
        return None
    if resolved_mono is None:
        return None
    try:
        pdfmetrics.registerFont(TTFont("ERBody", str(resolved_body)))
        pdfmetrics.registerFont(TTFont("ERBold", str(resolved_bold)))
        pdfmetrics.registerFont(TTFont("ERItalic", str(resolved_italic)))
        pdfmetrics.registerFont(TTFont("ERMono", str(resolved_mono)))
        pdfmetrics.registerFontFamily(
            "ERBody", normal="ERBody", bold="ERBold", italic="ERItalic", boldItalic="ERBold"
        )
        return FontSet("ERBody", "ERBold", "ERItalic", "ERMono")
    except Exception:
        return None


def _font_candidates(extra_dir: Path | None = None) -> list[tuple[Path, Path, Path, Path]]:
    candidates: list[tuple[Path, Path, Path, Path]] = []
    if extra_dir is not None:
        candidates.extend([
            (
                extra_dir / "DejaVuSans.ttf",
                extra_dir / "DejaVuSans-Bold.ttf",
                extra_dir / "DejaVuSans-Oblique.ttf",
                extra_dir / "DejaVuSansMono.ttf",
            ),
            (
                extra_dir / "Arial.ttf",
                extra_dir / "Arial Bold.ttf",
                extra_dir / "Arial Italic.ttf",
                extra_dir / "Courier New.ttf",
            ),
        ])
    if platform.system() == "Windows":
        windows_root = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT")
        if windows_root:
            fonts = Path(windows_root) / "Fonts"
            candidates.append((
                fonts / "arial.ttf", fonts / "arialbd.ttf",
                fonts / "ariali.ttf", fonts / "consola.ttf",
            ))
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            fonts = Path(local_app_data) / "Microsoft" / "Windows" / "Fonts"
            candidates.extend([
                (
                    fonts / "DejaVuSans.ttf", fonts / "DejaVuSans-Bold.ttf",
                    fonts / "DejaVuSans-Oblique.ttf", fonts / "DejaVuSansMono.ttf",
                ),
                (
                    fonts / "arial.ttf", fonts / "arialbd.ttf",
                    fonts / "ariali.ttf", fonts / "consola.ttf",
                ),
            ])
    candidates.extend([
        (
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
            Path("/System/Library/Fonts/Supplemental/Courier New.ttf"),
        ),
        (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/ariali.ttf"),
            Path("C:/Windows/Fonts/consola.ttf"),
        ),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
        ),
        (
            Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/dejavu/DejaVuSans-Oblique.ttf"),
            Path("/usr/share/fonts/dejavu/DejaVuSansMono.ttf"),
        ),
    ])
    return candidates


def register_fonts(font_dir: Path | None = None) -> FontSet:
    """Register a fixed cross-platform font set, with explicit overrides only."""
    if font_dir is not None:
        for candidate in _font_candidates(font_dir)[:2]:
            registered = _register_font_set(*candidate)
            if registered is not None:
                return registered
    packaged = _register_font_set(*_packaged_font_paths(), None)
    if packaged is not None:
        return packaged
    for candidate in _font_candidates():
        registered = _register_font_set(*candidate)
        if registered is not None:
            return registered
    return FontSet("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier")


def _load_object(path: Path) -> dict[str, Any]:
    value = strict_json_load(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _portable_document_path(root: Path, raw: str) -> Path:
    portable = canonical_portable_path(raw)
    relative = Path(portable)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.casefold() != ".md":
        raise ValueError(f"manifest document path is unsafe: {raw}")
    if any(part.split(".", 1)[0].casefold() in WINDOWS_RESERVED for part in relative.parts):
        raise ValueError(f"manifest document path is not Windows-portable: {raw}")
    candidate = root / relative
    if is_link_or_junction(candidate) or not candidate.is_file():
        raise ValueError(f"manifest document does not exist as a regular file: {raw}")
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError(f"manifest document resolves outside the review package: {raw}") from exc
    return candidate


def reject_package_links(root: Path) -> None:
    if is_link_or_junction(root) or not root.is_dir():
        raise ValueError("review directory must be a real directory")
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in names + files:
            path = base / name
            if is_link_or_junction(path):
                raise ValueError(
                    "review package may not contain links or junctions: "
                    + str(path.relative_to(root))
                )


def document_entries(review_dir: Path) -> list[DocumentEntry]:
    manifest_path = review_dir / "review-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("review-manifest.json is required for the all-in-one PDF")
    manifest = _load_object(manifest_path)
    rows = manifest.get("documents")
    if not isinstance(rows, list) or not rows:
        raise ValueError("review-manifest.json.documents must be a non-empty array")
    entries: list[DocumentEntry] = []
    seen_paths: set[str] = set()
    for index, row in enumerate(rows):
        context = f"review-manifest.json.documents[{index}]"
        if not isinstance(row, dict):
            raise ValueError(f"{context} must be an object")
        title, group, raw_path, order = (
            row.get("title"), row.get("group"), row.get("path"), row.get("order")
        )
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"{context}.title must be non-empty")
        if group not in GROUP_ORDER:
            raise ValueError(f"{context}.group is unsupported")
        if not isinstance(raw_path, str):
            raise ValueError(f"{context}.path must be a string")
        if not isinstance(order, int) or isinstance(order, bool):
            raise ValueError(f"{context}.order must be an integer")
        _portable_document_path(review_dir, raw_path)
        portable = canonical_portable_path(raw_path)
        if portable.casefold() in seen_paths:
            raise ValueError(f"duplicate or case-ambiguous manifest path: {raw_path}")
        seen_paths.add(portable.casefold())
        # README is the folder landing page and repeats the PDF cover. Internal
        # audits remain available under supporting/ but are never promoted into
        # the primary author report merely because they are Markdown.
        if group == "audit" or portable == "README.md":
            continue
        entries.append(DocumentEntry(title.strip(), group, portable, order))
    entries.sort(key=lambda row: (GROUP_ORDER[row.group], row.order, row.title.casefold(), row.path))
    required = {"report.md", "fix-plan.md"}
    present = {entry.path for entry in entries}
    missing = sorted(required - present)
    if missing:
        raise ValueError("review manifest omits required reader outputs: " + ", ".join(missing))
    if (review_dir / "editing-comments.md").exists() and "editing-comments.md" not in present:
        raise ValueError("review manifest omits the available editing-comments.md")
    return entries


def _clean_text(value: str) -> str:
    return (
        value.replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
        .replace("\u00a0", " ")
    )


def inline_markup(value: str, fonts: FontSet) -> str:
    """Convert a deliberately small, safe Markdown inline subset."""
    value = _clean_text(value).strip()
    escaped = html.escape(value, quote=True)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<link href="\2" color="#2457A6">\1</link>',
        escaped,
    )
    # Relative report links cannot be opened reliably from a standalone PDF.
    # Show a clean label; the same documents remain reachable through the TOC
    # and outline instead of leaking raw Markdown syntax.
    escaped = re.sub(
        r"(?<!!)\[([^\]]+)\]\((?!https?://)[^)]+\)",
        r"\1",
        escaped,
    )
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", escaped)
    escaped = re.sub(
        r"`([^`\n]+)`",
        lambda match: f'<font name="{fonts.mono}">{match.group(1)}</font>',
        escaped,
    )
    return escaped


def styles(fonts: FontSet) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    navy = colors.HexColor("#17324D")
    blue = colors.HexColor("#2457A6")
    charcoal = colors.HexColor("#25303B")
    muted = colors.HexColor("#657281")
    output = {
        "body": ParagraphStyle(
            "ERBody", parent=base["BodyText"], fontName=fonts.body, fontSize=9.4,
            leading=13.2, textColor=charcoal, spaceAfter=7, allowWidows=0, allowOrphans=0,
        ),
        "small": ParagraphStyle(
            "ERSmall", parent=base["BodyText"], fontName=fonts.body, fontSize=8,
            leading=10.5, textColor=muted, spaceAfter=4,
        ),
        "cover_brand": ParagraphStyle(
            "ERCoverBrand", parent=base["Normal"], fontName=fonts.bold, fontSize=10,
            leading=12, textColor=blue, tracking=1.5, alignment=TA_LEFT,
        ),
        "cover_title": ParagraphStyle(
            "ERCoverTitle", parent=base["Title"], fontName=fonts.bold, fontSize=27,
            leading=31, textColor=navy, alignment=TA_LEFT, spaceAfter=12,
        ),
        "cover_subtitle": ParagraphStyle(
            "ERCoverSubtitle", parent=base["BodyText"], fontName=fonts.body, fontSize=12,
            leading=17, textColor=muted, spaceAfter=12,
        ),
        "doc_title": ParagraphStyle(
            "ERDocTitle", parent=base["Heading1"], fontName=fonts.bold, fontSize=21,
            leading=25, textColor=navy, spaceBefore=2, spaceAfter=12, keepWithNext=True,
        ),
        "h1": ParagraphStyle(
            "ERH1", parent=base["Heading1"], fontName=fonts.bold, fontSize=15,
            leading=19, textColor=navy, spaceBefore=14, spaceAfter=7, keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "ERH2", parent=base["Heading2"], fontName=fonts.bold, fontSize=12,
            leading=15, textColor=blue, spaceBefore=11, spaceAfter=5, keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "ERH3", parent=base["Heading3"], fontName=fonts.bold, fontSize=10.4,
            leading=13.2, textColor=charcoal, spaceBefore=9, spaceAfter=4, keepWithNext=True,
        ),
        "quote": ParagraphStyle(
            "ERQuote", parent=base["BodyText"], fontName=fonts.italic, fontSize=8.8,
            leading=12.2, textColor=colors.HexColor("#34495E"), leftIndent=2,
            rightIndent=2, spaceAfter=0,
        ),
        "code": ParagraphStyle(
            "ERCode", parent=base["Code"], fontName=fonts.mono, fontSize=7.7,
            leading=10, textColor=charcoal, leftIndent=5, rightIndent=5, spaceAfter=8,
        ),
        "toc_title": ParagraphStyle(
            "ERTOCTitle", parent=base["Heading1"], fontName=fonts.bold, fontSize=18,
            leading=22, textColor=navy, spaceAfter=12,
        ),
    }
    return output


def heading_paragraph(
    text: str,
    level: int,
    style_map: dict[str, ParagraphStyle],
    *,
    include_in_toc: bool,
) -> Paragraph:
    global HEADING_SERIAL
    key = "doc_title" if level == 0 else "h1" if level == 1 else "h2" if level == 2 else "h3"
    paragraph = Paragraph(inline_markup(text, FONT_STATE), style_map[key])
    paragraph._toc_level = min(level, 3)  # type: ignore[attr-defined]
    paragraph._include_in_toc = include_in_toc  # type: ignore[attr-defined]
    paragraph._bookmark_key = f"section-{HEADING_SERIAL}"  # type: ignore[attr-defined]
    HEADING_SERIAL += 1
    return paragraph


def _table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]


def _is_table_divider(line: str) -> bool:
    cells = _table_row(line)
    return bool(cells) and all(TABLE_DIVIDER_CELL.fullmatch(cell) for cell in cells)


def markdown_table(
    lines: list[str], style_map: dict[str, ParagraphStyle], width: float
) -> Table:
    rows = [_table_row(line) for line in lines if not _is_table_divider(line)]
    column_count = max(len(row) for row in rows)
    rows = [row + [""] * (column_count - len(row)) for row in rows]
    cell_style = ParagraphStyle(
        "ERTableCell", parent=style_map["small"], fontSize=7.4, leading=9.2,
        textColor=colors.HexColor("#25303B"), spaceAfter=0,
    )
    head_style = ParagraphStyle(
        "ERTableHead", parent=cell_style, fontName=FONT_STATE.bold,
        textColor=colors.white,
    )
    data = [
        [Paragraph(inline_markup(cell, FONT_STATE), head_style if row_index == 0 else cell_style)
         for cell in row]
        for row_index, row in enumerate(rows)
    ]
    common_widths = {
        4: [0.19, 0.19, 0.20, 0.42],
        5: [0.17, 0.17, 0.16, 0.16, 0.34],
        6: [0.17, 0.17, 0.12, 0.14, 0.10, 0.30],
        7: [0.12, 0.13, 0.13, 0.17, 0.10, 0.14, 0.21],
    }
    proportions = common_widths.get(column_count, [1 / column_count] * column_count)
    table = Table(
        data,
        colWidths=[width * proportion for proportion in proportions],
        repeatRows=1,
        splitByRow=1,
        splitInRow=1,
        hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CCD5DF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8FA")]),
    ]))
    return table


def quote_block(text: str, style_map: dict[str, ParagraphStyle], width: float) -> Table:
    quote = Paragraph(inline_markup(text, FONT_STATE).replace("\n", "<br/>"), style_map["quote"])
    table = Table([[quote]], colWidths=[width - 18], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F6FA")),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD8E5")),
        ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor("#4E7DB4")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def markdown_flowables(
    raw: str,
    style_map: dict[str, ParagraphStyle],
    width: float,
    *,
    document_title: str,
    include_section_headings_in_toc: bool,
) -> list[Flowable]:
    raw = NAVIGATION_BLOCK.sub("", raw)
    raw = HTML_COMMENT.sub("", raw)
    lines = raw.splitlines()
    flowables: list[Flowable] = []
    index = 0
    first_heading = True

    def paragraph_from(parts: Iterable[str]) -> None:
        text = " ".join(part.strip() for part in parts if part.strip())
        if re.match(r"^\*\*Status:?\*\*", text, re.IGNORECASE):
            # Keep workflow status in the Markdown and Review Desk. It cannot
            # change in a static PDF and otherwise reads as unfinished copy.
            return
        if text:
            flowables.append(Paragraph(inline_markup(text, FONT_STATE), style_map["body"]))

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith("```"):
            fence = stripped[:3]
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(fence):
                code.append(_clean_text(lines[index]))
                index += 1
            index += int(index < len(lines))
            flowables.append(Preformatted("\n".join(code), style_map["code"], maxLineLength=100))
            continue
        match = HEADING.match(line)
        if match:
            level = len(match.group(1))
            text = re.sub(r"\s+#+$", "", match.group(2)).strip()
            if re.match(r"^Detailed(?: Editing)? Comments \(\d+\)$", text):
                flowables.append(PageBreak())
            if first_heading and level == 1:
                text = document_title or text
                flowables.append(heading_paragraph(
                    text,
                    0,
                    style_map,
                    include_in_toc=True,
                ))
                first_heading = False
            else:
                outline_level = max(1, level - 1)
                flowables.append(heading_paragraph(
                    text,
                    outline_level,
                    style_map,
                    include_in_toc=(
                        include_section_headings_in_toc
                        and level == 2
                    ),
                ))
            index += 1
            continue
        first_heading = False
        if stripped.startswith(">"):
            quoted: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quoted.append(re.sub(r"^\s*>\s?", "", lines[index]))
                index += 1
            quoted_text = "\n".join(quoted)
            if DERIVED_EVIDENCE_PREFIX.match(quoted_text):
                # Archived reports sometimes stored reviewer-created evidence
                # as a block quote with an internal provenance token. Current
                # reports render it as an unquoted note. Match that presentation
                # without rewriting the immutable legacy package.
                note = DERIVED_EVIDENCE_PREFIX.sub("", quoted_text, count=1)
                flowables.append(
                    Paragraph(
                        inline_markup(note, FONT_STATE).replace("\n", "<br/>"),
                        style_map["body"],
                    )
                )
            else:
                quoted_text = RENDERED_TRANSCRIPTION_PREFIX.sub("", quoted_text, count=1)
                flowables.append(quote_block(quoted_text, style_map, width))
            flowables.append(Spacer(1, 7))
            continue
        if "|" in line and index + 1 < len(lines) and _is_table_divider(lines[index + 1]):
            table_lines = [line, lines[index + 1]]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            flowables.append(markdown_table(table_lines, style_map, width))
            flowables.append(Spacer(1, 9))
            continue
        list_match = LIST_ITEM.match(line)
        if list_match:
            ordered = bool(list_match.group(1))
            items: list[ListItem] = []
            while index < len(lines):
                current = LIST_ITEM.match(lines[index])
                if not current or bool(current.group(1)) != ordered:
                    break
                value = re.sub(
                    r"^\[[ xX]\]\s*",
                    lambda match: "Completed - " if "x" in match.group(0).lower() else "",
                    current.group(2),
                )
                items.append(ListItem(
                    Paragraph(inline_markup(value, FONT_STATE), style_map["body"]),
                    leftIndent=12,
                ))
                index += 1
            flowables.append(ListFlowable(
                items,
                bulletType="1" if ordered else "bullet",
                # ReportLab's symbolic bullet is mis-mapped as a visible "1"
                # by some embedded TrueType fonts. An ASCII hyphen is stable in
                # both rendered pages and extracted text on every platform.
                start="1" if ordered else "-",
                leftIndent=18,
                bulletFontName=FONT_STATE.body,
                bulletFontSize=8,
                spaceAfter=6,
            ))
            continue
        if stripped in {"---", "***", "___"}:
            flowables.append(SectionBreak(width, colors.HexColor("#D8DEE9")))
            flowables.append(Spacer(1, 7))
            index += 1
            continue
        if stripped.startswith("$$") or stripped.startswith("\\["):
            math_lines = [stripped]
            index += 1
            terminator = "$$" if stripped.startswith("$$") else "\\]"
            while index < len(lines) and not lines[index].strip().endswith(terminator):
                math_lines.append(_clean_text(lines[index]))
                index += 1
            if index < len(lines):
                math_lines.append(_clean_text(lines[index]))
                index += 1
            flowables.append(Preformatted("\n".join(math_lines), style_map["code"], maxLineLength=100))
            continue
        paragraph_lines = [line]
        index += 1
        while index < len(lines):
            candidate = lines[index]
            if (
                not candidate.strip()
                or HEADING.match(candidate)
                or candidate.strip().startswith((">", "```"))
                or LIST_ITEM.match(candidate)
                or ("|" in candidate and index + 1 < len(lines) and _is_table_divider(lines[index + 1]))
            ):
                break
            paragraph_lines.append(candidate)
            index += 1
        paragraph_from(paragraph_lines)
    return flowables


def _plain_summary(markdown: str, limit: int = 560) -> str:
    clean = NAVIGATION_BLOCK.sub("", markdown)
    clean = HTML_COMMENT.sub("", clean)
    assessment = re.search(
        r"^## Overall assessment\s*$\s*(.+?)(?=\n\s*\n|\n## |\Z)",
        clean,
        re.MULTILINE | re.DOTALL,
    )
    if assessment:
        candidate = " ".join(
            line.strip(" >#*`\t") for line in assessment.group(1).splitlines()
        ).strip()
        candidate = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", candidate)
        candidate = re.sub(r"\s+", " ", candidate)
        if candidate:
            return candidate if len(candidate) <= limit else candidate[: limit - 1].rsplit(" ", 1)[0] + "..."
    paragraphs = [
        " ".join(line.strip(" >#*`\t") for line in block.splitlines()).strip()
        for block in re.split(r"\n\s*\n", clean)
    ]
    for paragraph in paragraphs:
        if paragraph and not paragraph.lower().startswith((
            "start here", "referee report", "overall assessment",
        )):
            paragraph = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", paragraph)
            paragraph = re.sub(r"\s+", " ", paragraph)
            return paragraph if len(paragraph) <= limit else paragraph[: limit - 1].rsplit(" ", 1)[0] + "..."
    return "A paper review prepared to support a focused revision."


def _plausible_paper_title(value: str) -> str | None:
    """Return a clean title candidate, rejecting headings and equation debris.

    PDF extraction often leaves the visible title as an unheaded first block.
    It can also emit a bare ``#`` beside a display equation much later in the
    manuscript.  A title fallback must therefore prefer human prose and never
    allow a Markdown-heading regex to cross a line boundary.
    """
    candidate = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    candidate = re.sub(r"\s+", " ", candidate).strip(" #*`")
    if not 8 <= len(candidate) <= 240:
        return None
    if candidate.casefold() in {
        "abstract", "introduction", "manuscript", "paper", "source",
        "references", "appendix",
    }:
        return None
    letters = re.findall(r"[^\W\d_]", candidate, flags=re.UNICODE)
    words = re.findall(r"[^\W\d_][^\s]*", candidate, flags=re.UNICODE)
    equation_marks = sum(candidate.count(mark) for mark in "=<>∑∫√±×÷{}[]_")
    if len(letters) < 6 or len(words) < 2 or equation_marks > max(2, len(words) // 2):
        return None
    if candidate.startswith(("$", "\\[", "\\(", "#")):
        return None
    return candidate


def _markdown_title(markdown: str) -> str | None:
    clean = HTML_COMMENT.sub("", markdown)
    # Horizontal whitespace is deliberate.  ``\s`` would cross from a bare
    # hash line into a later equation and turn that equation into the cover.
    for heading in re.finditer(r"^#[ \t]+(.+?)[ \t]*$", clean, re.MULTILINE):
        if candidate := _plausible_paper_title(heading.group(1)):
            return candidate

    first_heading = re.search(r"^#{1,6}[ \t]+", clean, re.MULTILINE)
    preamble = clean[: first_heading.start()] if first_heading else clean
    for block in re.split(r"\n[ \t]*\n", preamble):
        if candidate := _plausible_paper_title(block):
            return candidate
    return None


def paper_identity(review_dir: Path, run: dict[str, Any]) -> tuple[str, str, str | None]:
    title = run.get("paper_title")
    if not isinstance(title, str) or not title.strip():
        title = None
        manifest = _load_object(review_dir / "evidence" / "source-manifest.json")
        sources = manifest.get("sources") if isinstance(manifest.get("sources"), list) else []
        manuscript = next(
            (row for row in sources if isinstance(row, dict) and row.get("role") == "manuscript"),
            None,
        )
        if isinstance(manuscript, dict):
            extraction = manuscript.get("extraction")
            raw_path = extraction.get("path") if isinstance(extraction, dict) else None
            if not isinstance(raw_path, str):
                raw_path = manuscript.get("path")
            if isinstance(raw_path, str) and raw_path.casefold().endswith(".md"):
                source_path = _portable_document_path(review_dir, raw_path)
                title = _markdown_title(source_path.read_text(encoding="utf-8"))
            if title is None and isinstance(raw_path, str):
                stem = Path(raw_path).stem.replace("_", " ").replace("-", " ").strip()
                if stem.casefold() not in {"original", "manuscript", "paper", "source"}:
                    title = stem.title()
    paper_title = title.strip() if isinstance(title, str) and title.strip() else "Untitled manuscript"
    review_id = str(run.get("review_id") or "unidentified review")
    assessment_date = run.get("assessment_date")
    return paper_title, review_id, assessment_date if isinstance(assessment_date, str) else None


def cover_flowables(
    review_dir: Path,
    style_map: dict[str, ParagraphStyle],
    width: float,
) -> list[Flowable]:
    run = _load_object(review_dir / "run.json")
    paper_title, _review_id, assessment_date = paper_identity(review_dir, run)
    date_line = f"Assessment date: {assessment_date}" if assessment_date else None
    return [
        Spacer(1, 1.0 * inch),
        SectionBreak(width * 0.16, colors.HexColor("#2457A6")),
        Spacer(1, 0.42 * inch),
        Paragraph(inline_markup(paper_title, FONT_STATE), style_map["cover_title"]),
        Spacer(1, 0.22 * inch),
        Paragraph("Referee Report", style_map["cover_subtitle"]),
        *(
            [Spacer(1, 0.12 * inch), Paragraph(inline_markup(date_line, FONT_STATE), style_map["small"])]
            if date_line
            else []
        ),
        PageBreak(),
    ]


def build_pdf(review_dir: Path, output: Path, *, page_size: str, font_dir: Path | None) -> bytes:
    """Build the portable ReportLab fallback.

    This function remains public for callers that explicitly need the
    dependency-light fallback.  Normal CLI generation goes through
    :func:`build_professional_pdf`, which prefers the LaTeX renderer whenever
    a supported TeX engine is installed.
    """
    global FONT_STATE, HEADING_SERIAL
    review_dir = review_dir.expanduser().absolute()
    reject_package_links(review_dir)
    review_dir = review_dir.resolve(strict=True)
    HEADING_SERIAL = 0
    FONT_STATE = register_fonts(font_dir)
    style_map = styles(FONT_STATE)
    pagesize = LETTER if page_size == "letter" else A4
    left = right = 0.72 * inch
    top = 0.68 * inch
    bottom = 0.74 * inch
    width = pagesize[0] - left - right
    entries = document_entries(review_dir)
    run = _load_object(review_dir / "run.json")
    paper_title, _review_id, _assessment_date = paper_identity(review_dir, run)
    metadata_title = paper_title
    metadata_subject = "Referee Report"

    with tempfile.TemporaryDirectory(prefix="econ-review-pdf-") as temporary:
        temporary_pdf = Path(temporary) / PORTABLE_OUTPUT_NAME
        doc = ReviewDocTemplate(
            str(temporary_pdf),
            pagesize=pagesize,
            leftMargin=left,
            rightMargin=right,
            topMargin=top,
            bottomMargin=bottom,
            title="Referee Report",
            author="econ-review",
            font_set=FONT_STATE,
            metadata_title=metadata_title,
            metadata_subject=metadata_subject,
        )
        story: list[Flowable] = cover_flowables(review_dir, style_map, width)
        story.append(Paragraph("Contents", style_map["toc_title"]))
        toc = TableOfContents()
        toc.levelStyles = [
            ParagraphStyle(
                f"ERTOC{level}",
                fontName=FONT_STATE.bold if level == 0 else FONT_STATE.body,
                fontSize=11 if level == 0 else 9.4,
                leading=15 if level == 0 else 13,
                leftIndent=level * 16,
                firstLineIndent=0,
                textColor=colors.HexColor("#17324D") if level == 0 else colors.HexColor("#4D5967"),
                spaceBefore=8 if level == 0 else 3,
                spaceAfter=2 if level == 0 else 0,
            )
            for level in range(4)
        ]
        story.extend([toc, PageBreak()])
        for entry_index, entry in enumerate(entries):
            if entry_index:
                story.append(PageBreak())
            story.append(SectionBreak(width, colors.HexColor("#2457A6")))
            story.append(Spacer(1, 8))
            markdown = _portable_document_path(review_dir, entry.path).read_text(encoding="utf-8")
            story.extend(markdown_flowables(
                markdown,
                style_map,
                width,
                document_title=entry.title,
                include_section_headings_in_toc=entry.path in {
                    "report.md", "editing-comments.md", "fix-plan.md",
                    "evidence/round-reconciliation.md",
                },
            ))
        doc.multiBuild(story)
        data = temporary_pdf.read_bytes()
    if not data.startswith(b"%PDF-") or len(data) < 1000:
        raise ValueError("PDF generation did not produce a valid document")
    return data


def _review_date(raw: str | None, override: date | None) -> date:
    if override is not None:
        return override
    if not raw:
        raise ValueError(
            "assessment_date is absent; pass --assessment-date YYYY-MM-DD "
            "after verifying the review date"
        )
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("run.json.assessment_date must use YYYY-MM-DD") from exc


def _latex_is_available(renderer: str) -> bool:
    if renderer == "latexmk-lualatex":
        return bool(shutil.which("latexmk") and shutil.which("lualatex"))
    if renderer == "lualatex":
        return bool(shutil.which("lualatex"))
    if renderer == "tectonic":
        return bool(shutil.which("tectonic"))
    if renderer == "auto":
        return bool(
            (shutil.which("latexmk") and shutil.which("lualatex"))
            or shutil.which("lualatex")
            or shutil.which("tectonic")
        )
    return False


def _latex_documents(review_dir: Path) -> list[ReviewDocument]:
    """Load exactly the author-facing documents declared by the manifest."""
    documents: list[ReviewDocument] = []
    for entry in document_entries(review_dir):
        role = {
            "report.md": "referee_report",
            "editing-comments.md": "editing_comments",
            "writing-report.md": "editing_comments",
            "fix-plan.md": "revision_plan",
            "evidence/round-reconciliation.md": "round_progress",
        }.get(entry.path, "supplementary")
        documents.append(
            ReviewDocument(
                title=entry.title,
                markdown=_portable_document_path(review_dir, entry.path).read_text(encoding="utf-8"),
                role=role,
                source_name=entry.path,
            )
        )
    return documents


def build_professional_pdf(
    review_dir: Path,
    output: Path,
    *,
    page_size: str,
    font_dir: Path | None,
    renderer: str = "auto",
    assessment_date: date | None = None,
) -> tuple[bytes, RenderProfile | None]:
    """Build the primary PDF, preferring a health-checked LaTeX backend.

    Auto-selection uses a minimal compile to reject executables that cannot
    actually run (for example, ``latexmk`` without Perl).  Once a healthy TeX
    backend is selected, a content error is never hidden by a ReportLab retry.
    """
    if renderer not in SUPPORTED_RENDERERS:
        raise ValueError(f"renderer must be one of {', '.join(SUPPORTED_RENDERERS)}")
    review_dir = review_dir.expanduser().absolute()
    reject_package_links(review_dir)
    review_dir = review_dir.resolve(strict=True)
    if renderer == "reportlab":
        return build_pdf(review_dir, output, page_size=page_size, font_dir=font_dir), None
    if renderer == "auto":
        selected, _health_diagnostics = select_healthy_renderer()
        if selected is None:
            return build_pdf(review_dir, output, page_size=page_size, font_dir=font_dir), None
        renderer = selected
    elif not _latex_is_available(renderer):
        raise ValueError(f"requested renderer is unavailable: {renderer}")
    run = _load_object(review_dir / "run.json")
    paper_title, _review_id, raw_date = paper_identity(review_dir, run)
    if paper_title == "Untitled manuscript":
        raise ValueError(
            "the manuscript title could not be verified; set run.json.paper_title "
            "or supply a title-bearing Markdown extraction"
        )
    result = render_review_pdf(
        paper_title=paper_title,
        assessment_date=_review_date(raw_date, assessment_date),
        documents=_latex_documents(review_dir),
        renderer=renderer,
        page_size=page_size,
    )
    return result.pdf_bytes, result.profile


def _profile_bytes(profile: RenderProfile) -> bytes:
    return (
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


FONT_STATE = FontSet("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier")
HEADING_SERIAL = 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--output", type=Path, help="Output PDF (default: <review-dir>/paper-review.pdf)")
    parser.add_argument("--page-size", choices=("a4", "letter"), default="letter")
    parser.add_argument("--font-dir", type=Path, help="Optional directory containing portable TrueType fonts")
    parser.add_argument(
        "--renderer",
        choices=SUPPORTED_RENDERERS,
        default="auto",
        help="Typesetting backend (default: LaTeX when available, otherwise ReportLab)",
    )
    parser.add_argument(
        "--assessment-date",
        type=date.fromisoformat,
        help="Verified review date for legacy packages that do not record one (YYYY-MM-DD)",
    )
    parser.add_argument("--check", action="store_true", help="Verify the existing PDF is synchronized")
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().absolute()
    output = (args.output.expanduser().absolute() if args.output else review_dir / PORTABLE_OUTPUT_NAME)
    try:
        reject_package_links(review_dir)
        review_dir = review_dir.resolve(strict=True)
        renderer = args.renderer
        profile_path = review_dir / RENDER_PROFILE_PATH
        if args.check and profile_path.is_file() and renderer == "auto":
            recorded = _load_object(profile_path)
            recorded_renderer = recorded.get("renderer")
            if recorded_renderer not in LATEX_RENDERERS[1:]:
                raise ValueError("PDF render profile names an unsupported renderer")
            renderer = str(recorded_renderer)
        data, profile = build_professional_pdf(
            review_dir,
            output,
            page_size=args.page_size,
            font_dir=args.font_dir,
            renderer=renderer,
            assessment_date=args.assessment_date,
        )
        if args.check:
            if not output.is_file() or output.is_symlink() or output.read_bytes() != data:
                raise ValueError(f"{output} is not synchronized with the review package")
            if profile_path.exists():
                if profile is None or profile_path.read_bytes() != _profile_bytes(profile):
                    raise ValueError(f"{profile_path} is not synchronized with the PDF renderer")
        else:
            if output.parent.resolve() == review_dir.resolve():
                atomic_write_bytes(review_dir, output.name, data)
                if profile is not None:
                    atomic_write_bytes(review_dir, RENDER_PROFILE_PATH, _profile_bytes(profile))
                elif profile_path.exists() and not profile_path.is_symlink():
                    profile_path.unlink()
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(output.parent, output.name, data)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        LatexRenderError,
        LayoutError,
        ValueError,
    ) as exc:
        parser.exit(1, f"PDF report generation failed: {exc}\n")
    print(f"PDF report ready: {output}")
    return 0


if __name__ == "__main__":
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
