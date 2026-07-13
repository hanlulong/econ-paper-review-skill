#!/usr/bin/env python3
"""Build deterministic, render-bounded packets for PDF adjudication.

The packets route evidence to an agent or human reviewer. They never contain a
decision and never rewrite the canonical Markdown. A later decision may be
trusted only when its status records direct comparison with the page render.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from safe_io import canonical_portable_path, strict_json_load  # noqa: E402


DECISION_STATES = [
    "model_adjudicated",
    "render_verified",
    "bounded",
]
CRITICAL_TOKEN = re.compile(
    r"(?:[+\-−–±]?[0-9]+(?:[.,][0-9]+)*)|[=<>≤≥±×÷−]|[Α-ω]|(?:\\[A-Za-z]+)"
)


def load_proposal_page_index(
    root: Path, output_prefix: str, proposals: list[dict[str, Any]],
) -> dict[str, dict[int, dict[str, Any]]]:
    """Load only normalized backend indexes; raw outputs remain separate."""
    result: dict[str, dict[int, dict[str, Any]]] = {}
    try:
        prefix = Path(canonical_portable_path(output_prefix))
    except ValueError:
        return result
    resolved_root = root.resolve()

    def safe_file(relative: Path) -> Path | None:
        candidate = root.joinpath(*relative.parts)
        if candidate.is_symlink():
            return None
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            return None
        return resolved if resolved.is_file() else None

    for proposal in proposals:
        normalized = next(
            (row for row in proposal.get("artifacts", []) if row.get("path", "").endswith("/normalized.json")),
            None,
        )
        if normalized is None:
            continue
        raw_path = normalized.get("path")
        if not isinstance(raw_path, str):
            continue
        try:
            relative = Path(canonical_portable_path(raw_path))
            package_relative = relative.relative_to(prefix)
        except ValueError:
            continue
        path = next(
            (
                candidate
                for candidate in (
                    safe_file(relative),
                    safe_file(package_relative),
                )
                if candidate is not None
            ),
            None,
        )
        if path is None:
            continue
        try:
            value = strict_json_load(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        page_map: dict[int, dict[str, Any]] = {}
        for page in value.get("pages", []):
            if isinstance(page, dict) and isinstance(page.get("page"), int):
                page_map[page["page"]] = page
        result[proposal["id"]] = page_map
    return result


def _text_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _critical_tokens(value: str) -> list[str]:
    return CRITICAL_TOKEN.findall(value)


def _scaled_bbox(element: dict[str, Any], proposal_page: dict[str, Any], page: dict[str, Any]) -> list[float] | None:
    bbox = element.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    width, height = proposal_page.get("width"), proposal_page.get("height")
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)) or width <= 0 or height <= 0:
        return [round(float(value), 3) for value in bbox]
    sx, sy = page["width_points"] / width, page["height_points"] / height
    return [round(bbox[0] * sx, 3), round(bbox[1] * sy, 3), round(bbox[2] * sx, 3), round(bbox[3] * sy, 3)]


def _overlap_ratio(left: list[float], right: list[float]) -> float:
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    area = max(1.0, (left[2] - left[0]) * (left[3] - left[1]))
    return round(width * height / area, 4)


def _block_candidate(
    block: dict[str, Any], proposal_id: str, proposal_page: dict[str, Any], page: dict[str, Any],
) -> dict[str, Any] | None:
    canonical = _text_key(block["raw_text"])
    ranked: list[tuple[float, float, dict[str, Any], list[float] | None]] = []
    for element in proposal_page.get("elements", []):
        if not isinstance(element, dict):
            continue
        text = _text_key(str(element.get("text") or ""))
        bbox = _scaled_bbox(element, proposal_page, page)
        overlap = _overlap_ratio(block["bbox"], bbox) if bbox else 0.0
        similarity = SequenceMatcher(None, canonical, text, autojunk=False).ratio() if canonical or text else 1.0
        if overlap > 0 or similarity >= 0.35:
            ranked.append((overlap, similarity, element, bbox))
    if not ranked:
        return None
    overlap, similarity, element, bbox = max(ranked, key=lambda row: (row[0] >= 0.25, row[0], row[1]))
    text = str(element.get("text") or "")
    return {
        "proposal_id": proposal_id, "element_id": element.get("id"),
        "type": element.get("type"), "bbox": bbox, "text": text,
        "exact_text": _text_key(text) == canonical,
        "text_similarity": round(similarity, 4), "target_overlap": overlap,
        "critical_tokens": _critical_tokens(text),
        "critical_tokens_match": _critical_tokens(text) == _critical_tokens(block["raw_text"]),
    }


def _object_candidates(
    obj: dict[str, Any], proposal_page_index: dict[str, dict[int, dict[str, Any]]],
    page: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for proposal_id, proposal_pages in proposal_page_index.items():
        proposal_page = proposal_pages.get(page["page"])
        if proposal_page is None:
            continue
        for element in proposal_page.get("elements", []):
            bbox = _scaled_bbox(element, proposal_page, page)
            overlap = _overlap_ratio(obj["bbox"], bbox) if bbox else 0.0
            if overlap < 0.05:
                continue
            candidate = {
                "proposal_id": proposal_id, "element_id": element.get("id"),
                "type": element.get("type"), "subtype": element.get("subtype"),
                "bbox": bbox, "target_overlap": overlap,
                "text": str(element.get("text") or ""),
                "critical_tokens": _critical_tokens(str(element.get("text") or "")),
            }
            if isinstance(element.get("table_cells"), list):
                candidate["table_cells"] = element["table_cells"]
            candidates.append(candidate)
    return sorted(candidates, key=lambda row: (row["proposal_id"], -row["target_overlap"], str(row["element_id"])))


def build_page_packets(
    *,
    source_sha256: str,
    pages: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    equations: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    proposal_page_index: dict[str, dict[int, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Return a stable routing manifest without copying proposal content."""
    blocks_by_page: dict[int, list[str]] = {}
    objects_by_page: dict[int, list[dict[str, str]]] = {}
    for block in blocks:
        blocks_by_page.setdefault(block["page"], []).append(block["id"])
    for kind, rows in (("table", tables), ("figure", figures), ("equation", equations)):
        for row in rows:
            objects_by_page.setdefault(row["page"], []).append({"id": row["id"], "kind": kind})

    proposal_catalog = [
        {
            "id": proposal["id"],
            "engine": proposal["engine"],
            "role": proposal["role"],
            "artifacts": [
                {key: artifact[key] for key in ("path", "sha256", "media_type")}
                for artifact in proposal["artifacts"]
            ],
        }
        for proposal in proposals
    ]
    proposal_page_index = proposal_page_index or {}
    pages_by_number = {row["page"]: row for row in pages}
    page_packets: list[dict[str, Any]] = []
    for page in pages:
        number = page["page"]
        page_objects = sorted(objects_by_page.get(number, []), key=lambda row: row["id"])
        full_objects = sorted(
            (
                {
                    "id": row["id"], "kind": kind, "bbox": row["bbox"],
                    "caption": row.get("caption"), "crop_path": row["crop_path"],
                    "crop_sha256": row["crop_sha256"], "status": row["status"],
                    "transcription": row.get("transcription"),
                }
                for kind, collection in (("table", tables), ("figure", figures), ("equation", equations))
                for row in collection if row["page"] == number
            ),
            key=lambda row: row["id"],
        )
        for obj in full_objects:
            obj["backend_candidates"] = _object_candidates(obj, proposal_page_index, page)
        page_blocks = [block for block in blocks if block["page"] == number]
        targets: list[dict[str, Any]] = []
        backend_disagreement = False
        for block in page_blocks:
            candidates = [
                candidate
                for proposal_id, proposal_pages in proposal_page_index.items()
                if (proposal_page := proposal_pages.get(number)) is not None
                if (candidate := _block_candidate(block, proposal_id, proposal_page, page)) is not None
            ]
            if candidates and any(
                not row["critical_tokens_match"] or row["text_similarity"] < 0.85
                for row in candidates
            ):
                backend_disagreement = True
            targets.append({
                "target_id": block["id"], "kind": block["kind"], "bbox": block["bbox"],
                "canonical_candidate": block["raw_text"], "confidence": block["confidence"],
                "critical_tokens": _critical_tokens(block["raw_text"]),
                "backend_candidates": candidates,
            })
        reasons: list[str] = []
        if page["status"] == "bounded":
            reasons.append("no_usable_page_text")
        if page["replacement_character_count"] or page["private_use_character_count"]:
            reasons.append("suspicious_glyphs")
        if page_objects:
            reasons.append("structured_or_visual_objects")
        if any(block["page"] == number and block["confidence"] == "low" for block in blocks):
            reasons.append("low_confidence_layout")
        if backend_disagreement:
            reasons.append("backend_disagreement")
        adjacent = [
            {
                "page": adjacent_number,
                "render_path": pages_by_number[adjacent_number]["render_path"],
                "render_sha256": pages_by_number[adjacent_number]["render_sha256"],
            }
            for adjacent_number in (number - 1, number + 1) if adjacent_number in pages_by_number
        ]
        page_packets.append({
            "page": number,
            "render": {"path": page["render_path"], "sha256": page["render_sha256"]},
            "selected_text": {
                "path": page["text_path"], "sha256": page["text_sha256"],
                "method": page["text_method"],
            },
            "native_text": {
                "path": page["native_text_path"],
                "sha256": page["native_text_sha256"],
            },
            "ocr_text": (
                {"path": page["ocr_text_path"], "sha256": page["ocr_text_sha256"]}
                if page["ocr_text_path"] is not None else None
            ),
            "block_ids": sorted(blocks_by_page.get(number, [])),
            "objects": page_objects,
            "object_evidence": full_objects,
            "targets": targets,
            "proposal_ids": [proposal["id"] for proposal in proposal_catalog],
            "adjacent_page_renders": adjacent,
            "adjudication_required": bool(reasons),
            "routing_reasons": reasons,
        })
    return {
        "schema_version": "0.1",
        "source_sha256": source_sha256,
        "authority": "page_render",
        "canonical_policy": "no_automatic_promotion",
        "proposal_catalog": proposal_catalog,
        "pages": page_packets,
        "decision_contract": {
            "allowed_states": DECISION_STATES,
            "required_fields": [
                "page", "target_id", "state", "evidence_used", "transcription",
                "alternatives", "unreadable_regions", "verification_note",
            ],
            "promotion_rule": (
                "Only render_verified decisions may support exact quotations or changes to "
                "load-bearing equations, table cells, symbols, signs, values, and labels."
            ),
        },
    }


