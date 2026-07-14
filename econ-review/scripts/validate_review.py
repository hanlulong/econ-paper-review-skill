#!/usr/bin/env python3
"""Validate econ-review artifacts and their cross-file mappings."""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import (  # noqa: E402
    canonical_portable_path,
    require_valid_pdf_bytes,
    safe_read_bytes,
    sha256_bytes,
    strict_json_load,
    strict_json_loads,
)
from trust_spine import pdf_sources, validate_trust_spine  # noqa: E402
from generate_verification import render as render_verification  # noqa: E402
from generate_coverage import render as render_coverage  # noqa: E402
from generate_sources import render as render_sources  # noqa: E402
from generate_reports import render_current_writing_report, validate_current_venue_fit  # noqa: E402
from round_reconciliation import validate_round_reconciliation  # noqa: E402

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - environment/setup failure
    Draft202012Validator = None
    FormatChecker = None

try:
    from PIL import Image, UnidentifiedImageError
except ImportError:  # pragma: no cover - environment/setup failure
    Image = None
    UnidentifiedImageError = OSError


STAGES = {
    "pending",
    "in_progress",
    "passed",
    "bounded",
    "failed",
    "not_applicable",
}
SEVERITIES = {"critical", "major", "minor", "info"}
EVIDENCE_TYPES = {
    "quote",
    "equation",
    "table_cell",
    "figure",
    "code",
    "literature",
    "absence_scope",
    "computation",
}
FINDING_ID = re.compile(r"^[A-Z][A-Z0-9_-]*-[0-9]{2,}$")
ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
ALLOWED_RENDER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
ASSESSMENT_BOUNDARY_HEADING = re.compile(
    r"^#{1,6}[ \t]+Assessment[ \t-]+Boundar(?:y|ies)\b.*$",
    re.MULTILINE | re.IGNORECASE,
)
JOURNAL_FIT_HEADING = re.compile(
    r"^#{1,6}[ \t]+Journal[ \t-]+fit\b.*$",
    re.MULTILINE | re.IGNORECASE,
)


def _canonical_burden_parents() -> frozenset[str]:
    """Read the closed parent vocabulary from the schema that defines it."""

    schema = strict_json_load(ASSET_DIR / "run.schema.json")
    values = schema["$defs"]["burden"]["properties"]["parent_id"]["enum"]
    return frozenset(value for value in values if isinstance(value, str))


CANONICAL_BURDEN_PARENTS = _canonical_burden_parents()
CORE_AUDIT_VIEWS = frozenset(
    {"logical_validity", "technical_validity", "methodological_validity"}
)
DOCUMENT_SOURCE_ROLES = frozenset({"manuscript", "appendix", "supplement"})
BIBLIOGRAPHY_SOURCE_ROLES = frozenset({"bibliography"})
REPLICATION_SOURCE_ROLES = frozenset({"code", "data_dictionary"})
INTERNAL_SOURCE_ROLES = (
    DOCUMENT_SOURCE_ROLES | BIBLIOGRAPHY_SOURCE_ROLES | REPLICATION_SOURCE_ROLES
)
REPLICATION_MATERIAL_STATES = frozenset(
    {"not_permitted", "static_only", "executed"}
)
INSPECTED_REPLICATION_STATES = frozenset({"static_only", "executed"})
REPLICATION_BURDEN_PARENTS = frozenset(
    {"reproducibility", "computational_validity"}
)


ANALYTICAL_GENERIC_PHRASES = {
    "checked",
    "reviewed",
    "clear",
    "no issue",
    "no issues",
    "not applicable",
    "completed",
    "done",
}
ANALYTICAL_GENERIC_PREFIXES = (
    "all applicable objects were reviewed",
    "all relevant material was checked",
    "the audit was completed",
    "checked within the assessment boundary",
    "reviewed within the assessment boundary",
)
ANALYTICAL_META_BOILERPLATE = (
    re.compile(r"\b(?:this|the) (?:analytical )?(?:ledger|audit) (?:entry|domain)\b"),
    re.compile(r"\b(?:complete|corresponding|active) finding set\b"),
    re.compile(r"\bpaper-specific review\b"),
    re.compile(
        r"\bsource (?:passages?|materials?|content)\b.{0,120}"
        r"\b(?:show|contain) the (?:specific )?objects? summarized\b"
    ),
)
ANALYTICAL_META_BOILERPLATE_PAIRS = (
    ("traced through the manuscript", "linked finding"),
    ("traced through manuscript", "linked finding"),
    ("linked finding", "identify the exact adverse states"),
)


def validate_reverse_burden_activation(
    review_dir: Path,
    run: dict[str, Any],
    errors: list[str],
) -> None:
    """Require clear source objects to activate their conceptual audit burden.

    The burden ledger is intentionally open-ended, so this checks only
    unambiguous reverse implications. It must not infer a method from a paper
    label or turn every parsed block/equation into a canned checklist.
    """

    active_parents = {
        row.get("parent_id")
        for row in run.get("activated_burdens", [])
        if isinstance(row, dict) and row.get("status") == "active"
    }
    requirements: dict[str, list[str]] = {}

    def require(parent_id: str, reason: str) -> None:
        requirements.setdefault(parent_id, []).append(reason)

    payloads: dict[str, dict[str, Any]] = {}
    for relative in (
        "evidence/claims.json",
        "evidence/computations.json",
        "evidence/external-sources.json",
        "evidence/figures.json",
        "evidence/tables.json",
        "evidence/writing.json",
    ):
        try:
            payload = strict_json_load(review_dir / relative)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            # The ordinary schema/artifact passes report the concrete read error.
            continue
        if isinstance(payload, dict):
            payloads[relative] = payload

    claims = payloads.get("evidence/claims.json", {})
    if claims.get("claim_families"):
        require("logical_validity", "the claim-family map contains manuscript claims")
        require(
            "methodological_validity",
            "the claim-family map records a way of learning the paper's economic object",
        )

    computations = payloads.get("evidence/computations.json", {})
    if computations.get("computations"):
        require("computational_validity", "the computation ledger contains audited computations")

    external = payloads.get("evidence/external-sources.json", {})
    frontier = external.get("frontier_audit")
    if isinstance(frontier, dict) and frontier.get("status") in {"complete", "bounded"}:
        require("source_support", "the literature/source frontier was assessed or bounded")

    figures = payloads.get("evidence/figures.json", {})
    tables = payloads.get("evidence/tables.json", {})
    if figures.get("figures") or tables.get("tables"):
        require("exhibit_integrity", "the rendered exhibit audit contains a figure or table")

    writing = payloads.get("evidence/writing.json", {})
    if writing.get("schema_version") == "0.4":
        require("communication_integrity", "the current full writing audit is in scope")

    for parent_id, reasons in sorted(requirements.items()):
        if parent_id not in active_parents:
            errors.append(
                f"source objects require an active {parent_id} burden: "
                + "; ".join(dict.fromkeys(reasons))
            )


def generic_analytical_text(value: Any) -> bool:
    """Return true when an analytical-ledger field asserts review activity, not evidence."""
    if not isinstance(value, str):
        return True
    normalized = " ".join(value.lower().split()).strip(".")
    if not normalized:
        return True
    if normalized in ANALYTICAL_GENERIC_PHRASES:
        return True
    if normalized.startswith(ANALYTICAL_GENERIC_PREFIXES):
        return True
    if any(pattern.search(normalized) for pattern in ANALYTICAL_META_BOILERPLATE):
        return True
    return any(
        all(fragment in normalized for fragment in pair)
        for pair in ANALYTICAL_META_BOILERPLATE_PAIRS
    )


def validate_local_asset_path(
    review_dir: Path,
    raw_path: Any,
    label: str,
    errors: list[str],
) -> tuple[str, bytes] | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        errors.append(f"{label} must be a non-empty relative path")
        return None
    try:
        raw_path = canonical_portable_path(raw_path)
    except ValueError as exc:
        errors.append(
            f"{label} must use a canonical portable review-relative path: {exc}"
        )
        return None
    try:
        relative_path = Path(raw_path)
    except (OSError, ValueError) as exc:
        errors.append(f"{label} is not a valid relative path: {exc}")
        return None
    if relative_path.is_absolute() or ".." in relative_path.parts:
        errors.append(f"{label} must stay inside the review directory: {raw_path}")
        return None
    if relative_path.suffix.lower() not in ALLOWED_RENDER_SUFFIXES:
        errors.append(f"{label} has an unsupported render type: {raw_path}")
        return None
    root = review_dir.resolve()
    candidate = review_dir / relative_path
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        errors.append(f"{label} does not exist: {raw_path}")
        return None
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"{label} cannot be resolved safely: {exc}")
        return None
    try:
        canonical = resolved.relative_to(root).as_posix()
    except ValueError:
        errors.append(f"{label} resolves outside the review directory: {raw_path}")
        return None
    if not resolved.is_file():
        errors.append(f"{label} must resolve to a regular file: {raw_path}")
        return None
    try:
        asset_bytes = safe_read_bytes(review_dir, raw_path)
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        errors.append(f"{label} cannot be read safely: {exc}")
        return None
    return canonical, asset_bytes


def has_render_signature(path: str, data: bytes) -> bool:
    """Check the container signature for supported immutable render assets."""
    suffix = Path(path).suffix.lower()
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


def render_decode_error(path: str, data: bytes) -> str | None:
    """Return an error when retained bytes are not a complete readable image."""
    if Image is None:
        return "Pillow is required to decode retained render assets"
    expected_format = {
        ".png": "PNG",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".webp": "WEBP",
    }.get(Path(path).suffix.lower())
    try:
        with Image.open(io.BytesIO(data)) as image:
            observed_format = image.format
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image.load()
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        return f"cannot be decoded as a complete image: {exc}"
    if expected_format is None or observed_format != expected_format:
        return f"container format {observed_format!r} does not match the file extension"
    if width < 1 or height < 1:
        return "decoded image has invalid dimensions"
    return None


def normalized_figure_identity(value: Any) -> str:
    """Normalize a declared visual cue without assuming numbered figures."""
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFC", value).casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return re.sub(r"^(?:appendix\s+)?fig(?:ure)?\.?\s+", "", normalized)


def identity_key_matches(key: Any, text: Any) -> bool:
    """Match a declared cue as a bounded phrase, avoiding Figure 1/Figure 10 collisions."""
    normalized_key = normalized_figure_identity(key)
    normalized_text = normalized_figure_identity(text)
    if not normalized_key or not normalized_text:
        return False
    return bool(re.search(
        rf"(?<!\w){re.escape(normalized_key)}(?!\w)",
        normalized_text,
    ))


def explicit_figure_identifier(value: Any) -> str | None:
    """Extract an explicit Figure/Fig. identifier when the label supplies one."""
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFC", value).casefold().strip()
    match = re.match(
        r"^(?:appendix\s+)?fig(?:ure)?\.?\s+([^\s:;,()]+)",
        normalized,
    )
    return match.group(1).rstrip(".") if match else None


def normalized_table_identity(value: Any) -> str:
    """Normalize a declared table cue without assuming numbered exhibits."""
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFC", value).casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return re.sub(r"^(?:appendix\s+)?table\.?\s+", "", normalized)


def table_identity_key_matches(key: Any, text: Any) -> bool:
    """Match a table cue as a bounded phrase, avoiding Table 1/Table 10 collisions."""
    normalized_key = normalized_table_identity(key)
    normalized_text = normalized_table_identity(text)
    if not normalized_key or not normalized_text:
        return False
    return bool(re.search(
        rf"(?<!\w){re.escape(normalized_key)}(?!\w)",
        normalized_text,
    ))


def explicit_table_identifier(value: Any) -> str | None:
    """Extract an explicit Table identifier when the label supplies one."""
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFC", value).casefold().strip()
    match = re.match(r"^(?:appendix\s+)?table\.?\s+([^\s:;,()]+)", normalized)
    return match.group(1).rstrip(".") if match else None


