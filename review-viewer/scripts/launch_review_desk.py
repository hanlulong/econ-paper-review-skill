#!/usr/bin/env python3
"""Verify and serve one immutable Review Desk release on loopback only."""

from __future__ import annotations

import sys


# The immutable release directory is data, not an import root.  Remove it from
# Python's import path before importing shadowable standard-library modules.
# The stable dispatcher uses ``-I``, which already omits the script directory.
if __name__ == "__main__" and not sys.flags.isolated and sys.path:
    _SCRIPT_PATH_ENTRY = sys.path[0]
    sys.path[:] = [
        entry
        for index, entry in enumerate(sys.path)
        if index != 0 and entry not in {"", _SCRIPT_PATH_ENTRY}
    ]

import argparse
import hashlib
import http.server
import http.client
import json
import mimetypes
import os
import shutil
import socketserver
import stat
import subprocess
import threading
import unicodedata
import urllib.parse
import webbrowser
from pathlib import Path, PurePosixPath


HOST = "127.0.0.1"
DEFAULT_PORT = 48127
MANIFEST_DIGEST_HEADER = "X-Review-Desk-Manifest-SHA256"
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self' data:; form-action 'self'; frame-ancestors 'none'; img-src 'self' data: blob:; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction and is_junction():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _safe_manifest_path(raw: object) -> PurePosixPath:
    if (
        not isinstance(raw, str)
        or not raw
        or "\\" in raw
        or ":" in raw
        or raw.startswith("/")
        or raw != unicodedata.normalize("NFC", raw)
        or any(ord(character) < 32 or ord(character) == 127 for character in raw)
    ):
        raise ValueError(f"unsafe Review Desk manifest path: {raw!r}")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} or part != part.strip() or part.endswith(".") for part in path.parts)
        or raw != path.as_posix()
        or (
            raw not in {"launch_review_desk.py", "launch_installed_review_desk.py"}
            and path.parts[0] != "app"
        )
    ):
        raise ValueError(f"unsafe Review Desk manifest path: {raw!r}")
    return path


def _verify_exact_membership(root: Path, expected_files: set[str]) -> None:
    expected_directories = {""}
    for raw in expected_files:
        parts = PurePosixPath(raw).parts
        for length in range(1, len(parts)):
            expected_directories.add(PurePosixPath(*parts[:length]).as_posix())

    actual_files: set[str] = set()
    actual_directories: set[str] = set()

    def raise_walk_error(error: OSError) -> None:
        raise error

    for current, directories, names in os.walk(
        root,
        followlinks=False,
        onerror=raise_walk_error,
    ):
        current_path = Path(current)
        if _is_link_or_junction(current_path):
            raise ValueError("installed Review Desk contains a link or junction")
        relative_directory = current_path.relative_to(root).as_posix()
        actual_directories.add("" if relative_directory == "." else relative_directory)
        for name in directories:
            candidate = current_path / name
            if _is_link_or_junction(candidate) or not candidate.is_dir():
                raise ValueError("installed Review Desk contains an unsafe directory")
        for name in names:
            candidate = current_path / name
            if _is_link_or_junction(candidate) or not candidate.is_file():
                raise ValueError("installed Review Desk contains a non-regular file")
            actual_files.add(candidate.relative_to(root).as_posix())

    if actual_files != expected_files or actual_directories != expected_directories:
        raise ValueError("installed Review Desk differs from its exact manifest membership")


def load_inventory(root: Path) -> dict[str, tuple[int, str]]:
    manifest_path = root / "bundle-manifest.json"
    if _is_link_or_junction(root) or not root.is_dir():
        raise ValueError("installed Review Desk version directory is missing or unsafe")
    if _is_link_or_junction(manifest_path) or not manifest_path.is_file():
        raise ValueError("installed Review Desk manifest is missing or unsafe")
    manifest_bytes = manifest_path.read_bytes()
    expected_digest = root.name
    actual_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if expected_digest != actual_digest:
        raise ValueError("installed Review Desk version does not match its immutable digest directory")
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate manifest key: {key}")
            value[key] = item
        return value

    value = json.loads(
        manifest_bytes.decode("utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(f"invalid constant: {constant}")),
    )
    if not isinstance(value, dict):
        raise ValueError("Review Desk manifest must be an object")
    if set(value) != {"files", "package", "schema_version"}:
        raise ValueError("Review Desk manifest has unexpected fields")
    if value["package"] != "econ-review-desk" or value["schema_version"] != "1":
        raise ValueError("Review Desk manifest has the wrong package or schema version")
    records = value["files"]
    if not isinstance(records, list) or not records or len(records) > 500:
        raise ValueError("Review Desk manifest files must be a non-empty bounded array")
    inventory: dict[str, tuple[int, str]] = {}
    expected_files = {"bundle-manifest.json"}
    checked: list[tuple[PurePosixPath, int, str]] = []
    previous = ""
    folded: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Review Desk manifest contains a non-object file record")
        if set(record) != {"path", "sha256", "size"}:
            raise ValueError("Review Desk manifest contains an invalid file record")
        path = _safe_manifest_path(record["path"])
        name = path.as_posix()
        if name <= previous or name.casefold() in folded:
            raise ValueError("Review Desk manifest file records must be sorted and portable-unique")
        previous = name
        folded.add(name.casefold())
        size = record["size"]
        digest = record["sha256"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError(f"invalid Review Desk file size: {path}")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"invalid Review Desk file hash: {path}")
        expected_files.add(name)
        checked.append((path, size, digest))

    if not {
        "launch_review_desk.py",
        "launch_installed_review_desk.py",
        "app/index.html",
    }.issubset(expected_files):
        raise ValueError("Review Desk release lacks its launchers or application entry point")
    _verify_exact_membership(root, expected_files)
    for path, size, digest in checked:
        candidate = root.joinpath(*path.parts)
        data = candidate.read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"Review Desk file failed integrity verification: {path}")
        if path.parts[0] == "app":
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            if not relative:
                raise ValueError("empty Review Desk application path")
            inventory[relative] = (size, digest)
    if "index.html" not in inventory:
        raise ValueError("Review Desk release has no index.html")
    return inventory


