#!/usr/bin/env python3
"""Regression tests for the econ-review output validator."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "validate_review.py"
DESIGN_AUDIT = ROOT / "econ-review" / "references" / "design-audit.md"
DESIGN_PRESETS = ROOT / "econ-review" / "references" / "design-presets.md"
ANALYTICAL_AUDIT = ROOT / "econ-review" / "references" / "analytical-ledgers.md"
ARGUMENT_AUDIT = ROOT / "econ-review" / "references" / "argument-evidence-audit.md"
REPLICATION_AUDIT = ROOT / "econ-review" / "references" / "replication-audit.md"
INTEGRITY_AUDIT = ROOT / "econ-review" / "references" / "research-integrity-audit.md"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
SPEC = importlib.util.spec_from_file_location("validate_review", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sync_candidate_contract(target: Path) -> None:
    """Keep unrelated positive fixture mutations inside the discovery contract."""

    candidates_path = target / "evidence" / "candidates.json"
    coverage_path = target / "evidence" / "coverage.json"
    if not candidates_path.exists() or not coverage_path.exists():
        return
    run = json.loads((target / "run.json").read_text(encoding="utf-8"))
    findings = json.loads((target / "findings.json").read_text(encoding="utf-8"))
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    unit_ids = [
        row["id"] for row in coverage.get("units", [])
        if row.get("status") != "not_applicable"
    ]
    burden_ids = [
        row["id"] for row in run.get("activated_burdens", [])
        if row.get("status") == "active"
    ]
    for row in candidates.get("passes", []):
        if row.get("status") == "completed":
            row["coverage_unit_ids"] = unit_ids
            row["burden_ids"] = burden_ids
    active_rows = [
        row for row in findings.get("findings", [])
        if row.get("status") not in {"dismissed", "resolved"}
    ]
    active_ids = {row.get("id") for row in active_rows}
    granularity = run.get("finding_granularity")
    if isinstance(granularity, dict):
        granularity.update({
            "unique_defect_count": len(active_rows),
            "occurrence_count": sum(
                len(row.get("related_locations", [])) for row in active_rows
            ),
            "evidence_record_count": sum(
                len(row.get("evidence", [])) for row in active_rows
            ),
        })
        (target / "run.json").write_text(
            json.dumps(run, indent=2) + "\n", encoding="utf-8"
        )
    for row in candidates.get("candidates", []):
        if row.get("finding_id") not in active_ids and row.get("disposition") in {
            "admitted", "weakened", "merged"
        }:
            row.update({
                "disposition": "refuted",
                "disposition_reason": "The fixture mutation removed the corresponding active finding.",
                "finding_id": None,
                "merged_into_candidate_id": None,
            })
    sweep = coverage.get("second_sweep", {})
    rounds = sweep.get("rounds", []) if isinstance(sweep, dict) else []
    if rounds:
        rounds[-1]["coverage_unit_ids"] = unit_ids
        pass_id = rounds[-1].get("pass_id")
        sweep_pass_ids = {row.get("pass_id") for row in rounds}
        for row in candidates.get("passes", []):
            if row.get("id") == pass_id:
                row["burden_ids"] = burden_ids
        sweep_candidates = [
            row for row in candidates.get("candidates", [])
            if row.get("pass_id") in sweep_pass_ids
        ]
        sweep["rejected_candidate_count"] = sum(
            row.get("disposition") == "refuted"
            for row in sweep_candidates
        )
        sweep["bounded_candidate_count"] = sum(
            row.get("disposition") == "bounded" for row in sweep_candidates
        )
        sweep["merged_candidate_count"] = sum(
            row.get("disposition") == "merged" for row in sweep_candidates
        )
    candidates_path.write_text(
        json.dumps(candidates, indent=2) + "\n", encoding="utf-8"
    )
    coverage_path.write_text(
        json.dumps(coverage, indent=2) + "\n", encoding="utf-8"
    )


def refresh_finalization_receipt(target: Path) -> None:
    """Re-sign intentional fixture mutations that are not finalizer tests."""
    sync_candidate_contract(target)
    path = target / "finalization.json"
    if not path.exists():
        return
    receipt = json.loads(path.read_text(encoding="utf-8"))
    coverage_path = target / "evidence" / "coverage.json"
    if coverage_path.exists():
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        if coverage.get("schema_version") == "0.2":
            (target / "evidence" / "coverage.md").write_text(
                MODULE.render_coverage(coverage), encoding="utf-8"
            )
    sources_path = target / "evidence" / "external-sources.json"
    if receipt.get("schema_version") != "0.1" and sources_path.exists():
        sources = json.loads(sources_path.read_text(encoding="utf-8"))
        (target / "evidence" / "sources.md").write_text(
            MODULE.render_sources(sources), encoding="utf-8"
        )
    receipt["artifacts"] = {
        item.relative_to(target).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(target.rglob("*"))
        if item.is_file()
        and item.name != ".DS_Store"
        and item.relative_to(target).as_posix() not in {"finalization.json", "review-actions.json"}
    }
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def activate_test_burden(
    target: Path,
    *,
    burden_id: str,
    parent_id: str,
    object_type: str,
    anchor_id: str,
    coverage_unit_ids: list[str],
    rationale: str,
) -> None:
    """Keep positive mutation fixtures reciprocal under the current burden contract."""
    run_path = target / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run_row = next(
        (row for row in run["activated_burdens"] if row.get("id") == burden_id),
        None,
    )
    if run_row is None:
        run_row = {"id": burden_id}
        run["activated_burdens"].append(run_row)
    run_row.update({
        "parent_id": parent_id,
        "object_type": object_type,
        "status": "active",
        "activation_basis": "observed",
        "triggers": [{
            "kind": "anchor",
            "ref": anchor_id,
            "rationale": rationale,
        }],
        "nonactivation_reason": None,
    })
    run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

    coverage_path = target / "evidence" / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage_row = next(
        (row for row in coverage["burden_audits"] if row.get("burden_id") == burden_id),
        None,
    )
    if coverage_row is None:
        coverage_row = {"burden_id": burden_id}
        coverage["burden_audits"].append(coverage_row)
    coverage_row.update({
        "parent_id": parent_id,
        "status": "checked_no_issue",
        "coverage_unit_ids": coverage_unit_ids,
        "finding_ids": [],
        "notes": rationale,
    })
    coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")


def add_audit_only_computation(
    target: Path,
    *,
    audit_link: dict[str, str],
    computation_id: str = "CMP-01",
    result: str = "The recomputed boundary value is zero within tolerance 1e-12.",
) -> None:
    """Add a v0.2 computation whose only consumer is a clean audit row."""
    artifact = target / "evidence" / "computations" / f"{computation_id}.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(result + "\n", encoding="utf-8")
    path = target / "evidence" / "computations.json"
    computations = json.loads(path.read_text(encoding="utf-8"))
    computations["schema_version"] = "0.2"
    computations["computations"].append({
        "id": computation_id,
        "finding_ids": [],
        "audit_links": [audit_link],
        "input_anchor_ids": ["ANC-01"],
        "tool": "synthetic exact-arithmetic check",
        "method": "Evaluate the stated boundary expression at equality.",
        "result": result,
        "artifact_path": artifact.relative_to(target).as_posix(),
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "tolerance": "absolute tolerance 1e-12",
    })
    path.write_text(json.dumps(computations, indent=2) + "\n", encoding="utf-8")
    activate_test_burden(
        target,
        burden_id="computational_validity",
        parent_id="computational_validity",
        object_type="computation",
        anchor_id="ANC-01",
        coverage_unit_ids=["paper"],
        rationale="The synthetic boundary identity was recomputed and audited.",
    )


def bind_computation_to_analytical_entry(
    target: Path,
    *,
    computation_id: str = "CMP-01",
    result: str = "The recomputed boundary value is zero within tolerance 1e-12.",
) -> None:
    path = target / "evidence" / "analytical-audit.json"
    analytical = json.loads(path.read_text(encoding="utf-8"))
    domain = next(row for row in analytical["domains"] if row["kind"] == "timing-test")
    entry = domain["entries"][0]
    entry["evidence_refs"] = [{"kind": "computation", "id": computation_id}]
    entry["evidence_locators"] = [{
        "source": "evidence/computations.json",
        "locator": computation_id,
        "content": result,
        "coverage_unit_id": "paper",
        "anchor_id": None,
        "representation": "computed_result",
        "record_ref": {"kind": "computation", "id": computation_id},
    }]
    path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")


def bind_computation_to_magnitude_assessment(
    target: Path,
    *,
    computation_id: str = "CMP-01",
) -> None:
    claims_path = target / "evidence" / "claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    collection = claims["argument_audit"]["magnitude_assessments"]
    collection.update({
        "status": "complete",
        "boundary": None,
        "notes": "The synthetic boundary magnitude is explicitly recomputed and interpreted.",
        "entries": [{
            "id": "MAG-01",
            "claim_ids": ["CLM-01"],
            "coverage_unit_ids": ["paper"],
            "estimate_or_value": "0 at the equality boundary",
            "unit": "payoff units",
            "comparison_or_denominator": "Action 1 payoff minus action 0 payoff",
            "benchmark_or_baseline": "The zero payoff from action 0",
            "support_or_feasible_range": "The stated parameter domain includes equality",
            "cell_or_case_support": "The equality case is stated in the setup and result",
            "uncertainty": "Exact model identity; numerical tolerance 1e-12",
            "interpretation": "Both actions yield the same payoff at equality.",
            "status": "interpretable",
            "computation_id": computation_id,
            "evidence_refs": [
                {"kind": "anchor", "id": "ANC-01"},
                {"kind": "computation", "id": computation_id},
            ],
            "boundary": None,
            "finding_ids": [],
        }],
    })
    claims_path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
    coverage_path = target / "evidence" / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    dimension = next(
        row for row in coverage["dimensions"] if row["id"] == "magnitude-plausibility"
    )
    dimension.update({
        "status": "checked_no_issue",
        "finding_ids": [],
        "notes": "The explicitly recomputed equality-boundary magnitude is interpretable.",
    })
    coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")


def add_valid_v02_figure(target: Path) -> None:
    """Add one fully bound figure row to the otherwise figure-free fixture."""
    asset = target / "evidence" / "renders" / "pages" / "page-04.png"
    asset.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (560, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.text((24, 18), "Figure 1: Synthetic relationship", fill="black")
    draw.line((82, 295, 510, 295), fill="black", width=3)
    draw.line((82, 295, 82, 70), fill="black", width=3)
    draw.text((18, 76), "Outcome", fill="black")
    draw.text((390, 315), "Treatment group", fill="black")
    draw.line((105, 260, 220, 215, 340, 170, 480, 105), fill="#2457a6", width=5)
    for x, y in ((105, 260), (220, 215), (340, 170), (480, 105)):
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill="#2457a6")
    image.save(asset, format="PNG")

    run_path = target / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["assessment_boundary"]["figures"] = "visually_inspected"
    run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

    coverage_path = target / "evidence" / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["units"].append({
        "id": "U-FIG-01",
        "source_id": "SRC-01",
        "anchor_ids": ["ANC-04"],
        "type": "figure",
        "label": "Figure 1: Synthetic relationship",
        "status": "checked_no_issue",
        "finding_ids": [],
        "notes": "The synthetic rendered figure is clear and internally consistent.",
    })
    coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")

    source_manifest_path = target / "evidence" / "source-manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_text = (target / "synthetic-paper.md").read_text(encoding="utf-8")
    source_manifest["anchors"].append({
        "id": "ANC-04",
        "source_id": "SRC-01",
        "kind": "figure",
        "start_char": 0,
        "end_char": len(source_text),
        "content_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "locator": "Complete synthetic manuscript figure surface",
    })
    source_manifest_path.write_text(
        json.dumps(source_manifest, indent=2) + "\n", encoding="utf-8"
    )

    claims_path = target / "evidence" / "claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claims["audit_scope"]["coverage_unit_ids"].append("U-FIG-01")
    claims_path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")

    analytical_path = target / "evidence" / "analytical-audit.json"
    analytical = json.loads(analytical_path.read_text(encoding="utf-8"))
    analytical["scope"]["coverage_unit_ids"].append("U-FIG-01")
    analytical_path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")

    writing_path = target / "evidence" / "writing.json"
    writing = json.loads(writing_path.read_text(encoding="utf-8"))
    writing["scope"]["coverage_unit_ids"].append("U-FIG-01")
    writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")

    figures_path = target / "evidence" / "figures.json"
    figures = {
        "schema_version": "0.2",
        "review_id": run["review_id"],
        "source_render": "Synthetic rendered manuscript page",
        "inventory_complete_within_assessment_boundary": True,
        "no_figures_confirmed": False,
        "figures": [{
            "id": "FIG-01",
            "source_id": "SRC-01",
            "coverage_unit_id": "U-FIG-01",
            "label": "Figure 1: Synthetic relationship",
            "pdf_pages": [4],
            "source_locator": {
                "source_id": "SRC-01",
                "pages": [4],
                "context": "Rendered manuscript page containing the complete figure.",
            },
            "identity_keys": ["Figure 1", "Synthetic relationship"],
            "rendered_assets": [{
                "path": "evidence/renders/pages/page-04.png",
                "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                "pdf_page": 4,
                "render_type": "full_page",
                "source_object_id": None,
                "visible_identity": {
                    "basis": "figure_label",
                    "text": "Figure 1: Synthetic relationship",
                    "status": "matched",
                    "notes": "The visible figure label agrees with the audit row and page.",
                },
            }],
            "kind": "plot",
            "visual_status": "clear",
            "caption_text_status": "consistent",
            "claim_correspondence_status": "consistent",
            "checks": {
                "axes_scales_units": "The synthetic axes and units are visible.",
                "legend_series_panels": "The single series is identified directly.",
                "uncertainty": "No uncertainty display is applicable here.",
                "legibility_accessibility": "The retained render is legible for inspection.",
                "visual_integrity": "The figure identity and visual object agree.",
            },
            "assessment_boundary": None,
            "finding_ids": [],
            "notes": "The immutable full-page asset was visually reconciled.",
        }],
        "boundary_notes": "The synthetic figure inventory is complete.",
    }
    figures_path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
    activate_test_burden(
        target,
        burden_id="figure_integrity",
        parent_id="exhibit_integrity",
        object_type="exhibit",
        anchor_id="ANC-04",
        coverage_unit_ids=["U-FIG-01"],
        rationale="The synthetic figure was rendered and inspected against its source identity.",
    )
    activate_test_burden(
        target,
        burden_id="exhibit_integrity",
        parent_id="exhibit_integrity",
        object_type="exhibit",
        anchor_id="ANC-04",
        coverage_unit_ids=["U-FIG-01"],
        rationale="The rendered exhibit audit contains a source-bound synthetic figure.",
    )
    refresh_finalization_receipt(target)


def add_synthetic_table(target: Path, *, finding_ids: list[str] | None = None) -> None:
    """Add a rendered table to the public synthetic fixture."""
    finding_ids = list(finding_ids or [])
    render = target / "evidence" / "renders" / "tables" / "table-01.png"
    render.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (640, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 15), "Table 1: Synthetic boundary cases", fill="black")
    draw.text((30, 65), "Parameter", fill="black")
    draw.text((260, 65), "Action", fill="black")
    draw.text((30, 115), "Below boundary", fill="black")
    draw.text((260, 115), "0", fill="black")
    draw.text((30, 165), "At boundary", fill="black")
    draw.text((260, 165), "0 or 1", fill="black")
    image.save(render, format="PNG")

    coverage_path = target / "evidence" / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["units"].append({
        "id": "U-TBL-01",
        "source_id": "SRC-01",
        "anchor_ids": ["ANC-04"],
        "type": "table",
        "label": "Table 1: Synthetic boundary cases",
        "status": "issue" if finding_ids else "checked_no_issue",
        "finding_ids": finding_ids,
        "notes": "A synthetic rendered table used for portable contract tests.",
    })
    coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")

    source_manifest_path = target / "evidence" / "source-manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_text = (target / "synthetic-paper.md").read_text(encoding="utf-8")
    source_manifest["anchors"].append({
        "id": "ANC-04",
        "source_id": "SRC-01",
        "kind": "table_cell",
        "start_char": 0,
        "end_char": len(source_text),
        "content_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "locator": "Complete synthetic manuscript table surface",
    })
    source_manifest_path.write_text(
        json.dumps(source_manifest, indent=2) + "\n", encoding="utf-8"
    )

    for relative, scope_key in (
        ("claims.json", "audit_scope"),
        ("analytical-audit.json", "scope"),
        ("writing.json", "scope"),
    ):
        path = target / "evidence" / relative
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload[scope_key]["coverage_unit_ids"].append("U-TBL-01")
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    check = {"status": "clear", "result": "The rendered synthetic table is internally consistent."}
    table = {
        "id": "TBL-01",
        "source_id": "SRC-01",
        "coverage_unit_id": "U-TBL-01",
        "label": "Table 1: Synthetic boundary cases",
        "pdf_pages": [1],
        "source_locator": {
            "source_id": "SRC-01",
            "pages": [1],
            "context": "Synthetic source location containing the complete table.",
        },
        "identity_keys": ["Table 1", "Synthetic boundary cases"],
        "rendered_assets": [{
            "path": render.relative_to(target).as_posix(),
            "sha256": hashlib.sha256(render.read_bytes()).hexdigest(),
            "pdf_page": 1,
            "render_type": "crop",
            "source_object_id": None,
            "visible_identity": {
                "basis": "table_label",
                "text": "Table 1: Synthetic boundary cases",
                "status": "matched",
                "notes": "The visible table label agrees with the audit row.",
            },
        }],
        "render_status": "inspected",
        "extraction_status": "consistent",
        "visual_status": "clear",
        "claim_correspondence_status": "issue" if finding_ids else "consistent",
        "checks": {
            name: dict(check)
            for name in (
                "number_title_panels", "row_column_alignment", "cell_completeness",
                "units_transformations", "sample_denominator_support", "uncertainty_inference",
                "definitions_sources", "cross_table_consistency", "calculation_traceability",
                "text_claim_reconciliation",
            )
        },
        "assessment_boundary": None,
        "finding_ids": finding_ids,
        "notes": "The immutable render was inspected separately from extracted text.",
    }
    tables_path = target / "evidence" / "tables.json"
    tables = {
        "schema_version": "0.2",
        "review_id": json.loads((target / "run.json").read_text(encoding="utf-8"))["review_id"],
        "source": "Synthetic rendered manuscript page",
        "inventory_complete_within_assessment_boundary": True,
        "no_tables_confirmed": False,
        "tables": [table],
        "boundary_notes": "The synthetic table inventory is complete.",
    }
    tables_path.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
    activate_test_burden(
        target,
        burden_id="exhibit_integrity",
        parent_id="exhibit_integrity",
        object_type="exhibit",
        anchor_id="ANC-04",
        coverage_unit_ids=["U-TBL-01"],
        rationale="The rendered exhibit audit contains a source-bound synthetic table.",
    )
    refresh_finalization_receipt(target)


def declare_synthetic_pdf_render_index(
    target: Path,
    *,
    page_path: str = "evidence/renders/pages/page-04.png",
    page_number: int = 4,
    crop_path: str | None = None,
    crop_object_id: str = "SRC-01-PDF-FIG-001",
    crop_kind: str = "figure",
) -> None:
    """Make SRC-01 a PDF source with a minimal canonical render index.

    Exhibit-binding tests patch the full ingestion verifier because its complete
    package contract is tested separately. The review validator still reads
    this index and must join each declared asset to it exactly.
    """
    if crop_kind not in {"figure", "table"}:
        raise ValueError(crop_kind)
    paper = target / "paper.pdf"
    paper.write_bytes(b"%PDF-1.7\nsynthetic figure-binding fixture\n")
    page_asset = target / page_path
    source_path = target / "evidence" / "source-manifest.json"
    source_manifest = json.loads(source_path.read_text(encoding="utf-8"))
    anchor_by_id = {
        row["id"]: row
        for row in source_manifest["anchors"]
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    claims_path = target / "evidence" / "claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    terminology = claims["terminology_inventory"]
    terminology_source = next(
        row for row in terminology["sources"] if row.get("source_id") == "SRC-01"
    )
    terminology_source["method"] = "pdf_ingestion"
    terminology_source["boundary_reason"] = None
    candidate_rows = [
        row for row in terminology["candidates"]
        if isinstance(row, dict) and row.get("source_id") == "SRC-01"
    ]
    occurrence_anchor_ids = sorted({
        anchor_id
        for row in candidate_rows
        for anchor_id in row.get("occurrence_anchor_ids", [])
        if isinstance(anchor_id, str) and anchor_id in anchor_by_id
    })
    blocks = [{
        "id": f"PDF-BLOCK-{anchor_id}",
        "page": page_number,
        "markdown_start": anchor_by_id[anchor_id]["start_char"],
        "markdown_end": anchor_by_id[anchor_id]["end_char"],
        "sha256": anchor_by_id[anchor_id]["content_sha256"],
    } for anchor_id in occurrence_anchor_ids]
    symbols = [{
        "symbol": row["candidate"],
        "codepoints": row.get("codepoints", []),
        "occurrences": [{
            "block_id": f"PDF-BLOCK-{anchor_id}",
            "page": page_number,
        } for anchor_id in row.get("occurrence_anchor_ids", [])],
    } for row in candidate_rows]
    claims_path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
    ingestion = {
        "review_id": json.loads((target / "run.json").read_text(encoding="utf-8"))["review_id"],
        "source_id": "SRC-01",
        "pages": [{
            "page": page_number,
            "render_path": page_path,
            "render_sha256": hashlib.sha256(page_asset.read_bytes()).hexdigest(),
        }],
        "blocks": blocks,
        "symbols": symbols,
        "figures": [],
        "tables": [],
    }
    if crop_path is not None:
        crop_asset = target / crop_path
        ingestion[f"{crop_kind}s"].append({
            "id": crop_object_id,
            "page": page_number,
            "crop_path": crop_path,
            "crop_sha256": hashlib.sha256(crop_asset.read_bytes()).hexdigest(),
        })
    ingestion_path = target / "evidence" / "pdf-ingestion" / "SRC-01" / "ingestion.json"
    ingestion_path.parent.mkdir(parents=True, exist_ok=True)
    ingestion_bytes = json.dumps(ingestion, indent=2).encode("utf-8") + b"\n"
    ingestion_path.write_bytes(ingestion_bytes)

    source = source_manifest["sources"][0]
    source.update({
        "path": "paper.pdf",
        "media_type": "application/pdf",
        "sha256": hashlib.sha256(paper.read_bytes()).hexdigest(),
        "extraction": {
            "path": "synthetic-paper.md",
            "sha256": hashlib.sha256((target / "synthetic-paper.md").read_bytes()).hexdigest(),
            "normalization": "none",
            "ingestion_manifest_path": "evidence/pdf-ingestion/SRC-01/ingestion.json",
            "ingestion_manifest_sha256": hashlib.sha256(ingestion_bytes).hexdigest(),
            "pipeline_fingerprint": "a" * 64,
        },
    })
    source_path.write_text(json.dumps(source_manifest, indent=2) + "\n", encoding="utf-8")

    findings_path = target / "findings.json"
    findings = json.loads(findings_path.read_text(encoding="utf-8"))
    for finding in findings["findings"]:
        for evidence in finding.get("evidence", []):
            anchor = anchor_by_id.get(evidence.get("anchor_id"))
            if isinstance(anchor, dict) and anchor.get("source_id") == "SRC-01":
                evidence["source"] = "paper.pdf"
                locator = evidence.get("locator")
                if isinstance(locator, dict):
                    locator["file"] = "paper.pdf"
    findings_path.write_text(json.dumps(findings, indent=2) + "\n", encoding="utf-8")

    coverage_path = target / "evidence" / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    retained_inventory = [
        row for row in coverage.get("source_inventory", [])
        if not (
            isinstance(row, dict)
            and row.get("source_id") == "SRC-01"
            and str(row.get("object_type", "")).startswith("pdf_")
        )
    ]
    next_inventory = max(
        [
            int(str(row.get("id", "")).split("-", 1)[1])
            for row in retained_inventory
            if re.fullmatch(r"INV-[0-9]{3,}", str(row.get("id", "")))
        ],
        default=0,
    ) + 1
    retained_inventory.append({
        "id": f"INV-{next_inventory:03d}",
        "source_id": "SRC-01",
        "object_type": "pdf_page",
        "object_id": f"SRC-01-PDF-P{page_number:04d}",
        "locator": f"PDF page {page_number}",
        "state": "covered",
        "anchor_ids": [],
        "coverage_unit_ids": ["paper"],
        "audit_record_id": None,
        "duplicate_of": None,
        "reason": None,
    })
    for block in blocks:
        next_inventory += 1
        anchor_id = str(block["id"]).removeprefix("PDF-BLOCK-")
        retained_inventory.append({
            "id": f"INV-{next_inventory:03d}",
            "source_id": "SRC-01",
            "object_type": "pdf_block",
            "object_id": block["id"],
            "locator": f"PDF page {page_number}, block {block['id']}",
            "state": "covered",
            "anchor_ids": [anchor_id],
            "coverage_unit_ids": ["paper"],
            "audit_record_id": None,
            "duplicate_of": None,
            "reason": None,
        })
    if crop_path is not None:
        next_inventory += 1
        coverage_unit_id = "U-FIG-01" if crop_kind == "figure" else "U-TBL-01"
        audit_record_id = "FIG-01" if crop_kind == "figure" else "TBL-01"
        retained_inventory.append({
            "id": f"INV-{next_inventory:03d}",
            "source_id": "SRC-01",
            "object_type": f"pdf_{crop_kind}",
            "object_id": crop_object_id,
            "locator": f"PDF page {page_number}, pdf {crop_kind} {crop_object_id}",
            "state": "covered",
            "anchor_ids": [],
            "coverage_unit_ids": [coverage_unit_id],
            "audit_record_id": audit_record_id,
            "duplicate_of": None,
            "reason": None,
        })
    coverage["source_inventory"] = retained_inventory
    coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")

    run_path = target / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    boundary_source = run["assessment_boundary"]["sources"][0]
    boundary_source["source_id"] = source["id"]
    boundary_source["path"] = source["path"]
    boundary_source["sha256"] = source["sha256"]
    run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

    receipt_path = target / "finalization.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if "source_ingestion" not in receipt["gates"]:
        receipt["gates"].append("source_ingestion")
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    refresh_finalization_receipt(target)


def bind_synthetic_table_to_pdf(target: Path) -> None:
    """Bind the synthetic table's page and crop to a canonical ingestion index."""
    page_path = "evidence/renders/pages/page-01.png"
    page = target / page_path
    page.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (720, 480), "white")
    draw = ImageDraw.Draw(image)
    draw.text((35, 30), "Table 1: Synthetic boundary cases", fill="black")
    draw.rectangle((30, 75, 690, 420), outline="black", width=2)
    draw.text((55, 110), "Parameter", fill="black")
    draw.text((350, 110), "Action", fill="black")
    draw.text((55, 190), "Below boundary", fill="black")
    draw.text((350, 190), "0", fill="black")
    draw.text((55, 270), "At boundary", fill="black")
    draw.text((350, 270), "0 or 1", fill="black")
    image.save(page, format="PNG")

    tables_path = target / "evidence" / "tables.json"
    tables = json.loads(tables_path.read_text(encoding="utf-8"))
    row = tables["tables"][0]
    crop_path = row["rendered_assets"][0]["path"]
    crop = target / crop_path
    row["source_id"] = "SRC-01"
    row["pdf_pages"] = [1]
    row["source_locator"] = {
        "source_id": "SRC-01",
        "pages": [1],
        "context": "Canonical PDF page containing the complete table.",
    }
    row["rendered_assets"] = [
        {
            "path": page_path,
            "sha256": hashlib.sha256(page.read_bytes()).hexdigest(),
            "pdf_page": 1,
            "render_type": "full_page",
            "source_object_id": None,
            "visible_identity": {
                "basis": "table_label",
                "text": "Table 1: Synthetic boundary cases",
                "status": "matched",
                "notes": "The full source page visibly identifies Table 1.",
            },
        },
        {
            "path": crop_path,
            "sha256": hashlib.sha256(crop.read_bytes()).hexdigest(),
            "pdf_page": 1,
            "render_type": "crop",
            "source_object_id": "SRC-01-PDF-TBL-001",
            "visible_identity": {
                "basis": "table_label",
                "text": "Table 1: Synthetic boundary cases",
                "status": "matched",
                "notes": "The canonical crop visibly identifies Table 1.",
            },
        },
    ]
    tables_path.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
    declare_synthetic_pdf_render_index(
        target,
        page_path=page_path,
        page_number=1,
        crop_path=crop_path,
        crop_object_id="SRC-01-PDF-TBL-001",
        crop_kind="table",
    )
    refresh_finalization_receipt(target)


