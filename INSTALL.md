# Install Econ Review

## Agent installation contract

When the user sends you here from the README prompt, complete this entire
contract in the current Codex or Claude Code client. The request authorizes the
documented user-scoped plugin changes, the private econ-review runtime and its
declared core Python packages, the bundled Review Desk, exact legacy cleanup,
and the limited Poppler handling below. Do not ask the user to copy or run
commands, and do not ask them to repeat this authorization.

1. Detect the current client and operating system. Operate only on the client
   running this session; do not install into both merely because both CLIs are
   present. If the client is genuinely indeterminate, report that blocker rather
   than guessing.
2. Inspect the client's marketplace and plugin state, using JSON output where
   available. Remove the exact legacy `econ-review@econ-paper-review` plugin and
   `econ-paper-review` catalog if present. Check only the client's standard
   direct-skill location for a duplicate `econ-review` copy. Remove an exact,
   unmodified generated copy; move a modified copy to a timestamped backup
   outside active skill directories and report it. Never delete an unrelated
   file, parent directory, or unrecognized installation.
3. Ensure marketplace `openeconai` points to
   `https://github.com/OpenEconAI/plugins`. Add `OpenEconAI/plugins` if absent;
   update or upgrade it when the source matches. If that name points elsewhere,
   stop instead of overwriting an unrelated marketplace.
4. Install or update `econ-review@openeconai` at user scope. For Codex, use
   `codex plugin add econ-review@openeconai --json` and take `installedPath`
   from the result. For Claude Code, install or update the plugin and take the
   exact ID's `installPath` from `claude plugin list --json`. Do not guess a
   cache path or search unrelated directories.
5. Before executing bundled code, verify that the resolved root has a matching
   client manifest for `econ-review`, `scripts/setup_econ_review.py`,
   `requirements-core.txt`, and `assets/review-desk.zip`. Stop if any check fails.
6. Find an existing Python 3.10+ interpreter with working `venv` and pip
   bootstrapping support. Run the setup dry run, inspect every planned write and
   download, and apply the same setup without another confirmation. The setup
   tool performs its own standard-library package validation before changing
   support state:

   ```text
   PYTHON PLUGIN_ROOT/scripts/setup_econ_review.py --support-only --global --with-review-desk --dry-run
   PYTHON PLUGIN_ROOT/scripts/setup_econ_review.py --support-only --global --with-review-desk
   ```

   Use native path and Python syntax for the detected operating system. These
   commands may create or refresh econ-review's private user-owned environment
   and install only the plugin's declared core requirements. They must not copy
   the skill into an agent skill directory.
7. If the PDF doctor reports missing Poppler commands, install Poppler only
   through an already configured, trusted package manager and without `sudo`.
   Allow any native package-manager approval to surface. Do not install a new
   package manager or any other system or optional package. If Poppler requires
   administrator access or is blocked by policy, keep the completed runtime and
   Review Desk and report PDF ingestion as the one remaining blocker.
8. Verify one active `openeconai` marketplace, one active
   `econ-review@openeconai` plugin, no active legacy or direct duplicate, and
   the installed version. Run `setup_econ_review.py --runtime-path`, then use
   that managed interpreter to run
   `PLUGIN_ROOT/scripts/validate_skill_package.py PLUGIN_ROOT`. Preserve the PDF
   doctor's true result and run the Review Desk launcher's printed integrity
   check. Report the plugin version, verified runtime, PDF readiness, Review
   Desk command and URL, any legacy backup, and any genuine blocker. If the
   client needs a reload or new session before skill discovery, say so once at
   the end.

Never upload a manuscript, expose credentials, bypass client security, alter a
system Python environment, or silently elevate privileges. Never paste a token
or package-index credential into chat, a URL, or a shell command. The same
contract applies to future updates: refresh the catalog and plugin, then rerun
setup from the new verified plugin root so dependency or Review Desk changes are
applied transactionally while compatible support state is reused.

## Direct plugin installation

OpenEconAI publishes the sole native catalog, `openeconai`, at
[`OpenEconAI/plugins`](https://github.com/OpenEconAI/plugins). Use this section
when installing through a client's plugin interface instead of the recommended
agent prompt. Do not combine a native plugin and a direct skill copy for the
same client.

Claude Code:

```text
/plugin marketplace add OpenEconAI/plugins
/plugin install econ-review@openeconai
```

Codex:

```bash
codex plugin marketplace add OpenEconAI/plugins
codex plugin add econ-review@openeconai
```

Neither client exposes a portable trusted post-install event, so installing the
plugin cannot immediately run machine setup. After installation, send one
message to the agent:

```text
Run econ-review-setup now and finish its user-level setup with Review Desk.
```

The setup skill runs the bundled support-only dry run, inspects it, and applies
the same operation under that explicit request. It may download the declared
core Python packages into econ-review's private environment. It does not copy
the skill, upload a manuscript, or silently install system software.

Reload or restart the client after installation if it does not yet discover
`econ-review` and `econ-review-setup` in the current session.

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

The recommended README prompt performs these operations and setup verification
for the user. When running the commands directly, restart or reload the client
afterward and send the one-line setup message above. Setup reuses a compatible
runtime and refreshes it transactionally when the plugin's dependency contract
changes. The catalog pins every published version to a verified source release;
this repository must not be added as a second marketplace.

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
./scripts/install.sh --global --all
```

The equivalent cross-platform command is:

```text
python3 scripts/install_econ_review.py --copy-only --global --all
```

Add `--check` to inspect the active Python environment and Poppler after a
copy-only install. Both installers support `--dry-run`. Neither silently
installs Poppler, Tesseract, Node.js, optional PDF backends, or administrator-
managed packages. Maintainers who want to modify Review Desk can still use the
Node-based development workflow in [`review-viewer/README.md`](review-viewer/README.md).

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
