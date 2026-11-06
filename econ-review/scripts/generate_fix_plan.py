#!/usr/bin/env python3
"""Generate a dependency-aware P0/P1/P2 revision plan from findings.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import atomic_write_text, strict_json_load  # noqa: E402
from generate_reports import merge_repair  # noqa: E402


NAVIGATION_START = "<!-- review-navigation:start -->"
NAVIGATION_END = "<!-- review-navigation:end -->"

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}
DECISION_ROLE_ORDER = {
    "potentially_dispositive": 0,
    "posture_material": 1,
    "revision_value": 2,
    "polish": 3,
}


def reviewer_order_key(row: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        SEVERITY_ORDER.get(str(row.get("severity")), 99),
        DECISION_ROLE_ORDER.get(str(row.get("decision_role")), 99),
        row.get("importance_rank", 10**9),
        str(row.get("id") or ""),
    )


def load(path: Path) -> dict[str, Any]:
    value = strict_json_load(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def active_findings(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ledger.get("findings")
    if not isinstance(rows, list):
        raise ValueError("findings.json must contain a findings array")
    return [
        row for row in rows
        if isinstance(row, dict)
        and row.get("status") not in {"dismissed", "resolved"}
        and row.get("severity") in {"critical", "major", "minor", "info"}
    ]


def dependency_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row.get("id"): row for row in rows}
    if len(by_id) != len(rows) or None in by_id:
        raise ValueError("active findings must have unique nonempty IDs")
    for row in rows:
        finding_id = row.get("id")
        dependencies = row.get("fix", {}).get("dependencies", [])
        unknown = sorted(set(dependencies) - set(by_id))
        if unknown:
            raise ValueError(f"{finding_id} has unknown or inactive dependencies: {', '.join(unknown)}")
        if finding_id in dependencies:
            raise ValueError(f"{finding_id} cannot depend on itself")
        for dependency in dependencies:
            if SEVERITY_ORDER.get(str(by_id[dependency].get("severity")), 99) > SEVERITY_ORDER.get(str(row.get("severity")), 99):
                raise ValueError(
                    f"{finding_id} depends on lower-severity {dependency}; merge the shared root cause "
                    "or align the severities so the revision plan remains severity-first"
                )
    # Emit one item at a time: the most important item whose prerequisites are
    # already listed. Prerequisites still come first, but an unrelated minor
    # item no longer jumps ahead of a major one just because it has no
    # dependencies.
    pending = set(by_id)
    emitted: list[dict[str, Any]] = []
    while pending:
        ready = [
            by_id[finding_id] for finding_id in pending
            if not {
                dependency for dependency in by_id[finding_id].get("fix", {}).get("dependencies", [])
                if dependency in by_id
            } & pending
        ]
        if not ready:  # Preserve deterministic output while exposing a dependency cycle.
            cycle = ", ".join(sorted(pending))
            raise ValueError(f"finding dependency cycle: {cycle}")
        row = min(ready, key=reviewer_order_key)
        emitted.append(row)
        pending.remove(row.get("id"))
    return emitted


def report_channel(row: dict[str, Any]) -> str:
    return "writing" if row.get("report_channel", "substance") == "writing" else "substance"


def comment_labels(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Return the label each finding carries in the author-facing reports.

    The referee report numbers substance comments ``Comment 1..N`` and the
    editing document numbers its comments ``Editing comment 1..M``, each in
    importance order. The plan reuses those labels so that "Comment 8" means
    the same issue in every document.
    """
    labels: dict[str, str] = {}
    for channel, prefix in (("substance", "Comment"), ("writing", "Editing comment")):
        selected = sorted((row for row in rows if report_channel(row) == channel), key=reviewer_order_key)
        for index, row in enumerate(selected, start=1):
            labels[str(row.get("id"))] = f"{prefix} {index}"
    return labels


TIER_LABELS = {
    "top-general": "a top general-interest journal",
    "leading-field": "a leading field journal",
    "standard-field": "a field journal",
    "regional-specialized": "a regional or specialized journal",
}


def target_label(target: dict[str, Any]) -> str:
    """Name the target audience in prose, never as a raw schema value."""
    venue = str(target.get("venue") or "").strip()
    if venue:
        return venue
    return TIER_LABELS.get(str(target.get("tier") or ""), "the intended audience")


