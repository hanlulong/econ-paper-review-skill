#!/usr/bin/env python3
"""Verify and serve one immutable Review Desk release on loopback only."""

from __future__ import annotations

import argparse
import hashlib
import http.server
import http.client
import json
import mimetypes
import os
import shutil
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path, PurePosixPath


HOST = "127.0.0.1"
DEFAULT_PORT = 48127
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self' data:; form-action 'self'; frame-ancestors 'none'; img-src 'self' data: blob:; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def load_inventory(root: Path) -> dict[str, tuple[int, str]]:
    manifest_path = root / "bundle-manifest.json"
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
    inventory: dict[str, tuple[int, str]] = {}
    if not isinstance(value["files"], list):
        raise ValueError("Review Desk manifest files must be an array")
    for record in value["files"]:
        if not isinstance(record, dict):
            raise ValueError("Review Desk manifest contains a non-object file record")
        if set(record) != {"path", "sha256", "size"}:
            raise ValueError("Review Desk manifest contains an invalid file record")
        raw_path = record["path"]
        if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path or ":" in raw_path:
            raise ValueError("Review Desk manifest contains an unsafe file path")
        path = PurePosixPath(raw_path)
        if not path.parts or path.parts[0] != "app" or path.is_absolute() or ".." in path.parts:
            if path.as_posix() in {"launch_review_desk.py", "launch_installed_review_desk.py"}:
                continue
            raise ValueError(f"unsafe Review Desk manifest path: {path}")
        relative = PurePosixPath(*path.parts[1:]).as_posix()
        if not relative:
            raise ValueError("empty Review Desk application path")
        candidate = root.joinpath(*path.parts)
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f"Review Desk file is missing or unsafe: {path}")
        data = candidate.read_bytes()
        if (
            not isinstance(record["size"], int)
            or isinstance(record["size"], bool)
            or not isinstance(record["sha256"], str)
            or len(data) != record["size"]
            or hashlib.sha256(data).hexdigest() != record["sha256"]
        ):
            raise ValueError(f"Review Desk file failed integrity verification: {path}")
        inventory[relative] = (record["size"], record["sha256"])
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
) -> bool:
    """Return true only when the occupied port serves this Review Desk shape."""

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
        if verified_server_is_running(args.port, inventory):
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