def legacy_reference_audit() -> dict[str, object]:
    return {
        "status": "complete",
        "in_text_citation_count": 0,
        "bibliography_record_count": 0,
        "records_checked": 0,
        "records_verified": 0,
        "records_adverse": 0,
        "records_unresolved": 0,
        "records": [],
        "citation_reference_consistency": "No citations are present.",
        "load_bearing_support_check": "No external support claims are present.",
        "access_date": None,
        "finding_ids": [],
    }


def convert_fixture_to_contract_v02(target: Path) -> None:
    """Exercise the actual v0.2 split-report branch with its legacy presentation."""
    run_path = target / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["schema_version"] = "0.2"
    run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

    ledger_path = target / "findings.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["schema_version"] = "0.2"
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    by_id = {row["id"]: row for row in ledger["findings"]}

    substance = by_id["LOGIC-01"]
    target.joinpath("report.md").write_text(
        "# Referee Report\n\n"
        "## Is the argument convincing to a reader?\n\n"
        "The central logic is promising, but the stated boundary case must be reconciled before the uniqueness claim is convincing.\n\n"
        "## Detailed Comments (1)\n\n"
        f"### 1. {substance['title']}\n"
        "<!-- finding_id: LOGIC-01 -->\n\n"
        "**Status**: [Pending]\n\n"
        "**Quote**:\n"
        f"> {substance['evidence'][0]['content']}\n\n"
        f"**Feedback**: {substance['why_it_matters']} {substance['fix']['how']}\n",
        encoding="utf-8",
    )

    writing_path = target / "evidence" / "writing.json"
    writing = json.loads(writing_path.read_text(encoding="utf-8"))
    writing["schema_version"] = "0.1"
    writing["reference_audit"] = legacy_reference_audit()
    for field in (
        "paper_type_lens", "strengths", "section_audit", "redundancy_map",
        "highest_return_finding_ids", "finding_links",
    ):
        writing.pop(field, None)
    writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")

    writing_finding = by_id["WRT-01"]
    target.joinpath("editing-comments.md").write_text(
        "# Writing Review Report\n\n"
        "## Writing quality summary\n\n"
        "The manuscript is concise and generally readable; one verified agreement error remains.\n\n"
        "## Grammar, typos, and mechanics\n\n"
        "Correct the singular subject's verb in the proposition summary.\n\n"
        "## Language consistency\n\n"
        "The equilibrium terminology is otherwise consistent.\n\n"
        "## Style and writing improvement suggestions\n\n"
        "Preserve the compact proposition summary while making the objective correction.\n\n"
        "## Reference accuracy and citation support\n\n"
        "The synthetic fixture contains no citations or bibliography records.\n\n"
        "## Detailed Editing Comments (1)\n\n"
        f"### 1. {writing_finding['title']}\n"
        "<!-- finding_id: WRT-01 -->\n\n"
        "**Status**: [Pending]\n\n"
        "**Quote**:\n"
        f"> {writing_finding['evidence'][0]['content']}\n\n"
        f"**Feedback**: {writing_finding['why_it_matters']} {writing_finding['fix']['how']}\n",
        encoding="utf-8",
    )