def bucket(row: dict[str, Any]) -> str:
    role = row.get("decision_role")
    if row.get("severity") == "critical":
        return "P0"
    if role == "potentially_dispositive":
        return "P0"
    if role == "posture_material":
        return "P1"
    if role == "revision_value":
        return "P1"
    if role == "polish":
        return "P2"
    if row.get("essential"):
        return "P0"
    if row.get("severity") in {"critical", "major"}:
        return "P1"
    return "P2"


def without_self_reference(value: Any, finding_id: str) -> str:
    """Keep a finding ID unique to its plan heading.

    Findings may carry their own ID in author-facing repair prose. Repeating it
    in the generated action, payoff, or completion text makes machine linking
    ambiguous and causes the plan to read like a database export. Dependency
    IDs remain untouched because they refer to different findings.
    """
    return re.sub(
        rf"\b{re.escape(finding_id)}\b",
        "this finding",
        str(value or ""),
        flags=re.IGNORECASE,
    )


def combined_action(fix: dict[str, Any], finding_id: str) -> str:
    """Keep strategic direction and implementation without repeating either."""
    what = re.sub(r"\s+", " ", str(fix.get("what") or "")).strip()
    how = re.sub(r"\s+", " ", str(fix.get("how") or "")).strip()
    if not what and not how:
        raise ValueError(f"{finding_id} fix.what or fix.how must state an author action")

    return merge_repair(what, how)


def reject_generic_plan_text(row: dict[str, Any]) -> None:
    """Fail closed when canonical plan fields still contain migration boilerplate."""
    finding_id = str(row.get("id") or "unknown finding")
    fix = row.get("fix")
    if not isinstance(fix, dict):
        raise ValueError(f"{finding_id} must contain a structured fix object")
    publishability = str(fix.get("publishability") or "").strip()
    resolved_when = str(fix.get("resolved_when") or "").strip()
    if re.match(r"^Closing .+ removes the submission risk", publishability, re.IGNORECASE):
        raise ValueError(
            f"{finding_id} fix.publishability uses migration boilerplate; "
            "replace it with the paper-specific benefit of resolving the issue"
        )
    if re.match(rf"^{re.escape(finding_id)} closes when\b", resolved_when, re.IGNORECASE):
        raise ValueError(
            f"{finding_id} fix.resolved_when uses migration boilerplate; "
            "replace it with observable completion evidence"
        )
    if re.match(
        r"^(?:The revised paper|The paper) (?:visibly )?implements (?:this|the) (?:repair|correction)\b",
        resolved_when,
        re.IGNORECASE,
    ):
        raise ValueError(
            f"{finding_id} fix.resolved_when uses generic completion boilerplate; "
            "name the observable paper-specific state that closes the finding"
        )


def review_navigation(review_dir: Path) -> str:
    """Return compact links among the author-facing review artifacts."""
    links = [
        "[Start here](README.md)",
        "[Referee report](report.md)",
    ]
    if (review_dir / "editing-comments.md").exists():
        links.append("[Editing comments](editing-comments.md)")
    links.append("[Revision plan](fix-plan.md)")
    return "\n".join([
        NAVIGATION_START,
        "> **Review files:** " + " · ".join(links),
        NAVIGATION_END,
    ])


def feasibility_text(fix: dict[str, Any]) -> str:
    """Explain feasibility in author language without manufacturing a task."""
    if fix.get("current_design_can_support_primary_fix") is True:
        return "The current design can support this repair."
    if fix.get("requires_new_data") is True:
        alternative = str(fix.get("claim_narrowing_alternative") or "").strip()
        if alternative:
            return "The primary repair needs new evidence. A current-paper alternative is: " + alternative
        return "The primary repair needs new evidence; otherwise narrow the affected claim."
    alternative = str(fix.get("claim_narrowing_alternative") or "").strip()
    if alternative:
        return "The primary repair is not supported by the current design. A bounded alternative is: " + alternative
    return "The primary repair is not supported by the current design; redesign or narrow the affected claim."


