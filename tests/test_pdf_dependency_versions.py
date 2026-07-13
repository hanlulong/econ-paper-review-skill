#!/usr/bin/env python3

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "econ-review" / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VERSIONS = load_module("dependency_versions_test", SCRIPTS / "dependency_versions.py")
INGESTION = load_module("pdf_ingestion_dependency_test", SCRIPTS / "pdf_ingestion.py")
BACKENDS = load_module("pdf_backends_dependency_test", SCRIPTS / "pdf_backends.py")


class RequirementManifestTests(unittest.TestCase):
    def test_nested_manifest_is_version_aware_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "core.txt").write_text("Example-Package>=2,<3\n", encoding="utf-8")
            (root / "profile.txt").write_text(
                "-r core.txt\nExample-Package>=2,<3\nOptional-Package==4.1\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                VERSIONS,
                "installed_distribution_version",
                side_effect=lambda name: {"Example-Package": "2.5", "Optional-Package": "4.0"}[name],
            ):
                checks = VERSIONS.check_manifest(root / "profile.txt")
        self.assertEqual([row.name for row in checks], ["Example-Package", "Optional-Package"])
        self.assertEqual([row.state for row in checks], ["compatible", "unsupported"])
        self.assertEqual(checks[1].installed_version, "4.0")

    def test_missing_invalid_and_conflicting_contracts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = {
                "missing.txt": "-r absent.txt\n",
                "invalid.txt": "not a requirement ???\n",
                "directive.txt": "--index-url https://example.invalid\nExample>=1\n",
                "conflict.txt": "Example>=1\nexample<1\n",
            }
            for name, content in cases.items():
                with self.subTest(name=name):
                    path = root / name
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(VERSIONS.DependencyContractError):
                        VERSIONS.load_manifest(path)

    def test_manifest_include_cannot_escape_or_follow_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifests = root / "manifests"
            manifests.mkdir()
            outside = root / "outside.txt"
            outside.write_text("Example>=1\n", encoding="utf-8")
            escape = manifests / "escape.txt"
            escape.write_text("-r ../outside.txt\n", encoding="utf-8")
            linked = manifests / "linked.txt"
            linked.symlink_to(outside)
            for path in (escape, linked):
                with self.subTest(path=path.name):
                    with self.assertRaises(VERSIONS.DependencyContractError):
                        VERSIONS.load_manifest(path)

    def test_prerelease_and_unparseable_installed_versions_are_not_supported(self) -> None:
        requirement = VERSIONS.load_manifest(ROOT / "econ-review/requirements-docling.txt")["docling"]
        for installed in ("2.102.1rc1", "vendor-version"):
            with self.subTest(installed=installed):
                status = VERSIONS.check_requirement(requirement, installed_version=installed)
                self.assertEqual(status.state, "unsupported")


