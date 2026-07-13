#!/usr/bin/env python3
"""Create and verify a render-backed PDF transcription package.

Markdown is a reading surface. Page renders and typed page/bounding-box records
remain authoritative for tables, figures, equations, and uncertain glyphs.
Networking is forbidden by default. Mathpix is called only behind explicit
upload and retention authorization flags.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pdf_backends import (  # noqa: E402
    BackendError,
    docling_executable,
    docling_runtime_version,
    docling_version,
    run_docling,
    run_mathpix,
)
from pdf_reconciliation import (  # noqa: E402
    build_page_packets,
    load_proposal_page_index,
    packet_errors,
)

SKILL_ROOT = SCRIPT_DIR.parent
SCHEMA_PATH = SKILL_ROOT / "assets" / "pdf-ingestion.schema.json"
PIPELINE_VERSION = "0.2"
DEFAULT_OUTPUT_ROOT = Path("evidence/pdf-ingestion")
MIN_NATIVE_CHARACTERS = 24
MAX_PAGES_DEFAULT = 2_000
MAX_BYTES_DEFAULT = 1_000_000_000


class IngestionError(RuntimeError):
    pass


def validate_source_id(source_id: str) -> str:
    if not re.fullmatch(r"SRC-[0-9]{2,}", source_id):
        raise IngestionError("source ID must match SRC-[0-9]{2,}")
    return source_id


def source_block_id(source_id: str, number: int) -> str:
    return f"{validate_source_id(source_id)}-PDF-B{number:04d}"


def source_object_id(source_id: str, kind: str, number: int) -> str:
    return f"{validate_source_id(source_id)}-PDF-{kind}-{number:03d}"


def source_anchor_id(source_id: str, number: int) -> str:
    if number > 999_999:
        raise IngestionError("a PDF source cannot contain more than 999,999 anchors")
    digits = validate_source_id(source_id).split("-", 1)[1]
    return f"ANC-{digits}99{number:06d}"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def regular_file(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise IngestionError(f"{label} must not be a symbolic link: {path}")
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise IngestionError(f"cannot access {label}: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise IngestionError(f"{label} must be a regular file: {path}")
    return path.resolve()


def safe_relative(value: str | Path) -> str:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise IngestionError(f"path must be safe and relative: {value}")
    return path.as_posix()


def command_path(name: str) -> str | None:
    return shutil.which(name)


def run(command: list[str], *, timeout: int = 300, text: bool = False) -> subprocess.CompletedProcess[Any]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=text,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        )
    except FileNotFoundError as exc:
        raise IngestionError(f"required command is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise IngestionError(f"command timed out after {timeout}s: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        raise IngestionError(f"command failed ({command[0]}): {stderr.strip()}") from exc


def command_version(name: str, arguments: list[str]) -> str:
    executable = command_path(name)
    if not executable:
        return "unavailable"
    result = subprocess.run([executable, *arguments], capture_output=True, text=True, check=False)
    value = (result.stdout or result.stderr).strip().splitlines()
    return value[0][:160] if value else "available-version-unknown"


def python_package_version(name: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def doctor() -> int:
    rows = [
        ("pdftotext", command_version("pdftotext", ["-v"]), True),
        ("pdftoppm", command_version("pdftoppm", ["-v"]), True),
        ("pdfinfo", command_version("pdfinfo", ["-v"]), True),
        ("pdffonts", command_version("pdffonts", ["-v"]), False),
        ("tesseract", command_version("tesseract", ["--version"]), False),
        ("pdfplumber", python_package_version("pdfplumber") or "unavailable", False),
        ("pypdf", python_package_version("pypdf") or "unavailable", True),
        ("Pillow", python_package_version("Pillow") or "unavailable", True),
        ("jsonschema", python_package_version("jsonschema") or "unavailable", True),
        ("markitdown", command_version("markitdown", ["--version"]), False),
        ("docling", docling_version() or "unavailable", False),
        ("requests", python_package_version("requests") or "unavailable", False),
    ]
    missing_required = False
    for name, version, required in rows:
        state = "required" if required else "optional"
        print(f"{name}: {version} ({state})")
        if required and version == "unavailable":
            missing_required = True
    print("network: forbidden by default; Mathpix requires explicit upload and retention authorization")
    return 1 if missing_required else 0


def dereference(value: Any) -> Any:
    try:
        return value.get_object()
    except AttributeError:
        return value


def page_ranges(pages: Iterable[int]) -> str:
    ordered = sorted(set(pages))
    ranges: list[str] = []
    if not ordered:
        return ""
    start = previous = ordered[0]
    for page in ordered[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(ranges)


def inspect_pdf_safety(pdf: Path) -> list[str]:
    """Inspect document structure without executing actions or opening attachments."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise IngestionError("pypdf is required for non-executing PDF safety inspection") from exc
    try:
        reader = PdfReader(str(pdf), strict=False)
    except Exception as exc:
        raise IngestionError(f"pypdf could not inspect the PDF safely: {exc}") from exc
    if reader.is_encrypted:
        raise IngestionError("encrypted PDFs are not ingested; provide an authorized unencrypted copy")
    warnings: set[str] = set()
    page_action_pages: set[int] = set()
    annotation_action_pages: set[int] = set()
    root = dereference(reader.trailer.get("/Root"))
    if isinstance(root, dict):
        if "/OpenAction" in root:
            warnings.add("non-executing inspection found a document OpenAction; it was not executed")
        if "/AA" in root:
            warnings.add("non-executing inspection found document additional actions; they were not executed")
        if "/AcroForm" in root:
            warnings.add("non-executing inspection found an interactive form; form actions were not executed")
        if "/AF" in root or "/Collection" in root:
            warnings.add("non-executing inspection found associated or portfolio files; attachments were not opened")
        names = dereference(root.get("/Names"))
        if isinstance(names, dict):
            if "/JavaScript" in names:
                warnings.add("non-executing inspection found document JavaScript; it was not executed")
            if "/EmbeddedFiles" in names:
                warnings.add("non-executing inspection found embedded files; attachments were not opened")
    try:
        for page_number, page in enumerate(reader.pages, 1):
            if "/AA" in page:
                page_action_pages.add(page_number)
            annotations = dereference(page.get("/Annots")) or []
            for reference in annotations:
                annotation = dereference(reference)
                if isinstance(annotation, dict) and ("/A" in annotation or "/AA" in annotation):
                    annotation_action_pages.add(page_number)
                    break
    except Exception as exc:
        warnings.add(f"non-executing annotation inspection was bounded: {type(exc).__name__}")
    if page_action_pages:
        warnings.add(
            f"non-executing inspection found page actions on pages {page_ranges(page_action_pages)}; they were not executed"
        )
    if annotation_action_pages:
        warnings.add(
            "non-executing inspection found annotation actions on pages "
            f"{page_ranges(annotation_action_pages)}; they were not executed"
        )
    return sorted(warnings)


def toolchain_for(args: argparse.Namespace) -> dict[str, Any]:
    ocr_available = bool(command_path("tesseract"))
    proposal_version = command_version("markitdown", ["--version"]) if args.markitdown_proposal else "unavailable"
    if args.markitdown_proposal and proposal_version == "unavailable":
        raise IngestionError("--markitdown-proposal requires the local markitdown command")
    semantic_backends: list[dict[str, str]] = []
    if args.semantic_backend in {"auto", "docling"} and docling_version() and docling_executable():
        semantic_backends.append({"name": "docling", "version": docling_runtime_version() or "unavailable"})
    if args.mathpix:
        semantic_backends.append({"name": "mathpix", "version": "v3/pdf"})
    return {
        "primary": {"name": "pdftotext-bbox-layout", "version": command_version("pdftotext", ["-v"])},
        "renderer": {"name": "pdftoppm", "version": command_version("pdftoppm", ["-v"])},
        "table_extractor": ({"name": "pdfplumber", "version": python_package_version("pdfplumber")}
                            if python_package_version("pdfplumber") else None),
        "ocr": ({"name": "tesseract-local", "version": command_version("tesseract", ["--version"])}
                if ocr_available else None),
        "proposal": ({"name": "markitdown", "version": proposal_version}
                     if args.markitdown_proposal else None),
        "semantic_backends": semantic_backends,
    }


def run_markitdown_proposal(pdf: Path) -> str:
    executable = command_path("markitdown")
    if not executable:
        raise IngestionError("--markitdown-proposal requires the local markitdown command")
    result = run([executable, str(pdf)], timeout=900)
    return result.stdout.decode("utf-8", "replace")


