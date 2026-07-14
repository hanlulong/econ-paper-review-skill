#!/usr/bin/env python3
"""Build authenticated v0.4 external-source snapshots and source fragments."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import (  # noqa: E402
    atomic_write_bytes,
    canonical_portable_path,
    is_link_or_junction,
    safe_read_bytes,
    sha256_bytes,
    strict_json_load,
    strict_json_loads,
)
from trust_spine import (  # noqa: E402
    EXTERNAL_METADATA_PROJECTION_FIELDS,
    external_metadata_projection,
    validate_external_source_fragment,
)


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
EXTERNAL_SCHEMA = ASSET_DIR / "external-sources.schema.json"
MAX_SPEC_BYTES = 5 * 1024 * 1024
GENERATED_SOURCE_FIELDS = frozenset(
    {"supported_propositions", "support_records", "snapshot_sha256"}
)
GENERATED_SUPPORT_FIELDS = frozenset(
    {
        "snapshot_excerpt",
        "snapshot_start",
        "snapshot_end",
        "snapshot_excerpt_sha256",
    }
)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _normalize_lf(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _support_record(value: Any, label: str) -> dict[str, Any]:
    record = copy.deepcopy(_object(value, label))
    generated = sorted(GENERATED_SUPPORT_FIELDS & set(record))
    if generated:
        raise ValueError(
            f"{label} must omit generated fields: " + ", ".join(generated)
        )
    record.setdefault("scope_complete", False)
    record.setdefault("scope_complete_basis", None)
    record.setdefault("assessment_note", None)
    record.setdefault("boundary_reason", None)
    record.setdefault("finding_ids", [])
    if record.get("support_state") == "inconclusive":
        raise ValueError(
            f"{label} is inconclusive and therefore has no exact support span to capture"
        )
    return record


def _prepare(
    spec: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    source = copy.deepcopy(_object(spec.get("source"), "spec.source"))
    generated = sorted(GENERATED_SOURCE_FIELDS & set(source))
    if generated:
        raise ValueError(
            "spec.source must omit generated fields: " + ", ".join(generated)
        )
    source_id = source.get("id")
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("spec.source.id must be a nonempty string")
    if source.get("snapshot_kind") not in {"source_capture", "official_metadata"}:
        raise ValueError(
            "spec.source.snapshot_kind must be source_capture or official_metadata"
        )
    snapshot_path = source.get("snapshot_path")
    if not isinstance(snapshot_path, str):
        raise ValueError("spec.source.snapshot_path must be a string")
    source["snapshot_path"] = canonical_portable_path(snapshot_path)

    captures = spec.get("captures", [])
    if not isinstance(captures, list):
        raise ValueError("spec.captures must be an array")
    records: list[dict[str, Any]] = []
    excerpts: list[str] = []
    for index, raw_capture in enumerate(captures):
        label = f"spec.captures[{index}]"
        capture = _object(raw_capture, label)
        unknown = sorted(set(capture) - {"support_record", "excerpt"})
        if unknown:
            raise ValueError(f"{label} has unsupported fields: " + ", ".join(unknown))
        excerpt = capture.get("excerpt")
        if not isinstance(excerpt, str) or not excerpt:
            raise ValueError(f"{label}.excerpt must be a nonempty string")
        records.append(_support_record(capture.get("support_record"), f"{label}.support_record"))
        excerpts.append(_normalize_lf(excerpt))

    metadata_capture = spec.get("metadata_projection")
    if metadata_capture is not None:
        capture = _object(metadata_capture, "spec.metadata_projection")
        unknown = sorted(
            set(capture) - {"support_record_id", "locator", "finding_ids"}
        )
        if unknown:
            raise ValueError(
                "spec.metadata_projection has unsupported fields: "
                + ", ".join(unknown)
            )
        metadata = _object(
            source.get("bibliographic_metadata"),
            "spec.source.bibliographic_metadata",
        )
        if "field_support_record_ids" in metadata:
            raise ValueError(
                "spec.source.bibliographic_metadata must omit generated "
                "field_support_record_ids"
            )
        support_id = capture.get("support_record_id")
        locator = capture.get("locator")
        if not isinstance(support_id, str) or not support_id:
            raise ValueError(
                "spec.metadata_projection.support_record_id must be a nonempty string"
            )
        if not isinstance(locator, str) or not locator:
            raise ValueError("spec.metadata_projection.locator must be a nonempty string")
        metadata["field_support_record_ids"] = {
            field: support_id for field in EXTERNAL_METADATA_PROJECTION_FIELDS
        }
        projection = _canonical_json(external_metadata_projection(source))
        records.append(
            {
                "id": support_id,
                "proposition": projection,
                "proposition_kind": "bibliographic_metadata",
                "support_state": "supported",
                "access_scope": "metadata",
                "scope_complete": False,
                "scope_complete_basis": None,
                "assessment_note": None,
                "locator": locator,
                "boundary_reason": None,
                "finding_ids": copy.deepcopy(capture.get("finding_ids", [])),
            }
        )
        excerpts.append(projection)

    if not records:
        raise ValueError("spec must provide at least one capture or metadata projection")
    return source, records, excerpts


def _snapshot_bytes(excerpts: list[str]) -> bytes:
    text = "\n\n".join(excerpts) + "\n"
    value = text.encode("utf-8")
    if b"\r" in value:
        raise AssertionError("LF normalization failed")
    return value


def _bind_written_snapshot(
    spec: dict[str, Any],
    written: bytes,
    *,
    active_finding_ids: set[str],
) -> dict[str, Any]:
    source, record_templates, excerpts = _prepare(spec)
    try:
        text = written.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("written snapshot is not UTF-8") from exc
    if b"\r" in written:
        raise ValueError("written snapshot is not LF-only")
    expected = "\n\n".join(excerpts) + "\n"
    if text != expected:
        raise ValueError("written snapshot bytes differ from the staged capture")

    records: list[dict[str, Any]] = []
    cursor = 0
    for index, (template, expected_excerpt) in enumerate(
        zip(record_templates, excerpts, strict=True)
    ):
        start = cursor
        end = start + len(expected_excerpt)
        excerpt = text[start:end]
        if excerpt != expected_excerpt:
            raise ValueError(f"written support span {index} does not match its capture")
        record = copy.deepcopy(template)
        record.update(
            {
                "snapshot_excerpt": excerpt,
                "snapshot_start": start,
                "snapshot_end": end,
                "snapshot_excerpt_sha256": sha256_bytes(excerpt.encode("utf-8")),
            }
        )
        records.append(record)
        cursor = end + (2 if index < len(excerpts) - 1 else 1)
    if cursor != len(text):
        raise ValueError("written snapshot has trailing content outside captured spans")

    source["support_records"] = records
    source["supported_propositions"] = [
        record["proposition"]
        for record in records
        if record.get("support_state") == "supported"
    ]
    source["snapshot_sha256"] = sha256_bytes(written)
    fragment = {
        "schema_version": "0.4",
        "review_id": spec.get("review_id"),
        "search_confidentiality": spec.get("search_confidentiality"),
        "sources": [source],
    }
    _validate_fragment(fragment, written, active_finding_ids=active_finding_ids)
    return fragment


def _schema_errors(fragment: dict[str, Any]) -> list[str]:
    schema = strict_json_load(EXTERNAL_SCHEMA)
    errors: list[str] = []
    if fragment.get("schema_version") != "0.4":
        errors.append("schema at schema_version: must equal '0.4'")
    if not isinstance(fragment.get("review_id"), str) or not fragment["review_id"]:
        errors.append("schema at review_id: must be a nonempty string")
    if fragment.get("search_confidentiality") not in {
        "forbidden",
        "deidentified",
        "exact_allowed",
    }:
        errors.append("schema at search_confidentiality: invalid policy")
    sources = fragment.get("sources")
    if not isinstance(sources, list) or len(sources) != 1:
        errors.append("schema at sources: fragment must contain exactly one source")
        return errors
    validator = Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).evolve(schema=schema["$defs"]["source"])
    for error in sorted(
        validator.iter_errors(sources[0]), key=lambda item: list(item.absolute_path)
    ):
        location = ".".join(str(part) for part in error.absolute_path)
        errors.append(f"schema at sources.0.{location or '<root>'}: {error.message}")
    return errors


def _validate_fragment(
    fragment: dict[str, Any],
    snapshot: bytes,
    *,
    active_finding_ids: set[str],
) -> None:
    source_id = fragment.get("sources", [{}])[0].get("id")
    errors = _schema_errors(fragment)
    errors.extend(
        validate_external_source_fragment(
            fragment,
            {source_id: snapshot},
            active_finding_ids=active_finding_ids,
        )
    )
    if errors:
        raise ValueError("external source fragment is invalid:\n- " + "\n- ".join(errors))


def _active_finding_ids(review_dir: Path) -> set[str]:
    try:
        raw = safe_read_bytes(review_dir, "findings.json")
    except FileNotFoundError:
        return set()
    findings = strict_json_loads(raw)
    if not isinstance(findings, dict) or not isinstance(findings.get("findings"), list):
        raise ValueError("findings.json must contain a findings array")
    return {
        row.get("id")
        for row in findings["findings"]
        if isinstance(row, dict)
        and isinstance(row.get("id"), str)
        and row.get("status") not in {"dismissed", "resolved"}
        and row.get("severity") in {"critical", "major", "minor", "info"}
    }


def build_fragment(review_dir: Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Stage a snapshot, then bind and validate the bytes actually written."""

    expected = _snapshot_bytes(_prepare(spec)[2])
    with tempfile.TemporaryDirectory(prefix="econ-review-external-") as temporary:
        stage = Path(temporary)
        atomic_write_bytes(stage, "snapshot.txt", expected)
        written = safe_read_bytes(stage, "snapshot.txt")
        return _bind_written_snapshot(
            spec,
            written,
            active_finding_ids=_active_finding_ids(review_dir),
        )


