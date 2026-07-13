#!/usr/bin/env python3
"""Optional semantic backends for the render-backed PDF ingestion package.

Backends return immutable proposals. They never decide what the source says and
never replace page renders, native text, stable PDF blocks, or source anchors.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


MATHPIX_API_ROOT = "https://api.mathpix.com/v3"
MAX_VENDOR_RESPONSE_BYTES = 250_000_000
MAX_BACKEND_ARTIFACTS = 10_000
MAX_BACKEND_ARTIFACT_BYTES = 2_000_000_000


class BackendError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _private_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _private_write(path: Path, data: bytes) -> None:
    _private_mkdir(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _safe_artifacts(root: Path, review_relative_root: str) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise BackendError(f"backend output must not contain symbolic links: {path.name}")
        if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
            continue
        total_bytes += path.stat().st_size
        if len(artifacts) >= MAX_BACKEND_ARTIFACTS:
            raise BackendError("backend exceeded the artifact-count limit")
        if total_bytes > MAX_BACKEND_ARTIFACT_BYTES:
            raise BackendError("backend exceeded the total artifact-size limit")
        relative = path.relative_to(root).as_posix()
        suffix = path.suffix.casefold()
        media_type = {
            ".json": "application/json",
            ".md": "text/markdown",
            ".mmd": "text/x-mathpix-markdown",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(suffix, "application/octet-stream")
        artifacts.append({
            "path": f"{review_relative_root}/{relative}",
            "sha256": sha256_file(path),
            "media_type": media_type,
        })
    if not artifacts:
        raise BackendError("backend returned no durable artifacts")
    return artifacts


def docling_version() -> str | None:
    return _package_version("docling")


def docling_runtime_version() -> str | None:
    installed = docling_version()
    if not installed:
        return None
    components = [f"docling={installed}"]
    for package in ("docling-core", "docling-ibm-models", "docling-parse"):
        if component := _package_version(package):
            components.append(f"{package}={component}")
    return ";".join(components)


def docling_executable() -> str | None:
    """Find Docling in PATH or beside the active Python interpreter."""
    discovered = shutil.which("docling")
    if discovered:
        return discovered
    # Do not resolve the interpreter symlink: virtual environments commonly
    # link Python to a base installation while keeping console scripts local.
    sibling = Path(sys.executable).with_name("docling")
    return str(sibling) if sibling.is_file() and os.access(sibling, os.X_OK) else None


def _top_left_bbox(prov: dict[str, Any], page_height: float) -> list[float] | None:
    bbox = prov.get("bbox")
    if not isinstance(bbox, dict):
        return None
    try:
        left, top, right, bottom = (float(bbox[key]) for key in ("l", "t", "r", "b"))
    except (KeyError, TypeError, ValueError):
        return None
    if bbox.get("coord_origin") == "BOTTOMLEFT":
        top, bottom = page_height - top, page_height - bottom
    x0, x1 = sorted((left, right))
    y0, y1 = sorted((top, bottom))
    return [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]


def _normalize_docling(document: dict[str, Any]) -> dict[str, Any]:
    page_sizes = {
        int(value.get("page_no", key)): value.get("size", {})
        for key, value in document.get("pages", {}).items()
        if isinstance(value, dict)
    }
    pages: dict[int, list[dict[str, Any]]] = {}
    for collection, default_type in (("texts", "text"), ("tables", "table"), ("pictures", "picture")):
        for index, item in enumerate(document.get(collection, [])):
            if not isinstance(item, dict):
                continue
            for prov in item.get("prov", []):
                try:
                    page = int(prov["page_no"])
                    height = float(page_sizes[page]["height"])
                except (KeyError, TypeError, ValueError):
                    continue
                element: dict[str, Any] = {
                    "id": f"docling:{collection}:{index}",
                    "type": item.get("label") or default_type,
                    "bbox": _top_left_bbox(prov, height),
                    "text": item.get("text") or item.get("orig") or "",
                }
                if collection == "tables":
                    cells = item.get("data", {}).get("table_cells", [])
                    element["table_cells"] = [
                        {
                            "row_start": cell.get("start_row_offset_idx"),
                            "row_end": cell.get("end_row_offset_idx"),
                            "column_start": cell.get("start_col_offset_idx"),
                            "column_end": cell.get("end_col_offset_idx"),
                            "row_span": cell.get("row_span"), "column_span": cell.get("col_span"),
                            "text": cell.get("text", ""),
                        }
                        for cell in cells if isinstance(cell, dict)
                    ]
                pages.setdefault(page, []).append(element)
    return {
        "schema_version": "0.1", "engine": "docling",
        "document_schema": document.get("schema_name"),
        "document_version": document.get("version"),
        "pages": [
            {
                "page": page,
                "width": page_sizes.get(page, {}).get("width"),
                "height": page_sizes.get(page, {}).get("height"),
                "elements": elements,
            }
            for page, elements in sorted(pages.items())
        ],
    }


def _normalize_mathpix(lines: dict[str, Any], expected_pages: int) -> dict[str, Any]:
    raw_pages = lines.get("pages")
    if not isinstance(raw_pages, list):
        raise BackendError("Mathpix lines.json lacks a pages array")
    normalized_pages: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw_page in raw_pages:
        if not isinstance(raw_page, dict) or not isinstance(raw_page.get("lines"), list):
            raise BackendError("Mathpix lines.json contains an invalid page record")
        try:
            page = int(raw_page["page"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BackendError("Mathpix lines.json contains an invalid page number") from exc
        if page in seen:
            raise BackendError("Mathpix lines.json contains a duplicate page")
        seen.add(page)
        elements: list[dict[str, Any]] = []
        for index, line in enumerate(raw_page["lines"]):
            if not isinstance(line, dict):
                raise BackendError("Mathpix lines.json contains an invalid line record")
            region = line.get("region")
            bbox = None
            if isinstance(region, dict):
                coordinates = (
                    region.get("top_left_x"), region.get("top_left_y"),
                    region.get("width"), region.get("height"),
                )
                if all(isinstance(value, (int, float)) for value in coordinates):
                    x, y, width, height = coordinates
                    bbox = [x, y, x + width, y + height]
            elements.append({
                "id": str(line.get("id") or f"mathpix:line:{page}:{index}"),
                "type": str(line.get("type") or "line"),
                "subtype": line.get("subtype"), "bbox": bbox,
                "text": str(line.get("text") or ""),
                "confidence": line.get("confidence"),
                "confidence_rate": line.get("confidence_rate"),
            })
        normalized_pages.append({
            "page": page, "width": raw_page.get("page_width"),
            "height": raw_page.get("page_height"), "elements": elements,
        })
    if seen != set(range(1, expected_pages + 1)):
        raise BackendError("Mathpix lines.json page inventory differs from the source PDF")
    return {"schema_version": "0.1", "engine": "mathpix", "pages": normalized_pages}


def run_docling(
    pdf: Path,
    stage: Path,
    output_relative: str,
    *,
    allow_model_downloads: bool,
    enrich_formulas: bool,
    timeout: int,
    device: str,
) -> dict[str, Any]:
    executable = docling_executable()
    installed = docling_version()
    if not executable or not installed:
        raise BackendError(
            "Docling is unavailable; install the optional "
            f"{Path(__file__).resolve().parents[1] / 'requirements-docling.txt'} environment"
        )
    proposal_dir = stage / "proposals" / "docling"
    _private_mkdir(proposal_dir)
    command = [
        executable,
        str(pdf),
        "--from", "pdf",
        "--to", "md",
        "--to", "json",
        "--pipeline", "standard",
        "--ocr",
        "--tables",
        "--table-mode", "accurate",
        "--image-export-mode", "referenced",
        "--output", str(proposal_dir),
        "--device", device,
        "--num-threads", "4",
        "--document-timeout", str(timeout),
        "--enrich-formula" if enrich_formulas else "--no-enrich-formula",
        "-v",
    ]
    allowed_environment = {
        "PATH", "HOME", "TMPDIR", "XDG_CACHE_HOME", "HF_HOME", "TORCH_HOME",
        "DOCLING_ARTIFACTS_PATH", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
        "DYLD_LIBRARY_PATH",
    }
    if allow_model_downloads:
        allowed_environment.update({"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"})
    environment = {
        key: value for key, value in os.environ.items() if key in allowed_environment
    }
    environment.update({"LC_ALL": "C", "TZ": "UTC"})
    if not allow_model_downloads:
        environment.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=timeout + 60,
            env=environment,
        )
    except FileNotFoundError as exc:
        raise BackendError("Docling command disappeared during execution") from exc
    except subprocess.TimeoutExpired as exc:
        raise BackendError(f"Docling timed out after {timeout + 60} seconds") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", "replace")
        if not allow_model_downloads and (
            "offline" in stderr.casefold() or "cache" in stderr.casefold()
        ):
            raise BackendError(
                "Docling model artifacts are not cached; rerun with --allow-model-downloads after reviewing model licenses"
            ) from exc
        raise BackendError(f"Docling failed with exit code {exc.returncode}") from exc

    relative_root = f"{output_relative}/proposals/docling"
    stage_text = str(stage)
    proposal_text = relative_root
    for path in sorted(proposal_dir.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in {".md", ".json"}:
            continue
        raw = path.read_text(encoding="utf-8")
        # Docling's referenced-image export writes absolute output paths. Keep
        # the proposal movable and private by replacing the staging prefix.
        raw = raw.replace(stage_text + "/proposals/docling", proposal_text)
        _private_write(path, raw.encode("utf-8"))

    document_files = [
        path for path in proposal_dir.glob("*.json") if path.name != "normalized.json"
    ]
    if len(document_files) != 1:
        raise BackendError("Docling did not create exactly one structured document JSON")
    try:
        normalized = _normalize_docling(json.loads(document_files[0].read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BackendError("Docling structured JSON could not be normalized") from exc
    _private_write(
        proposal_dir / "normalized.json",
        (json.dumps(normalized, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
    )

    log = ((result.stdout or b"") + b"\n" + (result.stderr or b"")).decode("utf-8", "replace")
    log = log.replace(str(pdf), "<source.pdf>").replace(stage_text, "<package>")
    redactions = {
        os.environ.get("HOME"): "<home>", os.environ.get("TMPDIR"): "<temp>",
        os.environ.get("XDG_CACHE_HOME"): "<cache>", os.environ.get("HF_HOME"): "<model-cache>",
        os.environ.get("TORCH_HOME"): "<model-cache>",
    }
    for raw, replacement in sorted(
        ((raw, replacement) for raw, replacement in redactions.items() if raw),
        key=lambda row: len(row[0]), reverse=True,
    ):
        log = log.replace(raw, replacement)
    log = re.sub(r"(https?://)[^/\s:@]+:[^@\s]+@", r"\1<redacted>@", log)
    revisions = sorted(set(
        (match.group(1), match.group(2))
        for match in re.finditer(r"models/([^\s/]+/[^\s/]+)/revision/([0-9a-f]{7,64})", log)
    ))
    runtime_revisions = [
        (f"python-package/{package}", component)
        for package in ("docling-core", "docling-ibm-models", "docling-parse")
        if (component := _package_version(package))
    ]
    _private_write(proposal_dir / "run.log", log.encode("utf-8"))
    artifacts = _safe_artifacts(proposal_dir, relative_root)
    if not any(row["path"].endswith(".md") for row in artifacts):
        raise BackendError("Docling did not create Markdown")
    if not any(row["path"].endswith(".json") for row in artifacts):
        raise BackendError("Docling did not create structured JSON")
    return {
        "id": "PRP-DOCLING",
        "engine": "docling",
        "version": installed,
        "role": "semantic_structure",
        "mode": "local",
        "authoritative": False,
        "input_sha256": sha256_file(pdf),
        "artifacts": artifacts,
        "model_revisions": [
            {"name": name, "revision": revision}
            for name, revision in sorted(set([*revisions, *runtime_revisions]))
        ],
        "processing": {
            "manuscript_uploaded": False,
            "user_authorized": True,
            "credential_source": "none",
            "retention_policy": None,
            "remote_deletion": "not_applicable",
            "request_id": None,
        },
        "warnings": [
            "Docling output is a non-authoritative proposal and must be reconciled with native text and page renders.",
            *(
                ["Docling downloaded model artifacts; pin and audit every recorded model before product release."]
                if allow_model_downloads else []
            ),
            *(
                ["Formula enrichment is model-generated and remains render-bounded until independently verified."]
                if enrich_formulas else []
            ),
            *(
                ["Exact model-weight revisions were not observed in the Docling log; runtime package versions are recorded but weight provenance remains bounded."]
                if not revisions else []
            ),
        ],
    }


def _bounded_content(response: Any, label: str) -> bytes:
    length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
    if length is not None:
        try:
            if int(length) > MAX_VENDOR_RESPONSE_BYTES:
                raise BackendError(f"Mathpix {label} exceeded the configured response limit")
        except ValueError as exc:
            raise BackendError(f"Mathpix {label} returned an invalid Content-Length") from exc
    content = bytearray()
    try:
        chunks = response.iter_content(chunk_size=1024 * 1024)
        for chunk in chunks:
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > MAX_VENDOR_RESPONSE_BYTES:
                raise BackendError(f"Mathpix {label} exceeded the configured response limit")
    except BackendError:
        raise
    except Exception as exc:
        raise BackendError(f"Mathpix {label} response streaming failed") from exc
    return bytes(content)


def _mathpix_request(
    session: Any,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    timeout: int,
    **kwargs: Any,
) -> Any:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "api.mathpix.com" or parsed.port not in (None, 443):
        raise BackendError("Mathpix request target is outside the fixed API origin")
    kwargs["allow_redirects"] = False
    try:
        response = session.request(method, url, headers=headers, timeout=timeout, **kwargs)
    except Exception as exc:
        raise BackendError(f"Mathpix {method} request failed: {type(exc).__name__}") from exc
    if not 200 <= response.status_code < 300:
        raise BackendError(f"Mathpix {method} request returned HTTP {response.status_code}")
    return response


def run_mathpix(
    pdf: Path,
    stage: Path,
    output_relative: str,
    *,
    app_id: str,
    app_key: str,
    timeout: int,
    poll_interval: float,
    expected_pages: int,
) -> dict[str, Any]:
    if not app_id or not app_key:
        raise BackendError("Mathpix requires MATHPIX_APP_ID and MATHPIX_APP_KEY")
    try:
        import requests
    except ImportError as exc:
        raise BackendError(
            "Mathpix requires the optional "
            f"{Path(__file__).resolve().parents[1] / 'requirements-mathpix.txt'} environment"
        ) from exc

    proposal_dir = stage / "proposals" / "mathpix"
    _private_mkdir(proposal_dir)
    headers = {"app_id": app_id, "app_key": app_key}
    options = {
        "metadata": {"improve_mathpix": False},
        "include_page_breaks": True,
        "include_equation_tags": True,
        "include_diagram_text": True,
        "preserve_section_numbering": True,
        "enable_tables_fallback": True,
        "rm_fonts": False,
        "numbers_default_to_math": False,
    }
    session = requests.Session()
    pdf_id: str | None = None
    delete_state = "unconfirmed"
    status_summary: dict[str, Any] = {}
    primary_error: Exception | None = None
    try:
        with pdf.open("rb") as handle:
            response = _mathpix_request(
                session,
                "POST",
                f"{MATHPIX_API_ROOT}/pdf",
                headers=headers,
                timeout=min(timeout, 300),
                files={"file": ("document.pdf", handle, "application/pdf")},
                data={"options_json": json.dumps(options, sort_keys=True)},
            )
        try:
            submitted = response.json()
            pdf_id = submitted["pdf_id"]
        except (ValueError, KeyError, TypeError) as exc:
            raise BackendError("Mathpix submission did not return a pdf_id") from exc
        if not isinstance(pdf_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{4,160}", pdf_id):
            raise BackendError("Mathpix returned an unsafe request identifier")

        deadline = time.monotonic() + timeout
        delay = max(1.0, poll_interval)
        while True:
            if time.monotonic() >= deadline:
                raise BackendError(f"Mathpix processing timed out; remote request id: {pdf_id}")
            response = _mathpix_request(
                session,
                "GET",
                f"{MATHPIX_API_ROOT}/pdf/{pdf_id}",
                headers=headers,
                timeout=min(60, timeout),
            )
            try:
                status = response.json()
            except ValueError as exc:
                raise BackendError("Mathpix status response was not JSON") from exc
            state = status.get("status")
            status_summary = {
                key: status[key]
                for key in ("status", "num_pages", "num_pages_completed", "percent_done")
                if key in status
            }
            if state == "completed":
                break
            if state == "error":
                raise BackendError(f"Mathpix processing failed; remote request id: {pdf_id}")
            if state not in {"received", "loaded", "split"}:
                raise BackendError(f"Mathpix returned unknown processing state; remote request id: {pdf_id}")
            time.sleep(delay)
            delay = min(delay * 1.35, 15.0)

        if status_summary.get("num_pages") not in (None, expected_pages):
            raise BackendError("Mathpix completed page count differs from the source PDF")
        for extension, name in (("mmd", "document.mmd"), ("lines.json", "lines.json")):
            response = _mathpix_request(
                session,
                "GET",
                f"{MATHPIX_API_ROOT}/pdf/{pdf_id}.{extension}",
                headers=headers,
                timeout=min(300, timeout),
                stream=True,
            )
            content = _bounded_content(response, extension)
            if extension == "lines.json":
                try:
                    json.loads(content)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise BackendError("Mathpix lines.json was invalid") from exc
            _private_write(proposal_dir / name, content)
        try:
            lines = json.loads((proposal_dir / "lines.json").read_text(encoding="utf-8"))
            normalized = _normalize_mathpix(lines, expected_pages)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BackendError("Mathpix lines.json could not be normalized") from exc
        _private_write(
            proposal_dir / "normalized.json",
            (json.dumps(normalized, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )
    except Exception as exc:
        primary_error = exc
    finally:
        if pdf_id is not None:
            try:
                response = _mathpix_request(
                    session,
                    "DELETE",
                    f"{MATHPIX_API_ROOT}/pdf/{pdf_id}",
                    headers=headers,
                    timeout=min(60, timeout),
                )
                delete_state = "confirmed" if response.status_code < 300 else "failed"
            except Exception:
                delete_state = "failed"
        session.close()
    if primary_error is not None:
        if delete_state == "failed" and pdf_id:
            raise BackendError(
                f"{primary_error}; remote deletion was not confirmed for request id {pdf_id}"
            ) from primary_error
        raise primary_error
    if delete_state != "confirmed" or pdf_id is None:
        raise BackendError(
            f"Mathpix output was downloaded but remote deletion was not confirmed for request id {pdf_id or 'unknown'}"
        )

    receipt = {
        "provider": "mathpix",
        "request_id": pdf_id,
        "status": status_summary,
        "options": options,
        "remote_deletion": delete_state,
    }
    _private_write(
        proposal_dir / "receipt.json",
        (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    relative_root = f"{output_relative}/proposals/mathpix"
    artifacts = _safe_artifacts(proposal_dir, relative_root)
    return {
        "id": "PRP-MATHPIX",
        "engine": "mathpix",
        "version": "v3/pdf",
        "role": "scientific_ocr",
        "mode": "remote",
        "authoritative": False,
        "input_sha256": sha256_file(pdf),
        "artifacts": artifacts,
        "model_revisions": [],
        "processing": {
            "manuscript_uploaded": True,
            "user_authorized": True,
            "credential_source": "environment",
            "retention_policy": (
                "metadata.improve_mathpix=false; source deletion requested after processing; "
                "endpoint documentation permits page-image/CDN retention and text retention until explicit deletion"
            ),
            "remote_deletion": delete_state,
            "request_id": pdf_id,
        },
        "warnings": [
            "Mathpix output is a non-authoritative proposal and must be reconciled with native text and page renders.",
            "Remote deletion was confirmed, but provider billing/audit metadata and short-lived CDN caches may remain under provider policy.",
            "Do not use Mathpix output to train a competing conversion model without written permission and legal review.",
        ],
    }
