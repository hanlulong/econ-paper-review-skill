#!/usr/bin/env python3
"""Validate and render reviewer-owned reconciliation between review rounds."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import (  # noqa: E402
    atomic_write_text,
    canonical_portable_path,
    safe_read_bytes,
    sha256_bytes,
    strict_json_load,
    strict_json_loads,
)
from validate_revision_handoff import (  # noqa: E402
    normalized_note,
    validate_source_bindings,
    validate_response,
    validate_tasks,
)


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
RECONCILIATION_SCHEMA = ASSET_DIR / "round-reconciliation.schema.json"
FINDINGS_SCHEMA = ASSET_DIR / "findings.schema.json"
RECONCILIATION_JSON = "evidence/round-reconciliation.json"
RECONCILIATION_MD = "evidence/round-reconciliation.md"
MAX_SNAPSHOT_BYTES = 20 * 1024 * 1024
ACTIVE_SEVERITIES = frozenset({"critical", "major", "minor", "info"})
EXCLUSION_DISPOSITIONS = frozenset({"not_relevant", "not_addressable"})
NORMAL_OUTCOMES = frozenset({"resolved", "partly_resolved", "unchanged", "superseded"})
DEFERRED_OUTCOMES = frozenset({"resolved", "partly_resolved", "unchanged"})
EXCLUSION_OUTCOMES = frozenset({"user_excluded"})
OUTCOME_SUMMARY_LABELS = {
    "resolved": "Resolved after recheck",
    "partly_resolved": "Improved but still open",
    "unchanged": "Still open without material progress",
    "superseded": "Reframed as current comments",
    "user_excluded": "Set aside at the author's request",
}
REVIEWER_CONCLUSIONS = {
    "resolved": "The concern is resolved.",
    "partly_resolved": "The revision addresses part of the concern, but further work remains.",
    "unchanged": "The concern remains unresolved.",
    "superseded": "The original diagnosis has been reframed as one or more current comments.",
    "user_excluded": "The comment has been set aside at the author's request after the stated reason was checked.",
}
AGENT_STATUS_SENTENCES = {
    "changed": "The implementation agent reports making changes.",
    "response_only": "The implementation agent gives a response without reporting a file change.",
    "partial": "The implementation agent reports partial progress.",
    "blocked": "The implementation agent reports being unable to complete this item.",
    "not_attempted": "The implementation agent reports that this item was not attempted.",
}
CHECK_RESULT_LABELS = {
    "passed": "condition satisfied",
    "failed": "condition not satisfied",
    "bounded": "only partly verifiable",
}


def _schema_errors(
    value: Any,
    schema_path: Path,
    label: str,
) -> list[str]:
    schema = strict_json_load(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[str] = []
    for error in sorted(
        validator.iter_errors(value), key=lambda item: list(item.absolute_path)
    ):
        location = ".".join(str(part) for part in error.absolute_path)
        errors.append(
            f"{label} schema violation at {location or '<root>'}: {error.message}"
        )
    return errors


def _active_rows(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ledger.get("findings")
    if not isinstance(rows, list):
        return []
    return [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("status") not in {"dismissed", "resolved"}
        and row.get("severity") in ACTIVE_SEVERITIES
        and isinstance(row.get("id"), str)
    ]


def _load_package_json(
    review_dir: Path,
    raw_path: Any,
    label: str,
    errors: list[str],
) -> tuple[dict[str, Any] | None, bytes | None, str | None]:
    if not isinstance(raw_path, str):
        errors.append(f"{label} path must be a canonical package-relative string")
        return None, None, None
    try:
        portable = canonical_portable_path(raw_path)
    except ValueError as exc:
        errors.append(f"{label} path is not canonical and portable: {exc}")
        return None, None, None
    if portable != raw_path:
        errors.append(f"{label} path is not canonical: {raw_path!r}")
        return None, None, None
    try:
        raw = safe_read_bytes(review_dir, portable)
    except (OSError, ValueError) as exc:
        errors.append(f"cannot read {label} at {portable}: {exc}")
        return None, None, portable
    if len(raw) > MAX_SNAPSHOT_BYTES:
        errors.append(f"{label} exceeds {MAX_SNAPSHOT_BYTES} bytes")
        return None, raw, portable
    try:
        value = strict_json_loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot parse {label} at {portable}: {exc}")
        return None, raw, portable
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return None, raw, portable
    return value, raw, portable


def _load_current_json(
    review_dir: Path,
    relative: str,
    label: str,
    errors: list[str],
) -> dict[str, Any] | None:
    try:
        value = strict_json_loads(safe_read_bytes(review_dir, relative))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot read {label}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return None
    return value


def _paragraph(value: str) -> str:
    return " ".join(value.split())


def _check_label(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _fenced_text(value: str) -> list[str]:
    """Render exact handoff prose without interpreting it as report Markdown."""

    normalized = normalized_note(value)
    longest = max((len(match) for match in re.findall(r"`+", normalized)), default=0)
    fence = "`" * max(3, longest + 1)
    return [f"{fence}text", normalized, fence]


def _inline_code(value: str) -> str:
    ticks = max((len(match) for match in re.findall(r"`+", value)), default=0)
    fence = "`" * max(1, ticks + 1)
    padding = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{padding}{value}{padding}{fence}"


def _finding_title(row: dict[str, Any] | None, fallback: str) -> str:
    if isinstance(row, dict):
        for field in ("title", "issue"):
            value = row.get(field)
            if isinstance(value, str) and value.strip():
                return _paragraph(value)
    return fallback


def render(
    payload: dict[str, Any],
    *,
    prior_findings: dict[str, Any],
    current_findings: dict[str, Any],
    revision_tasks: dict[str, Any],
    agent_response: dict[str, Any] | None,
) -> str:
    """Render the readable round history from reviewer and bound handoff state."""

    counts = Counter(row["outcome"] for row in payload["records"])
    prior_by_id = {
        row["id"]: row
        for row in prior_findings.get("findings", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    current_by_id = {
        row["id"]: row
        for row in current_findings.get("findings", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    plan_by_id = {
        row["finding_id"]: row
        for row in revision_tasks.get("tasks", []) + revision_tasks.get("excluded", [])
        if isinstance(row, dict) and isinstance(row.get("finding_id"), str)
    }
    response_by_id = {
        row["finding_id"]: row
        for row in (agent_response or {}).get("entries", [])
        if isinstance(row, dict) and isinstance(row.get("finding_id"), str)
    }
    lines = [
        "# What Changed Since the Prior Review",
        "",
        "This section explains how each earlier comment fared after the revision. "
        "It keeps the author's instructions and the implementation agent's report separate "
        "from the reviewer's independent conclusion.",
        "",
        "## At a glance",
        "",
    ]
    for outcome, label in OUTCOME_SUMMARY_LABELS.items():
        lines.append(f"- {label}: {counts.get(outcome, 0)}")
    if payload["successor_consolidations"]:
        lines.extend(["", "## Comments combined in this review", ""])
        for consolidation in payload["successor_consolidations"]:
            successor_id = consolidation["successor_finding_id"]
            successor_title = _finding_title(
                current_by_id.get(successor_id), "Combined comment in the current review"
            )
            lines.extend([
                f"### {successor_title}",
                f"<!-- successor_finding_id: {successor_id} -->",
                "<!-- prior_finding_ids: "
                + ", ".join(consolidation["prior_finding_ids"])
                + " -->",
                "",
                "This comment brings together these earlier concerns:",
                "",
            ])
            for prior_id in consolidation["prior_finding_ids"]:
                lines.append(
                    "- " + _finding_title(
                        prior_by_id.get(prior_id) or plan_by_id.get(prior_id),
                        "Earlier review comment",
                    )
                )
            lines.extend(["", _paragraph(consolidation["rationale"]), ""])
    lines.extend(["", "## Earlier comments revisited", ""])
    for record in payload["records"]:
        finding_id = record["prior_finding_id"]
        prior = prior_by_id.get(finding_id, {})
        plan = plan_by_id.get(finding_id, {})
        response = response_by_id.get(finding_id)
        title = _finding_title(prior or plan, "Earlier review comment")
        issue = _paragraph(str(prior.get("issue") or ""))
        lines.extend(
            [
                f"### {title}",
                f"<!-- prior_finding_id: {finding_id} -->",
                f"<!-- reviewer_outcome: {record['outcome']} -->",
                "",
            ]
        )
        if issue and issue.casefold() != title.casefold():
            lines.extend([issue, ""])
        user_comment = normalized_note(plan.get("user_comment"))
        if user_comment:
            lines.extend(["**Author's instruction**", "", *_fenced_text(user_comment), ""])
        if response is not None:
            agent_status = str(response.get("status", "not_attempted"))
            lines.extend([
                f"<!-- agent_status: {agent_status} -->",
                "**What the implementation agent reports**",
                "",
                AGENT_STATUS_SENTENCES.get(
                    agent_status, "The implementation agent supplied an update."
                ),
                "",
            ])
            response_text = normalized_note(response.get("response"))
            if response_text:
                lines.extend([*_fenced_text(response_text), ""])
            else:
                lines.extend(["No response summary was recorded.", ""])
            changed_locations = response.get("changed_locations")
            if isinstance(changed_locations, list) and changed_locations:
                lines.extend(["**Locations reported as changed**", ""])
                for location in changed_locations:
                    if not isinstance(location, dict):
                        continue
                    path = _inline_code(str(location.get("path", "")))
                    locator = _paragraph(str(location.get("locator", "")))
                    summary = _paragraph(str(location.get("summary", "")))
                    lines.append(f"- {path} — {locator}: {summary}")
                lines.append("")
            blocker = response.get("blocker")
            if isinstance(blocker, str) and blocker.strip():
                lines.extend(["**Why the work could not be completed**", "", *_fenced_text(blocker), ""])
        lines.extend(
            [
                "**Reviewer's conclusion**",
                "",
                REVIEWER_CONCLUSIONS[record["outcome"]],
                "",
                _paragraph(record["rationale"]),
                "",
            ]
        )
        if record["successor_finding_ids"]:
            lines.extend([
                "<!-- successor_finding_ids: "
                + ", ".join(record["successor_finding_ids"])
                + " -->",
                "**Related comments in this review**",
                "",
            ])
            for successor_id in record["successor_finding_ids"]:
                lines.append(
                    "- " + _finding_title(
                        current_by_id.get(successor_id)
                        or prior_by_id.get(successor_id),
                        "Current review comment",
                    )
                )
            lines.append("")
        lines.extend(["**Evidence the reviewer checked**", ""])
        for check in record["checks"]:
            lines.append(
                "<!-- reviewer_check: "
                f"type={check['type']}; result={check['result']}; "
                f"anchor_ids={','.join(check['anchor_ids'])}; "
                f"computation_ids={','.join(check['computation_ids'])} -->"
            )
            lines.append(
                f"- **{_check_label(check['type'])} — "
                f"{CHECK_RESULT_LABELS[check['result']]}.** {_paragraph(check['notes'])}"
            )
        lines.append("")
    lines.extend(["## New comments in this review", ""])
    if payload["new_finding_ids"]:
        for finding_id in payload["new_finding_ids"]:
            lines.extend([
                f"<!-- new_finding_id: {finding_id} -->",
                "- " + _finding_title(
                    current_by_id.get(finding_id), "New comment in this review"
                ),
            ])
    else:
        lines.append("No new comments were identified.")
    return "\n".join(lines).rstrip() + "\n"


def validate_round_reconciliation(
    review_dir: Path,
    run: dict[str, Any],
    current_ledger: dict[str, Any],
    *,
    check_markdown: bool = True,
) -> list[str]:
    """Validate all snapshot bindings and reviewer adjudication invariants."""

    errors: list[str] = []
    activation = run.get("prior_round")
    if activation is None:
        return errors
    if run.get("schema_version") != "0.4":
        return ["run.json.prior_round is supported only by the v0.4 contract"]
    if not isinstance(activation, dict):
        return ["run.json.prior_round must be an activation object"]

    path_fields = (
        "prior_findings_path",
        "review_actions_path",
        "revision_tasks_path",
        "agent_response_path",
    )
    raw_paths = [activation.get(field) for field in path_fields]
    present_paths = [value for value in raw_paths if isinstance(value, str)]
    if len(present_paths) != len(set(present_paths)):
        errors.append("run.json.prior_round snapshot paths must be unique")
    folded = [value.casefold() for value in present_paths]
    if len(folded) != len(set(folded)):
        errors.append("run.json.prior_round snapshot paths must not collide by case")
    reserved = {RECONCILIATION_JSON, RECONCILIATION_MD, "run.json", "findings.json"}
    overlaps = sorted(set(present_paths) & reserved)
    if overlaps:
        errors.append(
            "prior-round snapshots cannot overwrite current canonical artifacts: "
            + ", ".join(overlaps)
        )
    invalid_snapshot_locations = sorted(
        value for value in present_paths
        if not value.startswith("evidence/prior-round/")
        or Path(value).parent.as_posix() != "evidence/prior-round"
        or Path(value).suffix != ".json"
    )
    if invalid_snapshot_locations:
        errors.append(
            "prior-round snapshots must be JSON files directly under evidence/prior-round: "
            + ", ".join(invalid_snapshot_locations)
        )

    prior_findings, prior_findings_raw, prior_findings_path = _load_package_json(
        review_dir,
        activation.get("prior_findings_path"),
        "prior findings snapshot",
        errors,
    )
    actions, actions_raw, actions_path = _load_package_json(
        review_dir,
        activation.get("review_actions_path"),
        "review actions snapshot",
        errors,
    )
    tasks, tasks_raw, tasks_path = _load_package_json(
        review_dir,
        activation.get("revision_tasks_path"),
        "revision tasks snapshot",
        errors,
    )
    response: dict[str, Any] | None = None
    response_raw: bytes | None = None
    response_path: str | None = None
    if activation.get("agent_response_path") is not None:
        response, response_raw, response_path = _load_package_json(
            review_dir,
            activation.get("agent_response_path"),
            "agent response snapshot",
            errors,
        )

    reconciliation = _load_current_json(
        review_dir,
        RECONCILIATION_JSON,
        "evidence/round-reconciliation.json",
        errors,
    )
    if reconciliation is None:
        return errors
    errors.extend(
        _schema_errors(
            reconciliation,
            RECONCILIATION_SCHEMA,
            "evidence/round-reconciliation.json",
        )
    )
    if errors:
        return errors

    assert (
        prior_findings is not None
        and prior_findings_raw is not None
        and prior_findings_path is not None
    )
    assert actions is not None and actions_raw is not None and actions_path is not None
    assert tasks is not None and tasks_raw is not None and tasks_path is not None

    errors.extend(_schema_errors(prior_findings, FINDINGS_SCHEMA, "prior findings snapshot"))
    task_errors, validated_tasks = validate_tasks(review_dir / tasks_path)
    errors.extend(f"prior revision tasks: {error}" for error in task_errors)
    if validated_tasks is None:
        validated_tasks = tasks
    if not task_errors:
        errors.extend(
            f"prior source binding: {error}"
            for error in validate_source_bindings(
                validated_tasks,
                findings_path=review_dir / prior_findings_path,
                actions_path=review_dir / actions_path,
            )
        )
    if response_path is not None and response is not None:
        errors.extend(
            f"prior agent response: {error}"
            for error in validate_response(
                review_dir / response_path,
                validated_tasks,
                template=False,
            )
        )
    if errors:
        return errors

    current_review_id = run.get("review_id")
    prior_review_id = prior_findings.get("review_id")
    if current_review_id != prior_review_id:
        errors.append(
            "a next round must retain the prior review_id for the same manuscript lineage"
        )
    if reconciliation["review_id"] != current_review_id:
        errors.append("round reconciliation review_id differs from run.json")
    if reconciliation["prior_review_id"] != prior_review_id:
        errors.append("round reconciliation prior_review_id differs from prior findings")
    expected_hashes = {
        "prior_findings_sha256": sha256_bytes(prior_findings_raw),
        "review_actions_sha256": sha256_bytes(actions_raw),
        "revision_tasks_sha256": sha256_bytes(tasks_raw),
        "agent_response_sha256": (
            sha256_bytes(response_raw) if response_raw is not None else None
        ),
    }
    for field, expected in expected_hashes.items():
        if reconciliation[field] != expected:
            errors.append(f"round reconciliation {field} does not match its snapshot")

    if actions.get("schema_version") != "0.4":
        errors.append("round reconciliation requires a v0.4 review-actions snapshot")
    for label, value in (("review actions", actions), ("revision tasks", tasks)):
        if value.get("source_review_id") != prior_review_id:
            errors.append(f"{label} source_review_id differs from prior findings")
    if actions.get("source_review_fingerprint") != tasks.get("source_review_fingerprint"):
        errors.append("review actions and revision tasks source fingerprints differ")
    if reconciliation["plan_id"] != tasks.get("plan_id"):
        errors.append("round reconciliation plan_id differs from revision tasks")
    if tasks.get("handoff_ready") is not True:
        errors.append("round reconciliation requires a handoff-ready prior revision plan")
    if response is not None:
        for field in ("source_review_id", "source_review_fingerprint", "plan_id"):
            if response.get(field) != tasks.get(field):
                errors.append(f"agent response {field} differs from revision tasks")

    prior_rows = prior_findings.get("findings", [])
    all_prior_ids = [
        row.get("id") for row in prior_rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ] if isinstance(prior_rows, list) else []
    duplicate_prior_ids = sorted(
        value for value, count in Counter(all_prior_ids).items() if count > 1
    )
    if duplicate_prior_ids:
        errors.append("prior findings snapshot repeats IDs: " + ", ".join(duplicate_prior_ids))
    prior_active = _active_rows(prior_findings)
    prior_active_ids = [row["id"] for row in prior_active]
    task_rows = tasks.get("tasks", [])
    excluded_rows = tasks.get("excluded", [])
    plan_rows = task_rows + excluded_rows
    plan_ids = [row.get("finding_id") for row in plan_rows if isinstance(row, dict)]
    if Counter(plan_ids) != Counter(prior_active_ids):
        missing = sorted(set(prior_active_ids) - set(plan_ids))
        extra = sorted(set(plan_ids) - set(prior_active_ids))
        if missing:
            errors.append("prior revision plan omits active prior findings: " + ", ".join(missing))
        if extra:
            errors.append("prior revision plan includes non-active prior findings: " + ", ".join(extra))
        if not missing and not extra:
            errors.append("prior revision plan does not partition active prior findings exactly once")

    action_rows = actions.get("entries", [])
    action_by_id = {
        row.get("finding_id"): row
        for row in action_rows
        if isinstance(row, dict) and isinstance(row.get("finding_id"), str)
    }
    missing_actions = sorted(set(prior_active_ids) - set(action_by_id))
    unknown_actions = sorted(set(action_by_id) - set(all_prior_ids))
    if missing_actions:
        errors.append(
            "review actions omit active prior findings: " + ", ".join(missing_actions)
        )
    if unknown_actions:
        errors.append(
            "review actions reference unknown prior finding IDs: " + ", ".join(unknown_actions)
        )
    for row in plan_rows:
        if not isinstance(row, dict):
            continue
        finding_id = row.get("finding_id")
        action = action_by_id.get(finding_id)
        if action is None:
            continue
        expected_values = {
            "disposition": action.get("disposition"),
            "user_priority": action.get("user_priority"),
            "reviewed": action.get("reviewed"),
            "user_comment": normalized_note(action.get("response_note")),
        }
        for field, expected in expected_values.items():
            observed = normalized_note(row.get(field)) if field == "user_comment" else row.get(field)
            if observed != expected:
                errors.append(
                    f"revision plan row {finding_id} {field} differs from review actions"
                )

    records = reconciliation["records"]
    consolidation_rows = reconciliation["successor_consolidations"]
    record_ids = [row["prior_finding_id"] for row in records]
    if record_ids != plan_ids:
        errors.append(
            "round reconciliation records must appear exactly once in revision-plan row order"
        )

    current_rows = _active_rows(current_ledger)
    current_by_id = {row["id"]: row for row in current_rows}
    if len(current_by_id) != len(current_rows):
        errors.append("current active findings repeat IDs")
    current_ids = set(current_by_id)
    prior_all_id_set = set(all_prior_ids)
    successor_occurrences: Counter[str] = Counter()
    successor_owners: dict[str, list[str]] = {}

    cited_anchors: set[str] = set()
    cited_computations: set[str] = set()
    plan_by_id = {
        row["finding_id"]: row for row in plan_rows
        if isinstance(row, dict) and isinstance(row.get("finding_id"), str)
    }
    for record in records:
        finding_id = record["prior_finding_id"]
        outcome = record["outcome"]
        successors = record["successor_finding_ids"]
        disposition = plan_by_id.get(finding_id, {}).get("disposition")
        results = [check["result"] for check in record["checks"]]
        for check in record["checks"]:
            cited_anchors.update(check["anchor_ids"])
            cited_computations.update(check["computation_ids"])

        invalid_successors = sorted(set(successors) - current_ids)
        if invalid_successors:
            errors.append(
                f"reconciliation record {finding_id} references inactive or unknown successors: "
                + ", ".join(invalid_successors)
            )
        successor_occurrences.update(successors)
        for successor in successors:
            successor_owners.setdefault(successor, []).append(finding_id)

        if disposition in EXCLUSION_DISPOSITIONS:
            allowed_outcomes = EXCLUSION_OUTCOMES
        elif disposition == "deferred":
            allowed_outcomes = DEFERRED_OUTCOMES
        else:
            allowed_outcomes = NORMAL_OUTCOMES
        if outcome not in allowed_outcomes:
            errors.append(
                f"reconciliation outcome {outcome} is invalid for prior disposition {disposition} on {finding_id}"
            )

        if outcome in {"resolved", "user_excluded"}:
            if finding_id in current_ids:
                errors.append(f"{outcome} record {finding_id} cannot remain an active current finding")
            if any(result != "passed" for result in results):
                errors.append(f"{outcome} record {finding_id} requires all closure checks to pass")
        elif outcome == "partly_resolved":
            if successors != [finding_id]:
                errors.append(f"partly_resolved record {finding_id} must retain the same active ID")
            if "passed" not in results or not any(
                result in {"failed", "bounded"} for result in results
            ):
                errors.append(
                    f"partly_resolved record {finding_id} requires both successful and incomplete closure checks"
                )
        elif outcome == "unchanged":
            if successors != [finding_id]:
                errors.append(f"unchanged record {finding_id} must retain the same active ID")
            if "passed" in results or not any(
                result in {"failed", "bounded"} for result in results
            ):
                errors.append(
                    f"unchanged record {finding_id} requires failed or bounded closure checks and no passed check"
                )
        elif outcome == "superseded":
            if finding_id in successors:
                errors.append(f"superseded record {finding_id} cannot retain its prior ID")
            reused = sorted(set(successors) & prior_all_id_set)
            if reused:
                errors.append(
                    f"superseded record {finding_id} must map to new IDs, not prior IDs: "
                    + ", ".join(reused)
                )
            if finding_id in current_ids:
                errors.append(f"superseded record {finding_id} cannot remain active under its prior ID")
            if "passed" not in results:
                errors.append(
                    f"superseded record {finding_id} requires at least one passed reviewer check"
                )

    outcomes_by_id = {
        record["prior_finding_id"]: record["outcome"] for record in records
    }
    declared_consolidations: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(consolidation_rows):
        successor = row["successor_finding_id"]
        members = row["prior_finding_ids"]
        if successor in declared_consolidations:
            errors.append(
                f"successor_consolidations repeats current finding {successor}"
            )
            continue
        declared_consolidations[successor] = row
        if successor not in current_ids:
            errors.append(
                f"successor_consolidations[{index}] references inactive or unknown current finding {successor}"
            )
        unknown_members = sorted(set(members) - set(plan_ids))
        if unknown_members:
            errors.append(
                f"successor_consolidations[{index}] references unknown prior plan findings: "
                + ", ".join(unknown_members)
            )
        expected_order = [finding_id for finding_id in plan_ids if finding_id in set(members)]
        if members != expected_order:
            errors.append(
                f"successor_consolidations[{index}].prior_finding_ids must follow revision-plan row order"
            )
        owners = successor_owners.get(successor, [])
        if owners != members:
            errors.append(
                f"successor consolidation {successor} must list exactly the prior findings that cite it"
            )
        if len(owners) < 2:
            errors.append(
                f"successor consolidation {successor} must join at least two prior findings"
            )
        invalid_outcomes = [
            finding_id for finding_id in members
            if outcomes_by_id.get(finding_id) != "superseded"
        ]
        if invalid_outcomes:
            errors.append(
                f"successor consolidation {successor} may include only superseded prior findings: "
                + ", ".join(invalid_outcomes)
            )

    undeclared_repeated = sorted(
        value
        for value, count in successor_occurrences.items()
        if count > 1 and value not in declared_consolidations
    )
    if undeclared_repeated:
        errors.append(
            "current findings cited by more than one prior finding require an explicit successor consolidation: "
            + ", ".join(undeclared_repeated)
        )

    new_ids = reconciliation["new_finding_ids"]
    unknown_new = sorted(set(new_ids) - current_ids)
    if unknown_new:
        errors.append("new_finding_ids contains inactive or unknown IDs: " + ", ".join(unknown_new))
    reused_new = sorted(set(new_ids) & prior_all_id_set)
    if reused_new:
        errors.append("new_finding_ids must not reuse prior finding IDs: " + ", ".join(reused_new))
    overlap = sorted(set(new_ids) & set(successor_occurrences))
    if overlap:
        errors.append("current findings cannot be both successors and new: " + ", ".join(overlap))
    accounted = set(successor_occurrences) | set(new_ids)
    missing_current = sorted(current_ids - accounted)
    extra_accounted = sorted(accounted - current_ids)
    if missing_current:
        errors.append(
            "current active findings are absent from reconciliation: " + ", ".join(missing_current)
        )
    if extra_accounted:
        errors.append(
            "round reconciliation accounts for inactive current findings: "
            + ", ".join(extra_accounted)
        )

    if cited_anchors:
        manifest = _load_current_json(
            review_dir,
            "evidence/source-manifest.json",
            "current source manifest",
            errors,
        )
        anchor_rows = manifest.get("anchors", []) if isinstance(manifest, dict) else []
        known_anchors = {
            row.get("id")
            for row in (anchor_rows if isinstance(anchor_rows, list) else [])
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        unknown_anchors = sorted(cited_anchors - known_anchors)
        if unknown_anchors:
            errors.append("round reconciliation cites unknown current anchors: " + ", ".join(unknown_anchors))
    if cited_computations:
        computations = _load_current_json(
            review_dir,
            "evidence/computations.json",
            "current computations ledger",
            errors,
        )
        computation_rows = (
            computations.get("computations", []) if isinstance(computations, dict) else []
        )
        known_computations = {
            row.get("id")
            for row in (computation_rows if isinstance(computation_rows, list) else [])
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        unknown_computations = sorted(cited_computations - known_computations)
        if unknown_computations:
            errors.append(
                "round reconciliation cites unknown current computations: "
                + ", ".join(unknown_computations)
            )

    # Agent status is deliberately absent from every outcome rule above. The
    # response is identity-checked evidence about attempted work, never an
    # adjudication authority.
    if check_markdown:
        try:
            observed_markdown = safe_read_bytes(review_dir, RECONCILIATION_MD).decode("utf-8")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"cannot read evidence/round-reconciliation.md: {exc}")
        else:
            expected_markdown = render(
                reconciliation,
                prior_findings=prior_findings,
                current_findings=current_ledger,
                revision_tasks=tasks,
                agent_response=response,
            )
            if observed_markdown != expected_markdown:
                errors.append(
                    "evidence/round-reconciliation.md is not synchronized with round-reconciliation.json"
                )
    return errors


def write_markdown(review_dir: Path) -> list[str]:
    run = strict_json_load(review_dir / "run.json")
    ledger = strict_json_load(review_dir / "findings.json")
    if not isinstance(run, dict) or not isinstance(ledger, dict):
        return ["run.json and findings.json must contain objects"]
    errors = validate_round_reconciliation(
        review_dir,
        run,
        ledger,
        check_markdown=False,
    )
    if errors:
        return errors
    payload = strict_json_load(review_dir / RECONCILIATION_JSON)
    assert isinstance(payload, dict)
    activation = run["prior_round"]
    prior_findings = strict_json_load(
        review_dir / activation["prior_findings_path"]
    )
    revision_tasks = strict_json_load(
        review_dir / activation["revision_tasks_path"]
    )
    response_path = activation.get("agent_response_path")
    agent_response = (
        strict_json_load(review_dir / response_path) if response_path is not None else None
    )
    assert isinstance(prior_findings, dict) and isinstance(revision_tasks, dict)
    assert agent_response is None or isinstance(agent_response, dict)
    atomic_write_text(
        review_dir,
        RECONCILIATION_MD,
        render(
            payload,
            prior_findings=prior_findings,
            current_findings=ledger,
            revision_tasks=revision_tasks,
            agent_response=agent_response,
        ),
    )
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the deterministic Markdown view after JSON validation.",
    )
    args = parser.parse_args()
    try:
        if args.write:
            errors = write_markdown(args.review_dir)
        else:
            run = strict_json_load(args.review_dir / "run.json")
            ledger = strict_json_load(args.review_dir / "findings.json")
            if not isinstance(run, dict) or not isinstance(ledger, dict):
                errors = ["run.json and findings.json must contain objects"]
            else:
                errors = validate_round_reconciliation(args.review_dir, run, ledger)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors = [str(exc)]
    if errors:
        print("round reconciliation validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    action = "written and validated" if args.write else "validated"
    print(f"round reconciliation {action}: {args.review_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
