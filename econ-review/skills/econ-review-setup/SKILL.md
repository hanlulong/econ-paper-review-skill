---
name: econ-review-setup
description: Prepare, verify, repair, or refresh the user-owned Python runtime and local Review Desk used by an installed econ-review plugin. Use when the user installs econ-review from a marketplace, asks to finish setup, reports missing Python packages or Poppler, needs the Review Desk launcher, or wants to check installation readiness without creating duplicate Claude Code or Codex skill copies.
---

# Set up Econ Review

Resolve `PLUGIN_ROOT` as the parent directory of the `skills/` directory that
contains this setup skill. Use the standard-library setup tool at
`PLUGIN_ROOT/scripts/setup_econ_review.py`. Do not copy the skill into an agent
home: marketplace installation already supplies it.

1. Find a working Python 3.10 or newer command with `venv` and pip bootstrapping
   support already on the machine. Do not install Python, a package manager, a
   missing `python3-venv` component, or system software on your own.
2. Choose global support setup unless the user explicitly requests one-project
   state. For global setup, run this exact operation first with `--dry-run`:

   ```text
   PYTHON PLUGIN_ROOT/scripts/setup_econ_review.py --support-only --global --with-review-desk --dry-run
   ```

   For project state, replace `--global` with `--local PROJECT_DIRECTORY`.
3. Summarize the dry run in plain language. State that applying it creates or
   refreshes a private econ-review virtual environment, may download the
   version-constrained Python packages declared by the plugin, and installs the
   already bundled, manifest-verified Review Desk. It does not install a second
   skill copy, use administrator access, or upload a manuscript.
4. Apply the same command without `--dry-run` only when the user has explicitly
   asked to install, finish, repair, or refresh setup, or confirms after seeing
   the plan. Do not treat a request merely to review a paper as authorization
   to download packages or change user-level state.
5. Preserve the setup tool's exit distinction. Exit `0` means the core runtime,
   PDF ingestion, and requested Review Desk passed. Exit `2` means the managed
   runtime and Review Desk may be ready but PDF ingestion is still incomplete,
   normally because Poppler is absent. Do not call that a failed plugin install.
6. Never install Poppler, Tesseract, TeX, Pandoc, Node.js, an optional PDF
   backend, or any administrator-managed package automatically. If Poppler is
   missing, report the setup tool's platform-specific user-level options and
   ask separately before running a package-manager command.
7. Verify runtime discovery without changing files:

   ```text
   PYTHON PLUGIN_ROOT/scripts/setup_econ_review.py --runtime-path
   ```

   After project-only setup, pass the same project scope instead:

   ```text
   PYTHON PLUGIN_ROOT/scripts/setup_econ_review.py --runtime-path --local PROJECT_DIRECTORY
   ```

   This read-only resolver verifies and prints only the managed interpreter.
   Preserve the setup command's earlier PDF-doctor result and Review Desk launch
   command or URL when reporting overall readiness. Never expose package-index
   credentials or environment-secret values in the response.

8. When the user asks to uninstall support data, show
   `--cleanup-support --global --dry-run` (or the matching `--local` scope)
   first. Apply the same scope with `--confirm-cleanup` only after explicit
   confirmation. Explain that plugin removal alone retains the runtime,
   descriptor, and Review Desk, while cleanup leaves the plugin and any direct
   skill copy unchanged.
