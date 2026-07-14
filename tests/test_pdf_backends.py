#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "pdf_backends.py"
SPEC = importlib.util.spec_from_file_location("pdf_backends_test", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(
        self, status_code: int, *, value: object | None = None, content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._value = value
        self.content = content or (json.dumps(value).encode("utf-8") if value is not None else b"")
        self.headers = headers or {}

    def json(self) -> object:
        if self._value is None:
            raise ValueError("not json")
        return self._value

    def iter_content(self, chunk_size: int = 1024 * 1024):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start:start + chunk_size]


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.closed = False

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class PdfBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requests_version = mock.patch.object(
            MODULE,
            "mathpix_http_requirement_status",
            return_value=MODULE.RequirementStatus(
                "requests", "requests>=2.32,<3", "2.32.0", "compatible",
            ),
        )
        self.requests_version.start()
        self.addCleanup(self.requests_version.stop)

    @staticmethod
    def requests_module(session: FakeSession) -> object:
        return types.SimpleNamespace(Session=lambda: session)

    def test_mathpix_proposal_is_hashed_deleted_and_contains_no_credentials(self) -> None:
        responses = [
            FakeResponse(200, value={"pdf_id": "pdf_safe_123"}),
            FakeResponse(200, value={"status": "completed", "num_pages": 1, "percent_done": 100}),
            FakeResponse(200, content=b"# Converted\n"),
            FakeResponse(200, content=b'{"pages": [{"page": 1, "lines": []}]}'),
            FakeResponse(200, value={"status": "deleted"}),
        ]
        session = FakeSession(responses)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"%PDF synthetic")
            with mock.patch.dict(sys.modules, {"requests": self.requests_module(session)}):
                proposal = MODULE.run_mathpix(
                    pdf, root / "stage", "evidence/pdf-ingestion/SRC-01",
                    app_id="secret-id", app_key="secret-key", timeout=60, poll_interval=0.1,
                    expected_pages=1,
                )
            self.assertEqual(proposal["engine"], "mathpix")
            self.assertEqual(proposal["processing"]["remote_deletion"], "confirmed")
            self.assertEqual([call[0] for call in session.calls], ["POST", "GET", "GET", "GET", "DELETE"])
            serialized = json.dumps(proposal)
            self.assertNotIn("secret-id", serialized)
            self.assertNotIn("secret-key", serialized)
            receipt = (root / "stage/proposals/mathpix/receipt.json").read_text()
            self.assertNotIn("secret-id", receipt)
            self.assertNotIn("secret-key", receipt)
            self.assertTrue(session.closed)

    def test_mathpix_page_inventory_mismatch_fails_and_still_deletes(self) -> None:
        session = FakeSession([
            FakeResponse(200, value={"pdf_id": "pdf_pages_123"}),
            FakeResponse(200, value={"status": "completed", "num_pages": 2}),
            FakeResponse(200, content=b"# Converted\n"),
            FakeResponse(200, content=b'{"pages": [{"page": 1, "lines": []}]}'),
            FakeResponse(200, value={"status": "completed"}),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"%PDF synthetic")
            with mock.patch.dict(sys.modules, {"requests": self.requests_module(session)}):
                with self.assertRaisesRegex(MODULE.BackendError, "page count differs"):
                    MODULE.run_mathpix(
                        pdf, root / "stage", "evidence/pdf-ingestion/SRC-01",
                        app_id="id", app_key="key", timeout=60, poll_interval=0.1,
                        expected_pages=1,
                    )
        self.assertEqual([call[0] for call in session.calls], ["POST", "GET", "DELETE"])

    def test_mathpix_failure_still_attempts_remote_delete(self) -> None:
        session = FakeSession([
            FakeResponse(200, value={"pdf_id": "pdf_cleanup_123"}),
            FakeResponse(200, value={"status": "error"}),
            FakeResponse(200, value={"status": "deleted"}),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"%PDF synthetic")
            with mock.patch.dict(sys.modules, {"requests": self.requests_module(session)}):
                with self.assertRaisesRegex(MODULE.BackendError, "processing failed"):
                    MODULE.run_mathpix(
                        pdf, root / "stage", "evidence/pdf-ingestion/SRC-01",
                        app_id="id", app_key="key", timeout=60, poll_interval=0.1,
                        expected_pages=1,
                    )
        self.assertEqual([call[0] for call in session.calls], ["POST", "GET", "DELETE"])

    def test_mathpix_rejects_redirect_without_following_or_forwarding_credentials(self) -> None:
        session = FakeSession([FakeResponse(302, headers={"Location": "https://example.com/steal"})])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"%PDF synthetic")
            with mock.patch.dict(sys.modules, {"requests": self.requests_module(session)}):
                with self.assertRaisesRegex(MODULE.BackendError, "HTTP 302"):
                    MODULE.run_mathpix(
                        pdf, root / "stage", "evidence/pdf-ingestion/SRC-01",
                        app_id="id", app_key="key", timeout=60, poll_interval=0.1,
                        expected_pages=1,
                    )
        self.assertEqual(len(session.calls), 1)
        self.assertFalse(session.calls[0][2]["allow_redirects"])

    def test_mathpix_stream_limit_rejects_oversized_content_length(self) -> None:
        response = FakeResponse(
            200, content=b"not-read",
            headers={"Content-Length": str(MODULE.MAX_VENDOR_RESPONSE_BYTES + 1)},
        )
        with self.assertRaisesRegex(MODULE.BackendError, "response limit"):
            MODULE._bounded_content(response, "mmd")

    def test_mathpix_control_response_is_bounded_before_json_parsing(self) -> None:
        response = FakeResponse(
            200, value={"pdf_id": "pdf_safe_123"},
            headers={"Content-Length": str(MODULE.MAX_VENDOR_CONTROL_BYTES + 1)},
        )
        with self.assertRaisesRegex(MODULE.BackendError, "response limit"):
            MODULE._bounded_json(response, "submission")

    def test_mathpix_control_response_rejects_ambiguous_json(self) -> None:
        for content in (
            b'{"pdf_id":"first","pdf_id":"second"}',
            b'{"percent_done":NaN}',
        ):
            with self.subTest(content=content):
                response = FakeResponse(200, content=content)
                with self.assertRaisesRegex(MODULE.BackendError, "not valid JSON"):
                    MODULE._bounded_json(response, "status")

    def test_backend_artifacts_require_portable_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CON.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.BackendError, "output path is not portable"):
                MODULE._safe_artifacts(root, "evidence/pdf-ingestion/SRC-01")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "result.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.BackendError, "review root is not portable"):
                MODULE._safe_artifacts(root, "evidence/../outside")

    def test_windows_docling_console_script_and_runtime_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "Scripts"
            scripts.mkdir()
            python = scripts / "python.exe"
            executable = scripts / "docling.exe"
            python.write_bytes(b"")
            executable.write_bytes(b"")
            executable.chmod(0o700)
            with mock.patch.object(MODULE.shutil, "which", return_value=None), \
                    mock.patch.object(MODULE.sys, "executable", str(python)):
                self.assertEqual(MODULE.docling_executable("Windows"), str(executable))

        windows_environment = {
            "PATH": r"C:\\tools",
            "SYSTEMROOT": r"C:\\Windows",
            "USERPROFILE": r"C:\\Users\\reviewer",
            "LOCALAPPDATA": r"C:\\Users\\reviewer\\AppData\\Local",
            "TEMP": r"C:\\Users\\reviewer\\AppData\\Local\\Temp",
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
            "UNRELATED_SECRET": "do-not-forward",
        }
        with mock.patch.dict(MODULE.os.environ, windows_environment, clear=True):
            selected = MODULE._docling_environment(
                allow_model_downloads=False,
                system="Windows",
            )
        for name in ("SYSTEMROOT", "USERPROFILE", "LOCALAPPDATA", "TEMP", "PATHEXT"):
            self.assertEqual(selected[name], windows_environment[name])
        self.assertNotIn("UNRELATED_SECRET", selected)
        self.assertEqual(selected["HF_HUB_OFFLINE"], "1")

    def test_docling_path_rewrite_handles_native_and_opposite_slashes(self) -> None:
        local = Path("stage") / "proposals" / "docling"
        native = str(local)
        opposite = native.replace("/", "\\")
        rewritten = MODULE._replace_local_path_variants(
            f"{native}/image.png\n{opposite}\\image.png\n",
            local,
            "evidence/pdf-ingestion/SRC-01/proposals/docling",
        )
        self.assertNotIn(native, rewritten)
        self.assertNotIn(opposite, rewritten)
        self.assertEqual(rewritten.count("evidence/pdf-ingestion/SRC-01/proposals/docling"), 2)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation unavailable")
    def test_backend_artifacts_reject_non_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "result.json").write_text("{}", encoding="utf-8")
            os.mkfifo(root / "control.json")
            with self.assertRaisesRegex(MODULE.BackendError, "only regular files"):
                MODULE._safe_artifacts(root, "evidence/pdf-ingestion/SRC-01")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_private_write_refuses_symlink_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.md"
            outside.write_text("preserve me\n", encoding="utf-8")
            linked = root / "linked.md"
            linked.symlink_to(outside)
            with self.assertRaisesRegex(MODULE.BackendError, "destination is unsafe"):
                MODULE._private_write(linked, b"overwritten\n")
            self.assertEqual(outside.read_text(encoding="utf-8"), "preserve me\n")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_docling_rejects_symlink_output_before_rewriting(self) -> None:
        outside: Path | None = None

        def fake_run(command: list[str], **_: object) -> object:
            nonlocal outside
            output = Path(command[command.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            outside = output.parent / "outside.md"
            outside.write_text("preserve me\n", encoding="utf-8")
            (output / "original.md").symlink_to(outside)
            (output / "original.json").write_text(
                json.dumps({"schema_name": "DoclingDocument", "pages": {}}),
                encoding="utf-8",
            )
            return type("Result", (), {"stdout": b"", "stderr": b""})()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"%PDF synthetic")
            with mock.patch.object(MODULE.shutil, "which", return_value="/fake/docling"), \
                    mock.patch.object(
                        MODULE, "docling_requirement_status",
                        return_value=MODULE.RequirementStatus(
                            "docling", "docling==2.102.1", "2.102.1", "compatible",
                        ),
                    ), \
                    mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run):
                with self.assertRaisesRegex(MODULE.BackendError, "symbolic links"):
                    MODULE.run_docling(
                        pdf, root / "stage", "evidence/pdf-ingestion/SRC-01",
                        allow_model_downloads=False, enrich_formulas=False,
                        timeout=120, device="cpu",
                    )
            assert outside is not None
            self.assertEqual(outside.read_text(encoding="utf-8"), "preserve me\n")

    def test_docling_proposal_rewrites_staging_paths_and_records_artifacts(self) -> None:
        def fake_run(command: list[str], **_: object) -> object:
            output = Path(command[command.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            artifacts = output / "original_artifacts"
            artifacts.mkdir()
            image = artifacts / "image.png"
            image.write_bytes(b"png")
            (output / "original.md").write_text(f"![Figure]({image})\n", encoding="utf-8")
            (output / "original.json").write_text(
                json.dumps({
                    "schema_name": "DoclingDocument", "version": "1.10.0",
                    "image": str(image),
                    "pages": {"1": {"page_no": 1, "size": {"width": 612, "height": 792}}},
                    "texts": [{
                        "label": "text", "text": "Evidence text",
                        "prov": [{
                            "page_no": 1,
                            "bbox": {"l": 10, "t": 780, "r": 120, "b": 760, "coord_origin": "BOTTOMLEFT"},
                        }],
                    }],
                    "tables": [], "pictures": [],
                }), encoding="utf-8",
            )
            return type("Result", (), {"stdout": b"", "stderr": b""})()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"%PDF synthetic")
            with mock.patch.object(MODULE.shutil, "which", return_value="/fake/docling"), \
                    mock.patch.object(MODULE, "docling_version", return_value="2.102.1"), \
                    mock.patch.object(
                        MODULE, "docling_requirement_status",
                        return_value=MODULE.RequirementStatus(
                            "docling", "docling==2.102.1", "2.102.1", "compatible",
                        ),
                    ), \
                    mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run):
                proposal = MODULE.run_docling(
                    pdf, root / "stage", "evidence/pdf-ingestion/SRC-01",
                    allow_model_downloads=False, enrich_formulas=False,
                    timeout=120, device="cpu",
                )
            markdown = (root / "stage/proposals/docling/original.md").read_text()
            self.assertIn("evidence/pdf-ingestion/SRC-01/proposals/docling", markdown)
            self.assertNotIn(str(root), markdown)
            self.assertEqual(proposal["engine"], "docling")
            self.assertFalse(proposal["processing"]["manuscript_uploaded"])
            self.assertGreaterEqual(len(proposal["artifacts"]), 4)
            normalized = json.loads((root / "stage/proposals/docling/normalized.json").read_text())
            self.assertEqual(normalized["pages"][0]["elements"][0]["text"], "Evidence text")
            self.assertEqual(normalized["pages"][0]["elements"][0]["bbox"], [10.0, 12.0, 120.0, 32.0])


if __name__ == "__main__":
    unittest.main()
