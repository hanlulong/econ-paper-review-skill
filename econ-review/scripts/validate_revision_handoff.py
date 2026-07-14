#!/usr/bin/env python3
"""Validate a user revision plan and an implementation-agent response."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import canonical_portable_path, is_link_or_junction, strict_json_load  # noqa: E402
from validate_review_actions import validate as validate_actions_file  # noqa: E402


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
TASKS_SCHEMA = ASSET_DIR / "revision-tasks.schema.json"
RESPONSE_SCHEMA = ASSET_DIR / "agent-response.schema.json"
MAX_HANDOFF_BYTES = 5 * 1024 * 1024
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, None: 3}
TASK_BINDING_FIELDS = (
    "finding_id", "user_priority", "reviewed", "disposition", "user_comment", "title",
    "issue", "relevant_text", "suggestions", "done_when", "source_location",
)
EXCLUDED_BINDING_FIELDS = (
    "finding_id", "user_priority", "reviewed", "disposition", "user_comment", "title",
)


def timestamp(value: str, label: str) -> datetime:
    if len(value) < 20 or value[10] != "T" or value.endswith("z"):
        raise ValueError(
            f"{label} must use canonical RFC 3339 with uppercase T and uppercase Z when used"
        )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_payload(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        if is_link_or_junction(path) or not path.is_file():
            errors.append(f"{label} must be a regular non-link file: {path}")
            return None
        if path.stat().st_size > MAX_HANDOFF_BYTES:
            errors.append(f"{label} exceeds {MAX_HANDOFF_BYTES} bytes")
            return None
        value = strict_json_load(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot read {label}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return None
    return value


def schema_errors(value: dict[str, Any], schema_path: Path, label: str) -> list[str]:
    schema = strict_json_load(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[str] = []
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path)
        errors.append(f"{label} schema violation at {location or '<root>'}: {error.message}")
    return errors


def duplicate_values(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def expected_plan_id(payload: dict[str, Any]) -> str:
    """Reproduce the viewer's content-derived UUID over the semantic plan snapshot."""

    binding = {
        "source_review_id": payload["source_review_id"],
        "source_review_fingerprint": payload["source_review_fingerprint"],
        "generated_at": payload["generated_at"],
        "all_comments_reviewed": payload["all_comments_reviewed"],
        "handoff_ready": payload["handoff_ready"],
        "tasks": [
            {field: row[field] for field in TASK_BINDING_FIELDS}
            for row in payload["tasks"]
        ],
        "excluded": [
            {field: row[field] for field in EXCLUDED_BINDING_FIELDS}
            for row in payload["excluded"]
        ],
    }
    seed = json.dumps(binding, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return (
        f"{digest[:8]}-{digest[8:12]}-5{digest[13:16]}-"
        f"a{digest[17:20]}-{digest[20:32]}"
    )


def validate_tasks(path: Path) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    payload = load_payload(path, "revision tasks", errors)
    if payload is None:
        return errors, None
    errors.extend(schema_errors(payload, TASKS_SCHEMA, "revision tasks"))
    if errors:
        return errors, payload
    if payload["plan_id"] != expected_plan_id(payload):
        errors.append("revision tasks plan_id does not match the task snapshot")
    tasks = payload["tasks"]
    excluded = payload["excluded"]
    task_ids = [row["finding_id"] for row in tasks]
    excluded_ids = [row["finding_id"] for row in excluded]
    duplicates = duplicate_values(task_ids + excluded_ids)
    if duplicates:
        errors.append("revision tasks repeat finding IDs: " + ", ".join(duplicates))
    all_rows = tasks + excluded
    expected_reviewed = all(row["reviewed"] for row in all_rows)
    if payload["all_comments_reviewed"] != expected_reviewed:
        errors.append(
            "revision tasks all_comments_reviewed must equal the per-comment reviewed states"
        )
    expected_ready = (
        expected_reviewed
        and all(row["user_priority"] is not None for row in tasks)
        and all(row["user_comment"].strip() for row in all_rows)
    )
    if payload["handoff_ready"] != expected_ready:
        errors.append(
            "revision tasks handoff_ready must reflect reviewed comments, active priorities, "
            "and nonblank user comments"
        )
    priorities = [PRIORITY_ORDER[row["user_priority"]] for row in tasks]
    if priorities != sorted(priorities):
        errors.append("revision tasks must be ordered P0, P1, P2, then unassigned")
    try:
        timestamp(payload["generated_at"], "revision tasks generated_at")
    except (TypeError, ValueError) as exc:
        errors.append(str(exc))
    return errors, payload


def normalized_note(value: Any) -> str:
    """Return the canonical newline form used by both handoff validation stages."""

    return value.replace("\r\n", "\n").replace("\r", "\n") if isinstance(value, str) else ""


def validate_source_bindings(
    tasks: dict[str, Any],
    *,
    findings_path: Path | None,
    actions_path: Path | None,
) -> list[str]:
    """Bind a plan to its canonical findings and committed author-action snapshot."""

    errors: list[str] = []
    plan_rows = tasks["tasks"] + tasks["excluded"]
    plan_by_id = {row["finding_id"]: row for row in plan_rows}

    if findings_path is not None:
        findings = load_payload(findings_path, "source findings", errors)
        if findings is not None:
            errors.extend(schema_errors(findings, ASSET_DIR / "findings.schema.json", "source findings"))
        if findings is not None and not errors:
            if findings.get("review_id") != tasks["source_review_id"]:
                errors.append("source findings review_id does not match revision tasks")
            # Bind the exact canonical findings.json bytes loaded by Review
            # Desk. Re-serializing parsed JSON here would make the digest
            # depend on Python-versus-JavaScript number and Unicode rendering.
            fingerprint = hashlib.sha256(findings_path.read_bytes()).hexdigest()
            if fingerprint != tasks["source_review_fingerprint"]:
                errors.append("source findings fingerprint does not match revision tasks")
            rows = findings.get("findings", [])
            active_ids = {
                row.get("id")
                for row in rows
                if isinstance(row, dict) and row.get("status") not in {"dismissed", "resolved"}
            }
            if set(plan_by_id) != active_ids:
                missing = sorted(active_ids - set(plan_by_id))
                extra = sorted(set(plan_by_id) - active_ids)
                if missing:
                    errors.append("revision tasks omit active source findings: " + ", ".join(missing))
                if extra:
                    errors.append("revision tasks include inactive or unknown source findings: " + ", ".join(extra))

    if actions_path is not None:
        action_errors = validate_actions_file(actions_path)
        errors.extend(f"source review actions: {error}" for error in action_errors)
        actions = load_payload(actions_path, "source review actions", errors)
        if actions is not None and not action_errors:
            if actions.get("source_review_id") != tasks["source_review_id"]:
                errors.append("source review actions review_id does not match revision tasks")
            if actions.get("source_review_fingerprint") != tasks["source_review_fingerprint"]:
                errors.append("source review actions fingerprint does not match revision tasks")
            entries = {
                row.get("finding_id"): row
                for row in actions.get("entries", [])
                if isinstance(row, dict) and isinstance(row.get("finding_id"), str)
            }
            for finding_id, row in plan_by_id.items():
                entry = entries.get(finding_id)
                expected = {
                    "disposition": "open",
                    "user_priority": None,
                    "reviewed": False,
                    "user_comment": "",
                } if entry is None else {
                    "disposition": entry.get("disposition"),
                    "user_priority": entry.get("user_priority"),
                    "reviewed": entry.get("reviewed"),
                    "user_comment": normalized_note(entry.get("response_note")),
                }
                observed = {
                    "disposition": row["disposition"],
                    "user_priority": row["user_priority"],
                    "reviewed": row["reviewed"],
                    "user_comment": normalized_note(row["user_comment"]),
                }
                if observed != expected:
                    errors.append(
                        f"revision task {finding_id} does not match the committed review action"
                    )
            update_times = sorted(
                row.get("updated_at")
                for row in entries.values()
                if isinstance(row.get("updated_at"), str)
            )
            expected_time = update_times[-1] if update_times else "1970-01-01T00:00:00.000Z"
            if tasks["generated_at"] != expected_time:
                errors.append("revision tasks generated_at does not match the action snapshot")
    return errors


def _portable_paths(entry: dict[str, Any], index: int, errors: list[str]) -> None:
    for path_index, raw_path in enumerate(entry["changed_files"]):
        try:
            canonical = canonical_portable_path(raw_path)
        except ValueError as exc:
            errors.append(
                f"agent response entries[{index}].changed_files[{path_index}] is not portable: {exc}"
            )
        else:
            if canonical != raw_path:
                errors.append(
                    f"agent response entries[{index}].changed_files[{path_index}] is not canonical"
                )
    for location_index, location in enumerate(entry["changed_locations"]):
        raw_path = location["path"]
        try:
            canonical = canonical_portable_path(raw_path)
        except ValueError as exc:
            errors.append(
                f"agent response entries[{index}].changed_locations[{location_index}].path "
                f"is not portable: {exc}"
            )
        else:
            if canonical != raw_path:
                errors.append(
                    f"agent response entries[{index}].changed_locations[{location_index}].path "
                    "is not canonical"
                )


def validate_response(
    path: Path,
    tasks: dict[str, Any],
    *,
    template: bool,
) -> list[str]:
    errors: list[str] = []
    payload = load_payload(path, "agent response", errors)
    if payload is None:
        return errors
    errors.extend(schema_errors(payload, RESPONSE_SCHEMA, "agent response"))
    if errors:
        return errors
    for field in ("plan_id", "source_review_id", "source_review_fingerprint"):
        if payload[field] != tasks[field]:
            errors.append(f"agent response {field} does not match revision tasks")
    entries = payload["entries"]
    response_ids = [entry["finding_id"] for entry in entries]
    duplicates = duplicate_values(response_ids)
    if duplicates:
        errors.append("agent response repeats finding IDs: " + ", ".join(duplicates))
    expected_ids = {entry["finding_id"] for entry in tasks["tasks"]}
    observed_ids = set(response_ids)
    missing = sorted(expected_ids - observed_ids)
    extra = sorted(observed_ids - expected_ids)
    if missing:
        errors.append("agent response omits active revision tasks: " + ", ".join(missing))
    if extra:
        errors.append("agent response includes non-task finding IDs: " + ", ".join(extra))
    if template:
        if payload["responded_at"] is not None:
            errors.append("response template responded_at must be null")
        if any(entry["status"] != "not_attempted" for entry in entries):
            errors.append("response template entries must start as not_attempted")
    else:
        if payload["responded_at"] is None:
            errors.append("returned agent response requires responded_at")
        else:
            try:
                responded_at = timestamp(payload["responded_at"], "agent response responded_at")
                generated_at = timestamp(tasks["generated_at"], "revision tasks generated_at")
                if responded_at < generated_at:
                    errors.append("agent response responded_at precedes the revision plan")
            except (TypeError, ValueError) as exc:
                errors.append(str(exc))
        if not tasks["handoff_ready"]:
            errors.append(
                "agent response cannot be accepted until every comment is reviewed, every active "
                "task has a priority, and every comment has a user instruction or reason"
            )
    for index, entry in enumerate(entries):
        _portable_paths(entry, index, errors)
        changed_files = set(entry["changed_files"])
        location_files = {location["path"] for location in entry["changed_locations"]}
        location_keys = [
            (location["path"], location["locator"], location["summary"])
            for location in entry["changed_locations"]
        ]
        if len(location_keys) != len(set(location_keys)):
            errors.append(f"agent response entries[{index}] repeats a changed location")
        check_names = [check["check"].strip().casefold() for check in entry["verification"]]
        if len(check_names) != len(set(check_names)):
            errors.append(f"agent response entries[{index}] repeats a verification check")
        unlisted = sorted(location_files - changed_files)
        if unlisted:
            errors.append(
                f"agent response entries[{index}] changed locations use files absent from changed_files: "
                + ", ".join(unlisted)
            )
        if entry["status"] == "changed":
            results = [check["result"] for check in entry["verification"]]
            if not results or any(result != "passed" for result in results):
                errors.append(
                    f"agent response entries[{index}] changed status requires every reported check to pass"
                )
        if entry["status"] in {"changed", "partial"} and changed_files != location_files:
            errors.append(
                f"agent response entries[{index}] must locate every changed file exactly"
            )
        if entry["status"] == "partial" and not (
            entry["changed_files"] or entry["verification"] or (entry["blocker"] or "").strip()
        ):
            errors.append(
                f"agent response entries[{index}] partial status must record work, a check, or a blocker"
            )
    return errors


def validate(
    tasks_path: Path,
    response_path: Path | None = None,
    *,
    template: bool = False,
    findings_path: Path | None = None,
    actions_path: Path | None = None,
) -> list[str]:
    errors, tasks = validate_tasks(tasks_path)
    if tasks is not None and not errors:
        errors.extend(
            validate_source_bindings(
                tasks,
                findings_path=findings_path,
                actions_path=actions_path,
            )
        )
    if response_path is not None and tasks is not None and not errors:
        errors.extend(validate_response(response_path, tasks, template=template))
    elif template and response_path is None:
        errors.append("--template requires --response")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("revision_tasks", type=Path, help="Viewer-exported revision-tasks.json")
    parser.add_argument("--findings", type=Path, help="Canonical source findings.json")
    parser.add_argument("--actions", type=Path, help="Matching committed review-actions.json")
    parser.add_argument("--response", type=Path, help="Agent-completed response JSON")
    parser.add_argument(
        "--template",
        action="store_true",
        help="Validate an untouched revision-response.template.json",
    )
    args = parser.parse_args()
    errors = validate(
        args.revision_tasks,
        args.response,
        template=args.template,
        findings_path=args.findings,
        actions_path=args.actions,
    )
    if errors:
        print("revision handoff validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    label = "draft response template" if args.template else "revision handoff"
    print(f"{label} validation passed")
    return 0


if __name__ == "__main__":
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
