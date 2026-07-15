# Install econ-review

## Recommended path

Install the native plugin from the shared OpenEconAI catalog, then run its
bundled setup workflow once. The plugin contains the complete first-party review
package, setup tool, and verified Review Desk archive. The explicit first-use
setup creates a shared user-owned Python runtime, checks manuscript-PDF support,
and installs Review Desk without creating a duplicate skill copy.

Do not combine a native plugin and a direct skill copy for the same client. The
alternative source installer remains available for users who cannot use a
marketplace.

## One-paste first-use setup prompt

After installing the plugin, paste this into Codex or Claude Code. Review Desk
is a prebuilt static application; users do not need Node.js or npm.

```text
Use econ-review-setup to finish setup on this machine. Detect macOS, Linux, or
Windows; run the bundled support-only dry run for global setup with Review Desk,
summarize every planned write and download, then apply the same operation. Do not
copy econ-review into an agent skill directory: the plugin already supplies it.
Do not install Poppler, Tesseract, TeX, Pandoc, Node.js, cloud backends, system
packages, or anything requiring administrator access. Report the verified runtime,
core/PDF readiness, the Review Desk command and URL, and anything still missing.
```

The setup may download the version-constrained core Python packages into an
econ-review-owned virtual environment only after the dry run and explicit setup
request. It never uploads a manuscript. Do not expose a token or package-index
credential in chat, a URL, or a shell command.

## Native marketplace install

OpenEconAI publishes one shared catalog, `openeconai`, for both clients. The
catalog lives at [`OpenEconAI/plugins`](https://github.com/OpenEconAI/plugins);
this source repository does not publish a second marketplace. Adding the
catalog makes its plugins browsable, while installing `econ-review` is a
separate step.

### Migrate from the former marketplace

If you previously installed `econ-review@econ-paper-review`, remove that
plugin and its old catalog **before** adding the OpenEconAI catalog. This
one-time migration prevents duplicate skill entries. A command that reports
the old plugin or catalog is already absent can be ignored.

Claude Code:

```bash
claude plugin uninstall econ-review@econ-paper-review
claude plugin marketplace remove econ-paper-review
claude plugin marketplace add OpenEconAI/plugins
claude plugin install econ-review@openeconai
```

Codex:

```bash
codex plugin remove econ-review@econ-paper-review
codex plugin marketplace remove econ-paper-review
codex plugin marketplace add OpenEconAI/plugins
codex plugin add econ-review@openeconai
```

If you also made a direct skill copy with this repository's installer, remove
that copy before using the native plugin, or keep the direct copy and skip the
native installation. Do not keep both installation paths for the same client.

### Fresh native install

Claude Code, from the `/plugin` interface:

```text
/plugin marketplace add OpenEconAI/plugins
/plugin install econ-review@openeconai
```

The equivalent Claude Code CLI commands are:

```bash
claude plugin marketplace add OpenEconAI/plugins
claude plugin install econ-review@openeconai
```

Codex:

```bash
codex plugin marketplace add OpenEconAI/plugins
codex plugin add econ-review@openeconai
```

These commands work on macOS, Linux, and native Windows terminals. Reload or
restart the client after installation so it discovers both `econ-review` and
`econ-review-setup`.

The plugin package includes both skills, all review scripts and contracts, the
support installer, dependency manifests, and the verified Review Desk archive.
Plugin installation itself only places that package in the client's versioned
cache; it does not execute downloads or machine setup. Run the first-use setup
prompt above to create the private runtime and install Review Desk.

The setup tool records the verified managed interpreter in mutable product data
outside the versioned plugin cache, so both clients can reuse it and plugin
updates remain read-only. If Poppler is absent, setup exits with a distinct
partial-readiness result: the runtime and Review Desk remain installed, but PDF
ingestion is not described as ready. Installing Poppler or any other external
tool is always a separate user decision.

### Update a plugin install

Claude Code:

```bash
claude plugin marketplace update openeconai
claude plugin update econ-review@openeconai
```

Codex:

```bash
codex plugin marketplace upgrade openeconai
codex plugin add econ-review@openeconai
```

The update commands refresh the catalog and then apply the current plugin
version. Restart or reload the client after an update, then ask
`econ-review-setup` to check readiness. It reuses a compatible runtime and
offers a dry-run refresh when the plugin's core dependency contract changed.
The shared catalog pins
each published plugin version to its verified source release, so users do not
need to add this source repository as another marketplace.

### Remove a plugin install

Removal is separate from updating. Run these only when you intend to uninstall
the skill:

Removing the plugin intentionally leaves its user-owned Python runtime, runtime
descriptor, and Review Desk in place. This avoids deleting data on an ordinary
plugin update or reinstall. To remove that support state too, preview the exact
scope **before** uninstalling the plugin:

```text
PYTHON PLUGIN_ROOT/scripts/setup_econ_review.py --cleanup-support --global --dry-run
```

After checking every path, remove only those default support files with:

```text
PYTHON PLUGIN_ROOT/scripts/setup_econ_review.py --cleanup-support --global --confirm-cleanup
```

Use `--local PROJECT_DIRECTORY` instead of `--global` for one project's hashed
support state. Cleanup never removes the plugin or a direct skill copy. Custom
`--runtime-dir`, `--review-desk-dir`, or `ECON_REVIEW_DESK_HOME` locations are
not inferred or deleted automatically.

Claude Code:

```bash
claude plugin uninstall econ-review@openeconai
```

Codex:

```bash
codex plugin remove econ-review@openeconai
```

Keep the `openeconai` catalog if you use or want to browse other OpenEconAI
plugins. Remove it only when you no longer want any plugin from that catalog:

```bash
claude plugin marketplace remove openeconai
codex plugin marketplace remove openeconai
```

## Alternative source installation

Use this path only when a native marketplace is unavailable. Python 3.10 or
newer with working `venv` and pip bootstrapping support is required. The managed setup creates or reuses one
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

Direct project setup copies the skill to `.claude/skills/econ-review` and/or
`.agents/skills/econ-review`. Its mutable runtime, descriptor, and Review Desk
stay outside the manuscript under the platform product-data root at
`econ-review/projects/<project-hash>/`. Global skill paths honor
`CLAUDE_CONFIG_DIR` and `CODEX_HOME`. Product-data roots are:

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

## Source-installation variants

Omit `--with-review-desk` to skip Review Desk. The original
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