def private_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def private_write(path: Path, data: bytes) -> None:
    private_mkdir(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def parse_pdfinfo(pdf: Path) -> dict[str, str]:
    result = run(["pdfinfo", str(pdf)], text=True)
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def pdf_security_preflight(pdf: Path, *, max_pages: int, max_bytes: int) -> tuple[int, bool, list[str]]:
    size = pdf.stat().st_size
    if size > max_bytes:
        raise IngestionError(f"PDF exceeds the configured {max_bytes}-byte limit")
    info = parse_pdfinfo(pdf)
    try:
        pages = int(info["Pages"])
    except (KeyError, ValueError) as exc:
        raise IngestionError("pdfinfo did not return a valid page count") from exc
    if pages < 1 or pages > max_pages:
        raise IngestionError(f"PDF page count {pages} is outside the configured 1..{max_pages} range")
    encrypted = info.get("Encrypted", "no").lower() not in {"no", "false", "none"}
    if encrypted:
        raise IngestionError("encrypted PDFs are not ingested; provide an authorized unencrypted copy")
    warnings: list[str] = []
    for key in ("JavaScript", "Form"):
        value = info.get(key, "none")
        if value.lower() not in {"no", "none", "false"}:
            warnings.append(f"PDF reports {key}={value}; embedded actions are not executed")
    return pages, encrypted, warnings


def render_pages(pdf: Path, destination: Path, dpi: int, expected_pages: int) -> list[Path]:
    private_mkdir(destination)
    prefix = destination / "raw"
    run(["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(prefix)], timeout=max(300, expected_pages * 12))
    raw = sorted(destination.glob("raw-*.png"), key=lambda path: int(path.stem.rsplit("-", 1)[1]))
    if len(raw) != expected_pages:
        raise IngestionError(f"renderer produced {len(raw)} pages; PDF declares {expected_pages}")
    rendered: list[Path] = []
    for index, source in enumerate(raw, 1):
        target = destination / f"page-{index:04d}.png"
        source.rename(target)
        target.chmod(0o600)
        rendered.append(target)
    return rendered


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def float_attr(element: ET.Element, name: str) -> float:
    return round(float(element.attrib[name]), 3)


def xml_10_character_allowed(character: str) -> bool:
    codepoint = ord(character)
    return (
        codepoint in {0x09, 0x0A, 0x0D}
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def sanitize_poppler_xhtml(raw: bytes) -> tuple[str, dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestionError(f"pdftotext bbox output is not UTF-8: {exc}") from exc
    forbidden = [character for character in text if not xml_10_character_allowed(character)]
    sanitized = "".join(character for character in text if xml_10_character_allowed(character))
    return sanitized, {
        "xml_forbidden_control_count": len(forbidden),
        "xml_forbidden_codepoints": sorted({f"U+{ord(character):04X}" for character in forbidden}),
        "raw_xhtml_sha256": sha256_bytes(raw),
        "parser_input_sha256": sha256_bytes(sanitized.encode("utf-8")),
        "action": "removed_xml_forbidden_controls_from_parser_input",
    }


def normalize_line(words: list[str]) -> str:
    text = " ".join(word for word in words if word)
    text = re.sub(r"\s+([,.;:!?%)\]])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    return text.strip()


def parse_bbox_layout(
    pdf: Path, destination: Path, source_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    bbox_path = destination / "layout.xhtml"
    run(["pdftotext", "-bbox-layout", "-enc", "UTF-8", str(pdf), str(bbox_path)])
    try:
        sanitized, repairs = sanitize_poppler_xhtml(bbox_path.read_bytes())
        root = ET.fromstring(sanitized)
    except OSError as exc:
        raise IngestionError(f"cannot read pdftotext bbox output: {exc}") from exc
    except ET.ParseError as exc:
        raise IngestionError(f"cannot parse pdftotext bbox output: {exc}") from exc
    pages: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    block_number = 0
    for page_number, page in enumerate((node for node in root.iter() if local_name(node.tag) == "page"), 1):
        width = float_attr(page, "width")
        height = float_attr(page, "height")
        pages.append({"page": page_number, "width": width, "height": height})
        for element in page.iter():
            if local_name(element.tag) != "block":
                continue
            lines: list[str] = []
            for line in element:
                if local_name(line.tag) != "line":
                    continue
                words = [(word.text or "") for word in line if local_name(word.tag) == "word"]
                value = normalize_line(words)
                if value:
                    lines.append(value)
            text = "\n".join(lines).strip()
            if not text:
                continue
            block_number += 1
            blocks.append({
                "id": source_block_id(source_id, block_number),
                "page": page_number,
                "bbox": [
                    float_attr(element, "xMin"), float_attr(element, "yMin"),
                    float_attr(element, "xMax"), float_attr(element, "yMax"),
                ],
                "raw_text": text,
                "page_width": width,
                "page_height": height,
            })
    bbox_path.unlink(missing_ok=True)
    return pages, blocks, repairs


def controls(text: str) -> list[str]:
    return sorted({f"U+{ord(char):04X}" for char in text if unicodedata.category(char) == "Cc" and char not in "\n\t\r"})


def classify_block(block: dict[str, Any], repeated: set[tuple[str, str]]) -> tuple[str, str]:
    text = block["raw_text"].strip()
    first = text.splitlines()[0]
    y0, y1 = block["bbox"][1], block["bbox"][3]
    page_height = block["page_height"]
    normalized = re.sub(r"\d+", "#", re.sub(r"\s+", " ", text.casefold())).strip()
    zone = "top" if y1 < page_height * 0.12 else "bottom" if y0 > page_height * 0.88 else "body"
    if (zone, normalized) in repeated:
        return "header_footer", "high"
    if re.match(r"^\s*(table|tab\.)\s+[A-Z0-9IVX]+(?:[.:]|\b)", first, re.I):
        return "caption_table", "high"
    if re.match(r"^\s*(figure|fig\.)\s+[A-Z0-9IVX]+(?:[.:]|\b)", first, re.I):
        return "caption_figure", "high"
    equation_signals = len(re.findall(r"[=∑∏∫√≤≥≈≡∂∆∇∞±×÷]|(?:\b(?:argmax|argmin|max|min)\b)", text))
    equation_label = bool(re.search(r"\([A-Za-z]?\d+(?:\.\d+)*\)\s*$", text))
    alpha_words = len(re.findall(r"\b[A-Za-z]{3,}\b", text))
    if (equation_label and equation_signals) or (equation_signals >= 2 and alpha_words <= 8 and len(text) <= 500):
        return "equation_candidate", "medium"
    if y0 > page_height * 0.82 and len(text) < 700:
        return "footnote", "medium"
    heading_patterns = (
        r"^(?:\d+(?:\.\d+)*|[A-Z])\s+[A-Z][^.!?]{1,100}$",
        r"^(?:abstract|introduction|conclusion|references|bibliography|appendix)(?:\b|$)",
    )
    if len(text.splitlines()) <= 2 and any(re.match(pattern, first, re.I) for pattern in heading_patterns):
        return "heading", "high"
    return "paragraph", "high"


def repeated_margin_blocks(blocks: list[dict[str, Any]], page_count: int) -> set[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for block in blocks:
        y0, y1 = block["bbox"][1], block["bbox"][3]
        height = block["page_height"]
        zone = "top" if y1 < height * 0.12 else "bottom" if y0 > height * 0.88 else "body"
        if zone == "body":
            continue
        value = re.sub(r"\d+", "#", re.sub(r"\s+", " ", block["raw_text"].casefold())).strip()
        counts[(zone, value)] += 1
    threshold = max(3, math.ceil(page_count * 0.2))
    return {key for key, count in counts.items() if count >= threshold}


def extract_ocr(render: Path) -> str:
    result = run(["tesseract", str(render), "stdout", "-l", "eng", "--psm", "1"], timeout=300)
    return result.stdout.decode("utf-8", "replace").strip()


def page_blocks(blocks: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        result[block["page"]].append(block)
    for rows in result.values():
        rows.sort(key=lambda row: (round(row["bbox"][1], 1), round(row["bbox"][0], 1)))
    return result


def build_markdown(
    pages: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    page_text: dict[int, tuple[str, str]],
    source_id: str,
) -> tuple[str, list[dict[str, Any]]]:
    by_page = page_blocks(blocks)
    pieces: list[str] = [
        "<!-- Generated by econ-review PDF ingestion. Rendered pages remain authoritative for visual and mathematical content. -->\n\n"
    ]
    position = len(pieces[0])
    output_blocks: list[dict[str, Any]] = []
    for page in pages:
        page_number = page["page"]
        header = f"<!-- PDF page {page_number} -->\n\n"
        pieces.append(header)
        position += len(header)
        rows = by_page.get(page_number, [])
        method = page_text[page_number][1]
        if method != "pdf_text_layer" or not rows:
            raw = page_text[page_number][0] if method == "ocr" else "[No usable text was recovered for this PDF page; inspect the page render.]"
            synthetic_count = sum(1 for row in output_blocks if row["kind"] in {"ocr_text", "bounded_page"})
            block_id = source_block_id(source_id, len(blocks) + synthetic_count + 1)
            marker = f"<!-- {block_id}; page={page_number}; bbox=0,0,{page['width']},{page['height']}; method={method} -->\n\n"
            pieces.append(marker)
            position += len(marker)
            start = position
            content = raw + "\n\n"
            pieces.append(content)
            position += len(content)
            output_blocks.append({
                "id": block_id, "page": page_number, "bbox": [0, 0, page["width"], page["height"]],
                "kind": "ocr_text" if method == "ocr" else "bounded_page", "raw_text": raw, "markdown_start": start,
                "markdown_end": start + len(raw), "sha256": sha256_bytes(raw.encode("utf-8")), "confidence": "low",
            })
            continue
        for row in rows:
            bbox = ",".join(str(value) for value in row["bbox"])
            marker = f"<!-- {row['id']}; page={page_number}; bbox={bbox}; method=pdf_text_layer -->\n\n"
            pieces.append(marker)
            position += len(marker)
            prefix = "## " if row["kind"] == "heading" else ""
            pieces.append(prefix)
            position += len(prefix)
            start = position
            raw = row["raw_text"]
            pieces.append(raw)
            position += len(raw)
            end = position
            pieces.append("\n\n")
            position += 2
            output_blocks.append({
                "id": row["id"], "page": page_number, "bbox": row["bbox"], "kind": row["kind"],
                "raw_text": raw, "markdown_start": start, "markdown_end": end,
                "sha256": sha256_bytes(raw.encode("utf-8")), "confidence": row["confidence"],
            })
    return "".join(pieces), output_blocks


def crop_render(render: Path, bbox: list[float], page_size: tuple[float, float], destination: Path) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise IngestionError(f"Pillow is required for object crops; install {SKILL_ROOT / 'requirements-core.txt'}") from exc
    with Image.open(render) as image:
        sx, sy = image.width / page_size[0], image.height / page_size[1]
        left = max(0, math.floor(bbox[0] * sx) - 12)
        top = max(0, math.floor(bbox[1] * sy) - 12)
        right = min(image.width, math.ceil(bbox[2] * sx) + 12)
        bottom = min(image.height, math.ceil(bbox[3] * sy) + 12)
        if right <= left or bottom <= top:
            raise IngestionError(f"invalid crop bounding box: {bbox}")
        cropped = image.crop((left, top, right, bottom)).convert("RGB")
        private_mkdir(destination.parent)
        cropped.save(destination, format="PNG", optimize=False)
        destination.chmod(0o600)


def overlaps(a: list[float], b: list[float], threshold: float = 0.4) -> bool:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return False
    intersection = (x1 - x0) * (y1 - y0)
    area = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return bool(area and intersection / area >= threshold)


def region_from_caption(block: dict[str, Any], kind: str, rows: list[dict[str, Any]]) -> list[float]:
    x0, y0, x1, y1 = block["bbox"]
    width, height = block["page_width"], block["page_height"]
    if kind == "figure":
        prior = [row["bbox"][3] for row in rows if row["bbox"][3] <= y0 and row["id"] != block["id"]]
        top = max(prior, default=max(0.0, y0 - height * 0.45))
        if y0 - top < height * 0.08:
            top = max(0.0, y0 - height * 0.4)
        return [max(0.0, x0 - 18), top, min(width, x1 + 18), min(height, y1 + 12)]
    following = [row["bbox"][1] for row in rows if row["bbox"][1] >= y1 and row["id"] != block["id"]]
    bottom = min(following, default=min(height, y1 + height * 0.45))
    if bottom - y1 < height * 0.08:
        bottom = min(height, y1 + height * 0.4)
    return [max(0.0, x0 - 18), max(0.0, y0 - 12), min(width, x1 + 18), bottom]


def table_candidates(pdf: Path) -> dict[int, list[dict[str, Any]]]:
    try:
        import pdfplumber
    except ImportError:
        return {}
    output: dict[int, list[dict[str, Any]]] = defaultdict(list)
    try:
        with pdfplumber.open(pdf) as document:
            for page_number, page in enumerate(document.pages, 1):
                try:
                    found = page.find_tables(table_settings={
                        "vertical_strategy": "lines", "horizontal_strategy": "lines",
                        "snap_tolerance": 3, "join_tolerance": 3, "intersection_tolerance": 4,
                    })
                except Exception:
                    continue
                for table in found:
                    grid = table.extract() or []
                    if len(grid) < 2 or max((len(row) for row in grid), default=0) < 2:
                        continue
                    bbox = [round(float(value), 3) for value in table.bbox]
                    output[page_number].append({"bbox": bbox, "grid": grid, "strategy": "pdfplumber_lines"})
    except Exception:
        return {}
    return output


def rectangular(grid: list[list[Any]]) -> bool:
    return bool(grid) and len({len(row) for row in grid}) == 1


def markdown_table(grid: list[list[Any]]) -> str:
    rows = [[str(cell or "").replace("\n", " ").replace("|", "\\|").strip() for cell in row] for row in grid]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return "\n".join(lines) + "\n"


def create_objects(
    stage: Path,
    output_prefix: str,
    source_id: str,
    pdf: Path,
    pages: list[dict[str, Any]],
    raw_blocks: list[dict[str, Any]],
    rendered: list[Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_page = page_blocks(raw_blocks)
    detected_tables = table_candidates(pdf)
    tables: list[dict[str, Any]] = []
    figures: list[dict[str, Any]] = []
    equations: list[dict[str, Any]] = []
    page_by_number = {page["page"]: page for page in pages}

    def add_object(collection: list[dict[str, Any]], kind: str, page: int, bbox: list[float], caption: str | None,
                   transcription: dict[str, Any] | None, status: str, warnings: list[str]) -> None:
        number = len(collection) + 1
        object_id = source_object_id(source_id, kind, number)
        folder = {"TBL": "tables", "FIG": "figures", "EQ": "equations"}[kind]
        relative = Path("objects") / folder / f"{object_id}.png"
        destination = stage / relative
        metadata = page_by_number[page]
        crop_render(rendered[page - 1], bbox, (metadata["width"], metadata["height"]), destination)
        record = {
            "id": object_id, "page": page, "bbox": [round(value, 3) for value in bbox], "caption": caption,
            "crop_path": f"{output_prefix}/{relative.as_posix()}", "crop_sha256": sha256_file(destination),
            "transcription": transcription, "status": status, "warnings": warnings,
        }
        collection.append(record)

    for page in pages:
        page_number = page["page"]
        rows = by_page.get(page_number, [])
        used_table_boxes: list[list[float]] = []
        for candidate in detected_tables.get(page_number, []):
            bbox, grid = candidate["bbox"], candidate["grid"]
            nearby = [row for row in rows if row["kind"] == "caption_table" and abs(row["bbox"][1] - bbox[1]) < page["height"] * 0.25]
            caption = min(nearby, key=lambda row: abs(row["bbox"][1] - bbox[1]))["raw_text"] if nearby else None
            table_number = len(tables) + 1
            table_id = source_object_id(source_id, "TBL", table_number)
            md_relative = Path("objects/tables") / f"{table_id}.md"
            csv_relative = Path("objects/tables") / f"{table_id}.csv"
            private_write(stage / md_relative, markdown_table(grid).encode("utf-8"))
            csv_path: str | None = None
            csv_sha256: str | None = None
            if rectangular(grid):
                buffer = io.StringIO(newline="")
                writer = csv.writer(buffer, lineterminator="\n")
                writer.writerows([[cell or "" for cell in row] for row in grid])
                private_write(stage / csv_relative, buffer.getvalue().encode("utf-8"))
                csv_path = f"{output_prefix}/{csv_relative.as_posix()}"
                csv_sha256 = sha256_file(stage / csv_relative)
            transcription = {
                "representation": "candidate_grid", "strategy": candidate["strategy"], "grid": grid,
                "markdown_path": f"{output_prefix}/{md_relative.as_posix()}",
                "markdown_sha256": sha256_file(stage / md_relative),
                "csv_path": csv_path, "csv_sha256": csv_sha256,
                "rectangular": rectangular(grid),
            }
            add_object(
                tables, "TBL", page_number, bbox, caption, transcription,
                "candidate_needs_visual_verification",
                ["A detected grid is not authoritative until every cell, header, span, note, and blank is checked against the crop."],
            )
            used_table_boxes.append(bbox)
        for caption in [row for row in rows if row["kind"] == "caption_table"]:
            if any(overlaps(caption["bbox"], bbox, 0.01) or abs(caption["bbox"][1] - bbox[1]) < page["height"] * 0.25 for bbox in used_table_boxes):
                continue
            bbox = region_from_caption(caption, "table", rows)
            add_object(
                tables, "TBL", page_number, bbox, caption["raw_text"], None, "bounded",
                ["Caption-driven table crop found, but no reliable rectangular grid was recovered; read the rendered crop directly."],
            )
        for caption in [row for row in rows if row["kind"] == "caption_figure"]:
            bbox = region_from_caption(caption, "figure", rows)
            add_object(
                figures, "FIG", page_number, bbox, caption["raw_text"],
                {"representation": "rendered_region", "caption_block_id": caption["id"]},
                "candidate_needs_visual_verification",
                ["The crop is caption-driven and may need manual panel-boundary adjustment; vector figures are preserved through the render."],
            )
        for equation in [row for row in rows if row["kind"] == "equation_candidate"]:
            bbox = [max(0.0, equation["bbox"][0] - 18), max(0.0, equation["bbox"][1] - 12),
                    min(page["width"], equation["bbox"][2] + 18), min(page["height"], equation["bbox"][3] + 12)]
            add_object(
                equations, "EQ", page_number, bbox, None,
                {"representation": "raw_glyph_candidate", "raw_unicode": equation["raw_text"], "latex": None,
                 "block_id": equation["id"]},
                "bounded",
                ["Generic PDF extraction cannot verify mathematical semantics; the crop is authoritative until source TeX or manual render verification resolves it."],
            )
    return tables, figures, equations


def symbol_inventory(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    occurrences: dict[str, list[dict[str, Any]]] = defaultdict(list)
    definition_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    math_blocks = {row["id"] for row in blocks if row["kind"] == "equation_candidate"}
    for block in blocks:
        text = block["raw_text"]
        symbols: set[str] = set()
        for char in text:
            category = unicodedata.category(char)
            name = unicodedata.name(char, "")
            if category in {"Sm", "Sk"} or "GREEK" in name or category in {"Lm"} or char in "₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹":
                symbols.add(char)
        if block["id"] in math_blocks:
            symbols.update(re.findall(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])", text))
        for symbol in symbols:
            context = re.sub(r"\s+", " ", text).strip()[:240]
            row = {"page": block["page"], "block_id": block["id"], "bbox": block["bbox"], "context": context}
            occurrences[symbol].append(row)
            escaped = re.escape(symbol)
            if re.search(rf"(?:where|let|denote[sd]?|define[sd]?|called)\s+[^.\n]{{0,80}}{escaped}|{escaped}\s+(?:is|denotes|represents)", text, re.I):
                definition_candidates[symbol].append(row)
    result: list[dict[str, Any]] = []
    confusable = {"l": "Latin l can resemble 1", "O": "Latin O can resemble zero", "v": "Latin v can resemble Greek nu",
                  "ν": "Greek nu can resemble Latin v", "−": "mathematical minus can be confused with a hyphen", "-": "hyphen can be used in place of mathematical minus"}
    for symbol in sorted(occurrences, key=lambda value: [ord(char) for char in value]):
        warnings: list[str] = []
        if symbol in confusable:
            warnings.append(confusable[symbol])
        normalized = unicodedata.normalize("NFC", symbol)
        if normalized != symbol:
            warnings.append("NFC normalization changes this glyph sequence; preserve the raw occurrence for verification")
        result.append({
            "symbol": symbol,
            "codepoints": [f"U+{ord(char):04X}" for char in symbol],
            "normalized": normalized,
            "occurrences": occurrences[symbol],
            "definition_candidates": definition_candidates.get(symbol, []),
            "warnings": warnings,
        })
    return result


def build_source_manifest(
    review_id: str, source_id: str, role: str, output_prefix: str, source_sha: str, markdown: str,
    blocks: list[dict[str, Any]], ingestion_sha: str, fingerprint: str,
) -> dict[str, Any]:
    source_path = f"{output_prefix}/source/original.pdf"
    markdown_path = f"{output_prefix}/manuscript.md"
    anchors: list[dict[str, Any]] = []
    kind_map = {"equation_candidate": "equation", "caption_table": "table_cell", "caption_figure": "figure"}
    for index, block in enumerate(blocks, 1):
        start, end = block["markdown_start"], block["markdown_end"]
        content = markdown[start:end]
        anchors.append({
            "id": source_anchor_id(source_id, index), "source_id": source_id,
            "kind": kind_map.get(block["kind"], "text_span"),
            "start_char": start, "end_char": end, "content_sha256": sha256_bytes(content.encode("utf-8")),
            "locator": f"PDF p. {block['page']}, bbox {','.join(str(value) for value in block['bbox'])}, block {block['id']}",
        })
    return {
        "schema_version": "0.1", "review_id": review_id,
        "sources": [{
            "id": source_id, "role": role, "path": source_path, "media_type": "application/pdf", "sha256": source_sha,
            "extraction": {
                "path": markdown_path, "sha256": sha256_bytes(markdown.encode("utf-8")), "normalization": "none",
                "ingestion_manifest_path": f"{output_prefix}/ingestion.json",
                "ingestion_manifest_sha256": ingestion_sha,
                "pipeline_fingerprint": fingerprint,
            },
        }],
        "anchors": anchors,
    }


def pipeline_fingerprint(
    configuration: dict[str, Any], toolchain: dict[str, Any], *, pipeline_version: str = PIPELINE_VERSION,
) -> str:
    return sha256_bytes(canonical_json({
        "pipeline_version": pipeline_version, "configuration": configuration,
        "tools": toolchain,
        "normalization": (
            "raw UTF-8 blocks with LF line endings; no NFKC or dehyphenation; "
            "XML-forbidden controls removed only from Poppler XHTML parser input with hashes and counts recorded"
        ),
    }))


def validate_schema(value: dict[str, Any]) -> list[str]:
    try:
        import jsonschema
    except ImportError as exc:
        raise IngestionError(f"jsonschema is required; install {SKILL_ROOT / 'requirements-core.txt'}") from exc
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    return [f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}" for error in validator.iter_errors(value)]


def package_path(review_dir: Path, relative: str) -> Path:
    relative = safe_relative(relative)
    root = review_dir.resolve()
    target = root / relative
    if target.is_symlink():
        raise IngestionError(f"package artifact is a symbolic link: {relative}")
    try:
        target.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise IngestionError(f"package artifact escapes review directory: {relative}") from exc
    return target


def infer_review_root(package_dir: Path, manifest: dict[str, Any]) -> Path:
    raw_source = manifest.get("source", {}).get("package_path")
    if not isinstance(raw_source, str):
        raise IngestionError("ingestion source.package_path is missing")
    source_relative = Path(safe_relative(raw_source))
    if len(source_relative.parts) < 3 or source_relative.parts[-2:] != ("source", "original.pdf"):
        raise IngestionError("ingestion source path must end in source/original.pdf")
    expected_package = source_relative.parent.parent
    review_dir = package_dir.resolve()
    for _ in expected_package.parts:
        review_dir = review_dir.parent
    expected = (review_dir / expected_package).resolve(strict=False)
    if expected != package_dir.resolve():
        raise IngestionError("ingestion package location does not match its declared package paths")
    return review_dir


def valid_bbox(bbox: Any, page: dict[str, Any]) -> bool:
    if not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(value, (int, float)) for value in bbox):
        return False
    x0, y0, x1, y1 = bbox
    return 0 <= x0 < x1 <= page.get("width_points", 0) and 0 <= y0 < y1 <= page.get("height_points", 0)


def verify_package(package_dir: Path, *, quiet: bool = False) -> list[str]:
    errors: list[str] = []
    try:
        package_dir = regular_file(package_dir / "ingestion.json", "ingestion manifest").parent
    except IngestionError as exc:
        errors.append(str(exc))
        if not quiet:
            print(f"PDF ingestion verification failed: {len(errors)} error(s)", file=sys.stderr)
            print(f"- {exc}", file=sys.stderr)
        return errors
    try:
        value = json.loads((package_dir / "ingestion.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"cannot read ingestion.json: {exc}"]
    try:
        schema_errors = validate_schema(value)
    except IngestionError as exc:
        schema_errors = [str(exc)]
    errors.extend(schema_errors)
    if schema_errors:
        if not quiet:
            print(f"PDF ingestion verification failed: {len(errors)} error(s)", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
        return errors
    try:
        review_dir = infer_review_root(package_dir, value)
    except IngestionError as exc:
        return [str(exc)]

    artifact_results: dict[str, bool] = {}

    def verify_artifact(path: Any, expected: Any, label: str) -> None:
        if not isinstance(path, str) or not isinstance(expected, str):
            errors.append(f"{label} path/hash declaration is incomplete")
            return
        try:
            observed = sha256_file(regular_file(package_path(review_dir, path), label))
        except (OSError, IngestionError) as exc:
            errors.append(str(exc))
            artifact_results[label] = False
        else:
            artifact_results[label] = observed == expected
            if observed != expected:
                errors.append(f"{label} hash mismatch")

    for path, expected, label in [
        (value.get("source", {}).get("package_path"), value.get("source", {}).get("sha256"), "source"),
        (value.get("markdown", {}).get("path"), value.get("markdown", {}).get("sha256"), "Markdown"),
    ]:
        verify_artifact(path, expected, label)
    artifacts: list[tuple[str, str, str]] = []
    for page in value.get("pages", []):
        artifacts.extend([
            (page.get("text_path"), page.get("text_sha256"), f"page {page.get('page')} text"),
            (page.get("native_text_path"), page.get("native_text_sha256"), f"page {page.get('page')} native text"),
            (page.get("render_path"), page.get("render_sha256"), f"page {page.get('page')} render"),
        ])
        if page.get("ocr_text_path") is not None or page.get("ocr_text_sha256") is not None:
            artifacts.append((page.get("ocr_text_path"), page.get("ocr_text_sha256"), f"page {page.get('page')} OCR text"))
        if (page.get("ocr_text_path") is None) != (page.get("ocr_text_sha256") is None):
            errors.append(f"page {page.get('page')} OCR path/hash must both be null or both be strings")
        selected = {
            "pdf_text_layer": (page.get("native_text_path"), page.get("native_text_sha256"), "extracted"),
            "ocr": (page.get("ocr_text_path"), page.get("ocr_text_sha256"), "ocr_fallback"),
            "none": (page.get("native_text_path"), page.get("native_text_sha256"), "bounded"),
        }.get(page.get("text_method"))
        if selected and (page.get("text_path"), page.get("text_sha256"), page.get("status")) != selected:
            errors.append(f"page {page.get('page')} selected text does not match its declared method/status")
    for collection in ("tables", "figures", "equations"):
        for row in value.get(collection, []):
            artifacts.append((row.get("crop_path"), row.get("crop_sha256"), row.get("id", collection)))
            transcription = row.get("transcription")
            if isinstance(transcription, dict):
                for field, hash_field, suffix in (
                    ("markdown_path", "markdown_sha256", "candidate Markdown"),
                    ("csv_path", "csv_sha256", "candidate CSV"),
                ):
                    if transcription.get(field) is not None or transcription.get(hash_field) is not None:
                        artifacts.append((transcription.get(field), transcription.get(hash_field), f"{row.get('id')} {suffix}"))
                    if (transcription.get(field) is None) != (transcription.get(hash_field) is None):
                        errors.append(f"{row.get('id')} {field}/{hash_field} must both be null or both be strings")
    proposal = value.get("proposal")
    if isinstance(proposal, dict):
        artifacts.append((proposal.get("path"), proposal.get("sha256"), "MarkItDown proposal"))
    proposals = value.get("proposals", []) if isinstance(value.get("proposals"), list) else []
    proposal_ids = [row.get("id") for row in proposals if isinstance(row, dict)]
    if len(proposal_ids) != len(set(proposal_ids)):
        errors.append("semantic proposal IDs are not unique")
    proposal_engines = [row.get("engine") for row in proposals if isinstance(row, dict)]
    if len(proposal_engines) != len(set(proposal_engines)):
        errors.append("semantic proposal engines are not unique")
    source_sha = value.get("source", {}).get("sha256")
    for proposal_row in proposals:
        if proposal_row.get("input_sha256") != source_sha:
            errors.append(f"{proposal_row.get('id')} input hash differs from the source PDF")
        processing = proposal_row.get("processing", {})
        if proposal_row.get("mode") == "remote":
            if processing.get("manuscript_uploaded") is not True or processing.get("user_authorized") is not True:
                errors.append(f"{proposal_row.get('id')} remote upload lacks affirmative authorization")
            if processing.get("credential_source") != "environment":
                errors.append(f"{proposal_row.get('id')} remote credentials must come from the environment")
            if processing.get("remote_deletion") != "confirmed":
                errors.append(f"{proposal_row.get('id')} remote deletion is not confirmed")
        else:
            if processing.get("manuscript_uploaded") is not False:
                errors.append(f"{proposal_row.get('id')} local backend cannot declare a manuscript upload")
            if processing.get("credential_source") != "none":
                errors.append(f"{proposal_row.get('id')} local backend cannot declare remote credentials")
        for index, artifact in enumerate(proposal_row.get("artifacts", []), 1):
            artifacts.append((
                artifact.get("path"), artifact.get("sha256"),
                f"{proposal_row.get('id', 'proposal')} artifact {index}",
            ))
    for path, expected, label in artifacts:
        verify_artifact(path, expected, label)

    if value.get("schema_version") == "0.2":
        configuration = value.get("configuration", {})
        if configuration.get("mathpix") != ("mathpix" in proposal_engines):
            errors.append("Mathpix configuration and proposal inventory disagree")
        if configuration.get("network_services") == "forbidden" and any(
            row.get("mode") == "remote" for row in proposals
        ):
            errors.append("a remote proposal exists although network services are forbidden")
        serialized = json.dumps(value, sort_keys=True).casefold()
        for forbidden_key in ('"app_key"', '"mathpix_app_key"', '"authorization"'):
            if forbidden_key in serialized:
                errors.append("ingestion manifest contains a forbidden credential field")
        reconciliation = value.get("reconciliation", {})
        verify_artifact(
            reconciliation.get("packets_path"), reconciliation.get("packets_sha256"),
            "reconciliation page packets",
        )
        if reconciliation.get("canonical_path") != value.get("markdown", {}).get("path"):
            errors.append("reconciliation canonical path differs from the evidence Markdown")
        if reconciliation.get("canonical_sha256") != value.get("markdown", {}).get("sha256"):
            errors.append("reconciliation canonical hash differs from the evidence Markdown")
        unresolved = reconciliation.get("unresolved", {})
        expected_unresolved = {
            "pages": sum(1 for row in value.get("pages", []) if row.get("status") == "bounded"),
            "tables": len(value.get("tables", [])),
            "figures": len(value.get("figures", [])),
            "equations": len(value.get("equations", [])),
        }
        if unresolved != expected_unresolved:
            errors.append("reconciliation unresolved counts differ from the package inventory")
        packets_path = reconciliation.get("packets_path")
        if isinstance(packets_path, str):
            try:
                packets = json.loads(package_path(review_dir, packets_path).read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError, IngestionError) as exc:
                errors.append(f"cannot read reconciliation page packets: {exc}")
            else:
                errors.extend(packet_errors(packets, value))
                expected_packets = build_page_packets(
                    source_sha256=value["source"]["sha256"], pages=value["pages"],
                    blocks=value["blocks"], tables=value["tables"], figures=value["figures"],
                    equations=value["equations"], proposals=value["proposals"],
                    proposal_page_index=load_proposal_page_index(
                        review_dir,
                        str(Path(value["source"]["package_path"]).parent.parent),
                        value["proposals"],
                    ),
                )
                if packets != expected_packets:
                    errors.append("reconciliation page packets are not reproducible from declared evidence")
        expected_reconciliation = "packets_ready"
        if reconciliation.get("status") != expected_reconciliation:
            errors.append("reconciliation status differs from the proposal inventory")

    markdown_path = value.get("markdown", {}).get("path")
    markdown = ""
    if isinstance(markdown_path, str):
        try:
            markdown = package_path(review_dir, markdown_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError, IngestionError) as exc:
            errors.append(f"cannot read Markdown for span verification: {exc}")
        else:
            previous_end = -1
            for block in sorted(value.get("blocks", []), key=lambda row: row.get("markdown_start", -1)):
                start, end = block.get("markdown_start"), block.get("markdown_end")
                if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start or end > len(markdown):
                    errors.append(f"{block.get('id')} has invalid Markdown span")
                    continue
                if start < previous_end:
                    errors.append(f"{block.get('id')} Markdown span overlaps a prior block")
                previous_end = max(previous_end, end)
                if sha256_bytes(markdown[start:end].encode("utf-8")) != block.get("sha256"):
                    errors.append(f"{block.get('id')} Markdown span hash mismatch")
                if markdown[start:end] != block.get("raw_text"):
                    errors.append(f"{block.get('id')} raw text differs from its Markdown span")

    pages = value.get("pages", [])
    expected_pages = value.get("source", {}).get("page_count")
    if [row.get("page") for row in pages] != list(range(1, (expected_pages or 0) + 1)):
        errors.append("page inventory is not complete and ordered")
    page_by_number = {row.get("page"): row for row in pages if isinstance(row, dict)}
    source_id = value.get("source_id")
    expected_fingerprint = pipeline_fingerprint(
        {
            **value.get("configuration", {}),
            "source_id": source_id,
            "source_role": value.get("source_role"),
        },
        value.get("toolchain", {}),
        pipeline_version=value.get("schema_version", PIPELINE_VERSION),
    )
    if value.get("pipeline_fingerprint") != expected_fingerprint:
        errors.append("pipeline fingerprint does not match the declared configuration and toolchain")
    blocks = value.get("blocks", []) if isinstance(value.get("blocks"), list) else []
    block_ids = [row.get("id") for row in blocks if isinstance(row, dict)]
    if len(block_ids) != len(set(block_ids)):
        errors.append("block IDs are not unique")
    block_by_id = {row.get("id"): row for row in blocks if isinstance(row, dict)}
    for block in blocks:
        block_id, page_number = block.get("id"), block.get("page")
        if not isinstance(block_id, str) or not block_id.startswith(f"{source_id}-PDF-B"):
            errors.append(f"block {block_id} is not qualified by source {source_id}")
        page = page_by_number.get(page_number)
        if page is None:
            errors.append(f"block {block_id} references unknown page {page_number}")
        elif not valid_bbox(block.get("bbox"), page):
            errors.append(f"block {block_id} has invalid or out-of-page bounds")

    object_ids: list[str] = []
    for collection, kind in (("tables", "TBL"), ("figures", "FIG"), ("equations", "EQ")):
        for row in value.get(collection, []):
            object_id, page_number = row.get("id"), row.get("page")
            object_ids.append(object_id)
            if not isinstance(object_id, str) or not object_id.startswith(f"{source_id}-PDF-{kind}-"):
                errors.append(f"{collection} object {object_id} is not qualified by source {source_id}")
            page = page_by_number.get(page_number)
            if page is None:
                errors.append(f"object {object_id} references unknown page {page_number}")
            elif not valid_bbox(row.get("bbox"), page):
                errors.append(f"object {object_id} has invalid or out-of-page bounds")
            transcription = row.get("transcription")
            if isinstance(transcription, dict):
                reference = transcription.get("block_id") or transcription.get("caption_block_id")
                if reference is not None:
                    block = block_by_id.get(reference)
                    if block is None:
                        errors.append(f"object {object_id} references unknown block {reference}")
                    elif block.get("page") != page_number:
                        errors.append(f"object {object_id} references a block on another page")
    if len(object_ids) != len(set(object_ids)):
        errors.append("PDF object IDs are not unique")

    for symbol in value.get("symbols", []):
        for field in ("occurrences", "definition_candidates"):
            for occurrence in symbol.get(field, []):
                block = block_by_id.get(occurrence.get("block_id"))
                if block is None:
                    errors.append(f"symbol {symbol.get('symbol')} references unknown block {occurrence.get('block_id')}")
                elif occurrence.get("page") != block.get("page"):
                    errors.append(f"symbol {symbol.get('symbol')} occurrence page differs from its block")
                page = page_by_number.get(occurrence.get("page"))
                if page is not None and not valid_bbox(occurrence.get("bbox"), page):
                    errors.append(f"symbol {symbol.get('symbol')} occurrence has invalid bounds")

    fragment_path = package_dir / "source-manifest.generated.json"
    try:
        fragment = json.loads(regular_file(fragment_path, "generated source manifest").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, IngestionError) as exc:
        errors.append(f"cannot verify generated source manifest: {exc}")
    else:
        sources = fragment.get("sources", []) if isinstance(fragment, dict) else []
        expected_source = sources[0] if len(sources) == 1 and isinstance(sources[0], dict) else {}
        extraction = expected_source.get("extraction", {}) if isinstance(expected_source.get("extraction"), dict) else {}
        if fragment.get("review_id") != value.get("review_id") or expected_source.get("id") != source_id:
            errors.append("generated source manifest identity differs from ingestion.json")
        if expected_source.get("role") != value.get("source_role"):
            errors.append("generated source manifest role differs from ingestion.json")
        if expected_source.get("sha256") != value.get("source", {}).get("sha256"):
            errors.append("generated source manifest source hash differs from ingestion.json")
        if extraction.get("path") != value.get("markdown", {}).get("path") or extraction.get("sha256") != value.get("markdown", {}).get("sha256"):
            errors.append("generated source manifest Markdown differs from ingestion.json")
        if extraction.get("ingestion_manifest_path") != f"{value.get('source', {}).get('package_path', '').rsplit('/source/original.pdf', 1)[0]}/ingestion.json":
            errors.append("generated source manifest ingestion path differs from package location")
        if extraction.get("ingestion_manifest_sha256") != sha256_file(package_dir / "ingestion.json"):
            errors.append("generated source manifest ingestion hash differs from ingestion.json")
        if extraction.get("pipeline_fingerprint") != value.get("pipeline_fingerprint"):
            errors.append("generated source manifest pipeline fingerprint differs from ingestion.json")
        anchors = fragment.get("anchors", []) if isinstance(fragment, dict) else []
        if len(anchors) != len(blocks) or len({row.get("id") for row in anchors if isinstance(row, dict)}) != len(anchors):
            errors.append("generated source manifest anchors are incomplete or not unique")
        for index, (anchor, block) in enumerate(zip(anchors, blocks), 1):
            if anchor.get("id") != source_anchor_id(source_id, index) or anchor.get("source_id") != source_id:
                errors.append(f"generated source anchor {index} is not source-qualified")
            if (anchor.get("start_char"), anchor.get("end_char"), anchor.get("content_sha256")) != (
                block.get("markdown_start"), block.get("markdown_end"), block.get("sha256"),
            ):
                errors.append(f"generated source anchor {anchor.get('id')} differs from its canonical block")

    quality = value.get("quality", {})
    parser_repairs = value.get("parser_repairs", {})
    repair_count = parser_repairs.get("xml_forbidden_control_count", 0)
    repair_codepoints = parser_repairs.get("xml_forbidden_codepoints", [])
    if repair_count == 0 and repair_codepoints:
        errors.append("parser repair codepoints must be empty when no forbidden controls were removed")
    if repair_count == 0 and parser_repairs.get("raw_xhtml_sha256") != parser_repairs.get("parser_input_sha256"):
        errors.append("parser XHTML hashes differ although no forbidden controls were removed")
    if repair_count > 0:
        if not repair_codepoints:
            errors.append("parser repair codepoints are missing for removed forbidden controls")
        if parser_repairs.get("raw_xhtml_sha256") == parser_repairs.get("parser_input_sha256"):
            errors.append("parser XHTML hashes must differ when forbidden controls were removed")
        if not any("XML-forbidden control" in warning for warning in quality.get("warnings", [])):
            errors.append("parser control repair is not disclosed in quality warnings")
    if quality.get("status") == "failed":
        errors.append("ingestion quality status is failed")
    if quality.get("page_count_match") is not ([row.get("page") for row in pages] == list(range(1, (expected_pages or 0) + 1))):
        errors.append("quality.page_count_match is inconsistent with the page inventory")
    if quality.get("all_pages_rendered") is not True:
        errors.append("quality.all_pages_rendered must be true for a committed ingestion")
    if quality.get("all_pages_have_text_or_boundary") is not all(row.get("status") in {"extracted", "ocr_fallback", "bounded"} for row in pages):
        errors.append("quality.all_pages_have_text_or_boundary is inconsistent with page states")
    expected_crop_state = all(isinstance(row.get("crop_sha256"), str) for key in ("tables", "figures", "equations") for row in value.get(key, []))
    if quality.get("object_crops_hashed") is not expected_crop_state:
        errors.append("quality.object_crops_hashed is inconsistent with object declarations")
    expected_span_state = all(
        isinstance(row.get("markdown_start"), int) and isinstance(row.get("markdown_end"), int)
        and 0 <= row["markdown_start"] < row["markdown_end"] <= len(markdown)
        and markdown[row["markdown_start"]:row["markdown_end"]] == row.get("raw_text")
        for row in blocks
    )
    if quality.get("anchor_spans_valid") is not expected_span_state:
        errors.append("quality.anchor_spans_valid is inconsistent with canonical Markdown")
    if not quiet:
        if errors:
            print(f"PDF ingestion verification failed: {len(errors)} error(s)", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
        else:
            print(f"PDF ingestion verified: {package_dir}")
    return errors


def ingest(args: argparse.Namespace) -> Path:
    if not 1 <= args.max_pages <= MAX_PAGES_DEFAULT:
        raise IngestionError(f"--max-pages must be between 1 and {MAX_PAGES_DEFAULT}")
    if not 1 <= args.max_bytes <= MAX_BYTES_DEFAULT:
        raise IngestionError(f"--max-bytes must be between 1 and {MAX_BYTES_DEFAULT}")
    if not 60 <= args.docling_timeout <= 86_400:
        raise IngestionError("--docling-timeout must be between 60 and 86400 seconds")
    if not 60 <= args.mathpix_timeout <= 86_400:
        raise IngestionError("--mathpix-timeout must be between 60 and 86400 seconds")
    if not 0.1 <= args.mathpix_poll_interval <= 60:
        raise IngestionError("--mathpix-poll-interval must be between 0.1 and 60 seconds")
    for required in ("pdfinfo", "pdftotext", "pdftoppm"):
        if not command_path(required):
            raise IngestionError(f"{required} is required; install Poppler and run the doctor command")
    for package in ("pypdf", "Pillow", "jsonschema"):
        if not python_package_version(package):
            raise IngestionError(
                f"Python package {package} is required; install {SKILL_ROOT / 'requirements-core.txt'}"
            )
    source_id = validate_source_id(args.source_id)
    source = regular_file(args.pdf, "input PDF")
    if source.suffix.casefold() != ".pdf":
        raise IngestionError("input must use a .pdf extension")
    review_dir = args.review_dir.resolve()
    if review_dir.is_symlink():
        raise IngestionError("review directory must not be a symbolic link")
    private_mkdir(review_dir)
    output = args.output if args.output is not None else DEFAULT_OUTPUT_ROOT / source_id
    output_rel = safe_relative(output)
    destination = package_path(review_dir, output_rel)
    source_sha = sha256_file(source)
    if args.mathpix and args.authorize_external_upload != "mathpix":
        raise IngestionError("Mathpix requires --authorize-external-upload mathpix")
    if args.mathpix and not args.accept_mathpix_retention:
        raise IngestionError("Mathpix requires --accept-mathpix-retention")
    configuration = {
        "dpi": args.dpi, "ocr": args.ocr, "max_pages": args.max_pages, "max_bytes": args.max_bytes,
        "markitdown_proposal": args.markitdown_proposal,
        "semantic_backend": args.semantic_backend,
        "allow_model_downloads": args.allow_model_downloads,
        "docling_formulas": args.docling_formulas,
        "docling_timeout": args.docling_timeout,
        "docling_device": args.docling_device,
        "mathpix": args.mathpix,
        "mathpix_timeout": args.mathpix_timeout,
        "mathpix_poll_interval": args.mathpix_poll_interval,
        "external_upload_authorization": args.authorize_external_upload,
        "mathpix_retention_accepted": args.accept_mathpix_retention,
        "network_services": "mathpix_authorized" if args.mathpix else "forbidden",
    }
    toolchain = toolchain_for(args)
    fingerprint = pipeline_fingerprint(
        {**configuration, "source_id": source_id, "source_role": args.role}, toolchain,
    )
    existing_manifest = destination / "ingestion.json"
    if existing_manifest.exists() and not args.force:
        try:
            existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        same_request = (
            existing.get("source", {}).get("sha256") == source_sha
            and existing.get("review_id") == args.review_id
            and existing.get("source_id") == source_id
            and existing.get("source_role") == args.role
            and existing.get("configuration") == configuration
            and existing.get("pipeline_fingerprint") == fingerprint
        )
        if same_request and not verify_package(destination, quiet=True):
            print(f"PDF ingestion already current: {destination}")
            return destination
        raise IngestionError(f"output already exists and differs or fails verification: {destination}; use --force to replace atomically")

    parent = destination.parent
    private_mkdir(parent)
    stage: Path | None = Path(tempfile.mkdtemp(prefix=f".{destination.name}.stage-", dir=parent))
    stage.chmod(0o700)
    backup: Path | None = None
    try:
        assert stage is not None
        source_copy = stage / "source/original.pdf"
        private_mkdir(source_copy.parent)
        shutil.copyfile(source, source_copy)
        source_copy.chmod(0o600)
        page_count, encrypted, preflight_warnings = pdf_security_preflight(
            source_copy, max_pages=args.max_pages, max_bytes=args.max_bytes,
        )
        preflight_warnings.extend(inspect_pdf_safety(source_copy))
        rendered = render_pages(source_copy, stage / "renders", args.dpi, page_count)
        pages, raw_blocks, parser_repairs = parse_bbox_layout(source_copy, stage, source_id)
        if len(pages) != page_count:
            raise IngestionError(f"bbox extractor returned {len(pages)} pages; PDF declares {page_count}")
        if parser_repairs["xml_forbidden_control_count"]:
            preflight_warnings.append(
                "Poppler bbox XHTML contained "
                f"{parser_repairs['xml_forbidden_control_count']} XML-forbidden control character(s) "
                f"({', '.join(parser_repairs['xml_forbidden_codepoints'])}); removed only from parser input, "
                "while the original PDF and page renders remain authoritative"
            )
        repeated = repeated_margin_blocks(raw_blocks, page_count)
        for block in raw_blocks:
            block["kind"], block["confidence"] = classify_block(block, repeated)

        by_page = page_blocks(raw_blocks)
        page_text: dict[int, tuple[str, str]] = {}
        page_records: list[dict[str, Any]] = []
        ocr_available = bool(command_path("tesseract"))
        overall_warnings = list(preflight_warnings)
        for page in pages:
            number = page["page"]
            native = "\n\n".join(row["raw_text"] for row in by_page.get(number, [])).strip()
            method = "pdf_text_layer"
            text = native
            ocr_text: str | None = None
            warnings: list[str] = []
            native_controls = controls(native)
            if native_controls:
                warnings.append("native text contains control glyphs: " + ", ".join(native_controls))
            poor_native = len(re.sub(r"\s+", "", native)) < MIN_NATIVE_CHARACTERS or bool(native_controls)
            should_ocr = args.ocr == "always" or (args.ocr == "auto" and poor_native)
            if should_ocr and ocr_available:
                ocr_text = extract_ocr(rendered[number - 1])
                if ocr_text:
                    text = ocr_text
                    method = "ocr"
                    warnings.append("local OCR selected because native text was absent, sparse, damaged, or OCR was explicitly required")
                else:
                    warnings.append("local OCR returned no text; usable native text was retained when available")
            elif should_ocr and not ocr_available:
                warnings.append("local OCR was indicated but Tesseract is unavailable")
            if not text:
                method = "none"
                warnings.append("no usable page text was recovered; use the page render")
            page_text[number] = (text, method)
            native_rel = Path("pages") / f"page-{number:04d}.native.txt"
            private_write(stage / native_rel, (native + ("\n" if native else "")).encode("utf-8"))
            ocr_rel: Path | None = None
            if ocr_text is not None:
                ocr_rel = Path("pages") / f"page-{number:04d}.ocr.txt"
                private_write(stage / ocr_rel, (ocr_text + ("\n" if ocr_text else "")).encode("utf-8"))
            text_rel = ocr_rel if method == "ocr" and ocr_rel is not None else native_rel
            render_rel = Path("renders") / f"page-{number:04d}.png"
            replacement = text.count("�")
            private_use = sum(1 for char in text if unicodedata.category(char) == "Co")
            if replacement:
                warnings.append(f"{replacement} Unicode replacement character(s) require render verification")
            if private_use:
                warnings.append(f"{private_use} private-use glyph(s) require render verification")
            status = "ocr_fallback" if method == "ocr" else "extracted" if method == "pdf_text_layer" else "bounded"
            page_records.append({
                "page": number, "width_points": page["width"], "height_points": page["height"],
                "text_method": method, "text_path": f"{output_rel}/{text_rel.as_posix()}",
                "text_sha256": sha256_file(stage / text_rel),
                "native_text_path": f"{output_rel}/{native_rel.as_posix()}",
                "native_text_sha256": sha256_file(stage / native_rel),
                "ocr_text_path": f"{output_rel}/{ocr_rel.as_posix()}" if ocr_rel is not None else None,
                "ocr_text_sha256": sha256_file(stage / ocr_rel) if ocr_rel is not None else None,
                "render_path": f"{output_rel}/{render_rel.as_posix()}", "render_sha256": sha256_file(stage / render_rel),
                "character_count": len(text), "replacement_character_count": replacement,
                "private_use_character_count": private_use, "status": status, "warnings": warnings,
            })
            overall_warnings.extend(f"page {number}: {warning}" for warning in warnings)

        markdown, blocks = build_markdown(pages, raw_blocks, page_text, source_id)
        private_write(stage / "manuscript.md", markdown.encode("utf-8"))
        tables, figures, equations = create_objects(
            stage, output_rel, source_id, source_copy, pages, raw_blocks, rendered,
        )
        symbols = symbol_inventory(blocks)
        proposal: dict[str, Any] | None = None
        proposals: list[dict[str, Any]] = []
        if args.markitdown_proposal:
            proposal_text = run_markitdown_proposal(source_copy)
            proposal_relative = Path("proposals/markitdown.md")
            private_write(stage / proposal_relative, proposal_text.encode("utf-8"))
            proposal = {
                "path": f"{output_rel}/{proposal_relative.as_posix()}",
                "sha256": sha256_file(stage / proposal_relative),
                "engine": "markitdown", "version": toolchain["proposal"]["version"], "authoritative": False,
                "warnings": [
                    "This optional local proposal is not canonical evidence and must not replace render-backed verification."
                ],
            }
            proposals.append({
                "id": "PRP-MARKITDOWN", "engine": "markitdown",
                "version": toolchain["proposal"]["version"], "role": "semantic_structure",
                "mode": "local", "authoritative": False, "input_sha256": source_sha,
                "artifacts": [{
                    "path": proposal["path"], "sha256": proposal["sha256"],
                    "media_type": "text/markdown",
                }],
                "model_revisions": [],
                "processing": {
                    "manuscript_uploaded": False, "user_authorized": True,
                    "credential_source": "none", "retention_policy": None,
                    "remote_deletion": "not_applicable", "request_id": None,
                },
                "warnings": proposal["warnings"],
            })
        docling_warning: str | None = None
        if args.semantic_backend in {"auto", "docling"}:
            try:
                proposals.append(run_docling(
                    source_copy, stage, output_rel,
                    allow_model_downloads=args.allow_model_downloads,
                    enrich_formulas=args.docling_formulas,
                    timeout=args.docling_timeout,
                    device=args.docling_device,
                ))
            except BackendError as exc:
                if args.semantic_backend == "docling":
                    raise IngestionError(str(exc)) from exc
                docling_warning = f"Docling auto proposal was unavailable: {exc}"
                overall_warnings.append(docling_warning)
        if args.mathpix:
            try:
                proposals.append(run_mathpix(
                    source_copy, stage, output_rel,
                    app_id=os.environ.get("MATHPIX_APP_ID", ""),
                    app_key=os.environ.get("MATHPIX_APP_KEY", ""),
                    timeout=args.mathpix_timeout,
                    poll_interval=args.mathpix_poll_interval,
                    expected_pages=page_count,
                ))
            except BackendError as exc:
                raise IngestionError(str(exc)) from exc
        proposal_page_index = load_proposal_page_index(stage, output_rel, proposals)
        packets = build_page_packets(
            source_sha256=source_sha, pages=page_records, blocks=blocks,
            tables=tables, figures=figures, equations=equations, proposals=proposals,
            proposal_page_index=proposal_page_index,
        )
        packets_relative = Path("reconciliation/page-packets.json")
        private_write(stage / packets_relative, canonical_json(packets))
        bounded_pages = [row["page"] for row in page_records if row["status"] == "bounded"]
        if bounded_pages:
            overall_warnings.append("pages without usable text: " + ", ".join(map(str, bounded_pages)))
        if any(row["status"] == "bounded" for row in equations):
            overall_warnings.append("equation transcriptions remain render-backed and bounded until verified")
        manifest = {
            "schema_version": PIPELINE_VERSION, "review_id": args.review_id, "source_id": source_id,
            "source_role": args.role, "pipeline_fingerprint": fingerprint,
            "parser_repairs": parser_repairs,
            "source": {"original_name": source.name, "package_path": f"{output_rel}/source/original.pdf",
                       "sha256": source_sha, "page_count": page_count, "encrypted": encrypted},
            "toolchain": toolchain,
            "configuration": configuration,
            "markdown": {"path": f"{output_rel}/manuscript.md", "sha256": sha256_file(stage / "manuscript.md"), "normalization": "none"},
            "pages": page_records, "blocks": blocks, "tables": tables, "figures": figures,
            "equations": equations, "symbols": symbols, "proposal": proposal,
            "proposals": proposals,
            "reconciliation": {
                "status": "packets_ready",
                "policy": "render_authority_native_glyph_preservation",
                "canonical_path": f"{output_rel}/manuscript.md",
                "canonical_sha256": sha256_file(stage / "manuscript.md"),
                "packets_path": f"{output_rel}/{packets_relative.as_posix()}",
                "packets_sha256": sha256_file(stage / packets_relative),
                "unresolved": {
                    "pages": len(bounded_pages),
                    "tables": len(tables),
                    "figures": len(figures),
                    "equations": len(equations),
                },
                "warnings": [
                    "Backend proposals have not been promoted automatically; reconcile disagreements against page renders before relying on load-bearing content."
                ] if proposals else [
                    "No semantic proposal backend ran; use native text only within its recorded evidence boundary."
                ],
            },
            "quality": {
                "status": "bounded" if bounded_pages else "ready_for_review",
                "page_count_match": len(page_records) == page_count,
                "all_pages_rendered": len(rendered) == page_count,
                "all_pages_have_text_or_boundary": len(page_records) == page_count,
                "object_crops_hashed": all(row.get("crop_sha256") for rows in (tables, figures, equations) for row in rows),
                "anchor_spans_valid": all(markdown[row["markdown_start"]:row["markdown_end"]] == row["raw_text"] for row in blocks),
                "requires_visual_verification": True,
                "warnings": sorted(set(overall_warnings)),
            },
        }
        errors = validate_schema(manifest)
        if errors:
            raise IngestionError("generated ingestion manifest failed schema validation:\n- " + "\n- ".join(errors))
        ingestion_bytes = canonical_json(manifest)
        private_write(stage / "ingestion.json", ingestion_bytes)
        source_manifest = build_source_manifest(
            args.review_id, source_id, args.role, output_rel, source_sha, markdown, blocks,
            sha256_bytes(ingestion_bytes), manifest["pipeline_fingerprint"],
        )
        private_write(stage / "source-manifest.generated.json", canonical_json(source_manifest))

        if destination.exists():
            if destination.is_symlink() or not destination.is_dir():
                raise IngestionError(f"refusing unsafe existing output: {destination}")
            backup = parent / f".{destination.name}.backup-{os.getpid()}"
            if backup.exists():
                raise IngestionError(f"temporary backup already exists: {backup}")
            destination.rename(backup)
        stage.rename(destination)
        stage = None
        errors = verify_package(destination, quiet=True)
        if errors:
            if destination.exists():
                shutil.rmtree(destination)
            if backup and backup.exists():
                backup.rename(destination)
            raise IngestionError("committed ingestion failed verification:\n- " + "\n- ".join(errors))
        if backup and backup.exists():
            shutil.rmtree(backup)
        print(f"PDF ingestion created: {destination}")
        print(f"Markdown reading surface: {destination / 'manuscript.md'}")
        print(f"Pages: {page_count}; tables: {len(tables)}; figures: {len(figures)}; equation candidates: {len(equations)}")
        print("Semantic proposals: " + (", ".join(row["engine"] for row in proposals) if proposals else "none"))
        return destination
    finally:
        if stage is not None and stage.exists() and stage.is_dir():
            shutil.rmtree(stage, ignore_errors=True)
        if backup and backup.exists() and not destination.exists():
            backup.rename(destination)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Report local PDF ingestion capabilities")
    ingest_parser = commands.add_parser("ingest", help="Create a verified PDF transcription package")
    ingest_parser.add_argument("pdf", type=Path)
    ingest_parser.add_argument("review_dir", type=Path, help="Review package root")
    ingest_parser.add_argument("--review-id", required=True)
    ingest_parser.add_argument("--source-id", default="SRC-01")
    ingest_parser.add_argument(
        "--role", choices=("manuscript", "appendix", "supplement"), default="manuscript",
        help="Role written to the generated source-manifest fragment",
    )
    ingest_parser.add_argument(
        "--output", type=Path, default=None,
        help="Safe path relative to review_dir (default: evidence/pdf-ingestion/SOURCE-ID)",
    )
    ingest_parser.add_argument("--dpi", type=int, default=250, choices=range(150, 401), metavar="150..400")
    ingest_parser.add_argument("--ocr", choices=("auto", "never", "always"), default="auto")
    ingest_parser.add_argument("--max-pages", type=int, default=MAX_PAGES_DEFAULT)
    ingest_parser.add_argument("--max-bytes", type=int, default=MAX_BYTES_DEFAULT)
    ingest_parser.add_argument(
        "--markitdown-proposal", action="store_true",
        help="Write a non-authoritative local MarkItDown proposal when the command is installed",
    )
    ingest_parser.add_argument(
        "--semantic-backend", choices=("none", "auto", "docling"), default="auto",
        help="Local semantic proposal backend; auto records a bounded fallback when unavailable",
    )
    ingest_parser.add_argument(
        "--allow-model-downloads", action="store_true",
        help="Allow Docling to download model artifacts; the manuscript itself remains local",
    )
    ingest_parser.add_argument(
        "--docling-formulas", action="store_true",
        help="Enable Docling formula enrichment (slow on unsupported accelerators)",
    )
    ingest_parser.add_argument("--docling-timeout", type=int, default=1_200)
    ingest_parser.add_argument("--docling-device", choices=("auto", "cpu", "mps", "cuda", "xpu"), default="auto")
    ingest_parser.add_argument(
        "--mathpix", action="store_true",
        help="Upload the complete PDF to Mathpix v3/pdf as a non-authoritative premium proposal",
    )
    ingest_parser.add_argument(
        "--authorize-external-upload", choices=("mathpix",), default=None,
        help="Explicitly authorize the named remote provider to receive this PDF",
    )
    ingest_parser.add_argument(
        "--accept-mathpix-retention", action="store_true",
        help="Acknowledge Mathpix endpoint retention terms before upload",
    )
    ingest_parser.add_argument("--mathpix-timeout", type=int, default=1_800)
    ingest_parser.add_argument("--mathpix-poll-interval", type=float, default=2.0)
    ingest_parser.add_argument("--force", action="store_true", help="Atomically replace a stale ingestion package")
    check = commands.add_parser("check", help="Validate hashes, paths, pages, and Markdown spans")
    check.add_argument("package_dir", type=Path)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "doctor":
            return doctor()
        if args.command == "check":
            return 1 if verify_package(args.package_dir) else 0
        ingest(args)
        return 0
    except (IngestionError, OSError, ValueError) as exc:
        print(f"PDF ingestion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