def _canonical_manifest_asset_path(review_dir: Path, raw_path: Any) -> str | None:
    """Resolve a retained ingestion path to the validator's canonical spelling."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    try:
        relative = Path(raw_path)
    except (OSError, ValueError):
        return None
    if relative.is_absolute() or ".." in relative.parts:
        return None
    try:
        resolved = (review_dir / relative).resolve(strict=True)
        return resolved.relative_to(review_dir.resolve()).as_posix()
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return None


def load_exhibit_source_bindings(
    review_dir: Path,
    errors: list[str],
    kind: str,
) -> tuple[dict[str, str], dict[str, dict[str, dict[str, tuple[Any, ...]]]]]:
    """Index canonical PDF pages and one exhibit kind by source-object ID.

    The PDF ingestion manifest is already authenticated by the trust spine. This
    index gives an exhibit audit a direct provenance join to those authenticated
    records. Crop lookup by ingestion object ID prevents a row from borrowing a
    different crop that happens to share a page, path, or digest. Non-PDF
    sources remain valid exhibit sources but intentionally have no PDF index.
    """
    if kind not in {"figure", "table"}:
        raise ValueError(f"unsupported exhibit binding kind: {kind}")
    collection = f"{kind}s"
    manifest = load_json(review_dir / "evidence" / "source-manifest.json", errors)
    if not isinstance(manifest, dict):
        return {}, {}
    source_media: dict[str, str] = {}
    pdf_assets: dict[str, dict[str, dict[str, tuple[Any, ...]]]] = {}
    for source in manifest.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_id = source.get("id")
        media_type = source.get("media_type")
        if not isinstance(source_id, str) or not isinstance(media_type, str):
            continue
        source_media[source_id] = media_type
        if media_type != "application/pdf":
            continue
        extraction = source.get("extraction")
        ingestion_path = (
            extraction.get("ingestion_manifest_path")
            if isinstance(extraction, dict)
            else None
        )
        if not isinstance(ingestion_path, str):
            errors.append(
                f"{kind} audit cannot bind PDF source {source_id}: ingestion manifest is not declared"
            )
            continue
        try:
            ingestion_bytes = safe_read_bytes(review_dir, ingestion_path)
            ingestion = strict_json_loads(ingestion_bytes)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(
                f"{kind} audit cannot bind PDF source {source_id}: ingestion manifest is unreadable: {exc}"
            )
            continue
        if not isinstance(ingestion, dict):
            errors.append(
                f"{kind} audit cannot bind PDF source {source_id}: ingestion manifest is not an object"
            )
            continue
        indexed: dict[str, dict[str, tuple[Any, ...]]] = {
            "full_page": {},
            "crop": {},
        }
        for page in ingestion.get("pages", []):
            if not isinstance(page, dict):
                continue
            canonical_path = _canonical_manifest_asset_path(
                review_dir, page.get("render_path")
            )
            page_number = page.get("page")
            digest = page.get("render_sha256")
            if (
                canonical_path is not None
                and isinstance(page_number, int)
                and isinstance(digest, str)
            ):
                indexed["full_page"][canonical_path] = (page_number, digest)
        for exhibit in ingestion.get(collection, []):
            if not isinstance(exhibit, dict):
                continue
            object_id = exhibit.get("id")
            canonical_path = _canonical_manifest_asset_path(
                review_dir, exhibit.get("crop_path")
            )
            page_number = exhibit.get("page")
            digest = exhibit.get("crop_sha256")
            if (
                canonical_path is not None
                and isinstance(object_id, str)
                and object_id.strip()
                and isinstance(page_number, int)
                and isinstance(digest, str)
            ):
                if object_id in indexed["crop"]:
                    errors.append(
                        f"{kind} audit cannot bind PDF source {source_id}: ingestion "
                        f"manifest has duplicate {kind} object ID {object_id}"
                    )
                else:
                    indexed["crop"][object_id] = (canonical_path, page_number, digest)
        pdf_assets[source_id] = indexed
    return source_media, pdf_assets


def normalized_exhibit_label(kind: str, label: Any) -> str:
    if not isinstance(label, str):
        return ""
    value = re.sub(r"\s+", " ", label).strip().lower()
    if kind == "table":
        return re.sub(r"^(appendix\s+)?table\s+", "", value)
    if kind == "figure":
        return re.sub(r"^(appendix\s+)?figure\s+", "", value)
    return value


def validate_schema(instance: Any, schema_name: str, label: str, errors: list[str]) -> None:
    if Draft202012Validator is None:
        errors.append("jsonschema is required to validate econ-review artifacts")
        return
    schema = load_json(ASSET_DIR / schema_name, errors)
    if not isinstance(schema, dict):
        return
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path)):
        path = ".".join(str(part) for part in error.absolute_path)
        location = f"{label}.{path}" if path else label
        errors.append(f"schema violation at {location}: {error.message}")


def load_json(path: Path, errors: list[str]) -> Any:
    try:
        return strict_json_load(path)
    except FileNotFoundError:
        errors.append(f"missing required file: {path}")
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}")
    except ValueError as exc:
        errors.append(f"invalid JSON in {path}: {exc}")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"cannot read JSON file {path}: {exc}")
    return None


_MARKDOWN_ATX_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)$")
_MARKDOWN_SETEXT = re.compile(r"^[ \t]*(=+|-+)[ \t]*$")
_LATEX_HEADING = re.compile(
    r"\\(?P<kind>part|chapter|section|subsection|subsubsection|paragraph|subparagraph)"
    r"\*?\s*(?:\[[^\]\n]*\]\s*)?\{"
)
_LATEX_ENVIRONMENT_TOKEN = re.compile(r"\\(?P<action>begin|end)\s*\{(?P<name>[^{}\n]+)\}")


def _text_lines_with_offsets(text: str) -> list[tuple[int, int, str]]:
    rows: list[tuple[int, int, str]] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        rows.append((cursor, cursor + len(line), line.rstrip("\r\n")))
        cursor += len(line)
    if cursor < len(text) or not rows:
        rows.append((cursor, len(text), text[cursor:]))
    return rows


def _balanced_brace_end(text: str, open_brace: int) -> tuple[int, bool]:
    depth = 0
    escaped = False
    for index in range(open_brace, len(text)):
        character = text[index]
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index + 1, True
    return len(text), False


def _latex_without_comments(text: str) -> str:
    """Blank TeX comments while preserving every source offset."""

    characters = list(text)
    line_start = 0
    while line_start < len(characters):
        line_end = line_start
        while line_end < len(characters) and characters[line_end] not in "\r\n":
            line_end += 1
        for index in range(line_start, line_end):
            if characters[index] != "%":
                continue
            slashes = 0
            cursor = index - 1
            while cursor >= line_start and characters[cursor] == "\\":
                slashes += 1
                cursor -= 1
            if slashes % 2 == 0:
                characters[index:line_end] = " " * (line_end - index)
                break
        line_start = line_end + 1
        if line_end + 1 < len(characters) and characters[line_end:line_end + 2] == ["\r", "\n"]:
            line_start += 1
    return "".join(characters)


def _latex_structural_view(text: str) -> tuple[str, set[int]]:
    """Hide literal-code bodies while retaining their environment tokens."""

    visible = list(_latex_without_comments(text))
    raw = "".join(visible)
    literal_names = {"verbatim", "Verbatim", "lstlisting", "minted", "comment"}
    unmatched: set[int] = set()
    cursor = 0
    while True:
        match = re.search(r"\\begin\s*\{([^{}\n]+)\}", raw[cursor:])
        if not match:
            break
        start = cursor + match.start()
        body_start = cursor + match.end()
        name = match.group(1).strip()
        cursor = body_start
        if name not in literal_names:
            continue
        closing = re.search(r"\\end\s*\{" + re.escape(name) + r"\}", raw[body_start:])
        if closing:
            body_end = body_start + closing.start()
            cursor = body_start + closing.end()
        else:
            body_end = len(raw)
            cursor = len(raw)
            unmatched.add(start)
        visible[body_start:body_end] = " " * (body_end - body_start)
        raw = "".join(visible)
    return "".join(visible), unmatched


def discover_source_outline(
    source_id: str,
    text: str,
    media_type: str,
    path: str,
) -> list[dict[str, Any]]:
    """Return a syntax-derived outline, never a paper-family checklist."""

    suffix = Path(path).suffix.lower()
    is_markdown = media_type in {"text/markdown", "text/x-markdown"} or suffix in {".md", ".markdown"}
    is_tex = media_type in {"application/x-tex", "text/x-tex", "text/latex"} or suffix in {".tex", ".ltx"}
    headings: list[tuple[int, int, str, bool]] = []
    uncertain_regions: list[tuple[int, int, str]] = []
    if is_markdown:
        lines = _text_lines_with_offsets(text)
        fenced: tuple[str, int] | None = None
        fence_start: int | None = None
        html_comment = False
        html_comment_start: int | None = None
        front_matter = bool(lines and lines[0][2].strip() == "---")
        front_matter_start = lines[0][0] if front_matter else None
        eligible: list[tuple[int, int, str]] = []
        for line_index, (start, end, line) in enumerate(lines):
            if front_matter:
                eligible.append((start, end, ""))
                if line_index > 0 and line.strip() in {"---", "..."}:
                    front_matter = False
                continue
            visible_line = line
            if fenced is None:
                characters = list(visible_line)
                cursor = 0
                if html_comment:
                    closing = visible_line.find("-->")
                    if closing < 0:
                        eligible.append((start, end, ""))
                        continue
                    characters[:closing + 3] = " " * (closing + 3)
                    cursor = closing + 3
                    html_comment = False
                    html_comment_start = None
                while True:
                    opening = visible_line.find("<!--", cursor)
                    if opening < 0:
                        break
                    closing = visible_line.find("-->", opening + 4)
                    if closing < 0:
                        characters[opening:] = " " * (len(characters) - opening)
                        html_comment = True
                        html_comment_start = start + opening
                        break
                    characters[opening:closing + 3] = " " * (closing + 3 - opening)
                    cursor = closing + 3
                visible_line = "".join(characters)
            fence = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", visible_line)
            if fence:
                token = fence.group(1)
                if fenced is None:
                    fenced = (token[0], len(token))
                    fence_start = start
                elif token[0] == fenced[0] and len(token) >= fenced[1]:
                    fenced = None
                    fence_start = None
                eligible.append((start, end, ""))
                continue
            eligible.append((start, end, visible_line if fenced is None and not html_comment else ""))
        if front_matter and front_matter_start is not None:
            uncertain_regions.append((
                front_matter_start,
                len(text),
                "Unclosed Markdown YAML front matter",
            ))
        if fenced is not None and fence_start is not None:
            uncertain_regions.append((
                fence_start,
                len(text),
                "Unclosed Markdown fenced block",
            ))
        if html_comment and html_comment_start is not None:
            uncertain_regions.append((
                html_comment_start,
                len(text),
                "Unclosed Markdown HTML comment",
            ))
        for index, (start, _end, line) in enumerate(eligible):
            match = _MARKDOWN_ATX_HEADING.match(line)
            if match:
                raw_label = (match.group(2) or "").strip()
                label = re.sub(r"[ \t]+#+[ \t]*$", "", raw_label).strip()
                headings.append((
                    start,
                    len(match.group(1)),
                    label or "(untitled heading)",
                    False,
                ))
                continue
            if index > 0 and _MARKDOWN_SETEXT.match(line):
                previous_start, _previous_end, previous = eligible[index - 1]
                if previous.strip() and not _MARKDOWN_ATX_HEADING.match(previous):
                    headings.append((
                        previous_start,
                        1 if line.lstrip().startswith("=") else 2,
                        previous.strip(),
                        False,
                    ))
    elif is_tex:
        visible, unmatched_literal = _latex_structural_view(text)
        for match in _LATEX_HEADING.finditer(visible):
            open_brace = match.end() - 1
            close, closed = _balanced_brace_end(visible, open_brace)
            label = text[open_brace + 1:max(open_brace + 1, close - 1)].strip()
            levels = {
                "part": 1, "chapter": 1, "section": 2, "subsection": 3,
                "subsubsection": 4, "paragraph": 5, "subparagraph": 6,
            }
            headings.append((
                match.start(),
                levels[match.group("kind")],
                label or match.group("kind"),
                not closed,
            ))
            if not closed:
                uncertain_regions.append((
                    match.start(), len(text), "Unclosed LaTeX heading argument"
                ))
        uncertain_regions.extend((
            start, len(text), "Unclosed LaTeX literal environment"
        ) for start in unmatched_literal)

    headings.sort(key=lambda item: item[0])
    objects: list[dict[str, Any]] = []
    for index, (start, level, label, heading_uncertain) in enumerate(headings, start=1):
        end = headings[index][0] if index < len(headings) else len(text)
        uncertain = heading_uncertain or any(
            region_start < end and region_end > start
            for region_start, region_end, _reason in uncertain_regions
        )
        objects.append({
            "object_type": "outline_heading",
            "object_id": f"{source_id}-OUT-H{index:03d}",
            "start": start,
            "end": end,
            "sha256": sha256_bytes(text[start:end].encode("utf-8")),
            "locator": f"Heading {index} (level {level}): {' '.join(label.split())}",
            "parser_uncertain": uncertain,
        })

    if is_tex:
        visible, unmatched_literal = _latex_structural_view(text)
        stacks: dict[str, list[re.Match[str]]] = {}
        environments: list[tuple[int, int, str, bool]] = []
        for match in _LATEX_ENVIRONMENT_TOKEN.finditer(visible):
            name = match.group("name").strip()
            if match.group("action") == "begin":
                stacks.setdefault(name, []).append(match)
                continue
            if not stacks.get(name):
                continue
            opening = stacks[name].pop()
            if name != "document":
                environments.append((opening.start(), match.end(), name, False))
        for name, openings in stacks.items():
            if name == "document":
                continue
            environments.extend((
                opening.start(), len(text), name, True
            ) for opening in openings)
        environments.sort(key=lambda item: (item[0], item[1], item[2]))
        for index, (start, end, name, unmatched) in enumerate(environments, start=1):
            objects.append({
                "object_type": "outline_environment",
                "object_id": f"{source_id}-OUT-E{index:03d}",
                "start": start,
                "end": end,
                "sha256": sha256_bytes(text[start:end].encode("utf-8")),
                "locator": f"LaTeX environment {index}: {name}",
                "parser_uncertain": unmatched or start in unmatched_literal,
            })
    elif is_markdown:
        for index, (start, end, reason) in enumerate(uncertain_regions, start=1):
            objects.append({
                "object_type": "outline_environment",
                "object_id": f"{source_id}-OUT-E{index:03d}",
                "start": start,
                "end": end,
                "sha256": sha256_bytes(text[start:end].encode("utf-8")),
                "locator": f"Markdown structural boundary {index}: {reason}",
                "parser_uncertain": True,
            })
    return objects


def _load_inventory_json(
    review_dir: Path, raw_path: Any, label: str, errors: list[str]
) -> dict[str, Any] | None:
    if not isinstance(raw_path, str):
        errors.append(f"{label} path is missing")
        return None
    try:
        value = strict_json_loads(safe_read_bytes(review_dir, raw_path))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"{label} cannot be read safely: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return None
    return value


def validate_source_inventory_closure(
    review_dir: Path,
    coverage: dict[str, Any],
    source_by_id: dict[str, dict[str, Any]],
    anchor_by_id: dict[str, dict[str, Any]],
    unit_rows: list[dict[str, Any]],
    errors: list[str],
) -> None:
    """Close the current full-review source inventory in both directions."""

    raw_inventory = coverage.get("source_inventory")
    if not isinstance(raw_inventory, list):
        errors.append("current full coverage requires source_inventory")
        raw_inventory = []
    inventory = [row for row in raw_inventory if isinstance(row, dict)]
    inventory_ids = [row.get("id") for row in inventory if isinstance(row.get("id"), str)]
    duplicate_ids = sorted(
        value for value, count in Counter(inventory_ids).items() if count > 1
    )
    if duplicate_ids:
        errors.append("duplicate source inventory IDs: " + ", ".join(duplicate_ids))

    unit_by_id = {
        row.get("id"): row for row in unit_rows if isinstance(row.get("id"), str)
    }
    expected: dict[tuple[str, str, str], dict[str, Any]] = {}
    document_sources = {
        source_id: source
        for source_id, source in source_by_id.items()
        if source.get("role") in DOCUMENT_SOURCE_ROLES
    }
    for source_id, source in document_sources.items():
        extraction = source.get("extraction")
        text_path = (
            extraction.get("path")
            if isinstance(extraction, dict) and isinstance(extraction.get("path"), str)
            else source.get("path")
        )
        text: str | None = None
        if isinstance(text_path, str):
            try:
                text = safe_read_bytes(review_dir, text_path).decode("utf-8")
            except (OSError, UnicodeError, ValueError):
                # The trust-spine pass reports the underlying source error.
                pass
        if isinstance(text, str):
            for row in discover_source_outline(
                source_id, text, str(source.get("media_type", "")), text_path or ""
            ):
                expected[(source_id, row["object_type"], row["object_id"])] = row

        precise = [
            anchor
            for anchor in anchor_by_id.values()
            if anchor.get("source_id") == source_id and anchor.get("kind") != "scope"
        ]
        if not precise:
            errors.append(
                f"source {source_id} has no granular anchor; a whole-source scope anchor cannot certify source coverage"
            )

        ingestion_path = (
            extraction.get("ingestion_manifest_path")
            if isinstance(extraction, dict)
            else None
        )
        if not isinstance(ingestion_path, str):
            continue
        ingestion = _load_inventory_json(
            review_dir,
            ingestion_path,
            f"PDF source {source_id} ingestion manifest",
            errors,
        )
        if not isinstance(ingestion, dict):
            continue
        for page in ingestion.get("pages", []) if isinstance(ingestion.get("pages"), list) else []:
            if not isinstance(page, dict) or not isinstance(page.get("page"), int):
                continue
            page_number = page["page"]
            object_id = f"{source_id}-PDF-P{page_number:04d}"
            expected[(source_id, "pdf_page", object_id)] = {
                "object_type": "pdf_page",
                "object_id": object_id,
                "locator": f"PDF page {page_number}",
                "page": page_number,
                "ingestion_status": page.get("status"),
            }
        for block in ingestion.get("blocks", []) if isinstance(ingestion.get("blocks"), list) else []:
            if not isinstance(block, dict) or not isinstance(block.get("id"), str):
                continue
            expected[(source_id, "pdf_block", block["id"])] = {
                "object_type": "pdf_block",
                "object_id": block["id"],
                "locator": f"PDF page {block.get('page')}, block {block['id']}",
                "start": block.get("markdown_start"),
                "end": block.get("markdown_end"),
                "sha256": block.get("sha256"),
                "page": block.get("page"),
                "ingestion_status": (
                    "bounded" if block.get("kind") == "bounded_page" else None
                ),
            }
        for collection, object_type in (
            ("tables", "pdf_table"),
            ("figures", "pdf_figure"),
            ("equations", "pdf_equation"),
        ):
            rows = ingestion.get(collection, [])
            for item in rows if isinstance(rows, list) else []:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    continue
                expected[(source_id, object_type, item["id"])] = {
                    "object_type": object_type,
                    "object_id": item["id"],
                    "locator": (
                        f"PDF page {item.get('page')}, "
                        f"{object_type.replace('_', ' ')} {item['id']}"
                    ),
                    "page": item.get("page"),
                    "ingestion_status": item.get("status"),
                }

    inventory_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in inventory:
        key = (
            str(row.get("source_id")),
            str(row.get("object_type")),
            str(row.get("object_id")),
        )
        if key in inventory_by_key:
            errors.append("duplicate source inventory object: " + "/".join(key))
        inventory_by_key[key] = row
    missing = sorted(set(expected) - set(inventory_by_key))
    extra = sorted(set(inventory_by_key) - set(expected))
    if missing:
        errors.append(
            "source inventory omits canonical objects: "
            + ", ".join("/".join(key) for key in missing)
        )
    if extra:
        errors.append(
            "source inventory references noncanonical objects: "
            + ", ".join("/".join(key) for key in extra)
        )

    figure_payload = load_json(review_dir / "evidence/figures.json", errors)
    table_payload = load_json(review_dir / "evidence/tables.json", errors)
    audit_by_id: dict[str, tuple[str, dict[str, Any], set[str]]] = {}
    for payload, object_type, collection in (
        (figure_payload, "pdf_figure", "figures"),
        (table_payload, "pdf_table", "tables"),
    ):
        if not isinstance(payload, dict):
            continue
        rows = payload.get(collection, [])
        for audit in rows if isinstance(rows, list) else []:
            if not isinstance(audit, dict) or not isinstance(audit.get("id"), str):
                continue
            object_ids = {
                asset.get("source_object_id")
                for asset in audit.get("rendered_assets", [])
                if isinstance(asset, dict)
                and isinstance(asset.get("source_object_id"), str)
            }
            audit_by_id[audit["id"]] = (object_type, audit, object_ids)

    required_unit_type = {
        "pdf_table": "table",
        "pdf_figure": "figure",
        "pdf_equation": "equation",
    }
    for key, row in inventory_by_key.items():
        canonical = expected.get(key)
        if not isinstance(canonical, dict):
            continue
        source_id, object_type, object_id = key
        state = row.get("state")
        if row.get("locator") != canonical.get("locator"):
            errors.append(
                f"source inventory {row.get('id')} locator differs from canonical object {object_id}"
            )
        if object_type.startswith("outline_") and state not in {"covered", "excluded", "bounded"}:
            errors.append(
                f"outline object {object_id} must be covered, excluded, or bounded"
            )
        if object_type.startswith("pdf_") and state == "excluded":
            errors.append(
                f"PDF object {object_id} cannot use excluded; adjudicate it as covered, duplicate, false_positive, or bounded"
            )
        if canonical.get("ingestion_status") == "bounded" and state != "bounded":
            errors.append(f"bounded ingestion object {object_id} must remain bounded")
        if canonical.get("parser_uncertain") is True and state != "bounded":
            errors.append(
                f"parser-uncertain source object {object_id} must be bounded"
            )

        coverage_ids = row.get("coverage_unit_ids", [])
        anchor_ids = row.get("anchor_ids", [])
        if not isinstance(coverage_ids, list) or not isinstance(anchor_ids, list):
            continue
        linked_units: list[dict[str, Any]] = []
        for unit_id in coverage_ids:
            unit = unit_by_id.get(unit_id)
            if not isinstance(unit, dict):
                errors.append(
                    f"source inventory {row.get('id')} references unknown coverage unit {unit_id}"
                )
                continue
            linked_units.append(unit)
            if unit.get("source_id") != source_id:
                errors.append(
                    f"source inventory {row.get('id')} coverage unit {unit_id} belongs to another source"
                )
        permitted_anchors = {
            anchor_id
            for unit in linked_units
            for anchor_id in unit.get("anchor_ids", [])
            if isinstance(anchor_id, str)
        }
        for anchor_id in anchor_ids:
            anchor = anchor_by_id.get(anchor_id)
            if not isinstance(anchor, dict):
                errors.append(
                    f"source inventory {row.get('id')} references unknown anchor {anchor_id}"
                )
            elif anchor.get("source_id") != source_id:
                errors.append(
                    f"source inventory {row.get('id')} anchor {anchor_id} belongs to another source"
                )
            elif anchor.get("kind") == "scope":
                errors.append(
                    f"source inventory {row.get('id')} cannot use whole-source scope anchor {anchor_id}"
                )
            if anchor_id not in permitted_anchors:
                errors.append(
                    f"source inventory {row.get('id')} anchor {anchor_id} is outside its coverage units"
                )

        if state == "covered" and object_type in {
            "outline_heading", "outline_environment", "pdf_block"
        }:
            exact = [
                anchor_id
                for anchor_id in anchor_ids
                if anchor_by_id.get(anchor_id, {}).get("start_char") == canonical.get("start")
                and anchor_by_id.get(anchor_id, {}).get("end_char") == canonical.get("end")
                and anchor_by_id.get(anchor_id, {}).get("content_sha256") == canonical.get("sha256")
            ]
            if not exact:
                errors.append(
                    f"covered source object {object_id} requires an exact granular source anchor"
                )
        if state == "covered" and object_type in required_unit_type:
            wanted = required_unit_type[object_type]
            if not any(unit.get("type") == wanted for unit in linked_units):
                errors.append(f"covered {object_id} requires a {wanted} coverage unit")

        audit_id = row.get("audit_record_id")
        if state == "covered" and object_type in {"pdf_table", "pdf_figure"}:
            audit_record = audit_by_id.get(audit_id) if isinstance(audit_id, str) else None
            if not audit_record:
                errors.append(f"covered {object_id} requires its rendered-audit record")
            else:
                audit_type, audit, object_ids = audit_record
                if audit_type != object_type or object_id not in object_ids:
                    errors.append(
                        f"source inventory {row.get('id')} audit {audit_id} does not map canonical object {object_id}"
                    )
                if audit.get("source_id") != source_id:
                    errors.append(
                        f"source inventory {row.get('id')} audit {audit_id} belongs to another source"
                    )
                if audit.get("coverage_unit_id") not in coverage_ids:
                    errors.append(
                        f"source inventory {row.get('id')} omits audit {audit_id} coverage unit"
                    )
        elif audit_id is not None:
            errors.append(
                f"source inventory {row.get('id')} may not attach a rendered-audit record"
            )

        duplicate_of = row.get("duplicate_of")
        if state == "duplicate":
            target_key = (source_id, object_type, str(duplicate_of))
            target = inventory_by_key.get(target_key)
            if duplicate_of == object_id or not isinstance(target, dict):
                errors.append(
                    f"source inventory {row.get('id')} has an invalid duplicate target {duplicate_of}"
                )
            elif target.get("state") == "duplicate":
                errors.append(
                    f"source inventory {row.get('id')} may not form a duplicate chain"
                )

    # Reverse closure: a rendered audit may not point outside the authenticated
    # ingestion or exist without the inventory row pointing back to it.
    for audit_id, (object_type, audit, object_ids) in audit_by_id.items():
        source_id = audit.get("source_id")
        for object_id in object_ids:
            key = (str(source_id), object_type, object_id)
            row = inventory_by_key.get(key)
            if key not in expected:
                errors.append(
                    f"rendered audit {audit_id} references noncanonical PDF object {object_id}"
                )
            elif (
                not isinstance(row, dict)
                or row.get("state") != "covered"
                or row.get("audit_record_id") != audit_id
            ):
                errors.append(
                    f"rendered audit {audit_id} is not reciprocally mapped from source inventory object {object_id}"
                )


def validate_finalization_receipt(
    review_dir: Path,
    review_id: Any,
    errors: list[str],
    run_mode: Any = None,
) -> None:
    receipt = load_json(review_dir / "finalization.json", errors)
    if not isinstance(receipt, dict):
        return
    validate_schema(receipt, "finalization.schema.json", "finalization.json", errors)
    if receipt.get("review_id") != review_id:
        errors.append("finalization.json review_id differs from run.json")
    source_manifest = load_json(review_dir / "evidence" / "source-manifest.json", errors)
    declared_pdfs = pdf_sources(source_manifest) if isinstance(source_manifest, dict) else []
    gates = receipt.get("gates", []) if isinstance(receipt.get("gates"), list) else []
    receipt_version = receipt.get("schema_version")
    if receipt_version in {"0.1", "0.2", "0.3"} and run_mode in {"quick", "full"}:
        expected_gates = {
            "source_integrity",
            "structured_verification",
            "report_generation",
            "fix_plan_generation",
            "contract_validation",
        }
        if declared_pdfs:
            expected_gates.add("source_ingestion")
        if run_mode == "full" and receipt_version in {"0.2", "0.3"}:
            expected_gates.add("structured_audit_v02")
        if run_mode == "full" and receipt_version == "0.3":
            expected_gates.add("burden_coverage_v02")
        missing_gates = sorted(expected_gates - set(gates))
        unexpected_gates = sorted(set(gates) - expected_gates)
        if missing_gates:
            errors.append(
                "finalization receipt is missing required gates: " + ", ".join(missing_gates)
            )
        if unexpected_gates:
            errors.append(
                "finalization receipt asserts gates outside its version, mode, or source boundary: "
                + ", ".join(unexpected_gates)
            )
    else:
        # Direct diagnostic callers may omit run_mode; retain the independent
        # PDF/source assertion even when the complete gate set cannot be built.
        if declared_pdfs and "source_ingestion" not in gates:
            errors.append("finalization receipt for PDF sources requires the source_ingestion gate")
        if not declared_pdfs and "source_ingestion" in gates:
            errors.append("finalization receipt declares source_ingestion without a PDF source")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict):
        return
    excluded_root = {"finalization.json", "review-actions.json"}
    artifact_paths: set[str] = set()
    folded_paths: dict[str, str] = {}
    for raw_path in artifacts:
        try:
            canonical = canonical_portable_path(raw_path)
        except (TypeError, ValueError) as exc:
            errors.append(f"finalization receipt has unsafe artifact path {raw_path!r}: {exc}")
            continue
        if canonical in excluded_root or canonical.rsplit("/", 1)[-1] == ".DS_Store":
            errors.append(f"finalization receipt declares an excluded artifact path: {canonical}")
        folded = canonical.casefold()
        if folded in folded_paths:
            errors.append(
                "finalization receipt has case-ambiguous artifact paths: "
                f"{folded_paths[folded]}, {canonical}"
            )
        folded_paths[folded] = canonical
        artifact_paths.add(canonical)

    observed_artifacts: set[str] = set()
    observed_folded: dict[str, str] = {}
    for path in review_dir.rglob("*"):
        if not path.is_file() or path.name == ".DS_Store":
            continue
        raw_relative = path.relative_to(review_dir).as_posix()
        if raw_relative in excluded_root:
            continue
        try:
            relative = canonical_portable_path(raw_relative)
        except ValueError as exc:
            errors.append(f"finalized package contains an unsafe artifact path {raw_relative!r}: {exc}")
            continue
        folded = relative.casefold()
        if folded in observed_folded:
            errors.append(
                "finalized package contains case-ambiguous artifact paths: "
                f"{observed_folded[folded]}, {relative}"
            )
        observed_folded[folded] = relative
        observed_artifacts.add(relative)

    unhashed = sorted(observed_artifacts - artifact_paths)
    if unhashed:
        errors.append(
            "finalized package contains artifacts absent from its receipt: "
            + ", ".join(unhashed)
        )
    required = {
        "run.json", "findings.json", "synthesis.json", "review-manifest.json",
        "README.md", "report.md", "fix-plan.md", "evidence/source-manifest.json",
        "evidence/verification.json", "evidence/computations.json", "evidence/external-sources.json",
    }
    missing = sorted(required - artifact_paths)
    if missing:
        errors.append("finalization receipt omits canonical artifacts: " + ", ".join(missing))
    for source in declared_pdfs:
        extraction = source.get("extraction")
        if not isinstance(extraction, dict):
            continue
        ingestion_path = extraction.get("ingestion_manifest_path")
        if isinstance(ingestion_path, str) and ingestion_path not in artifacts:
            errors.append(
                f"finalization receipt omits PDF ingestion manifest: {ingestion_path}"
            )
    for relative, expected in artifacts.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            continue
        try:
            relative = canonical_portable_path(relative)
        except ValueError:
            continue
        if relative in excluded_root or relative.rsplit("/", 1)[-1] == ".DS_Store":
            continue
        try:
            observed = sha256_bytes(safe_read_bytes(review_dir, relative))
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append(f"finalized artifact {relative} cannot be read safely: {exc}")
            continue
        if observed != expected:
            errors.append(f"finalized artifact changed after finalization: {relative}")
    if "paper-review.pdf" in artifacts:
        try:
            require_valid_pdf_bytes(
                safe_read_bytes(review_dir, "paper-review.pdf"),
                label="finalized paper-review.pdf",
            )
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    profile_relative = "evidence/pdf-render-profile.json"
    if profile_relative in artifact_paths:
        try:
            profile = strict_json_load(review_dir / profile_relative)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{profile_relative} cannot be read safely: {exc}")
        else:
            label = profile_relative
            required_profile = {
                "renderer", "engine", "compiler_version", "page_count", "page_size",
                "document_count", "source_date_epoch", "template_sha256", "latex_sha256",
                "pdf_sha256", "diagnostics", "attempts",
            }
            if not isinstance(profile, dict):
                errors.append(f"{label} must contain an object")
            else:
                require(profile, required_profile, label, errors)
                renderer = profile.get("renderer")
                if renderer not in {"latexmk-lualatex", "lualatex", "tectonic"}:
                    errors.append(f"{label}.renderer is invalid")
                if profile.get("page_size") not in {"letter", "a4"}:
                    errors.append(f"{label}.page_size is invalid")
                for field in ("page_count", "document_count", "source_date_epoch"):
                    value = profile.get(field)
                    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                        errors.append(f"{label}.{field} must be a positive integer")
                for field in ("template_sha256", "latex_sha256", "pdf_sha256"):
                    value = profile.get(field)
                    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                        errors.append(f"{label}.{field} must be a lowercase SHA-256 digest")
                for field in ("engine", "compiler_version"):
                    if not isinstance(profile.get(field), str) or not profile.get(field, "").strip():
                        errors.append(f"{label}.{field} must be non-empty")
                diagnostics = profile.get("diagnostics")
                if not isinstance(diagnostics, list) or any(
                    not isinstance(item, str) for item in diagnostics
                ):
                    errors.append(f"{label}.diagnostics must be an array of strings")
                attempts = profile.get("attempts")
                if not isinstance(attempts, list) or len(attempts) != 1:
                    errors.append(f"{label}.attempts must record exactly one selected renderer")
                elif not isinstance(attempts[0], dict) or attempts[0].get("renderer") != renderer:
                    errors.append(f"{label}.attempts does not match the selected renderer")
                if "paper-review.pdf" not in artifact_paths:
                    errors.append(f"{label} requires a finalized paper-review.pdf")
                else:
                    try:
                        pdf_digest = sha256_bytes(safe_read_bytes(review_dir, "paper-review.pdf"))
                    except (OSError, ValueError) as exc:
                        errors.append(f"cannot verify {label}.pdf_sha256: {exc}")
                    else:
                        if profile.get("pdf_sha256") != pdf_digest:
                            errors.append(f"{label}.pdf_sha256 does not match paper-review.pdf")


def require(obj: dict[str, Any], keys: set[str], label: str, errors: list[str]) -> None:
    missing = sorted(keys - obj.keys())
    if missing:
        errors.append(f"{label} missing keys: {', '.join(missing)}")


def validate_evidence(evidence: Any, label: str, errors: list[str]) -> None:
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"{label}.evidence must be a non-empty array")
        return
    for index, item in enumerate(evidence):
        item_label = f"{label}.evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} must be an object")
            continue
        require(item, {"type", "source", "locator", "content", "scope_checked"}, item_label, errors)
        if item.get("type") not in EVIDENCE_TYPES:
            errors.append(f"{item_label}.type is invalid")
        if not isinstance(item.get("source"), str) or not item.get("source", "").strip():
            errors.append(f"{item_label}.source must be non-empty")
        locator = item.get("locator")
        if not isinstance(locator, dict):
            errors.append(f"{item_label}.locator must be an object")
        elif item.get("type") != "absence_scope" and not any(
            value is not None and (not isinstance(value, str) or value.strip())
            for value in locator.values()
        ):
            errors.append(f"{item_label}.locator must identify at least one manuscript location")
        if item.get("type") == "absence_scope" and not item.get("scope_checked"):
            errors.append(f"{item_label} requires scope_checked")
        if item.get("type") != "absence_scope" and (
            not isinstance(item.get("content"), str) or not item.get("content", "").strip()
        ):
            errors.append(f"{item_label} requires non-empty content")


def validate_finding(item: Any, index: int, errors: list[str]) -> str | None:
    label = f"findings[{index}]"
    if not isinstance(item, dict):
        errors.append(f"{label} must be an object")
        return None
    require(
        item,
        {
            "id",
            "importance_rank",
            "dimension",
            "critique_basis",
            "data_limitation",
            "claim_ids",
            "reader_effect",
            "severity",
            "essential",
            "status",
            "support_state",
            "issue",
            "why_it_matters",
            "evidence",
            "confidence",
            "counterargument",
            "fix",
            "verification",
        },
        label,
        errors,
    )
    finding_id = item.get("id")
    if not isinstance(finding_id, str) or not FINDING_ID.fullmatch(finding_id):
        errors.append(f"{label}.id is invalid: {finding_id!r}")
        finding_id = None
    rank = item.get("importance_rank")
    if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
        errors.append(f"{label}.importance_rank must be a positive integer")
    if not isinstance(item.get("dimension"), str) or not item.get("dimension", "").strip():
        errors.append(f"{label}.dimension must be a non-empty string")
    if not isinstance(item.get("reader_effect"), str) or not item.get("reader_effect", "").strip():
        errors.append(f"{label}.reader_effect must be non-empty")
    data_limitation = item.get("data_limitation")
    critique_basis = item.get("critique_basis")
    severity = item.get("severity")
    if severity not in SEVERITIES:
        errors.append(f"{label}.severity is invalid")
    if not isinstance(item.get("essential"), bool):
        errors.append(f"{label}.essential must be boolean")
    if item.get("essential") and severity not in {"critical", "major"}:
        errors.append(f"{label}: essential findings must be critical or major")
    if item.get("status") not in {"dismissed", "resolved"} and data_limitation == "inherent_and_properly_bounded":
        errors.append(f"{label}: an inherent, properly bounded data limitation cannot be an active criticism")
    if data_limitation == "inherent_but_claim_exceeds" and critique_basis not in {
        "claim_exceeds_evidence", "internal_inconsistency", "reader_clarity"
    }:
        errors.append(f"{label}: inherent data limits must be framed as a claim-scope or reader issue")
    if critique_basis == "claim_exceeds_evidence" and not item.get("claim_ids"):
        errors.append(f"{label}: claim-overreach findings must link at least one claim family")
    validate_evidence(item.get("evidence"), label, errors)
    confidence = item.get("confidence")
    if not isinstance(confidence, dict) or confidence.get("level") not in {"high", "medium", "low"}:
        errors.append(f"{label}.confidence is invalid")
    elif not confidence.get("would_change_my_mind"):
        errors.append(f"{label}.confidence.would_change_my_mind must be non-empty")
    counter = item.get("counterargument")
    if not isinstance(counter, dict):
        errors.append(f"{label}.counterargument is required for every finding")
    elif counter.get("result") not in {"survived", "weakened", "refuted", "not_applicable"}:
        errors.append(f"{label}.counterargument.result must record a completed fairness check")
    elif item.get("status") not in {"dismissed", "resolved"} and counter.get("result") == "refuted":
        errors.append(f"{label}: an active finding cannot have a refuted counterargument")
    fix = item.get("fix")
    if not isinstance(fix, dict):
        errors.append(f"{label}.fix must be an object")
    else:
        require(
            fix,
            {
                "what", "how", "resolved_when", "strategy", "patch", "effort", "publishability", "dependencies",
                "requires_new_data", "current_design_can_support_primary_fix", "claim_narrowing_alternative",
            },
            f"{label}.fix",
            errors,
        )
        if not fix.get("publishability"):
            errors.append(f"{label}.fix.publishability must be non-empty")
        if not isinstance(fix.get("resolved_when"), str) or not fix.get("resolved_when", "").strip():
            errors.append(f"{label}.fix.resolved_when must state an observable completion condition")
        if data_limitation == "inherent_but_claim_exceeds":
            if fix.get("strategy") not in {"narrow_claim", "clarify_or_disclose", "reorganize_or_rewrite"}:
                errors.append(f"{label}: inherent data limits require claim narrowing or clarification, not a data demand")
            if fix.get("effort") == "new-data":
                errors.append(f"{label}: an inherent-data claim-scope finding cannot require new data")
            if fix.get("requires_new_data") is not False:
                errors.append(f"{label}: the primary fix for an inherent data limit must not require new data")
            if fix.get("current_design_can_support_primary_fix") is not True:
                errors.append(f"{label}: an inherent-data claim-scope finding needs a current-design repair")
            if not isinstance(fix.get("claim_narrowing_alternative"), str) or not fix.get("claim_narrowing_alternative", "").strip():
                errors.append(f"{label}: an inherent-data claim-scope finding needs a claim-narrowing alternative")
    return finding_id


def check_required_sections(
    text: str,
    file_label: str,
    headings: tuple[str, ...],
    errors: list[str],
) -> None:
    for heading in headings:
        heading_match = re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
        if not heading_match:
            errors.append(f"{file_label} is missing '{heading}'")
            continue
        following = text[heading_match.end():]
        next_heading = re.search(r"^## ", following, re.MULTILINE)
        content = following[:next_heading.start()] if next_heading else following
        if not content.strip():
            errors.append(f"{file_label} section '{heading}' must be non-empty")


def check_alternative_section_sets(
    text: str,
    file_label: str,
    alternatives: tuple[tuple[str, ...], ...],
    errors: list[str],
) -> None:
    """Accept a complete legacy or current section set, never a partial mixture."""
    recognized = {heading for headings in alternatives for heading in headings}
    present = {
        heading for heading in recognized
        if re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
    }
    for headings in alternatives:
        chosen = set(headings)
        if chosen.issubset(present) and not (present - chosen):
            counts = [len(re.findall(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)) for heading in headings]
            if counts != [1] * len(headings):
                errors.append(f"{file_label} requires each editing-comments heading exactly once")
                return
            positions = [text.find(heading) for heading in headings]
            if positions != sorted(positions):
                errors.append(f"{file_label} editing-comments headings are out of order")
                return
            check_required_sections(text, file_label, headings, errors)
            return
    if any(set(headings).issubset(present) for headings in alternatives):
        errors.append(f"{file_label} mixes legacy and current editing-comments headings")
        return
    choices = " or ".join(" / ".join(headings) for headings in alternatives)
    errors.append(f"{file_label} must contain one complete editing-comments section set: {choices}")


_QUOTE_FOLD = str.maketrans({
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "–": "-", "—": "-", "−": "-", "‑": "-",
    "…": "...", "\u00a0": " ",
})

_META_SCAFFOLD_OPENINGS = (
    "the reader needs to",
    "what must be clear",
    "decision at stake",
    "reader test",
    "a reader should",
    "readers should",
    "a reader-first",
    "this matters because",
    "the concern is",
    "the problem is",
    "the issue is",
)
_SUGGESTION_SCAFFOLD_OPENINGS = (
    "i suggest",
    "i recommend",
    "my suggestion is",
    "to address this issue",
    "to address this concern",
    "to address this comment",
    "a possible fix is",
    "a proportionate repair is",
)
_CONTENT_WORD_STOPLIST = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "because", "by", "for", "from",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that", "the",
    "their", "this", "to", "was", "were", "which", "with",
})


def prose_sentences(value: str) -> list[str]:
    """Return substantive prose sentences for conservative duplicate checks."""
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", value.strip()))
        if sentence.strip()
    ]


def content_words(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", value.lower())
    return {word for word in words if word not in _CONTENT_WORD_STOPLIST}


def near_duplicate_sentence_pair(value: str) -> tuple[int, int] | None:
    """Find only high-overlap sentence pairs, avoiding topic-overlap false positives."""
    sentences = prose_sentences(value)
    for left_index, left in enumerate(sentences):
        left_words = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", left.lower())
        if len(left_words) < 6:
            continue
        left_content = content_words(left)
        if len(left_content) < 4:
            continue
        for right_index in range(left_index + 1, len(sentences)):
            right = sentences[right_index]
            right_words = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", right.lower())
            if len(right_words) < 6:
                continue
            right_content = content_words(right)
            if len(right_content) < 4:
                continue
            shared = left_content & right_content
            union = left_content | right_content
            containment = len(shared) / min(len(left_content), len(right_content))
            jaccard = len(shared) / len(union)
            if len(shared) >= 4 and containment >= 0.8 and jaccard >= 0.5:
                return left_index + 1, right_index + 1
    return None


def normalize_quote(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(_QUOTE_FOLD)
    return " ".join(value.lower().split())


def normalize_source_transcription(value: str) -> str:
    """Normalize source prose without compatibility-folding mathematical glyphs."""

    value = unicodedata.normalize("NFC", value).translate(_QUOTE_FOLD)
    return " ".join(value.split())


def load_source_binding_context(
    review_dir: Path,
    findings: list[Any],
    errors: list[str],
) -> dict[str, Any]:
    """Load canonical source records used by claims and writing audit rows.

    The trust spine authenticates the retained files and anchor hashes.  This
    index adds the row-level joins needed to prevent a structured audit from
    certifying itself with a free-text quote, locator, or dismissed evidence.
    """

    manifest = load_json(review_dir / "evidence" / "source-manifest.json", errors)
    source_by_id: dict[str, dict[str, Any]] = {}
    anchor_by_id: dict[str, dict[str, Any]] = {}
    anchor_content: dict[str, str] = {}
    if isinstance(manifest, dict):
        source_by_id = {
            row.get("id"): row
            for row in manifest.get("sources", [])
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        anchor_by_id = {
            row.get("id"): row
            for row in manifest.get("anchors", [])
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        source_text: dict[str, str] = {}
        for source_id, source in source_by_id.items():
            extraction = source.get("extraction")
            raw_path = (
                extraction.get("path")
                if isinstance(extraction, dict) and isinstance(extraction.get("path"), str)
                else source.get("path")
            )
            if not isinstance(raw_path, str):
                continue
            try:
                source_text[source_id] = safe_read_bytes(review_dir, raw_path).decode("utf-8")
            except (OSError, UnicodeError, ValueError):
                # The trust-spine pass reports authoritative retained-file errors.
                continue
        for anchor_id, anchor in anchor_by_id.items():
            text = source_text.get(anchor.get("source_id"))
            start, end = anchor.get("start_char"), anchor.get("end_char")
            if (
                isinstance(text, str)
                and isinstance(start, int)
                and not isinstance(start, bool)
                and isinstance(end, int)
                and not isinstance(end, bool)
                and 0 <= start < end <= len(text)
            ):
                anchor_content[anchor_id] = text[start:end]

    all_evidence_by_id: dict[str, dict[str, Any]] = {}
    eligible_evidence_by_id: dict[str, dict[str, Any]] = {}
    eligible_evidence_owner: dict[str, str] = {}
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        finding_id = finding.get("id")
        eligible = (
            isinstance(finding_id, str)
            and finding.get("status") not in {"dismissed", "resolved"}
            and finding.get("verification") == "passed"
        )
        for evidence in finding.get("evidence", []):
            if not isinstance(evidence, dict) or not isinstance(evidence.get("id"), str):
                continue
            evidence_id = evidence["id"]
            all_evidence_by_id[evidence_id] = evidence
            if eligible:
                eligible_evidence_by_id[evidence_id] = evidence
                eligible_evidence_owner[evidence_id] = finding_id

    computations = load_json(review_dir / "evidence" / "computations.json", errors)
    computation_ids = {
        row.get("id")
        for row in computations.get("computations", [])
        if isinstance(computations, dict)
        and isinstance(row, dict)
        and isinstance(row.get("id"), str)
    } if isinstance(computations, dict) else set()
    external = load_json(review_dir / "evidence" / "external-sources.json", errors)
    external_support_ids = {
        support.get("id")
        for row in external.get("sources", [])
        if isinstance(external, dict) and isinstance(row, dict)
        for support in row.get("support_records", [])
        if isinstance(support, dict) and isinstance(support.get("id"), str)
    } if isinstance(external, dict) else set()
    return {
        "source_by_id": source_by_id,
        "anchor_by_id": anchor_by_id,
        "anchor_content": anchor_content,
        "all_evidence_by_id": all_evidence_by_id,
        "eligible_evidence_by_id": eligible_evidence_by_id,
        "eligible_evidence_owner": eligible_evidence_owner,
        "computation_ids": computation_ids,
        "external_support_ids": external_support_ids,
    }


def load_synthesis_support_context(
    review_dir: Path,
    findings: list[Any],
    errors: list[str],
) -> dict[str, Any]:
    """Resolve the canonical objects that may support referee synthesis.

    A synthesis mapping is a join, not an independent assertion of provenance.
    Claims therefore come from the canonical claim-family ledger, while finding
    evidence remains eligible only when its owner is active and verification
    passed.  This helper deliberately does not infer claims from finding links:
    a dismissed finding must not manufacture a claim ID that synthesis can use.
    """

    context = load_source_binding_context(review_dir, findings, errors)
    claims = load_json(review_dir / "evidence" / "claims.json", errors)
    claim_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(claims, dict):
        claim_by_id = {
            row.get("id"): row
            for row in claims.get("claim_families", [])
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
    eligible_finding_by_id = {
        row.get("id"): row
        for row in findings
        if isinstance(row, dict)
        and isinstance(row.get("id"), str)
        and row.get("status") not in {"dismissed", "resolved"}
        and row.get("verification") == "passed"
    }
    context.update({
        "claim_by_id": claim_by_id,
        "eligible_finding_by_id": eligible_finding_by_id,
    })
    return context


def evidence_has_canonical_support(
    evidence: dict[str, Any],
    context: dict[str, Any],
) -> bool:
    """Return whether one evidence record resolves to an authenticated object."""

    raw_anchor_ids = evidence.get("anchor_ids")
    anchor_ids = {
        value for value in raw_anchor_ids if isinstance(value, str)
    } if isinstance(raw_anchor_ids, list) else set()
    if isinstance(evidence.get("anchor_id"), str):
        anchor_ids.add(evidence["anchor_id"])
    representation = evidence.get("representation")
    for anchor_id in anchor_ids:
        anchor = context["anchor_by_id"].get(anchor_id)
        if not isinstance(anchor, dict):
            continue
        if representation == "checked_absence":
            if anchor.get("kind") == "scope":
                return True
        elif anchor.get("kind") != "scope":
            return True
    computation_id = evidence.get("computation_id")
    if isinstance(computation_id, str) and computation_id in context["computation_ids"]:
        return True
    support_record_id = evidence.get("support_record_id")
    return (
        isinstance(support_record_id, str)
        and support_record_id in context["external_support_ids"]
    )


def claim_has_canonical_support(
    claim: dict[str, Any],
    context: dict[str, Any],
) -> bool:
    """Return whether a canonical claim family owns at least one precise anchor."""

    raw_anchor_ids = claim.get("anchor_ids")
    anchor_ids = raw_anchor_ids if isinstance(raw_anchor_ids, list) else []
    return any(
        isinstance(anchor_id, str)
        and isinstance(context["anchor_by_id"].get(anchor_id), dict)
        and context["anchor_by_id"][anchor_id].get("kind") != "scope"
        for anchor_id in anchor_ids
    )


def validate_exact_source_binding(
    *,
    label: str,
    anchor_id: Any,
    representation: Any,
    content: Any,
    locator: Any,
    coverage_unit_id: Any,
    context: dict[str, Any],
    coverage_anchor_ids_by_unit: dict[str, set[str]],
    errors: list[str],
) -> str | None:
    """Reconcile a quoted audit row with one precise canonical source anchor."""

    if not isinstance(anchor_id, str):
        errors.append(f"{label} requires a canonical anchor_id")
        return None
    anchor = context["anchor_by_id"].get(anchor_id)
    if not isinstance(anchor, dict):
        errors.append(f"{label} references unknown canonical anchor {anchor_id}")
        return None
    if anchor.get("kind") == "scope":
        errors.append(f"{label} must use a precise source anchor, not scope anchor {anchor_id}")
    if not isinstance(coverage_unit_id, str) or anchor_id not in coverage_anchor_ids_by_unit.get(
        coverage_unit_id, set()
    ):
        errors.append(
            f"{label} anchor {anchor_id} is not assigned to coverage unit {coverage_unit_id}"
        )
    canonical = context["anchor_content"].get(anchor_id)
    if not isinstance(canonical, str):
        errors.append(f"{label} anchor {anchor_id} has no readable canonical text span")
        return None
    if representation == "verbatim":
        if content != canonical:
            errors.append(f"{label} content is not verbatim at canonical anchor {anchor_id}")
    elif representation == "normalized_transcription":
        if not isinstance(content, str) or normalize_source_transcription(
            content
        ) != normalize_source_transcription(canonical):
            errors.append(
                f"{label} content does not match normalized canonical anchor {anchor_id}"
            )
    else:
        errors.append(
            f"{label} representation must be verbatim or normalized_transcription"
        )
    canonical_locator = anchor.get("locator")
    if (
        not isinstance(locator, str)
        or not isinstance(canonical_locator, str)
        or normalize_source_transcription(locator)
        != normalize_source_transcription(canonical_locator)
    ):
        errors.append(f"{label} locator does not match canonical anchor {anchor_id}")
    return anchor_id


def validate_source_evidence_refs(
    raw_refs: Any,
    *,
    label: str,
    coverage_unit_ids: set[str],
    context: dict[str, Any],
    coverage_anchor_ids_by_unit: dict[str, set[str]],
    errors: list[str],
) -> dict[str, set[str]]:
    """Validate typed evidence joins and return their resolved support sets."""

    resolved: dict[str, set[str]] = {
        "direct_anchor_ids": set(),
        "absence_anchor_ids": set(),
        "finding_owners": set(),
    }
    if not isinstance(raw_refs, list) or not raw_refs:
        errors.append(f"{label} requires at least one canonical evidence reference")
        return resolved
    permitted_unit_anchors = set().union(
        *(coverage_anchor_ids_by_unit.get(unit_id, set()) for unit_id in coverage_unit_ids)
    ) if coverage_unit_ids else set()
    for index, ref in enumerate(raw_refs, start=1):
        ref_label = f"{label} evidence reference {index}"
        if not isinstance(ref, dict):
            errors.append(f"{ref_label} must be an object")
            continue
        kind, record_id, purpose = ref.get("kind"), ref.get("id"), ref.get("purpose")
        if not isinstance(kind, str) or not isinstance(record_id, str):
            errors.append(f"{ref_label} requires kind and id")
            continue
        if purpose not in {"direct_support", "checked_absence"}:
            errors.append(f"{ref_label} has unsupported purpose {purpose!r}")
            continue
        anchors: set[str] = set()
        evidence: dict[str, Any] | None = None
        if kind == "anchor":
            anchor = context["anchor_by_id"].get(record_id)
            if not isinstance(anchor, dict):
                errors.append(f"{ref_label} references unknown canonical anchor {record_id}")
                continue
            anchors.add(record_id)
        elif kind == "finding_evidence":
            evidence = context["eligible_evidence_by_id"].get(record_id)
            if not isinstance(evidence, dict):
                if record_id in context["all_evidence_by_id"]:
                    errors.append(
                        f"{ref_label} cannot use dismissed, resolved, or unverified finding evidence {record_id}"
                    )
                else:
                    errors.append(f"{ref_label} references unknown finding evidence {record_id}")
                continue
            owner = context["eligible_evidence_owner"].get(record_id)
            if isinstance(owner, str):
                resolved["finding_owners"].add(owner)
            raw_anchor = evidence.get("anchor_id")
            if isinstance(raw_anchor, str):
                anchors.add(raw_anchor)
            anchors.update(
                value for value in evidence.get("anchor_ids", []) if isinstance(value, str)
            )
            representation = evidence.get("representation")
            if purpose == "checked_absence":
                if evidence.get("type") != "absence_scope" or representation != "checked_absence":
                    errors.append(
                        f"{ref_label} checked_absence requires passed absence-scope evidence"
                    )
            elif representation not in {
                "verbatim", "normalized_transcription", "composite_comparison", "computed_result"
            }:
                errors.append(
                    f"{ref_label} cannot use self-authored representation {representation!r} as direct support"
                )
        elif kind == "computation":
            if record_id not in context["computation_ids"]:
                errors.append(f"{ref_label} references unknown computation {record_id}")
            if purpose != "direct_support":
                errors.append(f"{ref_label} computation cannot certify a checked absence")
            continue
        elif kind == "external_support":
            if record_id not in context["external_support_ids"]:
                errors.append(f"{ref_label} references unknown external support record {record_id}")
            if purpose != "direct_support":
                errors.append(f"{ref_label} external support cannot certify a checked absence")
            continue
        else:
            errors.append(f"{ref_label} has unsupported kind {kind!r}")
            continue

        if not anchors:
            errors.append(f"{ref_label} does not resolve to a canonical source anchor")
            continue
        unknown_anchors = sorted(anchors - set(context["anchor_by_id"]))
        if unknown_anchors:
            errors.append(
                f"{ref_label} resolves to unknown anchors: {', '.join(unknown_anchors)}"
            )
        if coverage_unit_ids and not anchors.intersection(permitted_unit_anchors):
            errors.append(
                f"{ref_label} is not assigned to the row's coverage units"
            )
        if isinstance(evidence, dict):
            representation = evidence.get("representation")
            content = evidence.get("content")
            for anchor_id in anchors:
                canonical_content = context["anchor_content"].get(anchor_id)
                if representation == "verbatim" and isinstance(canonical_content, str):
                    if content != canonical_content:
                        errors.append(
                            f"{ref_label} finding evidence is not verbatim at anchor {anchor_id}"
                        )
                elif representation == "normalized_transcription" and isinstance(
                    canonical_content, str
                ):
                    if not isinstance(content, str) or normalize_source_transcription(
                        content
                    ) != normalize_source_transcription(
                        canonical_content
                    ):
                        errors.append(
                            f"{ref_label} finding evidence does not match normalized anchor {anchor_id}"
                        )
            if len(anchors) == 1:
                anchor_id = next(iter(anchors))
                anchor = context["anchor_by_id"].get(anchor_id, {})
                canonical_locator = str(anchor.get("locator", ""))
                normalized_locator = normalize_source_transcription(canonical_locator)
                locator = evidence.get("locator")
                if isinstance(locator, dict):
                    locator_patterns = {
                        "section": r"(?:^|\b)section\s+{}(?:\b|$)",
                        "paragraph": r"(?:^|\b)(?:paragraph|para\.?|¶)\s*{}(?:\b|$)",
                        "page": r"(?:^|\b)(?:page|p\.?)\s*{}(?:\b|$)",
                        "equation": r"(?:^|\b)(?:equation|eq\.?)\s*{}(?:\b|$)",
                    }
                    for field, pattern in locator_patterns.items():
                        value = locator.get(field)
                        if value is None:
                            continue
                        normalized_value = normalize_source_transcription(str(value))
                        if not re.search(
                            pattern.format(re.escape(normalized_value)),
                            normalized_locator,
                            re.IGNORECASE,
                        ):
                            errors.append(
                                f"{ref_label} finding locator {field} does not reconcile to anchor {anchor_id}"
                            )
                    file_value = locator.get("file")
                    source = context["source_by_id"].get(anchor.get("source_id"), {})
                    source_path = source.get("path") if isinstance(source, dict) else None
                    if (
                        isinstance(file_value, str)
                        and isinstance(source_path, str)
                        and Path(file_value).name != Path(source_path).name
                    ):
                        errors.append(
                            f"{ref_label} finding locator file does not reconcile to anchor {anchor_id}"
                        )
        for anchor_id in anchors:
            anchor = context["anchor_by_id"].get(anchor_id)
            if not isinstance(anchor, dict):
                continue
            is_scope = anchor.get("kind") == "scope"
            if purpose == "checked_absence":
                if not is_scope:
                    errors.append(
                        f"{ref_label} checked_absence must resolve to a scope anchor, not {anchor_id}"
                    )
                else:
                    resolved["absence_anchor_ids"].add(anchor_id)
            else:
                if is_scope:
                    errors.append(
                        f"{ref_label} direct support requires a precise anchor, not scope anchor {anchor_id}"
                    )
                else:
                    resolved["direct_anchor_ids"].add(anchor_id)
    return resolved


def pdf_symbol_candidate_inventory(
    ingestion: dict[str, Any],
    anchor_by_id: dict[str, dict[str, Any]],
    source_id: str,
) -> dict[tuple[str, tuple[str, ...]], set[str]]:
    """Map every PDF-ingestion symbol candidate to its canonical block anchors."""

    anchors_by_span = {
        (anchor.get("start_char"), anchor.get("end_char")): anchor_id
        for anchor_id, anchor in anchor_by_id.items()
        if anchor.get("source_id") == source_id and anchor.get("kind") != "scope"
    }
    block_anchor_ids = {
        block.get("id"): anchors_by_span.get(
            (block.get("markdown_start"), block.get("markdown_end"))
        )
        for block in ingestion.get("blocks", [])
        if isinstance(block, dict) and isinstance(block.get("id"), str)
    }
    result: dict[tuple[str, tuple[str, ...]], set[str]] = {}
    for symbol in ingestion.get("symbols", []):
        if not isinstance(symbol, dict):
            continue
        symbol_text = symbol.get("symbol")
        codepoints = symbol.get("codepoints", [])
        if not isinstance(symbol_text, str) or not isinstance(codepoints, list):
            continue
        key = (
            symbol_text,
            tuple(value for value in codepoints if isinstance(value, str)),
        )
        result[key] = {
            anchor_id
            for occurrence in symbol.get("occurrences", [])
            if isinstance(occurrence, dict)
            for anchor_id in [block_anchor_ids.get(occurrence.get("block_id"))]
            if isinstance(anchor_id, str)
        }
    return result


def validate_comment_section(
    text: str,
    file_label: str,
    section_title: str,
    expected_items: list[dict[str, Any]],
    errors: list[str],
) -> set[str]:
    detail_match = re.search(rf"^## {re.escape(section_title)} \((\d+)\)\s*$", text, re.MULTILINE)
    if not detail_match:
        errors.append(f"{file_label} is missing '## {section_title} (N)'")
        return set()

    detail_start = detail_match.end()
    next_h2 = re.search(r"^## ", text[detail_start:], re.MULTILINE)
    detail_block = text[detail_start : detail_start + next_h2.start()] if next_h2 else text[detail_start:]
    comment_count = len(re.findall(r"^### \d+\. ", detail_block, re.MULTILINE))
    declared_count = int(detail_match.group(1))
    if declared_count != comment_count:
        errors.append(f"{section_title} count mismatch: heading says {declared_count}, found {comment_count}")
    if comment_count != len(expected_items):
        errors.append(
            f"{section_title} must contain every active finding exactly once: "
            f"found {comment_count}, expected {len(expected_items)}"
        )

    blocks = re.split(r"(?=^### \d+\. )", detail_block, flags=re.MULTILINE)
    blocks = [block for block in blocks if re.match(r"^### \d+\. ", block)]
    visible_numbers = [int(value) for value in re.findall(r"^### (\d+)\. ", detail_block, re.MULTILINE)]
    if visible_numbers != list(range(1, comment_count + 1)):
        errors.append(f"{section_title} visible numbering must be consecutive 1..N")

    block_quotes: list[str] = []
    feedback_texts: list[str] = []
    for block_index, block in enumerate(blocks, start=1):
        if len(re.findall(r"^\*\*Status\*\*: \[Pending\]\s*$", block, re.MULTILINE)) != 1:
            errors.append(f"detailed comment {block_index} requires exactly one '**Status**: [Pending]' field")
        if len(re.findall(r"^\*\*Quote\*\*:\s*$", block, re.MULTILINE)) != 1:
            errors.append(f"detailed comment {block_index} requires exactly one Quote field")
        quote_match = re.search(r"^\*\*Quote\*\*:\s*\n(?P<quote>(?:^>.*(?:\n|$))+)", block, re.MULTILINE)
        quote_text = "" if not quote_match else re.sub(
            r"^>\s?", "", quote_match.group("quote"), flags=re.MULTILINE
        ).strip()
        if not quote_text:
            errors.append(f"detailed comment {block_index} requires a non-empty block quote")
        block_quotes.append(quote_text)
        feedback_match = re.search(r"^\*\*Feedback\*\*:\s*(?P<feedback>[\s\S]+?)\s*\Z", block, re.MULTILINE)
        feedback_text = "" if not feedback_match else feedback_match.group("feedback").strip()
        if len(re.findall(r"^\*\*Feedback\*\*:", block, re.MULTILINE)) != 1 or not feedback_text:
            errors.append(f"detailed comment {block_index} requires exactly one non-empty Feedback field")
        feedback_texts.append(feedback_text)

    detail_ids = re.findall(r"<!-- finding_id: ([A-Z][A-Z0-9_-]*-[0-9]{2,}) -->", detail_block)
    if len(detail_ids) != comment_count:
        errors.append("each detailed comment requires exactly one hidden finding_id")
    expected_order = [
        item.get("id")
        for item in sorted(expected_items, key=lambda item: item.get("importance_rank", 10**9))
    ]
    if detail_ids != expected_order:
        errors.append(f"{section_title} finding IDs must follow importance_rank order")

    findings_by_id = {item.get("id"): item for item in expected_items}
    prohibited_feedback_phrases = (
        "As written,",
        "The strongest author-side defense is that",
        "The checked manuscript supports that defense only to this extent",
        "A proportionate repair is to",
        "leading-field verification requires",
        "the authors fail to",
        "the authors ignore",
        "There seems to be an issue",
        "The document would benefit from",
        "canonical record",
        "verification passed",
        "coverage unit",
        "finding ID",
        "audit gate",
        "the checked manuscript",
        "A careful reader cannot tell whether the stated claim is supported at the precision and scope presented.",
        "A careful reader may misread the object, unit, comparison, or evidentiary strength at this location.",
    )
    malformed_acronyms = ("vAR", "iRF", "hPI", "sVAR", "fOMC")
    for block_index, (finding_id, quote_text, feedback_text) in enumerate(
        zip(detail_ids, block_quotes, feedback_texts), start=1
    ):
        finding = findings_by_id.get(finding_id, {})
        evidence_texts = [
            evidence.get("content")
            for evidence in finding.get("evidence", [])
            if isinstance(evidence, dict) and isinstance(evidence.get("content"), str)
        ]
        normalized_quote = normalize_quote(quote_text)
        if evidence_texts and not any(
            normalized_quote in normalize_quote(evidence)
            for evidence in evidence_texts
        ):
            errors.append(f"detailed comment {block_index} quote does not match ledger evidence for {finding_id}")
        for phrase in prohibited_feedback_phrases:
            if phrase.lower() in feedback_text.lower():
                errors.append(f"detailed comment {block_index} uses prohibited boilerplate: {phrase}")
        for acronym in malformed_acronyms:
            if acronym in feedback_text:
                errors.append(f"detailed comment {block_index} contains malformed acronym {acronym}")

    sentence_owners: dict[str, set[str]] = {}
    major_label_signatures: list[tuple[str, ...]] = []
    for finding_id, feedback_text in zip(detail_ids, feedback_texts):
        for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\*\*[^*]+\*\*", "", feedback_text)):
            normalized_sentence = " ".join(sentence.lower().split()).strip()
            if len(normalized_sentence.split()) >= 10:
                sentence_owners.setdefault(normalized_sentence, set()).add(finding_id)
        if findings_by_id.get(finding_id, {}).get("severity") in {"critical", "major"}:
            labels = tuple(re.findall(r"\*\*([^*]+?)\.\*\*", feedback_text))
            if labels:
                major_label_signatures.append(labels)
    for sentence, owners in sentence_owners.items():
        if len(owners) >= 3:
            errors.append(
                "detailed comments repeat a nontechnical sentence across "
                f"{len(owners)} findings ({', '.join(sorted(owners))}): {sentence}"
            )
    if len(major_label_signatures) >= 6:
        signature, count = Counter(major_label_signatures).most_common(1)[0]
        if count > len(major_label_signatures) / 2:
            errors.append(
                "more than half of critical/major comments use the same label sequence: "
                + " / ".join(signature)
            )
    return set(detail_ids)


def validate_comment_section_v3(
    text: str,
    file_label: str,
    section_title: str,
    expected_items: list[dict[str, Any]],
    errors: list[str],
) -> set[str]:
    """Validate the v0.3 issue-first, status-last detailed-comment contract."""
    detail_match = re.search(rf"^## {re.escape(section_title)} \((\d+)\)\s*$", text, re.MULTILINE)
    if not detail_match:
        errors.append(f"{file_label} is missing '## {section_title} (N)'")
        return set()

    detail_start = detail_match.end()
    next_h2 = re.search(r"^## ", text[detail_start:], re.MULTILINE)
    detail_block = text[detail_start : detail_start + next_h2.start()] if next_h2 else text[detail_start:]
    blocks = re.split(r"(?=^### \d+\. )", detail_block, flags=re.MULTILINE)
    blocks = [block for block in blocks if re.match(r"^### \d+\. ", block)]
    declared_count = int(detail_match.group(1))
    if declared_count != len(blocks):
        errors.append(f"{section_title} count mismatch: heading says {declared_count}, found {len(blocks)}")
    if len(blocks) != len(expected_items):
        errors.append(
            f"{section_title} must contain every active finding exactly once: "
            f"found {len(blocks)}, expected {len(expected_items)}"
        )
    visible_numbers = [int(value) for value in re.findall(r"^### (\d+)\. ", detail_block, re.MULTILINE)]
    if visible_numbers != list(range(1, len(blocks) + 1)):
        errors.append(f"{section_title} visible numbering must be consecutive 1..N")

    detail_ids = re.findall(r"<!-- finding_id: ([A-Z][A-Z0-9_-]*-[0-9]{2,}) -->", detail_block)
    if len(detail_ids) != len(blocks):
        errors.append("each detailed comment requires exactly one hidden finding_id")
    expected_order = [
        item.get("id")
        for item in sorted(expected_items, key=lambda item: item.get("importance_rank", 10**9))
    ]
    if detail_ids != expected_order:
        errors.append(f"{section_title} finding IDs must follow importance_rank order")

    findings_by_id = {item.get("id"): item for item in expected_items}
    current_labels = ["Issue", "Relevant text", "Concern", "Suggestions", "Status"]
    archived_labels = [
        "Issue", "Relevant quote or evidence", "Problem and concern", "Constructive feedback", "Status"
    ]
    early_labels = archived_labels[:-1] + ["Possible fix", "Status"]
    prohibited_phrases = (
        "As written,",
        "The strongest author-side defense is that",
        "The checked manuscript supports that defense only to this extent",
        "A proportionate repair is to",
        "leading-field verification requires",
        "the authors fail to",
        "the authors ignore",
        "There seems to be an issue",
        "The document would benefit from",
        "canonical record",
        "verification passed",
        "coverage unit",
        "finding ID",
        "audit gate",
        "the checked manuscript",
    )
    malformed_acronyms = ("vAR", "iRF", "hPI", "sVAR", "fOMC")
    prose_by_id: dict[str, str] = {}

    for block_index, (block, finding_id) in enumerate(zip(blocks, detail_ids), start=1):
        finding = findings_by_id.get(finding_id, {})
        field_matches = list(re.finditer(r"^\*\*([^*]+)\*\*:\s*", block, re.MULTILINE))
        labels = [match.group(1) for match in field_matches]
        if labels not in (current_labels, archived_labels, early_labels):
            errors.append(
                f"detailed comment {block_index} fields must appear as Issue, Relevant text, "
                "Concern, Suggestions, then Status"
            )
            continue
        if labels[-1] != "Status":
            errors.append(f"detailed comment {block_index} must place Status last")

        values: dict[str, str] = {}
        for index, match in enumerate(field_matches):
            end = field_matches[index + 1].start() if index + 1 < len(field_matches) else len(block)
            values[match.group(1)] = block[match.end():end].strip()
        for label in labels[:-1]:
            if not values.get(label):
                errors.append(f"detailed comment {block_index} requires non-empty {label}")
        if "Possible fix" in labels and not values.get("Possible fix"):
            errors.append(f"detailed comment {block_index} has an empty Possible fix")
        if values.get("Status") != "[Pending]":
            errors.append(f"detailed comment {block_index} requires '**Status**: [Pending]' as its final field")

        issue_text = values.get("Issue", "")
        canonical_issue = str(finding.get("issue", ""))
        if issue_text and canonical_issue and normalize_quote(issue_text) != normalize_quote(canonical_issue):
            errors.append(f"detailed comment {block_index} Issue does not match ledger issue for {finding_id}")

        evidence_label = "Relevant text" if "Relevant text" in values else "Relevant quote or evidence"
        concern_label = "Concern" if "Concern" in values else "Problem and concern"
        suggestions_label = "Suggestions" if "Suggestions" in values else "Constructive feedback"
        evidence_block = values.get(evidence_label, "")
        evidence_rows = [
            evidence for evidence in finding.get("evidence", [])
            if isinstance(evidence, dict)
        ]
        display_id = finding.get("display_evidence_id")
        displayed = next(
            (evidence for evidence in evidence_rows if evidence.get("id") == display_id),
            evidence_rows[0] if evidence_rows else {},
        )
        representation = displayed.get("representation")
        derived_note = representation in {
            "reviewer_observation",
            "composite_comparison",
            "checked_absence",
            "computed_result",
        }
        evidence_lines = evidence_block.splitlines()
        quote_lines = [line for line in evidence_lines if line.startswith(">")]
        if derived_note and not quote_lines:
            display_text = evidence_block.strip()
            if not display_text:
                errors.append(f"detailed comment {block_index} requires one non-empty evidence note")
            if re.match(
                r"^\[(?:Reviewer observation|Figure observation|Table observation|"
                r"Reviewer comparison|Checked absence|Computation)\]",
                display_text,
            ):
                errors.append(
                    f"detailed comment {block_index} exposes an internal evidence label"
                )
        else:
            display_text = "\n".join(
                re.sub(r"^>\s?", "", line) for line in quote_lines
            ).strip()
            if not display_text or any(
                line.strip() and not line.startswith(">") for line in evidence_lines
            ):
                errors.append(f"detailed comment {block_index} requires one non-empty block quote")
        if f"\n\n**{concern_label}**:" not in block:
            errors.append(
                f"detailed comment {block_index} requires a blank line after Relevant text"
            )
        evidence_texts = [
            evidence.get("content")
            for evidence in evidence_rows
            if isinstance(evidence.get("content"), str)
        ]

        def without_internal_prefix(value: str) -> str:
            return re.sub(
                r"^\[(?:Rendered transcription|Reviewer observation|Reviewer comparison|"
                r"Figure observation|Table observation|Checked absence|Computation)\]\s*",
                "",
                value,
            )

        normalized_display = normalize_quote(without_internal_prefix(display_text))
        if evidence_texts and not any(
            normalized_display in normalize_quote(without_internal_prefix(evidence))
            for evidence in evidence_texts
        ):
            errors.append(f"detailed comment {block_index} evidence does not match ledger evidence for {finding_id}")

        prose = " ".join(
            values.get(label, "") for label in (concern_label, suggestions_label, "Possible fix")
        ).strip()
        prose_by_id[finding_id] = prose
        for phrase in prohibited_phrases:
            if phrase.lower() in prose.lower():
                errors.append(f"detailed comment {block_index} uses prohibited boilerplate: {phrase}")
        for acronym in malformed_acronyms:
            if acronym in prose:
                errors.append(f"detailed comment {block_index} contains malformed acronym {acronym}")

        problem_text = values.get(concern_label, "").lstrip()
        normalized_problem = problem_text.lower()
        concern_openings = _META_SCAFFOLD_OPENINGS if labels == current_labels else _META_SCAFFOLD_OPENINGS[:4]
        for opening in concern_openings:
            if normalized_problem.startswith(opening):
                errors.append(
                    f"detailed comment {block_index} ({finding_id}) begins {concern_label} "
                    f"with meta-scaffolding: {opening}"
                )
                break

        suggestion_text = values.get(suggestions_label, "")
        normalized_suggestion = suggestion_text.lstrip().lower()
        suggestion_openings = _SUGGESTION_SCAFFOLD_OPENINGS if labels == current_labels else ()
        for opening in suggestion_openings:
            if normalized_suggestion.startswith(opening):
                errors.append(
                    f"detailed comment {block_index} ({finding_id}) begins {suggestions_label} "
                    f"with meta-scaffolding: {opening}"
                )
                break

        duplicate_pair = near_duplicate_sentence_pair(suggestion_text)
        if duplicate_pair is not None:
            errors.append(
                f"detailed comment {block_index} ({finding_id}) repeats recommendation content "
                f"within {suggestions_label} sentences "
                f"{duplicate_pair[0]} and {duplicate_pair[1]}"
            )

    sentence_owners: dict[str, set[str]] = {}
    for finding_id, prose in prose_by_id.items():
        for sentence in re.split(r"(?<=[.!?])\s+", prose):
            normalized_sentence = " ".join(sentence.lower().split()).strip()
            if len(normalized_sentence.split()) >= 10:
                sentence_owners.setdefault(normalized_sentence, set()).add(finding_id)
    for sentence, owners in sentence_owners.items():
        if len(owners) >= 3:
            errors.append(
                "detailed comments repeat a nontechnical sentence across "
                f"{len(owners)} findings ({', '.join(sorted(owners))}): {sentence}"
            )
    return set(detail_ids)


def validate_review(review_dir: Path) -> list[str]:
    errors: list[str] = []
    run = load_json(review_dir / "run.json", errors)
    ledger = load_json(review_dir / "findings.json", errors)

    if not isinstance(run, dict) or not isinstance(ledger, dict):
        return errors

    validate_schema(run, "run.schema.json", "run.json", errors)
    validate_schema(ledger, "findings.schema.json", "findings.json", errors)

    require(
        run,
        {
            "schema_version",
            "review_id",
            "status",
            "mode",
            "target",
            "paper_family",
            "designs",
            "identity_handling",
            "assessment_boundary",
            "capabilities",
            "comment_policy",
            "stage_status",
            "gates_loaded",
            "counts",
            "verification_passed",
        },
        "run.json",
        errors,
    )
    require(ledger, {"schema_version", "review_id", "findings"}, "findings.json", errors)
    run_version = run.get("schema_version")
    ledger_version = ledger.get("schema_version")
    if run_version not in {"0.1", "0.2", "0.3", "0.4"} or ledger_version not in {"0.1", "0.2", "0.3", "0.4"}:
        errors.append("schema_version must be '0.1', '0.2', '0.3', or '0.4' in both JSON files")
    if run_version != ledger_version:
        errors.append("schema_version differs between run.json and findings.json")
    v2 = run_version == "0.2" and ledger_version == "0.2"
    v3 = run_version == "0.3" and ledger_version == "0.3"
    v4 = run_version == "0.4" and ledger_version == "0.4"
    current_contract = v3 or v4
    split_contract = v2 or current_contract
    strict_v4_audits = v4
    strict_burden_coverage = v4
    finalization_path_for_contract = review_dir / "finalization.json"
    if v4 and finalization_path_for_contract.exists():
        try:
            finalized_contract = strict_json_load(finalization_path_for_contract)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            # The receipt validator reports the malformed file; fail closed here.
            strict_v4_audits = True
            strict_burden_coverage = True
        else:
            strict_v4_audits = not (
                isinstance(finalized_contract, dict)
                and finalized_contract.get("schema_version") == "0.1"
            )
            strict_burden_coverage = not (
                isinstance(finalized_contract, dict)
                and finalized_contract.get("schema_version") in {"0.1", "0.2"}
            )
    strict_replication_contract = strict_burden_coverage or (
        v4 and run.get("mode") == "quick" and strict_v4_audits
    )
    requested_addons = run.get("requested_addons")
    if strict_burden_coverage and run.get("mode") == "full" and not isinstance(requested_addons, list):
        errors.append("current v0.4 full review requires run.json.requested_addons (use [] when none were requested)")
    journal_fit_requested = isinstance(requested_addons, list) and "journal_fit" in requested_addons
    if run.get("review_id") != ledger.get("review_id"):
        errors.append("review_id differs between run.json and findings.json")
    manifest_path = review_dir / "review-manifest.json"
    if current_contract and not manifest_path.exists():
        errors.append("review-manifest.json is required for contract v0.3+")
    if manifest_path.exists():
        manifest = load_json(manifest_path, errors)
        if isinstance(manifest, dict):
            validate_schema(manifest, "review-manifest.schema.json", "review-manifest.json", errors)
            if manifest.get("review_id") != run.get("review_id"):
                errors.append("review-manifest.json review_id differs from run.json")
            documents = manifest.get("documents", [])
            if isinstance(documents, list):
                document_ids = [row.get("id") for row in documents if isinstance(row, dict)]
                document_paths = [row.get("path") for row in documents if isinstance(row, dict)]
                duplicate_ids = sorted(value for value, count in Counter(document_ids).items() if value and count > 1)
                duplicate_paths = sorted(value for value, count in Counter(document_paths).items() if value and count > 1)
                if duplicate_ids:
                    errors.append("review-manifest.json has duplicate document IDs: " + ", ".join(duplicate_ids))
                if duplicate_paths:
                    errors.append("review-manifest.json has duplicate document paths: " + ", ".join(duplicate_paths))
                if (
                    run.get("prior_round") is not None
                    and "evidence/round-reconciliation.md" not in document_paths
                ):
                    errors.append(
                        "review-manifest.json must declare evidence/round-reconciliation.md "
                        "when run.json.prior_round is active"
                    )
                root = review_dir.resolve()
                for index, raw_path in enumerate(document_paths):
                    if not isinstance(raw_path, str):
                        continue
                    label = f"review-manifest.json documents[{index}].path"
                    try:
                        portable_path = canonical_portable_path(raw_path)
                    except ValueError as exc:
                        errors.append(f"{label} must be a canonical portable path: {exc}")
                        continue
                    relative = Path(portable_path)
                    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".md":
                        errors.append(f"{label} must be a safe relative Markdown path")
                        continue
                    candidate = review_dir / relative
                    if candidate.is_symlink():
                        errors.append(f"{label} must not be a symbolic link: {raw_path}")
                        continue
                    try:
                        resolved = candidate.resolve(strict=True)
                    except FileNotFoundError:
                        errors.append(f"{label} does not exist: {raw_path}")
                        continue
                    try:
                        resolved.relative_to(root)
                    except ValueError:
                        errors.append(f"{label} resolves outside the review directory: {raw_path}")
                        continue
                    if not resolved.is_file():
                        errors.append(f"{label} must resolve to a regular file: {raw_path}")
    if run.get("mode") not in {"quick", "full"}:
        errors.append("run.json.mode must be quick or full")
    comment_policy = run.get("comment_policy")
    if not isinstance(comment_policy, dict):
        errors.append("run.json.comment_policy must be an object")
        comment_policy = {}
    else:
        require(comment_policy, {"minimum_target", "maximum", "exhaustive"}, "run.json.comment_policy", errors)
    minimum_target = comment_policy.get("minimum_target")
    maximum_comments = comment_policy.get("maximum")
    substance_maximum = comment_policy.get("substance_maximum")
    writing_maximum = comment_policy.get("writing_maximum")
    channel_capacities_present = (
        "substance_maximum" in comment_policy or "writing_maximum" in comment_policy
    )
    if not isinstance(minimum_target, int) or isinstance(minimum_target, bool) or minimum_target < 0:
        errors.append("run.json.comment_policy.minimum_target must be a non-negative integer")
        minimum_target = 0
    if maximum_comments is not None and (
        not isinstance(maximum_comments, int) or isinstance(maximum_comments, bool) or maximum_comments < 1
    ):
        errors.append("run.json.comment_policy.maximum must be null or a positive integer")
        maximum_comments = None
    if maximum_comments is not None and minimum_target > maximum_comments:
        errors.append("run.json.comment_policy.minimum_target cannot exceed maximum")
    if channel_capacities_present:
        if "substance_maximum" not in comment_policy or "writing_maximum" not in comment_policy:
            errors.append(
                "run.json.comment_policy must declare substance_maximum and writing_maximum together"
            )
        for name, value in (
            ("substance_maximum", substance_maximum),
            ("writing_maximum", writing_maximum),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                errors.append(
                    f"run.json.comment_policy.{name} must be a positive integer when channel capacities are used"
                )
        if maximum_comments is not None:
            errors.append(
                "run.json.comment_policy.maximum must be null when channel-specific capacities are used"
            )
        if minimum_target > sum(
            value for value in (substance_maximum, writing_maximum)
            if isinstance(value, int) and not isinstance(value, bool)
        ):
            errors.append(
                "run.json.comment_policy.minimum_target cannot exceed the combined channel capacity"
            )
    if not isinstance(comment_policy.get("exhaustive"), bool):
        errors.append("run.json.comment_policy.exhaustive must be boolean")
    if v4 and run.get("mode") == "full" and maximum_comments is not None:
        errors.append(
            "v0.4 full reviews must set the legacy comment_policy.maximum to null"
        )
    if v4 and run.get("mode") == "full" and channel_capacities_present:
        if substance_maximum != 100 or writing_maximum != 30:
            errors.append(
                "current v0.4 full reviews use substance_maximum 100 and writing_maximum 30"
            )
    stage_status = run.get("stage_status")
    required_stages = {
        "intake",
        "reconstruction",
        "frontier",
        "audit",
        "counterargument",
        "synthesis",
        "verification",
        "delivery",
    }
    if not isinstance(stage_status, dict):
        errors.append("run.json.stage_status must be an object")
    else:
        require(stage_status, required_stages, "run.json.stage_status", errors)
        for stage, value in stage_status.items():
            if stage in required_stages and value not in STAGES:
                errors.append(f"invalid stage state for {stage}: {value!r}")

    findings = ledger.get("findings")
    if not isinstance(findings, list):
        errors.append("findings.json.findings must be an array")
        findings = []
    ids = [validate_finding(item, index, errors) for index, item in enumerate(findings)]
    clean_ids = [item for item in ids if item]
    duplicates = sorted(item for item, count in Counter(clean_ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate finding IDs: {', '.join(duplicates)}")

    active = [
        item for item in findings
        if isinstance(item, dict)
        and item.get("status") not in {"dismissed", "resolved"}
        and item.get("severity") in {"critical", "major", "minor", "info"}
    ]
    substance_active = [
        item for item in active
        if not split_contract or item.get("report_channel", "substance") == "substance"
    ]
    writing_active = [
        item for item in active
        if split_contract and item.get("report_channel", "substance") == "writing"
    ]
    if run.get("prior_round") is not None:
        errors.extend(validate_round_reconciliation(review_dir, run, ledger))
    if split_contract:
        for item in findings:
            if not isinstance(item, dict):
                continue
            channel = item.get("report_channel", "substance")
            if channel not in {"substance", "writing"}:
                errors.append(f"finding {item.get('id')} has invalid report_channel {channel!r}")
            if channel == "writing" and (
                item.get("severity") not in {"minor", "info"} or item.get("essential") is True
            ):
                errors.append(
                    f"writing-channel finding {item.get('id')} must be minor/info and non-essential; "
                    "reclassify science-obscuring issues as substance"
                )
        for item in active:
            if item.get("data_limitation") != "inherent_but_claim_exceeds":
                continue
            quote_evidence = [
                evidence for evidence in item.get("evidence", [])
                if isinstance(evidence, dict)
                and evidence.get("type") == "quote"
                and isinstance(evidence.get("content"), str)
                and evidence.get("content", "").strip()
            ]
            if len(quote_evidence) < 2:
                errors.append(
                    f"v0.2+ inherent-data claim-scope finding {item.get('id')} requires separate quoted "
                    "evidence for the disclosure and the conflicting unhedged claim"
                )
    if current_contract:
        allowed_roles = {"potentially_dispositive", "posture_material", "revision_value", "polish"}
        allowed_repairs = {
            "within_current_design", "claim_narrowing", "additional_analysis", "new_evidence",
            "redesign", "unclear", "no_clear_fix",
        }
        for item in findings:
            if not isinstance(item, dict):
                continue
            if not isinstance(item.get("title"), str) or not item.get("title", "").strip():
                errors.append(f"current-contract finding {item.get('id')} requires a consequence-centered title")
            role = item.get("decision_role")
            if role not in allowed_roles:
                errors.append(f"current-contract finding {item.get('id')} has invalid decision_role {role!r}")
            repairability = item.get("repairability")
            if repairability not in allowed_repairs:
                errors.append(f"current-contract finding {item.get('id')} has invalid repairability {repairability!r}")
            channel = item.get("report_channel", "substance")
            if channel == "writing" and role not in {"revision_value", "polish"}:
                errors.append(f"writing finding {item.get('id')} cannot be decision-role {role}")
            if item.get("essential") is not (role == "potentially_dispositive"):
                errors.append(
                    f"current-contract finding {item.get('id')} essential must mirror potentially_dispositive decision role"
                )
            if item.get("severity") == "critical" and role != "potentially_dispositive":
                errors.append(
                    f"critical finding {item.get('id')} must be potentially_dispositive and essential before submission"
                )
            displayable_evidence = any(
                isinstance(evidence, dict)
                and (
                    (isinstance(evidence.get("content"), str) and bool(evidence.get("content", "").strip()))
                    or (
                        evidence.get("type") == "absence_scope"
                        and isinstance(evidence.get("scope_checked"), str)
                        and bool(evidence.get("scope_checked", "").strip())
                    )
                )
                for evidence in item.get("evidence", [])
            )
            if not displayable_evidence:
                errors.append(f"current-contract finding {item.get('id')} requires displayable evidence content")
    if v4:
        burdens = run.get("activated_burdens", [])
        burden_ids = [row.get("id") for row in burdens if isinstance(row, dict)] if isinstance(burdens, list) else []
        duplicate_burdens = sorted(value for value, count in Counter(burden_ids).items() if value and count > 1)
        if duplicate_burdens:
            errors.append("run.json has duplicate burden IDs: " + ", ".join(duplicate_burdens))
        if strict_v4_audits and isinstance(burdens, list):
            burden_by_id = {
                row.get("id"): row for row in burdens
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            }
            for burden_id, burden in burden_by_id.items():
                parent_id = burden.get("parent_id")
                if parent_id not in CANONICAL_BURDEN_PARENTS:
                    errors.append(
                        f"burden {burden_id} must name a stable conceptual parent_id"
                    )
                    continue
                if burden_id in CANONICAL_BURDEN_PARENTS and parent_id != burden_id:
                    errors.append(
                        f"parent burden {burden_id} must be self-parented"
                    )
        for item in findings:
            if not isinstance(item, dict):
                continue
            evidence_rows = [row for row in item.get("evidence", []) if isinstance(row, dict)]
            evidence_ids = {row.get("id") for row in evidence_rows if isinstance(row.get("id"), str)}
            display_id = item.get("display_evidence_id")
            related_ids = set(item.get("related_evidence_ids", [])) if isinstance(item.get("related_evidence_ids"), list) else set()
            if display_id not in evidence_ids:
                errors.append(f"finding {item.get('id')} display_evidence_id must reference its own evidence")
            unknown_related = sorted(related_ids - evidence_ids)
            if unknown_related:
                errors.append(f"finding {item.get('id')} has unknown related_evidence_ids: {', '.join(unknown_related)}")
            if display_id in related_ids:
                errors.append(f"finding {item.get('id')} display evidence must not be repeated as related evidence")
            counter = item.get("counterargument", {})
            if isinstance(counter, dict) and counter.get("result") == "not_applicable":
                if not (
                    item.get("report_channel") == "writing"
                    and item.get("severity") in {"minor", "info"}
                    and item.get("critique_basis") in {"reader_clarity", "formal_or_computational_error"}
                ):
                    errors.append(
                        f"finding {item.get('id')} may use counterargument not_applicable only for objective writing mechanics"
                    )
    if maximum_comments is not None and len(active) > maximum_comments:
        errors.append(f"detailed comments exceed run maximum: {len(active)} > {maximum_comments}")
    if isinstance(substance_maximum, int) and not isinstance(substance_maximum, bool):
        if len(substance_active) > substance_maximum:
            errors.append(
                "substantive Detailed Comments exceed their publication capacity: "
                f"{len(substance_active)} > {substance_maximum}; do not silently truncate"
            )
    if isinstance(writing_maximum, int) and not isinstance(writing_maximum, bool):
        if len(writing_active) > writing_maximum:
            errors.append(
                "Detailed Editing Comments exceed their publication capacity: "
                f"{len(writing_active)} > {writing_maximum}; do not silently truncate"
            )
    active_ranks = [item.get("importance_rank") for item in active]
    valid_active_ranks = [rank for rank in active_ranks if isinstance(rank, int) and not isinstance(rank, bool)]
    duplicate_ranks = sorted(rank for rank, count in Counter(valid_active_ranks).items() if count > 1)
    if duplicate_ranks:
        errors.append(f"duplicate importance ranks: {duplicate_ranks}")
    expected_ranks = list(range(1, len(active) + 1))
    if sorted(valid_active_ranks) != expected_ranks:
        errors.append(f"active importance ranks must be consecutive 1..{len(active)}")
    severity_counts = Counter(item.get("severity") for item in active)
    essential_count = sum(bool(item.get("essential")) for item in active)
    if essential_count > 3 and not current_contract:
        errors.append(f"essential finding cap exceeded: {essential_count} > 3")
    if current_contract:
        role_priority = {
            "potentially_dispositive": 0,
            "posture_material": 1,
            "revision_value": 2,
            "polish": 3,
        }
        ranked_active = sorted(active, key=lambda item: item.get("importance_rank", 10**9))
        severity_priority = {
            "critical": 0,
            "major": 1,
            "minor": 2,
            "info": 3,
        }
        severities = [severity_priority.get(item.get("severity"), 99) for item in ranked_active]
        if severities != sorted(severities):
            errors.append(
                "current importance order must be globally severity-first: "
                "critical, major, minor, then info"
            )
        for severity in severity_priority:
            same_severity = [
                role_priority.get(item.get("decision_role"), 99)
                for item in ranked_active
                if item.get("severity") == severity
            ]
            if same_severity != sorted(same_severity):
                errors.append(
                    "within each severity tier, current importance order must place "
                    "potentially dispositive findings before posture material, revision value, and polish"
                )
                break
    known_id_set = {item.get("id") for item in findings if isinstance(item, dict)}
    active_id_set = {item.get("id") for item in active}
    active_by_id = {
        item.get("id"): item
        for item in active
        if isinstance(item.get("id"), str)
    }
    severity_priority = {"critical": 0, "major": 1, "minor": 2, "info": 3}
    dependency_graph: dict[str, list[str]] = {}
    for item in active:
        finding_id = item.get("id")
        raw_dependencies = item.get("fix", {}).get("dependencies", [])
        dependencies = raw_dependencies if isinstance(raw_dependencies, list) else []
        dependency_graph[finding_id] = [value for value in dependencies if isinstance(value, str)]
        for dependency in dependency_graph[finding_id]:
            if current_contract and dependency == finding_id:
                errors.append(f"finding {finding_id} cannot depend on itself")
            elif current_contract and dependency not in known_id_set:
                errors.append(f"finding {finding_id} depends on unknown {dependency}")
            elif current_contract and dependency in active_by_id:
                dependency_severity = active_by_id[dependency].get("severity")
                if severity_priority.get(dependency_severity, 99) > severity_priority.get(item.get("severity"), 99):
                    errors.append(
                        f"finding {finding_id} depends on lower-severity {dependency}; "
                        "merge the shared root cause or align the severities so the revision plan remains severity-first"
                    )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit_dependency(finding_id: str) -> None:
        if finding_id in visited:
            return
        if current_contract and finding_id in visiting:
            errors.append(f"fix dependencies contain a cycle involving {finding_id}")
            return
        visiting.add(finding_id)
        for dependency in dependency_graph.get(finding_id, []):
            if dependency in active_id_set and dependency in dependency_graph:
                visit_dependency(dependency)
        visiting.remove(finding_id)
        visited.add(finding_id)

    if current_contract:
        for finding_id in dependency_graph:
            visit_dependency(finding_id)
    expected_counts = {severity: severity_counts.get(severity, 0) for severity in SEVERITIES}
    expected_counts["essential"] = essential_count
    if run.get("counts") != expected_counts:
        errors.append(f"run.json.counts mismatch: expected {expected_counts}, got {run.get('counts')}")

    report_path = review_dir / "report.md"
    writing_report_path = review_dir / "editing-comments.md"
    plan_path = review_dir / "fix-plan.md"
    synthesis_path = review_dir / "synthesis.json"
    required_output_paths = [report_path, plan_path]
    if split_contract and (run.get("mode") == "full" or writing_active):
        required_output_paths.append(writing_report_path)
    if current_contract:
        required_output_paths.append(synthesis_path)
    for path in required_output_paths:
        if not path.exists():
            errors.append(f"missing required file: {path}")
    if strict_burden_coverage and run.get("mode") == "full":
        for path in (report_path, writing_report_path):
            if path.exists() and ASSESSMENT_BOUNDARY_HEADING.search(
                path.read_text(encoding="utf-8")
            ):
                errors.append(f"{path.name} must not contain an Assessment Boundary section")
        if report_path.exists() and JOURNAL_FIT_HEADING.search(
            report_path.read_text(encoding="utf-8")
        ):
            errors.append("report.md must not contain a journal-fit section")
    synthesis: dict[str, Any] | None = None
    if current_contract and synthesis_path.exists():
        loaded_synthesis = load_json(synthesis_path, errors)
        if isinstance(loaded_synthesis, dict):
            synthesis = loaded_synthesis
            validate_schema(synthesis, "synthesis.schema.json", "synthesis.json", errors)
            if synthesis.get("review_id") != run.get("review_id"):
                errors.append("synthesis review_id differs from run.json")
            target = run.get("target") if isinstance(run.get("target"), dict) else {}
            venue = target.get("venue")
            venue_unspecified = not isinstance(venue, str) or not venue.strip()
            tier_unspecified = target.get("tier") in {None, "unspecified"}
            if (
                strict_v4_audits
                and venue_unspecified
                and tier_unspecified
                and synthesis.get("review_posture") != "not_assessed"
            ):
                errors.append(
                    "synthesis review_posture must be not_assessed when both target venue and tier are unspecified"
                )
            active_by_id = {item.get("id"): item for item in active}
            raw_concerns = synthesis.get("principal_concerns")
            concern_rows = [row for row in raw_concerns if isinstance(row, dict)] if isinstance(raw_concerns, list) else []
            concern_ids = [row.get("id") for row in concern_rows]
            if concern_ids != [f"PC-{index:02d}" for index in range(1, len(concern_ids) + 1)]:
                errors.append("principal concern IDs must be consecutive PC-01..PC-N")
            mapped_ids: list[str] = []
            for row in concern_rows:
                raw_finding_ids = row.get("finding_ids")
                finding_ids = raw_finding_ids if isinstance(raw_finding_ids, list) else []
                linked_findings: list[dict[str, Any]] = []
                for finding_id in finding_ids:
                    finding = active_by_id.get(finding_id)
                    if finding is None:
                        errors.append(f"principal concern {row.get('id')} references unknown or inactive {finding_id}")
                        continue
                    if strict_burden_coverage and finding.get("verification") != "passed":
                        errors.append(
                            f"principal concern {row.get('id')} references verification-failed finding {finding_id}"
                        )
                    if finding.get("report_channel", "substance") != "substance":
                        errors.append(f"principal concern {row.get('id')} references writing finding {finding_id}")
                    linked_findings.append(finding)
                    mapped_ids.append(finding_id)
                if linked_findings:
                    expected_effect = (
                        "potentially_dispositive"
                        if any(finding.get("decision_role") == "potentially_dispositive" for finding in linked_findings)
                        else "posture_material"
                    )
                    if row.get("decision_effect") != expected_effect:
                        errors.append(
                            f"principal concern {row.get('id')} decision_effect must be {expected_effect}"
                        )
                    linked_repairs = {finding.get("repairability") for finding in linked_findings}
                    if row.get("repairability") not in linked_repairs:
                        errors.append(
                            f"principal concern {row.get('id')} repairability must match at least one linked finding"
                        )
            duplicated_mappings = sorted(
                finding_id for finding_id, count in Counter(mapped_ids).items() if count > 1
            )
            if duplicated_mappings:
                errors.append(
                    "principal concerns map findings more than once: " + ", ".join(duplicated_mappings)
                )
            dispositive_ids = {
                item.get("id") for item in substance_active
                if item.get("decision_role") == "potentially_dispositive"
            }
            if not dispositive_ids.issubset(set(mapped_ids)):
                errors.append(
                    "principal concerns omit potentially dispositive findings: "
                    + ", ".join(sorted(dispositive_ids - set(mapped_ids)))
                )
            raw_other_major_ids = synthesis.get("other_major_finding_ids")
            other_major_ids = set(raw_other_major_ids) if isinstance(raw_other_major_ids, list) else set()
            expected_other_major = {
                item.get("id") for item in substance_active
                if item.get("decision_role") == "posture_material" and item.get("id") not in set(mapped_ids)
            }
            if other_major_ids != expected_other_major:
                missing = sorted(expected_other_major - other_major_ids)
                extra = sorted(other_major_ids - expected_other_major)
                if missing:
                    errors.append("synthesis omits other major findings: " + ", ".join(missing))
                if extra:
                    errors.append("synthesis lists invalid other major findings: " + ", ".join(extra))
            if synthesis.get("writing_finding_count") != len(writing_active):
                errors.append(
                    f"synthesis writing_finding_count mismatch: expected {len(writing_active)}, "
                    f"got {synthesis.get('writing_finding_count')}"
                )
            if v4:
                expected_support: dict[tuple[str, str | None, int | None], str] = {
                    ("overall_assessment", None, None): str(synthesis.get("overall_assessment", "")),
                    ("posture_rationale", None, None): str(synthesis.get("posture_rationale", "")),
                    ("convincingness", None, None): str(synthesis.get("convincingness", "")),
                }
                for index, statement in enumerate(synthesis.get("strengths", [])):
                    expected_support[("strength", None, index)] = str(statement)
                for index, statement in enumerate(synthesis.get("upgrade_conditions", [])):
                    expected_support[("upgrade_condition", None, index)] = str(statement)
                for concern in concern_rows:
                    expected_support[("principal_concern_rationale", concern.get("id"), None)] = str(concern.get("rationale", ""))
                    expected_support[("principal_concern_upgrade", concern.get("id"), None)] = str(concern.get("upgrade_condition", ""))
                known_finding_ids = {
                    row.get("id") for row in findings
                    if isinstance(row, dict) and isinstance(row.get("id"), str)
                }
                support_context = (
                    load_synthesis_support_context(review_dir, findings, errors)
                    if strict_burden_coverage else None
                )
                if isinstance(support_context, dict):
                    known_claim_ids = set(support_context["claim_by_id"])
                else:
                    known_claim_ids = {
                        claim_id for row in findings if isinstance(row, dict)
                        for claim_id in (
                            row.get("claim_ids") if isinstance(row.get("claim_ids"), list) else []
                        ) if isinstance(claim_id, str)
                    }
                evidence_owner_by_id = {
                    evidence.get("id"): row.get("id")
                    for row in findings if isinstance(row, dict)
                    for evidence in (
                        row.get("evidence") if isinstance(row.get("evidence"), list) else []
                    )
                    if isinstance(evidence, dict)
                    and isinstance(evidence.get("id"), str)
                    and isinstance(row.get("id"), str)
                }
                known_evidence_ids = set(evidence_owner_by_id)
                concern_by_id = {
                    row.get("id"): row
                    for row in concern_rows
                    if isinstance(row.get("id"), str)
                }
                seen_support: set[tuple[str, str | None, int | None]] = set()
                for mapping in synthesis.get("support_mappings", []):
                    if not isinstance(mapping, dict):
                        continue
                    key = (mapping.get("target_type"), mapping.get("target_id"), mapping.get("target_index"))
                    if key in seen_support:
                        errors.append(f"synthesis has duplicate support mapping for {key}")
                    seen_support.add(key)
                    expected_statement = expected_support.get(key)
                    if expected_statement is None:
                        errors.append(f"synthesis support mapping has unknown target {key}")
                    elif mapping.get("statement") != expected_statement:
                        errors.append(f"synthesis support mapping statement differs from target {key}")
                    raw_claim_ids = mapping.get("claim_ids")
                    raw_finding_ids = mapping.get("finding_ids")
                    raw_evidence_ids = mapping.get("evidence_ids")
                    mapping_claim_ids = {
                        value for value in raw_claim_ids if isinstance(value, str)
                    } if isinstance(raw_claim_ids, list) else set()
                    mapping_finding_ids = {
                        value for value in raw_finding_ids if isinstance(value, str)
                    } if isinstance(raw_finding_ids, list) else set()
                    mapping_evidence_ids = {
                        value for value in raw_evidence_ids if isinstance(value, str)
                    } if isinstance(raw_evidence_ids, list) else set()
                    unknown_claims = sorted(mapping_claim_ids - known_claim_ids)
                    unknown_findings = sorted(mapping_finding_ids - known_finding_ids)
                    unknown_evidence = sorted(mapping_evidence_ids - known_evidence_ids)
                    if unknown_claims:
                        errors.append("synthesis support mapping references unknown claims: " + ", ".join(unknown_claims))
                    if unknown_findings:
                        errors.append("synthesis support mapping references unknown findings: " + ", ".join(unknown_findings))
                    if unknown_evidence:
                        errors.append("synthesis support mapping references unknown evidence: " + ", ".join(unknown_evidence))
                    if not isinstance(support_context, dict):
                        continue

                    eligible_findings = support_context["eligible_finding_by_id"]
                    ineligible_findings = sorted(
                        (mapping_finding_ids & known_finding_ids) - set(eligible_findings)
                    )
                    if ineligible_findings:
                        errors.append(
                            "synthesis support mapping cannot use inactive or verification-failed findings: "
                            + ", ".join(ineligible_findings)
                        )
                    eligible_evidence = support_context["eligible_evidence_by_id"]
                    ineligible_evidence = sorted(
                        (mapping_evidence_ids & known_evidence_ids) - set(eligible_evidence)
                    )
                    if ineligible_evidence:
                        errors.append(
                            "synthesis support mapping cannot use inactive or verification-failed evidence: "
                            + ", ".join(ineligible_evidence)
                        )
                    unowned_evidence = sorted(
                        evidence_id for evidence_id in mapping_evidence_ids & set(eligible_evidence)
                        if support_context["eligible_evidence_owner"].get(evidence_id)
                        not in mapping_finding_ids
                    )
                    if unowned_evidence:
                        errors.append(
                            "synthesis support mapping evidence lacks its reciprocal finding owner: "
                            + ", ".join(unowned_evidence)
                        )

                    supported_claim_ids = {
                        claim_id for claim_id in mapping_claim_ids & known_claim_ids
                        if claim_has_canonical_support(
                            support_context["claim_by_id"][claim_id], support_context
                        )
                    }
                    unsupported_claim_ids = sorted(
                        (mapping_claim_ids & known_claim_ids) - supported_claim_ids
                    )
                    if unsupported_claim_ids:
                        errors.append(
                            "synthesis support mapping claims lack precise canonical anchors: "
                            + ", ".join(unsupported_claim_ids)
                        )
                    supported_finding_ids = {
                        finding_id for finding_id in mapping_finding_ids & set(eligible_findings)
                        if any(
                            isinstance(evidence, dict)
                            and evidence_has_canonical_support(evidence, support_context)
                            for evidence in (
                                eligible_findings[finding_id].get("evidence")
                                if isinstance(eligible_findings[finding_id].get("evidence"), list)
                                else []
                            )
                        )
                    }
                    unsupported_finding_ids = sorted(
                        (mapping_finding_ids & set(eligible_findings)) - supported_finding_ids
                    )
                    if unsupported_finding_ids:
                        errors.append(
                            "synthesis support mapping findings lack canonical source support: "
                            + ", ".join(unsupported_finding_ids)
                        )
                    supported_evidence_ids = {
                        evidence_id for evidence_id in mapping_evidence_ids & set(eligible_evidence)
                        if evidence_has_canonical_support(
                            eligible_evidence[evidence_id], support_context
                        )
                    }
                    unsupported_evidence_ids = sorted(
                        (mapping_evidence_ids & set(eligible_evidence)) - supported_evidence_ids
                    )
                    if unsupported_evidence_ids:
                        errors.append(
                            "synthesis support mapping evidence lacks canonical source support: "
                            + ", ".join(unsupported_evidence_ids)
                        )

                    if mapping.get("target_type") == "strength":
                        if mapping_finding_ids or mapping_evidence_ids:
                            errors.append(
                                "clean synthesis strengths must use canonical claim support, not adverse finding evidence"
                            )
                        if not supported_claim_ids:
                            errors.append(
                                "clean synthesis strength requires at least one precisely anchored canonical claim"
                            )
                    elif not (
                        supported_claim_ids
                        or supported_finding_ids
                        or supported_evidence_ids
                    ):
                        errors.append(
                            f"synthesis support mapping for {key} lacks eligible canonical support"
                        )

                    if mapping.get("target_type") in {
                        "principal_concern_rationale", "principal_concern_upgrade"
                    }:
                        concern = concern_by_id.get(mapping.get("target_id"))
                        concern_finding_ids = {
                            value for value in concern.get("finding_ids", [])
                            if isinstance(value, str)
                        } if isinstance(concern, dict) and isinstance(
                            concern.get("finding_ids"), list
                        ) else set()
                        if mapping_finding_ids != concern_finding_ids:
                            errors.append(
                                f"synthesis support mapping for {key} must use exactly its principal concern findings"
                            )
                missing_support = sorted(set(expected_support) - seen_support, key=str)
                if missing_support:
                    errors.append("synthesis statements missing structured support: " + ", ".join(map(str, missing_support)))
    if report_path.exists() and not split_contract:
        report = report_path.read_text(encoding="utf-8")
        if run.get("mode") == "full":
            for heading in (
                "## Is the argument convincing to a reader?",
                "## Writing, clarity, consistency, and typographical review",
                "## Reference accuracy and citation support",
            ):
                heading_match = re.search(rf"^{re.escape(heading)}\s*$", report, re.MULTILINE)
                if not heading_match:
                    errors.append(f"report.md is missing '{heading}'")
                    continue
                following = report[heading_match.end():]
                next_heading = re.search(r"^## ", following, re.MULTILINE)
                content = following[:next_heading.start()] if next_heading else following
                if not content.strip():
                    errors.append(f"report.md section '{heading}' must be non-empty")
        detail_match = re.search(r"^## Detailed Comments \((\d+)\)\s*$", report, re.MULTILINE)
        if not detail_match:
            errors.append("report.md is missing '## Detailed Comments (N)'")
        else:
            detail_start = detail_match.end()
            next_h2 = re.search(r"^## ", report[detail_start:], re.MULTILINE)
            detail_block = report[detail_start : detail_start + next_h2.start()] if next_h2 else report[detail_start:]
            comment_count = len(re.findall(r"^### \d+\. ", detail_block, re.MULTILINE))
            declared_count = int(detail_match.group(1))
            if declared_count != comment_count:
                errors.append(
                    f"Detailed Comments count mismatch: heading says {declared_count}, found {comment_count}"
                )
            if comment_count != len(active):
                errors.append(
                    f"Detailed Comments must contain every active finding exactly once: found {comment_count}, expected {len(active)}"
                )
            blocks = re.split(r"(?=^### \d+\. )", detail_block, flags=re.MULTILINE)
            blocks = [block for block in blocks if re.match(r"^### \d+\. ", block)]
            visible_numbers = [int(value) for value in re.findall(r"^### (\d+)\. ", detail_block, re.MULTILINE)]
            if visible_numbers != list(range(1, comment_count + 1)):
                errors.append("Detailed Comments visible numbering must be consecutive 1..N")
            block_quotes: list[str] = []
            feedback_texts: list[str] = []
            for block_index, block in enumerate(blocks, start=1):
                if len(re.findall(r"^\*\*Status\*\*: \[Pending\]\s*$", block, re.MULTILINE)) != 1:
                    errors.append(f"detailed comment {block_index} requires exactly one '**Status**: [Pending]' field")
                if len(re.findall(r"^\*\*Quote\*\*:\s*$", block, re.MULTILINE)) != 1:
                    errors.append(f"detailed comment {block_index} requires exactly one Quote field")
                quote_match = re.search(
                    r"^\*\*Quote\*\*:\s*\n(?P<quote>(?:^>.*(?:\n|$))+)", block, re.MULTILINE
                )
                quote_text = "" if not quote_match else re.sub(
                    r"^>\s?", "", quote_match.group("quote"), flags=re.MULTILINE
                ).strip()
                if not quote_text:
                    errors.append(f"detailed comment {block_index} requires a non-empty block quote")
                block_quotes.append(quote_text)
                feedback_match = re.search(r"^\*\*Feedback\*\*:\s*(?P<feedback>[\s\S]+?)\s*\Z", block, re.MULTILINE)
                feedback_text = "" if not feedback_match else feedback_match.group("feedback").strip()
                if len(re.findall(r"^\*\*Feedback\*\*:", block, re.MULTILINE)) != 1 or not feedback_text:
                    errors.append(f"detailed comment {block_index} requires exactly one non-empty Feedback field")
                feedback_texts.append(feedback_text)
            detail_ids = re.findall(r"<!-- finding_id: ([A-Z][A-Z0-9_-]*-[0-9]{2,}) -->", detail_block)
            if len(detail_ids) != comment_count:
                errors.append("each detailed comment requires exactly one hidden finding_id")
            expected_order = [
                item.get("id")
                for item in sorted(active, key=lambda item: item.get("importance_rank", 10**9))
            ]
            if detail_ids != expected_order:
                errors.append("Detailed Comments finding IDs must follow importance_rank order")
            findings_by_id = {item.get("id"): item for item in active}
            prohibited_feedback_phrases = (
                "As written,",
                "The strongest author-side defense is that",
                "The checked manuscript supports that defense only to this extent",
                "A proportionate repair is to",
                "leading-field verification requires",
                "the authors fail to",
                "the authors ignore",
                "There seems to be an issue",
                "The document would benefit from",
                "A careful reader cannot tell whether the stated claim is supported at the precision and scope presented.",
                "A careful reader may misread the object, unit, comparison, or evidentiary strength at this location.",
            )
            malformed_acronyms = ("vAR", "iRF", "hPI", "sVAR", "fOMC")
            for block_index, (finding_id, quote_text, feedback_text) in enumerate(
                zip(detail_ids, block_quotes, feedback_texts), start=1
            ):
                finding = findings_by_id.get(finding_id, {})
                evidence_texts = [
                    evidence.get("content")
                    for evidence in finding.get("evidence", [])
                    if isinstance(evidence, dict) and isinstance(evidence.get("content"), str)
                ]
                normalized_quote = normalize_quote(quote_text)
                if evidence_texts and not any(
                    normalized_quote in normalize_quote(evidence)
                    for evidence in evidence_texts
                ):
                    errors.append(f"detailed comment {block_index} quote does not match ledger evidence for {finding_id}")
                for phrase in prohibited_feedback_phrases:
                    if phrase.lower() in feedback_text.lower():
                        errors.append(f"detailed comment {block_index} uses prohibited boilerplate: {phrase}")
                for acronym in malformed_acronyms:
                    if acronym in feedback_text:
                        errors.append(f"detailed comment {block_index} contains malformed acronym {acronym}")
            sentence_owners: dict[str, set[str]] = {}
            major_label_signatures: list[tuple[str, ...]] = []
            for finding_id, feedback_text in zip(detail_ids, feedback_texts):
                for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\*\*[^*]+\*\*", "", feedback_text)):
                    normalized_sentence = " ".join(sentence.lower().split()).strip()
                    if len(normalized_sentence.split()) >= 10:
                        sentence_owners.setdefault(normalized_sentence, set()).add(finding_id)
                if findings_by_id.get(finding_id, {}).get("severity") in {"critical", "major"}:
                    labels = tuple(re.findall(r"\*\*([^*]+?)\.\*\*", feedback_text))
                    if labels:
                        major_label_signatures.append(labels)
            repeated_sentences = [
                (sentence, owners) for sentence, owners in sentence_owners.items() if len(owners) >= 3
            ]
            for sentence, owners in repeated_sentences:
                errors.append(
                    "detailed comments repeat a nontechnical sentence across "
                    f"{len(owners)} findings ({', '.join(sorted(owners))}): {sentence}"
                )
            if len(major_label_signatures) >= 6:
                signature_counts = Counter(major_label_signatures)
                signature, count = signature_counts.most_common(1)[0]
                if count > len(major_label_signatures) / 2:
                    errors.append(
                        "more than half of critical/major comments use the same label sequence: "
                        + " / ".join(signature)
                    )
        report_id_tokens = set(re.findall(r"\b[A-Z][A-Z0-9_-]*-[0-9]{2,}\b", report))
        for item in active:
            if item.get("id") not in report_id_tokens:
                errors.append(f"active finding {item.get('id')} is not referenced in report.md")
    if report_path.exists() and v2:
        report = report_path.read_text(encoding="utf-8")
        if run.get("mode") == "full":
            check_required_sections(
                report,
                "report.md",
                ("## Is the argument convincing to a reader?",),
                errors,
            )
        for heading in (
            "## Writing, clarity, consistency, and typographical review",
            "## Reference accuracy and citation support",
            "## Journal fit and submission strategy",
        ):
            if re.search(rf"^{re.escape(heading)}\s*$", report, re.MULTILINE):
                errors.append(
                    f"{heading} belongs in editing-comments.md "
                    "(report.md is the substance-only referee report)"
                )
        report_ids = validate_comment_section(
            report, "report.md", "Detailed Comments", substance_active, errors
        )
        report_tokens = set(re.findall(r"\b[A-Z][A-Z0-9_-]*-[0-9]{2,}\b", report))
        for item in substance_active:
            if item.get("id") not in report_tokens:
                errors.append(f"active finding {item.get('id')} is not referenced in report.md")
        for item in writing_active:
            if item.get("id") in report_ids:
                errors.append(f"writing-channel finding {item.get('id')} must not appear in report.md")

    if report_path.exists() and current_contract:
        report = report_path.read_text(encoding="utf-8")
        required_headings = (
            "## Overall assessment",
            "## Recommendation and main grounds",
            "## Issues that could prevent publication",
            "## Other major issues",
            "## Is the argument convincing?",
        )
        check_required_sections(report, "report.md", required_headings, errors)
        positions = [report.find(heading) for heading in required_headings]
        if all(position >= 0 for position in positions) and positions != sorted(positions):
            errors.append("v0.3 referee-report synthesis headings are out of order")
        for heading in (
            "## Writing, clarity, consistency, and typographical review",
            "## Reference accuracy and citation support",
            "## Journal fit and submission strategy",
        ):
            if re.search(rf"^{re.escape(heading)}\s*$", report, re.MULTILINE):
                errors.append(
                    f"{heading} belongs in editing-comments.md "
                    "(report.md is the substance-only referee report)"
                )
        if synthesis is not None:
            posture_labels = {
                "reject": "Reject",
                "weak_r_and_r": "Weak R&R",
                "strong_r_and_r": "Strong R&R",
                "accept": "Accept",
                "not_assessed": "Not assessed",
            }
            expected_posture = posture_labels.get(synthesis.get("review_posture"))
            posture_match = re.search(
                r"^\*\*(?:Recommendation|Review posture)\*\*:\s*(.+?)\s*$",
                report,
                re.MULTILINE,
            )
            if not posture_match or posture_match.group(1).strip() != expected_posture:
                errors.append(
                    f"report review posture must match synthesis.json: {expected_posture!r}"
                )
            concern_section = re.search(
                r"^## Issues that could prevent publication\s*$([\s\S]*?)(?=^## )",
                report,
                re.MULTILINE,
            )
            concern_block = concern_section.group(1) if concern_section else ""
            report_concern_ids = re.findall(r"<!-- principal_concern_id: (PC-[0-9]{2,}) -->", concern_block)
            raw_concerns = synthesis.get("principal_concerns")
            concern_rows = [row for row in raw_concerns if isinstance(row, dict)] if isinstance(raw_concerns, list) else []
            expected_concern_ids = [row.get("id") for row in concern_rows]
            if report_concern_ids != expected_concern_ids:
                errors.append("report principal concerns must match synthesis.json order exactly")
            for row in concern_rows:
                if row.get("title") not in concern_block:
                    errors.append(f"report omits principal concern title {row.get('title')!r}")
                raw_finding_ids = row.get("finding_ids")
                for finding_id in raw_finding_ids if isinstance(raw_finding_ids, list) else []:
                    if finding_id not in concern_block:
                        errors.append(
                            f"report principal concern {row.get('id')} omits linked finding {finding_id}"
                        )
            other_section = re.search(
                r"^## Other major issues\s*$([\s\S]*?)(?=^## )",
                report,
                re.MULTILINE,
            )
            other_block = other_section.group(1) if other_section else ""
            raw_other_major_ids = synthesis.get("other_major_finding_ids")
            for finding_id in raw_other_major_ids if isinstance(raw_other_major_ids, list) else []:
                if finding_id not in other_block:
                    errors.append(f"report other-major synthesis omits {finding_id}")
        report_ids = validate_comment_section_v3(
            report, "report.md", "Detailed Comments", substance_active, errors
        )
        report_tokens = set(re.findall(r"\b[A-Z][A-Z0-9_-]*-[0-9]{2,}\b", report))
        for item in substance_active:
            if item.get("id") not in report_tokens:
                errors.append(f"active finding {item.get('id')} is not referenced in report.md")
        for item in writing_active:
            if item.get("id") in report_ids:
                errors.append(f"writing-channel finding {item.get('id')} must not appear in report.md")

    if writing_report_path.exists() and v2:
        writing_report = writing_report_path.read_text(encoding="utf-8")
        if run.get("mode") == "full":
            check_required_sections(
                writing_report,
                "editing-comments.md",
                (
                    "## Writing quality summary",
                    "## Grammar, typos, and mechanics",
                    "## Language consistency",
                    "## Style and writing improvement suggestions",
                    "## Reference accuracy and citation support",
                ),
                errors,
            )
        writing_ids = validate_comment_section(
            writing_report,
            "editing-comments.md",
            "Detailed Editing Comments",
            writing_active,
            errors,
        )
        writing_tokens = set(re.findall(r"\b[A-Z][A-Z0-9_-]*-[0-9]{2,}\b", writing_report))
        for item in writing_active:
            if item.get("id") not in writing_tokens:
                errors.append(f"active finding {item.get('id')} is not referenced in editing-comments.md")
        for item in substance_active:
            if item.get("id") in writing_ids:
                errors.append(f"substance-channel finding {item.get('id')} must not appear in editing-comments.md")
    if writing_report_path.exists() and current_contract:
        writing_report = writing_report_path.read_text(encoding="utf-8")
        if run.get("mode") == "full":
            current_sections = (
                "## Editing assessment",
                "## Highest-return editing revisions",
                "## Section-by-section reader audit",
                "## Terminology, definitions, and notation",
                "## Tables and figures as writing",
                "## Mechanics and copyedit inventory",
                "## Style and writing improvements",
            )
            if strict_burden_coverage:
                expected_sections = current_sections + (
                    ("## Journal fit and submission strategy",) if journal_fit_requested else ()
                )
                legacy_writing_headings = (
                    "## Writing quality summary",
                    "## Grammar, typos, and mechanics",
                    "## Language consistency",
                    "## Style and writing improvement suggestions",
                    "## References and citation integrity",
                    "## Reference accuracy and citation support",
                )
                if any(re.search(
                    rf"^{re.escape(heading)}\s*$",
                    writing_report,
                    re.MULTILINE,
                ) for heading in legacy_writing_headings):
                    errors.append("editing-comments.md mixes legacy and current editing-comments headings")
                check_alternative_section_sets(
                    writing_report,
                    "editing-comments.md",
                    (expected_sections,),
                    errors,
                )
                journal_sections = JOURNAL_FIT_HEADING.findall(writing_report)
                if bool(journal_sections) != journal_fit_requested or len(journal_sections) > 1:
                    expected = "present" if journal_fit_requested else "absent"
                    errors.append(
                        "editing-comments journal-fit section must be " + expected
                        + " according to run.json.requested_addons"
                    )
            else:
                check_alternative_section_sets(
                    writing_report,
                    "editing-comments.md",
                    (
                        current_sections,
                        current_sections[:-1],
                        current_sections[:-1] + ("## References and citation integrity",),
                        (
                            "## Writing quality summary",
                            "## Grammar, typos, and mechanics",
                            "## Language consistency",
                            "## Style and writing improvement suggestions",
                            "## Reference accuracy and citation support",
                        ),
                    ),
                    errors,
                )
        writing_ids = validate_comment_section_v3(
            writing_report,
            "editing-comments.md",
            "Detailed Editing Comments",
            writing_active,
            errors,
        )
        writing_tokens = set(re.findall(r"\b[A-Z][A-Z0-9_-]*-[0-9]{2,}\b", writing_report))
        for item in writing_active:
            if item.get("id") not in writing_tokens:
                errors.append(f"active finding {item.get('id')} is not referenced in editing-comments.md")
        for item in substance_active:
            if item.get("id") in writing_ids:
                errors.append(f"substance-channel finding {item.get('id')} must not appear in editing-comments.md")
    if plan_path.exists():
        plan = plan_path.read_text(encoding="utf-8")
        plan_ids = re.findall(
            r"^<!-- finding_id: ([A-Z][A-Z0-9_-]*-[0-9]{2,}) -->\s*$",
            plan,
            re.MULTILINE,
        )
        plan_numbers = [
            int(value)
            for value in re.findall(r"^### Comment ([0-9]+):\s+", plan, re.MULTILINE)
        ]
        if plan_numbers != list(range(1, len(plan_numbers) + 1)):
            errors.append("fix-plan.md comment headings must be consecutively numbered from 1")
        if len(plan_numbers) != len(plan_ids):
            errors.append("each fix-plan.md comment heading requires exactly one hidden finding_id")
        plan_id_counts = Counter(plan_ids)
        active_ids = {item.get("id") for item in active}
        unknown_plan_ids = sorted(set(plan_ids) - active_ids)
        if unknown_plan_ids:
            errors.append("fix-plan.md contains unknown task headings: " + ", ".join(unknown_plan_ids))
        for item in active:
            count = plan_id_counts[item.get("id")]
            if count == 0:
                errors.append(f"active finding {item.get('id')} is not referenced in fix-plan.md")
            elif count != 1:
                errors.append(f"active finding {item.get('id')} must appear exactly once in fix-plan.md")
        if split_contract:
            closure_lines = [
                " ".join(value.lower().split())
                for value in re.findall(
                    r"(?:\*\*(?:Done when|Completion evidence):\*\*|Completion evidence:)\s*([^\n]+)",
                    plan,
                )
            ]
            repeated_closures = [
                text for text, count in Counter(closure_lines).items() if text and count > 1
            ]
            if repeated_closures:
                errors.append("fix-plan.md repeats a generic completion condition across items")

    if run.get("status") == "complete":
        if run.get("verification_passed") is not True:
            errors.append("complete run requires verification_passed=true")
        if split_contract and not isinstance(run.get("telemetry"), dict):
            errors.append("complete v0.2+ run requires run.json.telemetry")
        if len(active) < minimum_target:
            coverage_probe = load_json(review_dir / "evidence/coverage.json", errors)
            sweep = coverage_probe.get("second_sweep", {}) if isinstance(coverage_probe, dict) else {}
            if not (
                isinstance(sweep, dict)
                and sweep.get("completed") is True
                and isinstance(sweep.get("shortfall_explanation"), str)
                and sweep.get("shortfall_explanation", "").strip()
            ):
                errors.append(
                    f"complete run falls below the requested comment target without a documented second-sweep shortfall: {len(active)} < {minimum_target}"
                )
        if run.get("mode") == "full" and comment_policy.get("exhaustive") is not True:
            errors.append("complete full run requires comment_policy.exhaustive=true")
        if stage_status and any(stage_status.get(stage) not in {"passed", "bounded", "not_applicable"} for stage in required_stages):
            errors.append("complete run contains an unfinished or failed stage")
        if run.get("mode") == "full" and stage_status:
            for stage in {"audit", "counterargument", "synthesis", "verification", "delivery"}:
                if stage_status.get(stage) != "passed":
                    errors.append(f"complete full run requires stage '{stage}' to be passed")
        for item in active:
            if item.get("verification") != "passed":
                errors.append(f"complete run requires passed verification for {item.get('id')}")
            if item.get("support_state") not in {"supported", "partially_supported", "in_conflict"}:
                errors.append(
                    f"complete run cannot report unresolved support state {item.get('support_state')!r} for {item.get('id')}"
                )
        required_artifacts = [
            "evidence/reconstruction.md",
            "evidence/sources.md",
            "evidence/verification.md",
        ]
        if run.get("prior_round") is not None:
            required_artifacts.extend([
                "evidence/round-reconciliation.json",
                "evidence/round-reconciliation.md",
            ])
        if run.get("mode") == "full":
            required_artifacts.append("evidence/reader-claim-audit.md")
            required_artifacts.append("evidence/claims.json")
            required_artifacts.append("evidence/figures.md")
            required_artifacts.append("evidence/figures.json")
            required_artifacts.append("evidence/tables.md")
            required_artifacts.append("evidence/tables.json")
            required_artifacts.append("evidence/analytical-audit.md")
            required_artifacts.append("evidence/analytical-audit.json")
            required_artifacts.append("evidence/writing.md")
            required_artifacts.append("evidence/writing.json")
            required_artifacts.append("evidence/coverage.md")
            required_artifacts.append("evidence/coverage.json")
        for relative in required_artifacts:
            artifact_path = review_dir / relative
            if not artifact_path.exists():
                errors.append(f"complete run missing audit artifact: {relative}")
            elif artifact_path.suffix == ".md" and not artifact_path.read_text(encoding="utf-8").strip():
                errors.append(f"complete run audit artifact is empty: {relative}")

        if run.get("mode") == "full":
            boundary = run.get("assessment_boundary", {})
            sources = boundary.get("sources", []) if isinstance(boundary, dict) else []
            if not sources:
                errors.append("complete full run requires at least one recorded manuscript source")
            elif not (v4 and strict_burden_coverage) and not any(
                isinstance(source, dict) and source.get("status") in {"fully_read", "partially_read"}
                for source in sources
            ):
                errors.append("complete full run requires a manuscript source marked fully_read or partially_read")
            if v4 and strict_burden_coverage:
                source_manifest_for_boundary = load_json(
                    review_dir / "evidence/source-manifest.json", errors
                )
                if isinstance(source_manifest_for_boundary, dict):
                    manifest_sources = {
                        row.get("id"): row
                        for row in source_manifest_for_boundary.get("sources", [])
                        if isinstance(row, dict)
                        and row.get("role") in INTERNAL_SOURCE_ROLES
                        and isinstance(row.get("id"), str)
                    }
                    boundary_sources = {
                        row.get("source_id"): row
                        for row in sources
                        if isinstance(row, dict) and isinstance(row.get("source_id"), str)
                    }
                    boundary_ids = [
                        row.get("source_id") for row in sources
                        if isinstance(row, dict) and isinstance(row.get("source_id"), str)
                    ]
                    if len(boundary_ids) != len(sources):
                        errors.append(
                            "current assessment boundary sources require canonical source_id values"
                        )
                    duplicate_boundary_ids = sorted(
                        source_id for source_id, count in Counter(boundary_ids).items()
                        if count > 1
                    )
                    if duplicate_boundary_ids:
                        errors.append(
                            "assessment boundary has duplicate source IDs: "
                            + ", ".join(duplicate_boundary_ids)
                        )
                    missing_boundary_sources = sorted(
                        set(manifest_sources) - set(boundary_sources)
                    )
                    unknown_boundary_sources = sorted(
                        set(boundary_sources) - set(manifest_sources)
                    )
                    if missing_boundary_sources:
                        errors.append(
                            "assessment boundary omits in-scope manifest sources: "
                            + ", ".join(missing_boundary_sources)
                        )
                    if unknown_boundary_sources:
                        errors.append(
                            "assessment boundary references unknown in-scope sources: "
                            + ", ".join(unknown_boundary_sources)
                        )
                    read_manuscript_ids = {
                        source_id
                        for source_id, boundary_source in boundary_sources.items()
                        if manifest_sources.get(source_id, {}).get("role") == "manuscript"
                        and boundary_source.get("status") in {"fully_read", "partially_read"}
                    }
                    if not read_manuscript_ids:
                        errors.append(
                            "complete full run requires a manuscript source marked fully_read or partially_read"
                        )
                    for source_id, boundary_source in boundary_sources.items():
                        manifest_source = manifest_sources.get(source_id)
                        if not isinstance(manifest_source, dict):
                            continue
                        if boundary_source.get("path") != manifest_source.get("path"):
                            errors.append(
                                f"assessment boundary source {source_id} path differs from source manifest"
                            )
                        if boundary_source.get("sha256") != manifest_source.get("sha256"):
                            errors.append(
                                f"assessment boundary source {source_id} hash differs from source manifest"
                            )

        if v4:
            if run.get("mode") == "full":
                burden_ids = {
                    row.get("id") for row in run.get("activated_burdens", []) if isinstance(row, dict)
                }
                missing_views = sorted(
                    CORE_AUDIT_VIEWS - burden_ids
                )
                if missing_views:
                    errors.append(
                        "complete full v0.4 run must decide the logical, technical, and methodological audit views: "
                        + ", ".join(missing_views)
                    )
            errors.extend(
                validate_trust_spine(
                    review_dir,
                    run,
                    ledger,
                    validate_schema,
                    strict_current_contract=strict_burden_coverage,
                )
            )
            if run.get("mode") == "full" and strict_burden_coverage:
                validate_reverse_burden_activation(review_dir, run, errors)
            if strict_replication_contract:
                replication_manifest = load_json(
                    review_dir / "evidence/source-manifest.json", errors
                )
                if isinstance(replication_manifest, dict):
                    replication_sources = {
                        row.get("id"): row
                        for row in replication_manifest.get("sources", [])
                        if isinstance(row, dict)
                        and row.get("role") in REPLICATION_SOURCE_ROLES
                        and isinstance(row.get("id"), str)
                    }
                    code_source_ids = {
                        source_id
                        for source_id, source in replication_sources.items()
                        if source.get("role") == "code"
                    }
                    capabilities = run.get("capabilities")
                    replication_state = (
                        capabilities.get("replication_code")
                        if isinstance(capabilities, dict)
                        else None
                    )
                    if code_source_ids and replication_state == "not_supplied":
                        errors.append(
                            "replication_code=not_supplied conflicts with supplied code sources: "
                            + ", ".join(sorted(code_source_ids))
                        )
                    if (
                        replication_state in REPLICATION_MATERIAL_STATES
                        and not code_source_ids
                    ):
                        errors.append(
                            f"replication_code={replication_state} requires at least one code source in the source manifest"
                        )
                    replication_triggered = bool(replication_sources) or (
                        replication_state in REPLICATION_MATERIAL_STATES
                    )
                    active_replication_burdens = {
                        row.get("id")
                        for row in run.get("activated_burdens", [])
                        if isinstance(row, dict)
                        and isinstance(row.get("id"), str)
                        and row.get("status") == "active"
                        and row.get("parent_id") in REPLICATION_BURDEN_PARENTS
                    }
                    if replication_triggered and not active_replication_burdens:
                        errors.append(
                            "supplied replication material requires an active reproducibility or computational-validity burden"
                        )
                    if run.get("mode") == "quick" and replication_sources:
                        boundary = run.get("assessment_boundary")
                        boundary_rows = (
                            boundary.get("sources", [])
                            if isinstance(boundary, dict)
                            else []
                        )
                        boundary_sources = {
                            row.get("source_id"): row
                            for row in boundary_rows
                            if isinstance(row, dict)
                            and isinstance(row.get("source_id"), str)
                        }
                        missing_boundary_sources = sorted(
                            set(replication_sources) - set(boundary_sources)
                        )
                        if missing_boundary_sources:
                            errors.append(
                                "assessment boundary omits supplied replication sources: "
                                + ", ".join(missing_boundary_sources)
                            )
                        for source_id, source in replication_sources.items():
                            boundary_source = boundary_sources.get(source_id)
                            if not isinstance(boundary_source, dict):
                                continue
                            if boundary_source.get("path") != source.get("path"):
                                errors.append(
                                    f"assessment boundary source {source_id} path differs from source manifest"
                                )
                            if boundary_source.get("sha256") != source.get("sha256"):
                                errors.append(
                                    f"assessment boundary source {source_id} hash differs from source manifest"
                                )
                    if replication_state in INSPECTED_REPLICATION_STATES:
                        boundary = run.get("assessment_boundary")
                        boundary_rows = (
                            boundary.get("sources", [])
                            if isinstance(boundary, dict)
                            else []
                        )
                        boundary_sources = {
                            row.get("source_id"): row
                            for row in boundary_rows
                            if isinstance(row, dict)
                            and isinstance(row.get("source_id"), str)
                        }
                        unread_code_ids = sorted(
                            source_id
                            for source_id in code_source_ids
                            if boundary_sources.get(source_id, {}).get("status")
                            not in {"fully_read", "partially_read"}
                        )
                        if unread_code_ids:
                            errors.append(
                                f"replication_code={replication_state} requires inspected code sources "
                                "to be marked fully_read or partially_read in the assessment boundary: "
                                + ", ".join(unread_code_ids)
                            )
            structured_sources = load_json(
                review_dir / "evidence/external-sources.json", errors
            )
            if run.get("mode") == "full" and strict_burden_coverage:
                if (
                    isinstance(structured_sources, dict)
                    and structured_sources.get("schema_version") != "0.4"
                ):
                    errors.append(
                        "v0.4 full review requires evidence/external-sources.json schema_version 0.4"
                    )
            readable_sources = review_dir / "evidence" / "sources.md"
            if (
                strict_v4_audits
                and isinstance(structured_sources, dict)
                and readable_sources.exists()
            ):
                try:
                    expected_sources = render_sources(structured_sources)
                    if readable_sources.read_text(encoding="utf-8") != expected_sources:
                        errors.append(
                            "evidence/sources.md is not synchronized with external-sources.json"
                        )
                except (OSError, UnicodeError, TypeError, ValueError) as exc:
                    errors.append(f"cannot render canonical source audit: {exc}")
            structured_verification = load_json(review_dir / "evidence/verification.json", errors)
            readable_verification = review_dir / "evidence" / "verification.md"
            if isinstance(structured_verification, dict) and readable_verification.exists():
                try:
                    expected_verification = render_verification(structured_verification)
                    if readable_verification.read_text(encoding="utf-8") != expected_verification:
                        errors.append("evidence/verification.md is not synchronized with verification.json")
                except (OSError, UnicodeError, TypeError, ValueError) as exc:
                    errors.append(f"cannot render canonical verification audit: {exc}")
            validate_finalization_receipt(
                review_dir, run.get("review_id"), errors, run.get("mode")
            )

        coverage_unit_ids: set[str] = set()
        coverage_anchor_ids_by_unit: dict[str, set[str]] = {}
        figure_coverage_ids: set[str] = set()
        figure_coverage_labels: dict[str, str] = {}
        figure_coverage_statuses: dict[str, str] = {}
        table_coverage_ids: set[str] = set()
        table_coverage_labels: dict[str, str] = {}
        table_coverage_statuses: dict[str, str] = {}
        coverage_dimensions_by_id: dict[str, dict[str, Any]] = {}
        coverage_path = review_dir / "evidence/coverage.json"
        if run.get("mode") == "full" and coverage_path.exists():
            coverage = load_json(coverage_path, errors)
            if isinstance(coverage, dict):
                validate_schema(coverage, "coverage.schema.json", "evidence/coverage.json", errors)
                if strict_burden_coverage and coverage.get("schema_version") != "0.2":
                    errors.append(
                        "v0.4 full review requires evidence/coverage.json schema_version 0.2"
                    )
                if coverage.get("review_id") != run.get("review_id"):
                    errors.append("coverage review_id differs from run.json")
                branches = set(coverage.get("branches_applied", []))
                if "universal" not in branches:
                    errors.append("full coverage requires the universal branch")
                known_ids = set(clean_ids)
                covered_ids: set[str] = set()
                for collection_name in ("units", "dimensions"):
                    rows = coverage.get(collection_name, [])
                    for row in rows if isinstance(rows, list) else []:
                        if not isinstance(row, dict):
                            continue
                        row_ids = row.get("finding_ids", [])
                        if isinstance(row_ids, list):
                            covered_ids.update(row_ids)
                        if row.get("status") == "findings" and not row_ids:
                            errors.append(f"coverage {collection_name} row '{row.get('id')}' has findings status but no IDs")
                        if row.get("status") != "findings" and row_ids:
                            errors.append(f"coverage {collection_name} row '{row.get('id')}' has IDs without findings status")
                unknown_coverage_ids = sorted(covered_ids - known_ids)
                if unknown_coverage_ids:
                    errors.append(f"coverage references unknown finding IDs: {', '.join(unknown_coverage_ids)}")
                active_ids = {item.get("id") for item in active}
                unit_rows = [row for row in coverage.get("units", []) if isinstance(row, dict)]
                coverage_anchor_ids_by_unit = {
                    str(row.get("id")): {
                        anchor_id
                        for anchor_id in row.get("anchor_ids", [])
                        if isinstance(anchor_id, str)
                    }
                    for row in unit_rows
                    if isinstance(row.get("id"), str)
                }
                unit_id_list = [row.get("id") for row in unit_rows if row.get("id")]
                duplicate_unit_ids = sorted(item for item, count in Counter(unit_id_list).items() if count > 1)
                if duplicate_unit_ids:
                    errors.append(f"duplicate coverage unit IDs: {', '.join(duplicate_unit_ids)}")
                coverage_unit_ids = set(unit_id_list)
                figure_coverage_ids = {
                    row.get("id") for row in unit_rows if row.get("type") == "figure" and row.get("id")
                }
                figure_coverage_labels = {
                    str(row.get("id")): str(row.get("label"))
                    for row in unit_rows
                    if row.get("type") == "figure" and row.get("id") and row.get("label")
                }
                figure_coverage_statuses = {
                    str(row.get("id")): str(row.get("status"))
                    for row in unit_rows
                    if row.get("type") == "figure" and row.get("id") and row.get("status")
                }
                table_coverage_ids = {
                    row.get("id") for row in unit_rows if row.get("type") == "table" and row.get("id")
                }
                table_coverage_labels = {
                    str(row.get("id")): str(row.get("label"))
                    for row in unit_rows
                    if row.get("type") == "table" and row.get("id") and row.get("label")
                }
                table_coverage_statuses = {
                    str(row.get("id")): str(row.get("status"))
                    for row in unit_rows
                    if row.get("type") == "table" and row.get("id") and row.get("status")
                }
                if coverage.get("schema_version") == "0.2":
                    coverage_source_manifest = load_json(
                        review_dir / "evidence/source-manifest.json", errors
                    )
                    source_by_id: dict[str, dict[str, Any]] = {}
                    anchor_by_id: dict[str, dict[str, Any]] = {}
                    if isinstance(coverage_source_manifest, dict):
                        source_by_id = {
                            row.get("id"): row
                            for row in coverage_source_manifest.get("sources", [])
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                        }
                        anchor_by_id = {
                            row.get("id"): row
                            for row in coverage_source_manifest.get("anchors", [])
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                        }
                    covered_anchor_ids: set[str] = set()
                    scope_sources: set[str] = set()
                    expected_anchor_kind = {
                        "figure": "figure",
                        "table": "table_cell",
                        "equation": "equation",
                        "code": "code_range",
                    }
                    for unit in unit_rows:
                        unit_id = unit.get("id")
                        source_id = unit.get("source_id")
                        if source_id not in source_by_id:
                            errors.append(
                                f"coverage unit {unit_id} references unknown source {source_id}"
                            )
                            continue
                        anchor_ids = unit.get("anchor_ids", [])
                        if not isinstance(anchor_ids, list):
                            continue
                        for anchor_id in anchor_ids:
                            anchor = anchor_by_id.get(anchor_id)
                            if not isinstance(anchor, dict):
                                errors.append(
                                    f"coverage unit {unit_id} references unknown anchor {anchor_id}"
                                )
                                continue
                            covered_anchor_ids.add(anchor_id)
                            if anchor.get("source_id") != source_id:
                                errors.append(
                                    f"coverage unit {unit_id} anchor {anchor_id} belongs to another source"
                                )
                            if anchor.get("kind") == "scope":
                                scope_sources.add(str(source_id))
                        required_kind = expected_anchor_kind.get(unit.get("type"))
                        if required_kind and unit.get("status") != "not_applicable" and not any(
                            anchor_by_id.get(anchor_id, {}).get("kind") == required_kind
                            for anchor_id in anchor_ids
                        ):
                            errors.append(
                                f"coverage unit {unit_id} requires a {required_kind} source anchor"
                            )
                    in_scope_roles = (
                        INTERNAL_SOURCE_ROLES
                        if strict_burden_coverage
                        else DOCUMENT_SOURCE_ROLES
                    )
                    in_scope_source_ids = {
                        source_id for source_id, source in source_by_id.items()
                        if source.get("role") in in_scope_roles
                    }
                    missing_scope_units = sorted(in_scope_source_ids - scope_sources)
                    if missing_scope_units:
                        errors.append(
                            "coverage lacks a scope-anchored unit for in-scope sources: "
                            + ", ".join(missing_scope_units)
                        )
                    relevant_anchor_ids = {
                        anchor_id for anchor_id, anchor in anchor_by_id.items()
                        if anchor.get("source_id") in in_scope_source_ids
                    }
                    missing_anchor_coverage = sorted(relevant_anchor_ids - covered_anchor_ids)
                    if missing_anchor_coverage:
                        errors.append(
                            "source anchors missing from coverage units: "
                            + ", ".join(missing_anchor_coverage)
                        )
                    unit_type_for_anchor_kind = {
                        "equation": "equation",
                        "table_cell": "table",
                        "figure": "figure",
                        "code_range": "code",
                    }
                    for anchor_id in sorted(relevant_anchor_ids):
                        anchor_kind = anchor_by_id.get(anchor_id, {}).get("kind")
                        required_unit_type = unit_type_for_anchor_kind.get(anchor_kind)
                        if required_unit_type is None:
                            continue
                        if not any(
                            required_unit_type == unit.get("type")
                            and anchor_id in unit.get("anchor_ids", [])
                            for unit in unit_rows
                            if isinstance(unit.get("anchor_ids"), list)
                        ):
                            errors.append(
                                f"source anchor {anchor_id} of kind {anchor_kind} requires a matching {required_unit_type} coverage unit"
                            )
                    if strict_burden_coverage:
                        validate_source_inventory_closure(
                            review_dir,
                            coverage,
                            source_by_id,
                            anchor_by_id,
                            unit_rows,
                            errors,
                        )
                    burden_rows = [
                        row for row in coverage.get("burden_audits", [])
                        if isinstance(row, dict)
                    ]
                    burden_id_list = [
                        row.get("burden_id") for row in burden_rows if row.get("burden_id")
                    ]
                    duplicate_burden_audits = sorted(
                        burden_id for burden_id, count in Counter(burden_id_list).items()
                        if count > 1
                    )
                    if duplicate_burden_audits:
                        errors.append(
                            "duplicate coverage burden IDs: "
                            + ", ".join(duplicate_burden_audits)
                        )
                    run_burdens = {
                        row.get("id"): row
                        for row in run.get("activated_burdens", [])
                        if isinstance(row, dict) and isinstance(row.get("id"), str)
                    }
                    burden_audits = {
                        row.get("burden_id"): row
                        for row in burden_rows
                        if isinstance(row.get("burden_id"), str)
                    }
                    missing_burden_audits = sorted(set(run_burdens) - set(burden_audits))
                    unknown_burden_audits = sorted(set(burden_audits) - set(run_burdens))
                    if missing_burden_audits:
                        errors.append(
                            "activated burdens missing from coverage: "
                            + ", ".join(missing_burden_audits)
                        )
                    if unknown_burden_audits:
                        errors.append(
                            "coverage references unknown burden IDs: "
                            + ", ".join(unknown_burden_audits)
                        )
                    burden_finding_ids: set[str] = set()
                    for burden_id, row in burden_audits.items():
                        run_burden = run_burdens.get(burden_id)
                        if not isinstance(run_burden, dict):
                            continue
                        if row.get("parent_id") != run_burden.get("parent_id"):
                            errors.append(
                                f"coverage burden {burden_id} parent_id differs from run.json"
                            )
                        row_status = row.get("status")
                        run_status = run_burden.get("status")
                        if run_status == "active" and row_status == "not_applicable":
                            errors.append(
                                f"active burden {burden_id} cannot be not_applicable in coverage"
                            )
                        if run_status == "not_applicable" and row_status != "not_applicable":
                            errors.append(
                                f"not-applicable burden {burden_id} must be not_applicable in coverage"
                            )
                        row_units = row.get("coverage_unit_ids", [])
                        if run_status == "active" and not row_units:
                            errors.append(
                                f"active coverage burden {burden_id} requires at least one coverage unit"
                            )
                        if isinstance(row_units, list):
                            unknown_units = sorted(set(row_units) - coverage_unit_ids)
                            if unknown_units:
                                errors.append(
                                    f"coverage burden {burden_id} references unknown coverage units: "
                                    + ", ".join(unknown_units)
                                )
                        row_findings = row.get("finding_ids", [])
                        if isinstance(row_findings, list):
                            burden_finding_ids.update(row_findings)
                            unknown_findings = sorted(set(row_findings) - known_ids)
                            if unknown_findings:
                                errors.append(
                                    f"coverage burden {burden_id} references unknown finding IDs: "
                                    + ", ".join(unknown_findings)
                                )
                            inactive_findings = sorted(set(row_findings) - active_ids)
                            if inactive_findings:
                                errors.append(
                                    f"coverage burden {burden_id} references inactive finding IDs: "
                                    + ", ".join(inactive_findings)
                                )
                        if row_status == "bounded" and not str(row.get("notes", "")).strip():
                            errors.append(
                                f"bounded coverage burden {burden_id} requires a boundary note"
                            )
                    capabilities = run.get("capabilities")
                    replication_state = (
                        capabilities.get("replication_code")
                        if isinstance(capabilities, dict)
                        else None
                    )
                    if (
                        strict_burden_coverage
                        and (
                            replication_state in REPLICATION_MATERIAL_STATES
                            or any(
                                source.get("role") in REPLICATION_SOURCE_ROLES
                                for source in source_by_id.values()
                            )
                        )
                    ):
                        replication_source_ids = {
                            source_id
                            for source_id, source in source_by_id.items()
                            if source.get("role") in REPLICATION_SOURCE_ROLES
                        }
                        code_source_ids = {
                            source_id for source_id in replication_source_ids
                            if source_by_id.get(source_id, {}).get("role") == "code"
                        }
                        replication_source_units = {
                            str(unit.get("id"))
                            for unit in unit_rows
                            if unit.get("source_id") in replication_source_ids
                            and isinstance(unit.get("id"), str)
                        }
                        if replication_source_ids and not replication_source_units:
                            errors.append(
                                "supplied replication sources require source-bound coverage units"
                            )
                        inapplicable_replication_units = sorted(
                            str(unit.get("id"))
                            for unit in unit_rows
                            if unit.get("source_id") in replication_source_ids
                            and unit.get("status") == "not_applicable"
                            and isinstance(unit.get("id"), str)
                        )
                        if inapplicable_replication_units:
                            errors.append(
                                "supplied replication-material coverage units cannot be not_applicable; use bounded when permission or inputs limit review: "
                                + ", ".join(inapplicable_replication_units)
                            )
                        eligible_burden_ids = {
                            burden_id
                            for burden_id, burden in run_burdens.items()
                            if burden.get("status") == "active"
                            and burden.get("parent_id") in REPLICATION_BURDEN_PARENTS
                        }
                        audited_replication_units = {
                            unit_id
                            for burden_id in eligible_burden_ids
                            for unit_id in burden_audits.get(burden_id, {}).get(
                                "coverage_unit_ids", []
                            )
                            if isinstance(unit_id, str)
                        }
                        missing_replication_audit_units = sorted(
                            replication_source_units - audited_replication_units
                        )
                        if missing_replication_audit_units:
                            errors.append(
                                "replication burden audits omit supplied-material coverage units: "
                                + ", ".join(missing_replication_audit_units)
                            )
                        if replication_state in INSPECTED_REPLICATION_STATES:
                            code_sources_with_typed_units = {
                                str(unit.get("source_id"))
                                for unit in unit_rows
                                if unit.get("source_id") in code_source_ids
                                and unit.get("type") == "code"
                                and unit.get("status") != "not_applicable"
                            }
                            missing_typed_code_sources = sorted(
                                code_source_ids - code_sources_with_typed_units
                            )
                            if missing_typed_code_sources:
                                errors.append(
                                    f"replication_code={replication_state} requires a code coverage unit for each inspected code source: "
                                    + ", ".join(missing_typed_code_sources)
                                )
                    findings_without_burden = sorted(active_ids - burden_finding_ids)
                    if findings_without_burden:
                        errors.append(
                            "active findings missing from burden coverage: "
                            + ", ".join(findings_without_burden)
                        )
                missing_coverage_ids = sorted(active_ids - covered_ids)
                if missing_coverage_ids:
                    errors.append(f"active findings missing from coverage: {', '.join(missing_coverage_ids)}")
                dimension_rows = [row for row in coverage.get("dimensions", []) if isinstance(row, dict)]
                coverage_dimensions_by_id = {
                    row.get("id"): row for row in dimension_rows if row.get("id")
                }
                dimension_id_list = [row.get("id") for row in dimension_rows if row.get("id")]
                duplicate_dimension_ids = sorted(item for item, count in Counter(dimension_id_list).items() if count > 1)
                if duplicate_dimension_ids:
                    errors.append(f"duplicate coverage dimension IDs: {', '.join(duplicate_dimension_ids)}")
                dimension_ids = set(dimension_id_list)
                undeclared_dimension_branches = sorted({
                    row.get("branch") for row in dimension_rows
                    if isinstance(row.get("branch"), str) and row.get("branch") not in branches
                })
                if undeclared_dimension_branches:
                    errors.append(
                        "coverage dimensions use undeclared branches: "
                        + ", ".join(undeclared_dimension_branches)
                    )
                # These rows are the genuinely paper-general reader/process
                # checks. Method and object rows are activated by the
                # structured claims, analytical ledgers, exhibits, and burden
                # audit below; they are not a universal method checklist.
                required_universal_dimensions = {
                    "contribution-literature",
                    "reader-clarity",
                    "claim-consistency",
                    "terms-variables",
                    "review-tone",
                    "writing-typography",
                    "language-mechanics",
                }
                missing_reader_dimensions = sorted(required_universal_dimensions - dimension_ids)
                if missing_reader_dimensions:
                    errors.append(
                        "coverage is missing required audit dimensions: "
                        + ", ".join(missing_reader_dimensions)
                    )
                for row in dimension_rows:
                    if row.get("id") in required_universal_dimensions and row.get("status") == "not_applicable":
                        errors.append(f"universal coverage dimension '{row.get('id')}' cannot be not_applicable")
                    if row.get("status") == "bounded" and not row.get("notes", "").strip():
                        errors.append(f"bounded coverage dimension '{row.get('id')}' requires a boundary note")
                    if row.get("status") == "not_applicable" and not row.get("notes", "").strip():
                        errors.append(
                            f"not-applicable coverage dimension '{row.get('id')}' requires a source-specific reason"
                        )
                sweep = coverage.get("second_sweep", {})
                if comment_policy.get("exhaustive") is True:
                    if not isinstance(sweep, dict) or sweep.get("required") is not True or sweep.get("completed") is not True:
                        errors.append("exhaustive full review requires a completed second sweep")
                if coverage.get("schema_version") == "0.2":
                    readable_coverage = review_dir / "evidence" / "coverage.md"
                    if readable_coverage.exists():
                        try:
                            if readable_coverage.read_text(encoding="utf-8") != render_coverage(coverage):
                                errors.append(
                                    "evidence/coverage.md is not synchronized with coverage.json"
                                )
                        except (OSError, UnicodeError, TypeError, ValueError) as exc:
                            errors.append(f"cannot render canonical coverage audit: {exc}")
                # Do not infer a quota from manuscript length. The explicit
                # comment policy and recorded coverage determine sufficiency.

        claims_for_computation_audit: dict[str, Any] | None = None
        source_binding_context: dict[str, Any] | None = None
        analytical_for_computation_audit: dict[str, Any] | None = None
        computations_for_computation_audit: dict[str, Any] | None = None
        computations_path_for_audit = review_dir / "evidence/computations.json"
        if run.get("mode") == "full" and computations_path_for_audit.exists():
            candidate_computations = load_json(computations_path_for_audit, errors)
            if isinstance(candidate_computations, dict):
                computations_for_computation_audit = candidate_computations
        claims_path = review_dir / "evidence/claims.json"
        if run.get("mode") == "full" and claims_path.exists():
            claims = load_json(claims_path, errors)
            if isinstance(claims, dict):
                claims_for_computation_audit = claims
                validate_schema(claims, "claims.schema.json", "evidence/claims.json", errors)
                if strict_v4_audits and claims.get("schema_version") != "0.2":
                    errors.append(
                        "v0.4 full review requires evidence/claims.json schema_version 0.2"
                    )
                if claims.get("review_id") != run.get("review_id"):
                    errors.append("claims review_id differs from run.json")
                strict_claim_source_binding = (
                    strict_burden_coverage and claims.get("schema_version") == "0.2"
                )
                if strict_claim_source_binding:
                    source_binding_context = load_source_binding_context(
                        review_dir, findings, errors
                    )
                families = {
                    family.get("id"): family
                    for family in claims.get("claim_families", [])
                    if isinstance(family, dict) and family.get("id")
                }
                active_by_id = {item.get("id"): item for item in active}
                claim_family_ids = [
                    family.get("id") for family in claims.get("claim_families", [])
                    if isinstance(family, dict) and family.get("id")
                ]
                duplicate_claim_ids = sorted(item for item, count in Counter(claim_family_ids).items() if count > 1)
                if duplicate_claim_ids:
                    errors.append(f"duplicate claim family IDs: {', '.join(duplicate_claim_ids)}")
                scope = claims.get("audit_scope", {})
                scope_units = set(scope.get("coverage_unit_ids", [])) if isinstance(scope, dict) else set()
                if scope_units != coverage_unit_ids:
                    missing = sorted(coverage_unit_ids - scope_units)
                    extra = sorted(scope_units - coverage_unit_ids)
                    if missing:
                        errors.append(f"claims audit scope omits coverage units: {', '.join(missing)}")
                    if extra:
                        errors.append(f"claims audit scope references unknown coverage units: {', '.join(extra)}")
                headline_ids = set(scope.get("headline_claim_ids", [])) if isinstance(scope, dict) else set()
                expected_headline_ids = {
                    family.get("id") for family in claims.get("claim_families", [])
                    if isinstance(family, dict) and family.get("is_headline") is True
                }
                if headline_ids != expected_headline_ids:
                    errors.append("claims audit headline_claim_ids must exactly match is_headline claim families")
                if strict_claim_source_binding and isinstance(source_binding_context, dict):
                    declared_scope_anchors = {
                        anchor_id
                        for anchor_id in scope.get("scope_anchor_ids", [])
                        if isinstance(scope, dict) and isinstance(anchor_id, str)
                    }
                    if not declared_scope_anchors:
                        errors.append(
                            "current claims audit requires canonical scope_anchor_ids"
                        )
                    expected_scope_sources: set[str] = set()
                    for unit_anchor_ids in coverage_anchor_ids_by_unit.values():
                        for anchor_id in unit_anchor_ids:
                            anchor = source_binding_context["anchor_by_id"].get(anchor_id)
                            source = source_binding_context["source_by_id"].get(
                                anchor.get("source_id") if isinstance(anchor, dict) else None
                            )
                            if (
                                isinstance(anchor, dict)
                                and isinstance(source, dict)
                                and source.get("role") in DOCUMENT_SOURCE_ROLES
                                and isinstance(anchor.get("source_id"), str)
                            ):
                                expected_scope_sources.add(anchor["source_id"])
                    declared_scope_sources: set[str] = set()
                    for anchor_id in declared_scope_anchors:
                        anchor = source_binding_context["anchor_by_id"].get(anchor_id)
                        if not isinstance(anchor, dict):
                            errors.append(
                                f"claims audit scope references unknown anchor {anchor_id}"
                            )
                        elif anchor.get("kind") != "scope":
                            errors.append(
                                f"claims audit scope anchor {anchor_id} is not a canonical scope anchor"
                            )
                        elif isinstance(anchor.get("source_id"), str):
                            declared_scope_sources.add(anchor["source_id"])
                    if declared_scope_sources != expected_scope_sources:
                        missing = sorted(expected_scope_sources - declared_scope_sources)
                        extra = sorted(declared_scope_sources - expected_scope_sources)
                        if missing:
                            errors.append(
                                "claims audit scope anchors omit covered sources: "
                                + ", ".join(missing)
                            )
                        if extra:
                            errors.append(
                                "claims audit scope anchors reference uncovered sources: "
                                + ", ".join(extra)
                            )
                occurrence_ids: list[str] = []
                for finding in active:
                    finding_id = finding.get("id")
                    for claim_id in finding.get("claim_ids", []):
                        if claim_id not in families:
                            errors.append(f"active finding {finding_id} references unknown claim family {claim_id}")
                        elif finding_id not in families[claim_id].get("finding_ids", []):
                            errors.append(f"claim family {claim_id} does not map back to active finding {finding_id}")
                for claim_id, family in families.items():
                    occurrence_anchor_ids: set[str] = set()
                    for finding_id in family.get("finding_ids", []):
                        if finding_id not in active_by_id:
                            errors.append(f"claim family {claim_id} references unknown or inactive finding {finding_id}")
                    for occurrence in family.get("occurrences", []):
                        if not isinstance(occurrence, dict):
                            continue
                        occurrence_ids.append(occurrence.get("id"))
                        if occurrence.get("coverage_unit_id") not in coverage_unit_ids:
                            errors.append(
                                f"claim occurrence {occurrence.get('id')} references unknown coverage unit {occurrence.get('coverage_unit_id')}"
                            )
                        if strict_claim_source_binding and isinstance(source_binding_context, dict):
                            resolved_anchor = validate_exact_source_binding(
                                label=f"claim occurrence {occurrence.get('id')}",
                                anchor_id=occurrence.get("anchor_id"),
                                representation=occurrence.get("representation"),
                                content=occurrence.get("text"),
                                locator=occurrence.get("locator"),
                                coverage_unit_id=occurrence.get("coverage_unit_id"),
                                context=source_binding_context,
                                coverage_anchor_ids_by_unit=coverage_anchor_ids_by_unit,
                                errors=errors,
                            )
                            if isinstance(resolved_anchor, str):
                                occurrence_anchor_ids.add(resolved_anchor)
                        unsafe = {
                            "qualifier_loss", "scope_expansion", "strength_inflation",
                            "benchmark_or_definition_drift", "numerical_conflict", "direct_contradiction",
                        }
                        if occurrence.get("relation_to_canonical") in unsafe and not family.get("finding_ids"):
                            errors.append(
                                f"unsafe claim occurrence {occurrence.get('id')} must map to an active finding"
                            )
                    if strict_claim_source_binding:
                        declared_family_anchors = {
                            anchor_id
                            for anchor_id in family.get("anchor_ids", [])
                            if isinstance(anchor_id, str)
                        }
                        if declared_family_anchors != occurrence_anchor_ids:
                            missing = sorted(occurrence_anchor_ids - declared_family_anchors)
                            extra = sorted(declared_family_anchors - occurrence_anchor_ids)
                            detail: list[str] = []
                            if missing:
                                detail.append("missing " + ", ".join(missing))
                            if extra:
                                detail.append("not used by occurrences " + ", ".join(extra))
                            errors.append(
                                f"claim family {claim_id} anchor_ids must exactly match its occurrence anchors"
                                + (f" ({'; '.join(detail)})" if detail else "")
                            )
                duplicate_occurrence_ids = sorted(item for item, count in Counter(occurrence_ids).items() if item and count > 1)
                if duplicate_occurrence_ids:
                    errors.append(f"duplicate claim occurrence IDs: {', '.join(duplicate_occurrence_ids)}")

                def validate_mapped_rows(
                    rows: Any,
                    kind: str,
                    adverse: set[str],
                    clean: set[str],
                ) -> None:
                    if not isinstance(rows, list):
                        return
                    row_ids = [row.get("id") for row in rows if isinstance(row, dict) and row.get("id")]
                    duplicates = sorted(item for item, count in Counter(row_ids).items() if count > 1)
                    if duplicates:
                        errors.append(f"duplicate {kind} IDs: {', '.join(duplicates)}")
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        for unit_id in ([row.get("coverage_unit_id")] if kind == "reader-map" else row.get("coverage_unit_ids", [])):
                            if unit_id not in coverage_unit_ids:
                                errors.append(f"{kind} {row.get('id')} references unknown coverage unit {unit_id}")
                        raw_mapped = row.get("finding_ids", [])
                        mapped = raw_mapped if isinstance(raw_mapped, list) else []
                        for finding_id in mapped:
                            if finding_id not in active_by_id:
                                errors.append(f"{kind} {row.get('id')} references unknown or inactive finding {finding_id}")
                        if row.get("status") in adverse and not mapped:
                            if kind == "reader-map" and isinstance(row.get("bounded_reason"), str) and row.get("bounded_reason", "").strip():
                                continue
                            errors.append(f"adverse {kind} state {row.get('id')} must map to an active finding")
                        if row.get("status") in clean and mapped:
                            errors.append(
                                f"clean {kind} state {row.get('id')} must not map to an active finding"
                            )

                validate_mapped_rows(
                    claims.get("reader_map"), "reader-map",
                    {"unclear", "inconsistent"},
                    {"clear_and_convincing"} if claims.get("schema_version") == "0.2" else set(),
                )
                validate_mapped_rows(
                    claims.get("terms"), "term",
                    {"undefined", "inconsistent", "overloaded"}, set(),
                )
                if strict_claim_source_binding and isinstance(source_binding_context, dict):
                    for row in claims.get("reader_map", []):
                        if not isinstance(row, dict):
                            continue
                        row_id = row.get("id")
                        raw_row_claim_ids = row.get("claim_ids")
                        row_claim_ids = {
                            claim_id for claim_id in raw_row_claim_ids
                            if isinstance(claim_id, str)
                        } if isinstance(raw_row_claim_ids, list) else set()
                        if not row_claim_ids:
                            errors.append(
                                f"reader-map {row_id} requires at least one claim_id"
                            )
                        unknown_claim_ids = sorted(row_claim_ids - set(families))
                        if unknown_claim_ids:
                            errors.append(
                                f"reader-map {row_id} references unknown claim families: "
                                + ", ".join(unknown_claim_ids)
                            )
                        unit_id = row.get("coverage_unit_id")
                        support = validate_source_evidence_refs(
                            row.get("evidence_refs"),
                            label=f"reader-map {row_id}",
                            coverage_unit_ids={unit_id} if isinstance(unit_id, str) else set(),
                            context=source_binding_context,
                            coverage_anchor_ids_by_unit=coverage_anchor_ids_by_unit,
                            errors=errors,
                        )
                        for claim_id in row_claim_ids & set(families):
                            claim_anchors = {
                                anchor_id
                                for anchor_id in families[claim_id].get("anchor_ids", [])
                                if isinstance(anchor_id, str)
                            }
                            if not claim_anchors.intersection(support["direct_anchor_ids"]):
                                errors.append(
                                    f"reader-map {row_id} evidence is not anchored to claim family {claim_id}"
                                )
                        raw_mapped_findings = row.get("finding_ids")
                        mapped_findings = {
                            finding_id for finding_id in raw_mapped_findings
                            if isinstance(finding_id, str)
                        } if isinstance(raw_mapped_findings, list) else set()
                        missing_owners = sorted(
                            mapped_findings - support["finding_owners"]
                        )
                        if missing_owners:
                            errors.append(
                                f"reader-map {row_id} finding links lack reciprocal passed evidence: "
                                + ", ".join(missing_owners)
                            )
                        if row.get("status") == "clear_and_convincing" and not support[
                            "absence_anchor_ids"
                        ]:
                            errors.append(
                                f"clean reader-map state {row_id} requires a scope-anchored checked_absence reference"
                            )

                    term_support_by_id: dict[str, dict[str, set[str]]] = {}
                    for row in claims.get("terms", []):
                        if not isinstance(row, dict):
                            continue
                        row_id = row.get("id")
                        row_units = {
                            unit_id for unit_id in row.get("coverage_unit_ids", [])
                            if isinstance(unit_id, str)
                        }
                        first_use_anchor_id = row.get("first_use_anchor_id")
                        first_use_anchor = source_binding_context["anchor_by_id"].get(
                            first_use_anchor_id
                        )
                        if not isinstance(first_use_anchor_id, str):
                            errors.append(
                                f"term {row_id} requires a canonical first_use_anchor_id"
                            )
                        elif not isinstance(first_use_anchor, dict):
                            errors.append(
                                f"term {row_id} references unknown first-use anchor {first_use_anchor_id}"
                            )
                        else:
                            if first_use_anchor.get("kind") == "scope":
                                errors.append(
                                    f"term {row_id} first use requires a precise anchor, not {first_use_anchor_id}"
                                )
                            permitted = set().union(
                                *(coverage_anchor_ids_by_unit.get(unit_id, set()) for unit_id in row_units)
                            ) if row_units else set()
                            if first_use_anchor_id not in permitted:
                                errors.append(
                                    f"term {row_id} first-use anchor is not assigned to its coverage units"
                                )
                            canonical_locator = first_use_anchor.get("locator")
                            if (
                                not isinstance(canonical_locator, str)
                                or normalize_source_transcription(str(row.get("first_use", "")))
                                != normalize_source_transcription(canonical_locator)
                            ):
                                errors.append(
                                    f"term {row_id} first_use locator does not match canonical anchor {first_use_anchor_id}"
                                )
                            canonical_content = source_binding_context["anchor_content"].get(
                                first_use_anchor_id
                            )
                            if (
                                isinstance(canonical_content, str)
                                and normalize_source_transcription(str(row.get("label", "")))
                                not in normalize_source_transcription(canonical_content)
                            ):
                                errors.append(
                                    f"term {row_id} label is absent from its declared first-use anchor"
                                )
                        support = validate_source_evidence_refs(
                            row.get("evidence_refs"),
                            label=f"term {row_id}",
                            coverage_unit_ids=row_units,
                            context=source_binding_context,
                            coverage_anchor_ids_by_unit=coverage_anchor_ids_by_unit,
                            errors=errors,
                        )
                        if isinstance(row_id, str):
                            term_support_by_id[row_id] = support
                        status = row.get("status")
                        if status in {"defined_clear", "defined_remote", "inconsistent", "overloaded"} and not support[
                            "direct_anchor_ids"
                        ]:
                            errors.append(
                                f"term {row_id} state {status} requires precise source support"
                            )
                        if status in {"defined_clear", "undefined"} and not support[
                            "absence_anchor_ids"
                        ]:
                            errors.append(
                                f"term {row_id} state {status} requires a scope-anchored checked_absence reference"
                            )
                        raw_mapped_findings = row.get("finding_ids")
                        mapped_findings = {
                            finding_id for finding_id in raw_mapped_findings
                            if isinstance(finding_id, str)
                        } if isinstance(raw_mapped_findings, list) else set()
                        missing_owners = sorted(
                            mapped_findings - support["finding_owners"]
                        )
                        if missing_owners:
                            errors.append(
                                f"term {row_id} finding links lack reciprocal passed evidence: "
                                + ", ".join(missing_owners)
                            )

                    terminology = claims.get("terminology_inventory")
                    if not isinstance(terminology, dict):
                        errors.append(
                            "current claims audit requires a structured terminology_inventory"
                        )
                    else:
                        inventory_sources = [
                            row for row in terminology.get("sources", [])
                            if isinstance(row, dict)
                        ]
                        inventory_candidates = [
                            row for row in terminology.get("candidates", [])
                            if isinstance(row, dict)
                        ]
                        source_ids = [
                            row.get("source_id") for row in inventory_sources
                            if isinstance(row.get("source_id"), str)
                        ]
                        duplicate_inventory_sources = sorted(
                            value for value, count in Counter(source_ids).items()
                            if count > 1
                        )
                        if duplicate_inventory_sources:
                            errors.append(
                                "terminology inventory repeats sources: "
                                + ", ".join(duplicate_inventory_sources)
                            )
                        document_source_ids = {
                            source_id
                            for source_id, source in source_binding_context["source_by_id"].items()
                            if source.get("role") in DOCUMENT_SOURCE_ROLES
                        }
                        if set(source_ids) != document_source_ids:
                            missing = sorted(document_source_ids - set(source_ids))
                            extra = sorted(set(source_ids) - document_source_ids)
                            if missing:
                                errors.append(
                                    "terminology inventory omits document sources: "
                                    + ", ".join(missing)
                                )
                            if extra:
                                errors.append(
                                    "terminology inventory references non-document sources: "
                                    + ", ".join(extra)
                                )

                        candidate_ids = [
                            row.get("id") for row in inventory_candidates
                            if isinstance(row.get("id"), str)
                        ]
                        duplicate_candidate_ids = sorted(
                            value for value, count in Counter(candidate_ids).items()
                            if count > 1
                        )
                        if duplicate_candidate_ids:
                            errors.append(
                                "terminology inventory repeats candidate IDs: "
                                + ", ".join(duplicate_candidate_ids)
                            )
                        candidate_by_id = {
                            row.get("id"): row
                            for row in inventory_candidates
                            if isinstance(row.get("id"), str)
                        }
                        terms_by_id = {
                            row.get("id"): row
                            for row in claims.get("terms", [])
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                        }
                        mapped_term_ids: set[str] = set()

                        for source_row in inventory_sources:
                            source_id = source_row.get("source_id")
                            source = source_binding_context["source_by_id"].get(source_id)
                            scope_anchor_id = source_row.get("scope_anchor_id")
                            scope_anchor = source_binding_context["anchor_by_id"].get(
                                scope_anchor_id
                            )
                            if (
                                not isinstance(scope_anchor, dict)
                                or scope_anchor.get("source_id") != source_id
                                or scope_anchor.get("kind") != "scope"
                            ):
                                errors.append(
                                    f"terminology source {source_id} requires its canonical scope anchor"
                                )
                            declared_candidate_ids = {
                                value for value in source_row.get("candidate_ids", [])
                                if isinstance(value, str)
                            }
                            actual_candidate_ids = {
                                row.get("id") for row in inventory_candidates
                                if row.get("source_id") == source_id
                                and isinstance(row.get("id"), str)
                            }
                            if declared_candidate_ids != actual_candidate_ids:
                                errors.append(
                                    f"terminology source {source_id} candidate_ids do not exactly match its candidate rows"
                                )
                            method = source_row.get("method")
                            boundary_reason = source_row.get("boundary_reason")
                            if method == "bounded_manual_scope":
                                if not isinstance(boundary_reason, str) or not boundary_reason.strip():
                                    errors.append(
                                        f"bounded terminology source {source_id} requires a boundary_reason"
                                    )
                            elif boundary_reason is not None:
                                errors.append(
                                    f"unbounded terminology source {source_id} must set boundary_reason to null"
                                )

                            if not isinstance(source, dict):
                                continue
                            if source.get("media_type") == "application/pdf":
                                if method != "pdf_ingestion":
                                    errors.append(
                                        f"PDF terminology source {source_id} must use pdf_ingestion candidate reconciliation"
                                    )
                                extraction = source.get("extraction")
                                ingestion_path = (
                                    extraction.get("ingestion_manifest_path")
                                    if isinstance(extraction, dict)
                                    else None
                                )
                                ingestion: Any = None
                                if isinstance(ingestion_path, str):
                                    try:
                                        ingestion = strict_json_loads(
                                            safe_read_bytes(review_dir, ingestion_path)
                                        )
                                    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                                        # Canonical ingestion validation records the retained-file error.
                                        ingestion = None
                                if isinstance(ingestion, dict):
                                    expected_pdf_candidates = pdf_symbol_candidate_inventory(
                                        ingestion,
                                        source_binding_context["anchor_by_id"],
                                        str(source_id),
                                    )
                                    observed_pdf_candidates: dict[
                                        tuple[str, tuple[str, ...]], dict[str, Any]
                                    ] = {}
                                    for candidate_id in declared_candidate_ids:
                                        candidate = candidate_by_id.get(candidate_id)
                                        if not isinstance(candidate, dict):
                                            continue
                                        key = (
                                            str(candidate.get("candidate", "")),
                                            tuple(
                                                value for value in candidate.get("codepoints", [])
                                                if isinstance(value, str)
                                            ),
                                        )
                                        if key in observed_pdf_candidates:
                                            errors.append(
                                                f"PDF terminology source {source_id} repeats candidate {key[0]!r}"
                                            )
                                        observed_pdf_candidates[key] = candidate
                                    if set(observed_pdf_candidates) != set(expected_pdf_candidates):
                                        errors.append(
                                            f"PDF terminology source {source_id} does not adjudicate the exact ingestion symbol inventory"
                                        )
                                    for key in set(observed_pdf_candidates) & set(expected_pdf_candidates):
                                        observed_anchors = {
                                            value
                                            for value in observed_pdf_candidates[key].get(
                                                "occurrence_anchor_ids", []
                                            )
                                            if isinstance(value, str)
                                        }
                                        if observed_anchors != expected_pdf_candidates[key]:
                                            errors.append(
                                                f"PDF terminology candidate {key[0]!r} occurrence anchors differ from ingestion"
                                            )
                            elif method not in {"declared_candidates", "bounded_manual_scope"}:
                                errors.append(
                                    f"non-PDF terminology source {source_id} requires a declared candidate inventory or bounded manual scope"
                                )

                        for candidate in inventory_candidates:
                            candidate_id = candidate.get("id")
                            source_id = candidate.get("source_id")
                            candidate_text = candidate.get("candidate")
                            if source_id not in document_source_ids:
                                errors.append(
                                    f"terminology candidate {candidate_id} references unknown document source {source_id}"
                                )
                            occurrence_anchor_ids = {
                                value for value in candidate.get("occurrence_anchor_ids", [])
                                if isinstance(value, str)
                            }
                            occurrence_positions: dict[str, int] = {}
                            for anchor_id in occurrence_anchor_ids:
                                anchor = source_binding_context["anchor_by_id"].get(anchor_id)
                                if not isinstance(anchor, dict):
                                    errors.append(
                                        f"terminology candidate {candidate_id} references unknown occurrence anchor {anchor_id}"
                                    )
                                elif anchor.get("source_id") != source_id or anchor.get("kind") == "scope":
                                    errors.append(
                                        f"terminology candidate {candidate_id} occurrence anchor {anchor_id} is not a precise anchor from {source_id}"
                                    )
                                else:
                                    content = source_binding_context["anchor_content"].get(anchor_id)
                                    normalized_candidate = normalize_source_transcription(
                                        str(candidate_text or "")
                                    )
                                    normalized_content = normalize_source_transcription(
                                        content if isinstance(content, str) else ""
                                    )
                                    if not normalized_candidate or normalized_candidate not in normalized_content:
                                        errors.append(
                                            f"terminology candidate {candidate_id} is absent from occurrence anchor {anchor_id}"
                                        )
                                    if isinstance(content, str) and isinstance(candidate_text, str):
                                        local_offset = content.find(candidate_text)
                                        start_char = anchor.get("start_char")
                                        if isinstance(start_char, int) and not isinstance(start_char, bool):
                                            occurrence_positions[anchor_id] = start_char + max(local_offset, 0)
                            disposition = candidate.get("disposition")
                            term_id = candidate.get("term_id")
                            first_use_anchor_id = candidate.get("first_use_anchor_id")
                            definition_anchor_ids = {
                                value for value in candidate.get("definition_anchor_ids", [])
                                if isinstance(value, str)
                            }
                            absence_anchor_ids = {
                                value
                                for value in candidate.get("definition_absence_anchor_ids", [])
                                if isinstance(value, str)
                            }
                            if disposition == "mapped_term":
                                term = terms_by_id.get(term_id)
                                if not isinstance(term, dict):
                                    errors.append(
                                        f"terminology candidate {candidate_id} maps to unknown term {term_id}"
                                    )
                                    continue
                                mapped_term_ids.add(str(term_id))
                                term_names = {
                                    normalize_source_transcription(value)
                                    for value in [term.get("label"), *(
                                        term.get("variants")
                                        if isinstance(term.get("variants"), list) else []
                                    )]
                                    if isinstance(value, str) and value.strip()
                                }
                                if normalize_source_transcription(str(candidate_text or "")) not in term_names:
                                    errors.append(
                                        f"terminology candidate {candidate_id} does not match the label or a declared variant of term {term_id}"
                                    )
                                if first_use_anchor_id != term.get("first_use_anchor_id"):
                                    errors.append(
                                        f"terminology candidate {candidate_id} first-use anchor differs from term {term_id}"
                                    )
                                if first_use_anchor_id not in occurrence_anchor_ids:
                                    errors.append(
                                        f"terminology candidate {candidate_id} first-use anchor is absent from its occurrences"
                                    )
                                elif occurrence_positions and first_use_anchor_id in occurrence_positions:
                                    earliest_position = min(occurrence_positions.values())
                                    if occurrence_positions[first_use_anchor_id] != earliest_position:
                                        errors.append(
                                            f"terminology candidate {candidate_id} first-use anchor is not its earliest declared occurrence"
                                        )
                                term_support = term_support_by_id.get(str(term_id), {})
                                if term.get("status") in {"defined_clear", "defined_remote"}:
                                    if not definition_anchor_ids:
                                        errors.append(
                                            f"defined term {term_id} requires at least one definition anchor"
                                        )
                                    if absence_anchor_ids:
                                        errors.append(
                                            f"defined term {term_id} cannot declare definition absence"
                                        )
                                    if not definition_anchor_ids.issubset(
                                        term_support.get("direct_anchor_ids", set())
                                    ):
                                        errors.append(
                                            f"term {term_id} evidence_refs do not cover its definition anchors"
                                        )
                                elif term.get("status") == "undefined":
                                    if definition_anchor_ids:
                                        errors.append(
                                            f"undefined term {term_id} cannot declare definition anchors"
                                        )
                                    if not absence_anchor_ids or any(
                                        not isinstance(
                                            source_binding_context["anchor_by_id"].get(anchor_id),
                                            dict,
                                        )
                                        or source_binding_context["anchor_by_id"][anchor_id].get(
                                            "kind"
                                        )
                                        != "scope"
                                        for anchor_id in absence_anchor_ids
                                    ):
                                        errors.append(
                                            f"undefined term {term_id} requires a scope-anchored definition absence"
                                        )
                                    if not absence_anchor_ids.issubset(
                                        term_support.get("absence_anchor_ids", set())
                                    ):
                                        errors.append(
                                            f"term {term_id} evidence_refs do not cover its definition-absence anchors"
                                        )
                                for anchor_id in definition_anchor_ids:
                                    anchor = source_binding_context["anchor_by_id"].get(anchor_id)
                                    if (
                                        not isinstance(anchor, dict)
                                        or anchor.get("kind") == "scope"
                                        or anchor.get("source_id") != source_id
                                    ):
                                        errors.append(
                                            f"term {term_id} definition anchor {anchor_id} is not a precise anchor from {source_id}"
                                        )
                                for anchor_id in absence_anchor_ids:
                                    anchor = source_binding_context["anchor_by_id"].get(anchor_id)
                                    if (
                                        not isinstance(anchor, dict)
                                        or anchor.get("kind") != "scope"
                                        or anchor.get("source_id") != source_id
                                    ):
                                        errors.append(
                                            f"term {term_id} definition-absence anchor {anchor_id} is not a scope anchor from {source_id}"
                                        )
                            else:
                                if term_id is not None:
                                    errors.append(
                                        f"terminology candidate {candidate_id} disposition {disposition} cannot map a term_id"
                                    )
                                if disposition in {"standard_unambiguous_notation", "non_load_bearing"}:
                                    if first_use_anchor_id not in occurrence_anchor_ids:
                                        errors.append(
                                            f"terminology candidate {candidate_id} requires a precise first-use occurrence"
                                        )
                                    elif occurrence_positions and first_use_anchor_id in occurrence_positions:
                                        if occurrence_positions[first_use_anchor_id] != min(occurrence_positions.values()):
                                            errors.append(
                                                f"terminology candidate {candidate_id} first-use anchor is not its earliest declared occurrence"
                                            )
                                elif first_use_anchor_id is not None or definition_anchor_ids or absence_anchor_ids:
                                    errors.append(
                                        f"terminology candidate {candidate_id} disposition {disposition} cannot claim definition anchors"
                                    )

                        unmapped_terms = sorted(set(terms_by_id) - mapped_term_ids)
                        if unmapped_terms:
                            errors.append(
                                "term rows missing from the adjudicated candidate inventory: "
                                + ", ".join(unmapped_terms)
                            )
                for structured_name in ("central_argument_assessment", "writing_audit"):
                    structured = claims.get(structured_name, {})
                    if isinstance(structured, dict):
                        for finding_id in structured.get("finding_ids", []):
                            if finding_id not in active_by_id:
                                errors.append(f"{structured_name} references unknown or inactive finding {finding_id}")

                if claims.get("schema_version") == "0.2":
                    argument = claims.get("argument_audit", {})
                    source_manifest_for_claims = load_json(
                        review_dir / "evidence" / "source-manifest.json", errors
                    )
                    computations_for_claims = load_json(
                        review_dir / "evidence" / "computations.json", errors
                    )
                    external_for_claims = load_json(
                        review_dir / "evidence" / "external-sources.json", errors
                    )
                    external_rows_for_claims = (
                        external_for_claims.get("sources", [])
                        if isinstance(external_for_claims, dict)
                        and isinstance(external_for_claims.get("sources"), list)
                        else []
                    )
                    external_support_state: dict[str, str] = {}
                    external_support_findings: dict[str, set[str]] = {}
                    for external_row in external_rows_for_claims:
                        if not isinstance(external_row, dict):
                            continue
                        raw_support_records = external_row.get("support_records")
                        support_records = (
                            raw_support_records if isinstance(raw_support_records, list) else []
                        )
                        for support_record in support_records:
                            if not isinstance(support_record, dict) or not isinstance(
                                support_record.get("id"), str
                            ):
                                continue
                            support_id = support_record["id"]
                            if isinstance(support_record.get("support_state"), str):
                                external_support_state[support_id] = support_record["support_state"]
                            raw_linked_findings = support_record.get("finding_ids")
                            external_support_findings[support_id] = {
                                value for value in raw_linked_findings if isinstance(value, str)
                            } if isinstance(raw_linked_findings, list) else set()
                    known_argument_refs: dict[str, set[str]] = {
                        "anchor": {
                            row.get("id")
                            for row in (
                                source_manifest_for_claims.get("anchors", [])
                                if isinstance(source_manifest_for_claims, dict)
                                else []
                            )
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                        },
                        "computation": {
                            row.get("id")
                            for row in (
                                computations_for_claims.get("computations", [])
                                if isinstance(computations_for_claims, dict)
                                else []
                            )
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                        },
                        "external_source": {
                            row.get("id")
                            for row in external_rows_for_claims
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                        },
                        "external_support": set(external_support_state),
                        "finding_evidence": set(),
                    }
                    argument_anchor_kinds = {
                        row.get("id"): row.get("kind")
                        for row in (
                            source_manifest_for_claims.get("anchors", [])
                            if isinstance(source_manifest_for_claims, dict)
                            else []
                        )
                        if isinstance(row, dict) and isinstance(row.get("id"), str)
                    }
                    evidence_owner: dict[str, str] = {}
                    evidence_support_refs: dict[str, set[tuple[str, str]]] = {}
                    absence_evidence_ids: set[str] = set()
                    for finding in active:
                        if strict_burden_coverage and finding.get("verification") != "passed":
                            continue
                        finding_id = finding.get("id")
                        for evidence_row in finding.get("evidence", []):
                            if not isinstance(evidence_row, dict):
                                continue
                            evidence_id = evidence_row.get("id")
                            if not isinstance(evidence_id, str):
                                continue
                            known_argument_refs["finding_evidence"].add(evidence_id)
                            evidence_owner[evidence_id] = finding_id
                            support = {("finding_evidence", evidence_id)}
                            anchor_id = evidence_row.get("anchor_id")
                            if isinstance(anchor_id, str):
                                support.add(("anchor", anchor_id))
                            for component_anchor in evidence_row.get("anchor_ids", []):
                                if isinstance(component_anchor, str):
                                    support.add(("anchor", component_anchor))
                            computation_id = evidence_row.get("computation_id")
                            if isinstance(computation_id, str):
                                support.add(("computation", computation_id))
                            support_record_id = evidence_row.get("support_record_id")
                            if isinstance(support_record_id, str):
                                support.add(("external_support", support_record_id))
                            elif not strict_burden_coverage:
                                external_id = evidence_row.get("source_record_id")
                                if isinstance(external_id, str):
                                    support.add(("external_source", external_id))
                            evidence_support_refs[evidence_id] = support
                            if evidence_row.get("type") == "absence_scope":
                                absence_evidence_ids.add(evidence_id)
                    claim_anchor_ids: dict[str, set[str]] = {}
                    for claim_id, family in families.items():
                        anchors = {
                            anchor_id for anchor_id in family.get("anchor_ids", [])
                            if isinstance(anchor_id, str)
                        }
                        claim_anchor_ids[claim_id] = anchors
                        for anchor_id in anchors:
                            if anchor_id not in known_argument_refs["anchor"]:
                                errors.append(
                                    f"claim family {claim_id} references unknown canonical anchor {anchor_id}"
                                )
                            elif argument_anchor_kinds.get(anchor_id) == "scope":
                                errors.append(
                                    f"claim family {claim_id} must use a precise claim anchor, not scope anchor {anchor_id}"
                                )
                    required_argument_dimensions = {
                        "economic-argument-chain",
                        "intervention-comparison-content",
                        "cross-result-coherence",
                        "evidence-object-completeness",
                        "magnitude-plausibility",
                        "population-claim-transport",
                    }
                    missing_dimensions = sorted(
                        required_argument_dimensions - set(coverage_dimensions_by_id)
                    )
                    if missing_dimensions:
                        errors.append(
                            "claims-audit v0.2 coverage is missing argument dimensions: "
                            + ", ".join(missing_dimensions)
                        )
                    for dimension_id in {
                        "economic-argument-chain", "evidence-object-completeness"
                    }:
                        if coverage_dimensions_by_id.get(dimension_id, {}).get("status") == "not_applicable":
                            errors.append(
                                f"claims-audit v0.2 coverage dimension {dimension_id} cannot be not_applicable"
                            )

                    def expand_argument_refs(
                        raw_refs: Any,
                        *,
                        label: str,
                    ) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
                        refs: set[tuple[str, str]] = set()
                        expanded: set[tuple[str, str]] = set()
                        if not isinstance(raw_refs, list):
                            return refs, expanded
                        for ref in raw_refs:
                            if not isinstance(ref, dict):
                                continue
                            ref_kind, ref_id = ref.get("kind"), ref.get("id")
                            if not isinstance(ref_kind, str) or not isinstance(ref_id, str):
                                continue
                            ref_tuple = (ref_kind, ref_id)
                            refs.add(ref_tuple)
                            expanded.add(ref_tuple)
                            if strict_burden_coverage and ref_kind == "external_source":
                                errors.append(
                                    f"{label} must cite an external_support proposition record, not source container {ref_id}"
                                )
                            if ref_id not in known_argument_refs.get(ref_kind, set()):
                                errors.append(
                                    f"{label} references unknown canonical evidence {ref_kind}:{ref_id}"
                                )
                            if ref_kind == "finding_evidence":
                                expanded.update(evidence_support_refs.get(ref_id, set()))
                        return refs, expanded

                    def validate_argument_boundary(
                        boundary: Any,
                        *,
                        label: str,
                        require_missing_input: bool,
                    ) -> None:
                        if not isinstance(boundary, dict):
                            errors.append(f"{label} requires a structured assessment boundary")
                            return
                        boundary_refs, expanded_boundary_refs = expand_argument_refs(
                            boundary.get("evidence_refs", []), label=f"{label} boundary"
                        )
                        has_scope_evidence = any(
                            ref_kind == "anchor"
                            and argument_anchor_kinds.get(ref_id) == "scope"
                            for ref_kind, ref_id in expanded_boundary_refs
                        ) or any(
                            ref_kind == "finding_evidence"
                            and ref_id in absence_evidence_ids
                            for ref_kind, ref_id in boundary_refs
                        )
                        if not has_scope_evidence:
                            errors.append(
                                f"{label} boundary requires a canonical scope anchor or absence record"
                            )
                        for field in ("checked_scope", "reason"):
                            if generic_analytical_text(boundary.get(field)):
                                errors.append(
                                    f"{label} boundary field {field} needs a paper-specific scope or reason"
                                )
                        if require_missing_input:
                            if not isinstance(boundary.get("missing_input"), str):
                                errors.append(f"{label} requires a concrete missing_input")
                            if not isinstance(boundary.get("decisive_evidence_needed"), str):
                                errors.append(f"{label} requires decisive_evidence_needed")

                    def validate_argument_rows(
                        rows: Any,
                        *,
                        kind: str,
                        adverse: set[str],
                        clean: set[str],
                        dimension_id: str,
                        text_fields: tuple[str, ...] = (),
                        collection_status: str | None = None,
                    ) -> set[str]:
                        if not isinstance(rows, list):
                            return set()
                        ids = [row.get("id") for row in rows if isinstance(row, dict) and row.get("id")]
                        duplicates = sorted(
                            item for item, count in Counter(ids).items() if count > 1
                        )
                        if duplicates:
                            errors.append(f"duplicate {kind} IDs: {', '.join(duplicates)}")
                        mapped_union: set[str] = set()
                        bounded_rows = False
                        for row in rows:
                            if not isinstance(row, dict):
                                continue
                            row_id = row.get("id")
                            raw_row_units = row.get("coverage_unit_ids")
                            row_units = raw_row_units if isinstance(raw_row_units, list) else []
                            for unit_id in row_units:
                                if unit_id not in coverage_unit_ids:
                                    errors.append(
                                        f"{kind} {row_id} references unknown coverage unit {unit_id}"
                                    )
                            raw_row_claim_ids = row.get(
                                "headline_claim_ids", row.get("claim_ids", [])
                            )
                            row_claim_ids = (
                                raw_row_claim_ids if isinstance(raw_row_claim_ids, list) else []
                            )
                            row_claim_set = set(row_claim_ids)
                            for claim_id in row_claim_ids:
                                if claim_id not in families:
                                    errors.append(
                                        f"{kind} {row_id} references unknown claim family {claim_id}"
                                    )
                            raw_mapped = row.get("finding_ids")
                            mapped = raw_mapped if isinstance(raw_mapped, list) else []
                            mapped_union.update(mapped)
                            active_mapped: list[dict[str, Any]] = []
                            for finding_id in mapped:
                                finding = active_by_id.get(finding_id)
                                if finding is None:
                                    errors.append(
                                        f"{kind} {row_id} references unknown or inactive finding {finding_id}"
                                    )
                                    continue
                                active_mapped.append(finding)
                                finding_claims = set(finding.get("claim_ids", []))
                                if row_claim_set and not row_claim_set.intersection(finding_claims):
                                    errors.append(
                                        f"{kind} {row_id} maps finding {finding_id} without an overlapping claim family"
                                    )
                            if row.get("status") in adverse and not active_mapped:
                                errors.append(
                                    f"adverse {kind} state {row_id} must map to an active finding"
                                )
                            if row.get("status") in clean and active_mapped:
                                errors.append(
                                    f"clean {kind} state {row_id} must not map to an active finding"
                                )
                            refs, expanded_refs = expand_argument_refs(
                                row.get("evidence_refs", []), label=f"{kind} {row_id}"
                            )
                            row_status = row.get("status")
                            for ref_kind, ref_id in refs:
                                if ref_kind != "external_support":
                                    continue
                                support_state = external_support_state.get(ref_id)
                                linked_external_findings = external_support_findings.get(
                                    ref_id, set()
                                )
                                if row_status in clean and support_state != "supported":
                                    errors.append(
                                        f"clean {kind} {row_id} cannot rely on external support state {support_state!r}"
                                    )
                                if row_status in clean and linked_external_findings:
                                    errors.append(
                                        f"clean {kind} {row_id} cannot rely on adverse external support {ref_id}"
                                    )
                                elif row_status in adverse and support_state == "inconclusive":
                                    errors.append(
                                        f"adverse {kind} {row_id} cannot rely on inconclusive external support {ref_id}"
                                    )
                                if mapped and not set(mapped).issubset(linked_external_findings):
                                    errors.append(
                                        f"{kind} {row_id} external support {ref_id} lacks reciprocal mapped findings"
                                    )
                            for claim_id in row_claim_set:
                                anchors = claim_anchor_ids.get(claim_id, set())
                                if anchors and not any(
                                    ("anchor", anchor_id) in expanded_refs
                                    for anchor_id in anchors
                                ):
                                    errors.append(
                                        f"{kind} {row_id} evidence is not anchored to claim family {claim_id}"
                                    )
                            for finding_id in mapped:
                                owned_support: set[tuple[str, str]] = set()
                                for evidence_id, owner in evidence_owner.items():
                                    if owner == finding_id:
                                        owned_support.update(evidence_support_refs.get(evidence_id, set()))
                                for support_id, linked_findings in external_support_findings.items():
                                    if finding_id in linked_findings:
                                        owned_support.add(("external_support", support_id))
                                if finding_id in active_by_id and refs.isdisjoint(owned_support):
                                    errors.append(
                                        f"{kind} {row_id} evidence does not support mapped finding {finding_id}"
                                    )
                            if row.get("status") == "bounded":
                                bounded_rows = True
                                validate_argument_boundary(
                                    row.get("boundary"),
                                    label=f"bounded {kind} {row_id}",
                                    require_missing_input=True,
                                )
                            for field in text_fields:
                                value = row.get(field)
                                if generic_analytical_text(value):
                                    errors.append(
                                        f"{kind} {row_id} field {field} needs paper-specific content, not audit meta-prose"
                                    )
                        coverage_row = coverage_dimensions_by_id.get(dimension_id, {})
                        if bounded_rows and coverage_row.get("status") != "bounded":
                            errors.append(
                                f"bounded {kind} row requires bounded coverage dimension {dimension_id}"
                            )
                        if bounded_rows and collection_status is not None and collection_status != "bounded":
                            errors.append(
                                f"bounded {kind} row requires a bounded collection status"
                            )
                        if mapped_union != set(coverage_row.get("finding_ids", [])):
                            errors.append(
                                f"{kind} finding links do not match coverage dimension {dimension_id}"
                            )
                        return mapped_union

                    if isinstance(argument, dict):
                        economic_links = argument.get("economic_links", [])
                        validate_argument_rows(
                            economic_links,
                            kind="economic argument link",
                            adverse={"partially_supported", "unsupported"},
                            clean={"convincing"},
                            dimension_id="economic-argument-chain",
                            text_fields=(
                                "warrant", "alternative_assessment",
                                "discriminating_evidence", "contribution_after_narrowing",
                            ),
                        )
                        adverse_economic_finding_ids = {
                            finding_id
                            for row in economic_links if isinstance(row, dict)
                            and row.get("status") in {"partially_supported", "unsupported"}
                            for finding_id in row.get("finding_ids", [])
                            if finding_id in active_by_id
                        }
                        adverse_headline_argument_finding_ids = set(
                            adverse_economic_finding_ids
                        )
                        bounded_headline_argument = any(
                            isinstance(row, dict) and row.get("status") == "bounded"
                            for row in economic_links
                        )
                        linked_headlines = {
                            claim_id
                            for row in economic_links if isinstance(row, dict)
                            for claim_id in row.get("headline_claim_ids", [])
                        }
                        if linked_headlines != expected_headline_ids:
                            missing = sorted(expected_headline_ids - linked_headlines)
                            extra = sorted(linked_headlines - expected_headline_ids)
                            if missing:
                                errors.append(
                                    "economic argument audit omits headline claims: "
                                    + ", ".join(missing)
                                )
                            if extra:
                                errors.append(
                                    "economic argument audit includes non-headline claims: "
                                    + ", ".join(extra)
                                )

                        collection_specs = (
                            (
                                "comparison_protocols",
                                "comparison protocol",
                                {"attribution_not_isolated", "reactive_or_primed"},
                                {"clean"},
                                "intervention-comparison-content",
                                ("supported_interpretation",),
                            ),
                            (
                                "result_relationships",
                                "result relationship",
                                {"unexplained_tension", "contradiction"},
                                {"coherent", "explained_difference"},
                                "cross-result-coherence",
                                ("asserted_relationship", "observed_relationship"),
                            ),
                            (
                                "magnitude_assessments",
                                "magnitude assessment",
                                {"missing_context", "internally_infeasible"},
                                {"interpretable"},
                                "magnitude-plausibility",
                                ("comparison_or_denominator", "benchmark_or_baseline", "interpretation"),
                            ),
                            (
                                "transport_assessments",
                                "transport assessment",
                                {"unsupported"},
                                {"supported"},
                                "population-claim-transport",
                                ("transport_basis", "adjustment_or_validation", "supported_scope"),
                            ),
                        )
                        for key, kind, adverse, clean, dimension_id, text_fields in collection_specs:
                            collection = argument.get(key, {})
                            entries = collection.get("entries", []) if isinstance(collection, dict) else []
                            collection_status = collection.get("status") if isinstance(collection, dict) else None
                            coverage_status = coverage_dimensions_by_id.get(dimension_id, {}).get("status")
                            if collection_status in {"bounded", "not_applicable"} and coverage_status != collection_status:
                                errors.append(
                                    f"{kind} {collection_status} state must match coverage dimension {dimension_id}"
                                )
                            if collection_status == "complete" and coverage_status == "not_applicable":
                                errors.append(
                                    f"complete {kind} cannot have a not_applicable coverage dimension {dimension_id}"
                                )
                            boundary = collection.get("boundary") if isinstance(collection, dict) else None
                            if collection_status in {"bounded", "not_applicable"}:
                                validate_argument_boundary(
                                    boundary,
                                    label=f"{kind} {collection_status}",
                                    require_missing_input=(collection_status == "bounded" and not entries),
                                )
                                if isinstance(boundary, dict):
                                    basis = boundary.get("status_basis")
                                    if collection_status == "not_applicable" and basis not in {
                                        "absent_object_or_trigger", "outside_claim_scope"
                                    }:
                                        errors.append(
                                            f"not_applicable {kind} requires an absent-object or outside-claim-scope basis"
                                        )
                            validate_argument_rows(
                                entries,
                                kind=kind,
                                adverse=adverse,
                                clean=clean,
                                dimension_id=dimension_id,
                                text_fields=text_fields,
                                collection_status=collection_status,
                            )
                            for entry in entries:
                                if (
                                    isinstance(entry, dict)
                                    and entry.get("status") == "bounded"
                                    and expected_headline_ids.intersection(entry.get("claim_ids", []))
                                ):
                                    bounded_headline_argument = True
                                if not isinstance(entry, dict) or entry.get("status") not in adverse:
                                    continue
                                row_claims = set(entry.get("claim_ids", []))
                                for finding_id in entry.get("finding_ids", []):
                                    finding = active_by_id.get(finding_id)
                                    finding_claims = (
                                        set(finding.get("claim_ids", []))
                                        if isinstance(finding, dict)
                                        else set()
                                    )
                                    if expected_headline_ids.intersection(
                                        row_claims | finding_claims
                                    ):
                                        adverse_headline_argument_finding_ids.add(
                                            finding_id
                                        )
                            if key == "magnitude_assessments":
                                for entry in entries:
                                    if not isinstance(entry, dict):
                                        continue
                                    computation_id = entry.get("computation_id")
                                    if computation_id is not None and computation_id not in known_argument_refs["computation"]:
                                        errors.append(
                                            f"magnitude assessment {entry.get('id')} references unknown computation {computation_id}"
                                        )
                                    if computation_id is not None and (
                                        "computation", computation_id
                                    ) not in {
                                        (ref.get("kind"), ref.get("id"))
                                        for ref in entry.get("evidence_refs", [])
                                        if isinstance(ref, dict)
                                    }:
                                        errors.append(
                                            f"magnitude assessment {entry.get('id')} computation_id must also appear in evidence_refs"
                                        )

                        evidence_objects = argument.get("evidence_objects", [])
                        validate_argument_rows(
                            evidence_objects,
                            kind="evidence object",
                            adverse={"partially_accounted", "unexplained_omission"},
                            clean={"accounted_for"},
                            dimension_id="evidence-object-completeness",
                            text_fields=("relevance_to_argument", "accounting"),
                        )
                        for row in evidence_objects:
                            if (
                                isinstance(row, dict)
                                and row.get("status") == "bounded"
                                and (
                                    row.get("role") == "headline"
                                    or expected_headline_ids.intersection(row.get("claim_ids", []))
                                )
                            ):
                                bounded_headline_argument = True
                            if (
                                not isinstance(row, dict)
                                or row.get("status") not in {
                                    "partially_accounted", "unexplained_omission"
                                }
                            ):
                                continue
                            for finding_id in row.get("finding_ids", []):
                                finding = active_by_id.get(finding_id)
                                finding_claims = (
                                    set(finding.get("claim_ids", []))
                                    if isinstance(finding, dict)
                                    else set()
                                )
                                if (
                                    row.get("role") == "headline"
                                    or expected_headline_ids.intersection(finding_claims)
                                ):
                                    adverse_headline_argument_finding_ids.add(finding_id)

                        central = claims.get("central_argument_assessment", {})
                        if isinstance(central, dict):
                            central_finding_ids = {
                                finding_id for finding_id in central.get("finding_ids", [])
                                if finding_id in active_by_id
                            }
                            missing_central_findings = sorted(
                                adverse_headline_argument_finding_ids - central_finding_ids
                            )
                            if missing_central_findings:
                                errors.append(
                                    "central_argument_assessment omits adverse headline argument findings: "
                                    + ", ".join(missing_central_findings)
                                )
                            if central.get("status") == "convincing" and central_finding_ids:
                                errors.append(
                                    "convincing central_argument_assessment must not map to active findings"
                                )
                            if central.get("status") == "convincing" and adverse_headline_argument_finding_ids:
                                errors.append(
                                    "convincing central_argument_assessment conflicts with an adverse headline argument finding"
                                )
                            if bounded_headline_argument and central.get("status") != "bounded":
                                errors.append(
                                    "a bounded headline argument audit requires a bounded central_argument_assessment"
                                )
                            if central.get("status") in {"partially_convincing", "not_yet_convincing"} and not central_finding_ids:
                                errors.append(
                                    f"{central.get('status')} central_argument_assessment must map to an active finding"
                                )

        figures_path = review_dir / "evidence/figures.json"
        if run.get("mode") == "full" and figures_path.exists():
            figures = load_json(figures_path, errors)
            if isinstance(figures, dict):
                validate_schema(figures, "figures.schema.json", "evidence/figures.json", errors)
                if figures.get("review_id") != run.get("review_id"):
                    errors.append("figures review_id differs from run.json")
                rows = [row for row in figures.get("figures", []) if isinstance(row, dict)]
                if current_contract:
                    boundary = run.get("assessment_boundary")
                    boundary_figures = boundary.get("figures") if isinstance(boundary, dict) else None
                    no_figures = figures.get("no_figures_confirmed") is True
                    if no_figures and boundary_figures != "not_present":
                        errors.append(
                            "run.json assessment_boundary.figures must be 'not_present' "
                            "when the figure audit confirms that the paper has no figures"
                        )
                    if not no_figures and boundary_figures == "not_present":
                        errors.append(
                            "run.json assessment_boundary.figures cannot be 'not_present' "
                            "when the figure audit contains or expects figures"
                        )
                figure_ids = [row.get("id") for row in rows if row.get("id")]
                duplicate_figure_ids = sorted(item for item, count in Counter(figure_ids).items() if count > 1)
                if duplicate_figure_ids:
                    errors.append(f"duplicate figure IDs: {', '.join(duplicate_figure_ids)}")
                figure_schema_version = figures.get("schema_version")
                no_figures_confirmed = figures.get("no_figures_confirmed") is True
                if strict_v4_audits and rows and figure_schema_version != "0.2":
                    errors.append(
                        "v0.4 full review with figures requires evidence/figures.json schema_version 0.2"
                    )
                if figure_coverage_ids and no_figures_confirmed:
                    errors.append(
                        "figure audit cannot confirm no figures when coverage contains figure units"
                    )
                if figure_schema_version == "0.2":
                    figure_source_media, canonical_pdf_assets = load_exhibit_source_bindings(
                        review_dir, errors, "figure"
                    )
                    mapped_units = [
                        row.get("coverage_unit_id") for row in rows if row.get("coverage_unit_id")
                    ]
                    duplicate_units = sorted(
                        item for item, count in Counter(mapped_units).items() if count > 1
                    )
                    if duplicate_units:
                        errors.append(
                            "figure audit maps coverage units more than once: "
                            + ", ".join(duplicate_units)
                        )
                    mapped_unit_set = set(mapped_units)
                    if mapped_unit_set != figure_coverage_ids:
                        missing = sorted(figure_coverage_ids - mapped_unit_set)
                        extra = sorted(mapped_unit_set - figure_coverage_ids)
                        if missing:
                            errors.append("figure audit omits coverage units: " + ", ".join(missing))
                        if extra:
                            errors.append(
                                "figure audit references non-figure coverage units: "
                                + ", ".join(extra)
                            )
                    if not figure_coverage_ids and figures.get("no_figures_confirmed") is not True:
                        errors.append("figure-free coverage requires no_figures_confirmed=true")
                active_ids = {item.get("id") for item in active}
                rendered_asset_owners: dict[str, tuple[str, str, Any, Any]] = {}
                for row in rows:
                    mapped = row.get("finding_ids", [])
                    for finding_id in mapped:
                        if finding_id not in active_ids:
                            errors.append(f"figure {row.get('id')} references unknown or inactive finding {finding_id}")
                    adverse_row_state = (
                        row.get("visual_status") == "issue"
                        or row.get("caption_text_status") == "issue"
                        or row.get("claim_correspondence_status") == "issue"
                    )
                    checked_clean_row = (
                        row.get("visual_status") == "clear"
                        and row.get("caption_text_status") == "consistent"
                        and row.get("claim_correspondence_status") == "consistent"
                    )
                    row_bounded_state = any(
                        row.get(field) == "bounded"
                        for field in (
                            "visual_status",
                            "caption_text_status",
                            "claim_correspondence_status",
                        )
                    )
                    if adverse_row_state and not mapped:
                        errors.append(f"adverse figure state {row.get('id')} must map to an active finding")
                    if figure_schema_version == "0.2" and checked_clean_row and mapped:
                        errors.append(
                            f"checked-clean figure {row.get('id')} cannot map to an active finding"
                        )
                    if figure_schema_version == "0.2":
                        source_id = row.get("source_id")
                        source_media_type = figure_source_media.get(str(source_id))
                        if source_media_type is None:
                            errors.append(
                                f"figure {row.get('id')} references unknown source {source_id}"
                            )
                        source_pdf_assets = (
                            canonical_pdf_assets.get(str(source_id))
                            if source_media_type == "application/pdf"
                            else None
                        )
                        if source_media_type == "application/pdf" and source_pdf_assets is None:
                            errors.append(
                                f"figure {row.get('id')} cannot bind assets because PDF source "
                                f"{source_id} has no readable canonical ingestion index"
                            )
                        declared_page_values = row.get("pdf_pages", [])
                        declared_pages = {
                            page for page in declared_page_values
                            if type(page) is int
                        } if isinstance(declared_page_values, list) else set()
                        source_locator = row.get("source_locator")
                        if isinstance(source_locator, dict):
                            locator_source_id = source_locator.get("source_id")
                            locator_page_values = source_locator.get("pages", [])
                            locator_pages = {
                                page for page in locator_page_values
                                if type(page) is int
                            } if isinstance(locator_page_values, list) else set()
                            if locator_source_id != source_id:
                                errors.append(
                                    f"figure {row.get('id')} source locator names {locator_source_id} "
                                    f"but the row binds source {source_id}"
                                )
                            if locator_pages != declared_pages:
                                errors.append(
                                    f"figure {row.get('id')} source locator pages "
                                    f"{sorted(locator_pages)} differ from declared pages "
                                    f"{sorted(declared_pages)}"
                                )
                        if source_media_type == "application/pdf" and not declared_pages:
                            errors.append(
                                f"PDF figure {row.get('id')} requires at least one declared PDF page"
                            )
                        full_page_pages: set[int] = set()
                        identity_keys = [
                            key for key in row.get("identity_keys", [])
                            if isinstance(key, str) and key.strip()
                        ]
                        coverage_label = figure_coverage_labels.get(str(row.get("coverage_unit_id")))
                        row_identifier = explicit_figure_identifier(row.get("label"))
                        coverage_identifier = explicit_figure_identifier(coverage_label)
                        if row_identifier and coverage_identifier:
                            labels_agree = row_identifier == coverage_identifier
                        else:
                            labels_agree = bool(coverage_label) and any(
                                identity_key_matches(key, row.get("label"))
                                and identity_key_matches(key, coverage_label)
                                for key in identity_keys
                            )
                        if coverage_label and not labels_agree:
                            errors.append(
                                f"figure {row.get('id')} label is not reconciled with coverage unit "
                                f"{row.get('coverage_unit_id')} through a shared identity key"
                            )
                        has_matched_full_page_identity = False
                        has_bounded_full_page_identity = False
                        identity_mismatch = False
                        identity_bounded = False
                        for asset_index, asset in enumerate(row.get("rendered_assets", [])):
                            if not isinstance(asset, dict):
                                continue
                            asset_label = f"figure {row.get('id')} rendered asset {asset_index + 1}"
                            raw_path = asset.get("path")
                            validated_asset = validate_local_asset_path(
                                review_dir,
                                raw_path,
                                f"{asset_label} path",
                                errors,
                            )
                            page = asset.get("pdf_page")
                            if source_media_type == "application/pdf" and page not in declared_pages:
                                errors.append(
                                    f"{asset_label} page {page} is not declared in the figure row"
                                )
                            if source_media_type != "application/pdf" and (
                                (page is None and declared_pages)
                                or (page is not None and page not in declared_pages)
                            ):
                                errors.append(
                                    f"{asset_label} source-location page {page} is not reconciled with the figure row"
                                )
                            render_type = asset.get("render_type")
                            source_object_id = asset.get("source_object_id")
                            if render_type == "full_page" and isinstance(page, int):
                                full_page_pages.add(page)
                            if source_media_type == "application/pdf":
                                if render_type == "full_page" and source_object_id is not None:
                                    errors.append(
                                        f"{asset_label} full-page render cannot claim a source_object_id"
                                    )
                                if render_type == "crop" and not (
                                    isinstance(source_object_id, str) and source_object_id.strip()
                                ):
                                    errors.append(
                                        f"{asset_label} PDF crop requires its canonical source_object_id"
                                    )
                            elif source_object_id is not None:
                                errors.append(
                                    f"{asset_label} non-PDF asset cannot claim a PDF source_object_id"
                                )
                            if validated_asset is not None and isinstance(raw_path, str):
                                canonical_path, asset_bytes = validated_asset
                                asset_record = (
                                    str(row.get("id")),
                                    str(asset.get("render_type")),
                                    asset.get("pdf_page"),
                                    asset.get("sha256"),
                                )
                                previous_owner = rendered_asset_owners.get(canonical_path)
                                shared_full_page = (
                                    previous_owner is not None
                                    and previous_owner[1] == "full_page"
                                    and asset_record[1] == "full_page"
                                    and previous_owner[2:] == asset_record[2:]
                                )
                                if previous_owner is not None and not shared_full_page:
                                    errors.append(
                                        f"figure rendered asset is assigned to multiple rows: {canonical_path} "
                                        f"({previous_owner[0]}, {row.get('id')})"
                                    )
                                elif previous_owner is None:
                                    rendered_asset_owners[canonical_path] = asset_record
                                observed_hash = sha256_bytes(asset_bytes)
                                expected_hash = asset.get("sha256")
                                if observed_hash != expected_hash:
                                    errors.append(
                                        f"{asset_label} SHA-256 does not match the retained image"
                                    )
                                if not has_render_signature(raw_path, asset_bytes):
                                    errors.append(
                                        f"{asset_label} does not have a valid supported image signature"
                                    )
                                elif decode_error := render_decode_error(raw_path, asset_bytes):
                                    errors.append(f"{asset_label} {decode_error}")
                                if source_pdf_assets is not None and render_type == "full_page":
                                    expected = source_pdf_assets["full_page"].get(canonical_path)
                                    if expected is None:
                                        errors.append(
                                            f"{asset_label} is not a canonical full_page asset "
                                            f"from PDF ingestion for source {source_id}"
                                        )
                                    else:
                                        expected_page, expected_hash = expected
                                        if page != expected_page:
                                            errors.append(
                                                f"{asset_label} page {page} differs from canonical "
                                                f"PDF ingestion page {expected_page}"
                                            )
                                        if asset.get("sha256") != expected_hash:
                                            errors.append(
                                                f"{asset_label} SHA-256 differs from canonical "
                                                "PDF ingestion"
                                            )
                                elif source_pdf_assets is not None and render_type == "crop":
                                    expected_object = source_pdf_assets["crop"].get(
                                        str(source_object_id)
                                    )
                                    if expected_object is None:
                                        errors.append(
                                            f"{asset_label} source_object_id {source_object_id!r} "
                                            f"is not a canonical PDF-ingestion figure object for source {source_id}"
                                        )
                                    else:
                                        expected_path, expected_page, expected_hash = expected_object
                                        if canonical_path != expected_path:
                                            errors.append(
                                                f"{asset_label} path does not match canonical figure object "
                                                f"{source_object_id}"
                                            )
                                        if page != expected_page:
                                            errors.append(
                                                f"{asset_label} page {page} differs from canonical "
                                                f"figure object {source_object_id} page {expected_page}"
                                            )
                                        if asset.get("sha256") != expected_hash:
                                            errors.append(
                                                f"{asset_label} SHA-256 differs from canonical "
                                                f"figure object {source_object_id}"
                                            )
                            identity = asset.get("visible_identity", {})
                            if not isinstance(identity, dict):
                                continue
                            identity_status = identity.get("status")
                            if identity_status == "mismatch":
                                identity_mismatch = True
                            elif identity_status == "bounded":
                                identity_bounded = True
                            identity_matches_row = any(
                                identity_key_matches(key, identity.get("text"))
                                for key in identity_keys
                            )
                            if identity_status == "matched" and not identity_matches_row:
                                errors.append(
                                    f"{asset_label} matched visible identity is not linked to "
                                    "the figure row's identity_keys"
                                )
                            if (
                                asset.get("render_type") == "full_page"
                                and identity_status == "matched"
                                and identity_matches_row
                            ):
                                has_matched_full_page_identity = True
                            if (
                                asset.get("render_type") == "full_page"
                                and identity_status == "bounded"
                            ):
                                has_bounded_full_page_identity = True
                        if full_page_pages != declared_pages:
                            missing_pages = sorted(declared_pages - full_page_pages)
                            extra_pages = sorted(full_page_pages - declared_pages)
                            if missing_pages:
                                errors.append(
                                    f"figure {row.get('id')} lacks full-page assets for pages: "
                                    + ", ".join(str(page) for page in missing_pages)
                                )
                            if extra_pages:
                                errors.append(
                                    f"figure {row.get('id')} has full-page assets outside declared pages: "
                                    + ", ".join(str(page) for page in extra_pages)
                                )
                        if not (
                            has_matched_full_page_identity
                            or has_bounded_full_page_identity
                        ):
                            errors.append(
                                f"figure {row.get('id')} lacks a matched or explicitly bounded "
                                "full-page visible identity linked to identity_keys"
                            )
                        if identity_mismatch and not mapped:
                            errors.append(
                                f"mismatched figure asset identity for {row.get('id')} must map "
                                "to an active finding"
                            )
                        if identity_mismatch and row.get("visual_status") != "issue":
                            errors.append(
                                f"figure {row.get('id')} with a mismatched asset identity must have "
                                "visual_status='issue'"
                            )
                        if identity_bounded and row.get("visual_status") != "bounded":
                            errors.append(
                                f"figure {row.get('id')} with a bounded asset identity must have "
                                "visual_status='bounded'"
                            )
                        bounded_state = row_bounded_state or identity_bounded
                        assessment_boundary = row.get("assessment_boundary")
                        if bounded_state and not isinstance(assessment_boundary, dict):
                            errors.append(
                                f"bounded figure {row.get('id')} requires a structured assessment_boundary"
                            )
                        if not bounded_state and assessment_boundary is not None:
                            errors.append(
                                f"unbounded figure {row.get('id')} must set assessment_boundary to null"
                            )
                        coverage_status = figure_coverage_statuses.get(
                            str(row.get("coverage_unit_id"))
                        )
                        if bounded_state and not mapped and coverage_status != "bounded":
                            errors.append(
                                f"bounded figure {row.get('id')} without an author-facing finding "
                                "must map to a bounded coverage unit"
                            )
                    else:
                        for extraction_path in row.get("extraction_paths", []):
                            validate_local_asset_path(
                                review_dir,
                                extraction_path,
                                f"figure {row.get('id')} extraction path",
                                errors,
                            )
                for finding in active:
                    finding_id = finding.get("id")
                    for item in finding.get("evidence", []):
                        if not isinstance(item, dict) or item.get("type") != "figure":
                            continue
                        exhibit = item.get("locator", {}).get("exhibit") if isinstance(item.get("locator"), dict) else None
                        target = normalized_exhibit_label("figure", exhibit)
                        matches = [
                            row for row in rows
                            if (
                                normalized_exhibit_label("figure", row.get("label")) == target
                                or normalized_exhibit_label("figure", row.get("label")).startswith(target + ":")
                            )
                        ]
                        if not matches:
                            errors.append(f"figure evidence for {finding_id} has no matching figure-audit row: {exhibit}")
                        elif not any(finding_id in row.get("finding_ids", []) for row in matches):
                            errors.append(f"figure evidence for {finding_id} is not mapped back from figure audit: {exhibit}")

        tables_path = review_dir / "evidence/tables.json"
        if run.get("mode") == "full" and tables_path.exists():
            tables = load_json(tables_path, errors)
            if isinstance(tables, dict):
                validate_schema(tables, "tables.schema.json", "evidence/tables.json", errors)
                if tables.get("review_id") != run.get("review_id"):
                    errors.append("tables review_id differs from run.json")
                rows = [row for row in tables.get("tables", []) if isinstance(row, dict)]
                table_ids = [row.get("id") for row in rows if row.get("id")]
                duplicate_table_ids = sorted(item for item, count in Counter(table_ids).items() if count > 1)
                if duplicate_table_ids:
                    errors.append(f"duplicate table IDs: {', '.join(duplicate_table_ids)}")
                table_schema_version = tables.get("schema_version")
                if strict_v4_audits and rows and table_schema_version != "0.2":
                    errors.append(
                        "v0.4 full review with tables requires evidence/tables.json schema_version 0.2"
                    )
                table_source_media: dict[str, str] = {}
                canonical_table_pdf_assets: dict[
                    str, dict[str, dict[str, tuple[Any, ...]]]
                ] = {}
                if table_schema_version == "0.2":
                    table_source_media, canonical_table_pdf_assets = load_exhibit_source_bindings(
                        review_dir, errors, "table"
                    )
                mapped_coverage_ids = [row.get("coverage_unit_id") for row in rows if row.get("coverage_unit_id")]
                duplicate_table_units = sorted(
                    item for item, count in Counter(mapped_coverage_ids).items() if count > 1
                )
                if duplicate_table_units:
                    errors.append(
                        "table audit maps coverage units more than once: " + ", ".join(duplicate_table_units)
                    )
                mapped_table_units = set(mapped_coverage_ids)
                if mapped_table_units != table_coverage_ids:
                    missing = sorted(table_coverage_ids - mapped_table_units)
                    extra = sorted(mapped_table_units - table_coverage_ids)
                    if missing:
                        errors.append("table audit omits coverage units: " + ", ".join(missing))
                    if extra:
                        errors.append("table audit references non-table coverage units: " + ", ".join(extra))
                if table_coverage_ids and tables.get("no_tables_confirmed") is True:
                    errors.append("table audit cannot confirm no tables when coverage contains table units")
                if not table_coverage_ids and tables.get("no_tables_confirmed") is not True:
                    errors.append("table-free coverage requires no_tables_confirmed=true")
                active_ids = {item.get("id") for item in active}
                rendered_table_asset_owners: dict[str, tuple[str, str, Any, Any]] = {}
                for row in rows:
                    mapped = row.get("finding_ids", [])
                    for finding_id in mapped:
                        if finding_id not in active_ids:
                            errors.append(f"table {row.get('id')} references unknown or inactive finding {finding_id}")
                    adverse = (
                        row.get("visual_status") == "issue"
                        or row.get("claim_correspondence_status") == "issue"
                        or row.get("extraction_status") == "conflict_unresolved"
                    )
                    if adverse and not mapped:
                        errors.append(f"adverse table state {row.get('id')} must map to an active finding")
                    if row.get("render_status") != "inspected" and row.get("visual_status") != "bounded":
                        errors.append(f"table {row.get('id')} must be rendered and inspected or explicitly bounded")
                    if row.get("extraction_status") == "conflict_unresolved" and run.get("status") == "complete":
                        errors.append(f"complete review cannot leave table extraction conflict unresolved: {row.get('id')}")
                    checks = row.get("checks", {})
                    if isinstance(checks, dict):
                        adverse_checks = [
                            name for name, check in checks.items()
                            if isinstance(check, dict) and check.get("status") == "issue"
                        ]
                        if adverse_checks and not mapped:
                            errors.append(
                                f"adverse table checks for {row.get('id')} must map to an active finding: "
                                + ", ".join(adverse_checks)
                            )
                    if table_schema_version == "0.2":
                        source_id = row.get("source_id")
                        source_media_type = table_source_media.get(str(source_id))
                        if source_media_type is None:
                            errors.append(
                                f"table {row.get('id')} references unknown source {source_id}"
                            )
                        source_pdf_assets = (
                            canonical_table_pdf_assets.get(str(source_id))
                            if source_media_type == "application/pdf"
                            else None
                        )
                        if source_media_type == "application/pdf" and source_pdf_assets is None:
                            errors.append(
                                f"table {row.get('id')} cannot bind assets because PDF source "
                                f"{source_id} has no readable canonical ingestion index"
                            )
                        declared_page_values = row.get("pdf_pages", [])
                        declared_pages = {
                            page for page in declared_page_values if type(page) is int
                        } if isinstance(declared_page_values, list) else set()
                        source_locator = row.get("source_locator")
                        if isinstance(source_locator, dict):
                            locator_source_id = source_locator.get("source_id")
                            locator_page_values = source_locator.get("pages", [])
                            locator_pages = {
                                page for page in locator_page_values if type(page) is int
                            } if isinstance(locator_page_values, list) else set()
                            if locator_source_id != source_id:
                                errors.append(
                                    f"table {row.get('id')} source locator names {locator_source_id} "
                                    f"but the row binds source {source_id}"
                                )
                            if locator_pages != declared_pages:
                                errors.append(
                                    f"table {row.get('id')} source locator pages "
                                    f"{sorted(locator_pages)} differ from declared pages "
                                    f"{sorted(declared_pages)}"
                                )
                        if source_media_type == "application/pdf" and not declared_pages:
                            errors.append(
                                f"PDF table {row.get('id')} requires at least one declared PDF page"
                            )
                        identity_keys = [
                            key for key in row.get("identity_keys", [])
                            if isinstance(key, str) and key.strip()
                        ]
                        coverage_label = table_coverage_labels.get(
                            str(row.get("coverage_unit_id"))
                        )
                        row_identifier = explicit_table_identifier(row.get("label"))
                        coverage_identifier = explicit_table_identifier(coverage_label)
                        if row_identifier and coverage_identifier:
                            labels_agree = row_identifier == coverage_identifier
                        else:
                            labels_agree = bool(coverage_label) and any(
                                table_identity_key_matches(key, row.get("label"))
                                and table_identity_key_matches(key, coverage_label)
                                for key in identity_keys
                            )
                        if coverage_label and not labels_agree:
                            errors.append(
                                f"table {row.get('id')} label is not reconciled with coverage unit "
                                f"{row.get('coverage_unit_id')} through a shared identity key"
                            )
                        full_page_pages: set[int] = set()
                        has_context_identity = False
                        identity_mismatch = False
                        identity_bounded = False
                        for asset_index, asset in enumerate(row.get("rendered_assets", [])):
                            if not isinstance(asset, dict):
                                continue
                            asset_label = f"table {row.get('id')} rendered asset {asset_index + 1}"
                            raw_path = asset.get("path")
                            validated_asset = validate_local_asset_path(
                                review_dir,
                                raw_path,
                                f"{asset_label} path",
                                errors,
                            )
                            page = asset.get("pdf_page")
                            if source_media_type == "application/pdf" and page not in declared_pages:
                                errors.append(
                                    f"{asset_label} page {page} is not declared in the table row"
                                )
                            if source_media_type != "application/pdf" and (
                                (page is None and declared_pages)
                                or (page is not None and page not in declared_pages)
                            ):
                                errors.append(
                                    f"{asset_label} source-location page {page} is not reconciled with the table row"
                                )
                            render_type = asset.get("render_type")
                            source_object_id = asset.get("source_object_id")
                            if render_type == "full_page" and isinstance(page, int):
                                full_page_pages.add(page)
                            if source_media_type == "application/pdf":
                                if render_type == "full_page" and source_object_id is not None:
                                    errors.append(
                                        f"{asset_label} full-page render cannot claim a source_object_id"
                                    )
                                if render_type == "crop" and not (
                                    isinstance(source_object_id, str) and source_object_id.strip()
                                ):
                                    errors.append(
                                        f"{asset_label} PDF crop requires its canonical source_object_id"
                                    )
                            elif source_object_id is not None:
                                errors.append(
                                    f"{asset_label} non-PDF asset cannot claim a PDF source_object_id"
                                )
                            identity = asset.get("visible_identity", {})
                            if isinstance(identity, dict):
                                identity_status = identity.get("status")
                                if identity_status == "mismatch":
                                    identity_mismatch = True
                                elif identity_status == "bounded":
                                    identity_bounded = True
                                identity_matches_row = any(
                                    table_identity_key_matches(key, identity.get("text"))
                                    for key in identity_keys
                                )
                                if identity_status == "matched" and not identity_matches_row:
                                    errors.append(
                                        f"{asset_label} matched visible identity is not linked to "
                                        "the table row's identity_keys"
                                    )
                                context_asset = (
                                    render_type == "full_page"
                                    if source_media_type == "application/pdf"
                                    else True
                                )
                                if context_asset and identity_status in {"matched", "bounded"}:
                                    has_context_identity = True
                            if validated_asset is None or not isinstance(raw_path, str):
                                continue
                            canonical_path, asset_bytes = validated_asset
                            asset_record = (
                                str(row.get("id")),
                                str(render_type),
                                page,
                                asset.get("sha256"),
                            )
                            previous_owner = rendered_table_asset_owners.get(canonical_path)
                            shared_full_page = (
                                previous_owner is not None
                                and previous_owner[1] == "full_page"
                                and asset_record[1] == "full_page"
                                and previous_owner[2:] == asset_record[2:]
                            )
                            if previous_owner is not None and not shared_full_page:
                                errors.append(
                                    f"table rendered asset is assigned to multiple rows: {canonical_path} "
                                    f"({previous_owner[0]}, {row.get('id')})"
                                )
                            elif previous_owner is None:
                                rendered_table_asset_owners[canonical_path] = asset_record
                            if sha256_bytes(asset_bytes) != asset.get("sha256"):
                                errors.append(
                                    f"{asset_label} SHA-256 does not match the retained image"
                                )
                            if not has_render_signature(raw_path, asset_bytes):
                                errors.append(
                                    f"{asset_label} does not have a valid supported image signature"
                                )
                            elif decode_error := render_decode_error(raw_path, asset_bytes):
                                errors.append(f"{asset_label} {decode_error}")
                            if source_pdf_assets is not None and render_type == "full_page":
                                expected = source_pdf_assets["full_page"].get(canonical_path)
                                if expected is None:
                                    errors.append(
                                        f"{asset_label} is not a canonical full_page asset "
                                        f"from PDF ingestion for source {source_id}"
                                    )
                                else:
                                    expected_page, expected_hash = expected
                                    if page != expected_page:
                                        errors.append(
                                            f"{asset_label} page {page} differs from canonical "
                                            f"PDF ingestion page {expected_page}"
                                        )
                                    if asset.get("sha256") != expected_hash:
                                        errors.append(
                                            f"{asset_label} SHA-256 differs from canonical PDF ingestion"
                                        )
                            elif source_pdf_assets is not None and render_type == "crop":
                                expected_object = source_pdf_assets["crop"].get(str(source_object_id))
                                if expected_object is None:
                                    errors.append(
                                        f"{asset_label} source_object_id {source_object_id!r} "
                                        f"is not a canonical PDF-ingestion table object for source {source_id}"
                                    )
                                else:
                                    expected_path, expected_page, expected_hash = expected_object
                                    if canonical_path != expected_path:
                                        errors.append(
                                            f"{asset_label} path does not match canonical table object "
                                            f"{source_object_id}"
                                        )
                                    if page != expected_page:
                                        errors.append(
                                            f"{asset_label} page {page} differs from canonical "
                                            f"table object {source_object_id} page {expected_page}"
                                        )
                                    if asset.get("sha256") != expected_hash:
                                        errors.append(
                                            f"{asset_label} SHA-256 differs from canonical "
                                            f"table object {source_object_id}"
                                        )
                        if source_media_type == "application/pdf" and full_page_pages != declared_pages:
                            missing_pages = sorted(declared_pages - full_page_pages)
                            extra_pages = sorted(full_page_pages - declared_pages)
                            if missing_pages:
                                errors.append(
                                    f"table {row.get('id')} lacks full-page assets for pages: "
                                    + ", ".join(str(page) for page in missing_pages)
                                )
                            if extra_pages:
                                errors.append(
                                    f"table {row.get('id')} has full-page assets outside declared pages: "
                                    + ", ".join(str(page) for page in extra_pages)
                                )
                        if row.get("render_status") == "inspected" and not has_context_identity:
                            errors.append(
                                f"table {row.get('id')} lacks a matched or explicitly bounded "
                                "visible identity on retained source context"
                            )
                        if identity_mismatch and not mapped:
                            errors.append(
                                f"mismatched table asset identity for {row.get('id')} must map "
                                "to an active finding"
                            )
                        if identity_mismatch and row.get("visual_status") != "issue":
                            errors.append(
                                f"table {row.get('id')} with a mismatched asset identity must have "
                                "visual_status='issue'"
                            )
                        if identity_bounded and row.get("visual_status") != "bounded":
                            errors.append(
                                f"table {row.get('id')} with a bounded asset identity must have "
                                "visual_status='bounded'"
                            )
                        bounded_checks = any(
                            isinstance(check, dict) and check.get("status") == "bounded"
                            for check in checks.values()
                        ) if isinstance(checks, dict) else False
                        bounded_state = (
                            row.get("render_status") == "bounded"
                            or row.get("extraction_status") == "bounded"
                            or row.get("visual_status") == "bounded"
                            or row.get("claim_correspondence_status") == "bounded"
                            or bounded_checks
                            or identity_bounded
                        )
                        assessment_boundary = row.get("assessment_boundary")
                        if bounded_state and not isinstance(assessment_boundary, dict):
                            errors.append(
                                f"bounded table {row.get('id')} requires a structured assessment_boundary"
                            )
                        if not bounded_state and assessment_boundary is not None:
                            errors.append(
                                f"unbounded table {row.get('id')} must set assessment_boundary to null"
                            )
                        coverage_status = table_coverage_statuses.get(
                            str(row.get("coverage_unit_id"))
                        )
                        if bounded_state and not mapped and coverage_status != "bounded":
                            errors.append(
                                f"bounded table {row.get('id')} without an author-facing finding "
                                "must map to a bounded coverage unit"
                            )
                    else:
                        for render_path in row.get("render_paths", []):
                            validate_local_asset_path(
                                review_dir,
                                render_path,
                                f"table {row.get('id')} render path",
                                errors,
                            )
                for finding in active:
                    finding_id = finding.get("id")
                    for item in finding.get("evidence", []):
                        if not isinstance(item, dict) or item.get("type") != "table_cell":
                            continue
                        exhibit = item.get("locator", {}).get("exhibit") if isinstance(item.get("locator"), dict) else None
                        target = normalized_exhibit_label("table", exhibit)
                        matches = [
                            row for row in rows
                            if normalized_exhibit_label("table", row.get("label")) == target
                        ]
                        if not matches:
                            errors.append(f"table-cell evidence for {finding_id} has no matching table-audit row: {exhibit}")
                        elif not any(finding_id in row.get("finding_ids", []) for row in matches):
                            errors.append(f"table-cell evidence for {finding_id} is not mapped back from table audit: {exhibit}")
                if run.get("status") == "complete":
                    for row in rows:
                        if row.get("render_status") != "inspected":
                            errors.append(
                                f"complete review requires a saved inspected render for table {row.get('id')}"
                            )

        analytical_path = review_dir / "evidence/analytical-audit.json"
        if run.get("mode") == "full" and analytical_path.exists():
            analytical = load_json(analytical_path, errors)
            if isinstance(analytical, dict):
                analytical_for_computation_audit = analytical
                validate_schema(
                    analytical,
                    "analytical-audit.schema.json",
                    "evidence/analytical-audit.json",
                    errors,
                )
                if strict_v4_audits and analytical.get("schema_version") != "0.2":
                    errors.append(
                        "v0.4 full review requires evidence/analytical-audit.json schema_version 0.2"
                    )
                if analytical.get("review_id") != run.get("review_id"):
                    errors.append("analytical-audit review_id differs from run.json")
                analytical_schema_version = analytical.get("schema_version")
                analytical_anchor_ids: set[str] = set()
                analytical_anchor_by_id: dict[str, dict[str, Any]] = {}
                analytical_anchor_content: dict[str, str] = {}
                analytical_source_by_id: dict[str, dict[str, Any]] = {}
                if analytical_schema_version == "0.2":
                    source_manifest = load_json(
                        review_dir / "evidence" / "source-manifest.json", errors
                    )
                    if isinstance(source_manifest, dict):
                        analytical_source_by_id = {
                            row.get("id"): row
                            for row in source_manifest.get("sources", [])
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                        }
                        analytical_anchor_by_id = {
                            row.get("id"): row
                            for row in source_manifest.get("anchors", [])
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                        }
                        analytical_anchor_ids = set(analytical_anchor_by_id)
                        analytical_source_text: dict[str, str] = {}
                        for source_id, source_row in analytical_source_by_id.items():
                            extraction = source_row.get("extraction")
                            source_path = (
                                extraction.get("path")
                                if isinstance(extraction, dict)
                                else source_row.get("path")
                            )
                            if not isinstance(source_path, str):
                                continue
                            try:
                                analytical_source_text[source_id] = safe_read_bytes(
                                    review_dir, source_path
                                ).decode("utf-8")
                            except (OSError, ValueError, UnicodeError):
                                # The trust-spine validator records the authoritative I/O error.
                                continue
                        for anchor_id, anchor_row in analytical_anchor_by_id.items():
                            source_text = analytical_source_text.get(anchor_row.get("source_id"))
                            start, end = anchor_row.get("start_char"), anchor_row.get("end_char")
                            if (
                                isinstance(source_text, str)
                                and isinstance(start, int)
                                and isinstance(end, int)
                                and 0 <= start < end <= len(source_text)
                            ):
                                analytical_anchor_content[anchor_id] = source_text[start:end]
                scope = analytical.get("scope", {})
                scope_units = set(scope.get("coverage_unit_ids", [])) if isinstance(scope, dict) else set()
                if scope_units != coverage_unit_ids:
                    missing = sorted(coverage_unit_ids - scope_units)
                    extra = sorted(scope_units - coverage_unit_ids)
                    if missing:
                        errors.append("analytical audit scope omits coverage units: " + ", ".join(missing))
                    if extra:
                        errors.append(
                            "analytical audit scope references unknown coverage units: " + ", ".join(extra)
                        )
                domains = [row for row in analytical.get("domains", []) if isinstance(row, dict)]
                expected_domains = {
                    "partition-regime",
                    "measure-algebra",
                    "assumption-implementation",
                    "derived-number",
                    "comparison-harmonization",
                    "timing-test",
                    "availability-exclusivity",
                }
                kinds = [row.get("kind") for row in domains if row.get("kind")]
                duplicates = sorted(item for item, count in Counter(kinds).items() if count > 1)
                if duplicates:
                    errors.append("duplicate analytical-ledger domains: " + ", ".join(duplicates))
                missing_domains = sorted(expected_domains - set(kinds))
                if missing_domains:
                    errors.append("analytical audit is missing domains: " + ", ".join(missing_domains))
                active_ids = {item.get("id") for item in active}
                analytical_known_refs: dict[str, set[str]] = {
                    "anchor": set(analytical_anchor_ids),
                    "finding_evidence": set(),
                    "computation": set(),
                    "external_source": set(),
                }
                analytical_evidence_owner: dict[str, str] = {}
                analytical_evidence_by_id: dict[str, dict[str, Any]] = {}
                analytical_evidence_support: dict[str, set[tuple[str, str]]] = {}
                analytical_absence_evidence: set[str] = set()
                analytical_computation_by_id: dict[str, dict[str, Any]] = {}
                analytical_external_by_id: dict[str, dict[str, Any]] = {}
                if analytical_schema_version == "0.2":
                    computations_for_analytical = computations_for_computation_audit
                    external_for_analytical = load_json(
                        review_dir / "evidence" / "external-sources.json", errors
                    )
                    if isinstance(computations_for_analytical, dict):
                        analytical_computation_by_id = {
                            row.get("id"): row
                            for row in computations_for_analytical.get("computations", [])
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                        }
                        analytical_known_refs["computation"] = set(
                            analytical_computation_by_id
                        )
                    if isinstance(external_for_analytical, dict):
                        analytical_external_by_id = {
                            row.get("id"): row
                            for row in external_for_analytical.get("sources", [])
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                        }
                        analytical_known_refs["external_source"] = set(
                            analytical_external_by_id
                        )
                    for finding in active:
                        finding_id = finding.get("id")
                        for evidence_row in finding.get("evidence", []):
                            if not isinstance(evidence_row, dict):
                                continue
                            evidence_id = evidence_row.get("id")
                            if not isinstance(evidence_id, str):
                                continue
                            analytical_known_refs["finding_evidence"].add(evidence_id)
                            analytical_evidence_owner[evidence_id] = finding_id
                            analytical_evidence_by_id[evidence_id] = evidence_row
                            support = {("finding_evidence", evidence_id)}
                            anchor_id = evidence_row.get("anchor_id")
                            if isinstance(anchor_id, str):
                                support.add(("anchor", anchor_id))
                            for component_anchor in evidence_row.get("anchor_ids", []):
                                if isinstance(component_anchor, str):
                                    support.add(("anchor", component_anchor))
                            computation_id = evidence_row.get("computation_id")
                            if isinstance(computation_id, str):
                                support.add(("computation", computation_id))
                            external_id = evidence_row.get("source_record_id")
                            if isinstance(external_id, str):
                                support.add(("external_source", external_id))
                            analytical_evidence_support[evidence_id] = support
                            if evidence_row.get("type") == "absence_scope":
                                analytical_absence_evidence.add(evidence_id)
                entry_ids: list[str] = []
                coverage_dimension_for_domain = {
                    "partition-regime": "partition-regime",
                    "measure-algebra": "measure-algebra",
                    "assumption-implementation": "assumption-implementation",
                    "derived-number": "derived-number-traceability",
                    "comparison-harmonization": "comparison-harmonization",
                    "timing-test": "timing-test-semantics",
                    "availability-exclusivity": "availability-exclusivity",
                }
                for domain in domains:
                    domain_units = set(domain.get("coverage_unit_ids", []))
                    unknown_units = sorted(domain_units - coverage_unit_ids)
                    if unknown_units:
                        errors.append(
                            f"analytical domain {domain.get('kind')} references unknown coverage units: "
                            + ", ".join(unknown_units)
                        )
                    entries = [row for row in domain.get("entries", []) if isinstance(row, dict)]
                    if domain.get("status") == "complete" and not entries:
                        errors.append(f"complete analytical domain {domain.get('kind')} requires at least one entry")
                    if domain.get("status") == "complete" and not domain_units:
                        errors.append(f"complete analytical domain {domain.get('kind')} requires a non-empty scope")
                    if domain.get("status") in {"bounded", "not_applicable"} and not domain.get("notes", "").strip():
                        errors.append(f"{domain.get('status')} analytical domain {domain.get('kind')} requires notes")
                    entry_unit_union: set[str] = set()
                    domain_finding_union: set[str] = set()
                    domain_has_bounded_entry_or_check = False
                    for entry in entries:
                        entry_ids.append(entry.get("id"))
                        evidence_summary = entry.get("evidence", "")
                        if strict_v4_audits and generic_analytical_text(evidence_summary):
                            errors.append(
                                f"analytical entry {entry.get('id')} needs paper-specific evidence, not a generic completion assertion"
                            )
                        entry_refs: set[tuple[str, str]] = set()
                        expanded_entry_refs: set[tuple[str, str]] = set()
                        if analytical_schema_version == "0.2":
                            for ref in entry.get("evidence_refs", []):
                                if not isinstance(ref, dict):
                                    continue
                                ref_kind, ref_id = ref.get("kind"), ref.get("id")
                                if not isinstance(ref_kind, str) or not isinstance(ref_id, str):
                                    continue
                                ref_tuple = (ref_kind, ref_id)
                                entry_refs.add(ref_tuple)
                                expanded_entry_refs.add(ref_tuple)
                                if ref_id not in analytical_known_refs.get(ref_kind, set()):
                                    errors.append(
                                        f"analytical entry {entry.get('id')} references unknown canonical evidence {ref_kind}:{ref_id}"
                                    )
                                if ref_kind == "finding_evidence":
                                    expanded_entry_refs.update(
                                        analytical_evidence_support.get(ref_id, set())
                                    )
                        for locator_index, locator in enumerate(entry.get("evidence_locators", [])):
                            content = locator.get("content", "") if isinstance(locator, dict) else ""
                            if strict_v4_audits and generic_analytical_text(content):
                                errors.append(
                                    f"analytical entry {entry.get('id')} evidence locator {locator_index + 1} needs substantive source content"
                                )
                            if analytical_schema_version == "0.2" and isinstance(locator, dict):
                                locator_unit = locator.get("coverage_unit_id")
                                if locator_unit not in entry.get("coverage_unit_ids", []):
                                    errors.append(
                                        f"analytical entry {entry.get('id')} evidence locator {locator_index + 1} "
                                        "must resolve to one of the entry's coverage units"
                                    )
                                representation = locator.get("representation")
                                anchor_id = locator.get("anchor_id")
                                record_ref = locator.get("record_ref")
                                record_kind = (
                                    record_ref.get("kind") if isinstance(record_ref, dict) else None
                                )
                                record_id = (
                                    record_ref.get("id") if isinstance(record_ref, dict) else None
                                )
                                record_tuple = (record_kind, record_id)
                                locator_label = (
                                    f"analytical entry {entry.get('id')} evidence locator "
                                    f"{locator_index + 1}"
                                )
                                if not isinstance(record_kind, str) or not isinstance(record_id, str):
                                    errors.append(
                                        f"{locator_label} requires a locator-level canonical record_ref"
                                    )
                                    continue
                                if record_tuple not in entry_refs:
                                    errors.append(
                                        f"{locator_label} record_ref {record_kind}:{record_id} "
                                        "must appear directly in the entry's evidence_refs"
                                    )
                                if record_id not in analytical_known_refs.get(record_kind, set()):
                                    errors.append(
                                        f"{locator_label} references unknown canonical record "
                                        f"{record_kind}:{record_id}"
                                    )

                                permitted_record_kinds = {
                                    "verbatim": {"anchor", "finding_evidence"},
                                    "normalized_transcription": {"anchor", "finding_evidence"},
                                    "reviewer_observation": {"anchor", "finding_evidence"},
                                    "checked_absence": {"anchor", "finding_evidence"},
                                    "computed_result": {"computation"},
                                    "external_source": {"external_source"},
                                }
                                if record_kind not in permitted_record_kinds.get(
                                    representation, set()
                                ):
                                    errors.append(
                                        f"{locator_label} representation {representation} cannot resolve "
                                        f"to {record_kind}:{record_id}"
                                    )

                                resolved_anchor_id: str | None = None
                                canonical_content: str | None = None
                                evidence_record: dict[str, Any] | None = None
                                if record_kind == "anchor":
                                    resolved_anchor_id = record_id
                                    canonical_content = analytical_anchor_content.get(record_id)
                                    if (
                                        representation == "checked_absence"
                                        and analytical_anchor_by_id.get(record_id, {}).get("kind")
                                        != "scope"
                                    ):
                                        errors.append(
                                            f"{locator_label} checked_absence record_ref must be a scope anchor"
                                        )
                                elif record_kind == "finding_evidence":
                                    evidence_record = analytical_evidence_by_id.get(record_id)
                                    if isinstance(evidence_record, dict):
                                        evidence_representation = evidence_record.get("representation")
                                        if evidence_representation != representation:
                                            errors.append(
                                                f"{locator_label} representation {representation} conflicts "
                                                f"with finding evidence {record_id} representation "
                                                f"{evidence_representation}"
                                            )
                                        evidence_anchor_id = evidence_record.get("anchor_id")
                                        if isinstance(evidence_anchor_id, str):
                                            resolved_anchor_id = evidence_anchor_id
                                        canonical_content = evidence_record.get("content")
                                        if (
                                            representation == "checked_absence"
                                            and record_id not in analytical_absence_evidence
                                        ):
                                            errors.append(
                                                f"{locator_label} checked_absence record_ref must be an "
                                                "absence-scope evidence record"
                                            )

                                if resolved_anchor_id is not None:
                                    if anchor_id != resolved_anchor_id:
                                        errors.append(
                                            f"{locator_label} anchor_id must match record_ref source anchor "
                                            f"{resolved_anchor_id}"
                                        )
                                    anchor_row = analytical_anchor_by_id.get(resolved_anchor_id)
                                    if not isinstance(anchor_row, dict):
                                        errors.append(
                                            f"{locator_label} references unknown source anchor "
                                            f"{resolved_anchor_id}"
                                        )
                                    else:
                                        source_row = analytical_source_by_id.get(
                                            anchor_row.get("source_id"), {}
                                        )
                                        extraction = source_row.get("extraction")
                                        allowed_sources = {
                                            anchor_row.get("source_id"),
                                            source_row.get("path"),
                                            extraction.get("path")
                                            if isinstance(extraction, dict)
                                            else None,
                                        }
                                        if locator.get("source") not in allowed_sources:
                                            errors.append(
                                                f"{locator_label} source does not match anchor "
                                                f"{resolved_anchor_id}"
                                            )
                                        if normalize_quote(str(locator.get("locator", ""))) != normalize_quote(
                                            str(anchor_row.get("locator", ""))
                                        ):
                                            errors.append(
                                                f"{locator_label} locator does not match anchor "
                                                f"{resolved_anchor_id}"
                                            )
                                elif record_kind in {"anchor", "finding_evidence"}:
                                    if anchor_id is not None:
                                        errors.append(
                                            f"{locator_label} has anchor_id {anchor_id} but its canonical "
                                            "record has no source anchor"
                                        )
                                    if isinstance(evidence_record, dict):
                                        if locator.get("source") != evidence_record.get("source"):
                                            errors.append(
                                                f"{locator_label} source does not match finding evidence "
                                                f"{record_id}"
                                            )
                                        checked_scope = evidence_record.get("scope_checked")
                                        if (
                                            isinstance(checked_scope, str)
                                            and normalize_quote(str(locator.get("locator", "")))
                                            != normalize_quote(checked_scope)
                                        ):
                                            errors.append(
                                                f"{locator_label} locator does not match the checked scope "
                                                f"for finding evidence {record_id}"
                                            )

                                if record_kind == "computation":
                                    computation = analytical_computation_by_id.get(record_id)
                                    if anchor_id is not None:
                                        errors.append(
                                            f"{locator_label} computed_result must use anchor_id null"
                                        )
                                    if locator.get("source") != "evidence/computations.json":
                                        errors.append(
                                            f"{locator_label} source must be evidence/computations.json"
                                        )
                                    if locator.get("locator") != record_id:
                                        errors.append(
                                            f"{locator_label} locator must equal computation ID {record_id}"
                                        )
                                    if isinstance(computation, dict):
                                        displayed_result = content
                                        if displayed_result.startswith("[Computation]"):
                                            displayed_result = displayed_result[len("[Computation]"):].lstrip()
                                        if normalize_quote(displayed_result) != normalize_quote(
                                            str(computation.get("result", ""))
                                        ):
                                            errors.append(
                                                f"{locator_label} content does not match computation "
                                                f"{record_id} result"
                                            )
                                elif record_kind == "external_source":
                                    external_record = analytical_external_by_id.get(record_id)
                                    if anchor_id is not None:
                                        errors.append(
                                            f"{locator_label} external_source must use anchor_id null"
                                        )
                                    if locator.get("source") != "evidence/external-sources.json":
                                        errors.append(
                                            f"{locator_label} source must be evidence/external-sources.json"
                                        )
                                    if locator.get("locator") != record_id:
                                        errors.append(
                                            f"{locator_label} locator must equal external-source ID {record_id}"
                                        )
                                    if isinstance(external_record, dict):
                                        propositions = {
                                            normalize_quote(str(proposition))
                                            for proposition in external_record.get(
                                                "supported_propositions", []
                                            )
                                        }
                                        if normalize_quote(content) not in propositions:
                                            errors.append(
                                                f"{locator_label} content is not a supported proposition "
                                                f"of external source {record_id}"
                                            )

                                if representation == "verbatim" and isinstance(
                                    canonical_content, str
                                ) and content != canonical_content:
                                    errors.append(
                                        f"{locator_label} is not verbatim at canonical record "
                                        f"{record_kind}:{record_id}"
                                    )
                                if representation == "normalized_transcription" and isinstance(
                                    canonical_content, str
                                ) and normalize_quote(content) != normalize_quote(canonical_content):
                                    errors.append(
                                        f"{locator_label} does not match normalized canonical record "
                                        f"{record_kind}:{record_id}"
                                    )
                                if representation == "reviewer_observation":
                                    if isinstance(evidence_record, dict):
                                        if isinstance(canonical_content, str) and content != canonical_content:
                                            errors.append(
                                                f"{locator_label} content does not match reviewer "
                                                f"observation {record_id}"
                                            )
                                if representation == "checked_absence":
                                    if isinstance(evidence_record, dict):
                                        if isinstance(canonical_content, str) and content != canonical_content:
                                            errors.append(
                                                f"{locator_label} content does not match checked absence "
                                                f"{record_id}"
                                            )
                                    elif not content.startswith("[Checked absence]"):
                                        errors.append(
                                            f"{locator_label} checked_absence content must start with "
                                            "[Checked absence]"
                                        )
                        entry_units = set(entry.get("coverage_unit_ids", []))
                        entry_unit_union.update(entry_units)
                        if not entry_units:
                            errors.append(f"analytical entry {entry.get('id')} requires at least one coverage unit")
                        unknown_entry_units = sorted(entry_units - domain_units)
                        if unknown_entry_units:
                            errors.append(
                                f"analytical entry {entry.get('id')} falls outside its domain scope: "
                                + ", ".join(unknown_entry_units)
                            )
                        mapped = entry.get("finding_ids", [])
                        domain_finding_union.update(mapped)
                        active_mapped: list[str] = []
                        for finding_id in mapped:
                            if finding_id not in active_ids:
                                errors.append(
                                    f"analytical entry {entry.get('id')} references unknown or inactive finding {finding_id}"
                                )
                            else:
                                active_mapped.append(finding_id)
                                if analytical_schema_version == "0.2":
                                    owned_support: set[tuple[str, str]] = set()
                                    for evidence_id, owner in analytical_evidence_owner.items():
                                        if owner == finding_id:
                                            owned_support.update(
                                                analytical_evidence_support.get(evidence_id, set())
                                            )
                                    if entry_refs.isdisjoint(owned_support):
                                        errors.append(
                                            f"analytical entry {entry.get('id')} evidence does not support mapped finding {finding_id}"
                                        )
                        checks = [check for check in entry.get("checks", []) if isinstance(check, dict)]
                        check_ids = [check.get("id") for check in checks if check.get("id")]
                        duplicate_checks = sorted(
                            item for item, count in Counter(check_ids).items() if count > 1
                        )
                        if duplicate_checks:
                            errors.append(
                                f"analytical entry {entry.get('id')} repeats checks: "
                                + ", ".join(duplicate_checks)
                            )
                        check_statuses = {check.get("status") for check in checks}
                        if entry.get("status") == "bounded" or "bounded" in check_statuses:
                            domain_has_bounded_entry_or_check = True
                        for check in checks:
                            result = check.get("result", "")
                            if strict_v4_audits and generic_analytical_text(result):
                                errors.append(
                                    f"analytical check {entry.get('id')}/{check.get('id')} needs a paper-specific result"
                                )
                        adverse_check = "issue" in check_statuses
                        if (entry.get("status") == "issue" or adverse_check) and not active_mapped:
                            errors.append(
                                f"adverse analytical entry {entry.get('id')} must map to an active finding"
                            )
                        if entry.get("status") == "issue" and not adverse_check:
                            errors.append(f"issue analytical entry {entry.get('id')} requires an issue check")
                        if entry.get("status") == "clear" and check_statuses - {"clear", "not_applicable"}:
                            errors.append(f"clear analytical entry {entry.get('id')} has a non-clear check")
                        if entry.get("status") == "clear" and active_mapped:
                            errors.append(
                                f"clear analytical entry {entry.get('id')} must not map to an active finding"
                            )
                        if entry.get("status") == "bounded" and not ({"bounded", "issue"} & check_statuses):
                            errors.append(f"bounded analytical entry {entry.get('id')} requires a bounded or issue check")
                    if (
                        analytical_schema_version == "0.2"
                        and domain_has_bounded_entry_or_check
                        and domain.get("status") != "bounded"
                    ):
                        errors.append(
                            f"analytical domain {domain.get('kind')} contains a bounded entry or check; "
                            "mark both the domain and its coverage dimension bounded"
                        )
                    if domain.get("status") == "complete" and entry_unit_union != domain_units:
                        missing = sorted(domain_units - entry_unit_union)
                        extra = sorted(entry_unit_union - domain_units)
                        if missing:
                            errors.append(
                                f"analytical domain {domain.get('kind')} has scope not covered by entries: "
                                + ", ".join(missing)
                            )
                        if extra:
                            errors.append(
                                f"analytical domain {domain.get('kind')} entries exceed domain scope: "
                                + ", ".join(extra)
                            )
                    coverage_dimension_id = coverage_dimension_for_domain.get(domain.get("kind"))
                    coverage_row = coverage_dimensions_by_id.get(coverage_dimension_id, {})
                    coverage_status = coverage_row.get("status")
                    domain_status = domain.get("status")
                    compatible_statuses = {
                        "complete": {"checked_no_issue", "findings"},
                        "bounded": {"bounded"},
                        "not_applicable": {"not_applicable"},
                    }
                    if coverage_status not in compatible_statuses.get(domain_status, set()):
                        errors.append(
                            f"analytical domain {domain.get('kind')} status {domain_status} "
                            f"conflicts with coverage dimension {coverage_dimension_id} status {coverage_status}"
                        )
                    if domain_finding_union != set(coverage_row.get("finding_ids", [])):
                        errors.append(
                            f"analytical domain {domain.get('kind')} finding links do not match coverage dimension {coverage_dimension_id}"
                        )
                duplicate_entries = sorted(
                    item for item, count in Counter(entry_ids).items() if item and count > 1
                )
                if duplicate_entries:
                    errors.append("duplicate analytical entry IDs: " + ", ".join(duplicate_entries))

        if (
            run.get("mode") == "full"
            and isinstance(computations_for_computation_audit, dict)
            and computations_for_computation_audit.get("schema_version") == "0.2"
        ):
            actual_audit_links: dict[str, set[tuple[str, str]]] = {}
            known_audit_targets: set[tuple[str, str]] = set()
            if isinstance(analytical_for_computation_audit, dict):
                for domain in analytical_for_computation_audit.get("domains", []):
                    if not isinstance(domain, dict):
                        continue
                    for entry in domain.get("entries", []):
                        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                            continue
                        target = ("analytical_entry", entry["id"])
                        known_audit_targets.add(target)
                        direct_refs = {
                            (ref.get("kind"), ref.get("id"))
                            for ref in entry.get("evidence_refs", [])
                            if isinstance(ref, dict)
                        }
                        for locator in entry.get("evidence_locators", []):
                            if not isinstance(locator, dict):
                                continue
                            record_ref = locator.get("record_ref")
                            if not isinstance(record_ref, dict):
                                continue
                            computation_id = record_ref.get("id")
                            if (
                                record_ref.get("kind") == "computation"
                                and isinstance(computation_id, str)
                                and ("computation", computation_id) in direct_refs
                            ):
                                actual_audit_links.setdefault(computation_id, set()).add(target)
            if isinstance(claims_for_computation_audit, dict):
                argument = claims_for_computation_audit.get("argument_audit")
                magnitude_collection = (
                    argument.get("magnitude_assessments")
                    if isinstance(argument, dict)
                    else None
                )
                magnitude_entries = (
                    magnitude_collection.get("entries", [])
                    if isinstance(magnitude_collection, dict)
                    else []
                )
                for entry in magnitude_entries:
                    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                        continue
                    target = ("magnitude_assessment", entry["id"])
                    known_audit_targets.add(target)
                    computation_id = entry.get("computation_id")
                    direct_refs = {
                        (ref.get("kind"), ref.get("id"))
                        for ref in entry.get("evidence_refs", [])
                        if isinstance(ref, dict)
                    }
                    if (
                        isinstance(computation_id, str)
                        and ("computation", computation_id) in direct_refs
                    ):
                        actual_audit_links.setdefault(computation_id, set()).add(target)

            computation_rows = [
                row
                for row in computations_for_computation_audit.get("computations", [])
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            ]
            for computation in computation_rows:
                computation_id = computation["id"]
                declared_links = {
                    (link.get("kind"), link.get("id"))
                    for link in computation.get("audit_links", [])
                    if isinstance(link, dict)
                    and isinstance(link.get("kind"), str)
                    and isinstance(link.get("id"), str)
                }
                unknown_targets = sorted(declared_links - known_audit_targets)
                if unknown_targets:
                    errors.append(
                        f"computation {computation_id} audit_links reference unknown audit rows: "
                        + ", ".join(f"{kind}:{row_id}" for kind, row_id in unknown_targets)
                    )
                actual_links = actual_audit_links.get(computation_id, set())
                if declared_links != actual_links:
                    missing = sorted(declared_links - actual_links)
                    undeclared = sorted(actual_links - declared_links)
                    detail: list[str] = []
                    if missing:
                        detail.append(
                            "not cited canonically by audit rows: "
                            + ", ".join(f"{kind}:{row_id}" for kind, row_id in missing)
                        )
                    if undeclared:
                        detail.append(
                            "undeclared canonical audit rows: "
                            + ", ".join(f"{kind}:{row_id}" for kind, row_id in undeclared)
                        )
                    errors.append(
                        f"computation {computation_id} audit links are not reciprocal ("
                        + "; ".join(detail)
                        + ")"
                    )
                if not computation.get("finding_ids") and not actual_links:
                    errors.append(
                        f"audit-only computation {computation_id} is orphaned; canonically link it "
                        "to an analytical entry or magnitude assessment"
                    )

        writing_path = review_dir / "evidence/writing.json"
        if run.get("mode") == "full" and writing_path.exists():
            writing = load_json(writing_path, errors)
            if isinstance(writing, dict):
                validate_schema(writing, "writing.schema.json", "evidence/writing.json", errors)
                writing_audit_version = writing.get("schema_version")
                strict_writing_audit = writing_audit_version in {"0.2", "0.3", "0.4"}
                if strict_burden_coverage and writing_audit_version != "0.4":
                    errors.append(
                        "current v0.4 full review requires evidence/writing.json schema_version 0.4"
                    )
                if writing_audit_version in {"0.3", "0.4"} and writing_report_path.exists():
                    current_writing_report = writing_report_path.read_text(encoding="utf-8")
                    if re.search(
                        r"^## (?:References and citation integrity|Reference accuracy and citation support)\s*$",
                        current_writing_report,
                        re.MULTILINE,
                    ):
                        errors.append(
                            f"writing audit v{writing_audit_version} forbids a routine reference or citation-accuracy section"
                        )
                if writing.get("review_id") != run.get("review_id"):
                    errors.append("writing review_id differs from run.json")
                active_ids = {item.get("id") for item in active}
                strict_writing_source_binding = (
                    strict_burden_coverage and writing_audit_version == "0.4"
                )
                if strict_writing_source_binding:
                    if source_binding_context is None:
                        source_binding_context = load_source_binding_context(
                            review_dir, findings, errors
                        )
                    writing_scope = writing.get("scope", {})
                    declared_source_ids = {
                        source_id for source_id in writing_scope.get("source_ids", [])
                        if isinstance(writing_scope, dict) and isinstance(source_id, str)
                    }
                    expected_source_ids = {
                        source_id
                        for source_id, source in source_binding_context["source_by_id"].items()
                        if source.get("role") in DOCUMENT_SOURCE_ROLES
                    }
                    if declared_source_ids != expected_source_ids:
                        missing = sorted(expected_source_ids - declared_source_ids)
                        extra = sorted(declared_source_ids - expected_source_ids)
                        if missing:
                            errors.append(
                                "writing scope omits document sources: " + ", ".join(missing)
                            )
                        if extra:
                            errors.append(
                                "writing scope references non-document sources: "
                                + ", ".join(extra)
                            )
                    declared_scope_anchor_ids = {
                        anchor_id for anchor_id in writing_scope.get("scope_anchor_ids", [])
                        if isinstance(writing_scope, dict) and isinstance(anchor_id, str)
                    }
                    scope_anchor_sources: set[str] = set()
                    for anchor_id in declared_scope_anchor_ids:
                        anchor = source_binding_context["anchor_by_id"].get(anchor_id)
                        if not isinstance(anchor, dict):
                            errors.append(
                                f"writing scope references unknown anchor {anchor_id}"
                            )
                        elif anchor.get("kind") != "scope":
                            errors.append(
                                f"writing scope anchor {anchor_id} is not a canonical scope anchor"
                            )
                        elif isinstance(anchor.get("source_id"), str):
                            scope_anchor_sources.add(anchor["source_id"])
                    if scope_anchor_sources != declared_source_ids:
                        errors.append(
                            "writing scope requires exactly one or more canonical scope anchors for every declared source"
                        )
                    writing_scope_units = {
                        unit_id for unit_id in writing_scope.get("coverage_unit_ids", [])
                        if isinstance(writing_scope, dict) and isinstance(unit_id, str)
                    }
                    document_coverage_units: set[str] = set()
                    for unit_id, anchor_ids in coverage_anchor_ids_by_unit.items():
                        if any(
                            source_binding_context["source_by_id"].get(
                                source_binding_context["anchor_by_id"].get(anchor_id, {}).get(
                                    "source_id"
                                ),
                                {},
                            ).get("role")
                            in DOCUMENT_SOURCE_ROLES
                            for anchor_id in anchor_ids
                        ):
                            document_coverage_units.add(unit_id)
                    if writing_scope_units != document_coverage_units:
                        missing = sorted(document_coverage_units - writing_scope_units)
                        extra = sorted(writing_scope_units - document_coverage_units)
                        if missing:
                            errors.append(
                                "writing scope omits document coverage units: "
                                + ", ".join(missing)
                            )
                        if extra:
                            errors.append(
                                "writing scope references non-document coverage units: "
                                + ", ".join(extra)
                            )

                    binding_collections = (
                        "section_audit",
                        "redundancy_map",
                        "mechanics",
                        "consistency_groups",
                        "style_suggestions",
                    )
                    for collection_name in binding_collections:
                        collection = writing.get(collection_name, [])
                        for row_index, row in enumerate(
                            collection if isinstance(collection, list) else [], start=1
                        ):
                            if not isinstance(row, dict):
                                continue
                            row_id = (
                                row.get("id")
                                or row.get("section")
                                or row.get("idea")
                                or str(row_index)
                            )
                            row_label = f"writing {collection_name} row {row_id}"
                            row_units = {
                                unit_id for unit_id in row.get("coverage_unit_ids", [])
                                if isinstance(unit_id, str)
                            }
                            if not row_units:
                                errors.append(f"{row_label} requires coverage_unit_ids")
                            unknown_units = sorted(row_units - writing_scope_units)
                            if unknown_units:
                                errors.append(
                                    f"{row_label} references units outside the writing scope: "
                                    + ", ".join(unknown_units)
                                )
                            support = validate_source_evidence_refs(
                                row.get("evidence_refs"),
                                label=row_label,
                                coverage_unit_ids=row_units,
                                context=source_binding_context,
                                coverage_anchor_ids_by_unit=coverage_anchor_ids_by_unit,
                                errors=errors,
                            )
                            if not support["direct_anchor_ids"] and not (
                                collection_name == "mechanics"
                                and row.get("status") == "checked_clean_group"
                            ):
                                errors.append(
                                    f"{row_label} requires precise source support"
                                )
                            raw_mapped_findings = row.get("finding_ids", [])
                            mapped_findings = {
                                finding_id
                                for finding_id in (
                                    raw_mapped_findings
                                    if isinstance(raw_mapped_findings, list)
                                    else []
                                )
                                if isinstance(finding_id, str)
                            }
                            missing_owners = sorted(
                                mapped_findings - support["finding_owners"]
                            )
                            if missing_owners:
                                errors.append(
                                    f"{row_label} finding links lack reciprocal passed evidence: "
                                    + ", ".join(missing_owners)
                                )
                            if collection_name == "mechanics":
                                if row.get("status") == "checked_clean_group" and not support[
                                    "absence_anchor_ids"
                                ]:
                                    errors.append(
                                        f"checked-clean {row_label} requires a scope-anchored checked_absence reference"
                                    )
                                occurrences = row.get("occurrences", [])
                                occurrence_anchor_ids: set[str] = set()
                                for occurrence_index, occurrence in enumerate(
                                    occurrences if isinstance(occurrences, list) else [], start=1
                                ):
                                    if not isinstance(occurrence, dict):
                                        continue
                                    occurrence_anchor = occurrence.get("anchor_id")
                                    matching_units = sorted(
                                        unit_id for unit_id in row_units
                                        if occurrence_anchor
                                        in coverage_anchor_ids_by_unit.get(unit_id, set())
                                    )
                                    anchor_id = validate_exact_source_binding(
                                        label=f"{row_label} occurrence {occurrence_index}",
                                        anchor_id=occurrence_anchor,
                                        representation=occurrence.get("representation"),
                                        content=occurrence.get("quote"),
                                        locator=occurrence.get("locator"),
                                        coverage_unit_id=(
                                            matching_units[0] if matching_units else None
                                        ),
                                        context=source_binding_context,
                                        coverage_anchor_ids_by_unit=coverage_anchor_ids_by_unit,
                                        errors=errors,
                                    )
                                    if isinstance(anchor_id, str):
                                        occurrence_anchor_ids.add(anchor_id)
                                if row.get("status") == "issue":
                                    if not occurrence_anchor_ids:
                                        errors.append(
                                            f"issue {row_label} requires a canonically bound occurrence"
                                        )
                                    if not occurrence_anchor_ids.issubset(
                                        support["direct_anchor_ids"]
                                    ):
                                        errors.append(
                                            f"{row_label} evidence_refs do not cover every occurrence anchor"
                                        )
                                    if isinstance(occurrences, list) and occurrences:
                                        first_occurrence = next(
                                            (
                                                occurrence for occurrence in occurrences
                                                if isinstance(occurrence, dict)
                                            ),
                                            None,
                                        )
                                        if isinstance(first_occurrence, dict) and (
                                            row.get("quote") != first_occurrence.get("quote")
                                            or normalize_source_transcription(str(row.get("locator", "")))
                                            != normalize_source_transcription(
                                                str(first_occurrence.get("locator", ""))
                                            )
                                        ):
                                            errors.append(
                                                f"{row_label} summary quote and locator must match its first occurrence"
                                            )
                            if (
                                collection_name == "consistency_groups"
                                and row.get("status") == "consistent"
                            ):
                                if not support["direct_anchor_ids"]:
                                    errors.append(
                                        f"consistent {row_label} requires precise source support"
                                    )
                                if not support["absence_anchor_ids"]:
                                    errors.append(
                                        f"consistent {row_label} requires a scope-anchored checked_absence reference"
                                    )

                def writing_string_list(value: Any) -> list[str]:
                    """Return only string members after schema validation has recorded bad input."""
                    if not isinstance(value, list):
                        return []
                    return [item for item in value if isinstance(item, str)]

                def check_writing_rows(rows: Any, label: str, adverse_statuses: set[str]) -> None:
                    if not isinstance(rows, list):
                        return
                    row_ids = [
                        row.get("id") for row in rows
                        if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("id")
                    ]
                    duplicates = sorted(item for item, count in Counter(row_ids).items() if count > 1)
                    if duplicates:
                        errors.append(f"duplicate {label} IDs: {', '.join(duplicates)}")
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        mapped = writing_string_list(row.get("finding_ids"))
                        row_status = row.get("status")
                        for finding_id in mapped:
                            if finding_id not in active_ids:
                                errors.append(f"{label} {row.get('id')} references unknown or inactive finding {finding_id}")
                        if isinstance(row_status, str) and row_status in adverse_statuses and not mapped:
                            errors.append(f"adverse {label} state {row.get('id')} must map to an active finding")
                        if strict_writing_audit and label == "writing-mechanics" and row_status == "checked_clean_group" and mapped:
                            errors.append(f"checked-clean writing-mechanics row {row.get('id')} cannot map an active finding")
                        if strict_writing_audit and label == "writing-consistency" and row_status == "consistent" and mapped:
                            errors.append(f"consistent writing-consistency row {row.get('id')} cannot map an active finding")

                mechanics_rows = writing.get("mechanics", [])
                for group in mechanics_rows if isinstance(mechanics_rows, list) else []:
                    if not isinstance(group, dict) or group.get("status") != "issue":
                        continue
                    occurrences = group.get("occurrences", [])
                    for occurrence in occurrences if isinstance(occurrences, list) else []:
                        if not isinstance(occurrence, dict):
                            continue
                        if writing_audit_version in {"0.2", "0.3"} and (
                            "render_verification" not in occurrence or "source_provenance" not in occurrence
                        ):
                            errors.append(
                                f"writing v{writing_audit_version} mechanics occurrence in {group.get('id')} requires render verification and source provenance"
                            )
                        occurrence_render = occurrence.get("render_verification")
                        if isinstance(occurrence_render, str) and occurrence_render in {"bounded", "extraction_artifact_rejected"}:
                            errors.append(
                                f"retained writing-mechanics occurrence in {group.get('id')} lacks authoritative visual/source verification"
                            )

                check_writing_rows(writing.get("mechanics"), "writing-mechanics", {"issue"})
                check_writing_rows(writing.get("consistency_groups"), "writing-consistency", {"issue"})
                check_writing_rows(writing.get("style_suggestions"), "writing-style", set())

                writing_mapped_ids: set[str] = set()
                observed_sources: dict[str, set[str]] = {}
                source_collections = {
                    "mechanics": "mechanics",
                    "consistency_groups": "consistency",
                    "style_suggestions": "style",
                    "section_audit": "section",
                    "redundancy_map": "redundancy",
                }
                for collection_name, source_name in source_collections.items():
                    collection = writing.get(collection_name, [])
                    for row in collection if isinstance(collection, list) else []:
                        if isinstance(row, dict):
                            mapped = writing_string_list(row.get("finding_ids"))
                            writing_mapped_ids.update(mapped)
                            for finding_id in mapped:
                                if finding_id not in active_ids:
                                    errors.append(
                                        f"writing {collection_name} row {row.get('id') or row.get('section') or row.get('idea')} "
                                        f"references unknown or inactive finding {finding_id}"
                                    )
                            issue_bearing = (
                                (collection_name == "mechanics" and row.get("status") == "issue")
                                or (collection_name == "consistency_groups" and row.get("status") == "issue")
                                or collection_name in {"style_suggestions", "section_audit", "redundancy_map"}
                            )
                            if issue_bearing:
                                for finding_id in mapped:
                                    observed_sources.setdefault(finding_id, set()).add(source_name)

                reference_audit = writing.get("reference_audit", {})
                if writing_audit_version in {"0.1", "0.2"} and isinstance(reference_audit, dict):
                    records = reference_audit.get("records", [])
                    record_rows = records if isinstance(records, list) else []
                    resolved_records = [
                        row for row in record_rows
                        if isinstance(row, dict) and row.get("status") != "unresolved"
                    ]
                    expected_checked = len(resolved_records) if writing_audit_version == "0.2" else len(record_rows)
                    if isinstance(records, list) and reference_audit.get("records_checked") != expected_checked:
                        expectation = "the number of non-unresolved record rows" if writing_audit_version == "0.2" else "the number of record rows"
                        errors.append(f"writing reference_audit.records_checked must equal {expectation}")
                    status_counts = Counter(
                        row.get("status") for row in record_rows
                        if isinstance(row, dict) and isinstance(row.get("status"), str)
                    )
                    expected_reference_counts = {
                        "records_verified": status_counts["verified"],
                        "records_adverse": sum(status_counts[value] for value in (
                            "metadata_issue", "version_issue", "citation_reference_mismatch", "support_issue"
                        )),
                        "records_unresolved": status_counts["unresolved"],
                    }
                    for field, expected in expected_reference_counts.items():
                        if field in reference_audit and reference_audit.get(field) != expected:
                            errors.append(f"writing reference_audit.{field} must equal {expected} from the record states")
                    if reference_audit.get("status") == "complete" and reference_audit.get("records_checked") != reference_audit.get("bibliography_record_count"):
                        errors.append("complete reference audit must check every bibliography record")
                    check_writing_rows(
                        record_rows,
                        "reference-record",
                        {"metadata_issue", "version_issue", "citation_reference_mismatch", "support_issue"},
                    )
                    for row in record_rows:
                        if isinstance(row, dict):
                            mapped = writing_string_list(row.get("finding_ids"))
                            writing_mapped_ids.update(mapped)
                            record_status = row.get("status")
                            if strict_writing_audit and isinstance(record_status, str) and record_status in {"verified", "unresolved"} and mapped:
                                errors.append(
                                    f"reference-record {row.get('id')} with status {record_status} cannot map an active finding"
                                )
                            if isinstance(record_status, str) and record_status in {
                                "metadata_issue", "version_issue", "citation_reference_mismatch", "support_issue"
                            }:
                                for finding_id in mapped:
                                    observed_sources.setdefault(finding_id, set()).add("reference")
                    reference_ids = writing_string_list(reference_audit.get("finding_ids"))
                    for finding_id in reference_ids:
                        if finding_id not in active_ids:
                            errors.append(f"reference_audit references unknown or inactive finding {finding_id}")
                    writing_mapped_ids.update(reference_ids)
                    for finding_id in reference_ids:
                        observed_sources.setdefault(finding_id, set()).add("reference")
                else:
                    # The schema error above is authoritative; keep later report checks type-safe.
                    reference_audit = {}

                venue = writing.get("venue_fit", {})
                if isinstance(venue, dict):
                    venue_status = venue.get("status")
                    if writing_audit_version == "0.4":
                        try:
                            validate_current_venue_fit(venue, journal_fit_requested)
                        except ValueError as exc:
                            errors.append(f"current venue_fit is invalid: {exc}")
                    if venue_status == "assessed" and not venue.get("candidates"):
                        errors.append("assessed venue fit requires at least one candidate journal")
                    if venue_status == "assessed" and not venue.get("as_of_date"):
                        errors.append("assessed venue fit requires an as_of_date")
                    venue_ids = writing_string_list(venue.get("finding_ids"))
                    for finding_id in venue_ids:
                        if finding_id not in active_ids:
                            errors.append(f"venue_fit references unknown or inactive finding {finding_id}")
                    if strict_writing_audit and isinstance(venue_status, str) and venue_status in {"not_requested", "not_assessed"} and venue_ids:
                        errors.append(f"venue_fit with status {venue_status} cannot map an active finding")
                    writing_mapped_ids.update(venue_ids)
                    if isinstance(venue_status, str) and venue_status in {"assessed", "bounded"}:
                        for finding_id in venue_ids:
                            observed_sources.setdefault(finding_id, set()).add("venue")
                    if strict_burden_coverage:
                        if journal_fit_requested and venue_status not in {"assessed", "bounded"}:
                            errors.append(
                                "requested journal_fit requires evidence/writing.json venue_fit.status assessed or bounded"
                            )
                        if not journal_fit_requested and venue_status != "not_requested":
                            errors.append(
                                "unrequested journal_fit requires evidence/writing.json venue_fit.status not_requested"
                            )

                active_writing_ids = {item.get("id") for item in writing_active}
                if strict_writing_audit:
                    missing_writing_mappings = sorted(active_writing_ids - writing_mapped_ids)
                    if missing_writing_mappings:
                        errors.append(
                            "active writing findings missing reciprocal evidence/writing.json mappings: "
                            + ", ".join(missing_writing_mappings)
                        )
                    raw_links = writing.get("finding_links", [])
                    link_rows = raw_links if isinstance(raw_links, list) else []
                    linked_ids = [
                        row.get("finding_id") for row in link_rows
                        if isinstance(row, dict) and isinstance(row.get("finding_id"), str)
                    ]
                    duplicate_links = sorted(
                        finding_id for finding_id, count in Counter(linked_ids).items()
                        if finding_id and count > 1
                    )
                    if duplicate_links:
                        errors.append("writing finding_links repeat IDs: " + ", ".join(duplicate_links))
                    linked_id_set = {value for value in linked_ids if isinstance(value, str)}
                    if linked_id_set != active_writing_ids:
                        missing = sorted(active_writing_ids - linked_id_set)
                        extra = sorted(linked_id_set - active_writing_ids)
                        if missing:
                            errors.append("writing finding_links omit active writing findings: " + ", ".join(missing))
                        if extra:
                            errors.append("writing finding_links contain non-writing or inactive findings: " + ", ".join(extra))
                    for row in link_rows:
                        if not isinstance(row, dict) or not isinstance(row.get("finding_id"), str):
                            continue
                        finding_id = row["finding_id"]
                        declared_sources = set(writing_string_list(row.get("sources")))
                        actual_sources = observed_sources.get(finding_id, set())
                        if declared_sources != actual_sources:
                            errors.append(
                                f"writing finding_link {finding_id} sources do not match issue-bearing audit mappings: "
                                f"declared {sorted(declared_sources)}, observed {sorted(actual_sources)}"
                            )

                    highest_ids = writing_string_list(writing.get("highest_return_finding_ids"))
                    if active_writing_ids and not highest_ids:
                        errors.append(f"writing audit v{writing_audit_version} requires a highest-return finding when active writing findings exist")
                    for finding_id in highest_ids:
                        if finding_id not in active_writing_ids:
                            errors.append(f"highest-return writing ID is not an active writing finding: {finding_id}")

                    if writing_report_path.exists():
                        writing_report = writing_report_path.read_text(encoding="utf-8")
                        rich_headings = (
                            "## Editing assessment",
                            "## Highest-return editing revisions",
                            "## Section-by-section reader audit",
                            "## Terminology, definitions, and notation",
                            "## Tables and figures as writing",
                            "## Mechanics and copyedit inventory",
                        )
                        if writing_audit_version == "0.4":
                            rich_headings += ("## Style and writing improvements",)
                        if not all(re.search(rf"^{re.escape(heading)}\s*$", writing_report, re.MULTILINE) for heading in rich_headings):
                            errors.append(
                                f"writing audit v{writing_audit_version} requires its complete current editing-comments preamble"
                            )
                        else:
                            def writing_section(heading: str) -> str:
                                match = re.search(rf"^{re.escape(heading)}\s*$", writing_report, re.MULTILINE)
                                if not match:
                                    return ""
                                following = writing_report[match.end():]
                                next_heading = re.search(r"^## ", following, re.MULTILINE)
                                return following[:next_heading.start()] if next_heading else following

                            assessment_block = normalize_quote(writing_section("## Editing assessment"))
                            raw_strengths = writing.get("strengths", [])
                            strengths = raw_strengths if isinstance(raw_strengths, list) else []
                            for strength in strengths:
                                if isinstance(strength, str) and normalize_quote(strength) not in assessment_block:
                                    errors.append("editing-comments assessment omits a canonical writing strength")
                            highest_block = writing_section("## Highest-return editing revisions")
                            writing_findings_by_id = {
                                item.get("id"): item
                                for item in writing_active
                                if isinstance(item, dict)
                            }
                            for finding_id in highest_ids:
                                finding = writing_findings_by_id.get(finding_id, {})
                                visible_label = finding.get("title") or finding.get("issue")
                                if not isinstance(visible_label, str) or normalize_quote(visible_label) not in normalize_quote(highest_block):
                                    errors.append(
                                        f"editing-comments highest-return section omits the visible title for {finding_id}"
                                    )
                            section_block = normalize_quote(writing_section("## Section-by-section reader audit"))
                            section_rows = writing.get("section_audit", [])
                            for row in section_rows if isinstance(section_rows, list) else []:
                                section_name = row.get("section") if isinstance(row, dict) else None
                                if isinstance(section_name, str) and normalize_quote(section_name) not in section_block:
                                    errors.append(f"editing-comments section audit omits {section_name!r}")
                        if strict_burden_coverage and writing_audit_version == "0.4":
                            try:
                                expected_writing_report = render_current_writing_report(
                                    ledger,
                                    writing,
                                    run,
                                )
                            except (KeyError, TypeError, ValueError) as exc:
                                errors.append(f"cannot render canonical editing-comments.md: {exc}")
                            else:
                                if writing_report != expected_writing_report:
                                    errors.append(
                                        "editing-comments.md is not synchronized with evidence/writing.json, findings.json, and run.json"
                                    )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an econ-review output directory")
    parser.add_argument("review_dir", type=Path, help="Path containing run.json, findings.json, report.md, and fix-plan.md")
    args = parser.parse_args()
    errors = validate_review(args.review_dir)
    if errors:
        print("econ-review validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"econ-review validation passed: {args.review_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
