# Install econ-review

## Choose an installation

The complete setup is recommended for a new machine: it installs the skill for
both agents, prepares a managed Python runtime, checks PDF support, and installs
Review Desk. The native marketplace path installs only the skill and is useful
when those supporting components are already available or when you want the
client's built-in plugin update flow.

Choose one skill-installation path per client. Installing both the native
plugin and a direct skill copy can make the same skill appear twice.

## One-paste agent prompt

Paste this prompt into Codex or Claude Code. It installs the skill for both
agents, prepares one managed Python runtime, checks manuscript-PDF support,
reports professional report-renderer readiness separately, and installs the
local Review Desk. Review Desk is a prebuilt static application; users do not
need Node.js or npm.

```text
Install econ-review from https://github.com/hanlulong/econ-paper-review-skill for
Claude Code and Codex by following this file. Clone the public repository over HTTPS;
never ask me to paste a token, and preserve uncommitted work. Detect macOS, Linux, or
Windows; run the dry run, then the managed global setup for both agents with
--with-review-desk. Do not install system packages, TeX, Pandoc, cloud backends, or
anything requiring administrator access. Report both skill paths, PDF/report readiness,
the Review Desk command and URL, anything still missing, and remind me to reload my
sessions.
```

The repository is public and its HTTPS checkout does not require GitHub
credentials. Do not expose a token in chat, a URL, or a shell command.

## Native marketplace install (skill only)

The repository exposes one marketplace named `econ-paper-review` to both
clients. Adding the marketplace makes the plugin browsable; installing the
plugin is a separate second step.

Claude Code, from the `/plugin` interface:

```text
/plugin marketplace add hanlulong/econ-paper-review-skill
/plugin install econ-review@econ-paper-review
```

The equivalent Claude Code CLI commands are:

```bash
claude plugin marketplace add hanlulong/econ-paper-review-skill
claude plugin install econ-review@econ-paper-review
```

Codex:

```bash
codex plugin marketplace add hanlulong/econ-paper-review-skill
codex plugin add econ-review@econ-paper-review
```

These commands work on macOS, Linux, and native Windows terminals. Reload or
restart the client after installation so it discovers the skill.

A plugin install contains the portable `econ-review` skill, its scripts,
contracts, references, and dependency manifests. It does not create the
managed Python environment, install Poppler or optional PDF backends, or
install Review Desk. If first use reports a missing Python package or PDF tool,
use the complete setup below rather than treating the plugin install as a
readiness check.

### Update a plugin install

Claude Code:

```bash
claude plugin marketplace update econ-paper-review
claude plugin update econ-review@econ-paper-review
```

Codex:

```bash
codex plugin marketplace upgrade econ-paper-review
codex plugin add econ-review@econ-paper-review
```

The update commands refresh the catalog and then apply the current plugin
version. Restart or reload the client after an update.

### Install a pinned release

Published release tags use `econ-review--v<version>`. Pinning the marketplace
to one of those versioned tags also pins the relative `./econ-review` plugin
source to the same tagged repository snapshot. For example, after the `0.1.0`
release tag has been published:

Claude Code:

```bash
claude plugin marketplace add hanlulong/econ-paper-review-skill@econ-review--v0.1.0
claude plugin install econ-review@econ-paper-review
```

Codex:

```bash
codex plugin marketplace add hanlulong/econ-paper-review-skill --ref econ-review--v0.1.0
codex plugin add econ-review@econ-paper-review
```

Both clients can pin the marketplace to a branch or tag. Claude Code does not
accept a raw commit SHA for a marketplace source, so use a versioned release
tag when reproducibility matters. This repository deliberately keeps the
plugin source inside the marketplace repository, avoiding a second independently
moving source to pin.

### Remove a plugin install

Removal is separate from updating. Run these only when you intend to uninstall
the skill:

Claude Code:

```bash
claude plugin uninstall econ-review@econ-paper-review
claude plugin marketplace remove econ-paper-review
```

Codex:

```bash
codex plugin remove econ-review@econ-paper-review
codex plugin marketplace remove econ-paper-review
```

Removing the marketplace is optional; do it only when you no longer want this
repository listed.

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
python scripts\install_econ_review.py --dry-run --global --all --with-review-desk
python scripts\install_econ_review.py --global --all --with-review-desk
```

Use the working Python 3.10+ command already available on the machine; the
optional Windows `py` launcher is not required. Native Windows does not require
Bash.

For one project instead of the whole user account:

```text
python3 scripts/install_econ_review.py --local PATH_TO_PROJECT --all --with-review-desk
```

Project setup uses `.claude/skills/econ-review`,
`.agents/skills/econ-review`, `.econ-review/runtime`, and
`.econ-review/review-desk`. Global skill paths honor `CLAUDE_CONFIG_DIR` and
`CODEX_HOME`. Global runtime and viewer paths use:

- macOS: `~/Library/Application Support/econ-review/`
- Linux: `${XDG_DATA_HOME:-$HOME/.local/share}/econ-review/`
- Windows: `%USERPROFILE%\.econ-review\`

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

On Windows managed installations, `review-desk.cmd` is generated beside the
stable Python launcher and is bound to the resolved managed-runtime interpreter.
It forwards options such as `--check` and `--port`, so Review Desk never depends
on whichever `python` happens to be first on the user's later `PATH`.
The launcher reuses an already-running, integrity-matched Review Desk on the
same port. If another program owns the port, it reports the conflict (and the
PID when the operating system exposes it) instead of presenting a generic bind
failure; choose another loopback port with `--port PORT`.

The setup is idempotent: it skips unchanged skill copies, reuses a healthy
runtime, and keeps an already verified Review Desk version. Use
`--refresh-runtime` only for a clean Python rebuild. A failed runtime rebuild
restores the prior runtime. A tampered immutable viewer version fails closed
instead of being silently trusted.

### Update a managed or copy-only setup

From the original public checkout, fast-forward it and repeat the same dry run
and setup command:

```bash
git pull --ff-only
python3 scripts/install_econ_review.py --dry-run --global --all --with-review-desk
python3 scripts/install_econ_review.py --global --all --with-review-desk
```

On native Windows PowerShell, use `python` and backslash script paths as in the
initial setup. If the original checkout was not retained, make a fresh public
HTTPS checkout in a new directory and run the same commands there. Rerunning
the installer updates changed skill files atomically, reuses a compatible
runtime, and keeps an already verified Review Desk version.

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
compatible and working LuaLaTeX or Tectonic executable is already available,
econ-review uses it for the report. Auto-selection first compiles a minimal
health document, so an installed but unusable TeX command is skipped and the
maintained ReportLab renderer remains available. Once a healthy LaTeX renderer
is selected, a manuscript-report source or compilation error fails visibly and
leaves the prior verified PDF intact; it is not hidden by a ReportLab retry.
Use `finalize_review.py --renderer reportlab` when a deterministic explicit
override is needed. The setup does not install or alter a system TeX
distribution. Pandoc is neither bundled nor required.

After skill installation, restart or reload Codex and Claude Code so their
skill discovery refreshes.
