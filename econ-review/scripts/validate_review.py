#!/usr/bin/env python3
"""Validate econ-review artifacts and their cross-file mappings."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import safe_read_bytes, sha256_bytes  # noqa: E402
from trust_spine import pdf_sources, validate_trust_spine  # noqa: E402
from generate_verification import render as render_verification  # noqa: E402

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - environment/setup failure
    Draft202012Validator = None
    FormatChecker = None


STAGES = {
    "pending",
    "in_progress",
    "passed",
    "bounded",
    "failed",
    "not_applicable",
}
SEVERITIES = {"critical", "major", "minor", "info"}
EVIDENCE_TYPES = {
    "quote",
    "equation",
    "table_cell",
    "figure",
    "code",
    "literature",
    "absence_scope",
    "computation",
}
FINDING_ID = re.compile(r"^[A-Z][A-Z0-9_-]*-[0-9]{2,}$")
ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
ALLOWED_RENDER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def validate_local_asset_path(
    review_dir: Path,
    raw_path: Any,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        errors.append(f"{label} must be a non-empty relative path")
        return
    relative_path = Path(raw_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        errors.append(f"{label} must stay inside the review directory: {raw_path}")
        return
    if relative_path.suffix.lower() not in ALLOWED_RENDER_SUFFIXES:
        errors.append(f"{label} has an unsupported render type: {raw_path}")
        return
    root = review_dir.resolve()
    candidate = review_dir / relative_path
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        errors.append(f"{label} does not exist: {raw_path}")
        return
    try:
        resolved.relative_to(root)
    except ValueError:
        errors.append(f"{label} resolves outside the review directory: {raw_path}")
        return
    if not resolved.is_file():
        errors.append(f"{label} must resolve to a regular file: {raw_path}")


def normalized_exhibit_label(kind: str, label: Any) -> str:
    if not isinstance(label, str):
        return ""
    value = re.sub(r"\s+", " ", label).strip().lower()
    if kind == "table":
        return re.sub(r"^(appendix\s+)?table\s+", "", value)
    if kind == "figure":
        return re.sub(r"^(appendix\s+)?figure\s+", "", value)
    return value


def validate_schema(instance: Any, schema_name: str, label: str, errors: list[str]) -> None:
    if Draft202012Validator is None:
        errors.append("jsonschema is required to validate econ-review artifacts")
        return
    schema = load_json(ASSET_DIR / schema_name, errors)
    if not isinstance(schema, dict):
        return
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path)):
        path = ".".join(str(part) for part in error.absolute_path)
        location = f"{label}.{path}" if path else label
        errors.append(f"schema violation at {location}: {error.message}")


def load_json(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing required file: {path}")
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"cannot read JSON file {path}: {exc}")
    return None


def validate_finalization_receipt(review_dir: Path, review_id: Any, errors: list[str]) -> None:
    receipt = load_json(review_dir / "finalization.json", errors)
    if not isinstance(receipt, dict):
        return
    validate_schema(receipt, "finalization.schema.json", "finalization.json", errors)
    if receipt.get("review_id") != review_id:
        errors.append("finalization.json review_id differs from run.json")
    source_manifest = load_json(review_dir / "evidence" / "source-manifest.json", errors)
    declared_pdfs = pdf_sources(source_manifest) if isinstance(source_manifest, dict) else []
    gates = receipt.get("gates", []) if isinstance(receipt.get("gates"), list) else []
    if declared_pdfs and "source_ingestion" not in gates:
        errors.append("finalization receipt for PDF sources requires the source_ingestion gate")
    if not declared_pdfs and "source_ingestion" in gates:
        errors.append("finalization receipt declares source_ingestion without a PDF source")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict):
        return
    required = {
        "run.json", "findings.json", "synthesis.json", "review-manifest.json",
        "README.md", "report.md", "fix-plan.md", "evidence/source-manifest.json",
        "evidence/verification.json", "evidence/computations.json", "evidence/external-sources.json",
    }
    missing = sorted(required - set(artifacts))
    if missing:
        errors.append("finalization receipt omits canonical artifacts: " + ", ".join(missing))
    for source in declared_pdfs:
        extraction = source.get("extraction")
        if not isinstance(extraction, dict):
            continue
        ingestion_path = extraction.get("ingestion_manifest_path")
        if isinstance(ingestion_path, str) and ingestion_path not in artifacts:
            errors.append(
                f"finalization receipt omits PDF ingestion manifest: {ingestion_path}"
            )
    for relative, expected in artifacts.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            continue
        try:
            observed = sha256_bytes(safe_read_bytes(review_dir, relative))
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append(f"finalized artifact {relative} cannot be read safely: {exc}")
            continue
        if observed != expected:
            errors.append(f"finalized artifact changed after finalization: {relative}")


def require(obj: dict[str, Any], keys: set[str], label: str, errors: list[str]) -> None:
    missing = sorted(keys - obj.keys())
    if missing:
        errors.append(f"{label} missing keys: {', '.join(missing)}")


def validate_evidence(evidence: Any, label: str, errors: list[str]) -> None:
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"{label}.evidence must be a non-empty array")
        return
    for index, item in enumerate(evidence):
        item_label = f"{label}.evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} must be an object")
            continue
        require(item, {"type", "source", "locator", "content", "scope_checked"}, item_label, errors)
        if item.get("type") not in EVIDENCE_TYPES:
            errors.append(f"{item_label}.type is invalid")
        if not isinstance(item.get("source"), str) or not item.get("source", "").strip():
            errors.append(f"{item_label}.source must be non-empty")
        locator = item.get("locator")
        if not isinstance(locator, dict):
            errors.append(f"{item_label}.locator must be an object")
        elif item.get("type") != "absence_scope" and not any(
            value is not None and (not isinstance(value, str) or value.strip())
            for value in locator.values()
        ):
            errors.append(f"{item_label}.locator must identify at least one manuscript location")
        if item.get("type") == "absence_scope" and not item.get("scope_checked"):
            errors.append(f"{item_label} requires scope_checked")
        if item.get("type") != "absence_scope" and (
            not isinstance(item.get("content"), str) or not item.get("content", "").strip()
        ):
            errors.append(f"{item_label} requires non-empty content")


def validate_finding(item: Any, index: int, errors: list[str]) -> str | None:
    label = f"findings[{index}]"
    if not isinstance(item, dict):
        errors.append(f"{label} must be an object")
        return None
    require(
        item,
        {
            "id",
            "importance_rank",
            "dimension",
            "critique_basis",
            "data_limitation",
            "claim_ids",
            "reader_effect",
            "severity",
            "essential",
            "status",
            "support_state",
            "issue",
            "why_it_matters",
            "evidence",
            "confidence",
            "counterargument",
            "fix",
            "verification",
        },
        label,
        errors,
    )
    finding_id = item.get("id")
    if not isinstance(finding_id, str) or not FINDING_ID.fullmatch(finding_id):
        errors.append(f"{label}.id is invalid: {finding_id!r}")
        finding_id = None
    rank = item.get("importance_rank")
    if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
        errors.append(f"{label}.importance_rank must be a positive integer")
    if not isinstance(item.get("dimension"), str) or not item.get("dimension", "").strip():
        errors.append(f"{label}.dimension must be a non-empty string")
    if not isinstance(item.get("reader_effect"), str) or not item.get("reader_effect", "").strip():
        errors.append(f"{label}.reader_effect must be non-empty")
    data_limitation = item.get("data_limitation")
    critique_basis = item.get("critique_basis")
    severity = item.get("severity")
    if severity not in SEVERITIES:
        errors.append(f"{label}.severity is invalid")
    if not isinstance(item.get("essential"), bool):
        errors.append(f"{label}.essential must be boolean")
    if item.get("essential") and severity not in {"critical", "major"}:
        errors.append(f"{label}: essential findings must be critical or major")
    if item.get("status") not in {"dismissed", "resolved"} and data_limitation == "inherent_and_properly_bounded":
        errors.append(f"{label}: an inherent, properly bounded data limitation cannot be an active criticism")
    if data_limitation == "inherent_but_claim_exceeds" and critique_basis not in {
        "claim_exceeds_evidence", "internal_inconsistency", "reader_clarity"
    }:
        errors.append(f"{label}: inherent data limits must be framed as a claim-scope or reader issue")
    if critique_basis == "claim_exceeds_evidence" and not item.get("claim_ids"):
        errors.append(f"{label}: claim-overreach findings must link at least one claim family")
    validate_evidence(item.get("evidence"), label, errors)
    confidence = item.get("confidence")
    if not isinstance(confidence, dict) or confidence.get("level") not in {"high", "medium", "low"}:
        errors.append(f"{label}.confidence is invalid")
    elif not confidence.get("would_change_my_mind"):
        errors.append(f"{label}.confidence.would_change_my_mind must be non-empty")
    counter = item.get("counterargument")
    if not isinstance(counter, dict):
        errors.append(f"{label}.counterargument is required for every finding")
    elif counter.get("result") not in {"survived", "weakened", "refuted", "not_applicable"}:
        errors.append(f"{label}.counterargument.result must record a completed fairness check")
    elif item.get("status") not in {"dismissed", "resolved"} and counter.get("result") == "refuted":
        errors.append(f"{label}: an active finding cannot have a refuted counterargument")
    fix = item.get("fix")
    if not isinstance(fix, dict):
        errors.append(f"{label}.fix must be an object")
    else:
        require(
            fix,
            {
                "what", "how", "resolved_when", "strategy", "patch", "effort", "publishability", "dependencies",
                "requires_new_data", "current_design_can_support_primary_fix", "claim_narrowing_alternative",
            },
            f"{label}.fix",
            errors,
        )
        if not fix.get("publishability"):
            errors.append(f"{label}.fix.publishability must be non-empty")
        if not isinstance(fix.get("resolved_when"), str) or not fix.get("resolved_when", "").strip():
            errors.append(f"{label}.fix.resolved_when must state an observable completion condition")
        if data_limitation == "inherent_but_claim_exceeds":
            if fix.get("strategy") not in {"narrow_claim", "clarify_or_disclose", "reorganize_or_rewrite"}:
                errors.append(f"{label}: inherent data limits require claim narrowing or clarification, not a data demand")
            if fix.get("effort") == "new-data":
                errors.append(f"{label}: an inherent-data claim-scope finding cannot require new data")
            if fix.get("requires_new_data") is not False:
                errors.append(f"{label}: the primary fix for an inherent data limit must not require new data")
            if fix.get("current_design_can_support_primary_fix") is not True:
                errors.append(f"{label}: an inherent-data claim-scope finding needs a current-design repair")
            if not isinstance(fix.get("claim_narrowing_alternative"), str) or not fix.get("claim_narrowing_alternative", "").strip():
                errors.append(f"{label}: an inherent-data claim-scope finding needs a claim-narrowing alternative")
    return finding_id


def check_required_sections(
    text: str,
    file_label: str,
    headings: tuple[str, ...],
    errors: list[str],
) -> None:
    for heading in headings:
        heading_match = re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
        if not heading_match:
            errors.append(f"{file_label} is missing '{heading}'")
            continue
        following = text[heading_match.end():]
        next_heading = re.search(r"^## ", following, re.MULTILINE)
        content = following[:next_heading.start()] if next_heading else following
        if not content.strip():
            errors.append(f"{file_label} section '{heading}' must be non-empty")


def check_alternative_section_sets(
    text: str,
    file_label: str,
    alternatives: tuple[tuple[str, ...], ...],
    errors: list[str],
) -> None:
    """Accept a complete legacy or current section set, never a partial mixture."""
    recognized = {heading for headings in alternatives for heading in headings}
    present = {
        heading for heading in recognized
        if re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
    }
    for headings in alternatives:
        chosen = set(headings)
        if chosen.issubset(present) and not (present - chosen):
            counts = [len(re.findall(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)) for heading in headings]
            if counts != [1] * len(headings):
                errors.append(f"{file_label} requires each writing-report heading exactly once")
                return
            positions = [text.find(heading) for heading in headings]
            if positions != sorted(positions):
                errors.append(f"{file_label} writing-report headings are out of order")
                return
            check_required_sections(text, file_label, headings, errors)
            return
    if any(set(headings).issubset(present) for headings in alternatives):
        errors.append(f"{file_label} mixes legacy and current writing-report headings")
        return
    choices = " or ".join(" / ".join(headings) for headings in alternatives)
    errors.append(f"{file_label} must contain one complete writing-report section set: {choices}")


_QUOTE_FOLD = str.maketrans({
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "–": "-", "—": "-", "−": "-", "‑": "-",
    "…": "...", "\u00a0": " ",
})

_META_SCAFFOLD_OPENINGS = (
    "the reader needs to",
    "what must be clear",
    "decision at stake",
    "reader test",
    "a reader should",
    "readers should",
    "a reader-first",
    "this matters because",
    "the concern is",
    "the problem is",
    "the issue is",
)
_SUGGESTION_SCAFFOLD_OPENINGS = (
    "i suggest",
    "i recommend",
    "my suggestion is",
    "to address this issue",
    "to address this concern",
    "to address this comment",
    "a possible fix is",
    "a proportionate repair is",
)
_CONTENT_WORD_STOPLIST = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "because", "by", "for", "from",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that", "the",
    "their", "this", "to", "was", "were", "which", "with",
})


def prose_sentences(value: str) -> list[str]:
    """Return substantive prose sentences for conservative duplicate checks."""
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", value.strip()))
        if sentence.strip()
    ]


def content_words(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", value.lower())
    return {word for word in words if word not in _CONTENT_WORD_STOPLIST}


def near_duplicate_sentence_pair(value: str) -> tuple[int, int] | None:
    """Find only high-overlap sentence pairs, avoiding topic-overlap false positives."""
    sentences = prose_sentences(value)
    for left_index, left in enumerate(sentences):
        left_words = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", left.lower())
        if len(left_words) < 6:
            continue
        left_content = content_words(left)
        if len(left_content) < 4:
            continue
        for right_index in range(left_index + 1, len(sentences)):
            right = sentences[right_index]
            right_words = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", right.lower())
            if len(right_words) < 6:
                continue
            right_content = content_words(right)
            if len(right_content) < 4:
                continue
            shared = left_content & right_content
            union = left_content | right_content
            containment = len(shared) / min(len(left_content), len(right_content))
            jaccard = len(shared) / len(union)
            if len(shared) >= 4 and containment >= 0.8 and jaccard >= 0.5:
                return left_index + 1, right_index + 1
    return None


def normalize_quote(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(_QUOTE_FOLD)
    return " ".join(value.lower().split())


def validate_comment_section(
    text: str,
    file_label: str,
    section_title: str,
    expected_items: list[dict[str, Any]],
    errors: list[str],
) -> set[str]:
    detail_match = re.search(rf"^## {re.escape(section_title)} \((\d+)\)\s*$", text, re.MULTILINE)
    if not detail_match:
        errors.append(f"{file_label} is missing '## {section_title} (N)'")
        return set()

    detail_start = detail_match.end()
    next_h2 = re.search(r"^## ", text[detail_start:], re.MULTILINE)
    detail_block = text[detail_start : detail_start + next_h2.start()] if next_h2 else text[detail_start:]
    comment_count = len(re.findall(r"^### \d+\. ", detail_block, re.MULTILINE))
    declared_count = int(detail_match.group(1))
    if declared_count != comment_count:
        errors.append(f"{section_title} count mismatch: heading says {declared_count}, found {comment_count}")
    if comment_count != len(expected_items):
        errors.append(
            f"{section_title} must contain every active finding exactly once: "
            f"found {comment_count}, expected {len(expected_items)}"
        )

    blocks = re.split(r"(?=^### \d+\. )", detail_block, flags=re.MULTILINE)
    blocks = [block for block in blocks if re.match(r"^### \d+\. ", block)]
    visible_numbers = [int(value) for value in re.findall(r"^### (\d+)\. ", detail_block, re.MULTILINE)]
    if visible_numbers != list(range(1, comment_count + 1)):
        errors.append(f"{section_title} visible numbering must be consecutive 1..N")

    block_quotes: list[str] = []
    feedback_texts: list[str] = []
    for block_index, block in enumerate(blocks, start=1):
        if len(re.findall(r"^\*\*Status\*\*: \[Pending\]\s*$", block, re.MULTILINE)) != 1:
            errors.append(f"detailed comment {block_index} requires exactly one '**Status**: [Pending]' field")
        if len(re.findall(r"^\*\*Quote\*\*:\s*$", block, re.MULTILINE)) != 1:
            errors.append(f"detailed comment {block_index} requires exactly one Quote field")
        quote_match = re.search(r"^\*\*Quote\*\*:\s*\n(?P<quote>(?:^>.*(?:\n|$))+)", block, re.MULTILINE)
        quote_text = "" if not quote_match else re.sub(
            r"^>\s?", "", quote_match.group("quote"), flags=re.MULTILINE
        ).strip()
        if not quote_text:
            errors.append(f"detailed comment {block_index} requires a non-empty block quote")
        block_quotes.append(quote_text)
        feedback_match = re.search(r"^\*\*Feedback\*\*:\s*(?P<feedback>[\s\S]+?)\s*\Z", block, re.MULTILINE)
        feedback_text = "" if not feedback_match else feedback_match.group("feedback").strip()
        if len(re.findall(r"^\*\*Feedback\*\*:", block, re.MULTILINE)) != 1 or not feedback_text:
            errors.append(f"detailed comment {block_index} requires exactly one non-empty Feedback field")
        feedback_texts.append(feedback_text)

    detail_ids = re.findall(r"<!-- finding_id: ([A-Z][A-Z0-9_-]*-[0-9]{2,}) -->", detail_block)
    if len(detail_ids) != comment_count:
        errors.append("each detailed comment requires exactly one hidden finding_id")
    expected_order = [
        item.get("id")
        for item in sorted(expected_items, key=lambda item: item.get("importance_rank", 10**9))
    ]
    if detail_ids != expected_order:
        errors.append(f"{section_title} finding IDs must follow importance_rank order")

    findings_by_id = {item.get("id"): item for item in expected_items}
    prohibited_feedback_phrases = (
        "As written,",
        "The strongest author-side defense is that",
        "The checked manuscript supports that defense only to this extent",
        "A proportionate repair is to",
        "leading-field verification requires",
        "the authors fail to",
        "the authors ignore",
        "There seems to be an issue",
        "The document would benefit from",
        "A careful reader cannot tell whether the stated claim is supported at the precision and scope presented.",
        "A careful reader may misread the object, unit, comparison, or evidentiary strength at this location.",
    )
    malformed_acronyms = ("vAR", "iRF", "hPI", "sVAR", "fOMC")
    for block_index, (finding_id, quote_text, feedback_text) in enumerate(
        zip(detail_ids, block_quotes, feedback_texts), start=1
    ):
        finding = findings_by_id.get(finding_id, {})
        evidence_texts = [
            evidence.get("content")
            for evidence in finding.get("evidence", [])
            if isinstance(evidence, dict) and isinstance(evidence.get("content"), str)
        ]
        normalized_quote = normalize_quote(quote_text)
        if evidence_texts and not any(
            normalized_quote in normalize_quote(evidence)
            for evidence in evidence_texts
        ):
            errors.append(f"detailed comment {block_index} quote does not match ledger evidence for {finding_id}")
        for phrase in prohibited_feedback_phrases:
            if phrase.lower() in feedback_text.lower():
                errors.append(f"detailed comment {block_index} uses prohibited boilerplate: {phrase}")
        for acronym in malformed_acronyms:
            if acronym in feedback_text:
                errors.append(f"detailed comment {block_index} contains malformed acronym {acronym}")

    sentence_owners: dict[str, set[str]] = {}
    major_label_signatures: list[tuple[str, ...]] = []
    for finding_id, feedback_text in zip(detail_ids, feedback_texts):
        for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\*\*[^*]+\*\*", "", feedback_text)):
            normalized_sentence = " ".join(sentence.lower().split()).strip()
            if len(normalized_sentence.split()) >= 10:
                sentence_owners.setdefault(normalized_sentence, set()).add(finding_id)
        if findings_by_id.get(finding_id, {}).get("severity") in {"critical", "major"}:
            labels = tuple(re.findall(r"\*\*([^*]+?)\.\*\*", feedback_text))
            if labels:
                major_label_signatures.append(labels)
    for sentence, owners in sentence_owners.items():
        if len(owners) >= 3:
            errors.append(
                "detailed comments repeat a nontechnical sentence across "
                f"{len(owners)} findings ({', '.join(sorted(owners))}): {sentence}"
            )
    if len(major_label_signatures) >= 6:
        signature, count = Counter(major_label_signatures).most_common(1)[0]
        if count > len(major_label_signatures) / 2:
            errors.append(
                "more than half of critical/major comments use the same label sequence: "
                + " / ".join(signature)
            )
    return set(detail_ids)


def validate_comment_section_v3(
    text: str,
    file_label: str,
    section_title: str,
    expected_items: list[dict[str, Any]],
    errors: list[str],
) -> set[str]:
    """Validate the v0.3 issue-first, status-last detailed-comment contract."""
    detail_match = re.search(rf"^## {re.escape(section_title)} \((\d+)\)\s*$", text, re.MULTILINE)
    if not detail_match:
        errors.append(f"{file_label} is missing '## {section_title} (N)'")
        return set()

    detail_start = detail_match.end()
    next_h2 = re.search(r"^## ", text[detail_start:], re.MULTILINE)
    detail_block = text[detail_start : detail_start + next_h2.start()] if next_h2 else text[detail_start:]
    blocks = re.split(r"(?=^### \d+\. )", detail_block, flags=re.MULTILINE)
    blocks = [block for block in blocks if re.match(r"^### \d+\. ", block)]
    declared_count = int(detail_match.group(1))
    if declared_count != len(blocks):
        errors.append(f"{section_title} count mismatch: heading says {declared_count}, found {len(blocks)}")
    if len(blocks) != len(expected_items):
        errors.append(
            f"{section_title} must contain every active finding exactly once: "
            f"found {len(blocks)}, expected {len(expected_items)}"
        )
    visible_numbers = [int(value) for value in re.findall(r"^### (\d+)\. ", detail_block, re.MULTILINE)]
    if visible_numbers != list(range(1, len(blocks) + 1)):
        errors.append(f"{section_title} visible numbering must be consecutive 1..N")

    detail_ids = re.findall(r"<!-- finding_id: ([A-Z][A-Z0-9_-]*-[0-9]{2,}) -->", detail_block)
    if len(detail_ids) != len(blocks):
        errors.append("each detailed comment requires exactly one hidden finding_id")
    expected_order = [
        item.get("id")
        for item in sorted(expected_items, key=lambda item: item.get("importance_rank", 10**9))
    ]
    if detail_ids != expected_order:
        errors.append(f"{section_title} finding IDs must follow importance_rank order")

    findings_by_id = {item.get("id"): item for item in expected_items}
    current_labels = ["Issue", "Relevant text", "Concern", "Suggestions", "Status"]
    archived_labels = [
        "Issue", "Relevant quote or evidence", "Problem and concern", "Constructive feedback", "Status"
    ]
    early_labels = archived_labels[:-1] + ["Possible fix", "Status"]
    prohibited_phrases = (
        "As written,",
        "The strongest author-side defense is that",
        "The checked manuscript supports that defense only to this extent",
        "A proportionate repair is to",
        "leading-field verification requires",
        "the authors fail to",
        "the authors ignore",
        "There seems to be an issue",
        "The document would benefit from",
    )
    malformed_acronyms = ("vAR", "iRF", "hPI", "sVAR", "fOMC")
    prose_by_id: dict[str, str] = {}

    for block_index, (block, finding_id) in enumerate(zip(blocks, detail_ids), start=1):
        finding = findings_by_id.get(finding_id, {})
        field_matches = list(re.finditer(r"^\*\*([^*]+)\*\*:\s*", block, re.MULTILINE))
        labels = [match.group(1) for match in field_matches]
        if labels not in (current_labels, archived_labels, early_labels):
            errors.append(
                f"detailed comment {block_index} fields must appear as Issue, Relevant text, "
                "Concern, Suggestions, then Status"
            )
            continue
        if labels[-1] != "Status":
            errors.append(f"detailed comment {block_index} must place Status last")

        values: dict[str, str] = {}
        for index, match in enumerate(field_matches):
            end = field_matches[index + 1].start() if index + 1 < len(field_matches) else len(block)
            values[match.group(1)] = block[match.end():end].strip()
        for label in labels[:-1]:
            if not values.get(label):
                errors.append(f"detailed comment {block_index} requires non-empty {label}")
        if "Possible fix" in labels and not values.get("Possible fix"):
            errors.append(f"detailed comment {block_index} has an empty Possible fix")
        if values.get("Status") != "[Pending]":
            errors.append(f"detailed comment {block_index} requires '**Status**: [Pending]' as its final field")

        issue_text = values.get("Issue", "")
        canonical_issue = str(finding.get("issue", ""))
        if issue_text and canonical_issue and normalize_quote(issue_text) != normalize_quote(canonical_issue):
            errors.append(f"detailed comment {block_index} Issue does not match ledger issue for {finding_id}")

        evidence_label = "Relevant text" if "Relevant text" in values else "Relevant quote or evidence"
        concern_label = "Concern" if "Concern" in values else "Problem and concern"
        suggestions_label = "Suggestions" if "Suggestions" in values else "Constructive feedback"
        quote_block = values.get(evidence_label, "")
        quote_lines = [line for line in quote_block.splitlines() if line.startswith(">")]
        quote_text = "\n".join(re.sub(r"^>\s?", "", line) for line in quote_lines).strip()
        if not quote_text or any(line.strip() and not line.startswith(">") for line in quote_block.splitlines()):
            errors.append(f"detailed comment {block_index} requires one non-empty block quote")
        if not re.search(
            rf"^\*\*{re.escape(evidence_label)}\*\*:\s*\n(?:>.*(?:\n|$))+\n\*\*{re.escape(concern_label)}\*\*:",
            block,
            re.MULTILINE,
        ):
            errors.append(
                f"detailed comment {block_index} requires a blank line after the evidence block quote"
            )
        evidence_texts = [
            evidence.get("content")
            for evidence in finding.get("evidence", [])
            if isinstance(evidence, dict) and isinstance(evidence.get("content"), str)
        ]
        normalized_quote = normalize_quote(quote_text)
        if evidence_texts and not any(
            normalized_quote in normalize_quote(evidence) for evidence in evidence_texts
        ):
            errors.append(f"detailed comment {block_index} quote does not match ledger evidence for {finding_id}")

        prose = " ".join(
            values.get(label, "") for label in (concern_label, suggestions_label, "Possible fix")
        ).strip()
        prose_by_id[finding_id] = prose
        for phrase in prohibited_phrases:
            if phrase.lower() in prose.lower():
                errors.append(f"detailed comment {block_index} uses prohibited boilerplate: {phrase}")
        for acronym in malformed_acronyms:
            if acronym in prose:
                errors.append(f"detailed comment {block_index} contains malformed acronym {acronym}")

        problem_text = values.get(concern_label, "").lstrip()
        normalized_problem = problem_text.lower()
        concern_openings = _META_SCAFFOLD_OPENINGS if labels == current_labels else _META_SCAFFOLD_OPENINGS[:4]
        for opening in concern_openings:
            if normalized_problem.startswith(opening):
                errors.append(
                    f"detailed comment {block_index} ({finding_id}) begins {concern_label} "
                    f"with meta-scaffolding: {opening}"
                )
                break

        suggestion_text = values.get(suggestions_label, "")
        normalized_suggestion = suggestion_text.lstrip().lower()
        suggestion_openings = _SUGGESTION_SCAFFOLD_OPENINGS if labels == current_labels else ()
        for opening in suggestion_openings:
            if normalized_suggestion.startswith(opening):
                errors.append(
                    f"detailed comment {block_index} ({finding_id}) begins {suggestions_label} "
                    f"with meta-scaffolding: {opening}"
                )
                break

        duplicate_pair = near_duplicate_sentence_pair(suggestion_text)
        if duplicate_pair is not None:
            errors.append(
                f"detailed comment {block_index} ({finding_id}) repeats recommendation content "
                f"within {suggestions_label} sentences "
                f"{duplicate_pair[0]} and {duplicate_pair[1]}"
            )

    sentence_owners: dict[str, set[str]] = {}
    for finding_id, prose in prose_by_id.items():
        for sentence in re.split(r"(?<=[.!?])\s+", prose):
            normalized_sentence = " ".join(sentence.lower().split()).strip()
            if len(normalized_sentence.split()) >= 10:
                sentence_owners.setdefault(normalized_sentence, set()).add(finding_id)
    for sentence, owners in sentence_owners.items():
        if len(owners) >= 3:
            errors.append(
                "detailed comments repeat a nontechnical sentence across "
                f"{len(owners)} findings ({', '.join(sorted(owners))}): {sentence}"
            )
    return set(detail_ids)


def validate_review(review_dir: Path) -> list[str]:
    errors: list[str] = []
    run = load_json(review_dir / "run.json", errors)
    ledger = load_json(review_dir / "findings.json", errors)

    if not isinstance(run, dict) or not isinstance(ledger, dict):
        return errors

    validate_schema(run, "run.schema.json", "run.json", errors)
    validate_schema(ledger, "findings.schema.json", "findings.json", errors)

    require(
        run,
        {
            "schema_version",
            "review_id",
            "status",
            "mode",
            "target",
            "paper_family",
            "designs",
            "identity_handling",
            "assessment_boundary",
            "capabilities",
            "comment_policy",
            "stage_status",
            "gates_loaded",
            "counts",
            "verification_passed",
        },
        "run.json",
        errors,
    )
    require(ledger, {"schema_version", "review_id", "findings"}, "findings.json", errors)
    run_version = run.get("schema_version")
    ledger_version = ledger.get("schema_version")
    if run_version not in {"0.1", "0.2", "0.3", "0.4"} or ledger_version not in {"0.1", "0.2", "0.3", "0.4"}:
        errors.append("schema_version must be '0.1', '0.2', '0.3', or '0.4' in both JSON files")
    if run_version != ledger_version:
        errors.append("schema_version differs between run.json and findings.json")
    v2 = run_version == "0.2" and ledger_version == "0.2"
    v3 = run_version == "0.3" and ledger_version == "0.3"
    v4 = run_version == "0.4" and ledger_version == "0.4"
    current_contract = v3 or v4
    split_contract = v2 or current_contract
    if run.get("review_id") != ledger.get("review_id"):
        errors.append("review_id differs between run.json and findings.json")
    manifest_path = review_dir / "review-manifest.json"
    if current_contract and not manifest_path.exists():
        errors.append("review-manifest.json is required for contract v0.3+")
    if manifest_path.exists():
        manifest = load_json(manifest_path, errors)
        if isinstance(manifest, dict):
            validate_schema(manifest, "review-manifest.schema.json", "review-manifest.json", errors)
            if manifest.get("review_id") != run.get("review_id"):
                errors.append("review-manifest.json review_id differs from run.json")
            documents = manifest.get("documents", [])
            if isinstance(documents, list):
                document_ids = [row.get("id") for row in documents if isinstance(row, dict)]
                document_paths = [row.get("path") for row in documents if isinstance(row, dict)]
                duplicate_ids = sorted(value for value, count in Counter(document_ids).items() if value and count > 1)
                duplicate_paths = sorted(value for value, count in Counter(document_paths).items() if value and count > 1)
                if duplicate_ids:
                    errors.append("review-manifest.json has duplicate document IDs: " + ", ".join(duplicate_ids))
                if duplicate_paths:
                    errors.append("review-manifest.json has duplicate document paths: " + ", ".join(duplicate_paths))
                root = review_dir.resolve()
                for index, raw_path in enumerate(document_paths):
                    if not isinstance(raw_path, str):
                        continue
                    relative = Path(raw_path)
                    label = f"review-manifest.json documents[{index}].path"
                    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".md":
                        errors.append(f"{label} must be a safe relative Markdown path")
                        continue
                    candidate = review_dir / relative
                    if candidate.is_symlink():
                        errors.append(f"{label} must not be a symbolic link: {raw_path}")
                        continue
                    try:
                        resolved = candidate.resolve(strict=True)
                    except FileNotFoundError:
                        errors.append(f"{label} does not exist: {raw_path}")
                        continue
                    try:
                        resolved.relative_to(root)
                    except ValueError:
                        errors.append(f"{label} resolves outside the review directory: {raw_path}")
                        continue
                    if not resolved.is_file():
                        errors.append(f"{label} must resolve to a regular file: {raw_path}")
    if run.get("mode") not in {"quick", "full"}:
        errors.append("run.json.mode must be quick or full")
    comment_policy = run.get("comment_policy")
    if not isinstance(comment_policy, dict):
        errors.append("run.json.comment_policy must be an object")
        comment_policy = {}
    else:
        require(comment_policy, {"minimum_target", "maximum", "exhaustive"}, "run.json.comment_policy", errors)
    minimum_target = comment_policy.get("minimum_target")
    maximum_comments = comment_policy.get("maximum")
    if not isinstance(minimum_target, int) or isinstance(minimum_target, bool) or minimum_target < 0:
        errors.append("run.json.comment_policy.minimum_target must be a non-negative integer")
        minimum_target = 0
    if maximum_comments is not None and (
        not isinstance(maximum_comments, int) or isinstance(maximum_comments, bool) or maximum_comments < 1
    ):
        errors.append("run.json.comment_policy.maximum must be null or a positive integer")
        maximum_comments = None
    if maximum_comments is not None and minimum_target > maximum_comments:
        errors.append("run.json.comment_policy.minimum_target cannot exceed maximum")
    if not isinstance(comment_policy.get("exhaustive"), bool):
        errors.append("run.json.comment_policy.exhaustive must be boolean")
    stage_status = run.get("stage_status")
    required_stages = {
        "intake",
        "reconstruction",
        "frontier",
        "audit",
        "counterargument",
        "synthesis",
        "verification",
        "delivery",
    }
    if not isinstance(stage_status, dict):
        errors.append("run.json.stage_status must be an object")
    else:
        require(stage_status, required_stages, "run.json.stage_status", errors)
        for stage, value in stage_status.items():
            if stage in required_stages and value not in STAGES:
                errors.append(f"invalid stage state for {stage}: {value!r}")

    findings = ledger.get("findings")
    if not isinstance(findings, list):
        errors.append("findings.json.findings must be an array")
        findings = []
    ids = [validate_finding(item, index, errors) for index, item in enumerate(findings)]
    clean_ids = [item for item in ids if item]
    duplicates = sorted(item for item, count in Counter(clean_ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate finding IDs: {', '.join(duplicates)}")

    active = [
        item for item in findings
        if isinstance(item, dict)
        and item.get("status") not in {"dismissed", "resolved"}
        and item.get("severity") in {"critical", "major", "minor"}
    ]
    informational = [
        item for item in findings
        if isinstance(item, dict)
        and item.get("status") not in {"dismissed", "resolved"}
        and item.get("severity") == "info"
    ]
    substance_active = [
        item for item in active
        if not split_contract or item.get("report_channel", "substance") == "substance"
    ]
    writing_active = [
        item for item in active
        if split_contract and item.get("report_channel", "substance") == "writing"
    ]
    if split_contract:
        for item in findings:
            if not isinstance(item, dict):
                continue
            channel = item.get("report_channel", "substance")
            if channel not in {"substance", "writing"}:
                errors.append(f"finding {item.get('id')} has invalid report_channel {channel!r}")
            if channel == "writing" and (
                item.get("severity") not in {"minor", "info"} or item.get("essential") is True
            ):
                errors.append(
                    f"writing-channel finding {item.get('id')} must be minor/info and non-essential; "
                    "reclassify science-obscuring issues as substance"
                )
        for item in active:
            if item.get("data_limitation") != "inherent_but_claim_exceeds":
                continue
            quote_evidence = [
                evidence for evidence in item.get("evidence", [])
                if isinstance(evidence, dict)
                and evidence.get("type") == "quote"
                and isinstance(evidence.get("content"), str)
                and evidence.get("content", "").strip()
            ]
            if len(quote_evidence) < 2:
                errors.append(
                    f"v0.2+ inherent-data claim-scope finding {item.get('id')} requires separate quoted "
                    "evidence for the disclosure and the conflicting unhedged claim"
                )
    if current_contract:
        allowed_roles = {"potentially_dispositive", "posture_material", "revision_value", "polish"}
        allowed_repairs = {
            "within_current_design", "claim_narrowing", "additional_analysis", "new_evidence",
            "redesign", "unclear", "no_clear_fix",
        }
        for item in findings:
            if not isinstance(item, dict):
                continue
            if not isinstance(item.get("title"), str) or not item.get("title", "").strip():
                errors.append(f"v0.3 finding {item.get('id')} requires a consequence-centered title")
            role = item.get("decision_role")
            if role not in allowed_roles:
                errors.append(f"v0.3 finding {item.get('id')} has invalid decision_role {role!r}")
            repairability = item.get("repairability")
            if repairability not in allowed_repairs:
                errors.append(f"v0.3 finding {item.get('id')} has invalid repairability {repairability!r}")
            channel = item.get("report_channel", "substance")
            if channel == "writing" and role not in {"revision_value", "polish"}:
                errors.append(f"writing finding {item.get('id')} cannot be decision-role {role}")
            if item.get("essential") is not (role == "potentially_dispositive"):
                errors.append(
                    f"v0.3 finding {item.get('id')} essential must mirror potentially_dispositive decision role"
                )
            displayable_evidence = any(
                isinstance(evidence, dict)
                and (
                    (isinstance(evidence.get("content"), str) and bool(evidence.get("content", "").strip()))
                    or (
                        evidence.get("type") == "absence_scope"
                        and isinstance(evidence.get("scope_checked"), str)
                        and bool(evidence.get("scope_checked", "").strip())
                    )
                )
                for evidence in item.get("evidence", [])
            )
            if not displayable_evidence:
                errors.append(f"v0.3 finding {item.get('id')} requires displayable evidence content")
    if v4:
        burdens = run.get("activated_burdens", [])
        burden_ids = [row.get("id") for row in burdens if isinstance(row, dict)] if isinstance(burdens, list) else []
        duplicate_burdens = sorted(value for value, count in Counter(burden_ids).items() if value and count > 1)
        if duplicate_burdens:
            errors.append("run.json has duplicate burden IDs: " + ", ".join(duplicate_burdens))
        for item in findings:
            if not isinstance(item, dict):
                continue
            evidence_rows = [row for row in item.get("evidence", []) if isinstance(row, dict)]
            evidence_ids = {row.get("id") for row in evidence_rows if isinstance(row.get("id"), str)}
            display_id = item.get("display_evidence_id")
            related_ids = set(item.get("related_evidence_ids", [])) if isinstance(item.get("related_evidence_ids"), list) else set()
            if display_id not in evidence_ids:
                errors.append(f"finding {item.get('id')} display_evidence_id must reference its own evidence")
            unknown_related = sorted(related_ids - evidence_ids)
            if unknown_related:
                errors.append(f"finding {item.get('id')} has unknown related_evidence_ids: {', '.join(unknown_related)}")
            if display_id in related_ids:
                errors.append(f"finding {item.get('id')} display evidence must not be repeated as related evidence")
            counter = item.get("counterargument", {})
            if isinstance(counter, dict) and counter.get("result") == "not_applicable":
                if not (
                    item.get("report_channel") == "writing"
                    and item.get("severity") in {"minor", "info"}
                    and item.get("critique_basis") in {"reader_clarity", "formal_or_computational_error"}
                ):
                    errors.append(
                        f"finding {item.get('id')} may use counterargument not_applicable only for objective writing mechanics"
                    )
    if maximum_comments is not None and len(active) > maximum_comments:
        errors.append(f"detailed comments exceed run maximum: {len(active)} > {maximum_comments}")
    active_ranks = [item.get("importance_rank") for item in active]
    valid_active_ranks = [rank for rank in active_ranks if isinstance(rank, int) and not isinstance(rank, bool)]
    duplicate_ranks = sorted(rank for rank, count in Counter(valid_active_ranks).items() if count > 1)
    if duplicate_ranks:
        errors.append(f"duplicate importance ranks: {duplicate_ranks}")
    expected_ranks = list(range(1, len(active) + 1))
    if sorted(valid_active_ranks) != expected_ranks:
        errors.append(f"active importance ranks must be consecutive 1..{len(active)}")
    severity_counts = Counter(item.get("severity") for item in active + informational)
    essential_count = sum(bool(item.get("essential")) for item in active)
    if essential_count > 3 and not current_contract:
        errors.append(f"essential finding cap exceeded: {essential_count} > 3")
    if current_contract:
        role_priority = {
            "potentially_dispositive": 0,
            "posture_material": 1,
            "revision_value": 2,
            "polish": 3,
        }
        ranked_active = sorted(active, key=lambda item: item.get("importance_rank", 10**9))
        priorities = [role_priority.get(item.get("decision_role"), 99) for item in ranked_active]
        if priorities != sorted(priorities):
            errors.append("v0.3 importance order must place decision-relevant findings before revision value and polish")
    known_id_set = {item.get("id") for item in findings if isinstance(item, dict)}
    active_id_set = {item.get("id") for item in active}
    dependency_graph: dict[str, list[str]] = {}
    for item in active:
        finding_id = item.get("id")
        raw_dependencies = item.get("fix", {}).get("dependencies", [])
        dependencies = raw_dependencies if isinstance(raw_dependencies, list) else []
        dependency_graph[finding_id] = [value for value in dependencies if isinstance(value, str)]
        for dependency in dependency_graph[finding_id]:
            if current_contract and dependency == finding_id:
                errors.append(f"finding {finding_id} cannot depend on itself")
            elif current_contract and dependency not in known_id_set:
                errors.append(f"finding {finding_id} depends on unknown {dependency}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit_dependency(finding_id: str) -> None:
        if finding_id in visited:
            return
        if current_contract and finding_id in visiting:
            errors.append(f"fix dependencies contain a cycle involving {finding_id}")
            return
        visiting.add(finding_id)
        for dependency in dependency_graph.get(finding_id, []):
            if dependency in active_id_set and dependency in dependency_graph:
                visit_dependency(dependency)
        visiting.remove(finding_id)
        visited.add(finding_id)

    if current_contract:
        for finding_id in dependency_graph:
            visit_dependency(finding_id)
    expected_counts = {severity: severity_counts.get(severity, 0) for severity in SEVERITIES}
    expected_counts["essential"] = essential_count
    if run.get("counts") != expected_counts:
        errors.append(f"run.json.counts mismatch: expected {expected_counts}, got {run.get('counts')}")

    report_path = review_dir / "report.md"
    writing_report_path = review_dir / "writing-report.md"
    plan_path = review_dir / "fix-plan.md"
    synthesis_path = review_dir / "synthesis.json"
    required_output_paths = [report_path, plan_path]
    if split_contract and (run.get("mode") == "full" or writing_active):
        required_output_paths.append(writing_report_path)
    if current_contract:
        required_output_paths.append(synthesis_path)
    for path in required_output_paths:
        if not path.exists():
            errors.append(f"missing required file: {path}")
    synthesis: dict[str, Any] | None = None
    if current_contract and synthesis_path.exists():
        loaded_synthesis = load_json(synthesis_path, errors)
        if isinstance(loaded_synthesis, dict):
            synthesis = loaded_synthesis
            validate_schema(synthesis, "synthesis.schema.json", "synthesis.json", errors)
            if synthesis.get("review_id") != run.get("review_id"):
                errors.append("synthesis review_id differs from run.json")
            active_by_id = {item.get("id"): item for item in active}
            raw_concerns = synthesis.get("principal_concerns")
            concern_rows = [row for row in raw_concerns if isinstance(row, dict)] if isinstance(raw_concerns, list) else []
            concern_ids = [row.get("id") for row in concern_rows]
            if concern_ids != [f"PC-{index:02d}" for index in range(1, len(concern_ids) + 1)]:
                errors.append("principal concern IDs must be consecutive PC-01..PC-N")
            mapped_ids: list[str] = []
            for row in concern_rows:
                raw_finding_ids = row.get("finding_ids")
                finding_ids = raw_finding_ids if isinstance(raw_finding_ids, list) else []
                linked_findings: list[dict[str, Any]] = []
                for finding_id in finding_ids:
                    finding = active_by_id.get(finding_id)
                    if finding is None:
                        errors.append(f"principal concern {row.get('id')} references unknown or inactive {finding_id}")
                        continue
                    if finding.get("report_channel", "substance") != "substance":
                        errors.append(f"principal concern {row.get('id')} references writing finding {finding_id}")
                    linked_findings.append(finding)
                    mapped_ids.append(finding_id)
                if linked_findings:
                    expected_effect = (
                        "potentially_dispositive"
                        if any(finding.get("decision_role") == "potentially_dispositive" for finding in linked_findings)
                        else "posture_material"
                    )
                    if row.get("decision_effect") != expected_effect:
                        errors.append(
                            f"principal concern {row.get('id')} decision_effect must be {expected_effect}"
                        )
                    linked_repairs = {finding.get("repairability") for finding in linked_findings}
                    if row.get("repairability") not in linked_repairs:
                        errors.append(
                            f"principal concern {row.get('id')} repairability must match at least one linked finding"
                        )
            duplicated_mappings = sorted(
                finding_id for finding_id, count in Counter(mapped_ids).items() if count > 1
            )
            if duplicated_mappings:
                errors.append(
                    "principal concerns map findings more than once: " + ", ".join(duplicated_mappings)
                )
            dispositive_ids = {
                item.get("id") for item in substance_active
                if item.get("decision_role") == "potentially_dispositive"
            }
            if not dispositive_ids.issubset(set(mapped_ids)):
                errors.append(
                    "principal concerns omit potentially dispositive findings: "
                    + ", ".join(sorted(dispositive_ids - set(mapped_ids)))
                )
            raw_other_major_ids = synthesis.get("other_major_finding_ids")
            other_major_ids = set(raw_other_major_ids) if isinstance(raw_other_major_ids, list) else set()
            expected_other_major = {
                item.get("id") for item in substance_active
                if item.get("decision_role") == "posture_material" and item.get("id") not in set(mapped_ids)
            }
            if other_major_ids != expected_other_major:
                missing = sorted(expected_other_major - other_major_ids)
                extra = sorted(other_major_ids - expected_other_major)
                if missing:
                    errors.append("synthesis omits other major findings: " + ", ".join(missing))
                if extra:
                    errors.append("synthesis lists invalid other major findings: " + ", ".join(extra))
            if synthesis.get("writing_finding_count") != len(writing_active):
                errors.append(
                    f"synthesis writing_finding_count mismatch: expected {len(writing_active)}, "
                    f"got {synthesis.get('writing_finding_count')}"
                )
            if v4:
                expected_support: dict[tuple[str, str | None, int | None], str] = {
                    ("overall_assessment", None, None): str(synthesis.get("overall_assessment", "")),
                    ("posture_rationale", None, None): str(synthesis.get("posture_rationale", "")),
                    ("convincingness", None, None): str(synthesis.get("convincingness", "")),
                }
                for index, statement in enumerate(synthesis.get("strengths", [])):
                    expected_support[("strength", None, index)] = str(statement)
                for index, statement in enumerate(synthesis.get("upgrade_conditions", [])):
                    expected_support[("upgrade_condition", None, index)] = str(statement)
                for concern in concern_rows:
                    expected_support[("principal_concern_rationale", concern.get("id"), None)] = str(concern.get("rationale", ""))
                    expected_support[("principal_concern_upgrade", concern.get("id"), None)] = str(concern.get("upgrade_condition", ""))
                known_finding_ids = {row.get("id") for row in findings if isinstance(row, dict)}
                known_claim_ids = {
                    claim_id for row in findings if isinstance(row, dict)
                    for claim_id in row.get("claim_ids", []) if isinstance(claim_id, str)
                }
                known_evidence_ids = {
                    evidence.get("id") for row in findings if isinstance(row, dict)
                    for evidence in row.get("evidence", []) if isinstance(evidence, dict) and evidence.get("id")
                }
                seen_support: set[tuple[str, str | None, int | None]] = set()
                for mapping in synthesis.get("support_mappings", []):
                    if not isinstance(mapping, dict):
                        continue
                    key = (mapping.get("target_type"), mapping.get("target_id"), mapping.get("target_index"))
                    if key in seen_support:
                        errors.append(f"synthesis has duplicate support mapping for {key}")
                    seen_support.add(key)
                    expected_statement = expected_support.get(key)
                    if expected_statement is None:
                        errors.append(f"synthesis support mapping has unknown target {key}")
                    elif mapping.get("statement") != expected_statement:
                        errors.append(f"synthesis support mapping statement differs from target {key}")
                    unknown_claims = sorted(set(mapping.get("claim_ids", [])) - known_claim_ids)
                    unknown_findings = sorted(set(mapping.get("finding_ids", [])) - known_finding_ids)
                    unknown_evidence = sorted(set(mapping.get("evidence_ids", [])) - known_evidence_ids)
                    if unknown_claims:
                        errors.append("synthesis support mapping references unknown claims: " + ", ".join(unknown_claims))
                    if unknown_findings:
                        errors.append("synthesis support mapping references unknown findings: " + ", ".join(unknown_findings))
                    if unknown_evidence:
                        errors.append("synthesis support mapping references unknown evidence: " + ", ".join(unknown_evidence))
                missing_support = sorted(set(expected_support) - seen_support, key=str)
                if missing_support:
                    errors.append("synthesis statements missing structured support: " + ", ".join(map(str, missing_support)))
    if report_path.exists() and not split_contract:
        report = report_path.read_text(encoding="utf-8")
        if run.get("mode") == "full":
            for heading in (
                "## Is the argument convincing to a reader?",
                "## Writing, clarity, consistency, and typographical review",
                "## Reference accuracy and citation support",
            ):
                heading_match = re.search(rf"^{re.escape(heading)}\s*$", report, re.MULTILINE)
                if not heading_match:
                    errors.append(f"report.md is missing '{heading}'")
                    continue
                following = report[heading_match.end():]
                next_heading = re.search(r"^## ", following, re.MULTILINE)
                content = following[:next_heading.start()] if next_heading else following
                if not content.strip():
                    errors.append(f"report.md section '{heading}' must be non-empty")
        detail_match = re.search(r"^## Detailed Comments \((\d+)\)\s*$", report, re.MULTILINE)
        if not detail_match:
            errors.append("report.md is missing '## Detailed Comments (N)'")
        else:
            detail_start = detail_match.end()
            next_h2 = re.search(r"^## ", report[detail_start:], re.MULTILINE)
            detail_block = report[detail_start : detail_start + next_h2.start()] if next_h2 else report[detail_start:]
            comment_count = len(re.findall(r"^### \d+\. ", detail_block, re.MULTILINE))
            declared_count = int(detail_match.group(1))
            if declared_count != comment_count:
                errors.append(
                    f"Detailed Comments count mismatch: heading says {declared_count}, found {comment_count}"
                )
            if comment_count != len(active):
                errors.append(
                    f"Detailed Comments must contain every active finding exactly once: found {comment_count}, expected {len(active)}"
                )
            blocks = re.split(r"(?=^### \d+\. )", detail_block, flags=re.MULTILINE)
            blocks = [block for block in blocks if re.match(r"^### \d+\. ", block)]
            visible_numbers = [int(value) for value in re.findall(r"^### (\d+)\. ", detail_block, re.MULTILINE)]
            if visible_numbers != list(range(1, comment_count + 1)):
                errors.append("Detailed Comments visible numbering must be consecutive 1..N")
            block_quotes: list[str] = []
            feedback_texts: list[str] = []
            for block_index, block in enumerate(blocks, start=1):
                if len(re.findall(r"^\*\*Status\*\*: \[Pending\]\s*$", block, re.MULTILINE)) != 1:
                    errors.append(f"detailed comment {block_index} requires exactly one '**Status**: [Pending]' field")
                if len(re.findall(r"^\*\*Quote\*\*:\s*$", block, re.MULTILINE)) != 1:
                    errors.append(f"detailed comment {block_index} requires exactly one Quote field")
                quote_match = re.search(
                    r"^\*\*Quote\*\*:\s*\n(?P<quote>(?:^>.*(?:\n|$))+)", block, re.MULTILINE
                )
                quote_text = "" if not quote_match else re.sub(
                    r"^>\s?", "", quote_match.group("quote"), flags=re.MULTILINE
                ).strip()
                if not quote_text:
                    errors.append(f"detailed comment {block_index} requires a non-empty block quote")
                block_quotes.append(quote_text)
                feedback_match = re.search(r"^\*\*Feedback\*\*:\s*(?P<feedback>[\s\S]+?)\s*\Z", block, re.MULTILINE)
                feedback_text = "" if not feedback_match else feedback_match.group("feedback").strip()
                if len(re.findall(r"^\*\*Feedback\*\*:", block, re.MULTILINE)) != 1 or not feedback_text:
                    errors.append(f"detailed comment {block_index} requires exactly one non-empty Feedback field")
                feedback_texts.append(feedback_text)
            detail_ids = re.findall(r"<!-- finding_id: ([A-Z][A-Z0-9_-]*-[0-9]{2,}) -->", detail_block)
            if len(detail_ids) != comment_count:
                errors.append("each detailed comment requires exactly one hidden finding_id")
            expected_order = [
                item.get("id")
                for item in sorted(active, key=lambda item: item.get("importance_rank", 10**9))
            ]
            if detail_ids != expected_order:
                errors.append("Detailed Comments finding IDs must follow importance_rank order")
            findings_by_id = {item.get("id"): item for item in active}
            prohibited_feedback_phrases = (
                "As written,",
                "The strongest author-side defense is that",
                "The checked manuscript supports that defense only to this extent",
                "A proportionate repair is to",
                "leading-field verification requires",
                "the authors fail to",
                "the authors ignore",
                "There seems to be an issue",
                "The document would benefit from",
                "A careful reader cannot tell whether the stated claim is supported at the precision and scope presented.",
                "A careful reader may misread the object, unit, comparison, or evidentiary strength at this location.",
            )
            malformed_acronyms = ("vAR", "iRF", "hPI", "sVAR", "fOMC")
            for block_index, (finding_id, quote_text, feedback_text) in enumerate(
                zip(detail_ids, block_quotes, feedback_texts), start=1
            ):
                finding = findings_by_id.get(finding_id, {})
                evidence_texts = [
                    evidence.get("content")
                    for evidence in finding.get("evidence", [])
                    if isinstance(evidence, dict) and isinstance(evidence.get("content"), str)
                ]
                normalized_quote = normalize_quote(quote_text)
                if evidence_texts and not any(
                    normalized_quote in normalize_quote(evidence)
                    for evidence in evidence_texts
                ):
                    errors.append(f"detailed comment {block_index} quote does not match ledger evidence for {finding_id}")
                for phrase in prohibited_feedback_phrases:
                    if phrase.lower() in feedback_text.lower():
                        errors.append(f"detailed comment {block_index} uses prohibited boilerplate: {phrase}")
                for acronym in malformed_acronyms:
                    if acronym in feedback_text:
                        errors.append(f"detailed comment {block_index} contains malformed acronym {acronym}")
            sentence_owners: dict[str, set[str]] = {}
            major_label_signatures: list[tuple[str, ...]] = []
            for finding_id, feedback_text in zip(detail_ids, feedback_texts):
                for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\*\*[^*]+\*\*", "", feedback_text)):
                    normalized_sentence = " ".join(sentence.lower().split()).strip()
                    if len(normalized_sentence.split()) >= 10:
                        sentence_owners.setdefault(normalized_sentence, set()).add(finding_id)
                if findings_by_id.get(finding_id, {}).get("severity") in {"critical", "major"}:
                    labels = tuple(re.findall(r"\*\*([^*]+?)\.\*\*", feedback_text))
                    if labels:
                        major_label_signatures.append(labels)
            repeated_sentences = [
                (sentence, owners) for sentence, owners in sentence_owners.items() if len(owners) >= 3
            ]
            for sentence, owners in repeated_sentences:
                errors.append(
                    "detailed comments repeat a nontechnical sentence across "
                    f"{len(owners)} findings ({', '.join(sorted(owners))}): {sentence}"
                )
            if len(major_label_signatures) >= 6:
                signature_counts = Counter(major_label_signatures)
                signature, count = signature_counts.most_common(1)[0]
                if count > len(major_label_signatures) / 2:
                    errors.append(
                        "more than half of critical/major comments use the same label sequence: "
                        + " / ".join(signature)
                    )
        report_id_tokens = set(re.findall(r"\b[A-Z][A-Z0-9_-]*-[0-9]{2,}\b", report))
        for item in active:
            if item.get("id") not in report_id_tokens:
                errors.append(f"active finding {item.get('id')} is not referenced in report.md")
    if report_path.exists() and v2:
        report = report_path.read_text(encoding="utf-8")
        if run.get("mode") == "full":
            check_required_sections(
                report,
                "report.md",
                ("## Is the argument convincing to a reader?",),
                errors,
            )
        for heading in (
            "## Writing, clarity, consistency, and typographical review",
            "## Reference accuracy and citation support",
            "## Journal fit and submission strategy",
        ):
            if re.search(rf"^{re.escape(heading)}\s*$", report, re.MULTILINE):
                errors.append(
                    f"{heading} belongs in writing-report.md "
                    "(report.md is the substance-only referee report)"
                )
        report_ids = validate_comment_section(
            report, "report.md", "Detailed Comments", substance_active, errors
        )
        report_tokens = set(re.findall(r"\b[A-Z][A-Z0-9_-]*-[0-9]{2,}\b", report))
        for item in substance_active:
            if item.get("id") not in report_tokens:
                errors.append(f"active finding {item.get('id')} is not referenced in report.md")
        for item in writing_active:
            if item.get("id") in report_ids:
                errors.append(f"writing-channel finding {item.get('id')} must not appear in report.md")

    if report_path.exists() and current_contract:
        report = report_path.read_text(encoding="utf-8")
        required_headings = (
            "## Overall assessment",
            "## Recommendation and main grounds",
            "## Issues that could prevent publication",
            "## Other major issues",
            "## Is the argument convincing?",
        )
        check_required_sections(report, "report.md", required_headings, errors)
        positions = [report.find(heading) for heading in required_headings]
        if all(position >= 0 for position in positions) and positions != sorted(positions):
            errors.append("v0.3 referee-report synthesis headings are out of order")
        for heading in (
            "## Writing, clarity, consistency, and typographical review",
            "## Reference accuracy and citation support",
            "## Journal fit and submission strategy",
        ):
            if re.search(rf"^{re.escape(heading)}\s*$", report, re.MULTILINE):
                errors.append(
                    f"{heading} belongs in writing-report.md "
                    "(report.md is the substance-only referee report)"
                )
        if synthesis is not None:
            posture_labels = {
                "reject": "Reject",
                "weak_r_and_r": "Weak R&R",
                "strong_r_and_r": "Strong R&R",
                "accept": "Accept",
                "not_assessed": "Not assessed",
            }
            expected_posture = posture_labels.get(synthesis.get("review_posture"))
            posture_match = re.search(
                r"^\*\*(?:Recommendation|Review posture)\*\*:\s*(.+?)\s*$",
                report,
                re.MULTILINE,
            )
            if not posture_match or posture_match.group(1).strip() != expected_posture:
                errors.append(
                    f"report review posture must match synthesis.json: {expected_posture!r}"
                )
            concern_section = re.search(
                r"^## Issues that could prevent publication\s*$([\s\S]*?)(?=^## )",
                report,
                re.MULTILINE,
            )
            concern_block = concern_section.group(1) if concern_section else ""
            report_concern_ids = re.findall(r"<!-- principal_concern_id: (PC-[0-9]{2,}) -->", concern_block)
            raw_concerns = synthesis.get("principal_concerns")
            concern_rows = [row for row in raw_concerns if isinstance(row, dict)] if isinstance(raw_concerns, list) else []
            expected_concern_ids = [row.get("id") for row in concern_rows]
            if report_concern_ids != expected_concern_ids:
                errors.append("report principal concerns must match synthesis.json order exactly")
            for row in concern_rows:
                if row.get("title") not in concern_block:
                    errors.append(f"report omits principal concern title {row.get('title')!r}")
                raw_finding_ids = row.get("finding_ids")
                for finding_id in raw_finding_ids if isinstance(raw_finding_ids, list) else []:
                    if finding_id not in concern_block:
                        errors.append(
                            f"report principal concern {row.get('id')} omits linked finding {finding_id}"
                        )
            other_section = re.search(
                r"^## Other major issues\s*$([\s\S]*?)(?=^## )",
                report,
                re.MULTILINE,
            )
            other_block = other_section.group(1) if other_section else ""
            raw_other_major_ids = synthesis.get("other_major_finding_ids")
            for finding_id in raw_other_major_ids if isinstance(raw_other_major_ids, list) else []:
                if finding_id not in other_block:
                    errors.append(f"report other-major synthesis omits {finding_id}")
        report_ids = validate_comment_section_v3(
            report, "report.md", "Detailed Comments", substance_active, errors
        )
        report_tokens = set(re.findall(r"\b[A-Z][A-Z0-9_-]*-[0-9]{2,}\b", report))
        for item in substance_active:
            if item.get("id") not in report_tokens:
                errors.append(f"active finding {item.get('id')} is not referenced in report.md")
        for item in writing_active:
            if item.get("id") in report_ids:
                errors.append(f"writing-channel finding {item.get('id')} must not appear in report.md")

    if writing_report_path.exists() and v2:
        writing_report = writing_report_path.read_text(encoding="utf-8")
        if run.get("mode") == "full":
            check_required_sections(
                writing_report,
                "writing-report.md",
                (
                    "## Writing quality summary",
                    "## Grammar, typos, and mechanics",
                    "## Language consistency",
                    "## Style and writing improvement suggestions",
                    "## Reference accuracy and citation support",
                ),
                errors,
            )
        writing_ids = validate_comment_section(
            writing_report,
            "writing-report.md",
            "Detailed Writing Comments",
            writing_active,
            errors,
        )
        writing_tokens = set(re.findall(r"\b[A-Z][A-Z0-9_-]*-[0-9]{2,}\b", writing_report))
        for item in writing_active:
            if item.get("id") not in writing_tokens:
                errors.append(f"active finding {item.get('id')} is not referenced in writing-report.md")
        for item in substance_active:
            if item.get("id") in writing_ids:
                errors.append(f"substance-channel finding {item.get('id')} must not appear in writing-report.md")
    if writing_report_path.exists() and current_contract:
        writing_report = writing_report_path.read_text(encoding="utf-8")
        if run.get("mode") == "full":
            check_alternative_section_sets(
                writing_report,
                "writing-report.md",
                (
                    (
                        "## Writing assessment",
                        "## Highest-return writing revisions",
                        "## Section-by-section reader audit",
                        "## Terminology, definitions, and notation",
                        "## Tables and figures as writing",
                        "## Mechanics and copyedit inventory",
                    ),
                    (
                        "## Writing assessment",
                        "## Highest-return writing revisions",
                        "## Section-by-section reader audit",
                        "## Terminology, definitions, and notation",
                        "## Tables and figures as writing",
                        "## Mechanics and copyedit inventory",
                        "## References and citation integrity",
                    ),
                    (
                        "## Writing quality summary",
                        "## Grammar, typos, and mechanics",
                        "## Language consistency",
                        "## Style and writing improvement suggestions",
                        "## Reference accuracy and citation support",
                    ),
                ),
                errors,
            )
        writing_ids = validate_comment_section_v3(
            writing_report,
            "writing-report.md",
            "Detailed Writing Comments",
            writing_active,
            errors,
        )
        writing_tokens = set(re.findall(r"\b[A-Z][A-Z0-9_-]*-[0-9]{2,}\b", writing_report))
        for item in writing_active:
            if item.get("id") not in writing_tokens:
                errors.append(f"active finding {item.get('id')} is not referenced in writing-report.md")
        for item in substance_active:
            if item.get("id") in writing_ids:
                errors.append(f"substance-channel finding {item.get('id')} must not appear in writing-report.md")
    if plan_path.exists():
        plan = plan_path.read_text(encoding="utf-8")
        plan_ids = re.findall(r"^### ([A-Z][A-Z0-9_-]*-[0-9]{2,}):", plan, re.MULTILINE)
        active_ids = {item.get("id") for item in active}
        unknown_plan_ids = sorted(set(plan_ids) - active_ids)
        if unknown_plan_ids:
            errors.append("fix-plan.md contains unknown task headings: " + ", ".join(unknown_plan_ids))
        for item in active:
            count = plan_ids.count(item.get("id"))
            if count == 0:
                errors.append(f"active finding {item.get('id')} is not referenced in fix-plan.md")
            elif count != 1:
                errors.append(f"active finding {item.get('id')} must appear exactly once in fix-plan.md")
        if split_contract:
            closure_lines = [
                " ".join(value.lower().split())
                for value in re.findall(
                    r"(?:\*\*(?:Done when|Completion evidence):\*\*|Completion evidence:)\s*([^\n]+)",
                    plan,
                )
            ]
            repeated_closures = [
                text for text, count in Counter(closure_lines).items() if text and count > 1
            ]
            if repeated_closures:
                errors.append("fix-plan.md repeats a generic completion condition across items")

    if run.get("status") == "complete":
        if run.get("verification_passed") is not True:
            errors.append("complete run requires verification_passed=true")
        if split_contract and not isinstance(run.get("telemetry"), dict):
            errors.append("complete v0.2+ run requires run.json.telemetry")
        if len(active) < minimum_target:
            coverage_probe = load_json(review_dir / "evidence/coverage.json", errors)
            sweep = coverage_probe.get("second_sweep", {}) if isinstance(coverage_probe, dict) else {}
            if not (
                isinstance(sweep, dict)
                and sweep.get("completed") is True
                and isinstance(sweep.get("shortfall_explanation"), str)
                and sweep.get("shortfall_explanation", "").strip()
            ):
                errors.append(
                    f"complete run falls below the requested comment target without a documented second-sweep shortfall: {len(active)} < {minimum_target}"
                )
        if run.get("mode") == "full" and comment_policy.get("exhaustive") is not True:
            errors.append("complete full run requires comment_policy.exhaustive=true")
        if stage_status and any(stage_status.get(stage) not in {"passed", "bounded", "not_applicable"} for stage in required_stages):
            errors.append("complete run contains an unfinished or failed stage")
        if run.get("mode") == "full" and stage_status:
            for stage in {"audit", "counterargument", "synthesis", "verification", "delivery"}:
                if stage_status.get(stage) != "passed":
                    errors.append(f"complete full run requires stage '{stage}' to be passed")
        for item in active:
            if item.get("verification") != "passed":
                errors.append(f"complete run requires passed verification for {item.get('id')}")
            if item.get("support_state") not in {"supported", "partially_supported", "in_conflict"}:
                errors.append(
                    f"complete run cannot report unresolved support state {item.get('support_state')!r} for {item.get('id')}"
                )
        required_artifacts = [
            "evidence/reconstruction.md",
            "evidence/sources.md",
            "evidence/verification.md",
        ]
        if run.get("mode") == "full":
            required_artifacts.append("evidence/reader-claim-audit.md")
            required_artifacts.append("evidence/claims.json")
            required_artifacts.append("evidence/figures.md")
            required_artifacts.append("evidence/figures.json")
            required_artifacts.append("evidence/tables.md")
            required_artifacts.append("evidence/tables.json")
            required_artifacts.append("evidence/analytical-audit.md")
            required_artifacts.append("evidence/analytical-audit.json")
            required_artifacts.append("evidence/writing.md")
            required_artifacts.append("evidence/writing.json")
            required_artifacts.append("evidence/coverage.md")
            required_artifacts.append("evidence/coverage.json")
        for relative in required_artifacts:
            artifact_path = review_dir / relative
            if not artifact_path.exists():
                errors.append(f"complete run missing audit artifact: {relative}")
            elif artifact_path.suffix == ".md" and not artifact_path.read_text(encoding="utf-8").strip():
                errors.append(f"complete run audit artifact is empty: {relative}")

        if run.get("mode") == "full":
            boundary = run.get("assessment_boundary", {})
            sources = boundary.get("sources", []) if isinstance(boundary, dict) else []
            if not sources:
                errors.append("complete full run requires at least one recorded manuscript source")
            elif not any(
                isinstance(source, dict) and source.get("status") in {"fully_read", "partially_read"}
                for source in sources
            ):
                errors.append("complete full run requires a manuscript source marked fully_read or partially_read")

        if v4:
            if run.get("mode") == "full":
                burden_ids = {
                    row.get("id") for row in run.get("activated_burdens", []) if isinstance(row, dict)
                }
                missing_views = sorted(
                    {"logical_validity", "technical_validity", "methodological_validity"} - burden_ids
                )
                if missing_views:
                    errors.append(
                        "complete full v0.4 run must decide the logical, technical, and methodological audit views: "
                        + ", ".join(missing_views)
                    )
            errors.extend(validate_trust_spine(review_dir, run, ledger, validate_schema))
            structured_verification = load_json(review_dir / "evidence/verification.json", errors)
            readable_verification = review_dir / "evidence" / "verification.md"
            if isinstance(structured_verification, dict) and readable_verification.exists():
                try:
                    expected_verification = render_verification(structured_verification)
                    if readable_verification.read_text(encoding="utf-8") != expected_verification:
                        errors.append("evidence/verification.md is not synchronized with verification.json")
                except (OSError, UnicodeError, TypeError, ValueError) as exc:
                    errors.append(f"cannot render canonical verification audit: {exc}")
            validate_finalization_receipt(review_dir, run.get("review_id"), errors)

        coverage_unit_ids: set[str] = set()
        table_coverage_ids: set[str] = set()
        coverage_dimensions_by_id: dict[str, dict[str, Any]] = {}
        coverage_path = review_dir / "evidence/coverage.json"
        if run.get("mode") == "full" and coverage_path.exists():
            coverage = load_json(coverage_path, errors)
            if isinstance(coverage, dict):
                validate_schema(coverage, "coverage.schema.json", "evidence/coverage.json", errors)
                if coverage.get("review_id") != run.get("review_id"):
                    errors.append("coverage review_id differs from run.json")
                branches = set(coverage.get("branches_applied", []))
                required_branch = {
                    "empirical": "empirical",
                    "descriptive": "descriptive",
                    "structural-quantitative": "structural",
                    "macro": "macro",
                    "theory": "theory",
                    "hybrid": "mixed",
                }.get(run.get("paper_family"))
                if "universal" not in branches:
                    errors.append("full coverage requires the universal branch")
                if required_branch and required_branch not in branches:
                    errors.append(f"coverage is missing required branch '{required_branch}'")
                known_ids = set(clean_ids)
                covered_ids: set[str] = set()
                for collection_name in ("units", "dimensions"):
                    rows = coverage.get(collection_name, [])
                    for row in rows if isinstance(rows, list) else []:
                        if not isinstance(row, dict):
                            continue
                        row_ids = row.get("finding_ids", [])
                        if isinstance(row_ids, list):
                            covered_ids.update(row_ids)
                        if row.get("status") == "findings" and not row_ids:
                            errors.append(f"coverage {collection_name} row '{row.get('id')}' has findings status but no IDs")
                        if row.get("status") != "findings" and row_ids:
                            errors.append(f"coverage {collection_name} row '{row.get('id')}' has IDs without findings status")
                unknown_coverage_ids = sorted(covered_ids - known_ids)
                if unknown_coverage_ids:
                    errors.append(f"coverage references unknown finding IDs: {', '.join(unknown_coverage_ids)}")
                active_ids = {item.get("id") for item in active}
                unit_rows = [row for row in coverage.get("units", []) if isinstance(row, dict)]
                unit_id_list = [row.get("id") for row in unit_rows if row.get("id")]
                duplicate_unit_ids = sorted(item for item, count in Counter(unit_id_list).items() if count > 1)
                if duplicate_unit_ids:
                    errors.append(f"duplicate coverage unit IDs: {', '.join(duplicate_unit_ids)}")
                coverage_unit_ids = set(unit_id_list)
                table_coverage_ids = {
                    row.get("id") for row in unit_rows if row.get("type") == "table" and row.get("id")
                }
                missing_coverage_ids = sorted(active_ids - covered_ids)
                if missing_coverage_ids:
                    errors.append(f"active findings missing from coverage: {', '.join(missing_coverage_ids)}")
                dimension_rows = [row for row in coverage.get("dimensions", []) if isinstance(row, dict)]
                coverage_dimensions_by_id = {
                    row.get("id"): row for row in dimension_rows if row.get("id")
                }
                dimension_id_list = [row.get("id") for row in dimension_rows if row.get("id")]
                duplicate_dimension_ids = sorted(item for item, count in Counter(dimension_id_list).items() if count > 1)
                if duplicate_dimension_ids:
                    errors.append(f"duplicate coverage dimension IDs: {', '.join(duplicate_dimension_ids)}")
                dimension_ids = set(dimension_id_list)
                required_universal_dimensions = {
                    "contribution-literature",
                    "reader-clarity",
                    "claim-consistency",
                    "data-provenance-sample",
                    "measurement-variables",
                    "identification-assumptions-estimand",
                    "estimation-computation-inference",
                    "equations-logic-units",
                    "results-magnitudes-exhibits",
                    "robustness-mechanisms-policy",
                    "reproducibility-documentation",
                    "terms-variables",
                    "data-limitation-fairness",
                    "review-tone",
                    "writing-typography",
                    "language-mechanics",
                    "rendered-table-integrity",
                    "partition-regime",
                    "measure-algebra",
                    "assumption-implementation",
                    "derived-number-traceability",
                    "comparison-harmonization",
                    "timing-test-semantics",
                    "availability-exclusivity",
                }
                missing_reader_dimensions = sorted(required_universal_dimensions - dimension_ids)
                if missing_reader_dimensions:
                    errors.append(
                        "coverage is missing required audit dimensions: "
                        + ", ".join(missing_reader_dimensions)
                    )
                conditionally_applicable_dimensions = {
                    "data-limitation-fairness",
                    "rendered-table-integrity",
                    "partition-regime",
                    "measure-algebra",
                    "derived-number-traceability",
                    "comparison-harmonization",
                    "timing-test-semantics",
                    "availability-exclusivity",
                }
                if run.get("paper_family") in {"theory", "macro"}:
                    conditionally_applicable_dimensions.add("data-provenance-sample")
                    conditionally_applicable_dimensions.add("estimation-computation-inference")
                never_na = required_universal_dimensions - conditionally_applicable_dimensions
                for row in dimension_rows:
                    if row.get("id") in never_na and row.get("status") == "not_applicable":
                        errors.append(f"universal coverage dimension '{row.get('id')}' cannot be not_applicable")
                    if row.get("status") == "bounded" and not row.get("notes", "").strip():
                        errors.append(f"bounded coverage dimension '{row.get('id')}' requires a boundary note")
                if branches & {"empirical", "descriptive", "structural", "mixed"}:
                    fairness_rows = [row for row in dimension_rows if row.get("id") == "data-limitation-fairness"]
                    if fairness_rows and fairness_rows[0].get("status") == "not_applicable":
                        errors.append("data-limitation-fairness cannot be not_applicable for a data-using paper family")
                sweep = coverage.get("second_sweep", {})
                if comment_policy.get("exhaustive") is True:
                    if not isinstance(sweep, dict) or sweep.get("required") is not True or sweep.get("completed") is not True:
                        errors.append("exhaustive full review requires a completed second sweep")
                # Do not infer a quota from manuscript length. The explicit
                # comment policy and recorded coverage determine sufficiency.

        claims_path = review_dir / "evidence/claims.json"
        if run.get("mode") == "full" and claims_path.exists():
            claims = load_json(claims_path, errors)
            if isinstance(claims, dict):
                validate_schema(claims, "claims.schema.json", "evidence/claims.json", errors)
                if claims.get("review_id") != run.get("review_id"):
                    errors.append("claims review_id differs from run.json")
                families = {
                    family.get("id"): family
                    for family in claims.get("claim_families", [])
                    if isinstance(family, dict) and family.get("id")
                }
                active_by_id = {item.get("id"): item for item in active}
                claim_family_ids = [
                    family.get("id") for family in claims.get("claim_families", [])
                    if isinstance(family, dict) and family.get("id")
                ]
                duplicate_claim_ids = sorted(item for item, count in Counter(claim_family_ids).items() if count > 1)
                if duplicate_claim_ids:
                    errors.append(f"duplicate claim family IDs: {', '.join(duplicate_claim_ids)}")
                scope = claims.get("audit_scope", {})
                scope_units = set(scope.get("coverage_unit_ids", [])) if isinstance(scope, dict) else set()
                if scope_units != coverage_unit_ids:
                    missing = sorted(coverage_unit_ids - scope_units)
                    extra = sorted(scope_units - coverage_unit_ids)
                    if missing:
                        errors.append(f"claims audit scope omits coverage units: {', '.join(missing)}")
                    if extra:
                        errors.append(f"claims audit scope references unknown coverage units: {', '.join(extra)}")
                headline_ids = set(scope.get("headline_claim_ids", [])) if isinstance(scope, dict) else set()
                expected_headline_ids = {
                    family.get("id") for family in claims.get("claim_families", [])
                    if isinstance(family, dict) and family.get("is_headline") is True
                }
                if headline_ids != expected_headline_ids:
                    errors.append("claims audit headline_claim_ids must exactly match is_headline claim families")
                occurrence_ids: list[str] = []
                for finding in active:
                    finding_id = finding.get("id")
                    for claim_id in finding.get("claim_ids", []):
                        if claim_id not in families:
                            errors.append(f"active finding {finding_id} references unknown claim family {claim_id}")
                        elif finding_id not in families[claim_id].get("finding_ids", []):
                            errors.append(f"claim family {claim_id} does not map back to active finding {finding_id}")
                for claim_id, family in families.items():
                    for finding_id in family.get("finding_ids", []):
                        if finding_id not in active_by_id:
                            errors.append(f"claim family {claim_id} references unknown or inactive finding {finding_id}")
                    for occurrence in family.get("occurrences", []):
                        if not isinstance(occurrence, dict):
                            continue
                        occurrence_ids.append(occurrence.get("id"))
                        if occurrence.get("coverage_unit_id") not in coverage_unit_ids:
                            errors.append(
                                f"claim occurrence {occurrence.get('id')} references unknown coverage unit {occurrence.get('coverage_unit_id')}"
                            )
                        unsafe = {
                            "qualifier_loss", "scope_expansion", "strength_inflation",
                            "benchmark_or_definition_drift", "numerical_conflict", "direct_contradiction",
                        }
                        if occurrence.get("relation_to_canonical") in unsafe and not family.get("finding_ids"):
                            errors.append(
                                f"unsafe claim occurrence {occurrence.get('id')} must map to an active finding"
                            )
                duplicate_occurrence_ids = sorted(item for item, count in Counter(occurrence_ids).items() if item and count > 1)
                if duplicate_occurrence_ids:
                    errors.append(f"duplicate claim occurrence IDs: {', '.join(duplicate_occurrence_ids)}")

                def validate_mapped_rows(rows: Any, kind: str, adverse: set[str]) -> None:
                    if not isinstance(rows, list):
                        return
                    row_ids = [row.get("id") for row in rows if isinstance(row, dict) and row.get("id")]
                    duplicates = sorted(item for item, count in Counter(row_ids).items() if count > 1)
                    if duplicates:
                        errors.append(f"duplicate {kind} IDs: {', '.join(duplicates)}")
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        for unit_id in ([row.get("coverage_unit_id")] if kind == "reader-map" else row.get("coverage_unit_ids", [])):
                            if unit_id not in coverage_unit_ids:
                                errors.append(f"{kind} {row.get('id')} references unknown coverage unit {unit_id}")
                        raw_mapped = row.get("finding_ids", [])
                        mapped = raw_mapped if isinstance(raw_mapped, list) else []
                        for finding_id in mapped:
                            if finding_id not in active_by_id:
                                errors.append(f"{kind} {row.get('id')} references unknown or inactive finding {finding_id}")
                        if row.get("status") in adverse and not mapped:
                            if kind == "reader-map" and isinstance(row.get("bounded_reason"), str) and row.get("bounded_reason", "").strip():
                                continue
                            errors.append(f"adverse {kind} state {row.get('id')} must map to an active finding")

                validate_mapped_rows(claims.get("reader_map"), "reader-map", {"unclear", "inconsistent"})
                validate_mapped_rows(claims.get("terms"), "term", {"undefined", "inconsistent", "overloaded"})
                for structured_name in ("central_argument_assessment", "writing_audit"):
                    structured = claims.get(structured_name, {})
                    if isinstance(structured, dict):
                        for finding_id in structured.get("finding_ids", []):
                            if finding_id not in active_by_id:
                                errors.append(f"{structured_name} references unknown or inactive finding {finding_id}")

        figures_path = review_dir / "evidence/figures.json"
        if run.get("mode") == "full" and figures_path.exists():
            figures = load_json(figures_path, errors)
            if isinstance(figures, dict):
                validate_schema(figures, "figures.schema.json", "evidence/figures.json", errors)
                if figures.get("review_id") != run.get("review_id"):
                    errors.append("figures review_id differs from run.json")
                rows = [row for row in figures.get("figures", []) if isinstance(row, dict)]
                if current_contract:
                    boundary = run.get("assessment_boundary")
                    boundary_figures = boundary.get("figures") if isinstance(boundary, dict) else None
                    no_figures = figures.get("no_figures_confirmed") is True
                    if no_figures and boundary_figures != "not_present":
                        errors.append(
                            "run.json assessment_boundary.figures must be 'not_present' "
                            "when the figure audit confirms that the paper has no figures"
                        )
                    if not no_figures and boundary_figures == "not_present":
                        errors.append(
                            "run.json assessment_boundary.figures cannot be 'not_present' "
                            "when the figure audit contains or expects figures"
                        )
                figure_ids = [row.get("id") for row in rows if row.get("id")]
                duplicate_figure_ids = sorted(item for item, count in Counter(figure_ids).items() if count > 1)
                if duplicate_figure_ids:
                    errors.append(f"duplicate figure IDs: {', '.join(duplicate_figure_ids)}")
                active_ids = {item.get("id") for item in active}
                for row in rows:
                    mapped = row.get("finding_ids", [])
                    for finding_id in mapped:
                        if finding_id not in active_ids:
                            errors.append(f"figure {row.get('id')} references unknown or inactive finding {finding_id}")
                    if (
                        row.get("visual_status") == "issue"
                        or row.get("caption_text_status") == "issue"
                        or row.get("claim_correspondence_status") == "issue"
                    ) and not mapped:
                        errors.append(f"adverse figure state {row.get('id')} must map to an active finding")
                    for extraction_path in row.get("extraction_paths", []):
                        validate_local_asset_path(
                            review_dir,
                            extraction_path,
                            f"figure {row.get('id')} extraction path",
                            errors,
                        )
                for finding in active:
                    finding_id = finding.get("id")
                    for item in finding.get("evidence", []):
                        if not isinstance(item, dict) or item.get("type") != "figure":
                            continue
                        exhibit = item.get("locator", {}).get("exhibit") if isinstance(item.get("locator"), dict) else None
                        target = normalized_exhibit_label("figure", exhibit)
                        matches = [
                            row for row in rows
                            if (
                                normalized_exhibit_label("figure", row.get("label")) == target
                                or normalized_exhibit_label("figure", row.get("label")).startswith(target + ":")
                            )
                        ]
                        if not matches:
                            errors.append(f"figure evidence for {finding_id} has no matching figure-audit row: {exhibit}")
                        elif not any(finding_id in row.get("finding_ids", []) for row in matches):
                            errors.append(f"figure evidence for {finding_id} is not mapped back from figure audit: {exhibit}")

        tables_path = review_dir / "evidence/tables.json"
        if run.get("mode") == "full" and tables_path.exists():
            tables = load_json(tables_path, errors)
            if isinstance(tables, dict):
                validate_schema(tables, "tables.schema.json", "evidence/tables.json", errors)
                if tables.get("review_id") != run.get("review_id"):
                    errors.append("tables review_id differs from run.json")
                rows = [row for row in tables.get("tables", []) if isinstance(row, dict)]
                table_ids = [row.get("id") for row in rows if row.get("id")]
                duplicate_table_ids = sorted(item for item, count in Counter(table_ids).items() if count > 1)
                if duplicate_table_ids:
                    errors.append(f"duplicate table IDs: {', '.join(duplicate_table_ids)}")
                mapped_coverage_ids = [row.get("coverage_unit_id") for row in rows if row.get("coverage_unit_id")]
                duplicate_table_units = sorted(
                    item for item, count in Counter(mapped_coverage_ids).items() if count > 1
                )
                if duplicate_table_units:
                    errors.append(
                        "table audit maps coverage units more than once: " + ", ".join(duplicate_table_units)
                    )
                mapped_table_units = set(mapped_coverage_ids)
                if mapped_table_units != table_coverage_ids:
                    missing = sorted(table_coverage_ids - mapped_table_units)
                    extra = sorted(mapped_table_units - table_coverage_ids)
                    if missing:
                        errors.append("table audit omits coverage units: " + ", ".join(missing))
                    if extra:
                        errors.append("table audit references non-table coverage units: " + ", ".join(extra))
                if table_coverage_ids and tables.get("no_tables_confirmed") is True:
                    errors.append("table audit cannot confirm no tables when coverage contains table units")
                if not table_coverage_ids and tables.get("no_tables_confirmed") is not True:
                    errors.append("table-free coverage requires no_tables_confirmed=true")
                active_ids = {item.get("id") for item in active}
                for row in rows:
                    mapped = row.get("finding_ids", [])
                    for finding_id in mapped:
                        if finding_id not in active_ids:
                            errors.append(f"table {row.get('id')} references unknown or inactive finding {finding_id}")
                    adverse = (
                        row.get("visual_status") == "issue"
                        or row.get("claim_correspondence_status") == "issue"
                        or row.get("extraction_status") == "conflict_unresolved"
                    )
                    if adverse and not mapped:
                        errors.append(f"adverse table state {row.get('id')} must map to an active finding")
                    if row.get("render_status") != "inspected" and row.get("visual_status") != "bounded":
                        errors.append(f"table {row.get('id')} must be rendered and inspected or explicitly bounded")
                    if row.get("extraction_status") == "conflict_unresolved" and run.get("status") == "complete":
                        errors.append(f"complete review cannot leave table extraction conflict unresolved: {row.get('id')}")
                    checks = row.get("checks", {})
                    if isinstance(checks, dict):
                        adverse_checks = [
                            name for name, check in checks.items()
                            if isinstance(check, dict) and check.get("status") == "issue"
                        ]
                        if adverse_checks and not mapped:
                            errors.append(
                                f"adverse table checks for {row.get('id')} must map to an active finding: "
                                + ", ".join(adverse_checks)
                            )
                    for render_path in row.get("render_paths", []):
                        validate_local_asset_path(
                            review_dir,
                            render_path,
                            f"table {row.get('id')} render path",
                            errors,
                        )
                for finding in active:
                    finding_id = finding.get("id")
                    for item in finding.get("evidence", []):
                        if not isinstance(item, dict) or item.get("type") != "table_cell":
                            continue
                        exhibit = item.get("locator", {}).get("exhibit") if isinstance(item.get("locator"), dict) else None
                        target = normalized_exhibit_label("table", exhibit)
                        matches = [
                            row for row in rows
                            if normalized_exhibit_label("table", row.get("label")) == target
                        ]
                        if not matches:
                            errors.append(f"table-cell evidence for {finding_id} has no matching table-audit row: {exhibit}")
                        elif not any(finding_id in row.get("finding_ids", []) for row in matches):
                            errors.append(f"table-cell evidence for {finding_id} is not mapped back from table audit: {exhibit}")
                if run.get("status") == "complete":
                    for row in rows:
                        if row.get("render_status") != "inspected":
                            errors.append(
                                f"complete review requires a saved inspected render for table {row.get('id')}"
                            )

        analytical_path = review_dir / "evidence/analytical-audit.json"
        if run.get("mode") == "full" and analytical_path.exists():
            analytical = load_json(analytical_path, errors)
            if isinstance(analytical, dict):
                validate_schema(
                    analytical,
                    "analytical-audit.schema.json",
                    "evidence/analytical-audit.json",
                    errors,
                )
                if analytical.get("review_id") != run.get("review_id"):
                    errors.append("analytical-audit review_id differs from run.json")
                scope = analytical.get("scope", {})
                scope_units = set(scope.get("coverage_unit_ids", [])) if isinstance(scope, dict) else set()
                if scope_units != coverage_unit_ids:
                    missing = sorted(coverage_unit_ids - scope_units)
                    extra = sorted(scope_units - coverage_unit_ids)
                    if missing:
                        errors.append("analytical audit scope omits coverage units: " + ", ".join(missing))
                    if extra:
                        errors.append(
                            "analytical audit scope references unknown coverage units: " + ", ".join(extra)
                        )
                domains = [row for row in analytical.get("domains", []) if isinstance(row, dict)]
                expected_domains = {
                    "partition-regime",
                    "measure-algebra",
                    "assumption-implementation",
                    "derived-number",
                    "comparison-harmonization",
                    "timing-test",
                    "availability-exclusivity",
                }
                kinds = [row.get("kind") for row in domains if row.get("kind")]
                duplicates = sorted(item for item, count in Counter(kinds).items() if count > 1)
                if duplicates:
                    errors.append("duplicate analytical-ledger domains: " + ", ".join(duplicates))
                missing_domains = sorted(expected_domains - set(kinds))
                if missing_domains:
                    errors.append("analytical audit is missing domains: " + ", ".join(missing_domains))
                active_ids = {item.get("id") for item in active}
                entry_ids: list[str] = []
                coverage_dimension_for_domain = {
                    "partition-regime": "partition-regime",
                    "measure-algebra": "measure-algebra",
                    "assumption-implementation": "assumption-implementation",
                    "derived-number": "derived-number-traceability",
                    "comparison-harmonization": "comparison-harmonization",
                    "timing-test": "timing-test-semantics",
                    "availability-exclusivity": "availability-exclusivity",
                }
                for domain in domains:
                    domain_units = set(domain.get("coverage_unit_ids", []))
                    unknown_units = sorted(domain_units - coverage_unit_ids)
                    if unknown_units:
                        errors.append(
                            f"analytical domain {domain.get('kind')} references unknown coverage units: "
                            + ", ".join(unknown_units)
                        )
                    entries = [row for row in domain.get("entries", []) if isinstance(row, dict)]
                    if domain.get("status") == "complete" and not entries:
                        errors.append(f"complete analytical domain {domain.get('kind')} requires at least one entry")
                    if domain.get("status") == "complete" and not domain_units:
                        errors.append(f"complete analytical domain {domain.get('kind')} requires a non-empty scope")
                    if domain.get("status") in {"bounded", "not_applicable"} and not domain.get("notes", "").strip():
                        errors.append(f"{domain.get('status')} analytical domain {domain.get('kind')} requires notes")
                    entry_unit_union: set[str] = set()
                    domain_finding_union: set[str] = set()
                    for entry in entries:
                        entry_ids.append(entry.get("id"))
                        generic_audit_phrases = {
                            "checked", "reviewed", "clear", "no issue", "no issues",
                            "not applicable", "completed", "done",
                        }
                        generic_audit_prefixes = (
                            "all applicable objects were reviewed",
                            "all relevant material was checked",
                            "the audit was completed",
                            "checked within the assessment boundary",
                            "reviewed within the assessment boundary",
                        )
                        evidence_summary = entry.get("evidence", "")
                        normalized_summary = " ".join(evidence_summary.lower().split()).strip(".") if isinstance(evidence_summary, str) else ""
                        if (
                            not isinstance(evidence_summary, str)
                            or len(evidence_summary.split()) < 5
                            or normalized_summary in generic_audit_phrases
                            or normalized_summary.startswith(generic_audit_prefixes)
                        ):
                            errors.append(
                                f"analytical entry {entry.get('id')} needs paper-specific evidence, not a generic completion assertion"
                            )
                        for locator_index, locator in enumerate(entry.get("evidence_locators", [])):
                            content = locator.get("content", "") if isinstance(locator, dict) else ""
                            if not isinstance(content, str) or len(content.split()) < 4:
                                errors.append(
                                    f"analytical entry {entry.get('id')} evidence locator {locator_index + 1} needs substantive source content"
                                )
                        entry_units = set(entry.get("coverage_unit_ids", []))
                        entry_unit_union.update(entry_units)
                        if not entry_units:
                            errors.append(f"analytical entry {entry.get('id')} requires at least one coverage unit")
                        unknown_entry_units = sorted(entry_units - domain_units)
                        if unknown_entry_units:
                            errors.append(
                                f"analytical entry {entry.get('id')} falls outside its domain scope: "
                                + ", ".join(unknown_entry_units)
                            )
                        mapped = entry.get("finding_ids", [])
                        domain_finding_union.update(mapped)
                        for finding_id in mapped:
                            if finding_id not in active_ids:
                                errors.append(
                                    f"analytical entry {entry.get('id')} references unknown or inactive finding {finding_id}"
                                )
                        checks = [check for check in entry.get("checks", []) if isinstance(check, dict)]
                        check_ids = [check.get("id") for check in checks if check.get("id")]
                        duplicate_checks = sorted(
                            item for item, count in Counter(check_ids).items() if count > 1
                        )
                        if duplicate_checks:
                            errors.append(
                                f"analytical entry {entry.get('id')} repeats checks: "
                                + ", ".join(duplicate_checks)
                            )
                        check_statuses = {check.get("status") for check in checks}
                        for check in checks:
                            result = check.get("result", "")
                            normalized_result = " ".join(result.lower().split()).strip(".") if isinstance(result, str) else ""
                            if (
                                not isinstance(result, str)
                                or len(result.split()) < 5
                                or normalized_result in generic_audit_phrases
                                or normalized_result.startswith(generic_audit_prefixes)
                            ):
                                errors.append(
                                    f"analytical check {entry.get('id')}/{check.get('id')} needs a paper-specific result"
                                )
                        adverse_check = "issue" in check_statuses
                        if (entry.get("status") == "issue" or adverse_check) and not mapped:
                            errors.append(
                                f"adverse analytical entry {entry.get('id')} must map to an active finding"
                            )
                        if entry.get("status") == "issue" and not adverse_check:
                            errors.append(f"issue analytical entry {entry.get('id')} requires an issue check")
                        if entry.get("status") == "clear" and check_statuses - {"clear", "not_applicable"}:
                            errors.append(f"clear analytical entry {entry.get('id')} has a non-clear check")
                        if entry.get("status") == "bounded" and not ({"bounded", "issue"} & check_statuses):
                            errors.append(f"bounded analytical entry {entry.get('id')} requires a bounded or issue check")
                    if domain.get("status") == "complete" and entry_unit_union != domain_units:
                        missing = sorted(domain_units - entry_unit_union)
                        extra = sorted(entry_unit_union - domain_units)
                        if missing:
                            errors.append(
                                f"analytical domain {domain.get('kind')} has scope not covered by entries: "
                                + ", ".join(missing)
                            )
                        if extra:
                            errors.append(
                                f"analytical domain {domain.get('kind')} entries exceed domain scope: "
                                + ", ".join(extra)
                            )
                    coverage_dimension_id = coverage_dimension_for_domain.get(domain.get("kind"))
                    coverage_row = coverage_dimensions_by_id.get(coverage_dimension_id, {})
                    if domain_finding_union != set(coverage_row.get("finding_ids", [])):
                        errors.append(
                            f"analytical domain {domain.get('kind')} finding links do not match coverage dimension {coverage_dimension_id}"
                        )
                duplicate_entries = sorted(
                    item for item, count in Counter(entry_ids).items() if item and count > 1
                )
                if duplicate_entries:
                    errors.append("duplicate analytical entry IDs: " + ", ".join(duplicate_entries))

        writing_path = review_dir / "evidence/writing.json"
        if run.get("mode") == "full" and writing_path.exists():
            writing = load_json(writing_path, errors)
            if isinstance(writing, dict):
                validate_schema(writing, "writing.schema.json", "evidence/writing.json", errors)
                writing_audit_version = writing.get("schema_version")
                strict_writing_audit = writing_audit_version in {"0.2", "0.3"}
                if writing_audit_version == "0.3" and writing_report_path.exists():
                    current_writing_report = writing_report_path.read_text(encoding="utf-8")
                    if re.search(
                        r"^## (?:References and citation integrity|Reference accuracy and citation support)\s*$",
                        current_writing_report,
                        re.MULTILINE,
                    ):
                        errors.append("writing audit v0.3 forbids a routine reference or citation-accuracy section")
                if writing.get("review_id") != run.get("review_id"):
                    errors.append("writing review_id differs from run.json")
                active_ids = {item.get("id") for item in active}

                def writing_string_list(value: Any) -> list[str]:
                    """Return only string members after schema validation has recorded bad input."""
                    if not isinstance(value, list):
                        return []
                    return [item for item in value if isinstance(item, str)]

                def check_writing_rows(rows: Any, label: str, adverse_statuses: set[str]) -> None:
                    if not isinstance(rows, list):
                        return
                    row_ids = [
                        row.get("id") for row in rows
                        if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("id")
                    ]
                    duplicates = sorted(item for item, count in Counter(row_ids).items() if count > 1)
                    if duplicates:
                        errors.append(f"duplicate {label} IDs: {', '.join(duplicates)}")
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        mapped = writing_string_list(row.get("finding_ids"))
                        row_status = row.get("status")
                        for finding_id in mapped:
                            if finding_id not in active_ids:
                                errors.append(f"{label} {row.get('id')} references unknown or inactive finding {finding_id}")
                        if isinstance(row_status, str) and row_status in adverse_statuses and not mapped:
                            errors.append(f"adverse {label} state {row.get('id')} must map to an active finding")
                        if strict_writing_audit and label == "writing-mechanics" and row_status == "checked_clean_group" and mapped:
                            errors.append(f"checked-clean writing-mechanics row {row.get('id')} cannot map an active finding")
                        if strict_writing_audit and label == "writing-consistency" and row_status == "consistent" and mapped:
                            errors.append(f"consistent writing-consistency row {row.get('id')} cannot map an active finding")

                mechanics_rows = writing.get("mechanics", [])
                for group in mechanics_rows if isinstance(mechanics_rows, list) else []:
                    if not isinstance(group, dict) or group.get("status") != "issue":
                        continue
                    occurrences = group.get("occurrences", [])
                    for occurrence in occurrences if isinstance(occurrences, list) else []:
                        if not isinstance(occurrence, dict):
                            continue
                        if writing_audit_version in {"0.2", "0.3"} and (
                            "render_verification" not in occurrence or "source_provenance" not in occurrence
                        ):
                            errors.append(
                                f"writing v{writing_audit_version} mechanics occurrence in {group.get('id')} requires render verification and source provenance"
                            )
                        occurrence_render = occurrence.get("render_verification")
                        if isinstance(occurrence_render, str) and occurrence_render in {"bounded", "extraction_artifact_rejected"}:
                            errors.append(
                                f"retained writing-mechanics occurrence in {group.get('id')} lacks authoritative visual/source verification"
                            )

                check_writing_rows(writing.get("mechanics"), "writing-mechanics", {"issue"})
                check_writing_rows(writing.get("consistency_groups"), "writing-consistency", {"issue"})
                check_writing_rows(writing.get("style_suggestions"), "writing-style", set())

                writing_mapped_ids: set[str] = set()
                observed_sources: dict[str, set[str]] = {}
                source_collections = {
                    "mechanics": "mechanics",
                    "consistency_groups": "consistency",
                    "style_suggestions": "style",
                    "section_audit": "section",
                    "redundancy_map": "redundancy",
                }
                for collection_name, source_name in source_collections.items():
                    collection = writing.get(collection_name, [])
                    for row in collection if isinstance(collection, list) else []:
                        if isinstance(row, dict):
                            mapped = writing_string_list(row.get("finding_ids"))
                            writing_mapped_ids.update(mapped)
                            for finding_id in mapped:
                                if finding_id not in active_ids:
                                    errors.append(
                                        f"writing {collection_name} row {row.get('id') or row.get('section') or row.get('idea')} "
                                        f"references unknown or inactive finding {finding_id}"
                                    )
                            issue_bearing = (
                                (collection_name == "mechanics" and row.get("status") == "issue")
                                or (collection_name == "consistency_groups" and row.get("status") == "issue")
                                or collection_name in {"style_suggestions", "section_audit", "redundancy_map"}
                            )
                            if issue_bearing:
                                for finding_id in mapped:
                                    observed_sources.setdefault(finding_id, set()).add(source_name)

                reference_audit = writing.get("reference_audit", {})
                if writing_audit_version in {"0.1", "0.2"} and isinstance(reference_audit, dict):
                    records = reference_audit.get("records", [])
                    record_rows = records if isinstance(records, list) else []
                    resolved_records = [
                        row for row in record_rows
                        if isinstance(row, dict) and row.get("status") != "unresolved"
                    ]
                    expected_checked = len(resolved_records) if writing_audit_version == "0.2" else len(record_rows)
                    if isinstance(records, list) and reference_audit.get("records_checked") != expected_checked:
                        expectation = "the number of non-unresolved record rows" if writing_audit_version == "0.2" else "the number of record rows"
                        errors.append(f"writing reference_audit.records_checked must equal {expectation}")
                    status_counts = Counter(
                        row.get("status") for row in record_rows
                        if isinstance(row, dict) and isinstance(row.get("status"), str)
                    )
                    expected_reference_counts = {
                        "records_verified": status_counts["verified"],
                        "records_adverse": sum(status_counts[value] for value in (
                            "metadata_issue", "version_issue", "citation_reference_mismatch", "support_issue"
                        )),
                        "records_unresolved": status_counts["unresolved"],
                    }
                    for field, expected in expected_reference_counts.items():
                        if field in reference_audit and reference_audit.get(field) != expected:
                            errors.append(f"writing reference_audit.{field} must equal {expected} from the record states")
                    if reference_audit.get("status") == "complete" and reference_audit.get("records_checked") != reference_audit.get("bibliography_record_count"):
                        errors.append("complete reference audit must check every bibliography record")
                    check_writing_rows(
                        record_rows,
                        "reference-record",
                        {"metadata_issue", "version_issue", "citation_reference_mismatch", "support_issue"},
                    )
                    for row in record_rows:
                        if isinstance(row, dict):
                            mapped = writing_string_list(row.get("finding_ids"))
                            writing_mapped_ids.update(mapped)
                            record_status = row.get("status")
                            if strict_writing_audit and isinstance(record_status, str) and record_status in {"verified", "unresolved"} and mapped:
                                errors.append(
                                    f"reference-record {row.get('id')} with status {record_status} cannot map an active finding"
                                )
                            if isinstance(record_status, str) and record_status in {
                                "metadata_issue", "version_issue", "citation_reference_mismatch", "support_issue"
                            }:
                                for finding_id in mapped:
                                    observed_sources.setdefault(finding_id, set()).add("reference")
                    reference_ids = writing_string_list(reference_audit.get("finding_ids"))
                    for finding_id in reference_ids:
                        if finding_id not in active_ids:
                            errors.append(f"reference_audit references unknown or inactive finding {finding_id}")
                    writing_mapped_ids.update(reference_ids)
                    for finding_id in reference_ids:
                        observed_sources.setdefault(finding_id, set()).add("reference")
                else:
                    # The schema error above is authoritative; keep later report checks type-safe.
                    reference_audit = {}

                venue = writing.get("venue_fit", {})
                if isinstance(venue, dict):
                    venue_status = venue.get("status")
                    if venue_status == "assessed" and not venue.get("candidates"):
                        errors.append("assessed venue fit requires at least one candidate journal")
                    if venue_status == "assessed" and not venue.get("as_of_date"):
                        errors.append("assessed venue fit requires an as_of_date")
                    venue_ids = writing_string_list(venue.get("finding_ids"))
                    for finding_id in venue_ids:
                        if finding_id not in active_ids:
                            errors.append(f"venue_fit references unknown or inactive finding {finding_id}")
                    if strict_writing_audit and isinstance(venue_status, str) and venue_status in {"not_requested", "not_assessed"} and venue_ids:
                        errors.append(f"venue_fit with status {venue_status} cannot map an active finding")
                    writing_mapped_ids.update(venue_ids)
                    if isinstance(venue_status, str) and venue_status in {"assessed", "bounded"}:
                        for finding_id in venue_ids:
                            observed_sources.setdefault(finding_id, set()).add("venue")

                active_writing_ids = {item.get("id") for item in writing_active}
                if strict_writing_audit:
                    missing_writing_mappings = sorted(active_writing_ids - writing_mapped_ids)
                    if missing_writing_mappings:
                        errors.append(
                            "active writing findings missing reciprocal evidence/writing.json mappings: "
                            + ", ".join(missing_writing_mappings)
                        )
                    raw_links = writing.get("finding_links", [])
                    link_rows = raw_links if isinstance(raw_links, list) else []
                    linked_ids = [
                        row.get("finding_id") for row in link_rows
                        if isinstance(row, dict) and isinstance(row.get("finding_id"), str)
                    ]
                    duplicate_links = sorted(
                        finding_id for finding_id, count in Counter(linked_ids).items()
                        if finding_id and count > 1
                    )
                    if duplicate_links:
                        errors.append("writing finding_links repeat IDs: " + ", ".join(duplicate_links))
                    linked_id_set = {value for value in linked_ids if isinstance(value, str)}
                    if linked_id_set != active_writing_ids:
                        missing = sorted(active_writing_ids - linked_id_set)
                        extra = sorted(linked_id_set - active_writing_ids)
                        if missing:
                            errors.append("writing finding_links omit active writing findings: " + ", ".join(missing))
                        if extra:
                            errors.append("writing finding_links contain non-writing or inactive findings: " + ", ".join(extra))
                    for row in link_rows:
                        if not isinstance(row, dict) or not isinstance(row.get("finding_id"), str):
                            continue
                        finding_id = row["finding_id"]
                        declared_sources = set(writing_string_list(row.get("sources")))
                        actual_sources = observed_sources.get(finding_id, set())
                        if declared_sources != actual_sources:
                            errors.append(
                                f"writing finding_link {finding_id} sources do not match issue-bearing audit mappings: "
                                f"declared {sorted(declared_sources)}, observed {sorted(actual_sources)}"
                            )

                    highest_ids = writing_string_list(writing.get("highest_return_finding_ids"))
                    if active_writing_ids and not highest_ids:
                        errors.append(f"writing audit v{writing_audit_version} requires a highest-return finding when active writing findings exist")
                    for finding_id in highest_ids:
                        if finding_id not in active_writing_ids:
                            errors.append(f"highest-return writing ID is not an active writing finding: {finding_id}")

                    if writing_report_path.exists():
                        writing_report = writing_report_path.read_text(encoding="utf-8")
                        rich_headings = (
                            "## Writing assessment",
                            "## Highest-return writing revisions",
                            "## Section-by-section reader audit",
                            "## Terminology, definitions, and notation",
                            "## Tables and figures as writing",
                            "## Mechanics and copyedit inventory",
                        )
                        if not all(re.search(rf"^{re.escape(heading)}\s*$", writing_report, re.MULTILINE) for heading in rich_headings):
                            errors.append(
                                f"writing audit v{writing_audit_version} requires the current six-section writing-report preamble"
                            )
                        else:
                            def writing_section(heading: str) -> str:
                                match = re.search(rf"^{re.escape(heading)}\s*$", writing_report, re.MULTILINE)
                                if not match:
                                    return ""
                                following = writing_report[match.end():]
                                next_heading = re.search(r"^## ", following, re.MULTILINE)
                                return following[:next_heading.start()] if next_heading else following

                            assessment_block = normalize_quote(writing_section("## Writing assessment"))
                            raw_strengths = writing.get("strengths", [])
                            strengths = raw_strengths if isinstance(raw_strengths, list) else []
                            for strength in strengths:
                                if isinstance(strength, str) and normalize_quote(strength) not in assessment_block:
                                    errors.append("writing-report assessment omits a canonical writing strength")
                            highest_block = writing_section("## Highest-return writing revisions")
                            for finding_id in highest_ids:
                                if finding_id not in highest_block:
                                    errors.append(f"writing-report highest-return section omits {finding_id}")
                            section_block = normalize_quote(writing_section("## Section-by-section reader audit"))
                            section_rows = writing.get("section_audit", [])
                            for row in section_rows if isinstance(section_rows, list) else []:
                                section_name = row.get("section") if isinstance(row, dict) else None
                                if isinstance(section_name, str) and normalize_quote(section_name) not in section_block:
                                    errors.append(f"writing-report section audit omits {section_name!r}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an econ-review output directory")
    parser.add_argument("review_dir", type=Path, help="Path containing run.json, findings.json, report.md, and fix-plan.md")
    args = parser.parse_args()
    errors = validate_review(args.review_dir)
    if errors:
        print("econ-review validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"econ-review validation passed: {args.review_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
