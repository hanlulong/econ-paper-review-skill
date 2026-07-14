#!/usr/bin/env bash

set -euo pipefail

MODE="global"
PLATFORM="all"
TARGET=""
DRY_RUN=0
MODE_SEEN=""
PLATFORM_SEEN=""
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
TEMP_DIR=""
ACTIVE_STAGE=""
ACTIVE_BACKUP=""
ACTIVE_DESTINATION=""

usage() {
  cat <<'EOF'
Install econ-review for Claude Code and/or Codex.

Usage:
  ./install.sh [--global | --local [directory]] [--all | --claude | --codex] [--dry-run]
  ./install.sh --setup [managed-setup options]

Examples:
  ./install.sh
  ./install.sh --global --codex
  ./install.sh --local /path/to/project --all
  ./install.sh --local . --dry-run
  ./install.sh --setup --global --all --with-review-desk

The default command preserves the lightweight copy-only installer. --setup
delegates to the cross-platform Python installer, which creates or reuses a
managed core runtime and checks Poppler. Native Windows users should run:
  py -3 scripts/install_econ_review.py --global --all --with-review-desk

The explicit --with-review-desk option installs a verified prebuilt viewer and
loopback-only Python launcher. It does not require Node.js or npm. Omit that
option to preserve skill-only managed setup.

Local checkouts install directly. Remote installation is disabled unless both
ECON_REVIEW_ARCHIVE_URL (HTTPS) and ECON_REVIEW_ARCHIVE_SHA256 (64 hex digits)
are supplied. The archive checksum, embedded release manifest, every file hash,
and every extraction path are verified before installation.
EOF
}

fail() {
  echo "econ-review installer: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

SETUP_REQUESTED=0
SETUP_ARGS=()
for argument in "$@"; do
  if [ "$argument" = "--setup" ]; then
    SETUP_REQUESTED=1
  else
    SETUP_ARGS+=("$argument")
  fi
done
if [ "$SETUP_REQUESTED" -eq 1 ]; then
  require_command python3
  [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/scripts/install_econ_review.py" ] \
    || fail "--setup requires a complete local checkout; run scripts/install_econ_review.py from the repository"
  exec python3 "$SCRIPT_DIR/scripts/install_econ_review.py" "${SETUP_ARGS[@]}"
fi

set_mode() {
  [ -z "$MODE_SEEN" ] || [ "$MODE_SEEN" = "$1" ] || fail "choose only one of --global and --local"
  MODE_SEEN="$1"
  MODE="$1"
}

set_platform() {
  [ -z "$PLATFORM_SEEN" ] || [ "$PLATFORM_SEEN" = "$1" ] || fail "choose only one of --all, --claude, and --codex"
  PLATFORM_SEEN="$1"
  PLATFORM="$1"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --global)
      set_mode global
      shift
      ;;
    --local)
      set_mode local
      shift
      if [ "$#" -gt 0 ] && [ "${1#--}" = "$1" ]; then
        TARGET="$1"
        shift
      fi
      ;;
    --all)
      set_platform all
      shift
      ;;
    --claude)
      set_platform claude
      shift
      ;;
    --codex)
      set_platform codex
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --*)
      fail "unknown option: $1"
      ;;
    *)
      fail "unexpected argument: $1"
      ;;
  esac
done

