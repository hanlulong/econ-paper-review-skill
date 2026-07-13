#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
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
        self.content = content
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