class ReviewDeskHandler(http.server.BaseHTTPRequestHandler):
    server_version = "ReviewDesk/1"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._serve(send_body=True)

    def do_HEAD(self) -> None:
        self._serve(send_body=False)

    def do_POST(self) -> None:
        self._method_not_allowed()

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        self._security_headers()
        self.end_headers()

    def _serve(self, *, send_body: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        try:
            decoded = urllib.parse.unquote(parsed.path, errors="strict")
        except UnicodeError:
            self.send_error(400)
            return
        if "\\" in decoded or "\x00" in decoded:
            self.send_error(400)
            return
        relative = decoded.lstrip("/") or "index.html"
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative:
            self.send_error(404)
            return
        if relative not in self.server.inventory:  # type: ignore[attr-defined]
            self.send_error(404)
            return
        path = self.server.app_root.joinpath(*pure.parts)  # type: ignore[attr-defined]
        if path.is_symlink() or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        expected_size, expected_digest = self.server.inventory[relative]  # type: ignore[attr-defined]
        if len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_digest:
            self.send_error(500, "Review Desk asset failed integrity verification")
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            content_type = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store" if relative == "index.html" else "public, max-age=31536000, immutable")
        self._security_headers()
        self.end_headers()
        if send_body:
            self.wfile.write(data)

    def _security_headers(self) -> None:
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        manifest_digest = getattr(self.server, "manifest_digest", "")
        if manifest_digest:
            self.send_header(MANIFEST_DIGEST_HEADER, manifest_digest)

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        short, long = self.responses.get(code, ("Error", "Request failed"))
        body = f"{code} {message or short}\n".encode("utf-8")
        self.send_response(code, message or short)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        if getattr(self.server, "quiet", False):  # type: ignore[attr-defined]
            return
        super().log_message(format, *args)


class LoopbackServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def verified_server_is_running(
    port: int,
    inventory: dict[str, tuple[int, str]],
    manifest_digest: str,
) -> bool:
    """Return true only when the occupied port serves this exact Review Desk release."""

    expected_size, expected_digest = inventory.get("index.html", (-1, ""))
    connection = http.client.HTTPConnection(HOST, port, timeout=1.5)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read(expected_size + 1 if expected_size >= 0 else 1)
        return (
            response.status == 200
            and response.getheader("Content-Length") == str(expected_size)
            and len(body) == expected_size
            and hashlib.sha256(body).hexdigest() == expected_digest
            and response.getheader(MANIFEST_DIGEST_HEADER) == manifest_digest
            and response.getheader("X-Content-Type-Options") == "nosniff"
            and response.getheader("Cross-Origin-Opener-Policy") == "same-origin"
            and (response.getheader("Server") or "").startswith("ReviewDesk/1")
        )
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def port_owner_hint(port: int) -> str | None:
    """Best-effort PID hint for a conflicting listener; never required to launch."""

    try:
        if os.name == "nt":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
                check=False,
            )
            suffix = f":{port}"
            for line in result.stdout.splitlines():
                columns = line.split()
                if (
                    len(columns) >= 5
                    and columns[1].endswith(suffix)
                    and columns[3].upper() == "LISTENING"
                    and columns[4].isdigit()
                ):
                    return f"PID {columns[4]}"
        elif shutil.which("lsof"):
            result = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
                check=False,
            )
            pid = result.stdout.strip().splitlines()
            if pid and pid[0].isdigit():
                return f"PID {pid[0]}"
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def open_review_desk(url: str) -> None:
    if not webbrowser.open(url):
        print(f"The browser did not open automatically. Open {url} manually.", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the installed Review Desk on a stable loopback origin.")
    parser.add_argument("--no-browser", action="store_true", help="do not open the default browser")
    parser.add_argument("--quiet", action="store_true", help="suppress request logs")
    parser.add_argument("--check", action="store_true", help="verify the installed release without serving it")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"loopback port (default: {DEFAULT_PORT})",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    root = Path(__file__).resolve().parent
    inventory = load_inventory(root)
    if args.check:
        print(f"Review Desk integrity check passed: {root.name}")
        return 0
    app_root = root / "app"
    try:
        server = LoopbackServer((HOST, args.port), ReviewDeskHandler)
    except OSError as exc:
        url = f"http://{HOST}:{args.port}/"
        if verified_server_is_running(args.port, inventory, root.name):
            print(f"Review Desk is already verified and running at {url}")
            if not args.no_browser:
                open_review_desk(url)
            return 0
        owner = port_owner_hint(args.port)
        owner_detail = f" ({owner})" if owner else ""
        raise RuntimeError(
            f"could not bind the Review Desk origin {url}; the port is occupied{owner_detail}. "
            "Close that process or choose another port with --port."
        ) from exc
    server.inventory = inventory  # type: ignore[attr-defined]
    server.app_root = app_root  # type: ignore[attr-defined]
    server.manifest_digest = root.name  # type: ignore[attr-defined]
    server.quiet = args.quiet  # type: ignore[attr-defined]
    url = f"http://{HOST}:{args.port}/"
    print(f"Review Desk verified and available at {url}")
    print("Press Ctrl+C to stop it. Review files remain in the browser and are not uploaded.")
    if not args.no_browser:
        timer = threading.Timer(0.2, open_review_desk, args=(url,))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Review Desk could not start: {exc}", file=sys.stderr)
        raise SystemExit(1)