def packet_errors(packets: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    """Cross-check packet references against an ingestion manifest."""
    errors: list[str] = []
    if packets.get("source_sha256") != manifest.get("source", {}).get("sha256"):
        errors.append("page-packet source hash differs from the ingestion source")
    expected_pages = {row["page"]: row for row in manifest.get("pages", [])}
    packet_pages = {row.get("page"): row for row in packets.get("pages", [])}
    if set(packet_pages) != set(expected_pages):
        errors.append("page-packet page inventory differs from the ingestion manifest")
    manifest_proposals = manifest.get("proposals", [])
    proposal_ids = {row["id"] for row in manifest_proposals}
    catalog_ids = {row.get("id") for row in packets.get("proposal_catalog", [])}
    if catalog_ids != proposal_ids:
        errors.append("page-packet proposal catalog differs from the ingestion manifest")
    expected_catalog = [
        {
            "id": proposal["id"], "engine": proposal["engine"], "role": proposal["role"],
            "artifacts": [
                {key: artifact[key] for key in ("path", "sha256", "media_type")}
                for artifact in proposal["artifacts"]
            ],
        }
        for proposal in manifest_proposals
    ]
    if packets.get("proposal_catalog") != expected_catalog:
        errors.append("page-packet proposal catalog metadata differs from the ingestion manifest")
    for number, packet in packet_pages.items():
        expected = expected_pages.get(number)
        if expected is None:
            continue
        if packet.get("render") != {"path": expected["render_path"], "sha256": expected["render_sha256"]}:
            errors.append(f"page {number} packet render differs from the ingestion manifest")
        expected_block_ids = sorted(
            row["id"] for row in manifest.get("blocks", []) if row["page"] == number
        )
        if packet.get("block_ids") != expected_block_ids:
            errors.append(f"page {number} packet block inventory differs from the ingestion manifest")
        expected_objects = sorted(
            (
                {"id": row["id"], "kind": kind}
                for kind, collection in (("table", "tables"), ("figure", "figures"), ("equation", "equations"))
                for row in manifest.get(collection, []) if row["page"] == number
            ),
            key=lambda row: row["id"],
        )
        if packet.get("objects") != expected_objects:
            errors.append(f"page {number} packet object inventory differs from the ingestion manifest")
        if set(packet.get("proposal_ids", [])) != proposal_ids:
            errors.append(f"page {number} packet proposal inventory is incomplete")
    return errors


def decision_errors(
    decisions: dict[str, Any], manifest: dict[str, Any], packets: dict[str, Any],
) -> list[str]:
    """Validate adjudication scope without treating a model as its own verifier."""
    errors: list[str] = []
    try:
        import jsonschema
        schema_path = Path(__file__).resolve().parents[1] / "assets/pdf-reconciliation-decisions.schema.json"
        schema = strict_json_load(schema_path)
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        errors.extend(
            f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in validator.iter_errors(decisions)
        )
    except (ImportError, OSError, json.JSONDecodeError) as exc:
        return [f"cannot validate the decision schema: {exc}"]
    if errors:
        return errors
    if decisions["source_sha256"] != manifest.get("source", {}).get("sha256"):
        errors.append("decision source hash differs from the ingestion source")
    if decisions["packets_sha256"] != manifest.get("reconciliation", {}).get("packets_sha256"):
        errors.append("decision packet hash differs from the ingestion manifest")

    targets: dict[str, dict[str, Any]] = {}
    for page in packets.get("pages", []):
        render_hash = page.get("render", {}).get("sha256")
        for target in page.get("targets", []):
            targets[target["target_id"]] = {
                "page": page["page"], "render_hash": render_hash, "crop_hash": None,
            }
        for obj in page.get("object_evidence", []):
            targets[obj["id"]] = {
                "page": page["page"], "render_hash": render_hash,
                "crop_hash": obj.get("crop_sha256"),
            }
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for decision in decisions["decisions"]:
        target_id = decision["target_id"]
        if target_id in seen:
            errors.append(f"duplicate reconciliation decision: {target_id}")
            continue
        seen.add(target_id)
        target = targets.get(target_id)
        if target is None:
            errors.append(f"decision refers to an unknown packet target: {target_id}")
            continue
        if decision["page"] != target["page"]:
            errors.append(f"decision page differs from its packet target: {target_id}")
        evidence = set(decision["evidence_hashes"])
        if target["render_hash"] not in evidence:
            errors.append(f"decision omits the authoritative page render: {target_id}")
        if decision["state"] == "render_verified" and target["crop_hash"] and target["crop_hash"] not in evidence:
            errors.append(f"render-verified object omits its crop evidence: {target_id}")
        if decision["state"] == "model_adjudicated" and decision["verifier"]["kind"] != "model":
            errors.append(f"model-adjudicated decision lacks model provenance: {target_id}")
        if decision["state"] == "render_verified" and decision["unreadable_regions"]:
            errors.append(f"render-verified decision still declares unreadable regions: {target_id}")
        counts[decision["state"]] += 1
    expected_summary = {
        "model_adjudicated": counts["model_adjudicated"],
        "render_verified": counts["render_verified"],
        "bounded": counts["bounded"],
    }
    if decisions["summary"] != expected_summary:
        errors.append("decision summary differs from the decision inventory")
    expected_status = (
        "bounded" if counts["bounded"] else
        "verified_scope" if decisions["decisions"] and counts["render_verified"] == len(decisions["decisions"])
        else "partial"
    )
    if decisions["scope_status"] != expected_status:
        errors.append("decision scope status differs from the decision inventory")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("decisions", type=Path)
    args = parser.parse_args()
    try:
        manifest = strict_json_load(args.package_dir / "ingestion.json")
        packets_path = args.package_dir / "reconciliation/page-packets.json"
        packets = strict_json_load(packets_path)
        decisions = strict_json_load(args.decisions)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"PDF reconciliation validation failed: {exc}", file=sys.stderr)
        return 1
    observed_packets = hashlib.sha256(packets_path.read_bytes()).hexdigest()
    if observed_packets != manifest.get("reconciliation", {}).get("packets_sha256"):
        print("PDF reconciliation validation failed: page-packet hash mismatch", file=sys.stderr)
        return 1
    errors = decision_errors(decisions, manifest, packets)
    if errors:
        print(f"PDF reconciliation validation failed: {len(errors)} error(s)", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"PDF reconciliation decisions verified: {args.decisions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