def render(review_dir: Path) -> str:
    run = load(review_dir / "run.json")
    rows = active_findings(load(review_dir / "findings.json"))
    for row in rows:
        if row.get("severity") == "critical" and not (
            row.get("decision_role") == "potentially_dispositive"
            and row.get("essential") is True
        ):
            raise ValueError(
                f"{row.get('id')} is critical and must be potentially_dispositive, "
                "essential, and P0 before submission"
            )
        reject_generic_plan_text(row)
    closures = [
        re.sub(r"\s+", " ", str(row.get("fix", {}).get("resolved_when", ""))).strip().lower()
        for row in rows
    ]
    repeated = [text for text, count in Counter(closures).items() if text and count > 1]
    if repeated:
        raise ValueError("resolved_when text must be paper-specific; duplicate closure detected")
    payoffs = [
        re.sub(r"\s+", " ", str(row.get("fix", {}).get("publishability", ""))).strip().lower()
        for row in rows
    ]
    repeated_payoffs = [text for text, count in Counter(payoffs).items() if text and count > 1]
    if repeated_payoffs:
        raise ValueError("publishability text must be finding-specific; duplicate payoff detected")

    target = run.get("target") if isinstance(run.get("target"), dict) else {}
    venue = target_label(target)
    lines = [
        "# Revision Plan",
        "",
        review_navigation(review_dir),
        "",
        f"Objective: improve the paper for {venue} by resolving the verified concerns below.",
        "",
        "## How to use this plan",
        "",
        "Work from P0 to P2. A later review confirms whether each revision resolves the concern by comparing it with the **Done when** condition.",
        "",
        (
            "Items keep the numbers they have in the referee report (**Comment N**) and the editing comments "
            "(**Editing comment N**), so each number names the same issue in every document."
            if any(report_channel(row) == "writing" for row in rows)
            else "Items keep the numbers they have in the referee report (**Comment N**), so each number names "
            "the same issue in both documents."
        )
        + " Within a priority level, prerequisites come first and the rest follow the report's order of importance.",
        "",
        "Unless an item says otherwise, the current design can support the stated repair. Items that need new evidence or claim narrowing say so explicitly.",
        "",
    ]
    labels = {
        "P0": "P0 — essential before submission",
        "P1": "P1 — substantive revision",
        "P2": "P2 — copyediting and optional polish",
    }
    ordered = dependency_order(rows)
    display_order = [
        row
        for priority in ("P0", "P1", "P2")
        for row in ordered
        if bucket(row) == priority
    ]
    labels_by_id = comment_labels(display_order)
    bucket_priority = {"P0": 0, "P1": 1, "P2": 2}
    by_id = {row.get("id"): row for row in rows}
    for row in rows:
        for dependency in row.get("fix", {}).get("dependencies", []):
            if bucket_priority[bucket(by_id[dependency])] > bucket_priority[bucket(row)]:
                raise ValueError(
                    f"{row.get('id')} depends on lower-priority {dependency}; promote the prerequisite or revise the dependency"
                )
    for key in ("P0", "P1", "P2"):
        selected = [row for row in ordered if bucket(row) == key]
        if not selected:
            continue
        lines.extend([f"## {labels[key]}", ""])
        for row in selected:
            fix = row.get("fix", {})
            dependencies = fix.get("dependencies") or []
            finding_id = str(row.get("id"))
            action = without_self_reference(combined_action(fix, finding_id), finding_id)
            payoff = without_self_reference(fix.get("publishability"), finding_id)
            closure = without_self_reference(fix.get("resolved_when"), finding_id)
            item_lines = [
                f"### {labels_by_id[finding_id]}: {row.get('title') or row.get('issue')}",
                f"<!-- finding_id: {finding_id} -->",
                "",
                f"- **Severity:** {row.get('severity')}",
                f"- [ ] **Action:** {action}",
                f"- **Payoff:** {payoff}",
                f"- **Done when:** {closure}",
            ]
            if fix.get("current_design_can_support_primary_fix") is not True:
                item_lines.append(f"- **Feasibility:** {feasibility_text(fix)}")
            item_lines.extend([
                f"- **Effort:** {fix.get('effort')}",
                "- **Dependencies:** "
                + (
                    "; ".join(
                        f"{labels_by_id[str(dependency)]}: "
                        f"{by_id[dependency].get('title') or by_id[dependency].get('issue')}"
                        for dependency in dependencies
                    )
                    if dependencies
                    else "None"
                ),
                "",
            ])
            lines.extend(item_lines)
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--check", action="store_true", help="Fail if the existing fix-plan.md differs")
    args = parser.parse_args()
    try:
        output = render(args.review_dir)
        destination = args.review_dir / "fix-plan.md"
        if args.check:
            if not destination.exists() or destination.read_text(encoding="utf-8") != output:
                raise ValueError(f"{destination} is not synchronized with findings.json")
        else:
            atomic_write_text(args.review_dir, "fix-plan.md", output)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        parser.exit(1, f"fix-plan generation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