class ValidateReviewTests(unittest.TestCase):
    def test_comment_validator_accepts_unquoted_reviewer_observation_without_label(self) -> None:
        finding = {
            "id": "LOGIC-01",
            "issue": "The displayed values diverge.",
            "importance_rank": 1,
            "display_evidence_id": "EVD-01",
            "evidence": [{
                "id": "EVD-01",
                "representation": "reviewer_observation",
                "content": "[Reviewer observation] The displayed values diverge.",
            }],
        }
        report = (
            "## Detailed Comments (1)\n\n"
            "### 1. Results: Displayed values\n"
            "<!-- finding_id: LOGIC-01 -->\n\n"
            "**Issue**: The displayed values diverge.\n\n"
            "**Relevant text**:\n"
            "The displayed values diverge.\n\n"
            "**Concern**: The inconsistency changes the reported comparison.\n\n"
            "**Suggestions**: Reconcile the two displayed values.\n\n"
            "**Status**: [Pending]\n"
        )
        errors: list[str] = []
        ids = MODULE.validate_comment_section_v3(
            report, "report.md", "Detailed Comments", [finding], errors,
        )
        self.assertEqual(ids, {"LOGIC-01"})
        self.assertEqual(errors, [])

    def test_design_audit_remains_general_across_paper_families(self) -> None:
        audit = (
            DESIGN_AUDIT.read_text(encoding="utf-8")
            + "\n"
            + DESIGN_PRESETS.read_text(encoding="utf-8")
        ).lower()
        ledgers = ANALYTICAL_AUDIT.read_text(encoding="utf-8").lower()
        for branch in (
            "empirical causal and experimental",
            "descriptive, measurement, and forecasting",
            "prediction and machine learning",
            "institutional, historical, archival, and qualitative evidence",
            "evidence synthesis and meta-analysis",
            "structural and quantitative",
            "macro and dynamic equilibrium",
            "formal theory",
            "mixed components",
        ):
            self.assertIn(branch, audit)
        for domain in (
            "partition and regime ledger",
            "measure-algebra ledger",
            "assumption-to-implementation crosswalk",
            "derived-number ledger",
            "comparison-harmonization ledger",
            "timing and test ledger",
            "availability and exclusivity ledger",
        ):
            self.assertIn(domain, ledgers)
        argument = ARGUMENT_AUDIT.read_text(encoding="utf-8").lower()
        for concept in (
            "economic argument",
            "complete comparison or intervention experience",
            "related results across claim families",
            "promised, measured, and modeled objects",
            "classify what each evidence object can establish",
            "branching test",
            "headline magnitudes",
            "sample and model scope",
        ):
            self.assertIn(concept, argument)
        replication = REPLICATION_AUDIT.read_text(encoding="utf-8").lower()
        for concept in (
            "static audit before execution",
            "explicit user permission",
            "successful execution supports reproducibility, not identification",
            "package_failure",
            "result_mismatch",
        ):
            self.assertIn(concept, replication)
        integrity = INTEGRITY_AUDIT.read_text(encoding="utf-8").lower()
        for concept in (
            "activate from facts, not from a universal checklist",
            "not legal advice",
            "do not infer fabrication, unethical conduct, illegality, or intent",
            "restricted or nonshareable data are not a criticism",
        ):
            self.assertIn(concept, integrity)
        for paper_specific_term in ("inflation reduction act", "prolific", "qualtrics"):
            self.assertNotIn(paper_specific_term, argument)

    def test_new_design_lenses_have_object_activation_and_anti_ritual_contracts(self) -> None:
        audit = DESIGN_AUDIT.read_text(encoding="utf-8").lower()
        presets = DESIGN_PRESETS.read_text(encoding="utf-8").lower()

        self.assertIn("activation follows the object", audit)
        self.assertIn(
            "a familiar method name does not activate every conventional diagnostic",
            audit,
        )
        self.assertIn("state the exact source-derived trigger", audit)
        self.assertIn(
            "do not request a ritual diagnostic that cannot do so",
            audit,
        )

        prediction = presets.split("## prediction and machine learning", 1)[1].split("\n## ", 1)[0]
        for required in (
            "prediction target",
            "information available at the prediction date",
            "separate predictive performance from causal, mechanism, welfare, or policy claims",
            "only when it carries one of those claims or a stated decision objective",
            "not as a universal machine-learning ritual",
        ):
            self.assertIn(required, prediction)

        historical = presets.split(
            "## institutional, historical, archival, and qualitative evidence", 1
        )[1].split("\n## ", 1)[0]
        for required in (
            "source universe",
            "inferential move from recorded evidence",
            "existence, mechanism plausibility, typicality, or a broader causal claim",
            "do not impose sampling-based inference or a fixed source count",
        ):
            self.assertIn(required, historical)

        synthesis = presets.split("## evidence synthesis and meta-analysis", 1)[1].split(
            "\n## ", 1
        )[0]
        for required in (
            "search universe and dates",
            "estimand comparability",
            "whether a pooled summary answers a stable economic question",
            "do not demand one named bias diagnostic or a universal random-effects model",
            "smallest sensitivity or scope change",
        ):
            self.assertIn(required, synthesis)

    def test_valid_fixture_passes(self) -> None:
        self.assertEqual(MODULE.validate_review(FIXTURE), [])

    def test_coarse_family_metadata_does_not_activate_a_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["paper_family"] = "historical-qualitative"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_contract_v02_with_writing_audit_v01_and_five_heading_report_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            convert_fixture_to_contract_v02(target)
            self.assertEqual(json.loads((target / "run.json").read_text())["schema_version"], "0.2")
            self.assertEqual(json.loads((target / "findings.json").read_text())["schema_version"], "0.2")
            self.assertEqual(json.loads((target / "evidence" / "writing.json").read_text())["schema_version"], "0.1")
            self.assertIn("## Writing quality summary", (target / "editing-comments.md").read_text())
            self.assertEqual(MODULE.validate_review(target), [])

    def test_uncapped_comment_policy_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["comment_policy"]["maximum"] = None
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_v04_full_review_rejects_a_legacy_aggregate_comment_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["comment_policy"]["maximum"] = 100
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("legacy comment_policy.maximum" in error for error in errors), errors)

    def test_v04_full_review_uses_separate_100_and_30_channel_capacities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["comment_policy"]["writing_maximum"] = 29
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "substance_maximum 100 and writing_maximum 30" in error
                for error in errors
            ), errors)

    def test_channel_capacities_must_be_declared_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["comment_policy"].pop("writing_maximum")
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("declare substance_maximum and writing_maximum together" in error for error in errors), errors)

    def test_burdens_use_closed_conceptual_parents_without_alias_rows(self) -> None:
        def append_extension(target: Path, parent_id: str | None) -> None:
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            extension = json.loads(json.dumps(next(
                row for row in run["activated_burdens"] if row["id"] == "logical_validity"
            )))
            extension["id"] = "boundary_case_logic"
            if parent_id is not None:
                extension["parent_id"] = parent_id
            else:
                extension.pop("parent_id", None)
            run["activated_burdens"].append(extension)
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            append_extension(target, None)
            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("must name a stable conceptual parent_id" in error for error in errors),
                errors,
            )

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            append_extension(target, "invented_parent")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("parent_id" in error for error in errors), errors)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            append_extension(target, "logical_validity")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage["burden_audits"].append({
                "burden_id": "boundary_case_logic",
                "parent_id": "logical_validity",
                "status": "findings",
                "coverage_unit_ids": ["paper"],
                "finding_ids": ["LOGIC-01"],
                "notes": "The boundary-case extension is audited through the same verified source span.",
            })
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            logical = next(
                row for row in run["activated_burdens"] if row["id"] == "logical_validity"
            )
            logical["parent_id"] = "technical_validity"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("parent burden logical_validity must be self-parented" in error for error in errors),
                errors,
            )

    def test_source_objects_reverse_activate_unambiguous_burdens(self) -> None:
        def helper_errors(target: Path, run: dict) -> list[str]:
            errors: list[str] = []
            MODULE.validate_reverse_burden_activation(target, run, errors)
            return errors

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            if not any(
                row.get("parent_id") == "source_support" and row.get("status") == "active"
                for row in run["activated_burdens"]
            ):
                run["activated_burdens"].append({
                    "id": "literature_frontier",
                    "parent_id": "source_support",
                    "object_type": "literature",
                    "status": "active",
                    "activation_basis": "observed",
                    "triggers": [],
                    "nonactivation_reason": None,
                })
            self.assertEqual(helper_errors(target, run), [])

            logical = json.loads(json.dumps(run))
            for row in logical["activated_burdens"]:
                if row.get("parent_id") == "logical_validity":
                    row["status"] = "not_applicable"
            errors = helper_errors(target, logical)
            self.assertTrue(any("active logical_validity burden" in error for error in errors), errors)

            communication = json.loads(json.dumps(run))
            for row in communication["activated_burdens"]:
                if row.get("parent_id") == "communication_integrity":
                    row["status"] = "not_applicable"
            errors = helper_errors(target, communication)
            self.assertTrue(any("active communication_integrity burden" in error for error in errors), errors)

            computations_path = target / "evidence" / "computations.json"
            computations = json.loads(computations_path.read_text(encoding="utf-8"))
            computations["computations"].append({})
            computations_path.write_text(
                json.dumps(computations, indent=2) + "\n", encoding="utf-8"
            )
            errors = helper_errors(target, run)
            self.assertTrue(any("active computational_validity burden" in error for error in errors), errors)

            computations["computations"] = []
            computations_path.write_text(
                json.dumps(computations, indent=2) + "\n", encoding="utf-8"
            )
            external_path = target / "evidence" / "external-sources.json"
            external = json.loads(external_path.read_text(encoding="utf-8"))
            external["frontier_audit"]["status"] = "bounded"
            external_path.write_text(
                json.dumps(external, indent=2) + "\n", encoding="utf-8"
            )
            no_source_support = json.loads(json.dumps(run))
            for row in no_source_support["activated_burdens"]:
                if row.get("parent_id") == "source_support":
                    row["status"] = "not_applicable"
            errors = helper_errors(target, no_source_support)
            self.assertTrue(any("active source_support burden" in error for error in errors), errors)

            external["frontier_audit"]["status"] = "not_assessed"
            external_path.write_text(
                json.dumps(external, indent=2) + "\n", encoding="utf-8"
            )
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            figures["figures"].append({})
            figures_path.write_text(
                json.dumps(figures, indent=2) + "\n", encoding="utf-8"
            )
            errors = helper_errors(target, run)
            self.assertTrue(any("active exhibit_integrity burden" in error for error in errors), errors)

    def test_v3_does_not_apply_an_arbitrary_essential_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            base = ledger["findings"][0]
            ledger["findings"] = []
            for index in range(4):
                item = json.loads(json.dumps(base))
                item["id"] = f"LOGIC-{index + 1:02d}"
                ledger["findings"].append(item)
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertFalse(any("essential finding cap exceeded" in error for error in errors))

    def test_missing_absence_scope_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            evidence = ledger["findings"][0]["evidence"][0]
            evidence["type"] = "absence_scope"
            evidence["content"] = None
            evidence["scope_checked"] = None
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires scope_checked" in error for error in errors))

    def test_unmet_comment_target_with_documented_second_sweep_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["comment_policy"]["minimum_target"] = 3
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_unmet_comment_target_without_shortfall_explanation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["comment_policy"]["minimum_target"] = 3
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage["second_sweep"]["shortfall_explanation"] = None
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("falls below the requested comment target" in error for error in errors))

    def test_nonconsecutive_ranks_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"][0]["importance_rank"] = 2
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("importance ranks must be consecutive" in error for error in errors))

    def test_current_priority_order_is_globally_severity_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            major, minor = ledger["findings"]
            major["decision_role"] = "revision_value"
            major["essential"] = False
            major["importance_rank"] = 2
            minor["decision_role"] = "revision_value"
            minor["importance_rank"] = 1
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("globally severity-first" in error for error in errors),
                errors,
            )

    def test_current_priority_order_uses_decision_role_within_severity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            dispositive, revision = ledger["findings"]
            dispositive.update({"severity": "major", "importance_rank": 2})
            revision.update({
                "severity": "major",
                "decision_role": "revision_value",
                "essential": False,
                "report_channel": "substance",
                "importance_rank": 1,
            })
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("within each severity tier" in error for error in errors),
                errors,
            )

    def test_critical_finding_must_be_potentially_dispositive_and_essential(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            row = ledger["findings"][0]
            row.update({
                "severity": "critical",
                "decision_role": "revision_value",
                "essential": False,
            })
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("must be potentially_dispositive and essential" in error for error in errors),
                errors,
            )

    def test_active_refuted_finding_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"][0]["counterargument"]["result"] = "refuted"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("active finding cannot have a refuted counterargument" in error for error in errors))

    def test_duplicate_fix_plan_mapping_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            plan_path = target / "fix-plan.md"
            plan_path.write_text(
                plan_path.read_text(encoding="utf-8")
                + "\n### Comment 99: Duplicate task\n<!-- finding_id: LOGIC-01 -->\n",
                encoding="utf-8",
            )
            errors = MODULE.validate_review(target)
            self.assertTrue(any("exactly once in fix-plan.md" in error for error in errors))

    def test_invalid_status_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["status"] = "COMPLETE"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("schema violation" in error and "status" in error for error in errors))

    def test_empty_coverage_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "evidence" / "coverage.json").write_text("{}\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("coverage.json" in error for error in errors))

    def test_bounded_core_stage_fails_complete_full_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["stage_status"]["verification"] = "bounded"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires stage 'verification' to be passed" in error for error in errors))

    def test_inherent_bounded_data_limit_cannot_be_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"][0]["data_limitation"] = "inherent_and_properly_bounded"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("cannot be an active criticism" in error for error in errors))

    def test_inherent_data_overclaim_cannot_demand_new_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            finding = ledger["findings"][0]
            finding["critique_basis"] = "claim_exceeds_evidence"
            finding["data_limitation"] = "inherent_but_claim_exceeds"
            finding["fix"]["strategy"] = "add_analysis"
            finding["fix"]["effort"] = "new-data"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("cannot require new data" in error for error in errors))

    def test_v2_inherent_data_overclaim_needs_disclosure_and_unhedged_claim_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            finding = ledger["findings"][0]
            finding["data_limitation"] = "inherent_but_claim_exceeds"
            finding["critique_basis"] = "claim_exceeds_evidence"
            finding["claim_ids"] = ["CLM-01"]
            finding["fix"]["strategy"] = "narrow_claim"
            finding["fix"]["requires_new_data"] = False
            finding["fix"]["current_design_can_support_primary_fix"] = True
            finding["fix"]["claim_narrowing_alternative"] = "Narrow the claim to the supported parameter set."
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires separate quoted evidence" in error for error in errors))

    def test_unknown_claim_family_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"][0]["claim_ids"] = ["CLM-99"]
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("unknown claim family CLM-99" in error for error in errors))

    def test_missing_reader_assessment_section_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            report_path = target / "report.md"
            report = report_path.read_text(encoding="utf-8")
            start = report.index("## Is the argument convincing?")
            end = report.index("## Detailed Comments")
            report_path.write_text(report[:start] + report[end:], encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("missing '## Is the argument convincing?'" in error for error in errors))

    def test_unsafe_claim_occurrence_requires_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["claim_families"][0]["finding_ids"] = []
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("unsafe claim occurrence" in error for error in errors))

    def test_undefined_term_requires_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["terms"][0]["status"] = "undefined"
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("adverse term state" in error for error in errors))

    def test_unmapped_inconsistent_reader_state_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["reader_map"][0]["finding_ids"] = []
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("adverse reader-map state" in error for error in errors))

    def test_unassessed_active_finding_fails_complete_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            ledger["findings"][0]["support_state"] = "not_assessed"
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("cannot report unresolved support state" in error for error in errors))

    def test_empty_evidence_and_locator_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            evidence = ledger["findings"][0]["evidence"][0]
            evidence["content"] = "   "
            evidence["locator"] = {key: None for key in evidence["locator"]}
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires non-empty content" in error for error in errors))
            self.assertTrue(any("must identify at least one manuscript location" in error for error in errors))

    def test_inherent_data_fix_structurally_disallows_new_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            finding = ledger["findings"][0]
            finding["critique_basis"] = "claim_exceeds_evidence"
            finding["data_limitation"] = "inherent_but_claim_exceeds"
            finding["fix"]["strategy"] = "narrow_claim"
            finding["fix"]["requires_new_data"] = True
            finding["fix"]["what"] = "Collect a new proprietary dataset."
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("primary fix for an inherent data limit must not require new data" in error for error in errors))

    def test_universal_reader_dimension_cannot_be_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "coverage.json"
            coverage = json.loads(path.read_text(encoding="utf-8"))
            next(row for row in coverage["dimensions"] if row["id"] == "terms-variables")["status"] = "not_applicable"
            path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("terms-variables' cannot be not_applicable" in error for error in errors))

    def test_object_specific_dimension_can_be_source_grounded_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "coverage.json"
            coverage = json.loads(path.read_text(encoding="utf-8"))
            row = next(
                item for item in coverage["dimensions"]
                if item["id"] == "reproducibility-documentation"
            )
            row.update({
                "status": "not_applicable",
                "finding_ids": [],
                "notes": "The complete synthetic note contains no data, code, simulation, or numerical result.",
                "branch": "formal-note",
            })
            coverage["branches_applied"].append("formal-note")
            path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            (target / "evidence" / "coverage.md").write_text(
                MODULE.render_coverage(coverage), encoding="utf-8"
            )
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_dimension_extension_requires_its_declared_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "coverage.json"
            coverage = json.loads(path.read_text(encoding="utf-8"))
            next(
                item for item in coverage["dimensions"]
                if item["id"] == "reproducibility-documentation"
            )["branch"] = "prediction-ml"
            path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("undeclared branches: prediction-ml" in error for error in errors), errors)

    def test_not_applicable_dimension_requires_source_specific_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "coverage.json"
            coverage = json.loads(path.read_text(encoding="utf-8"))
            row = next(
                item for item in coverage["dimensions"]
                if item["id"] == "reproducibility-documentation"
            )
            row.update({"status": "not_applicable", "finding_ids": [], "notes": ""})
            path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires a source-specific reason" in error for error in errors), errors)

    def test_claims_scope_must_cover_every_manuscript_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["audit_scope"]["coverage_unit_ids"] = ["missing-unit"]
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("claims audit scope omits coverage units" in error for error in errors))

    def test_claims_v02_requires_all_argument_coverage_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "coverage.json"
            coverage = json.loads(path.read_text(encoding="utf-8"))
            coverage["dimensions"] = [
                row for row in coverage["dimensions"]
                if row["id"] != "cross-result-coherence"
            ]
            path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "coverage is missing argument dimensions" in error
                and "cross-result-coherence" in error
                for error in errors
            ))

    def test_clear_and_convincing_reader_map_rejects_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["reader_map"][0]["status"] = "clear_and_convincing"
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "clean reader-map state main-result" in error for error in errors
            ))

    def test_legacy_claims_v01_remains_validator_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            convert_fixture_to_contract_v02(target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["schema_version"] = "0.1"
            claims.pop("argument_audit")
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(MODULE.validate_review(target), [])

    def test_current_v04_full_review_requires_claims_v02(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["schema_version"] = "0.1"
            claims.pop("argument_audit")
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "v0.4 full review requires evidence/claims.json schema_version 0.2" in error
                for error in errors
            ))

    def test_adverse_economic_argument_link_requires_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["argument_audit"]["economic_links"][0]["finding_ids"] = []
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "adverse economic argument link state ARG-01" in error
                for error in errors
            ))

    def test_convincing_economic_argument_link_rejects_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["argument_audit"]["economic_links"][0]["status"] = "convincing"
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "clean economic argument link state ARG-01" in error
                for error in errors
            ))

    def test_claim_scoped_argument_row_requires_finding_claim_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            row = claims["argument_audit"]["economic_links"][0]
            row["finding_ids"] = ["WRT-01"]
            row["evidence_refs"] = [{"kind": "finding_evidence", "id": "EVD-WRT-01-A"}]
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            next(
                item for item in coverage["dimensions"]
                if item["id"] == "economic-argument-chain"
            )["finding_ids"] = ["WRT-01"]
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "maps finding WRT-01 without an overlapping claim family" in error
                for error in errors
            ))

    def test_central_argument_cannot_be_convincing_with_adverse_headline_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["central_argument_assessment"]["status"] = "convincing"
            claims["central_argument_assessment"]["finding_ids"] = []
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "conflicts with an adverse headline argument finding" in error
                for error in errors
            ))

    def test_central_argument_must_include_adverse_headline_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["central_argument_assessment"]["finding_ids"] = []
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "omits adverse headline argument findings: LOGIC-01" in error
                for error in errors
            ))

    def test_argument_audit_must_cover_every_headline_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["argument_audit"]["economic_links"][0]["headline_claim_ids"] = ["CLM-99"]
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("unknown claim family CLM-99" in error for error in errors))
            self.assertTrue(any("omits headline claims: CLM-01" in error for error in errors))

    def test_unexplained_evidence_object_omission_requires_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            row = claims["argument_audit"]["evidence_objects"][0]
            row["status"] = "unexplained_omission"
            row["finding_ids"] = []
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "adverse evidence object state OBJ-01" in error for error in errors
            ))

    def test_argument_audit_rejects_review_process_meta_prose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["argument_audit"]["economic_links"][0]["discriminating_evidence"] = (
                "The paper-specific review found the relevant issue."
            )
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "field discriminating_evidence needs paper-specific content" in error
                for error in errors
            ))

    def test_argument_audit_rejects_unknown_canonical_evidence_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["argument_audit"]["economic_links"][0]["evidence_refs"] = [
                {"kind": "anchor", "id": "ANC-99"}
            ]
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "unknown canonical evidence anchor:ANC-99" in error for error in errors
            ))

    def test_argument_audit_evidence_must_support_its_mapped_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["argument_audit"]["economic_links"][0]["evidence_refs"] = [
                {"kind": "anchor", "id": "ANC-02"}
            ]
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "ARG-01 evidence does not support mapped finding LOGIC-01" in error
                for error in errors
            ))

    def test_clean_argument_row_must_be_anchored_to_its_claim_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["argument_audit"]["evidence_objects"][0]["evidence_refs"] = [
                {"kind": "anchor", "id": "ANC-02"}
            ]
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "OBJ-01 evidence is not anchored to claim family CLM-01" in error
                for error in errors
            ), errors)

    def test_claim_family_anchor_must_be_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["claim_families"][0]["anchor_ids"] = ["ANC-99"]
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "claim family CLM-01 references unknown canonical anchor ANC-99" in error
                for error in errors
            ), errors)

    def test_v02_claim_family_requires_precise_anchor_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["claim_families"][0].pop("anchor_ids")
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "anchor_ids" in error and "schema violation" in error
                for error in errors
            ), errors)

    def test_v02_evidence_object_requires_claim_family_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["argument_audit"]["evidence_objects"][0].pop("claim_ids")
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "claim_ids" in error and "schema violation" in error
                for error in errors
            ), errors)

    def test_claim_family_cannot_use_a_whole_source_scope_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["claim_families"][0]["anchor_ids"] = ["ANC-03"]
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "must use a precise claim anchor, not scope anchor ANC-03" in error
                for error in errors
            ), errors)

    def test_bounded_headline_argument_propagates_to_central_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            claims_path = target / "evidence" / "claims.json"
            claims = json.loads(claims_path.read_text(encoding="utf-8"))
            row = claims["argument_audit"]["economic_links"][0]
            row["status"] = "bounded"
            row["boundary"] = {
                "checked_scope": "The complete displayed payoff comparison and its stated parameter domain.",
                "status_basis": "unavailable_input",
                "reason": "The manuscript does not state the selection rule needed to assess uniqueness at equality.",
                "missing_input": "The equilibrium selection or tie-breaking rule at equality.",
                "decisive_evidence_needed": "A stated and justified rule that selects one action when payoffs coincide.",
                "evidence_refs": [{"kind": "anchor", "id": "ANC-03"}],
            }
            claims_path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            next(
                item for item in coverage["dimensions"]
                if item["id"] == "economic-argument-chain"
            )["status"] = "bounded"
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "bounded headline argument audit requires a bounded central_argument_assessment"
                in error for error in errors
            ), errors)

    def test_bounded_argument_row_requires_collection_and_coverage_parity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            row = claims["argument_audit"]["transport_assessments"]["entries"][0]
            row["status"] = "bounded"
            row["boundary"] = {
                "checked_scope": "The proposition's complete stated parameter domain.",
                "status_basis": "unavailable_input",
                "reason": "The selection rule at equality is unavailable.",
                "missing_input": "A selection rule at equality.",
                "decisive_evidence_needed": "A rule that establishes the target-domain result.",
                "evidence_refs": [{"kind": "anchor", "id": "ANC-03"}],
            }
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "bounded transport assessment row requires bounded coverage dimension population-claim-transport"
                in error for error in errors
            ), errors)
            self.assertTrue(any(
                "bounded transport assessment row requires a bounded collection status"
                in error for error in errors
            ), errors)

    def test_adverse_transport_of_headline_claim_reaches_central_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            claims_path = target / "evidence" / "claims.json"
            claims = json.loads(claims_path.read_text(encoding="utf-8"))
            economic = claims["argument_audit"]["economic_links"][0]
            economic["status"] = "convincing"
            economic["finding_ids"] = []
            economic["evidence_refs"] = [{"kind": "anchor", "id": "ANC-01"}]
            claims["central_argument_assessment"]["status"] = "convincing"
            claims["central_argument_assessment"]["finding_ids"] = []
            claims_path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            next(
                item for item in coverage["dimensions"]
                if item["id"] == "economic-argument-chain"
            )["finding_ids"] = []
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "central_argument_assessment omits adverse headline argument findings: LOGIC-01"
                in error for error in errors
            ), errors)
            self.assertTrue(any(
                "conflicts with an adverse headline argument finding" in error
                for error in errors
            ), errors)

    def test_argument_audit_requires_explicit_alternative_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["argument_audit"]["economic_links"][0].pop("alternative_assessment")
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "alternative_assessment" in error and "schema violation" in error
                for error in errors
            ))

    def test_not_applicable_argument_collection_requires_structured_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["argument_audit"]["comparison_protocols"].pop("boundary")
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "boundary" in error and "schema violation" in error for error in errors
            ))

    def test_empty_bounded_argument_collection_names_missing_and_decisive_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            claims_path = target / "evidence" / "claims.json"
            claims = json.loads(claims_path.read_text(encoding="utf-8"))
            collection = claims["argument_audit"]["comparison_protocols"]
            collection["status"] = "bounded"
            collection["boundary"].update({
                "status_basis": "unavailable_input",
                "missing_input": None,
                "decisive_evidence_needed": None,
            })
            claims_path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            row = next(
                item for item in coverage["dimensions"]
                if item["id"] == "intervention-comparison-content"
            )
            row["status"] = "bounded"
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "requires a concrete missing_input" in error for error in errors
            ))
            self.assertTrue(any(
                "requires decisive_evidence_needed" in error for error in errors
            ))

    def test_full_review_requires_separate_figure_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "evidence" / "figures.json").unlink()
            errors = MODULE.validate_review(target)
            self.assertTrue(any("evidence/figures.json" in error for error in errors))

    def test_v02_figure_asset_binding_passes_when_identity_page_and_hash_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_v02_happy_figure_asset_has_an_inspectable_visual_canvas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            asset = target / "evidence" / "renders" / "pages" / "page-04.png"
            with Image.open(asset) as retained:
                self.assertGreaterEqual(retained.width, 500)
                self.assertGreaterEqual(retained.height, 300)
                extrema = retained.convert("RGB").getextrema()
            self.assertTrue(all(low < high for low, high in extrema))

    def test_v02_pdf_figure_asset_joins_canonical_ingestion_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            declare_synthetic_pdf_render_index(target)
            with mock.patch.object(MODULE, "validate_trust_spine", return_value=[]):
                self.assertEqual(MODULE.validate_review(target), [])

    def test_v02_pdf_figure_rejects_self_attested_copy_of_canonical_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            declare_synthetic_pdf_render_index(target)
            canonical = target / "evidence" / "renders" / "pages" / "page-04.png"
            copied = target / "evidence" / "renders" / "pages" / "claimed-page-04.png"
            copied.write_bytes(canonical.read_bytes())
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            figures["figures"][0]["rendered_assets"][0]["path"] = (
                "evidence/renders/pages/claimed-page-04.png"
            )
            figures_path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            with mock.patch.object(MODULE, "validate_trust_spine", return_value=[]):
                errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "is not a canonical full_page asset from PDF ingestion" in error
                for error in errors
            ), errors)

    def test_v02_pdf_figure_rejects_page_number_not_in_ingestion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            declare_synthetic_pdf_render_index(target)
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            figures["figures"][0]["pdf_pages"] = [999]
            figures["figures"][0]["rendered_assets"][0]["pdf_page"] = 999
            figures_path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            with mock.patch.object(MODULE, "validate_trust_spine", return_value=[]):
                errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "page 999 differs from canonical PDF ingestion page 4" in error
                for error in errors
            ), errors)

    def test_v02_pdf_figure_crop_joins_canonical_ingestion_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            page = target / "evidence" / "renders" / "pages" / "page-04.png"
            canonical_crop = target / "evidence" / "pdf-ingestion" / "SRC-01" / "objects" / "figures" / "fig-001.png"
            canonical_crop.parent.mkdir(parents=True, exist_ok=True)
            canonical_crop.write_bytes(page.read_bytes())
            canonical_crop_path = (
                "evidence/pdf-ingestion/SRC-01/objects/figures/fig-001.png"
            )
            declare_synthetic_pdf_render_index(target, crop_path=canonical_crop_path)
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            figures["figures"][0]["identity_keys"].append("Outcome")
            figures["figures"][0]["rendered_assets"].append({
                "path": canonical_crop_path,
                "sha256": hashlib.sha256(canonical_crop.read_bytes()).hexdigest(),
                "pdf_page": 4,
                "render_type": "crop",
                "source_object_id": "SRC-01-PDF-FIG-001",
                "visible_identity": {
                    "basis": "panel_or_axis_text",
                    "text": "Outcome",
                    "status": "matched",
                    "notes": "The canonical crop contains the figure's outcome axis.",
                },
            })
            figures_path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            with mock.patch.object(MODULE, "validate_trust_spine", return_value=[]):
                self.assertEqual(MODULE.validate_review(target), [])

            copied_crop = target / "evidence" / "figures" / "claimed-crop.png"
            copied_crop.parent.mkdir(parents=True, exist_ok=True)
            copied_crop.write_bytes(canonical_crop.read_bytes())
            figures["figures"][0]["rendered_assets"][1]["path"] = (
                "evidence/figures/claimed-crop.png"
            )
            figures_path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            with mock.patch.object(MODULE, "validate_trust_spine", return_value=[]):
                errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "path does not match canonical figure object SRC-01-PDF-FIG-001" in error
                for error in errors
            ), errors)

    def test_v02_pdf_crop_cannot_bind_a_different_ingestion_object_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            page = target / "evidence" / "renders" / "pages" / "page-04.png"
            crop_one_path = (
                "evidence/pdf-ingestion/SRC-01/objects/figures/fig-001.png"
            )
            crop_two_path = (
                "evidence/pdf-ingestion/SRC-01/objects/figures/fig-002.png"
            )
            for relative in (crop_one_path, crop_two_path):
                crop = target / relative
                crop.parent.mkdir(parents=True, exist_ok=True)
                crop.write_bytes(page.read_bytes())
            declare_synthetic_pdf_render_index(target, crop_path=crop_one_path)

            ingestion_path = (
                target / "evidence" / "pdf-ingestion" / "SRC-01" / "ingestion.json"
            )
            ingestion = json.loads(ingestion_path.read_text(encoding="utf-8"))
            ingestion["figures"].append({
                "id": "SRC-01-PDF-FIG-002",
                "page": 4,
                "crop_path": crop_two_path,
                "crop_sha256": hashlib.sha256((target / crop_two_path).read_bytes()).hexdigest(),
            })
            ingestion_bytes = json.dumps(ingestion, indent=2).encode("utf-8") + b"\n"
            ingestion_path.write_bytes(ingestion_bytes)
            source_path = target / "evidence" / "source-manifest.json"
            source_manifest = json.loads(source_path.read_text(encoding="utf-8"))
            source_manifest["sources"][0]["extraction"]["ingestion_manifest_sha256"] = (
                hashlib.sha256(ingestion_bytes).hexdigest()
            )
            source_path.write_text(
                json.dumps(source_manifest, indent=2) + "\n", encoding="utf-8"
            )

            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            row = figures["figures"][0]
            row["identity_keys"].append("Outcome")
            row["rendered_assets"].append({
                "path": crop_one_path,
                "sha256": hashlib.sha256((target / crop_one_path).read_bytes()).hexdigest(),
                "pdf_page": 4,
                "render_type": "crop",
                "source_object_id": "SRC-01-PDF-FIG-002",
                "visible_identity": {
                    "basis": "panel_or_axis_text",
                    "text": "Outcome",
                    "status": "matched",
                    "notes": "The crop is deliberately bound to the other object identifier.",
                },
            })
            figures_path.write_text(
                json.dumps(figures, indent=2) + "\n", encoding="utf-8"
            )
            refresh_finalization_receipt(target)
            with mock.patch.object(MODULE, "validate_trust_spine", return_value=[]):
                errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "path does not match canonical figure object SRC-01-PDF-FIG-002" in error
                for error in errors
            ), errors)

    def test_v02_figure_asset_rejects_semantically_shifted_visible_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            path = target / "evidence" / "figures.json"
            figures = json.loads(path.read_text(encoding="utf-8"))
            figures["figures"][0]["rendered_assets"][0]["visible_identity"]["text"] = (
                "Figure 10: A different visual object"
            )
            path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "matched visible identity is not linked" in error
                for error in errors
            ))

    def test_v02_figure_asset_rejects_stale_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            path = target / "evidence" / "figures.json"
            figures = json.loads(path.read_text(encoding="utf-8"))
            figures["figures"][0]["rendered_assets"][0]["sha256"] = "0" * 64
            path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("SHA-256 does not match" in error for error in errors))

    def test_v02_figures_may_share_one_immutable_full_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)

            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage["units"].append({
                "id": "U-FIG-02",
                "source_id": "SRC-01",
                "anchor_ids": ["ANC-04"],
                "type": "figure",
                "label": "Figure 2: Second synthetic relationship",
                "status": "checked_no_issue",
                "finding_ids": [],
                "notes": "A second figure appears on the same rendered PDF page.",
            })
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")

            for relative in ("claims.json", "analytical-audit.json", "writing.json"):
                path = target / "evidence" / relative
                payload = json.loads(path.read_text(encoding="utf-8"))
                scope = payload["audit_scope"] if relative == "claims.json" else payload["scope"]
                scope["coverage_unit_ids"].append("U-FIG-02")
                path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            for burden_id in ("figure_integrity", "exhibit_integrity"):
                next(
                    row for row in coverage["burden_audits"]
                    if row["burden_id"] == burden_id
                )["coverage_unit_ids"].append("U-FIG-02")
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")

            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            second = json.loads(json.dumps(figures["figures"][0]))
            second["id"] = "FIG-02"
            second["coverage_unit_id"] = "U-FIG-02"
            second["label"] = "Figure 2: Second synthetic relationship"
            second["rendered_assets"][0]["visible_identity"]["text"] = (
                "Figure 2: Second synthetic relationship"
            )
            figures["figures"].append(second)
            figures_path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            declare_synthetic_pdf_render_index(target)
            refresh_finalization_receipt(target)
            with mock.patch.object(MODULE, "validate_trust_spine", return_value=[]):
                self.assertEqual(MODULE.validate_review(target), [])

    def test_immutable_earlier_v04_receipt_remains_validator_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)

            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["schema_version"] = "0.1"
            receipt["gates"].remove("structured_audit_v02")
            receipt["gates"].remove("burden_coverage_v02")
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

            claims_path = target / "evidence" / "claims.json"
            claims = json.loads(claims_path.read_text(encoding="utf-8"))
            claims["schema_version"] = "0.1"
            claims.pop("argument_audit")
            claims_path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")

            analytical_path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(analytical_path.read_text(encoding="utf-8"))
            analytical["schema_version"] = "0.1"
            for domain in analytical["domains"]:
                for entry in domain["entries"]:
                    entry.pop("evidence_refs", None)
                    for locator in entry["evidence_locators"]:
                        locator.pop("coverage_unit_id", None)
                        locator.pop("anchor_id", None)
                        locator.pop("representation", None)
            analytical_path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")

            external_path = target / "evidence" / "external-sources.json"
            external = json.loads(external_path.read_text(encoding="utf-8"))
            external["schema_version"] = "0.1"
            external.pop("frontier_audit", None)
            external_path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")

            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_immutable_full_v04_receipt_v02_does_not_require_new_execution_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)

            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["schema_version"] = "0.2"
            receipt["gates"] = [
                gate for gate in receipt["gates"]
                if gate != "burden_coverage_v02"
            ]
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            for field in (
                "requested_mode",
                "delivered_mode",
                "mode_transition",
                "transition_reason",
                "transition_source_review_id",
                "finding_granularity",
                "provenance",
            ):
                run.pop(field, None)
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertEqual(errors, [])

    def test_current_receipt_gate_removal_does_not_bypass_v02_audits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["gates"].remove("structured_audit_v02")
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            claims_path = target / "evidence" / "claims.json"
            claims = json.loads(claims_path.read_text(encoding="utf-8"))
            claims["schema_version"] = "0.1"
            claims.pop("argument_audit")
            claims_path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "requires evidence/claims.json schema_version 0.2" in error
                for error in errors
            ))
            self.assertTrue(any(
                "missing required gates: structured_audit_v02" in error for error in errors
            ))

    def test_v02_figure_title_identity_key_is_not_forced_to_repeat_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            path = target / "evidence" / "figures.json"
            figures = json.loads(path.read_text(encoding="utf-8"))
            identity = figures["figures"][0]["rendered_assets"][0]["visible_identity"]
            identity["basis"] = "caption_or_title"
            identity["text"] = "Synthetic relationship"
            path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertFalse(any("figure FIG-01" in error for error in errors), errors)

    def test_v02_non_pdf_figure_does_not_require_fictional_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            path = target / "evidence" / "figures.json"
            figures = json.loads(path.read_text(encoding="utf-8"))
            row = figures["figures"][0]
            row["pdf_pages"] = []
            row["rendered_assets"][0]["pdf_page"] = None
            row["source_locator"] = {
                "source_id": "SRC-01",
                "pages": [],
                "context": "Embedded figure in the Markdown manuscript.",
            }
            path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_v02_structured_source_locator_pages_must_match_row_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            path = target / "evidence" / "figures.json"
            figures = json.loads(path.read_text(encoding="utf-8"))
            figures["figures"][0]["source_locator"]["pages"] = [99]
            path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "source locator pages [99] differ from declared pages [4]" in error
                for error in errors
            ), errors)

    def test_v02_bounded_visual_identity_uses_boundary_without_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            row = figures["figures"][0]
            row["visual_status"] = "bounded"
            row["rendered_assets"][0]["visible_identity"].update({
                "status": "bounded",
                "notes": "The retained page is legible, but the figure label is cropped.",
            })
            row["assessment_boundary"] = {
                "checked_scope": "The retained full page and surrounding caption were opened.",
                "status_basis": "ambiguous_visual_identity",
                "reason": "The visible crop omits the discriminating panel label.",
                "missing_input": "A complete render containing the panel label.",
                "decisive_evidence_needed": "A new full-page render with the label visible.",
            }
            figures_path.write_text(
                json.dumps(figures, indent=2) + "\n", encoding="utf-8"
            )
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            figure_unit = next(
                unit for unit in coverage["units"] if unit["id"] == "U-FIG-01"
            )
            figure_unit["status"] = "bounded"
            figure_unit["notes"] = "Visual identity is bounded by the incomplete render."
            coverage_path.write_text(
                json.dumps(coverage, indent=2) + "\n", encoding="utf-8"
            )
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_v02_bounded_visual_identity_requires_structured_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            row = figures["figures"][0]
            row["visual_status"] = "bounded"
            row["rendered_assets"][0]["visible_identity"]["status"] = "bounded"
            figures_path.write_text(
                json.dumps(figures, indent=2) + "\n", encoding="utf-8"
            )
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "bounded figure FIG-01 requires a structured assessment_boundary" in error
                for error in errors
            ), errors)

    def test_v02_mismatched_visual_identity_remains_adverse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            row = figures["figures"][0]
            row["visual_status"] = "issue"
            row["rendered_assets"][0]["visible_identity"].update({
                "status": "mismatch",
                "text": "Figure 2: A different object",
                "notes": "The retained page visibly belongs to another figure.",
            })
            figures_path.write_text(
                json.dumps(figures, indent=2) + "\n", encoding="utf-8"
            )
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "mismatched figure asset identity for FIG-01 must map to an active finding"
                in error for error in errors
            ), errors)

    def test_v02_figure_row_label_must_reconcile_with_coverage_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            path = target / "evidence" / "figures.json"
            figures = json.loads(path.read_text(encoding="utf-8"))
            row = figures["figures"][0]
            row["label"] = "Figure 2: A shifted visual object"
            row["identity_keys"] = ["Figure 2", "Shifted visual object"]
            row["rendered_assets"][0]["visible_identity"]["text"] = (
                "Figure 2: A shifted visual object"
            )
            path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("not reconciled with coverage unit" in error for error in errors))

    def test_v02_matched_crop_identity_must_use_a_row_identity_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            source = target / "evidence" / "renders" / "pages" / "page-04.png"
            crop = target / "evidence" / "figures" / "shifted.png"
            crop.parent.mkdir(parents=True, exist_ok=True)
            crop.write_bytes(source.read_bytes())
            path = target / "evidence" / "figures.json"
            figures = json.loads(path.read_text(encoding="utf-8"))
            figures["figures"][0]["rendered_assets"].append({
                "path": "evidence/figures/shifted.png",
                "sha256": hashlib.sha256(crop.read_bytes()).hexdigest(),
                "pdf_page": 4,
                "render_type": "crop",
                "source_object_id": None,
                "visible_identity": {
                    "basis": "panel_or_axis_text",
                    "text": "Unrelated outcome and comparison group",
                    "status": "matched",
                    "notes": "The declared cue does not belong to this figure row.",
                },
            })
            path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("matched visible identity is not linked" in error for error in errors))

    def test_v02_truncated_render_fails_complete_image_decode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            asset = target / "evidence" / "renders" / "pages" / "page-04.png"
            asset.write_bytes(b"\x89PNG\r\n\x1a\n")
            path = target / "evidence" / "figures.json"
            figures = json.loads(path.read_text(encoding="utf-8"))
            figures["figures"][0]["rendered_assets"][0]["sha256"] = hashlib.sha256(
                asset.read_bytes()
            ).hexdigest()
            path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("cannot be decoded as a complete image" in error for error in errors))

    def test_v02_nonportable_path_fails_without_validator_exception(self) -> None:
        for unsafe_path in ("\x00.png", "evidence/NUL.png", "evidence/e\u0301.png"):
            with self.subTest(path=unsafe_path), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                add_valid_v02_figure(target)
                path = target / "evidence" / "figures.json"
                figures = json.loads(path.read_text(encoding="utf-8"))
                figures["figures"][0]["rendered_assets"][0]["path"] = unsafe_path
                path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
                refresh_finalization_receipt(target)
                errors = MODULE.validate_review(target)
                self.assertTrue(errors)
                self.assertTrue(any(
                    "portable review-relative path" in error for error in errors
                ))

    @unittest.skipIf(os.name == "nt", "symlink creation is privilege-dependent on Windows")
    def test_v02_asset_safe_read_failure_is_not_silently_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            link = target / "evidence" / "renders" / "pages" / "linked-page.png"
            link.symlink_to("page-04.png")
            path = target / "evidence" / "figures.json"
            figures = json.loads(path.read_text(encoding="utf-8"))
            figures["figures"][0]["rendered_assets"][0]["path"] = (
                "evidence/renders/pages/linked-page.png"
            )
            path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "figure FIG-01 rendered asset 1 path cannot be read safely" in error
                for error in errors
            ))

    def test_v02_canonical_path_alias_is_rejected_before_crop_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            source = target / "evidence" / "renders" / "pages" / "page-04.png"
            crop = target / "evidence" / "figures" / "crop.png"
            crop.parent.mkdir(parents=True, exist_ok=True)
            crop.write_bytes(source.read_bytes())
            digest = hashlib.sha256(crop.read_bytes()).hexdigest()
            path = target / "evidence" / "figures.json"
            figures = json.loads(path.read_text(encoding="utf-8"))
            row = figures["figures"][0]
            row["identity_keys"].append("Outcome")
            for asset_path in ("evidence/figures/crop.png", "evidence/figures/./crop.png"):
                row["rendered_assets"].append({
                    "path": asset_path,
                    "sha256": digest,
                    "pdf_page": 4,
                    "render_type": "crop",
                    "source_object_id": None,
                    "visible_identity": {
                        "basis": "panel_or_axis_text",
                        "text": "Outcome",
                        "status": "matched",
                        "notes": "The crop is deliberately repeated through a path alias.",
                    },
                })
            path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "canonical portable review-relative path" in error for error in errors
            ), errors)

    def test_checked_clean_figure_cannot_map_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_valid_v02_figure(target)
            path = target / "evidence" / "figures.json"
            figures = json.loads(path.read_text(encoding="utf-8"))
            figures["figures"][0]["finding_ids"] = ["LOGIC-01"]
            path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("checked-clean figure FIG-01" in error for error in errors))

    def test_v01_no_figures_cannot_contradict_figure_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage["units"].append({
                "id": "U-FIG-LEGACY",
                "type": "figure",
                "label": "Figure 1: Legacy figure",
                "status": "checked_no_issue",
                "finding_ids": [],
                "notes": "The coverage inventory records a rendered figure.",
            })
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            for relative in ("claims.json", "analytical-audit.json"):
                scope_path = target / "evidence" / relative
                payload = json.loads(scope_path.read_text(encoding="utf-8"))
                scope = payload["audit_scope"] if relative == "claims.json" else payload["scope"]
                scope["coverage_unit_ids"].append("U-FIG-LEGACY")
                scope_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "cannot confirm no figures when coverage contains figure units" in error
                for error in errors
            ))

    def test_figure_free_v3_run_must_record_not_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["assessment_boundary"]["figures"] = "not_assessed"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("must be 'not_present'" in error for error in errors))

    def test_full_review_requires_writing_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "evidence" / "writing.json").unlink()
            errors = MODULE.validate_review(target)
            self.assertTrue(any("evidence/writing.json" in error for error in errors))

    def test_full_review_requires_rendered_table_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "evidence" / "tables.json").unlink()
            errors = MODULE.validate_review(target)
            self.assertTrue(any("evidence/tables.json" in error for error in errors))

    def test_full_review_requires_analytical_ledgers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "evidence" / "analytical-audit.json").unlink()
            errors = MODULE.validate_review(target)
            self.assertTrue(any("evidence/analytical-audit.json" in error for error in errors))

    def test_adverse_analytical_entry_requires_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            entry = next(domain for domain in analytical["domains"] if domain["kind"] == "timing-test")["entries"][0]
            entry["status"] = "issue"
            entry["checks"][0]["status"] = "issue"
            entry["finding_ids"] = []
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("adverse analytical entry ANA-TIM-01" in error for error in errors))

    def test_analytical_scope_must_match_source_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            analytical["scope"]["coverage_unit_ids"] = ["missing-unit"]
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("analytical audit scope omits coverage units" in error for error in errors))

    def test_analytical_v02_locator_requires_locator_level_record_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "timing-test")
            domain["entries"][0]["evidence_locators"][0].pop("record_ref")
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "requires a locator-level canonical record_ref" in error for error in errors
            ), errors)

    def test_analytical_v02_locator_reconciles_source_and_locator_to_record(self) -> None:
        for field, value, expected in (
            ("source", "wrong-source.md", "source does not match anchor ANC-01"),
            ("locator", "Section 99", "locator does not match anchor ANC-01"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                path = target / "evidence" / "analytical-audit.json"
                analytical = json.loads(path.read_text(encoding="utf-8"))
                domain = next(
                    row for row in analytical["domains"] if row["kind"] == "timing-test"
                )
                domain["entries"][0]["evidence_locators"][0][field] = value
                path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
                errors = MODULE.validate_review(target)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_analytical_v02_locator_requires_known_source_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "timing-test")
            entry = domain["entries"][0]
            entry["evidence_refs"] = [{"kind": "anchor", "id": "ANC-99"}]
            entry["evidence_locators"][0]["anchor_id"] = "ANC-99"
            entry["evidence_locators"][0]["record_ref"] = {
                "kind": "anchor", "id": "ANC-99",
            }
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "references unknown canonical record anchor:ANC-99" in error
                for error in errors
            ))

    def test_analytical_v02_locator_must_match_entry_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "measure-algebra")
            domain["entries"][0]["evidence_locators"][0]["coverage_unit_id"] = "elsewhere"
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "must resolve to one of the entry's coverage units" in error
                for error in errors
            ))

    def test_analytical_v02_rejects_fabricated_verbatim_locator_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "timing-test")
            locator = domain["entries"][0]["evidence_locators"][0]
            locator.update({
                "source": "synthetic-paper.md",
                "representation": "verbatim",
                "content": "Fabricated text at a real anchor.",
            })
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "is not verbatim at canonical record anchor:ANC-01" in error
                for error in errors
            ))

    def test_analytical_v02_evidence_must_support_mapped_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "measure-algebra")
            entry = domain["entries"][0]
            entry["evidence_refs"] = [{"kind": "anchor", "id": "ANC-02"}]
            entry["evidence_locators"][0].update({
                "source": "synthetic-paper.md",
                "locator": "Section 3, paragraph 2",
                "content": "The proposition characterize the model's comparative static.",
                "anchor_id": "ANC-02",
                "representation": "verbatim",
                "record_ref": {"kind": "anchor", "id": "ANC-02"},
            })
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "ANA-MEA-01 evidence does not support mapped finding LOGIC-01" in error
                for error in errors
            ))

    def test_analytical_v02_computed_result_requires_known_computation_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "timing-test")
            entry = domain["entries"][0]
            entry["evidence_refs"] = [{"kind": "computation", "id": "CMP-99"}]
            locator = entry["evidence_locators"][0]
            locator.update({
                "source": "evidence/computations.json",
                "locator": "CMP-99",
                "content": "A synthetic calculation result.",
                "representation": "computed_result",
                "anchor_id": None,
                "record_ref": {"kind": "computation", "id": "CMP-99"},
            })
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "references unknown canonical record computation:CMP-99" in error
                for error in errors
            ))

    def test_clean_audit_only_computation_may_link_to_analytical_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_audit_only_computation(
                target,
                audit_link={"kind": "analytical_entry", "id": "ANA-TIM-01"},
            )
            bind_computation_to_analytical_entry(target)
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_computed_result_content_must_match_canonical_computation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_audit_only_computation(
                target,
                audit_link={"kind": "analytical_entry", "id": "ANA-TIM-01"},
            )
            bind_computation_to_analytical_entry(target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "timing-test")
            domain["entries"][0]["evidence_locators"][0]["content"] = (
                "A result that the computation record does not report."
            )
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "content does not match computation CMP-01 result" in error
                for error in errors
            ), errors)

    def test_audit_only_computation_rejects_nonreciprocal_analytical_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_audit_only_computation(
                target,
                audit_link={"kind": "analytical_entry", "id": "ANA-TIM-01"},
            )
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "computation CMP-01 audit links are not reciprocal" in error
                for error in errors
            ), errors)
            self.assertTrue(any(
                "audit-only computation CMP-01 is orphaned" in error for error in errors
            ), errors)

    def test_clean_audit_only_computation_may_link_to_magnitude_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_audit_only_computation(
                target,
                audit_link={"kind": "magnitude_assessment", "id": "MAG-01"},
            )
            bind_computation_to_magnitude_assessment(target)
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_analytical_checked_absence_resolves_to_canonical_scope_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            manifest_path = target / "evidence" / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["anchors"][0]["kind"] = "scope"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "timing-test")
            locator = domain["entries"][0]["evidence_locators"][0]
            locator["representation"] = "checked_absence"
            locator["content"] = (
                "[Checked absence] No dynamic timing claim appears within the checked proposition span."
            )
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertFalse(any(
                "checked_absence" in error and "ANA-TIM-01" in error
                for error in errors
            ), errors)

    def test_legacy_analytical_v01_remains_validator_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            convert_fixture_to_contract_v02(target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            analytical["schema_version"] = "0.1"
            for domain in analytical["domains"]:
                for entry in domain["entries"]:
                    for locator in entry["evidence_locators"]:
                        locator.pop("coverage_unit_id")
                        locator.pop("anchor_id")
                        locator.pop("representation")
                        locator.pop("record_ref")
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(MODULE.validate_review(target), [])

    def test_current_v04_full_review_requires_analytical_v02(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            analytical["schema_version"] = "0.1"
            for domain in analytical["domains"]:
                for entry in domain["entries"]:
                    entry.pop("evidence_refs", None)
                    for locator in entry["evidence_locators"]:
                        locator.pop("coverage_unit_id")
                        locator.pop("anchor_id")
                        locator.pop("representation")
                        locator.pop("record_ref")
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "v0.4 full review requires evidence/analytical-audit.json schema_version 0.2" in error
                for error in errors
            ))

    def test_clear_analytical_entry_rejects_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "timing-test")
            entry = domain["entries"][0]
            entry["finding_ids"] = ["LOGIC-01"]
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            row = next(
                item for item in coverage["dimensions"]
                if item["id"] == "timing-test-semantics"
            )
            row["status"] = "findings"
            row["finding_ids"] = ["LOGIC-01"]
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "clear analytical entry ANA-TIM-01 must not map to an active finding" in error
                for error in errors
            ))

    def test_analytical_domain_status_must_match_coverage_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            row = next(
                item for item in coverage["dimensions"]
                if item["id"] == "timing-test-semantics"
            )
            row["status"] = "not_applicable"
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "analytical domain timing-test status complete conflicts with coverage dimension "
                "timing-test-semantics status not_applicable" in error
                for error in errors
            ))

    def test_complete_analytical_domain_requires_nonempty_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "measure-algebra")
            domain["coverage_unit_ids"] = []
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires a non-empty scope" in error or "schema violation" in error for error in errors))

    def test_analytical_entry_status_must_match_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            entry = next(row for row in analytical["domains"] if row["kind"] == "measure-algebra")["entries"][0]
            entry["checks"][0]["status"] = "clear"
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("issue analytical entry ANA-MEA-01 requires an issue check" in error for error in errors))

    def test_bounded_analytical_entry_propagates_to_domain_and_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "timing-test")
            entry = domain["entries"][0]
            entry["status"] = "bounded"
            entry["checks"][0]["status"] = "bounded"
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "mark both the domain and its coverage dimension bounded" in error
                for error in errors
            ), errors)

    def test_bounded_analytical_entry_accepts_bounded_domain_and_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "timing-test")
            domain["status"] = "bounded"
            entry = domain["entries"][0]
            entry["status"] = "bounded"
            entry["checks"][0]["status"] = "bounded"
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            dimension = next(
                row for row in coverage["dimensions"]
                if row["id"] == "timing-test-semantics"
            )
            dimension.update({
                "status": "bounded",
                "finding_ids": [],
                "notes": "A named unavailable timing input bounds this analytical check.",
            })
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_legacy_analytical_v01_does_not_retroactively_propagate_bounded_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            convert_fixture_to_contract_v02(target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            analytical["schema_version"] = "0.1"
            domain = next(row for row in analytical["domains"] if row["kind"] == "timing-test")
            domain["entries"][0]["status"] = "bounded"
            domain["entries"][0]["checks"][0]["status"] = "bounded"
            for row in analytical["domains"]:
                for entry in row["entries"]:
                    entry.pop("evidence_refs", None)
                    for locator in entry["evidence_locators"]:
                        for field in (
                            "coverage_unit_id", "anchor_id", "representation", "record_ref"
                        ):
                            locator.pop(field, None)
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertFalse(any(
                "mark both the domain and its coverage dimension bounded" in error
                for error in errors
            ), errors)

    def test_analytical_entry_check_ids_must_be_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            entry = next(row for row in analytical["domains"] if row["kind"] == "measure-algebra")["entries"][0]
            entry["checks"].append(json.loads(json.dumps(entry["checks"][0])))
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("analytical entry ANA-MEA-01 repeats checks" in error for error in errors))

    def test_generic_analytical_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            entry = next(row for row in analytical["domains"] if row["kind"] == "measure-algebra")["entries"][0]
            entry["evidence"] = "checked"
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("needs paper-specific evidence" in error for error in errors))

    def test_analytical_meta_boilerplate_fails_in_each_evidence_field(self) -> None:
        cases = (
            (
                "evidence",
                "The constructed measures were traced through the manuscript and rendered exhibits; "
                "the linked findings identify the adverse states and repairs.",
                "needs paper-specific evidence",
            ),
            (
                "locator",
                "The source passages, equations, tables, and figures show the specific objects "
                "summarized in this ledger entry.",
                "needs substantive source content",
            ),
            (
                "result",
                "Paper-specific review found unresolved issues in the constructed measures, mapped "
                "to the complete finding set for this analytical domain.",
                "needs a paper-specific result",
            ),
        )
        for field, boilerplate, expected_error in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                path = target / "evidence" / "analytical-audit.json"
                analytical = json.loads(path.read_text(encoding="utf-8"))
                entry = next(
                    row for row in analytical["domains"] if row["kind"] == "measure-algebra"
                )["entries"][0]
                if field == "evidence":
                    entry["evidence"] = boilerplate
                elif field == "locator":
                    entry["evidence_locators"][0]["content"] = boilerplate
                else:
                    entry["checks"][0]["result"] = boilerplate
                path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")

                errors = MODULE.validate_review(target)
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    msg=f"Expected {field} boilerplate to fail, got: {errors}",
                )

    def test_substantive_analytical_evidence_can_include_a_mapping_note(self) -> None:
        evidence = (
            "Table 4 displays posterior response differences for both reported group contrasts; "
            "the separately derived quantities remain mapped to findings."
        )
        self.assertFalse(MODULE.generic_analytical_text(evidence))

    def test_compact_math_or_theory_evidence_is_not_forced_into_padded_prose(self) -> None:
        for evidence in ("No fixed point", "x*=0", "det(H)<0"):
            with self.subTest(evidence=evidence):
                self.assertFalse(MODULE.generic_analytical_text(evidence))

    def test_source_inventory_summary_is_meta_boilerplate_without_self_reference(self) -> None:
        evidence = (
            "The source passages, equations, tables, and figures show the specific objects "
            "summarized for the completed review."
        )
        self.assertTrue(MODULE.generic_analytical_text(evidence))

    def test_table_checks_are_typed_and_inspected_tables_have_renders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_synthetic_table(target)
            tables = json.loads((target / "evidence" / "tables.json").read_text(encoding="utf-8"))
            self.assertTrue(all(
                row["rendered_assets"] for row in tables["tables"]
                if row["render_status"] == "inspected"
            ))
            broken = json.loads(json.dumps(tables))
            broken["tables"][0]["checks"]["cell_completeness"] = "checked"
            errors: list[str] = []
            MODULE.validate_schema(broken, "tables.schema.json", "tables", errors)
            self.assertTrue(any("cell_completeness" in error for error in errors))

    def test_v02_pdf_table_assets_join_canonical_ingestion_page_and_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_synthetic_table(target)
            bind_synthetic_table_to_pdf(target)
            with mock.patch.object(MODULE, "validate_trust_spine", return_value=[]):
                self.assertEqual(MODULE.validate_review(target), [])

    def test_v02_pdf_table_rejects_self_attested_copy_of_canonical_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_synthetic_table(target)
            bind_synthetic_table_to_pdf(target)
            canonical = target / "evidence" / "renders" / "pages" / "page-01.png"
            copied = canonical.with_name("claimed-page-01.png")
            copied.write_bytes(canonical.read_bytes())
            path = target / "evidence" / "tables.json"
            tables = json.loads(path.read_text(encoding="utf-8"))
            tables["tables"][0]["rendered_assets"][0]["path"] = (
                "evidence/renders/pages/claimed-page-01.png"
            )
            path.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            with mock.patch.object(MODULE, "validate_trust_spine", return_value=[]):
                errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "is not a canonical full_page asset from PDF ingestion" in error
                for error in errors
            ), errors)

    def test_v02_pdf_table_crop_cannot_borrow_another_object_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_synthetic_table(target)
            bind_synthetic_table_to_pdf(target)
            path = target / "evidence" / "tables.json"
            tables = json.loads(path.read_text(encoding="utf-8"))
            tables["tables"][0]["rendered_assets"][1]["source_object_id"] = (
                "SRC-01-PDF-FIG-001"
            )
            path.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            with mock.patch.object(MODULE, "validate_trust_spine", return_value=[]):
                errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "is not a canonical PDF-ingestion table object" in error
                for error in errors
            ), errors)

    def test_v02_pdf_table_binding_rejects_unauthenticated_ingestion_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_synthetic_table(target)
            bind_synthetic_table_to_pdf(target)
            ingestion = target / "evidence" / "pdf-ingestion" / "SRC-01" / "ingestion.json"
            ingestion.write_bytes(ingestion.read_bytes() + b" ")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "ingestion manifest hash mismatch" in error for error in errors
            ), errors)

    def test_v02_pdf_table_requires_full_page_context_for_every_declared_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_synthetic_table(target)
            bind_synthetic_table_to_pdf(target)
            path = target / "evidence" / "tables.json"
            tables = json.loads(path.read_text(encoding="utf-8"))
            tables["tables"][0]["rendered_assets"] = tables["tables"][0]["rendered_assets"][1:]
            path.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            with mock.patch.object(MODULE, "validate_trust_spine", return_value=[]):
                errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "table TBL-01 lacks full-page assets for pages: 1" in error
                for error in errors
            ), errors)

    def test_v02_table_rejects_stale_hash_and_shifted_visible_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_synthetic_table(target)
            path = target / "evidence" / "tables.json"
            tables = json.loads(path.read_text(encoding="utf-8"))
            asset = tables["tables"][0]["rendered_assets"][0]
            asset["sha256"] = "0" * 64
            asset["visible_identity"]["text"] = "Table 10: A different object"
            path.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("SHA-256 does not match" in error for error in errors), errors)
            self.assertTrue(any("matched visible identity is not linked" in error for error in errors), errors)

    def test_v04_populated_table_inventory_rejects_legacy_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_synthetic_table(target)
            path = target / "evidence" / "tables.json"
            tables = json.loads(path.read_text(encoding="utf-8"))
            row = tables["tables"][0]
            legacy = {
                key: value for key, value in row.items()
                if key not in {"source_id", "identity_keys", "rendered_assets", "assessment_boundary"}
            }
            legacy["source_locator"] = "Synthetic rendered page 1"
            legacy["render_paths"] = [row["rendered_assets"][0]["path"]]
            tables["schema_version"] = "0.1"
            tables["tables"] = [legacy]
            path.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "v0.4 full review with tables requires evidence/tables.json schema_version 0.2"
                in error for error in errors
            ), errors)

    def test_complete_review_rejects_bounded_unrendered_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_synthetic_table(target)
            path = target / "evidence" / "tables.json"
            tables = json.loads(path.read_text(encoding="utf-8"))
            tables["tables"][0]["render_status"] = "bounded"
            tables["tables"][0]["visual_status"] = "bounded"
            tables["tables"][0]["rendered_assets"] = []
            path.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires a saved inspected render" in error for error in errors))

    def test_table_cell_evidence_requires_reciprocal_table_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            add_synthetic_table(target, finding_ids=["LOGIC-01"])
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            evidence = ledger["findings"][0]["evidence"][0]
            evidence["type"] = "table_cell"
            evidence["locator"]["exhibit"] = "Table 1: Synthetic boundary cases"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            path = target / "evidence" / "tables.json"
            tables = json.loads(path.read_text(encoding="utf-8"))
            tables["tables"][0]["finding_ids"].remove("LOGIC-01")
            path.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("table-cell evidence for LOGIC-01 is not mapped back" in error for error in errors))

    def test_detailed_comment_boilerplate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8")
            report = report.replace(
                "**Suggestions**:",
                "**Suggestions**: As written,",
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("uses prohibited boilerplate: As written," in error for error in errors))

    def test_detailed_comment_rejects_internal_machine_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "At equality both actions maximize payoff",
                "The canonical record shows that both actions maximize payoff at equality",
                1,
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("uses prohibited boilerplate: canonical record" in error for error in errors),
                errors,
            )

    def test_v3_problem_cannot_open_with_meta_scaffolding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "**Concern**: At equality both actions maximize payoff",
                "**Concern**: The reader needs to understand why both actions maximize payoff at equality",
                1,
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("begins Concern with meta-scaffolding" in error for error in errors))

    def test_v3_near_duplicate_constructive_feedback_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "Add a tie-breaking rule or state a set-valued equilibrium at the boundary. "
                "Align Proposition 1, its proof, and the comparative static.",
                "Add a tie-breaking rule to Proposition 1 and its proof. "
                "Add the same tie-breaking rule to Proposition 1 and its proof text.",
                1,
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("repeats recommendation content" in error for error in errors))

    def test_v3_distinct_steps_on_same_object_are_not_near_duplicates(self) -> None:
        feedback = (
            "Report response rates for every experimental arm and survey wave. "
            "Test whether those response rates differ across arms using the randomized assignment."
        )
        self.assertIsNone(MODULE.near_duplicate_sentence_pair(feedback))

    def test_v3_status_must_be_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8")
            report = report.replace(
                "**Suggestions**:",
                "**Status**: [Pending]\n\n**Suggestions**:",
                1,
            )
            report = report.rsplit("\n\n**Status**: [Pending]", 1)[0] + "\n"
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("fields must appear" in error or "Status last" in error for error in errors))

    def test_v3_accepts_streamlined_comment_without_possible_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_v3_report_posture_must_match_synthesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "**Recommendation**: Not assessed", "**Recommendation**: Accept"
                ),
                encoding="utf-8",
            )
            errors = MODULE.validate_review(target)
            self.assertTrue(any("review posture must match" in error for error in errors))

    def test_unspecified_target_cannot_carry_an_assessed_publication_posture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "synthesis.json"
            synthesis = json.loads(path.read_text(encoding="utf-8"))
            synthesis["review_posture"] = "weak_r_and_r"
            path.write_text(json.dumps(synthesis, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("target venue and tier are unspecified" in error for error in errors), errors)

    def test_v3_malformed_synthesis_collections_fail_without_exception(self) -> None:
        for field, value in (
            ("principal_concerns", None),
            ("other_major_finding_ids", None),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                path = target / "synthesis.json"
                synthesis = json.loads(path.read_text(encoding="utf-8"))
                synthesis[field] = value
                path.write_text(json.dumps(synthesis, indent=2) + "\n", encoding="utf-8")
                errors = MODULE.validate_review(target)
                self.assertTrue(any("synthesis.json" in error for error in errors))

    def test_v3_principal_concern_collection_member_fails_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "synthesis.json"
            synthesis = json.loads(path.read_text(encoding="utf-8"))
            synthesis["principal_concerns"][0]["finding_ids"] = None
            path.write_text(json.dumps(synthesis, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("synthesis.json" in error for error in errors))

    def test_malformed_writing_collections_fail_without_exception(self) -> None:
        def replace(field: str, value: object):
            return lambda writing: writing.__setitem__(field, value)

        def nested(collection: str, field: str, value: object):
            return lambda writing: writing[collection][0].__setitem__(field, value)

        mutations = (
            ("mechanics-null", replace("mechanics", None)),
            ("mechanics-finding-ids-null", nested("mechanics", "finding_ids", None)),
            ("mechanics-status-object", nested("mechanics", "status", {})),
            ("mechanics-occurrences-object", nested("mechanics", "occurrences", {})),
            (
                "mechanics-occurrence-render-object",
                lambda writing: writing["mechanics"][0]["occurrences"][0].__setitem__("render_verification", {}),
            ),
            ("consistency-null", replace("consistency_groups", None)),
            ("consistency-id-object", nested("consistency_groups", "id", {})),
            ("style-member-null", replace("style_suggestions", [None])),
            ("section-audit-null", replace("section_audit", None)),
            ("section-audit-member-null", replace("section_audit", [None])),
            ("redundancy-map-member-null", replace("redundancy_map", [None])),
            ("strengths-null", replace("strengths", None)),
            ("finding-links-null", replace("finding_links", None)),
            ("finding-link-id-object", nested("finding_links", "finding_id", {})),
            ("finding-link-sources-object", nested("finding_links", "sources", [{}])),
            ("highest-return-member-object", replace("highest_return_finding_ids", [{}])),
            ("reference-audit-null", replace("reference_audit", None)),
            ("venue-fit-null", replace("venue_fit", None)),
            (
                "venue-finding-ids-object",
                lambda writing: writing["venue_fit"].__setitem__("finding_ids", [{}]),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                path = target / "evidence" / "writing.json"
                writing = json.loads(path.read_text(encoding="utf-8"))
                mutate(writing)
                path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
                errors = MODULE.validate_review(target)
                self.assertTrue(
                    any("schema violation at evidence/writing.json" in error for error in errors),
                    errors,
                )

    def test_v3_unknown_and_self_dependencies_fail(self) -> None:
        for dependency, expected in (("UNKNOWN-99", "depends on unknown"), ("LOGIC-01", "cannot depend on itself")):
            with self.subTest(dependency=dependency), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                path = target / "findings.json"
                ledger = json.loads(path.read_text(encoding="utf-8"))
                ledger["findings"][0]["fix"]["dependencies"] = [dependency]
                path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
                self.assertTrue(any(expected in error for error in MODULE.validate_review(target)))

    def test_v3_schema_requires_decision_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            del ledger["findings"][0]["decision_role"]
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("schema violation" in error and "decision_role" in error for error in errors))

    def test_major_comment_need_not_repeat_ledger_resolution_condition_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8")
            resolution = json.loads((target / "findings.json").read_text(encoding="utf-8"))["findings"][0]["fix"]["resolved_when"]
            path.write_text(report.replace(resolution, "The revision is complete."), encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_exact_quote_may_be_a_verbatim_subpassage_of_ledger_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "> The equilibrium action is unique for every parameter value.",
                "> equilibrium action is unique for every parameter value.",
            )
            path.write_text(report, encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_quote_with_fabricated_suffix_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "> The equilibrium action is unique for every parameter value.",
                "> The equilibrium action is unique for every parameter value, and the proof is invalid.",
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("evidence does not match ledger evidence" in error for error in errors))

    def test_adverse_writing_mechanics_state_requires_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["mechanics"][0]["status"] = "issue"
            writing["mechanics"][0]["quote"] = "A synthetic error."
            writing["mechanics"][0]["correction"] = "A synthetic correction."
            writing["mechanics"][0]["occurrences"] = [
                {
                    "locator": "Synthetic paragraph",
                    "quote": "A synthetic error.",
                    "correction": "A synthetic correction.",
                }
            ]
            writing["mechanics"][0]["priority"] = "required_copyedit"
            writing["mechanics"][0]["finding_ids"] = []
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("adverse writing-mechanics state WRT-01" in error for error in errors))

    def test_active_writing_finding_requires_reciprocal_writing_audit_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["mechanics"][0]["finding_ids"] = []
            writing["section_audit"][0]["finding_ids"] = []
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("active writing findings missing reciprocal" in error for error in errors))

    def test_checked_clean_writing_row_cannot_map_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            row = writing["mechanics"][0]
            row.update({
                "status": "checked_clean_group",
                "quote": None,
                "correction": None,
                "occurrences": [],
                "priority": "not_applicable",
            })
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("checked-clean writing-mechanics" in error for error in errors))

    def test_writing_v02_link_sources_must_match_issue_bearing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            row = writing["mechanics"][0]
            row.update({
                "status": "checked_clean_group",
                "quote": None,
                "correction": None,
                "occurrences": [],
                "priority": "not_applicable",
                "finding_ids": [],
            })
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("sources do not match issue-bearing audit mappings" in error for error in errors))

    def test_writing_v01_empty_rich_arrays_remain_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["schema_version"] = "0.1"
            for gate in ("structured_audit_v02", "burden_coverage_v02"):
                if gate in receipt["gates"]:
                    receipt["gates"].remove(gate)
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["schema_version"] = "0.1"
            writing["reference_audit"] = legacy_reference_audit()
            writing["strengths"] = []
            writing["section_audit"] = []
            writing.pop("highest_return_finding_ids", None)
            writing.pop("finding_links", None)
            row = writing["mechanics"][0]
            row.update({
                "status": "checked_clean_group",
                "quote": None,
                "correction": None,
                "occurrences": [],
                "priority": "not_applicable",
                "finding_ids": [],
            })
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_complete_reference_audit_must_check_every_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["schema_version"] = "0.2"
            writing["reference_audit"] = legacy_reference_audit()
            writing["reference_audit"]["bibliography_record_count"] = 1
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("complete reference audit must check every bibliography record" in error for error in errors))

    def test_assessed_venue_fit_requires_dated_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["venue_fit"]["status"] = "assessed"
            writing["venue_fit"]["as_of_date"] = None
            writing["venue_fit"]["candidates"] = []
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("assessed venue fit requires at least one candidate journal" in error for error in errors))
            self.assertTrue(any("assessed venue fit requires an as_of_date" in error for error in errors))

    def test_current_venue_schema_requires_https_without_retroactive_legacy_change(self) -> None:
        writing = json.loads((FIXTURE / "evidence" / "writing.json").read_text(encoding="utf-8"))
        writing["venue_fit"].update({
            "status": "assessed",
            "as_of_date": "2024-06-01",
            "candidates": [{
                "journal": "Example Economics Journal",
                "category": "credible_target_after_revision",
                "official_scope_url": "http://example.org/journal/scope",
                "recent_comparator_urls": ["http://example.org/article/1"],
                "fit": "The journal covers the paper's question.",
                "mismatch": "The evidence base remains too narrow.",
                "required_changes": "Strengthen validation before submission.",
                "evidence_date": "2024-05-31",
            }],
        })
        current_errors: list[str] = []
        MODULE.validate_schema(
            writing,
            "writing.schema.json",
            "evidence/writing.json",
            current_errors,
        )
        self.assertTrue(any("does not match '^https://'" in error for error in current_errors), current_errors)

        writing["schema_version"] = "0.3"
        for field in ("assessment_summary", "terminology_summary", "exhibit_summary"):
            writing.pop(field)
        legacy_errors: list[str] = []
        MODULE.validate_schema(
            writing,
            "writing.schema.json",
            "evidence/writing.json",
            legacy_errors,
        )
        self.assertFalse(any("does not match '^https://'" in error for error in legacy_errors), legacy_errors)

    def test_current_venue_semantics_reject_future_assessment_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["requested_addons"] = ["journal_fit"]
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            writing_path = target / "evidence" / "writing.json"
            writing = json.loads(writing_path.read_text(encoding="utf-8"))
            writing["venue_fit"].update({
                "status": "assessed",
                "as_of_date": "9999-12-31",
                "candidates": [{
                    "journal": "Example Economics Journal",
                    "category": "credible_target_after_revision",
                    "official_scope_url": "https://example.org/journal/scope",
                    "recent_comparator_urls": ["https://example.org/article/1"],
                    "fit": "The journal covers the paper's question.",
                    "mismatch": "The evidence base remains too narrow.",
                    "required_changes": "Strengthen validation before submission.",
                    "evidence_date": "2024-05-31",
                }],
            })
            writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "venue_fit.as_of_date cannot be later than the current date" in error
                for error in errors
            ), errors)

    def test_current_writing_report_forbids_reference_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            report_path = target / "editing-comments.md"
            report = report_path.read_text(encoding="utf-8")
            report = report.replace(
                "## Detailed Editing Comments",
                "## References and citation integrity\n\nRoutine reference checks.\n\n## Detailed Editing Comments",
            )
            report_path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("forbids a routine reference" in error for error in errors))

    def test_retained_mechanics_occurrence_requires_authoritative_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["mechanics"][0].update({
                "status": "issue",
                "quote": "synthetic extraction",
                "correction": "synthetic correction",
                "priority": "required_copyedit",
                "finding_ids": ["WRT-01"],
                "occurrences": [{
                    "locator": "Synthetic page 1",
                    "quote": "synthetic extraction",
                    "correction": "synthetic correction",
                    "render_verification": "extraction_artifact_rejected",
                    "source_provenance": "main_manuscript",
                }],
            })
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("lacks authoritative visual/source verification" in error for error in errors))

    def test_reference_checked_count_excludes_unresolved_inventory_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["schema_version"] = "0.2"
            writing["reference_audit"] = legacy_reference_audit()
            writing["paper_type_lens"] = "Synthetic test"
            writing["strengths"] = ["The synthetic prose is concise."]
            writing["section_audit"] = [{
                "section": "Synthetic manuscript",
                "current_job": "State the model.",
                "what_works": "The model is concise.",
                "reader_friction": "No material friction.",
                "revision_direction": "Preserve the concise structure.",
                "finding_ids": [],
            }]
            writing["redundancy_map"] = []
            writing["reference_audit"]["status"] = "bounded"
            writing["reference_audit"]["bibliography_record_count"] = 1
            writing["reference_audit"]["records_checked"] = 1
            writing["reference_audit"]["records_verified"] = 0
            writing["reference_audit"]["records_adverse"] = 0
            writing["reference_audit"]["records_unresolved"] = 1
            writing["reference_audit"]["records"] = [{
                "id": "REF-01",
                "manuscript_record": "Unverified record",
                "status": "unresolved",
                "verified_record": None,
                "authoritative_url": None,
                "support_note": "Not live-checked.",
                "finding_ids": [],
            }]
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("records_checked must equal the number of non-unresolved" in error for error in errors))

    def test_writing_v02_requires_comprehensive_reader_and_reference_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["reference_audit"] = legacy_reference_audit()
            writing.update({
                "schema_version": "0.2",
                "paper_type_lens": "Synthetic test",
                "strengths": [],
                "section_audit": [],
                "redundancy_map": [],
            })
            for field in ("records_verified", "records_adverse", "records_unresolved"):
                writing["reference_audit"].pop(field, None)
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("schema violation" in error and "strengths" in error for error in errors))
            self.assertTrue(any("schema violation" in error and "section_audit" in error for error in errors))
            self.assertTrue(any("schema violation" in error and "records_verified" in error for error in errors))

    def test_current_full_review_uses_canonical_writing_audit_v4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(writing["schema_version"], "0.4")
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertEqual(errors, [])

    def test_current_full_review_rejects_precanonical_writing_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["schema_version"] = "0.3"
            for field in ("assessment_summary", "terminology_summary", "exhibit_summary"):
                writing.pop(field)
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "requires evidence/writing.json schema_version 0.4" in error
                for error in errors
            ))

    def test_writing_v04_requires_each_canonical_summary(self) -> None:
        for field in ("assessment_summary", "terminology_summary", "exhibit_summary"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                path = target / "evidence" / "writing.json"
                writing = json.loads(path.read_text(encoding="utf-8"))
                writing.pop(field)
                path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
                errors = MODULE.validate_review(target)
                self.assertTrue(any(
                    "schema violation" in error and field in error
                    for error in errors
                ), errors)

    def test_earlier_receipt_preserves_writing_v03_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["schema_version"] = "0.1"
            for gate in ("structured_audit_v02", "burden_coverage_v02"):
                if gate in receipt["gates"]:
                    receipt["gates"].remove(gate)
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

            writing_path = target / "evidence" / "writing.json"
            writing = json.loads(writing_path.read_text(encoding="utf-8"))
            writing["schema_version"] = "0.3"
            for field in ("assessment_summary", "terminology_summary", "exhibit_summary"):
                writing.pop(field)
            writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_writing_v02_allows_empty_action_arrays_when_no_writing_findings_are_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)

            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            next(row for row in ledger["findings"] if row["id"] == "WRT-01")["status"] = "resolved"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

            verification_path = target / "evidence" / "verification.json"
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
            verification["records"] = [
                row for row in verification["records"] if row["finding_id"] != "WRT-01"
            ]
            verification_path.write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")

            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["counts"]["minor"] = 0
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

            synthesis_path = target / "synthesis.json"
            synthesis = json.loads(synthesis_path.read_text(encoding="utf-8"))
            synthesis["writing_finding_count"] = 0
            synthesis_path.write_text(json.dumps(synthesis, indent=2) + "\n", encoding="utf-8")

            writing_path = target / "evidence" / "writing.json"
            writing = json.loads(writing_path.read_text(encoding="utf-8"))
            writing["assessment_summary"] = (
                "The synthetic manuscript is concise and readable; no active writing problem survives verification."
            )
            writing["highest_return_finding_ids"] = []
            writing["finding_links"] = []
            writing["section_audit"][0].update({
                "reader_friction": "No material writing friction survives verification.",
                "revision_direction": "Preserve the concise structure.",
                "evidence_refs": [
                    {"kind": "anchor", "id": "ANC-02", "purpose": "direct_support"},
                    {"kind": "anchor", "id": "ANC-03", "purpose": "checked_absence"},
                ],
                "finding_ids": [],
            })
            writing["mechanics"][0].update({
                "status": "checked_clean_group",
                "quote": None,
                "correction": None,
                "occurrences": [],
                "reader_consequence": "No reader-facing mechanics problem was found.",
                "priority": "not_applicable",
                "notes": "The complete synthetic manuscript was checked clean.",
                "evidence_refs": [
                    {"kind": "anchor", "id": "ANC-03", "purpose": "checked_absence"},
                ],
                "finding_ids": [],
            })
            writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")

            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            burden = next(
                row for row in coverage["burden_audits"]
                if row["burden_id"] == "writing_mechanics"
            )
            burden.update({
                "status": "checked_no_issue",
                "finding_ids": [],
                "notes": "The resolved mechanics item no longer leaves an active writing concern.",
            })
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")

            report_path = target / "editing-comments.md"
            report = report_path.read_text(encoding="utf-8")
            report = report.replace(
                "The synthetic manuscript is concise and readable. One objective subject-verb agreement error requires correction; no broader prose problem is present.",
                "The synthetic manuscript is concise and readable; no active writing problem survives verification.",
            ).replace(
                "- `WRT-01`: correct the subject-verb agreement error without expanding the proposition summary.",
                "No active writing revision is required.",
            ).replace(
                "One subject-verb agreement error interrupts the proposition summary. | Correct the verb while preserving the concise structure.",
                "No material writing friction survives verification. | Preserve the concise structure.",
            ).replace(
                "Correct “The proposition characterize” to “The proposition characterizes.” The rendered occurrence is mapped to `WRT-01`.",
                "The complete synthetic manuscript was checked clean for mechanics.",
            )
            report_path.write_text(report, encoding="utf-8")

            for generator in ("generate_verification.py", "generate_reports.py", "generate_fix_plan.py"):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "econ-review" / "scripts" / generator), str(target)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_writing_v02_requires_highest_return_id_when_writing_findings_are_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["highest_return_finding_ids"] = []
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires a highest-return finding" in error for error in errors))

    def test_full_writing_report_does_not_require_journal_fit(self) -> None:
        report = (FIXTURE / "editing-comments.md").read_text(encoding="utf-8")
        self.assertNotIn("## Journal fit and submission strategy", report)
        self.assertEqual(MODULE.validate_review(FIXTURE), [])

    def test_current_full_run_requires_explicit_requested_addon_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "run.json"
            run = json.loads(path.read_text(encoding="utf-8"))
            run.pop("requested_addons")
            path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires run.json.requested_addons" in error for error in errors))

    def test_assessment_boundary_heading_is_internal_only(self) -> None:
        for relative in ("report.md", "editing-comments.md"):
            for heading in ("## Assessment Boundary: internal scope", "### assessment-boundaries"):
                with self.subTest(relative=relative, heading=heading), tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp) / "review"
                    shutil.copytree(FIXTURE, target)
                    path = target / relative
                    path.write_text(
                        path.read_text(encoding="utf-8")
                        + f"\n{heading}\n\nInternal audit scope.\n",
                        encoding="utf-8",
                    )
                    errors = MODULE.validate_review(target)
                    self.assertTrue(any(
                        relative in error and "must not contain an Assessment Boundary" in error
                        for error in errors
                    ))

    def test_journal_fit_state_must_match_requested_addon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            writing_path = target / "evidence" / "writing.json"
            writing = json.loads(writing_path.read_text(encoding="utf-8"))
            writing["venue_fit"]["status"] = "bounded"
            writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("unrequested journal_fit" in error for error in errors))

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["requested_addons"] = ["journal_fit"]
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requested journal_fit" in error for error in errors))

    def test_substance_report_rejects_journal_fit_heading_variants(self) -> None:
        for heading in ("## Journal fit: possible targets", "### journal-fit guidance"):
            with self.subTest(heading=heading), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                path = target / "report.md"
                path.write_text(
                    path.read_text(encoding="utf-8")
                    + f"\n{heading}\n\nUnrequested venue prose.\n",
                    encoding="utf-8",
                )
                errors = MODULE.validate_review(target)
                self.assertTrue(any("report.md must not contain a journal-fit section" in error for error in errors))

    def test_current_writing_report_rejects_stale_noncanonical_preamble(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "editing-comments.md"
            report = path.read_text(encoding="utf-8").replace(
                "The synthetic manuscript is concise and readable.",
                "A stale hand-edited assessment says something else.",
                1,
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("not synchronized with evidence/writing.json" in error for error in errors))

    def test_writing_report_rejects_mixed_legacy_and_current_heading_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "editing-comments.md"
            report = path.read_text(encoding="utf-8").replace(
                "## Detailed Editing Comments",
                "## Writing quality summary\n\nRedundant legacy-format section.\n\n## Detailed Editing Comments",
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("mixes legacy and current editing-comments headings" in error for error in errors))

    def test_writing_report_rejects_reordered_or_duplicate_headings(self) -> None:
        for mutation, expected in (
            (
                lambda report: report.replace(
                    "## Editing assessment", "## TEMP", 1
                ).replace(
                    "## Highest-return editing revisions", "## Editing assessment", 1
                ).replace(
                    "## TEMP", "## Highest-return editing revisions", 1
                ),
                "headings are out of order",
            ),
            (
                lambda report: report.replace(
                    "## Detailed Editing Comments",
                    "## Editing assessment\n\nDuplicate.\n\n## Detailed Editing Comments",
                ),
                "each editing-comments heading exactly once",
            ),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                path = target / "editing-comments.md"
                path.write_text(mutation(path.read_text(encoding="utf-8")), encoding="utf-8")
                errors = MODULE.validate_review(target)
                self.assertTrue(any(expected in error for error in errors))

    def test_review_manifest_must_match_review_and_existing_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "review-manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["review_id"] = "wrong-review"
            manifest["documents"][0]["path"] = "missing-report.md"
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("review_id differs" in error for error in errors))
            self.assertTrue(any("does not exist: missing-report.md" in error for error in errors))

    def test_v3_requires_review_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "review-manifest.json").unlink()
            errors = MODULE.validate_review(target)
            self.assertIn("review-manifest.json is required for contract v0.3+", errors)

    def test_review_manifest_rejects_duplicate_document_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "review-manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["documents"][1]["id"] = manifest["documents"][0]["id"]
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("duplicate document IDs" in error for error in errors))

    def test_review_manifest_requires_trimmed_title_and_review_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "review-manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["review_id"] = f" {manifest['review_id']} "
            manifest["documents"][0]["title"] = " Referee report "
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("schema violation" in error and "review-manifest.json" in error for error in errors))

    def test_review_manifest_rejects_cross_runtime_path_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            alias_directory = target / "audit."
            alias_directory.mkdir()
            (alias_directory / "notes.md").write_text("# Notes\n", encoding="utf-8")
            path = target / "review-manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["documents"][0]["path"] = "audit./notes.md"
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "must be a canonical portable path" in error for error in errors
            ), errors)

    def test_v2_substance_report_rejects_writing_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "## Detailed Comments",
                "## Writing, clarity, consistency, and typographical review\n\nWrong channel.\n\n## Detailed Comments",
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("belongs in editing-comments.md" in error for error in errors))

    def test_v2_full_run_requires_writing_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "editing-comments.md").unlink()
            errors = MODULE.validate_review(target)
            self.assertTrue(any("missing required file" in error and "editing-comments.md" in error for error in errors))

    def test_complete_v2_run_requires_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "run.json"
            run = json.loads(path.read_text(encoding="utf-8"))
            run.pop("telemetry")
            path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires run.json.telemetry" in error for error in errors))

    def test_writing_channel_finding_cannot_be_listed_in_substance_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "<!-- finding_id: LOGIC-01 -->", "<!-- finding_id: WRT-01 -->"
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("writing-channel finding WRT-01 must not appear in report.md" in error for error in errors))

    def test_finding_id_substring_does_not_count_as_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            path.write_text(path.read_text(encoding="utf-8").replace("LOGIC-01", "LOGIC-011"), encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("active finding LOGIC-01 is not referenced in report.md" in error for error in errors))

    def test_json_schema_formats_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["venue_fit"]["as_of_date"] = "2026-99-99"
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("schema violation" in error and "as_of_date" in error for error in errors))

    def test_non_directory_input_fails_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not-a-review"
            path.write_text("x", encoding="utf-8")
            errors = MODULE.validate_review(path)
            self.assertTrue(errors)

    def test_adverse_figure_state_requires_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            figures["no_figures_confirmed"] = False
            figures["figures"] = [
                {
                    "id": "FIG-01",
                    "label": "Synthetic plot",
                    "pdf_pages": [1],
                    "source_locator": "Synthetic page 1",
                    "extraction_paths": ["evidence/figures.md"],
                    "kind": "plot",
                    "visual_status": "issue",
                    "caption_text_status": "consistent",
                    "claim_correspondence_status": "consistent",
                    "checks": {
                        "axes_scales_units": "Axis unit is missing.",
                        "legend_series_panels": "One series, no legend needed.",
                        "uncertainty": "Not applicable.",
                        "legibility_accessibility": "Readable.",
                        "visual_integrity": "Rendered page checked."
                    },
                    "finding_ids": [],
                    "notes": "Synthetic adversarial fixture."
                }
            ]
            figures_path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("adverse figure state FIG-01" in error for error in errors))

    def test_figure_extraction_path_cannot_escape_review_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            figures["no_figures_confirmed"] = False
            figures["figures"] = [
                {
                    "id": "FIG-01",
                    "label": "Synthetic clean plot",
                    "pdf_pages": [1],
                    "source_locator": "Synthetic page 1",
                    "extraction_paths": ["../outside.png"],
                    "kind": "plot",
                    "visual_status": "clear",
                    "caption_text_status": "consistent",
                    "claim_correspondence_status": "consistent",
                    "checks": {
                        "axes_scales_units": "Clear.",
                        "legend_series_panels": "Clear.",
                        "uncertainty": "Not applicable.",
                        "legibility_accessibility": "Readable.",
                        "visual_integrity": "Rendered page checked."
                    },
                    "finding_ids": [],
                    "notes": "Synthetic adversarial path fixture."
                }
            ]
            figures_path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "canonical portable review-relative path" in error for error in errors
            ), errors)

    @unittest.skipIf(os.name == "nt", "symlink creation is privilege-dependent on Windows")
    def test_figure_extraction_symlink_cannot_escape_review_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            link = target / "evidence" / "outside.png"
            link.symlink_to("/etc/hosts")
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            figures["no_figures_confirmed"] = False
            figures["figures"] = [{
                "id": "FIG-01", "label": "Synthetic plot", "pdf_pages": [1],
                "source_locator": "Synthetic page 1", "extraction_paths": ["evidence/outside.png"],
                "kind": "plot", "visual_status": "clear", "caption_text_status": "consistent",
                "claim_correspondence_status": "consistent",
                "checks": {
                    "axes_scales_units": "Clear.", "legend_series_panels": "Clear.",
                    "uncertainty": "Not applicable.", "legibility_accessibility": "Readable.",
                    "visual_integrity": "Rendered page checked.",
                },
                "finding_ids": [], "notes": "Synthetic adversarial symlink fixture.",
            }]
            figures_path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("resolves outside the review directory" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
