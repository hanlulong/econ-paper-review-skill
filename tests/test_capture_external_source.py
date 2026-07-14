#!/usr/bin/env python3
"""Focused tests for deterministic external-source capture construction."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "capture_external_source.py"
SPEC = importlib.util.spec_from_file_location("capture_external_source", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def capture_spec() -> dict:
    return {
        "review_id": "capture-test-001",
        "search_confidentiality": "deidentified",
        "source": {
            "id": "EXT-01",
            "title": "A β-Convergence Result",
            "stable_id": "doi:10.1234/example.result",
            "url": "https://doi.org/10.1234/example.result",
            "accessed_at": "2026-07-14",
            "snapshot_kind": "source_capture",
            "bibliographic_metadata": {
                "authors": [
                    {
                        "name": "Ana Example",
                        "author_type": "person",
                        "stable_id": "orcid:0000-0000-0000-0001",
                    }
                ],
                "identifiers": [
                    {"scheme": "doi", "value": "10.1234/example.result"}
                ],
                "source_type": "working_paper",
                "venue": "Example Economics Series",
                "publication_date": "2025-02-01",
                "first_public_date": "2024-03-15",
                "first_public_date_status": "verified",
                "work_family_id": "WORK-01",
                "metadata_source_url": "https://example.org/metadata/result",
                "record_status": "current",
                "record_status_checked_at": "2026-07-14",
                "record_status_source_url": "https://example.org/status/result",
            },
            "capture_policy": {
                "lawful_access_basis": "open_or_public",
                "retained_material": "minimal_excerpt",
                "redistribution": "permitted",
            },
            "snapshot_path": "evidence/external/EXT-01.txt",
        },
        "captures": [
            {
                "support_record": {
                    "id": "EXT-01-SUP-01",
                    "proposition": "The paper reports a β-convergence result.",
                    "proposition_kind": "reported_main_result",
                    "support_state": "supported",
                    "access_scope": "full_text",
                    "locator": "Source capture, result paragraph",
                },
                "excerpt": "The estimated β effect is negative.\r\nThe result is robust.",
            }
        ],
        "metadata_projection": {
            "support_record_id": "EXT-01-SUP-02",
            "locator": "Official record, canonical metadata projection",
        },
    }


def initialize_review(
    review: Path,
    *,
    run_id: str = "capture-test-001",
    findings_id: str | None = None,
) -> None:
    """Create the minimum identity-bearing package artifacts for helper tests."""

    findings_id = run_id if findings_id is None else findings_id
    (review / "run.json").write_text(
        json.dumps({"review_id": run_id}) + "\n",
        encoding="utf-8",
    )
    (review / "findings.json").write_text(
        json.dumps({"review_id": findings_id, "findings": []}) + "\n",
        encoding="utf-8",
    )


class CaptureExternalSourceTests(unittest.TestCase):
    def test_dry_run_is_non_destructive_and_fragment_is_contract_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            initialize_review(review)
            fragment = MODULE.build_fragment(review, capture_spec())
            snapshot = review / "evidence/external/EXT-01.txt"
            self.assertFalse(snapshot.exists())
            self.assertEqual(fragment["schema_version"], "0.4")
            self.assertEqual(fragment["sources"][0]["id"], "EXT-01")
            self.assertEqual(MODULE._schema_errors(fragment), [])

    def test_write_uses_lf_utf8_and_binds_actual_character_spans(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            initialize_review(review)
            fragment = MODULE.write_capture(
                review,
                capture_spec(),
                fragment_path="evidence/external/EXT-01.source.json",
            )
            source = fragment["sources"][0]
            raw = (review / source["snapshot_path"]).read_bytes()
            text = raw.decode("utf-8")
            self.assertNotIn(b"\r", raw)
            self.assertIn("β", text)
            self.assertEqual(source["snapshot_sha256"], hashlib.sha256(raw).hexdigest())
            for record in source["support_records"]:
                excerpt = text[record["snapshot_start"] : record["snapshot_end"]]
                self.assertEqual(excerpt, record["snapshot_excerpt"])
                self.assertEqual(
                    record["snapshot_excerpt_sha256"],
                    hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                )
            first = source["support_records"][0]
            self.assertEqual(first["snapshot_start"], 0)
            self.assertEqual(first["snapshot_end"], len(first["snapshot_excerpt"]))
            sidecar = json.loads(
                (review / "evidence/external/EXT-01.source.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(sidecar, fragment)

    def test_metadata_projection_is_canonical_and_deep_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            initialize_review(review)
            fragment = MODULE.build_fragment(review, capture_spec())
            source = fragment["sources"][0]
            metadata_record = source["support_records"][1]
            projection = json.loads(metadata_record["snapshot_excerpt"])
            self.assertEqual(
                metadata_record["snapshot_excerpt"],
                json.dumps(
                    projection,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            self.assertEqual(projection["title"], source["title"])
            self.assertEqual(
                projection["authors"], source["bibliographic_metadata"]["authors"]
            )
            self.assertEqual(
                set(source["bibliographic_metadata"]["field_support_record_ids"]),
                set(MODULE.EXTERNAL_METADATA_PROJECTION_FIELDS),
            )
            self.assertEqual(
                set(source["bibliographic_metadata"]["field_support_record_ids"].values()),
                {"EXT-01-SUP-02"},
            )

    def test_existing_destinations_are_refused_without_explicit_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            initialize_review(review)
            spec = capture_spec()
            MODULE.write_capture(review, spec)
            snapshot = review / "evidence/external/EXT-01.txt"
            before = snapshot.read_bytes()
            changed = copy.deepcopy(spec)
            changed["captures"][0]["excerpt"] = "A changed exact excerpt."
            with self.assertRaisesRegex(FileExistsError, "refusing to replace"):
                MODULE.write_capture(review, changed)
            self.assertEqual(snapshot.read_bytes(), before)

    def test_sidecar_failure_rolls_back_new_snapshot_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            initialize_review(review)
            original_write = MODULE.atomic_write_bytes
            failed = False

            def fail_sidecar(root: Path, relative: str, value: bytes) -> Path:
                nonlocal failed
                if (
                    root == review
                    and relative == "evidence/external/EXT-01.source.json"
                    and not failed
                ):
                    failed = True
                    raise OSError("synthetic sidecar failure")
                return original_write(root, relative, value)

            with mock.patch.object(
                MODULE, "atomic_write_bytes", side_effect=fail_sidecar
            ), self.assertRaisesRegex(OSError, "synthetic sidecar failure"):
                MODULE.write_capture(
                    review,
                    capture_spec(),
                    fragment_path="evidence/external/EXT-01.source.json",
                )
            self.assertFalse((review / "evidence/external/EXT-01.txt").exists())
            self.assertFalse(
                (review / "evidence/external/EXT-01.source.json").exists()
            )
            self.assertFalse((review / "evidence").exists())

    def test_sidecar_failure_restores_explicit_replacements_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            initialize_review(review)
            external = review / "evidence/external"
            external.mkdir(parents=True)
            snapshot = external / "EXT-01.txt"
            sidecar = external / "EXT-01.source.json"
            old_snapshot = b"old snapshot bytes\r\n"
            old_sidecar = b'{"old":true}\r\n'
            snapshot.write_bytes(old_snapshot)
            sidecar.write_bytes(old_sidecar)
            original_write = MODULE.atomic_write_bytes
            failed = False

            def fail_sidecar_once(root: Path, relative: str, value: bytes) -> Path:
                nonlocal failed
                if (
                    root == review
                    and relative == "evidence/external/EXT-01.source.json"
                    and not failed
                ):
                    failed = True
                    raise OSError("synthetic replacement failure")
                return original_write(root, relative, value)

            with mock.patch.object(
                MODULE, "atomic_write_bytes", side_effect=fail_sidecar_once
            ), self.assertRaisesRegex(OSError, "synthetic replacement failure"):
                MODULE.write_capture(
                    review,
                    capture_spec(),
                    fragment_path="evidence/external/EXT-01.source.json",
                    replace_existing=True,
                )
            self.assertEqual(snapshot.read_bytes(), old_snapshot)
            self.assertEqual(sidecar.read_bytes(), old_sidecar)

    def test_invalid_source_evidence_fails_before_package_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            initialize_review(review)
            spec = capture_spec()
            spec["source"]["snapshot_kind"] = "reviewer_note"
            with self.assertRaisesRegex(ValueError, "source_capture or official_metadata"):
                MODULE.write_capture(review, spec)
            self.assertFalse((review / "evidence").exists())

    def test_immediate_contract_validation_rejects_tampered_span(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            initialize_review(review)
            fragment = MODULE.build_fragment(review, capture_spec())
            source = fragment["sources"][0]
            raw = MODULE._snapshot_bytes(MODULE._prepare(capture_spec())[2])
            source["support_records"][0]["snapshot_start"] += 1
            with self.assertRaisesRegex(ValueError, "excerpt does not match"):
                MODULE._validate_fragment(
                    fragment,
                    raw,
                    active_finding_ids=set(),
                )

    def test_cli_dry_run_prints_utf8_fragment_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            initialize_review(review)
            spec_path = review / "capture-spec.json"
            spec_path.write_text(
                json.dumps(capture_spec(), ensure_ascii=False), encoding="utf-8"
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(review), str(spec_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            payload = json.loads(result.stdout.decode("utf-8"))
            self.assertEqual(payload["sources"][0]["title"], "A β-Convergence Result")
            self.assertFalse((review / "evidence").exists())

    def test_review_id_mismatch_is_rejected_before_build_or_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            initialize_review(review, run_id="different-review")
            with mock.patch.object(MODULE, "_prepare") as prepare:
                with self.assertRaisesRegex(ValueError, "does not match target review"):
                    MODULE.build_fragment(review, capture_spec())
                prepare.assert_not_called()
            with self.assertRaisesRegex(ValueError, "does not match target review"):
                MODULE.write_capture(review, capture_spec())
            self.assertFalse((review / "evidence").exists())

    def test_conflicting_target_review_ids_are_rejected_before_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            initialize_review(
                review,
                run_id="capture-test-001",
                findings_id="different-review",
            )
            with mock.patch.object(MODULE, "_prepare") as prepare:
                with self.assertRaisesRegex(
                    ValueError, "target review identity artifacts conflict"
                ):
                    MODULE.build_fragment(review, capture_spec())
                prepare.assert_not_called()
            self.assertFalse((review / "evidence").exists())

    def test_empty_target_requires_explicit_standalone_fragment_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            with self.assertRaisesRegex(ValueError, "no run.json or findings.json"):
                MODULE.build_fragment(review, capture_spec())
            fragment = MODULE.build_fragment(
                review,
                capture_spec(),
                standalone=True,
            )
            self.assertEqual(fragment["review_id"], "capture-test-001")
            self.assertFalse((review / "evidence").exists())

    def test_cli_standalone_dry_run_is_explicit_and_cannot_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary)
            spec_path = review / "capture-spec.json"
            spec_path.write_text(
                json.dumps(capture_spec(), ensure_ascii=False), encoding="utf-8"
            )
            dry_run = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(review),
                    str(spec_path),
                    "--standalone",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr.decode("utf-8"))
            self.assertFalse((review / "evidence").exists())
            write = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(review),
                    str(spec_path),
                    "--standalone",
                    "--write",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(write.returncode, 0)
            self.assertIn(
                "--standalone cannot be combined with --write",
                write.stderr.decode("utf-8"),
            )
            self.assertFalse((review / "evidence").exists())


if __name__ == "__main__":
    unittest.main()