cleanup() {
  status=$?
  if [ -n "$ACTIVE_BACKUP" ] && [ -e "$ACTIVE_BACKUP" ] && [ -n "$ACTIVE_DESTINATION" ]; then
    rm -rf -- "$ACTIVE_DESTINATION"
    mv -- "$ACTIVE_BACKUP" "$ACTIVE_DESTINATION" || true
  elif [ -n "$ACTIVE_DESTINATION" ] && [ -n "$ACTIVE_STAGE" ] && [ ! -e "$ACTIVE_STAGE" ]; then
    # A signal may arrive after the stage was renamed but before the commit
    # markers were cleared. Restore the prior absence in that narrow window.
    rm -rf -- "$ACTIVE_DESTINATION"
  fi
  if [ -n "$ACTIVE_STAGE" ] && [ -e "$ACTIVE_STAGE" ]; then
    rm -rf -- "$ACTIVE_STAGE"
  fi
  if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
    rm -rf -- "$TEMP_DIR"
  fi
  return "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

validate_skill_tree() {
  python3 - "$1" <<'PY'
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
if not root.is_dir() or root.is_symlink():
    raise SystemExit("source econ-review tree is missing or is a symbolic link")
skill = root / "SKILL.md"
if not skill.is_file() or skill.is_symlink():
    raise SystemExit("source econ-review tree is missing a safe SKILL.md")
try:
    text = skill.read_text(encoding="utf-8")
except UnicodeDecodeError as exc:
    raise SystemExit(f"SKILL.md is not UTF-8: {exc}")
if "\nname: econ-review\n" not in f"\n{text}":
    raise SystemExit("SKILL.md has the wrong name")
for current, directories, files in os.walk(root, followlinks=False):
    for name in [*directories, *files]:
        path = Path(current, name)
        if path.is_symlink():
            raise SystemExit(f"source tree contains a symbolic link: {path.relative_to(root)}")
        if (
            name == ".env"
            or (name.startswith(".env.") and name != ".env.example")
            or path.suffix.casefold() in {".key", ".pem", ".p12"}
        ):
            raise SystemExit(f"source tree contains a credential-bearing file: {path.relative_to(root)}")
PY
}

verify_and_extract_archive() {
  archive="$1"
  expected_sha="$2"
  destination="$3"
  python3 - "$archive" "$expected_sha" "$destination" <<'PY'
import hashlib
import json
import re
import stat
import sys
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

archive_path = Path(sys.argv[1])
expected_sha = sys.argv[2].lower()
destination = Path(sys.argv[3])
if archive_path.stat().st_size > 100 * 1024 * 1024:
    raise SystemExit("release archive exceeds the 100 MiB safety limit")
if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
    raise SystemExit("ECON_REVIEW_ARCHIVE_SHA256 must be exactly 64 hexadecimal digits")
actual_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
if actual_sha != expected_sha:
    raise SystemExit(f"archive SHA-256 mismatch: expected {expected_sha}, got {actual_sha}")

WINDOWS_RESERVED_BASENAMES = frozenset(
    {"con", "prn", "aux", "nul", "clock$"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)

def safe_name(raw):
    if (
        not raw
        or "\\" in raw
        or ":" in raw
        or raw.startswith("/")
        or raw != unicodedata.normalize("NFC", raw)
        or any(ord(character) < 32 or ord(character) == 127 for character in raw)
    ):
        raise SystemExit(f"unsafe archive path: {raw!r}")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(
            part in {"", "."}
            or part != part.strip()
            or part.endswith(".")
            or part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_BASENAMES
            for part in path.parts
        )
    ):
        raise SystemExit(f"unsafe archive path: {raw!r}")
    if raw != path.as_posix():
        raise SystemExit(f"non-canonical archive path: {raw!r}")
    return path

with zipfile.ZipFile(archive_path) as archive:
    infos = archive.infolist()
    if not infos:
        raise SystemExit("release archive is empty")
    if len(infos) > 2000:
        raise SystemExit("release archive contains too many entries")
    if sum(info.file_size for info in infos) > 200 * 1024 * 1024:
        raise SystemExit("release archive exceeds the 200 MiB uncompressed safety limit")
    names = []
    folded = set()
    for info in infos:
        path = safe_name(info.filename)
        if info.flag_bits & 0x1:
            raise SystemExit(f"encrypted archive entry is not allowed: {info.filename}")
        if info.file_size > 20 * 1024 * 1024:
            raise SystemExit(f"archive entry exceeds the 20 MiB safety limit: {info.filename}")
        if info.is_dir():
            raise SystemExit(f"explicit directory entries are not allowed: {info.filename}")
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if kind not in {0, stat.S_IFREG}:
            raise SystemExit(f"non-regular archive entry is not allowed: {info.filename}")
        folded_name = unicodedata.normalize("NFC", path.as_posix()).casefold()
        if folded_name in folded:
            raise SystemExit(f"duplicate or case-colliding archive entry: {info.filename}")
        folded.add(folded_name)
        names.append(path)
    roots = {path.parts[0] for path in names}
    if roots != {"econ-paper-review-skill"}:
        raise SystemExit("archive must contain exactly one econ-paper-review-skill root")
    manifest_name = "econ-paper-review-skill/RELEASE-MANIFEST.json"
    if manifest_name not in {path.as_posix() for path in names}:
        raise SystemExit("archive is missing RELEASE-MANIFEST.json")
    def reject_duplicate_pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value
    def reject_json_constant(value):
        raise ValueError(f"non-standard JSON numeric constant: {value}")
    try:
        manifest = json.loads(
            archive.read(manifest_name),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"invalid release manifest: {exc}")
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"archive_format_version", "file_contract_sha256", "files", "package"}
        or manifest.get("archive_format_version") != 1
    ):
        raise SystemExit("unsupported release manifest format")
    if manifest.get("package") != "econ-paper-review-skill":
        raise SystemExit("release manifest has the wrong package name")
    contract_digest = manifest.get("file_contract_sha256")
    if not isinstance(contract_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", contract_digest):
        raise SystemExit("release manifest has an invalid file-contract hash")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise SystemExit("release manifest files must be a non-empty array")
    expected_names = {manifest_name}
    records = {}
    previous = ""
    for record in files:
        if not isinstance(record, dict) or set(record) != {"mode", "path", "sha256", "size"}:
            raise SystemExit("release manifest contains an invalid file record")
        relative = safe_name(record["path"] if isinstance(record.get("path"), str) else "")
        relative_name = relative.as_posix()
        if relative_name <= previous:
            raise SystemExit("release manifest file records must be sorted and unique")
        previous = relative_name
        digest = record.get("sha256")
        size = record.get("size")
        mode = record.get("mode")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SystemExit(f"invalid file hash in release manifest: {relative_name}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise SystemExit(f"invalid file size in release manifest: {relative_name}")
        if mode not in {0o644, 0o755}:
            raise SystemExit(f"invalid file mode in release manifest: {relative_name}")
        full_name = f"econ-paper-review-skill/{relative_name}"
        expected_names.add(full_name)
        records[full_name] = record
    actual_names = {path.as_posix() for path in names}
    if actual_names != expected_names:
        unexpected = sorted(actual_names - expected_names)
        missing = sorted(expected_names - actual_names)
        raise SystemExit(f"archive entries differ from manifest; unexpected={unexpected}, missing={missing}")
    if "econ-paper-review-skill/econ-review/SKILL.md" not in records:
        raise SystemExit("release manifest does not contain econ-review/SKILL.md")
    contract_name = "econ-paper-review-skill/scripts/public-release-files.json"
    if contract_name not in records or records[contract_name]["sha256"] != contract_digest:
        raise SystemExit("release manifest file-contract hash does not match its file record")
    destination.mkdir(parents=True, exist_ok=False)
    for full_name, record in records.items():
        data = archive.read(full_name)
        if len(data) != record["size"]:
            raise SystemExit(f"file size mismatch: {full_name}")
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise SystemExit(f"file hash mismatch: {full_name}")
        relative = PurePosixPath(record["path"])
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        target.chmod(record["mode"])
PY
}

find_source() {
  if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/econ-review/SKILL.md" ]; then
    validate_skill_tree "$SCRIPT_DIR/econ-review" || fail "local source validation failed"
    SOURCE_DIR="$SCRIPT_DIR/econ-review"
    return
  fi

  require_command curl
  archive_url="${ECON_REVIEW_ARCHIVE_URL:-}"
  archive_sha="${ECON_REVIEW_ARCHIVE_SHA256:-}"
  [ -n "$archive_url" ] && [ -n "$archive_sha" ] || fail "remote installation is disabled; set both ECON_REVIEW_ARCHIVE_URL and ECON_REVIEW_ARCHIVE_SHA256"
  case "$archive_url" in
    https://*) curl_protocols=(--proto '=https' --proto-redir '=https') ;;
    file://*)
      [ "${ECON_REVIEW_ALLOW_INSECURE_TEST_URL:-0}" = "1" ] || fail "remote archive URL must use HTTPS"
      curl_protocols=(--proto '=file' --proto-redir '=file')
      ;;
    *) fail "remote archive URL must use HTTPS" ;;
  esac
  TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/econ-review.XXXXXX")"
  curl -fL --retry 2 --connect-timeout 15 --max-time 900 --max-filesize 104857600 \
    "${curl_protocols[@]}" "$archive_url" -o "$TEMP_DIR/release.zip" \
    || fail "failed to download release archive"
  verify_and_extract_archive "$TEMP_DIR/release.zip" "$archive_sha" "$TEMP_DIR/source" || fail "release archive verification failed"
  validate_skill_tree "$TEMP_DIR/source/econ-review" || fail "extracted skill validation failed"
  SOURCE_DIR="$TEMP_DIR/source/econ-review"
}