def _destination_exists(root: Path, relative: str) -> bool:
    destination = root.joinpath(*Path(relative).parts)
    return destination.exists() or is_link_or_junction(destination)


def _existing_bytes(root: Path, relative: str) -> bytes | None:
    if not _destination_exists(root, relative):
        return None
    return safe_read_bytes(root, relative)


def _missing_parent_directories(root: Path, relatives: list[str]) -> list[Path]:
    missing: set[Path] = set()
    for relative in relatives:
        path = Path(relative)
        for parent in path.parents:
            if parent == Path("."):
                continue
            candidate = root.joinpath(*parent.parts)
            if not candidate.exists() and not is_link_or_junction(candidate):
                missing.add(candidate)
    return sorted(missing, key=lambda path: len(path.parts), reverse=True)


def _remove_created_file(root: Path, relative: str) -> None:
    try:
        safe_read_bytes(root, relative)
    except FileNotFoundError:
        return
    destination = root.joinpath(*Path(relative).parts)
    if is_link_or_junction(destination) or not destination.is_file():
        raise ValueError(f"refusing to remove non-regular rollback target: {destination}")
    destination.unlink()


def _rollback_writes(
    root: Path,
    attempted: list[str],
    originals: dict[str, bytes | None],
    created_directories: list[Path],
) -> list[str]:
    errors: list[str] = []
    for relative in reversed(attempted):
        try:
            original = originals[relative]
            if original is None:
                _remove_created_file(root, relative)
            else:
                atomic_write_bytes(root, relative, original)
        except (OSError, ValueError) as exc:
            errors.append(f"{relative}: {exc}")
    for directory in created_directories:
        try:
            directory.rmdir()
        except FileNotFoundError:
            continue
        except OSError:
            # Keep a directory when it is no longer empty or another process
            # began using it; never remove unrelated package content.
            continue
    return errors


