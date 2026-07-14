#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import posixpath
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INSTALLER = load_module("install_econ_review_for_desk_tests", ROOT / "scripts" / "install_econ_review.py")
LAUNCHER = load_module(
    "launch_review_desk_for_tests",
    ROOT / "review-viewer" / "scripts" / "launch_review_desk.py",
)
BUILDER = load_module(
    "build_review_desk_release_for_tests",
    ROOT / "review-viewer" / "scripts" / "build_review_desk_release.py",
)


class LocalAssetReferenceParser(HTMLParser):
    """Collect browser-loaded asset references from one static HTML file."""

    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(
        self,
        _tag: str,
        attributes: list[tuple[str, str | None]],
    ) -> None:
        self.references.extend(
            value
            for name, value in attributes
            if name in {"href", "src"} and value
        )


class ReviewDeskReleaseTests(unittest.TestCase):
    def install_release(self, root: Path) -> Path:
        with contextlib.redirect_stdout(io.StringIO()):
            return INSTALLER.install_review_desk(
                ROOT / "review-viewer" / "release" / "review-desk.zip",
                root,
                dry_run=False,
            )

    def test_builder_embeds_synchronized_first_party_license(self) -> None:
        data = BUILDER.build_bytes()
        BUILDER.verify_bundle_bytes(data)
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "review-desk.zip"
            bundle.write_bytes(data)
            _manifest, records, _digest = INSTALLER.verify_review_desk_bundle(bundle)
            self.assertIn("app/LICENSE.txt", {record["path"] for record in records})
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(
                archive.read("app/LICENSE.txt"),
                (ROOT / "review-viewer" / "LICENSE").read_bytes(),
            )

    def test_checked_in_bundle_is_deterministic_and_runtime_free(self) -> None:
        expected = (ROOT / "review-viewer" / "release" / "review-desk.zip").read_bytes()
        BUILDER.verify_bundle_bytes(expected)
        if BUILDER.STATIC_ROOT.is_dir():
            self.assertEqual(BUILDER.build_bytes(), expected)
        manifest, records, digest = INSTALLER.verify_review_desk_bundle(
            ROOT / "review-viewer" / "release" / "review-desk.zip"
        )
        self.assertEqual(len(digest), 64)
        self.assertTrue(manifest.endswith(b"\n"))
        paths = {record["path"] for record in records}
        self.assertIn("app/index.html", paths)
        self.assertIn(BUILDER.FAVICON, paths)
        self.assertIn("app/LICENSE.txt", paths)
        self.assertIn("app/THIRD_PARTY_NOTICES.txt", paths)
        self.assertIn("app/third-party-licenses/manifest.json", paths)
        self.assertIn("app/third-party-licenses/katex-fonts/KATEX-FONTS-OFL-1.1.txt", paths)
        self.assertIn("launch_installed_review_desk.py", paths)
        self.assertIn("launch_review_desk.py", paths)
        self.assertFalse(any(str(path).endswith(".map") for path in paths))
        self.assertFalse(any("node_modules" in str(path) or "/reviews/" in str(path) for path in paths))
        with zipfile.ZipFile(ROOT / "review-viewer" / "release" / "review-desk.zip") as archive:
            self.assertEqual(
                archive.read(BUILDER.FAVICON),
                BUILDER.FAVICON_SOURCE.read_bytes(),
            )
            parser = LocalAssetReferenceParser()
            parser.feed(archive.read("app/index.html").decode("utf-8"))
            local_references: list[tuple[str, str]] = []
            for reference in parser.references:
                parsed = urllib.parse.urlsplit(reference)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                decoded = urllib.parse.unquote(parsed.path)
                archive_path = (
                    f"app/{decoded.lstrip('/')}"
                    if decoded.startswith("/")
                    else posixpath.normpath(posixpath.join("app", decoded))
                )
                local_references.append((reference, archive_path))
            self.assertTrue(local_references)
            for reference, archive_path in local_references:
                with self.subTest(reference=reference):
                    self.assertFalse(archive_path.startswith("../"))
                    self.assertIn(archive_path, paths)
            self.assertEqual(
                archive.read("app/LICENSE.txt"),
                (ROOT / "review-viewer" / "LICENSE").read_bytes(),
            )
            licenses = json.loads(archive.read("app/third-party-licenses/manifest.json"))
            package_names = {package["name"] for package in licenses["packages"]}
            self.assertGreater(len(licenses["packages"]), 20)
            self.assertTrue(BUILDER.REQUIRED_RUNTIME_PACKAGES.issubset(package_names))
            self.assertFalse({"vite", "vinext", "wrangler"} & package_names)
            referenced = {
                path
                for package in licenses["packages"]
                for path in package["license_files"]
            }
            referenced.update(
                path
                for asset in licenses["supplemental_assets"]
                for path in asset["license_files"]
            )
            self.assertTrue(referenced.issubset(paths))

    def test_loopback_server_allows_only_manifest_get_and_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            installed = self.install_release(Path(tmp) / "desk")
            inventory = LAUNCHER.load_inventory(installed)
            server = LAUNCHER.LoopbackServer((LAUNCHER.HOST, 0), LAUNCHER.ReviewDeskHandler)
            server.inventory = inventory
            server.app_root = installed / "app"
            server.manifest_digest = installed.name
            server.quiet = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://{LAUNCHER.HOST}:{server.server_address[1]}"
            try:
                with urllib.request.urlopen(base + "/", timeout=5) as response:
                    body = response.read()
                    self.assertEqual(response.status, 200)
                    self.assertIn(b'<div id="root"></div>', body)
                    self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
                    self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
                    self.assertEqual(
                        response.headers[LAUNCHER.MANIFEST_DIGEST_HEADER],
                        installed.name,
                    )
                request = urllib.request.Request(base + "/", method="HEAD")
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), b"")
                script = next(path for path in inventory if path.endswith(".js"))
                with urllib.request.urlopen(base + "/" + script, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers["Content-Type"], "text/javascript")
                    self.assertIn("immutable", response.headers["Cache-Control"])
                for method, path, code in (
                    ("POST", "/", 405),
                    ("GET", "/%2e%2e/bundle-manifest.json", 404),
                    ("GET", "/reviews/index.json", 404),
                ):
                    with self.subTest(method=method, path=path):
                        request = urllib.request.Request(base + path, method=method)
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(request, timeout=5)
                        self.assertEqual(raised.exception.code, code)
                        self.assertIn("default-src 'self'", raised.exception.headers["Content-Security-Policy"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_launcher_recognizes_an_already_running_verified_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            installed = self.install_release(Path(tmp) / "desk")
            inventory = LAUNCHER.load_inventory(installed)
            server = LAUNCHER.LoopbackServer((LAUNCHER.HOST, 0), LAUNCHER.ReviewDeskHandler)
            server.inventory = inventory
            server.app_root = installed / "app"
            server.manifest_digest = installed.name
            server.quiet = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertTrue(
                    LAUNCHER.verified_server_is_running(
                        server.server_address[1], inventory, installed.name
                    )
                )
                self.assertFalse(
                    LAUNCHER.verified_server_is_running(
                        server.server_address[1], inventory, "0" * 64
                    )
                )
                mismatched = dict(inventory)
                size, digest = mismatched["index.html"]
                mismatched["index.html"] = (size + 1, digest)
                self.assertFalse(
                    LAUNCHER.verified_server_is_running(
                        server.server_address[1], mismatched, installed.name
                    )
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_running_server_refuses_asset_tampering_after_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            installed = self.install_release(Path(tmp) / "desk")
            inventory = LAUNCHER.load_inventory(installed)
            server = LAUNCHER.LoopbackServer((LAUNCHER.HOST, 0), LAUNCHER.ReviewDeskHandler)
            server.inventory = inventory
            server.app_root = installed / "app"
            server.manifest_digest = installed.name
            server.quiet = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            script = next(path for path in inventory if path.endswith(".js"))
            script_path = installed / "app" / script
            script_path.write_bytes(script_path.read_bytes() + b"tampered")
            try:
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(
                        f"http://{LAUNCHER.HOST}:{server.server_address[1]}/{script}",
                        timeout=5,
                    )
                self.assertEqual(raised.exception.code, 500)
                self.assertEqual(
                    raised.exception.headers[LAUNCHER.MANIFEST_DIGEST_HEADER],
                    installed.name,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_launcher_detects_installed_file_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            installed = self.install_release(Path(tmp) / "desk")
            index = installed / "app" / "index.html"
            index.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "integrity verification"):
                LAUNCHER.load_inventory(installed)


if __name__ == "__main__":
    unittest.main()
