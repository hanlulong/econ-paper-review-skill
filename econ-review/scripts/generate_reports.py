#!/usr/bin/env python3
"""Generate v0.3 referee and detailed-comment Markdown from canonical JSON state."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import atomic_write_text  # noqa: E402


POSTURE = {
    "reject": "Reject",
    "weak_r_and_r": "Weak R&R",
    "strong_r_and_r": "Strong R&R",
    "accept": "Accept",
    "not_assessed": "Not assessed",
}

NAVIGATION_START = "<!-- review-navigation:start -->"
NAVIGATION_END = "<!-- review-navigation:end -->"


def review_navigation(include_writing: bool) -> str:
    links = [
        "[Start here](README.md)",
        "[Referee report](report.md)",
    ]
    if include_writing:
        links.append("[Writing report](writing-report.md)")
    links.extend([
        "[Revision plan](fix-plan.md)",
        "[Audit trail](evidence/verification.md)",
    ])
    return "\n".join([
        NAVIGATION_START,
        "> **Review package:** " + " · ".join(links),
        NAVIGATION_END,
    ])


def without_navigation(markdown: str) -> str:
    """Remove an earlier generated navigation block before regenerating it."""
    pattern = re.compile(
        rf"\n?{re.escape(NAVIGATION_START)}.*?{re.escape(NAVIGATION_END)}\n?",
        re.DOTALL,
    )
    return pattern.sub("\n\n", markdown, count=1).strip()


def add_navigation(markdown: str, include_writing: bool) -> str:
    """Place navigation directly below the document title."""
    clean = without_navigation(markdown)
    title, separator, body = clean.partition("\n")
    if not separator:
        raise ValueError("author-facing Markdown must contain a title and body")
    return f"{title}\n\n{review_navigation(include_writing)}\n\n{body.lstrip()}"


def markdown_anchor(index: int, title: str) -> str:
    slug = "".join(character.lower() for character in title if character.isalnum() or character in " -_")
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return f"{index}-{slug}"


def humanize(value: Any) -> str:
    return str(value or "not assessed").replace("_", " ")


def counted(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def manifest_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "document"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def required_text(mapping: dict[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def optional_text(mapping: dict[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{context}.{key} must be a string or null")
    return value.strip()


def string_list(mapping: dict[str, Any], key: str, context: str) -> list[str]:
    value = mapping.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{context}.{key} must be an array")
    output: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{context}.{key}[{index}] must be a non-empty string")
        output.append(item.strip())
    return output


def finding_rows(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    value = ledger.get("findings")
    if not isinstance(value, list):
        raise ValueError("findings.json.findings must be an array")
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise ValueError(f"findings.json.findings[{index}] must be an object")
        rows.append(row)
    return rows


def finding_context(row: dict[str, Any]) -> str:
    finding_id = row.get("id")
    return f"finding {finding_id}" if isinstance(finding_id, str) and finding_id else "finding <unknown>"


def clean_join(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if text and text not in parts:
            parts.append(text)
    return " ".join(parts)


def display_evidence(row: dict[str, Any]) -> dict[str, Any]:
    context = finding_context(row)
    evidence_rows = row.get("evidence")
    if not isinstance(evidence_rows, list) or not evidence_rows:
        raise ValueError(f"{context}.evidence must contain at least one evidence object")
    for index, evidence in enumerate(evidence_rows):
        if not isinstance(evidence, dict):
            raise ValueError(f"{context}.evidence[{index}] must be an evidence object")
    display_id = row.get("display_evidence_id")
    if isinstance(display_id, str):
        for evidence in evidence_rows:
            if isinstance(evidence, dict) and evidence.get("id") == display_id:
                return evidence
        raise ValueError(f"{context}.display_evidence_id does not reference its evidence")
    if isinstance(evidence_rows[0], dict):
        return evidence_rows[0]
    raise ValueError(f"{context}.evidence[0] must be an object")


def evidence_text(row: dict[str, Any]) -> str:
    context = finding_context(row)
    evidence_rows = [display_evidence(row)]
    for index, evidence in enumerate(evidence_rows):
        if not isinstance(evidence, dict):
            raise ValueError(f"{context}.evidence[{index}] must be an object")
        if isinstance(evidence.get("content"), str):
            value = evidence["content"].strip()
            if value:
                return value
        if (
            evidence.get("type") == "absence_scope"
            and isinstance(evidence.get("scope_checked"), str)
            and evidence.get("scope_checked", "").strip()
        ):
            return "No responsive material was found in the checked scope: " + evidence["scope_checked"].strip()
    raise ValueError(f"{context}.evidence has no displayable content or checked absence scope")


def quote(value: str) -> str:
    return "\n".join("> " + line if line else ">" for line in value.splitlines())


def heading_location(value: str) -> str:
    """Keep the comment-title colon unique and easy to scan.

    Evidence locators often contain their own colon (for example,
    ``Section 3.4: sample exclusions``).  Rendering that value immediately
    before the title delimiter produces a visually noisy triple-part heading.
    Preserve the locator wording while using an em dash inside it, leaving the
    requested ``location: comment title`` structure unambiguous.
    """
    normalized = " ".join(value.split()).strip(" :")
    if re.fullmatch(r"\d+(?:\.\d+)*", normalized):
        normalized = f"Section {normalized}"
    return re.sub(r"\s*:\s*", " — ", normalized)


def constructive_feedback(row: dict[str, Any]) -> str:
    """Render one author-facing recommendation from the structured repair fields.

    ``fix.what`` and ``fix.how`` remain separate in the canonical ledger because
    the fix plan and resolution checks need their distinct meanings.  Reports
    should not make authors read the same recommendation twice, however, so the
    two values are combined here and obvious overlap is removed.
    """
    fix = row.get("fix")
    context = finding_context(row)
    if not isinstance(fix, dict):
        raise ValueError(f"{context} must contain a structured fix object at .fix")
    what = optional_text(row, "minimum_repair", context) or optional_text(fix, "what", f"{context}.fix")
    how = optional_text(fix, "how", f"{context}.fix")
    if not what and not how:
        raise ValueError(f"{context}.fix must provide what or how for Suggestions")

    def normalized(value: str) -> str:
        return "".join(character.lower() for character in value if character.isalnum())

    if not what:
        return how
    if not how:
        return what
    what_key, how_key = normalized(what), normalized(how)
    if what_key == how_key or how_key in what_key:
        return what
    if what_key in how_key:
        return how
    return clean_join(what, how)


def detail_block(number: int, row: dict[str, Any]) -> str:
    context = finding_context(row)
    finding_id = required_text(row, "id", context)
    issue = required_text(row, "issue", context)
    displayed = display_evidence(row)
    locator = displayed.get("locator")
    if not isinstance(locator, dict):
        raise ValueError(f"{context}.evidence[0].locator must be an object")
    location = locator.get("section") or locator.get("exhibit") or locator.get("file") or "Manuscript"
    if not isinstance(location, str):
        raise ValueError(f"{context}.evidence[0].locator values must be strings")
    title = optional_text(row, "title", context) or issue
    concern = clean_join(
        optional_text(row, "why_it_matters", context),
        optional_text(row, "reader_effect", context),
        optional_text(row, "evidence_boundary", context),
    )
    if not concern:
        raise ValueError(f"{context} must provide why_it_matters or reader_effect")
    lines = [
        f"### {number}. {heading_location(location)}: {title}",
        f"<!-- finding_id: {finding_id} -->",
        "",
        f"**Issue**: {issue}",
        "",
        "**Relevant text**:",
        quote(evidence_text(row)),
        "",
        f"**Concern**: {concern}",
        "",
        f"**Suggestions**: {constructive_feedback(row)}",
    ]
    lines.extend(["", "**Status**: [Pending]"])
    return "\n".join(lines)


def active_rows(ledger: dict[str, Any], channel: str) -> list[dict[str, Any]]:
    rows = [
        row for row in finding_rows(ledger)
        if row.get("status") not in {"dismissed", "resolved"}
        and row.get("severity") in {"critical", "major", "minor"}
        and row.get("report_channel", "substance") == channel
    ]
    return sorted(rows, key=lambda row: row.get("importance_rank", 10**9))


def canonical_manifest(
    review_dir: Path,
    ledger: dict[str, Any],
    include_writing: bool,
) -> dict[str, Any]:
    """Build the standard v0.3 viewer index while preserving declared extras.

    The manifest lists only author-facing review documents. Manuscripts are
    intentionally never discovered by a directory-wide scan. An existing
    manifest may declare additional Markdown documents; safe, existing extras
    are retained so the framework remains extensible.
    """
    review_id = required_text(ledger, "review_id", "findings.json")
    documents: list[dict[str, Any]] = [
        {"id": "start-here", "title": "Start here", "group": "overview", "path": "README.md", "order": 0},
        {"id": "referee-report", "title": "Referee report", "group": "overview", "path": "report.md", "order": 10},
    ]
    if include_writing:
        documents.append({
            "id": "writing-report",
            "title": "Writing report",
            "group": "reports",
            "path": "writing-report.md",
            "order": 10,
        })
    documents.append({
        "id": "revision-plan",
        "title": "Revision plan",
        "group": "plan",
        "path": "fix-plan.md",
        "order": 10,
    })

    evidence_metadata = {
        "reconstruction.md": ("paper-reconstruction", "Paper reconstruction", 10),
        "reader-claim-audit.md": ("reader-claim-audit", "Reader and claim audit", 20),
        "analytical-audit.md": ("analytical-audit", "Analytical audit", 30),
        "figures.md": ("figure-audit", "Figure audit", 40),
        "tables.md": ("table-audit", "Table audit", 50),
        "writing.md": ("writing-audit", "Writing audit", 60),
        "coverage.md": ("coverage-audit", "Coverage audit", 70),
        "sources.md": ("source-verification", "Source verification", 80),
        "verification.md": ("package-verification", "Package verification", 90),
    }
    for index, path in enumerate(sorted((review_dir / "evidence").glob("*.md"))):
        identifier, title, order = evidence_metadata.get(
            path.name,
            (f"evidence-{manifest_slug(path.stem)}", path.stem.replace("-", " ").title(), 100 + index),
        )
        documents.append({
            "id": identifier,
            "title": title,
            "group": "audit",
            "path": path.relative_to(review_dir).as_posix(),
            "order": order,
        })

    canonical_paths = {row["path"] for row in documents} | {"writing-report.md"}
    manifest_path = review_dir / "review-manifest.json"
    if manifest_path.exists():
        existing = load(manifest_path)
        rows = existing.get("documents")
        if not isinstance(rows, list):
            raise ValueError("review-manifest.json.documents must be an array")
        for index, row in enumerate(rows):
            context = f"review-manifest.json.documents[{index}]"
            if not isinstance(row, dict):
                raise ValueError(f"{context} must be an object")
            path = required_text(row, "path", context)
            relative = Path(path)
            if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".md":
                raise ValueError(f"{context}.path must be a safe package-relative Markdown path")
            if path in canonical_paths:
                continue
            if not (review_dir / relative).is_file():
                raise ValueError(f"{context}.path does not exist: {path}")
            order = row.get("order")
            if not isinstance(order, int) or isinstance(order, bool):
                raise ValueError(f"{context}.order must be an integer")
            documents.append({
                "id": required_text(row, "id", context),
                "title": required_text(row, "title", context),
                "group": required_text(row, "group", context),
                "path": path,
                "order": order,
            })

    group_order = {"overview": 0, "reports": 1, "plan": 2, "audit": 3}
    documents.sort(key=lambda row: (
        group_order.get(row["group"], 9), row["order"], row["title"].lower(), row["path"]
    ))
    ids = [row["id"] for row in documents]
    paths = [row["path"] for row in documents]
    if len(ids) != len(set(ids)):
        raise ValueError("review-manifest.json would contain duplicate document IDs")
    if len(paths) != len(set(paths)):
        raise ValueError("review-manifest.json would contain duplicate document paths")
    return {"schema_version": "0.1", "review_id": review_id, "documents": documents}


def author_documents(review_dir: Path, include_writing: bool) -> list[tuple[str, str, str]]:
    """Return stable, human-readable package documents for the landing page."""
    documents: dict[str, tuple[str, str, str, int]] = {
        "README.md": ("Start here", "Overview", "README.md", 0),
        "report.md": ("Referee report", "Overview", "report.md", 10),
        "fix-plan.md": ("Revision plan", "Plan", "fix-plan.md", 10),
    }
    if include_writing:
        documents["writing-report.md"] = (
            "Writing report",
            "Reports",
            "writing-report.md",
            10,
        )
    manifest_path = review_dir / "review-manifest.json"
    if manifest_path.exists():
        manifest = load(manifest_path)
        rows = manifest.get("documents")
        if not isinstance(rows, list):
            raise ValueError("review-manifest.json.documents must be an array")
        for index, row in enumerate(rows):
            context = f"review-manifest.json.documents[{index}]"
            if not isinstance(row, dict):
                raise ValueError(f"{context} must be an object")
            path = required_text(row, "path", context)
            if Path(path).is_absolute() or ".." in Path(path).parts or not path.endswith(".md"):
                raise ValueError(f"{context}.path must be a safe package-relative Markdown path")
            if path == "writing-report.md" and not include_writing:
                continue
            title = required_text(row, "title", context)
            group = required_text(row, "group", context).title()
            order = row.get("order")
            if not isinstance(order, int) or isinstance(order, bool):
                raise ValueError(f"{context}.order must be an integer")
            documents[path] = (title, group, path, order)
    else:
        for path in sorted((review_dir / "evidence").glob("*.md")):
            relative = path.relative_to(review_dir).as_posix()
            title = path.stem.replace("-", " ").title()
            documents[relative] = (title, "Audit", relative, 100)

    group_order = {"Overview": 0, "Reports": 1, "Plan": 2, "Audit": 3}
    rows = [
        row for row in documents.values()
        if row[2] in {"README.md", "report.md"}
        or (row[2] == "writing-report.md" and include_writing)
        or (review_dir / row[2]).exists()
        or row[2] == "fix-plan.md"
    ]
    rows.sort(key=lambda row: (group_order.get(row[1], 9), row[3], row[0].lower(), row[2]))
    return [(title, group, path) for title, group, path, _ in rows]


def source_coverage(run: dict[str, Any]) -> str:
    boundary = run.get("assessment_boundary")
    if not isinstance(boundary, dict):
        raise ValueError("run.json.assessment_boundary must be an object")
    sources = boundary.get("sources")
    if not isinstance(sources, list):
        raise ValueError("run.json.assessment_boundary.sources must be an array")
    counts: dict[str, int] = {}
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"run.json.assessment_boundary.sources[{index}] must be an object")
        status = required_text(source, "status", f"run.json.assessment_boundary.sources[{index}]")
        counts[status] = counts.get(status, 0) + 1
    if not counts:
        return "no source files were recorded"
    return ", ".join(f"{count} {humanize(status)}" for status, count in sorted(counts.items()))


def render_landing_page(
    review_dir: Path,
    ledger: dict[str, Any],
    synthesis: dict[str, Any],
    run: dict[str, Any],
    include_writing: bool,
) -> str:
    """Create the deterministic author entry point for a v0.3 package."""
    posture_key = required_text(synthesis, "review_posture", "synthesis.json")
    if posture_key not in POSTURE:
        raise ValueError(f"synthesis.json.review_posture has unsupported value {posture_key!r}")
    concerns = synthesis.get("principal_concerns")
    if not isinstance(concerns, list):
        raise ValueError("synthesis.json.principal_concerns must be an array")
    substance = active_rows(ledger, "substance")
    writing = active_rows(ledger, "writing") if include_writing else []
    boundary = run.get("assessment_boundary")
    if not isinstance(boundary, dict):
        raise ValueError("run.json.assessment_boundary must be an object")
    capabilities = run.get("capabilities")
    if not isinstance(capabilities, dict):
        raise ValueError("run.json.capabilities must be an object")

    lines = [
        "# Start here: paper review",
        "",
        f"**Recommendation:** {POSTURE[posture_key]}",
        "",
        "The Markdown reports and revision plan contain the full review; the local Review Desk is optional.",
        "",
        f"**Inventory:** {counted(len(substance), 'substantive comment')}, {counted(len(writing), 'writing comment')}, and {counted(len(concerns), 'principal publication concern')}.",
        "",
        "## Recommended reading order",
        "",
        "1. Read the [referee report](report.md) for the overall assessment and publication risks.",
        "2. Work through the [revision plan](fix-plan.md) from P0 to P2.",
    ]
    if include_writing:
        lines.append("3. Use the [writing report](writing-report.md) for structure, terminology, mechanics, figures, and style.")
    lines.extend(["", "## Highest-priority concerns", ""])
    if not concerns:
        lines.append("No verified issue currently meets the principal-concern threshold.")
    for index, concern in enumerate(concerns, start=1):
        context = f"synthesis.json.principal_concerns[{index - 1}]"
        if not isinstance(concern, dict):
            raise ValueError(f"{context} must be an object")
        title = required_text(concern, "title", context)
        required_text(concern, "rationale", context)
        finding_ids = string_list(concern, "finding_ids", context)
        repairability = humanize(required_text(concern, "repairability", context))
        linked = ", ".join(f"`{finding_id}`" for finding_id in finding_ids)
        lines.append(
            f"{index}. [{title}](report.md#{markdown_anchor(index, title)}) — linked comments: {linked}; repairability: {repairability}."
        )
    other_major = synthesis.get("other_major_finding_ids")
    if not isinstance(other_major, list):
        raise ValueError("synthesis.json.other_major_finding_ids must be an array")
    if other_major:
        lines.extend([
            "",
            f"The referee report also identifies {len(other_major)} other posture-material issue{'s' if len(other_major) != 1 else ''}.",
        ])

    figures = required_text(boundary, "figures", "run.json.assessment_boundary")
    equations = required_text(boundary, "equations", "run.json.assessment_boundary")
    appendix = required_text(boundary, "appendix", "run.json.assessment_boundary")
    notes = optional_text(boundary, "notes", "run.json.assessment_boundary") or "No additional boundary note was recorded."
    literature = "available" if capabilities.get("live_literature_search") is True else "not available"
    replication = humanize(capabilities.get("replication_code"))
    lines.extend([
        "",
        "## Review coverage at a glance",
        "",
        f"- **Materials:** {source_coverage(run)}; appendix {humanize(appendix)}.",
        f"- **Rendered/formal evidence:** figures {humanize(figures)}; equations {humanize(equations)}.",
        f"- **External checks and limits:** live literature search {literature}; replication code {replication}. {notes}",
        "",
        "## Files in this package",
        "",
        "| Purpose | File |",
        "|---|---|",
    ])
    for title, group, path in author_documents(review_dir, include_writing):
        safe_title = title.replace("|", "\\|")
        lines.append(f"| {group}: {safe_title} | [{path}]({path}) |")
    lines.extend([
        "",
        "The JSON files are canonical machine-readable state for validation and later review rounds; authors normally work from the Markdown files above.",
        "",
        "## Carry work into the next round",
        "",
        "Ticking a revision-plan box records author progress; it does not close the finding, so report comments remain **Pending** until rechecked. In the optional Review Desk, **Ready for recheck** requests another review, **Challenged** requests reconsideration, and **Deferred** keeps the issue open. Notes are optional. Export `review-actions.json` to carry these actions into the next round.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def render_report(
    ledger: dict[str, Any],
    synthesis: dict[str, Any],
    include_writing: bool = True,
) -> str:
    all_rows = finding_rows(ledger)
    by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(all_rows):
        finding_id = required_text(row, "id", f"findings.json.findings[{index}]")
        if finding_id in by_id:
            raise ValueError(f"findings.json contains duplicate finding id {finding_id}")
        by_id[finding_id] = row
    substance = active_rows(ledger, "substance")
    overall_assessment = required_text(synthesis, "overall_assessment", "synthesis.json")
    posture_key = required_text(synthesis, "review_posture", "synthesis.json")
    if posture_key not in POSTURE:
        raise ValueError(f"synthesis.json.review_posture has unsupported value {posture_key!r}")
    posture_rationale = required_text(synthesis, "posture_rationale", "synthesis.json")
    convincingness = required_text(synthesis, "convincingness", "synthesis.json")
    strengths = string_list(synthesis, "strengths", "synthesis.json")
    upgrade_conditions = string_list(synthesis, "upgrade_conditions", "synthesis.json")
    lines = [
        "# Referee Report",
        "",
        review_navigation(include_writing),
        "",
        "## Overall assessment",
        "",
        overall_assessment,
    ]
    if strengths:
        lines.extend(["", "The main strengths worth preserving are:", ""])
        lines.extend(f"- {value}" for value in strengths)
    lines.extend([
        "",
        "## Recommendation and main grounds",
        "",
        f"**Recommendation**: {POSTURE[posture_key]}",
        "",
        posture_rationale,
    ])
    if upgrade_conditions:
        lines.extend(["", "The assessment would improve if the revision:", ""])
        lines.extend(f"- {value}" for value in upgrade_conditions)
    lines.extend(["", "## Issues that could prevent publication", ""])
    concerns = synthesis.get("principal_concerns")
    if not isinstance(concerns, list):
        raise ValueError("synthesis.json.principal_concerns must be an array")
    if not concerns:
        lines.extend(["No verified issue currently meets the threshold for a principal publication concern.", ""])
    for index, concern in enumerate(concerns, start=1):
        context = f"synthesis.json.principal_concerns[{index - 1}]"
        if not isinstance(concern, dict):
            raise ValueError(f"{context} must be an object")
        concern_id = required_text(concern, "id", context)
        concern_title = required_text(concern, "title", context)
        rationale = required_text(concern, "rationale", context)
        finding_ids = string_list(concern, "finding_ids", context)
        for finding_id in finding_ids:
            if finding_id not in by_id:
                raise ValueError(f"{context}.finding_ids references unknown finding {finding_id}")
        linked = ", ".join(f"`{finding_id}`" for finding_id in finding_ids)
        repairability = required_text(concern, "repairability", context)
        upgrade_condition = required_text(concern, "upgrade_condition", context)
        lines.extend([
            f"### {index}. {concern_title}",
            f"<!-- principal_concern_id: {concern_id} -->",
            "",
            rationale,
            "",
            f"Linked findings: {linked}. Repairability: {repairability.replace('_', ' ')}.",
            "",
            f"What would change the assessment: {upgrade_condition}",
            "",
        ])
    lines.extend(["## Other major issues", ""])
    other_ids = string_list(synthesis, "other_major_finding_ids", "synthesis.json")
    if other_ids:
        for finding_id in other_ids:
            row = by_id.get(finding_id)
            if row is None:
                raise ValueError(f"synthesis.json.other_major_finding_ids references unknown finding {finding_id}")
            context = finding_context(row)
            title = optional_text(row, "title", context) or required_text(row, "issue", context)
            why_it_matters = required_text(row, "why_it_matters", context)
            lines.append(f"- **{title}** (`{finding_id}`): {why_it_matters}")
    else:
        lines.append("No other major substantive issues were identified.")
    lines.extend([
        "",
        "## Is the argument convincing?",
        "",
        convincingness,
        "",
        f"## Detailed Comments ({len(substance)})",
        "",
    ])
    lines.append("\n\n".join(detail_block(index, row) for index, row in enumerate(substance, start=1)))
    return "\n".join(lines).rstrip() + "\n"


def render_writing_report(review_dir: Path, ledger: dict[str, Any]) -> str:
    destination = review_dir / "writing-report.md"
    if not destination.exists():
        raise ValueError("writing-report.md preamble is required before deterministic detail generation")
    existing = destination.read_text(encoding="utf-8")
    marker = "## Detailed Writing Comments"
    preamble = existing.split(marker, 1)[0].rstrip()
    # New writing reports exclude routine bibliography and citation-accuracy
    # checking. Strip either legacy reference section when normalizing a current
    # package, while leaving archived packages untouched unless regenerated.
    for heading in (
        "## References and citation integrity",
        "## Reference accuracy and citation support",
    ):
        preamble = re.sub(
            rf"^{re.escape(heading)}\s*$[\s\S]*?(?=^## |\Z)",
            "",
            preamble,
            flags=re.MULTILINE,
        ).rstrip()
    preamble = re.sub(r"^# Writing and reference report\s*$", "# Writing report", preamble, flags=re.MULTILINE)
    preamble = add_navigation(preamble, include_writing=True)
    writing = active_rows(ledger, "writing")
    details = "\n\n".join(detail_block(index, row) for index, row in enumerate(writing, start=1))
    return f"{preamble}\n\n## Detailed Writing Comments ({len(writing)})\n\n{details}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        ledger = load(args.review_dir / "findings.json")
        synthesis = load(args.review_dir / "synthesis.json")
        run = load(args.review_dir / "run.json")
        contract = ledger.get("schema_version")
        if contract not in {"0.3", "0.4"} or synthesis.get("review_contract_version") not in {"0.3", "0.4"}:
            raise ValueError("generate_reports.py requires the v0.3 or v0.4 contract")
        writing_rows = active_rows(ledger, "writing")
        writing_path = args.review_dir / "writing-report.md"
        include_writing = bool(run.get("mode") == "full" or writing_rows or writing_path.exists())
        manifest_path = args.review_dir / "review-manifest.json"
        manifest_output = json.dumps(
            canonical_manifest(args.review_dir, ledger, include_writing),
            indent=2,
            ensure_ascii=False,
        ) + "\n"
        if args.check:
            if not manifest_path.exists() or manifest_path.read_text(encoding="utf-8") != manifest_output:
                raise ValueError(f"{manifest_path} is not synchronized with the v0.3 document set")
        else:
            atomic_write_text(args.review_dir, "review-manifest.json", manifest_output)
        outputs = {
            args.review_dir / "report.md": render_report(ledger, synthesis, include_writing),
            args.review_dir / "README.md": render_landing_page(
                args.review_dir,
                ledger,
                synthesis,
                run,
                include_writing,
            ),
        }
        if include_writing:
            outputs[writing_path] = render_writing_report(args.review_dir, ledger)
        for destination, output in outputs.items():
            if args.check:
                if not destination.exists() or destination.read_text(encoding="utf-8") != output:
                    raise ValueError(f"{destination} is not synchronized with canonical JSON state")
            else:
                atomic_write_text(args.review_dir, destination.relative_to(args.review_dir), output)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, IndexError, ValueError) as exc:
        parser.exit(1, f"report generation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
