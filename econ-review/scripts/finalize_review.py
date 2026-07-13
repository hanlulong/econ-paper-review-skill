#!/usr/bin/env python3
"""Finalize or check an econ-review v0.4 package as one fail-closed transaction."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import atomic_write_bytes, atomic_write_json, atomic_write_text, safe_read_bytes, sha256_bytes  # noqa: E402
from trust_spine import pdf_sources, validate_pdf_ingestions  # noqa: E402
from validate_review import validate_review  # noqa: E402


SCRIPT_DIR = Path(__file__).resolve().parent
GENERATORS = (
    SCRIPT_DIR / "generate_verification.py",
    SCRIPT_DIR / "generate_reports.py",
    SCRIPT_DIR / "generate_fix_plan.py",
)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def reject_symlinks(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("review directory must be a real directory")
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in names + files:
            path = base / name
            if path.is_symlink():
                raise ValueError(f"review packages may not contain symbolic links: {path.relative_to(root)}")


def run_generators(review_dir: Path, *, check: bool) -> None:
    for script in GENERATORS:
        command = [sys.executable, str(script), str(review_dir)]
        if check:
            command.append("--check")
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise ValueError(f"{script.name} failed: {detail}")


def artifact_hashes(review_dir: Path) -> dict[str, str]:
    excluded = {"finalization.json", "review-actions.json", ".DS_Store"}
    artifacts: dict[str, str] = {}
    for path in sorted(review_dir.rglob("*")):
        if not path.is_file() or path.name in excluded:
            continue
        relative = path.relative_to(review_dir).as_posix()
        artifacts[relative] = sha256_bytes(safe_read_bytes(review_dir, relative))
    return artifacts


def receipt(review_dir: Path, run: dict[str, Any]) -> dict[str, Any]:
    gates = [
        "source_integrity",
        "structured_verification",
        "report_generation",
        "fix_plan_generation",
        "contract_validation",
    ]
    source_manifest = load_object(review_dir / "evidence" / "source-manifest.json")
    if pdf_sources(source_manifest):
        gates.insert(1, "source_ingestion")
    return {
        "schema_version": "0.1",
        "review_id": run["review_id"],
        "contract_version": "0.4",
        "artifacts": artifact_hashes(review_dir),
        "gates": gates,
    }


def readiness_errors(review_dir: Path, run: dict[str, Any], ledger: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if run.get("schema_version") != "0.4" or ledger.get("schema_version") != "0.4":
        errors.append("finalization requires matching v0.4 run and findings contracts")
    if run.get("verification_passed") is not True:
        errors.append("run.json.verification_passed must be true before finalization")
    stages = run.get("stage_status", {})
    if not isinstance(stages, dict) or any(value not in {"passed", "bounded", "not_applicable"} for value in stages.values()):
        errors.append("all workflow stages must be passed, bounded, or not applicable")
    for finding in ledger.get("findings", []):
        if not isinstance(finding, dict) or finding.get("status") in {"dismissed", "resolved"}:
            continue
        if finding.get("severity") in {"critical", "major", "minor"} and finding.get("verification") != "passed":
            errors.append(f"finding {finding.get('id')} has not passed verification")
    try:
        source_manifest = load_object(review_dir / "evidence" / "source-manifest.json")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot validate source ingestion readiness: {exc}")
    else:
        errors.extend(
            validate_pdf_ingestions(
                review_dir,
                source_manifest,
                run.get("review_id"),
                require_ready=True,
            )
        )
    return errors


def check(review_dir: Path) -> list[str]:
    try:
        reject_symlinks(review_dir)
        run_generators(review_dir, check=True)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return [str(exc)]
    return validate_review(review_dir)


def finalize(review_dir: Path) -> None:
    review_dir = review_dir.resolve(strict=True)
    reject_symlinks(review_dir)
    run = load_object(review_dir / "run.json")
    ledger = load_object(review_dir / "findings.json")
    if errors := readiness_errors(review_dir, run, ledger):
        raise ValueError("; ".join(errors))
    with tempfile.TemporaryDirectory(prefix="econ-review-finalize-") as temporary:
        staged = Path(temporary) / "review"
        shutil.copytree(review_dir, staged)
        staged_run = load_object(staged / "run.json")
        staged_run["status"] = "complete"
        atomic_write_json(staged, "run.json", staged_run)
        finalization_path = staged / "finalization.json"
        if finalization_path.exists():
            finalization_path.unlink()
        run_generators(staged, check=False)
        run_generators(staged, check=True)
        atomic_write_json(staged, "finalization.json", receipt(staged, staged_run))
        errors = validate_review(staged)
        if errors:
            raise ValueError("staged package failed validation:\n- " + "\n- ".join(errors))

        # The receipt is the commit marker and is deliberately written last.
        commit_paths = [
            "run.json", "review-manifest.json", "README.md", "report.md", "fix-plan.md",
            "evidence/verification.md",
        ]
        if (staged / "writing-report.md").exists():
            commit_paths.append("writing-report.md")
        rollback_paths = commit_paths + ["finalization.json"]
        previous = {
            relative: safe_read_bytes(review_dir, relative)
            for relative in rollback_paths
            if (review_dir / relative).exists()
        }
        try:
            for relative in commit_paths:
                atomic_write_text(review_dir, relative, (staged / relative).read_text(encoding="utf-8"))
            atomic_write_json(review_dir, "finalization.json", load_object(staged / "finalization.json"))
        except Exception:
            for relative, content in previous.items():
                atomic_write_bytes(review_dir, relative, content)
            for relative in set(rollback_paths) - set(previous):
                path = review_dir / relative
                if path.exists() and not path.is_symlink():
                    path.unlink()
            raise

    errors = check(review_dir)
    if errors:
        raise ValueError("committed package failed final check:\n- " + "\n- ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--check", action="store_true", help="Check an existing finalized package without writing")
    args = parser.parse_args()
    try:
        if args.check:
            errors = check(args.review_dir.resolve(strict=True))
            if errors:
                raise ValueError("\n- ".join(errors))
        else:
            finalize(args.review_dir)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        parser.exit(1, f"finalization failed: {exc}\n")
    print(f"econ-review finalization passed: {args.review_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
