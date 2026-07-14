#!/usr/bin/env python3
"""Query authenticated canonical source spans without printing whole ledgers."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import (  # noqa: E402
    canonical_portable_path,
    safe_read_bytes,
    sha256_bytes,
    strict_json_loads,
)


DEFAULT_CONTEXT_CHARS = 160
DEFAULT_LIMIT = 12
DEFAULT_MAX_CONTENT_CHARS = 4_000
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024
MAX_CONTEXT_CHARS = 2_000
MAX_LIMIT = 50
MAX_MAX_CONTENT_CHARS = 32_000
MAX_OUTPUT_BYTES = 256 * 1024
MAX_QUERY_CHARS = 256
MAX_OFFSET = 100_000
_WINDOWS_ILLEGAL_FILENAME_CHARS = frozenset('?*<>|"')
_WINDOWS_SUPERSCRIPT_DEVICE_NAMES = frozenset(
    {f"com{digit}" for digit in "¹²³"} | {f"lpt{digit}" for digit in "¹²³"}
)


def _objects(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"{label} must be an array of objects")
    return value


def _index(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"{label} contains a row without an ID")
        if identifier in result:
            raise ValueError(f"{label} contains duplicate ID {identifier}")
        result[identifier] = row
    return result


def _integer(value: int, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return value


def _digest_matches(value: bytes, expected: Any, label: str) -> None:
    if not isinstance(expected, str) or sha256_bytes(value) != expected:
        raise ValueError(f"{label} SHA-256 does not match its canonical ledger")


class SourceQuery:
    """Read-only authenticated view over one review support directory."""

    def __init__(self, review_dir: Path):
        self.review_dir = review_dir
        manifest_bytes = safe_read_bytes(review_dir, "evidence/source-manifest.json")
        manifest = strict_json_loads(manifest_bytes)
        if not isinstance(manifest, dict):
            raise ValueError("source-manifest.json must contain an object")
        self.review_id = manifest.get("review_id")
        if not isinstance(self.review_id, str) or not self.review_id:
            raise ValueError("source-manifest.json has no review_id")
        self.sources = _index(
            _objects(manifest.get("sources"), "source-manifest.json.sources"),
            "source-manifest.json.sources",
        )
        self.anchors = _index(
            _objects(manifest.get("anchors"), "source-manifest.json.anchors"),
            "source-manifest.json.anchors",
        )
        self._authenticated: dict[str, tuple[str, dict[str, Any], dict[str, Any] | None]] = {}
        self._coverage: dict[str, dict[str, Any]] | None = None

    @staticmethod
    def _portable_path(relative: Any, label: str) -> str:
        if not isinstance(relative, str):
            raise ValueError(f"{label} path must be a string")
        try:
            safe_relative = canonical_portable_path(relative)
        except ValueError as exc:
            raise ValueError(f"unsafe {label} path: {relative!r}") from exc
        for part in safe_relative.split("/"):
            basename = part.split(".", 1)[0].casefold()
            if (
                basename in _WINDOWS_SUPERSCRIPT_DEVICE_NAMES
                or any(character in _WINDOWS_ILLEGAL_FILENAME_CHARS for character in part)
            ):
                raise ValueError(f"unsafe {label} path: {relative!r}")
        return safe_relative

    def _read(self, relative: Any, label: str) -> bytes:
        safe_relative = self._portable_path(relative, label)
        return safe_read_bytes(self.review_dir, safe_relative)

    def _require_pdf_path(self, source_id: str, relative: Any, label: str) -> str:
        safe_relative = self._portable_path(relative, label)
        prefix = f"evidence/pdf-ingestion/{source_id}/"
        if not safe_relative.startswith(prefix):
            raise ValueError(
                f"source {source_id} {label} path escapes its canonical ingestion root"
            )
        return safe_relative

    def _source(self, source_id: str) -> dict[str, Any]:
        source = self.sources.get(source_id)
        if source is None:
            raise ValueError(f"unknown source ID: {source_id}")
        return source

    def authenticate(
        self, source_id: str,
    ) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
        """Return authenticated source text, integrity flags, and ingestion ledger."""

        cached = self._authenticated.get(source_id)
        if cached is not None:
            return cached
        source = self._source(source_id)
        is_pdf = source.get("media_type") == "application/pdf"
        if is_pdf:
            self._require_pdf_path(source_id, source.get("path"), "source")
        source_bytes = self._read(source.get("path"), f"source {source_id}")
        _digest_matches(source_bytes, source.get("sha256"), f"source {source_id}")

        extraction = source.get("extraction")
        ingestion: dict[str, Any] | None = None
        integrity = {
            "authenticated": True,
            "source_file_sha256": True,
            "extraction_sha256": None,
            "ingestion_manifest_sha256": None,
        }
        if is_pdf and not isinstance(extraction, dict):
            raise ValueError(f"PDF source {source_id} has no authenticated extraction")
        if isinstance(extraction, dict):
            ingestion_path = extraction.get("ingestion_manifest_path")
            if not isinstance(ingestion_path, str):
                raise ValueError(
                    f"source {source_id} extraction has no ingestion manifest path"
                )
            if is_pdf:
                self._require_pdf_path(
                    source_id, ingestion_path, "ingestion manifest"
                )
                self._require_pdf_path(
                    source_id, extraction.get("path"), "extraction"
                )
            ingestion_bytes = self._read(
                ingestion_path, f"source {source_id} ingestion manifest"
            )
            _digest_matches(
                ingestion_bytes,
                extraction.get("ingestion_manifest_sha256"),
                f"source {source_id} ingestion manifest",
            )
            parsed = strict_json_loads(ingestion_bytes)
            if not isinstance(parsed, dict):
                raise ValueError(f"source {source_id} ingestion manifest must be an object")
            ingestion = parsed
            if ingestion.get("source_id") != source_id:
                raise ValueError(f"source {source_id} ingestion source_id does not match")
            if ingestion.get("pipeline_fingerprint") != extraction.get("pipeline_fingerprint"):
                raise ValueError(f"source {source_id} ingestion pipeline fingerprint does not match")
            ingestion_source = ingestion.get("source")
            if not isinstance(ingestion_source, dict) or ingestion_source.get("sha256") != source.get("sha256"):
                raise ValueError(f"source {source_id} ingestion source hash does not match")
            ingestion_markdown = ingestion.get("markdown")
            if not isinstance(ingestion_markdown, dict):
                raise ValueError(f"source {source_id} ingestion markdown record is missing")
            if ingestion_markdown.get("path") != extraction.get("path"):
                raise ValueError(f"source {source_id} ingestion extraction path does not match")
            if ingestion_markdown.get("sha256") != extraction.get("sha256"):
                raise ValueError(f"source {source_id} ingestion extraction hash does not match")
            text_bytes = self._read(extraction.get("path"), f"source {source_id} extraction")
            _digest_matches(
                text_bytes, extraction.get("sha256"), f"source {source_id} extraction"
            )
            integrity["extraction_sha256"] = True
            integrity["ingestion_manifest_sha256"] = True
        elif extraction is None:
            text_bytes = source_bytes
        else:
            raise ValueError(f"source {source_id} extraction must be an object or null")

        try:
            text = text_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"source {source_id} has no authenticated UTF-8 text") from exc
        result = (text, integrity, ingestion)
        self._authenticated[source_id] = result
        return result

    def coverage_units(self) -> dict[str, dict[str, Any]]:
        if self._coverage is None:
            coverage = strict_json_loads(safe_read_bytes(self.review_dir, "evidence/coverage.json"))
            if not isinstance(coverage, dict):
                raise ValueError("coverage.json must contain an object")
            if coverage.get("review_id") != self.review_id:
                raise ValueError("coverage.json review_id does not match source-manifest.json")
            units = _index(
                _objects(coverage.get("units"), "coverage.json.units"),
                "coverage.json.units",
            )
            for unit_id, unit in units.items():
                source_id = unit.get("source_id")
                if not isinstance(source_id, str) or source_id not in self.sources:
                    raise ValueError(
                        f"coverage unit {unit_id} references an unknown source"
                    )
                anchor_ids = unit.get("anchor_ids")
                if not isinstance(anchor_ids, list) or not all(
                    isinstance(value, str) for value in anchor_ids
                ):
                    raise ValueError(f"coverage unit {unit_id} has invalid anchor_ids")
                for anchor_id in anchor_ids:
                    anchor = self.anchors.get(anchor_id)
                    if anchor is None:
                        raise ValueError(
                            f"coverage unit {unit_id} references unknown anchor {anchor_id}"
                        )
                    if anchor.get("source_id") != source_id:
                        raise ValueError(
                            f"coverage unit {unit_id} borrows anchor {anchor_id} "
                            "from another source"
                        )
            self._coverage = units
        return self._coverage

    def verify_anchor(
        self, anchor_id: str,
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        anchor = self.anchors.get(anchor_id)
        if anchor is None:
            raise ValueError(f"unknown anchor ID: {anchor_id}")
        source_id = anchor.get("source_id")
        if not isinstance(source_id, str):
            raise ValueError(f"anchor {anchor_id} has no source_id")
        text, integrity, _ingestion = self.authenticate(source_id)
        start, end = anchor.get("start_char"), anchor.get("end_char")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or not 0 <= start < end <= len(text)
        ):
            raise ValueError(f"anchor {anchor_id} has an invalid source span")
        content = text[start:end]
        _digest_matches(
            content.encode("utf-8"), anchor.get("content_sha256"), f"anchor {anchor_id}"
        )
        return anchor, content, {**integrity, "exact_span_sha256": True}

    def authenticated_locator(
        self,
        anchor: dict[str, Any],
        text: str,
        ingestion: dict[str, Any] | None,
    ) -> tuple[str, bool | None]:
        """Derive PDF locators from authenticated blocks, never free-form text."""

        declared = anchor.get("locator")
        if not isinstance(declared, str) or not declared:
            raise ValueError(f"anchor {anchor.get('id')} has no locator")
        source_id = anchor.get("source_id")
        source = self._source(str(source_id))
        if source.get("media_type") != "application/pdf":
            return declared, None
        if not isinstance(ingestion, dict):
            raise ValueError(f"PDF anchor {anchor.get('id')} has no ingestion ledger")
        start, end = anchor.get("start_char"), anchor.get("end_char")
        blocks = _objects(
            ingestion.get("blocks"), f"source {source_id} ingestion blocks"
        )
        containing = [
            block for block in blocks
            if isinstance(block.get("markdown_start"), int)
            and isinstance(block.get("markdown_end"), int)
            and block["markdown_start"] <= start
            and block["markdown_end"] >= end
        ]
        pages = _objects(ingestion.get("pages"), f"source {source_id} ingestion pages")
        known_pages = {
            row.get("page") for row in pages if isinstance(row.get("page"), int)
        }

        def verify_block(block: dict[str, Any]) -> int:
            block_id = block.get("id")
            block_start, block_end = block.get("markdown_start"), block.get("markdown_end")
            raw_text = block.get("raw_text")
            if (
                not isinstance(block_start, int)
                or not isinstance(block_end, int)
                or not isinstance(raw_text, str)
                or not 0 <= block_start < block_end <= len(text)
                or text[block_start:block_end] != raw_text
            ):
                raise ValueError(
                    f"PDF block {block_id} does not match the authenticated extraction"
                )
            _digest_matches(
                raw_text.encode("utf-8"), block.get("sha256"), f"PDF block {block_id}"
            )
            page_number = block.get("page")
            if not isinstance(page_number, int) or page_number not in known_pages:
                raise ValueError(f"PDF block {block_id} references an unknown page")
            return page_number

        if containing:
            block = min(
                containing,
                key=lambda row: (
                    row["markdown_end"] - row["markdown_start"], str(row.get("id"))
                ),
            )
            page_number = verify_block(block)
            block_id = block.get("id")
            bbox = block.get("bbox")
            if (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or any(
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    for value in bbox
                )
            ):
                raise ValueError(f"PDF block {block_id} has an invalid bounding box")
            coordinates = ",".join(f"{value:g}" for value in bbox)
            return f"PDF p. {page_number}, bbox {coordinates}, block {block_id}", True

        overlapping = [
            block for block in blocks
            if isinstance(block.get("markdown_start"), int)
            and isinstance(block.get("markdown_end"), int)
            and block["markdown_start"] < end
            and block["markdown_end"] > start
        ]
        if not overlapping:
            return f"authenticated extraction characters {start}-{end}", False
        page_numbers = sorted({verify_block(block) for block in overlapping})
        page_label = (
            f"PDF p. {page_numbers[0]}"
            if len(page_numbers) == 1
            else f"PDF pp. {page_numbers[0]}-{page_numbers[-1]}"
        )
        scope = "complete extraction" if anchor.get("kind") == "scope" else "source span"
        return f"{page_label}, authenticated {scope} {start}-{end}", True

    @staticmethod
    def compact_source(source: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": source.get("id"),
            "role": source.get("role"),
            "media_type": source.get("media_type"),
        }

    def anchor_result(
        self,
        anchor_id: str,
        *,
        context_chars: int,
        max_content_chars: int,
    ) -> dict[str, Any]:
        anchor, content, integrity = self.verify_anchor(anchor_id)
        source_id = anchor["source_id"]
        text, _source_integrity, ingestion = self.authenticate(source_id)
        start, end = anchor["start_char"], anchor["end_char"]
        locator, locator_binding = self.authenticated_locator(anchor, text, ingestion)
        content_included = len(content) <= max_content_chars
        return {
            "source": self.compact_source(self._source(source_id)),
            "anchor": {
                "id": anchor_id,
                "kind": anchor.get("kind"),
                "start_char": start,
                "end_char": end,
                "content_sha256": anchor.get("content_sha256"),
            },
            "locator": locator,
            "content": content if content_included else None,
            "content_char_count": len(content),
            "content_complete": content_included,
            "content_omission": None if content_included else "max_content_chars",
            "context": {
                "before": text[max(0, start - context_chars):start],
                "after": text[end:min(len(text), end + context_chars)],
                "navigation_only": True,
            },
            "verification": {
                **integrity,
                "pdf_locator_from_authenticated_block": locator_binding,
            },
        }

    def query_anchors(
        self,
        anchor_ids: list[str],
        *,
        context_chars: int,
        max_content_chars: int,
    ) -> dict[str, Any]:
        if not anchor_ids or len(anchor_ids) > MAX_LIMIT:
            raise ValueError(f"anchor query requires between 1 and {MAX_LIMIT} IDs")
        if len(set(anchor_ids)) != len(anchor_ids):
            raise ValueError("anchor query contains duplicate IDs")
        return self._base("anchor", [
            self.anchor_result(
                anchor_id,
                context_chars=context_chars,
                max_content_chars=max_content_chars,
            )
            for anchor_id in anchor_ids
        ])

    def query_coverage(
        self,
        unit_id: str | None,
        *,
        offset: int,
        limit: int,
        context_chars: int,
        max_content_chars: int,
    ) -> dict[str, Any]:
        if unit_id is None:
            units = self.coverage_units()
            rows = [
                {
                    key: unit.get(key)
                    for key in (
                        "id", "source_id", "type", "label", "status", "finding_ids"
                    )
                }
                for unit in units.values()
            ]
            selected, pagination = _page(rows, offset, limit)
            payload = self._base("coverage", selected)
            payload["listing"] = "coverage_units"
            payload["pagination"] = pagination
            return payload
        unit = self.coverage_units().get(unit_id)
        if unit is None:
            raise ValueError(f"unknown coverage unit ID: {unit_id}")
        source_id = unit.get("source_id")
        if not isinstance(source_id, str) or source_id not in self.sources:
            raise ValueError(f"coverage unit {unit_id} references an unknown source")
        anchor_ids = unit.get("anchor_ids")
        if not isinstance(anchor_ids, list) or not all(isinstance(value, str) for value in anchor_ids):
            raise ValueError(f"coverage unit {unit_id} has invalid anchor_ids")
        for anchor_id in anchor_ids:
            anchor = self.anchors.get(anchor_id)
            if anchor is None:
                raise ValueError(f"coverage unit {unit_id} references unknown anchor {anchor_id}")
            if anchor.get("source_id") != source_id:
                raise ValueError(
                    f"coverage unit {unit_id} borrows anchor {anchor_id} from another source"
                )
        selected, pagination = _page(anchor_ids, offset, limit)
        payload = self._base("coverage", [
            self.anchor_result(
                anchor_id,
                context_chars=context_chars,
                max_content_chars=max_content_chars,
            )
            for anchor_id in selected
        ])
        payload["coverage_unit"] = {
            key: unit.get(key)
            for key in ("id", "source_id", "type", "label", "status", "finding_ids", "notes")
        }
        payload["pagination"] = pagination
        return payload

    def query_page(
        self,
        source_id: str,
        page_number: int,
        *,
        offset: int,
        limit: int,
        max_content_chars: int,
    ) -> dict[str, Any]:
        source = self._source(source_id)
        text, integrity, ingestion = self.authenticate(source_id)
        if source.get("media_type") != "application/pdf" or not isinstance(ingestion, dict):
            raise ValueError(f"source {source_id} is not an ingested PDF")
        pages = _objects(ingestion.get("pages"), f"source {source_id} ingestion pages")
        page = next((row for row in pages if row.get("page") == page_number), None)
        if page is None:
            raise ValueError(f"source {source_id} has no PDF page {page_number}")
        self._require_pdf_path(source_id, page.get("text_path"), "page text")
        self._require_pdf_path(source_id, page.get("render_path"), "page render")
        page_text_bytes = self._read(page.get("text_path"), f"source {source_id} page text")
        _digest_matches(
            page_text_bytes, page.get("text_sha256"), f"source {source_id} page {page_number} text"
        )
        render_bytes = self._read(page.get("render_path"), f"source {source_id} page render")
        _digest_matches(
            render_bytes, page.get("render_sha256"), f"source {source_id} page {page_number} render"
        )
        try:
            page_text = page_text_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"source {source_id} page {page_number} text is not UTF-8") from exc

        blocks = [
            row for row in _objects(ingestion.get("blocks"), f"source {source_id} ingestion blocks")
            if row.get("page") == page_number
        ]
        selected, pagination = _page(blocks, offset, limit)
        anchors_by_span: dict[tuple[int, int, str], list[dict[str, Any]]] = {}
        for anchor in self.anchors.values():
            if anchor.get("source_id") != source_id:
                continue
            key = (anchor.get("start_char"), anchor.get("end_char"), anchor.get("content_sha256"))
            if isinstance(key[0], int) and isinstance(key[1], int) and isinstance(key[2], str):
                anchors_by_span.setdefault(key, []).append(anchor)

        results: list[dict[str, Any]] = []
        for block in selected:
            block_id = block.get("id")
            start, end, block_hash = (
                block.get("markdown_start"),
                block.get("markdown_end"),
                block.get("sha256"),
            )
            raw_text = block.get("raw_text")
            if not isinstance(raw_text, str):
                raise ValueError(f"PDF block {block_id} has no text")
            _digest_matches(raw_text.encode("utf-8"), block_hash, f"PDF block {block_id}")
            if (
                not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or not 0 <= start < end <= len(text)
                or text[start:end] != raw_text
            ):
                raise ValueError(f"PDF block {block_id} does not match the authenticated extraction")
            candidates = sorted(
                anchors_by_span.get((start, end, block_hash), []),
                key=lambda row: str(row.get("id")),
            )
            anchor = candidates[0] if candidates else None
            if anchor is not None:
                self.verify_anchor(str(anchor["id"]))
            content_included = len(raw_text) <= max_content_chars
            results.append({
                "source": self.compact_source(source),
                "anchor": ({
                    "id": anchor.get("id"),
                    "kind": anchor.get("kind"),
                    "start_char": start,
                    "end_char": end,
                    "content_sha256": block_hash,
                } if anchor is not None else None),
                "locator": f"PDF p. {page_number}, block {block_id}",
                "content": raw_text if content_included else None,
                "content_char_count": len(raw_text),
                "content_complete": content_included,
                "content_omission": None if content_included else "max_content_chars",
                "context": {
                    "page": page_number,
                    "block_id": block_id,
                    "bbox": block.get("bbox"),
                    "kind": block.get("kind"),
                    "navigation_only": True,
                },
                "verification": {
                    **integrity,
                    "page_text_sha256": True,
                    "page_render_sha256": True,
                    "exact_span_sha256": True,
                    "canonical_anchor": anchor is not None,
                },
            })
        payload = self._base("page", results)
        page_content_included = len(page_text) <= max_content_chars
        payload["page"] = {
            "source_id": source_id,
            "page": page_number,
            "locator": f"PDF p. {page_number}",
            "text_path": page.get("text_path"),
            "render_path": page.get("render_path"),
            "status": page.get("status"),
            "text_method": page.get("text_method"),
            "content": page_text if page_content_included else None,
            "content_char_count": len(page_text),
            "content_complete": page_content_included,
            "content_omission": None if page_content_included else "max_content_chars",
            "navigation_only": True,
            "verification": {
                **integrity,
                "page_text_sha256": True,
                "page_render_sha256": True,
            },
        }
        payload["pagination"] = pagination
        return payload

    def query_search(
        self,
        query: str,
        *,
        source_ids: list[str] | None,
        ignore_case: bool,
        offset: int,
        limit: int,
        context_chars: int,
    ) -> dict[str, Any]:
        if not query or len(query) > MAX_QUERY_CHARS or "\x00" in query:
            raise ValueError(f"literal search text must contain 1 to {MAX_QUERY_CHARS} characters")
        selected_source_ids = source_ids or list(self.sources)
        if len(set(selected_source_ids)) != len(selected_source_ids):
            raise ValueError("search source IDs contain duplicates")
        for source_id in selected_source_ids:
            self._source(source_id)
        expression = re.compile(re.escape(query), re.IGNORECASE if ignore_case else 0)
        results: list[dict[str, Any]] = []
        skipped = 0
        has_more = False

        anchors_by_source: dict[str, list[dict[str, Any]]] = {}
        for anchor in self.anchors.values():
            source_id = anchor.get("source_id")
            if not isinstance(source_id, str) or anchor.get("kind") == "scope":
                continue
            if isinstance(anchor.get("start_char"), int) and isinstance(anchor.get("end_char"), int):
                anchors_by_source.setdefault(source_id, []).append(anchor)
        for rows in anchors_by_source.values():
            rows.sort(key=lambda row: (row["end_char"] - row["start_char"], str(row.get("id"))))

        stop = False
        for source_id in selected_source_ids:
            text, integrity, ingestion = self.authenticate(source_id)
            for match in expression.finditer(text):
                if skipped < offset:
                    skipped += 1
                    continue
                if len(results) >= limit:
                    has_more = True
                    stop = True
                    break
                containing = next((
                    row for row in anchors_by_source.get(source_id, [])
                    if row["start_char"] <= match.start() and row["end_char"] >= match.end()
                ), None)
                anchor_reference = None
                locator = f"source characters {match.start()}-{match.end()}"
                anchor_verified = False
                locator_binding: bool | None = None
                if containing is not None:
                    self.verify_anchor(str(containing["id"]))
                    anchor_verified = True
                    locator, locator_binding = self.authenticated_locator(
                        containing, text, ingestion
                    )
                    anchor_reference = {
                        "id": containing.get("id"),
                        "kind": containing.get("kind"),
                        "start_char": containing.get("start_char"),
                        "end_char": containing.get("end_char"),
                        "content_sha256": containing.get("content_sha256"),
                    }
                results.append({
                    "source": self.compact_source(self._source(source_id)),
                    "anchor": anchor_reference,
                    "locator": locator,
                    "content": match.group(0),
                    "content_char_count": len(match.group(0)),
                    "content_complete": True,
                    "content_omission": None,
                    "context": {
                        "before": text[max(0, match.start() - context_chars):match.start()],
                        "after": text[match.end():min(len(text), match.end() + context_chars)],
                        "match_start_char": match.start(),
                        "match_end_char": match.end(),
                        "navigation_only": True,
                    },
                    "verification": {
                        **integrity,
                        "literal_match_in_authenticated_source": True,
                        "canonical_anchor_exact_span_sha256": anchor_verified,
                        "pdf_locator_from_authenticated_block": locator_binding,
                    },
                })
            if stop:
                break
        payload = self._base("search", results)
        payload["query"] = {
            "literal": query,
            "ignore_case": ignore_case,
            "source_ids": selected_source_ids,
        }
        payload["navigation_only"] = True
        payload["instruction"] = (
            "Search results locate candidate text only. Query or create a canonical exact "
            "anchor before using a span as review evidence."
        )
        payload["pagination"] = {
            "offset": offset,
            "limit": limit,
            "returned": len(results),
            "total": None,
            "has_more": has_more,
            "next_offset": offset + len(results) if has_more else None,
        }
        return payload

    def _base(self, command: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "read_only": True,
            "review_id": self.review_id,
            "command": command,
            "results": results,
        }


def _page(items: list[Any], offset: int, limit: int) -> tuple[list[Any], dict[str, Any]]:
    total = len(items)
    selected = items[offset:offset + limit]
    has_more = offset + len(selected) < total
    return selected, {
        "offset": offset,
        "limit": limit,
        "returned": len(selected),
        "total": total,
        "has_more": has_more,
        "next_offset": offset + len(selected) if has_more else None,
    }


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def bounded_json(payload: dict[str, Any], max_output_bytes: int) -> bytes:
    """Return valid compact JSON at or below the hard output budget."""

    value = _json_bytes(payload)
    if len(value) <= max_output_bytes:
        return value

    page = payload.get("page")
    if isinstance(page, dict) and isinstance(page.get("content"), str):
        page["content"] = None
        page["content_complete"] = False
        page["content_omission"] = "max_output_bytes"
    for result in payload.get("results", []):
        context = result.get("context") if isinstance(result, dict) else None
        if isinstance(context, dict):
            compact_context = {
                "navigation_only": True,
                "omission": "max_output_bytes",
            }
            for key in (
                "match_start_char", "match_end_char", "page", "block_id", "bbox", "kind"
            ):
                if key in context:
                    compact_context[key] = context[key]
            result["context"] = compact_context
    value = _json_bytes(payload)
    if len(value) <= max_output_bytes:
        return value

    results = payload.get("results")
    if isinstance(results, list):
        for result in sorted(
            (row for row in results if isinstance(row, dict) and isinstance(row.get("content"), str)),
            key=lambda row: len(row["content"]),
            reverse=True,
        ):
            result["content"] = None
            result["content_complete"] = False
            result["content_omission"] = "max_output_bytes"
            value = _json_bytes(payload)
            if len(value) <= max_output_bytes:
                return value

        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            while len(results) > 1 and len(_json_bytes(payload)) > max_output_bytes:
                results.pop()
                pagination["returned"] = len(results)
                pagination["has_more"] = True
                pagination["next_offset"] = int(pagination.get("offset", 0)) + len(results)
        value = _json_bytes(payload)
        if len(value) <= max_output_bytes:
            return value
    raise ValueError(
        "requested metadata exceeds max_output_bytes; raise the cap or narrow the query"
    )


def _common(parser: argparse.ArgumentParser, *, pagination: bool = False) -> None:
    parser.add_argument(
        "--context-chars", type=int, default=DEFAULT_CONTEXT_CHARS,
        help="navigation-only characters before and after each exact result",
    )
    parser.add_argument(
        "--max-content-chars", type=int, default=DEFAULT_MAX_CONTENT_CHARS,
        help="omit, never truncate, exact content longer than this bound",
    )
    parser.add_argument(
        "--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES,
        help="hard UTF-8 JSON output cap",
    )
    if pagination:
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)


def _validate_args(args: argparse.Namespace) -> None:
    _integer(args.context_chars, "context_chars", minimum=0, maximum=MAX_CONTEXT_CHARS)
    _integer(
        args.max_content_chars,
        "max_content_chars",
        minimum=0,
        maximum=MAX_MAX_CONTENT_CHARS,
    )
    _integer(
        args.max_output_bytes,
        "max_output_bytes",
        minimum=2_048,
        maximum=MAX_OUTPUT_BYTES,
    )
    if hasattr(args, "offset"):
        _integer(args.offset, "offset", minimum=0, maximum=MAX_OFFSET)
        _integer(args.limit, "limit", minimum=1, maximum=MAX_LIMIT)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path, help="review support directory containing evidence/")
    commands = parser.add_subparsers(dest="command", required=True)

    anchor = commands.add_parser("anchor", help="return authenticated canonical anchors")
    anchor.add_argument("anchor_ids", nargs="+")
    _common(anchor)

    coverage = commands.add_parser("coverage", help="page through one coverage unit's anchors")
    coverage.add_argument("unit_id", nargs="?")
    _common(coverage, pagination=True)

    page = commands.add_parser("page", help="return one authenticated PDF page locator and blocks")
    page.add_argument("source_id")
    page.add_argument("page", type=int)
    _common(page, pagination=True)

    search = commands.add_parser("search", help="bounded literal navigation search")
    search.add_argument("literal")
    search.add_argument("--source-id", action="append", dest="source_ids")
    search.add_argument("--ignore-case", action="store_true")
    _common(search, pagination=True)
    return parser


def execute(args: argparse.Namespace) -> dict[str, Any]:
    _validate_args(args)
    query = SourceQuery(args.review_dir)
    if args.command == "anchor":
        return query.query_anchors(
            args.anchor_ids,
            context_chars=args.context_chars,
            max_content_chars=args.max_content_chars,
        )
    if args.command == "coverage":
        return query.query_coverage(
            args.unit_id,
            offset=args.offset,
            limit=args.limit,
            context_chars=args.context_chars,
            max_content_chars=args.max_content_chars,
        )
    if args.command == "page":
        _integer(args.page, "page", minimum=1, maximum=1_000_000)
        return query.query_page(
            args.source_id,
            args.page,
            offset=args.offset,
            limit=args.limit,
            max_content_chars=args.max_content_chars,
        )
    if args.command == "search":
        return query.query_search(
            args.literal,
            source_ids=args.source_ids,
            ignore_case=args.ignore_case,
            offset=args.offset,
            limit=args.limit,
            context_chars=args.context_chars,
        )
    raise ValueError(f"unsupported command: {args.command}")


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = execute(args)
        output = bounded_json(payload, args.max_output_bytes)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"source query failed: {exc}\n")
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
