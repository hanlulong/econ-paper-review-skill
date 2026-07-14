#!/usr/bin/env python3
"""Record observed econ-review stage timings without estimating unavailable data."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from safe_io import atomic_write_json, strict_json_load


STAGES = (
    "intake",
    "reconstruction",
    "frontier",
    "audit",
    "counterargument",
    "synthesis",
    "verification",
    "delivery",
)
STATE_NAME = ".econ-review-timing.json"


def load_object(path: Path) -> dict[str, Any]:
    value = strict_json_load(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_state(review_dir: Path, *, create: bool) -> dict[str, Any]:
    path = review_dir / STATE_NAME
    if path.exists():
        state = load_object(path)
        if state.get("schema_version") != "1":
            raise ValueError(f"{path} has an unsupported schema version")
        if not isinstance(state.get("active"), dict) or not isinstance(
            state.get("completed_seconds"), dict
        ):
            raise ValueError(f"{path} is malformed")
        return state
    if not create:
        raise ValueError("timing has not been started for this review")
    now = time.time()
    return {
        "schema_version": "1",
        "started_at_epoch": now,
        "active": {},
        "completed_seconds": {},
    }


def update_run_telemetry(
    review_dir: Path,
    completed_seconds: dict[str, Any],
    *,
    wall_clock_seconds: float | None = None,
) -> None:
    run = load_object(review_dir / "run.json")
    telemetry = run.get("telemetry")
    if not isinstance(telemetry, dict):
        raise ValueError("run.json.telemetry must exist before timing starts")
    telemetry["stage_seconds"] = {
        stage: (
            round(float(completed_seconds[stage]), 3)
            if stage in completed_seconds
            else None
        )
        for stage in STAGES
    }
    if wall_clock_seconds is not None:
        telemetry["wall_clock_seconds"] = round(wall_clock_seconds, 3)
    atomic_write_json(review_dir, "run.json", run)


def start(review_dir: Path, stage: str) -> None:
    state = load_state(review_dir, create=True)
    active = state["active"]
    if stage in active:
        raise ValueError(f"stage {stage!r} is already being timed")
    if stage in state["completed_seconds"]:
        raise ValueError(f"stage {stage!r} already has a completed timing")
    active[stage] = time.time()
    atomic_write_json(review_dir, STATE_NAME, state)


def finish(review_dir: Path, stage: str) -> None:
    state = load_state(review_dir, create=False)
    active = state["active"]
    started = active.pop(stage, None)
    if not isinstance(started, (int, float)):
        raise ValueError(f"stage {stage!r} is not currently being timed")
    elapsed = max(0.0, time.time() - float(started))
    state["completed_seconds"][stage] = elapsed
    atomic_write_json(review_dir, STATE_NAME, state)
    update_run_telemetry(review_dir, state["completed_seconds"])


def transition(review_dir: Path, from_stage: str, to_stage: str) -> None:
    if from_stage == to_stage:
        raise ValueError("timing transition requires two different stages")
    state = load_state(review_dir, create=False)
    active = state["active"]
    started = active.pop(from_stage, None)
    if not isinstance(started, (int, float)):
        raise ValueError(f"stage {from_stage!r} is not currently being timed")
    if to_stage in active or to_stage in state["completed_seconds"]:
        raise ValueError(f"stage {to_stage!r} has already been timed or started")
    now = time.time()
    state["completed_seconds"][from_stage] = max(0.0, now - float(started))
    active[to_stage] = now
    atomic_write_json(review_dir, STATE_NAME, state)
    update_run_telemetry(review_dir, state["completed_seconds"])


def complete(review_dir: Path) -> None:
    state = load_state(review_dir, create=False)
    if state["active"]:
        raise ValueError(
            "cannot complete timing while stages remain active: "
            + ", ".join(sorted(state["active"]))
        )
    started = state.get("started_at_epoch")
    if not isinstance(started, (int, float)):
        raise ValueError("timing state lacks a valid overall start")
    update_run_telemetry(
        review_dir,
        state["completed_seconds"],
        wall_clock_seconds=max(0.0, time.time() - float(started)),
    )
    (review_dir / STATE_NAME).unlink()


def finish_delivery_for_finalizer(review_dir: Path) -> bool:
    """Complete delivery and overall timing inside the staged transaction."""

    state_path = review_dir / STATE_NAME
    if not state_path.exists():
        return False
    state = load_state(review_dir, create=False)
    active = state["active"]
    if set(active) != {"delivery"}:
        detail = ", ".join(sorted(active)) or "none"
        raise ValueError(
            "finalization timing requires delivery to be the only active stage; "
            f"active stages: {detail}"
        )
    now = time.time()
    delivery_started = active.pop("delivery")
    state["completed_seconds"]["delivery"] = max(
        0.0, now - float(delivery_started)
    )
    overall_started = state.get("started_at_epoch")
    if not isinstance(overall_started, (int, float)):
        raise ValueError("timing state lacks a valid overall start")
    update_run_telemetry(
        review_dir,
        state["completed_seconds"],
        wall_clock_seconds=max(0.0, now - float(overall_started)),
    )
    state_path.unlink()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "finish"):
        child = subparsers.add_parser(command)
        child.add_argument("review_dir", type=Path)
        child.add_argument("--stage", choices=STAGES, required=True)
    child = subparsers.add_parser("transition")
    child.add_argument("review_dir", type=Path)
    child.add_argument("--from-stage", choices=STAGES, required=True)
    child.add_argument("--to-stage", choices=STAGES, required=True)
    child = subparsers.add_parser("complete")
    child.add_argument("review_dir", type=Path)
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().resolve(strict=True)
    try:
        if args.command == "start":
            start(review_dir, args.stage)
        elif args.command == "finish":
            finish(review_dir, args.stage)
        elif args.command == "transition":
            transition(review_dir, args.from_stage, args.to_stage)
        else:
            complete(review_dir)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        parser.exit(1, f"review timing failed: {exc}\n")
    return 0


if __name__ == "__main__":
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
