#!/usr/bin/env python3
"""Validate a review-actions.json handoff before next-round reconciliation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA = Path(__file__).resolve().parents[1] / "assets" / "review-actions.schema.json"
MAX_ACTIONS_BYTES = 5 * 1024 * 1024


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        if path.stat().st_size > MAX_ACTIONS_BYTES:
            return [f"review-actions file exceeds {MAX_ACTIONS_BYTES} bytes"]
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"missing review-actions file: {path}"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"cannot read review-actions file: {exc}"]

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path)
        errors.append(f"schema violation at {location or '<root>'}: {error.message}")
    if errors or not isinstance(payload, dict):
        return errors

    entries = payload.get("entries", [])
    ids = [entry.get("finding_id") for entry in entries if isinstance(entry, dict)]
    duplicates = sorted({finding_id for finding_id in ids if ids.count(finding_id) > 1})
    if duplicates:
        errors.append("duplicate finding IDs: " + ", ".join(duplicates))
    paths = [source.get("path") for source in payload.get("source_manuscripts", []) if isinstance(source, dict)]
    duplicate_paths = sorted({source for source in paths if paths.count(source) > 1})
    if duplicate_paths:
        errors.append("duplicate source manuscript paths: " + ", ".join(duplicate_paths))

    try:
        exported_at = timestamp(payload["exported_at"])
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
            if payload.get("schema_version") == "0.3":
                events = entry["events"]
                event_ids = [event["event_id"] for event in events]
                duplicate_events = sorted({event_id for event_id in event_ids if event_ids.count(event_id) > 1})
                if duplicate_events:
                    errors.append(f"entries[{index}] has duplicate event IDs: {', '.join(duplicate_events)}")
                seen: set[str] = set()
                event_times: list[datetime] = []
                replay_disposition = "open"
                replay_note = ""
                replay_history: list[dict[str, str]] = []
                for event_index, event in enumerate(events):
                    event_id = event["event_id"]
                    parent = event.get("parent_event_id")
                    if event_index == 0 and parent is not None:
                        errors.append(f"entries[{index}].events[0] must have a null parent_event_id")
                    elif event_index > 0 and parent not in seen:
                        errors.append(
                            f"entries[{index}].events[{event_index}] parent_event_id must reference an earlier event"
                        )
                    if event.get("type") == "reversed" and parent is None:
                        errors.append(f"entries[{index}].events[{event_index}] reversal requires a parent event")
                    seen.add(event_id)
                    event_at = timestamp(event["at"])
                    event_times.append(event_at)
                    if "disposition" in event:
                        replay_disposition = event["disposition"]
                        replay_history.append({"disposition": replay_disposition, "at": event["at"]})
                    if "note" in event:
                        replay_note = event["note"] or ""
                if event_times != sorted(event_times):
                    errors.append(f"entries[{index}] events are not chronological")
                if event_times and event_times[-1] > exported_at:
                    errors.append(f"entries[{index}] final event is later than exported_at")
                if entry["disposition"] != replay_disposition:
                    errors.append(f"entries[{index}] disposition differs from replayed events")
                if entry["response_note"] != replay_note:
                    errors.append(f"entries[{index}] response_note differs from replayed events")
                if entry["status_history"] != replay_history:
                    errors.append(f"entries[{index}] status_history differs from replayed events")
                if events and entry["updated_at"] != events[-1]["at"]:
                    errors.append(f"entries[{index}] updated_at differs from final event time")
    except (KeyError, IndexError, TypeError, ValueError):
        # Structural/date errors were already reported by JSON Schema.
        pass
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