install_one() {
  source_dir="$1"
  destination="$2"
  label="$3"

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "Would install $label: $destination"
    return
  fi
  [ ! -L "$destination" ] || fail "refusing to replace symbolic-link destination: $destination"
  parent="$(dirname "$destination")"
  mkdir -p "$parent"
  ACTIVE_STAGE="$(mktemp -d "$parent/.econ-review.stage.XXXXXX")"
  python3 - "$source_dir" "$ACTIVE_STAGE" <<'PY'
import shutil
import sys
from pathlib import Path

source, stage = map(Path, sys.argv[1:])
shutil.copytree(
    source,
    stage,
    dirs_exist_ok=True,
    symlinks=True,
    ignore=shutil.ignore_patterns(
        ".DS_Store", "__pycache__", "*.pyc", "*.pyo",
        ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ),
)
PY
  validate_skill_tree "$ACTIVE_STAGE" || fail "staged package validation failed"

  ACTIVE_BACKUP=""
  if [ -e "$destination" ]; then
    ACTIVE_BACKUP="$(mktemp -d "$parent/.econ-review.backup.XXXXXX")"
    rmdir "$ACTIVE_BACKUP"
    mv -- "$destination" "$ACTIVE_BACKUP"
  fi
  ACTIVE_DESTINATION="$destination"
  if ! mv -- "$ACTIVE_STAGE" "$destination"; then
    rm -rf -- "$destination"
    if [ -n "$ACTIVE_BACKUP" ] && [ -e "$ACTIVE_BACKUP" ]; then
      mv -- "$ACTIVE_BACKUP" "$destination" || true
    fi
    fail "failed to install $label; previous installation restored"
  fi
  ACTIVE_STAGE=""
  if [ -n "$ACTIVE_BACKUP" ]; then
    rm -rf -- "$ACTIVE_BACKUP"
  fi
  ACTIVE_BACKUP=""
  ACTIVE_DESTINATION=""
  echo "Installed $label: $destination"
}

