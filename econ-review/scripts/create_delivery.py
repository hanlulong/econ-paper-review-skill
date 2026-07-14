#!/usr/bin/env python3
"""Create a clean reader delivery folder from a finalized econ-review package."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import (  # noqa: E402
    atomic_write_bytes,
    atomic_write_text,
    is_link_or_junction,
    require_valid_pdf_bytes,
    strict_json_load,
)
from generate_pdf_report import build_professional_pdf, paper_identity  # noqa: E402
from latex_pdf_renderer import LatexRenderError  # noqa: E402
from validate_review import validate_review  # noqa: E402


PDF_NAME = "paper-review.pdf"
READER_FILES = {
    "report.md": "reports/referee-report.md",
    "editing-comments.md": "reports/editing-comments.md",
    "fix-plan.md": "reports/revision-plan.md",
    "evidence/round-reconciliation.md": "reports/round-progress.md",
}
DELIVERY_ROOT_NAMES = {"README.md", PDF_NAME, "reports", "supporting"}
DELIVERY_REPORT_NAMES = {Path(path).name for path in READER_FILES.values()}
OS_JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
NAVIGATION_BLOCK = re.compile(
    r"<!-- review-navigation:start -->.*?<!-- review-navigation:end -->",
    re.DOTALL,
)


def load_object(path: Path) -> dict[str, Any]:
    value = strict_json_load(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def reject_symlinks(root: Path) -> None:
    if is_link_or_junction(root) or not root.is_dir():
        raise ValueError("review directory must be a real directory")
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in names + files:
            if is_link_or_junction(base / name):
                raise ValueError(
                    "review packages may not contain links or junctions: "
                    + str((base / name).relative_to(root))
                )


def delivery_readme(review_dir: Path) -> str:
    run = load_object(review_dir / "run.json")
    findings = load_object(review_dir / "findings.json")
    synthesis = load_object(review_dir / "synthesis.json")
    rows = findings.get("findings") if isinstance(findings.get("findings"), list) else []
    active = [
        row for row in rows
        if isinstance(row, dict)
        and row.get("status") not in {"dismissed", "resolved"}
        and row.get("severity") in {"critical", "major", "minor", "info"}
    ]
    substance = sum(row.get("report_channel", "substance") == "substance" for row in active)
    writing = sum(row.get("report_channel", "substance") == "writing" for row in active)
    posture_key = str(synthesis.get("review_posture") or "not_assessed")
    posture = {
        "reject": "Reject",
        "weak_r_and_r": "Weak R&R",
        "strong_r_and_r": "Strong R&R",
        "accept": "Accept",
        "not_assessed": "Not assessed",
    }.get(posture_key, posture_key.replace("_", " ").title())
    mode = str(run.get("mode") or "review").title()
    paper_title, _, assessment_date = paper_identity(review_dir, run)
    writing_line = (
        "- [Editing comments](reports/editing-comments.md) - writing, terminology, mechanics, and presentation.\n"
        if (review_dir / "editing-comments.md").is_file()
        else ""
    )
    round_line = (
        "- [Round progress](reports/round-progress.md) - independent recheck of prior comments and new findings.\n"
        if (review_dir / "evidence" / "round-reconciliation.md").is_file()
        else ""
    )
    round_pdf_text = (
        ", prior-round progress"
        if (review_dir / "evidence" / "round-reconciliation.md").is_file()
        else ""
    )
    date_line = f"Assessment date: {assessment_date}\n\n" if assessment_date else ""
    return (
        f"# {paper_title}\n\n"
        f"**{mode} review. Recommendation: {posture}. "
        f"{substance} substantive {'comment' if substance == 1 else 'comments'}; "
        f"{writing} editing {'comment' if writing == 1 else 'comments'}.**\n\n"
        + date_line
        + "Start with [paper-review.pdf](paper-review.pdf). It combines the referee report, "
        + "editing comments, revision plan"
        + round_pdf_text
        + " in one professionally formatted document.\n\n"
        + "## Other reader files\n\n"
        + "- [Referee report](reports/referee-report.md) - overall assessment and exhaustive detailed comments.\n"
        + round_line
        + writing_line
        + "- [Revision plan](reports/revision-plan.md) - prioritized actions and completion evidence.\n\n"
        + "## Supporting material\n\n"
        + "The `supporting/` folder keeps the source evidence and working files needed for later review rounds. "
        + "You normally do not need to open or edit it. Select this whole delivery folder in Review Desk; "
        + "the viewer will find the review automatically.\n"
    )


def reader_markdown(source: str, *, include_writing: bool, include_round: bool) -> str:
    """Rewrite supporting-folder navigation for the renamed reader copies."""
    links = [
        "[Start here](../README.md)",
        "[Referee report](referee-report.md)",
    ]
    if include_writing:
        links.append("[Editing comments](editing-comments.md)")
    links.append("[Revision plan](revision-plan.md)")
    navigation = "> **Review files:** " + " · ".join(links)
    rewritten = NAVIGATION_BLOCK.sub(navigation, source)
    if include_round:
        rewritten = rewritten.replace(
            "(evidence/round-reconciliation.md)",
            "(round-progress.md)",
        )
    return rewritten


def copy_reader_files(review_dir: Path, delivery_dir: Path, pdf_bytes: bytes) -> None:
    atomic_write_bytes(delivery_dir, PDF_NAME, pdf_bytes)
    atomic_write_text(delivery_dir, "README.md", delivery_readme(review_dir))
    for source, destination in READER_FILES.items():
        source_path = review_dir / source
        if source_path.exists():
            if is_link_or_junction(source_path) or not source_path.is_file():
                raise ValueError(f"reader output is not a regular file: {source}")
            markdown = source_path.read_text(encoding="utf-8")
            if source in {"report.md", "editing-comments.md", "fix-plan.md"}:
                markdown = reader_markdown(
                    markdown,
                    include_writing=(review_dir / "editing-comments.md").is_file(),
                    include_round=(review_dir / "evidence" / "round-reconciliation.md").is_file(),
                )
            atomic_write_text(delivery_dir, destination, markdown)


def validate_in_place_destination(review_dir: Path, delivery_dir: Path) -> list[Path]:
    """Reject ambiguous parent contents before refreshing generated reader files."""
    junk: list[Path] = []
    for path in delivery_dir.iterdir():
        if path.name.casefold() in OS_JUNK_NAMES:
            if is_link_or_junction(path) or not path.is_file():
                raise ValueError(f"delivery OS metadata must be a regular file: {path.name}")
            junk.append(path)
    unexpected_root = sorted(
        path.name for path in delivery_dir.iterdir()
        if path.name not in DELIVERY_ROOT_NAMES and path.name.casefold() not in OS_JUNK_NAMES
    )
    if unexpected_root:
        raise ValueError(
            "reader delivery contains unexpected root entries; move them before rebuilding: "
            + ", ".join(unexpected_root)
        )
    for name in ("README.md", PDF_NAME):
        path = delivery_dir / name
        if path.exists() and (is_link_or_junction(path) or not path.is_file()):
            raise ValueError(f"delivery {name} must be a regular file")
    reports = delivery_dir / "reports"
    if reports.exists():
        if is_link_or_junction(reports) or not reports.is_dir():
            raise ValueError("delivery reports path must be a real directory")
        unexpected_reports = sorted(
            path.name for path in reports.iterdir()
            if path.name not in DELIVERY_REPORT_NAMES and path.name.casefold() not in OS_JUNK_NAMES
        )
        if unexpected_reports:
            raise ValueError(
                "reader delivery reports contains unexpected entries; move them before rebuilding: "
                + ", ".join(unexpected_reports)
            )
        for path in reports.iterdir():
            if path.name.casefold() in OS_JUNK_NAMES:
                if is_link_or_junction(path) or not path.is_file():
                    raise ValueError(f"delivery OS metadata must be a regular file: {path.name}")
                junk.append(path)
            elif is_link_or_junction(path) or not path.is_file():
                raise ValueError(f"delivery report must be a regular file: {path.name}")
    if review_dir != delivery_dir / "supporting":
        raise ValueError("in-place reader delivery must contain the canonical supporting directory")
    return junk


def create_delivery(
    review_dir: Path,
    delivery_dir: Path,
    *,
    replace: bool,
    assessment_date: date | None = None,
    prevalidated: bool = False,
) -> None:
    review_dir = review_dir.expanduser().absolute()
    delivery_dir = delivery_dir.expanduser().absolute()
    reject_symlinks(review_dir)
    review_dir = review_dir.resolve(strict=True)
    delivery_resolved = delivery_dir.resolve(strict=False)
    if not prevalidated:
        errors = validate_review(review_dir)
        if errors:
            raise ValueError("canonical review package is not valid:\n- " + "\n- ".join(errors))
    pdf_path = review_dir / PDF_NAME
    if pdf_path.exists():
        if is_link_or_junction(pdf_path) or not pdf_path.is_file():
            raise ValueError("canonical paper-review.pdf must be a regular file")
        pdf_bytes = pdf_path.read_bytes()
        require_valid_pdf_bytes(pdf_bytes, label="canonical paper-review.pdf")
    else:
        # Immutable review receipts created before PDF delivery must remain
        # byte-for-byte valid. Render their reader PDF into the delivery only;
        # never mutate the frozen canonical package or pretend to migrate it.
        pdf_bytes, _profile = build_professional_pdf(
            review_dir,
            delivery_dir / PDF_NAME,
            page_size="letter",
            font_dir=None,
            assessment_date=assessment_date,
        )

    in_place_support = (
        review_dir.name == "supporting"
        and review_dir.parent == delivery_resolved
    )
    if in_place_support:
        junk = validate_in_place_destination(review_dir, delivery_resolved)
        managed = [delivery_dir / "README.md", delivery_dir / PDF_NAME]
        managed.extend(delivery_dir / destination for destination in READER_FILES.values())
        previous = {
            path: path.read_bytes()
            for path in managed
            if path.is_file() and not is_link_or_junction(path)
        }
        junk_previous = {path: path.read_bytes() for path in junk}
        reports_existed = (delivery_dir / "reports").is_dir()
        delivery_dir.mkdir(parents=True, exist_ok=True)
        reports = delivery_dir / "reports"
        try:
            reports.mkdir(exist_ok=True)
            copy_reader_files(review_dir, delivery_dir, pdf_bytes)
            for source, destination in READER_FILES.items():
                destination_path = delivery_dir / destination
                if not (review_dir / source).exists() and destination_path.exists():
                    destination_path.unlink()
            for path in junk:
                path.unlink()
        except Exception as exc:
            try:
                for path in managed:
                    if path in previous:
                        atomic_write_bytes(path.parent, path.name, previous[path])
                    elif path.exists() and not is_link_or_junction(path) and path.is_file():
                        path.unlink()
                for path, value in junk_previous.items():
                    atomic_write_bytes(path.parent, path.name, value)
                if not reports_existed and reports.is_dir() and not any(reports.iterdir()):
                    reports.rmdir()
            except Exception as rollback_exc:
                raise ValueError(f"{exc}; reader delivery rollback failed: {rollback_exc}") from rollback_exc
            raise
        return

    try:
        delivery_resolved.relative_to(review_dir)
    except ValueError:
        pass
    else:
        raise ValueError("delivery directory must not be inside the canonical review directory")
    try:
        review_dir.relative_to(delivery_resolved)
    except ValueError:
        pass
    else:
        raise ValueError(
            "delivery directory must not contain the canonical review directory"
        )
    if delivery_dir.exists() and not replace:
        raise ValueError("delivery directory already exists; pass --replace to rebuild it")
    delivery_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="econ-review-delivery-", dir=delivery_dir.parent
    ) as temporary:
        staged = Path(temporary) / delivery_dir.name
        staged.mkdir()
        shutil.copytree(
            review_dir,
            staged / "supporting",
            ignore=shutil.ignore_patterns(
                ".DS_Store", "Thumbs.db", "desktop.ini", "__pycache__", "*.pyc"
            ),
        )
        copy_reader_files(review_dir, staged, pdf_bytes)
        previous = None
        if delivery_dir.exists():
            previous = delivery_dir.with_name(f".{delivery_dir.name}.backup-{os.getpid()}")
            if previous.exists():
                raise ValueError(f"temporary backup path already exists: {previous}")
            os.replace(delivery_dir, previous)
        try:
            os.replace(staged, delivery_dir)
        except Exception:
            if previous is not None and previous.exists() and not delivery_dir.exists():
                os.replace(previous, delivery_dir)
            raise
        if previous is not None and previous.exists():
            shutil.rmtree(previous)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path, help="Finalized canonical review package")
    parser.add_argument("delivery_dir", type=Path, help="Clean reader delivery directory")
    parser.add_argument("--replace", action="store_true", help="Atomically replace an existing delivery")
    parser.add_argument(
        "--assessment-date",
        type=date.fromisoformat,
        help="Verified review date for a legacy package that does not record one (YYYY-MM-DD)",
    )
    args = parser.parse_args()
    try:
        create_delivery(
            args.review_dir,
            args.delivery_dir,
            replace=args.replace,
            assessment_date=args.assessment_date,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, LatexRenderError, ValueError) as exc:
        parser.exit(1, f"delivery generation failed: {exc}\n")
    print(f"Reader delivery ready: {args.delivery_dir.expanduser().absolute()}")
    return 0


if __name__ == "__main__":
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
