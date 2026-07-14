# Install econ-review

## One-paste agent prompt

Paste this prompt into Codex or Claude Code. It installs the skill for both
agents, prepares one managed Python runtime, checks manuscript-PDF support,
reports professional report-renderer readiness separately, and installs the
local Review Desk. Review Desk is a prebuilt static application; users do not
need Node.js or npm.

```text
Install econ-review from https://github.com/hanlulong/econ-paper-review-skill for
Claude Code and Codex by following this file. Use my existing GitHub login; never ask
me to paste a token, and preserve uncommitted work. Detect macOS, Linux, or Windows;
run the dry run, then the managed global setup for both agents with --with-review-desk.
Do not install system packages, TeX, Pandoc, cloud backends, or anything requiring
administrator access. Report both skill paths, PDF/report readiness, the Review Desk
command and URL, anything still missing, and remind me to reload my sessions.
```

The prompt leaves credentials with the user's existing GitHub client. If a
private-repository checkout is not authorized, configure `gh auth login` or the
normal Git credential helper; do not expose a token in chat, a URL, or a shell
command.

## Recommended direct setup

Python 3.10 or newer is required. The managed setup creates or reuses one
virtual environment, installs the version-constrained core requirements, copies the skill to
both agent locations, runs the PDF-ingestion doctor, and installs Review Desk.
It does not install administrator-managed packages, TeX, or Pandoc.

macOS or Linux:

```bash
python3 scripts/install_econ_review.py --dry-run --global --all --with-review-desk
python3 scripts/install_econ_review.py --global --all --with-review-desk
```

Native Windows PowerShell:

```powershell
py -3 scripts\install_econ_review.py --dry-run --global --all --with-review-desk
py -3 scripts\install_econ_review.py --global --all --with-review-desk
```

If the Windows `py` launcher is unavailable, use the machine's Python 3.10+
command. Native Windows does not require Bash.

For one project instead of the whole user account:

```text
python3 scripts/install_econ_review.py --local PATH_TO_PROJECT --all --with-review-desk
```

Project setup uses `.claude/skills/econ-review`,
`.agents/skills/econ-review`, `.econ-review/runtime`, and
`.econ-review/review-desk`. Global skill paths honor `CLAUDE_CONFIG_DIR` and
`CODEX_HOME`. Global runtime and viewer paths use:

- macOS: `~/Library/Application Support/econ-review/`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/econ-review/`
- Windows: `%LOCALAPPDATA%\econ-review\`

`--runtime-dir`, `--review-desk-dir`, and `ECON_REVIEW_DESK_HOME` provide
explicit overrides. Environment overrides must be absolute paths.

The installer prints Review Desk's stable launcher and URL:
`http://127.0.0.1:48127/`. The application version lives under
`review-desk/versions/<manifest-digest>` and is verified before installation
and again at launch. The stable launcher selects that immutable version. It
serves only release-manifest files on loopback, accepts only `GET` and `HEAD`,
ships no manuscript or review bundle, and uses the browser's local file picker.
If a browser cannot open automatically, the launcher prints the URL to open
manually. No manuscript is uploaded.

The setup is idempotent: it skips unchanged skill copies, reuses a healthy
runtime, and keeps an already verified Review Desk version. Use
`--refresh-runtime` only for a clean Python rebuild. A failed runtime rebuild
restores the prior runtime. A tampered immutable viewer version fails closed
instead of being silently trusted.

## Skill-only and manual modes

Omit `--with-review-desk` to keep the managed setup skill-only. The original
copy-only installer also remains available and does not modify Python, install
Review Desk, or install system software:

```bash
./install.sh --global --all
```

The equivalent cross-platform command is:

```text
python3 scripts/install_econ_review.py --copy-only --global --all
```

Add `--check` to inspect the active Python environment and Poppler after a
copy-only install. Both installers support `--dry-run`. Neither silently
installs Poppler, Tesseract, Node.js, optional PDF backends, or administrator-
managed packages. Maintainers who want to modify Review Desk can still use the
Node-based development workflow in [`review-viewer/README.md`](../review-viewer/README.md).

## PDF ingestion and report rendering are separate

Review Desk readiness does not imply manuscript-PDF ingestion readiness. If
Poppler is unavailable, the installer reports the missing commands and exits
without claiming that PDF ingestion is ready. It gives non-admin Homebrew or
Conda/micromamba guidance appropriate to the operating system; the user decides
whether to install it.
Review Desk can still be installed, and the installer reports both states
separately.

Professional report rendering is a third, independent capability. When a
compatible LuaLaTeX or Tectonic executable is already available, econ-review
uses it for the report. When neither is available, the maintained ReportLab
renderer remains available. A selected LaTeX renderer that encounters a source
or compilation error fails visibly and leaves the prior verified PDF intact; it
never silently falls back to ReportLab. The setup does not install or alter a
system TeX distribution. Pandoc is neither bundled nor required.

After skill installation, restart or reload Codex and Claude Code so their
skill discovery refreshes.
