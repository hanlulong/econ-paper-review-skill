#!/usr/bin/env python3
"""Validate a review-actions.json handoff before next-round reconciliation."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import canonical_portable_path, strict_json_load  # noqa: E402


SCHEMA = Path(__file__).resolve().parents[1] / "assets" / "review-actions.schema.json"
MAX_ACTIONS_BYTES = 5 * 1024 * 1024


def timestamp(value: str) -> datetime:
    if len(value) < 20 or value[10] != "T" or value.endswith("z"):
        raise ValueError(
            "timestamps must use canonical RFC 3339 with uppercase T and uppercase Z when used"
        )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        if path.stat().st_size > MAX_ACTIONS_BYTES:
            return [f"review-actions file exceeds {MAX_ACTIONS_BYTES} bytes"]
        payload: Any = strict_json_load(path)
    except FileNotFoundError:
        return [f"missing review-actions file: {path}"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [f"cannot read review-actions file: {exc}"]

    schema = strict_json_load(SCHEMA)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path)
        errors.append(f"schema violation at {location or '<root>'}: {error.message}")
    if errors or not isinstance(payload, dict):
        return errors

    entries = payload.get("entries", [])
    ids = [entry.get("finding_id") for entry in entries if isinstance(entry, dict)]
    duplicates = sorted(finding_id for finding_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append("duplicate finding IDs: " + ", ".join(duplicates))
    paths = [source.get("path") for source in payload.get("source_manuscripts", []) if isinstance(source, dict)]
    for index, raw_path in enumerate(paths):
        if not isinstance(raw_path, str):
            continue
        try:
            canonical = canonical_portable_path(raw_path)
        except ValueError as exc:
            errors.append(f"source_manuscripts[{index}].path is not portable: {exc}")
        else:
            if canonical != raw_path:
                errors.append(
                    f"source_manuscripts[{index}].path is not canonical: {raw_path!r}"
                )
    duplicate_paths = sorted(source for source, count in Counter(paths).items() if count > 1)
    if duplicate_paths:
        errors.append("duplicate source manuscript paths: " + ", ".join(duplicate_paths))
    folded_paths = [path.casefold() for path in paths if isinstance(path, str)]
    if len(set(folded_paths)) != len(folded_paths):
        errors.append("source manuscript paths must not collide by case")

    try:
        exported_at = timestamp(payload["exported_at"])
        all_event_ids: list[str] = []
        for index, entry in enumerate(entries):
            history = entry["status_history"]
            if history[-1]["disposition"] != entry["disposition"]:
                errors.append(f"entries[{index}] disposition differs from final history state")
            history_times = [timestamp(row["at"]) for row in history]
            if history_times != sorted(history_times):
                errors.append(f"entries[{index}] status history is not chronological")
            updated_at = timestamp(entry["updated_at"])
            if updated_at < history_times[-1]:
                errors.append(f"entries[{index}] updated_at precedes final status history")
            if updated_at > exported_at:
                errors.append(f"entries[{index}] updated_at is later than exported_at")
            if payload.get("schema_version") in {"0.3", "0.4"}:
                events = entry["events"]
                event_ids = [event["event_id"] for event in events]
                all_event_ids.extend(event_ids)
                duplicate_events = sorted(
                    event_id for event_id, count in Counter(event_ids).items() if count > 1
                )
                if duplicate_events:
                    errors.append(f"entries[{index}] has duplicate event IDs: {', '.join(duplicate_events)}")
                event_times: list[datetime] = []
                replay_disposition = "open"
                replay_note = ""
                replay_priority: str | None = None
                replay_reviewed = False
                replay_history: list[dict[str, str]] = []
                for event_index, event in enumerate(events):
                    parent = event.get("parent_event_id")
                    if event_index == 0 and parent is not None:
                        errors.append(f"entries[{index}].events[0] must have a null parent_event_id")
                    elif event_index > 0 and parent != events[event_index - 1]["event_id"]:
                        errors.append(
                            f"entries[{index}].events[{event_index}] parent_event_id must reference the preceding event"
                        )
                    if event.get("type") == "reversed" and parent is None:
                        errors.append(f"entries[{index}].events[{event_index}] reversal requires a parent event")
                    event_at = timestamp(event["at"])
                    event_times.append(event_at)
                    if "disposition" in event:
                        replay_disposition = event["disposition"]
                        replay_history.append({"disposition": replay_disposition, "at": event["at"]})
                    if "note" in event:
                        replay_note = event["note"] or ""
                    if event.get("type") == "priority_changed":
                        replay_priority = event["user_priority"]
                    if event.get("type") == "reviewed_changed":
                        replay_reviewed = event["reviewed"]
                if event_times != sorted(event_times):
                    errors.append(f"entries[{index}] events are not chronological")
                if event_times and event_times[-1] > exported_at:
                    errors.append(f"entries[{index}] final event is later than exported_at")
                if entry["disposition"] != replay_disposition:
                    errors.append(f"entries[{index}] disposition differs from replayed events")
                if entry["response_note"] != replay_note:
                    errors.append(f"entries[{index}] response_note differs from replayed events")
                if payload.get("schema_version") == "0.4":
                    if entry["user_priority"] != replay_priority:
                        errors.append(f"entries[{index}] user_priority differs from replayed events")
                    if entry["reviewed"] != replay_reviewed:
                        errors.append(f"entries[{index}] reviewed differs from replayed events")
                    if entry["disposition"] in {"not_relevant", "not_addressable"} and not entry["reviewed"]:
                        errors.append(
                            f"entries[{index}] excluded disposition must be marked reviewed"
                        )
                if entry["status_history"] != replay_history:
                    errors.append(f"entries[{index}] status_history differs from replayed events")
                if events and entry["updated_at"] != events[-1]["at"]:
                    errors.append(f"entries[{index}] updated_at differs from final event time")
        duplicate_event_ids = sorted(
            event_id for event_id, count in Counter(all_event_ids).items() if count > 1
        )
        if duplicate_event_ids:
            errors.append(
                "event IDs must be globally unique across entries: "
                + ", ".join(duplicate_event_ids)
            )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        # Schema format checkers and runtime date parsers do not accept exactly
        # the same RFC 3339 surface. Never let that mismatch skip replay or
        # chronology validation silently.
        errors.append(f"semantic action validation failed: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("actions_file", type=Path)
    args = parser.parse_args()
    errors = validate(args.actions_file)
    if errors:
        print("review-actions validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"review-actions validation passed: {args.actions_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