class PdfDependencyGateTests(unittest.TestCase):
    @staticmethod
    def status(name: str, state: str, installed: str | None = None):
        return INGESTION.RequirementStatus(
            name=name,
            requirement=f"{name}>=2,<3",
            installed_version=installed,
            state=state,
        )

    def test_doctor_fails_for_required_mismatch_but_not_optional_mismatch(self) -> None:
        compatible = self.status("core", "compatible", "2.1")
        unsupported = self.status("core", "unsupported", "1.9")
        optional = self.status("docling", "unsupported", "1.9")
        def command_versions(name: str, _: object) -> str:
            return (
                "tool 1.0"
                if name in {"pdftotext", "pdftoppm", "pdfinfo"}
                else "unavailable"
            )

        with mock.patch.object(INGESTION, "command_version", side_effect=command_versions), \
                mock.patch.object(INGESTION, "check_manifest", return_value=[unsupported]), \
                mock.patch.object(INGESTION, "markitdown_requirement_status", return_value=optional), \
                mock.patch.object(INGESTION, "docling_requirement_status", return_value=optional), \
                mock.patch.object(INGESTION, "mathpix_http_requirement_status", return_value=optional), \
                mock.patch.object(INGESTION, "command_path", return_value=None):
            required_output = io.StringIO()
            with contextlib.redirect_stdout(required_output):
                self.assertEqual(INGESTION.doctor(), 1)
            self.assertIn("required; unsupported", required_output.getvalue())

        with mock.patch.object(INGESTION, "command_version", side_effect=command_versions), \
                mock.patch.object(INGESTION, "check_manifest", return_value=[compatible]), \
                mock.patch.object(INGESTION, "markitdown_requirement_status", return_value=optional), \
                mock.patch.object(INGESTION, "docling_requirement_status", return_value=optional), \
                mock.patch.object(INGESTION, "mathpix_http_requirement_status", return_value=optional), \
                mock.patch.object(INGESTION, "command_path", return_value=None):
            optional_output = io.StringIO()
            with contextlib.redirect_stdout(optional_output):
                self.assertEqual(INGESTION.doctor(), 0)
            self.assertIn("Docling: 1.9 (optional; unsupported", optional_output.getvalue())

    def test_ingestion_required_version_gate_runs_before_pdf_commands(self) -> None:
        args = argparse.Namespace(
            max_pages=1,
            max_bytes=1024,
            docling_timeout=60,
            ocr_language="eng",
            mathpix_timeout=60,
            mathpix_poll_interval=1.0,
            semantic_backend="none",
        )
        with mock.patch.object(
            INGESTION,
            "ensure_core_python_runtime",
            side_effect=INGESTION.IngestionError("synthetic unsupported core version"),
        ), mock.patch.object(INGESTION, "command_path") as command_path:
            with self.assertRaisesRegex(INGESTION.IngestionError, "unsupported core version"):
                INGESTION.ingest(args)
        command_path.assert_not_called()

    def test_package_check_cannot_bypass_required_version_gate(self) -> None:
        fake_parser = types.SimpleNamespace(
            parse_args=lambda: argparse.Namespace(command="check", package_dir=Path("package")),
        )
        with mock.patch.object(INGESTION, "parser", return_value=fake_parser), \
                mock.patch.object(
                    INGESTION, "ensure_core_python_runtime",
                    side_effect=INGESTION.IngestionError("synthetic unsupported core version"),
                ), mock.patch.object(INGESTION, "verify_package") as verify_package, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(INGESTION.main(), 1)
        verify_package.assert_not_called()

    def test_explicit_optional_backends_reject_unsupported_versions(self) -> None:
        unsupported_markitdown = INGESTION.RequirementStatus(
            "markitdown", "markitdown[pdf]==0.1.6", "0.1.5", "unsupported",
        )
        markitdown_args = argparse.Namespace(
            markitdown_proposal=True, semantic_backend="none", mathpix=False,
        )
        with mock.patch.object(
            INGESTION, "markitdown_requirement_status", return_value=unsupported_markitdown,
        ), mock.patch.object(INGESTION, "command_path", return_value="/fake/markitdown"):
            with self.assertRaisesRegex(INGESTION.IngestionError, "unsupported"):
                INGESTION.toolchain_for(markitdown_args)

        unsupported_docling = BACKENDS.RequirementStatus(
            "docling", "docling==2.102.1", "2.101.0", "unsupported",
        )
        with mock.patch.object(BACKENDS, "docling_requirement_status", return_value=unsupported_docling):
            with self.assertRaisesRegex(BACKENDS.BackendError, "unsupported"):
                BACKENDS.run_docling(
                    Path("source.pdf"), Path("stage"), "evidence/pdf-ingestion/SRC-01",
                    allow_model_downloads=False, enrich_formulas=False, timeout=60, device="cpu",
                )

        unsupported_requests = BACKENDS.RequirementStatus(
            "requests", "requests>=2.32,<3", "2.31.0", "unsupported",
        )
        with mock.patch.object(BACKENDS, "mathpix_http_requirement_status", return_value=unsupported_requests):
            with self.assertRaisesRegex(BACKENDS.BackendError, "unsupported"):
                BACKENDS.run_mathpix(
                    Path("source.pdf"), Path("stage"), "evidence/pdf-ingestion/SRC-01",
                    app_id="id", app_key="key", timeout=60, poll_interval=1.0, expected_pages=1,
                )


if __name__ == "__main__":
    unittest.main()