def write_capture(
    review_dir: Path,
    spec: dict[str, Any],
    *,
    fragment_path: str | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Commit a validated snapshot and sidecar with rollback on any failure."""

    preview = build_fragment(review_dir, spec)
    snapshot_path = preview["sources"][0]["snapshot_path"]
    fragment_path = (
        canonical_portable_path(fragment_path) if fragment_path is not None else None
    )
    if fragment_path == snapshot_path:
        raise ValueError("fragment path must differ from snapshot path")
    destinations = [snapshot_path] + ([fragment_path] if fragment_path else [])
    collisions = [
        path for path in destinations if _destination_exists(review_dir, str(path))
    ]
    if collisions and not replace_existing:
        raise FileExistsError(
            "refusing to replace existing package paths: "
            + ", ".join(str(path) for path in collisions)
        )

    snapshot = _snapshot_bytes(_prepare(spec)[2])
    active_finding_ids = _active_finding_ids(review_dir)
    fragment = _bind_written_snapshot(
        spec,
        snapshot,
        active_finding_ids=active_finding_ids,
    )
    fragment_bytes = (
        json.dumps(fragment, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")
    if fragment_path is not None:
        observed = strict_json_loads(fragment_bytes)
        if observed != fragment:
            raise ValueError("serialized fragment does not match its validated source record")
        _validate_fragment(
            observed,
            snapshot,
            active_finding_ids=active_finding_ids,
        )

    destinations = [snapshot_path] + ([fragment_path] if fragment_path else [])
    originals = {
        relative: _existing_bytes(review_dir, relative) for relative in destinations
    }
    created_directories = _missing_parent_directories(review_dir, destinations)
    attempted: list[str] = []
    try:
        attempted.append(snapshot_path)
        atomic_write_bytes(review_dir, snapshot_path, snapshot)
        if fragment_path is not None:
            attempted.append(fragment_path)
            atomic_write_bytes(review_dir, fragment_path, fragment_bytes)

        written = safe_read_bytes(review_dir, snapshot_path)
        committed = _bind_written_snapshot(
            spec,
            written,
            active_finding_ids=active_finding_ids,
        )
        if committed != fragment:
            raise ValueError("committed snapshot changed the validated source fragment")
        if fragment_path is not None:
            observed = strict_json_loads(safe_read_bytes(review_dir, fragment_path))
            if observed != committed:
                raise ValueError("written fragment does not match its validated source record")
            _validate_fragment(
                observed,
                written,
                active_finding_ids=active_finding_ids,
            )
        return committed
    except Exception as exc:
        rollback_errors = _rollback_writes(
            review_dir,
            attempted,
            originals,
            created_directories,
        )
        if rollback_errors:
            raise RuntimeError(
                f"external capture write failed ({exc}); rollback also failed: "
                + "; ".join(rollback_errors)
            ) from exc
        raise


def load_spec(path: Path) -> dict[str, Any]:
    if is_link_or_junction(path) or not path.is_file():
        raise ValueError(f"spec must be a regular non-link file: {path}")
    if path.stat().st_size > MAX_SPEC_BYTES:
        raise ValueError(f"spec exceeds {MAX_SPEC_BYTES} bytes")
    return _object(strict_json_load(path), "spec")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("spec", type=Path)
    parser.add_argument(
        "--write",
        action="store_true",
        help="atomically write the snapshot after validation",
    )
    parser.add_argument(
        "--fragment-path",
        help="with --write, also write the validated v0.4 JSON fragment at this package path",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="allow explicit atomic replacement of existing snapshot/fragment files",
    )
    args = parser.parse_args()
    if args.fragment_path and not args.write:
        parser.error("--fragment-path requires --write")
    if args.replace_existing and not args.write:
        parser.error("--replace-existing requires --write")
    try:
        spec = load_spec(args.spec)
        fragment = (
            write_capture(
                args.review_dir,
                spec,
                fragment_path=args.fragment_path,
                replace_existing=args.replace_existing,
            )
            if args.write
            else build_fragment(args.review_dir, spec)
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"external source capture failed: {exc}\n")
    print(json.dumps(fragment, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