require_command python3
require_command mktemp
require_command mv
python3 - <<'PY' || fail "Python 3.10 or newer is required"
import sys

if sys.version_info < (3, 10):
    raise SystemExit(1)
PY

SOURCE_DIR=""
find_source

if [ "$MODE" = "global" ]; then
  if [ "$PLATFORM" = "all" ] || [ "$PLATFORM" = "claude" ]; then
    install_one "$SOURCE_DIR" "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/econ-review" "Claude Code (global)"
  fi
  if [ "$PLATFORM" = "all" ] || [ "$PLATFORM" = "codex" ]; then
    install_one "$SOURCE_DIR" "${CODEX_HOME:-$HOME/.codex}/skills/econ-review" "Codex (global)"
  fi
else
  TARGET="${TARGET:-.}"
  [ -d "$TARGET" ] || fail "local target directory does not exist: $TARGET"
  TARGET="$(CDPATH= cd -- "$TARGET" && pwd)" || fail "cannot resolve local target directory: $TARGET"
  if [ "$PLATFORM" = "all" ] || [ "$PLATFORM" = "claude" ]; then
    install_one "$SOURCE_DIR" "$TARGET/.claude/skills/econ-review" "Claude Code (project)"
  fi
  if [ "$PLATFORM" = "all" ] || [ "$PLATFORM" = "codex" ]; then
    install_one "$SOURCE_DIR" "$TARGET/.agents/skills/econ-review" "Codex (project)"
  fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "econ-review dry run complete; no files changed."
else
  echo "econ-review installation complete."
fi
echo "Restart or reload Codex and Claude Code sessions so they discover the installed skill."
