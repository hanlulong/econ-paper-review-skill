# Install or update Econ Review

Standalone skill installation is the default. It preserves the short
`/econ-review` command in Claude Code and `$econ-review` mention in Codex, while
still allowing the skill to activate automatically from an ordinary paper-review
request. Native plugin installation remains available as an optional alternative.

Use one installation method per client. Claude Code and Codex need separate
standalone copies when both clients are used, but those copies must come from the
same release. Installing or updating one client must never change the other
client's active skill path or plugin registration. Compatible managed runtimes
and Review Desk builds are stored outside both clients under content-versioned
paths, so they can be reused without replacing support still needed by an older
installed release.

## Agent installation contract

When the user sends you here from the README prompt, complete this contract in
the current Codex or Claude Code client. The request authorizes a user-scoped
standalone install or update, migration of exact same-client duplicates after
verification, Econ Review's private runtime and declared core Python packages,
and the bundled Review Desk. Do not ask the user to copy or run commands.

1. Detect the current client and operating system. Operate only on the client
   running this session unless the user explicitly requested both clients. If
   the client is genuinely indeterminate, stop rather than guessing.
2. Use the current client's canonical user destination:
   - Claude Code: `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/econ-review`
   - Codex: `$HOME/.agents/skills/econ-review`

   A project-local installation is used only when the user explicitly requests
   one; its destination is `.claude/skills/econ-review` or
   `.agents/skills/econ-review` under that project. Before changing a project
   path, check version control. Never remove or move a tracked source copy.
3. Inventory only the selected client's active copies before changing state:
   its canonical standalone path, a same-client project copy, and the exact
   `econ-review@openeconai` native plugin. For Codex, also inspect the legacy
   `${CODEX_HOME:-$HOME/.codex}/skills/econ-review` direct-skill path. Inspect
   the former `econ-review@econ-paper-review` plugin only for the selected
   client. Do not inspect, remove, back up, or migrate the other client's copy.
4. Obtain one consistent public source snapshot over HTTPS. Prefer an existing
   clean checkout whose origin is exactly
   `https://github.com/hanlulong/econ-paper-review-skill`; otherwise use a
   temporary shallow clone. Do not request or expose a GitHub token. Verify that
   the snapshot contains `econ-review/SKILL.md`, both matching client manifests,
   `econ-review/scripts/setup_econ_review.py`,
   `econ-review/requirements-core.txt`, and
   `econ-review/assets/review-desk.zip` before executing bundled code.
5. Find an existing Python 3.10+ interpreter with working `venv` and pip
   bootstrapping support. Select `--claude` or `--codex` for the current client,
   show the managed setup's dry run, inspect every planned destination and
   download, and then apply the identical operation:

   ```text
   PYTHON scripts/install_econ_review.py --dry-run --global --CLIENT --with-review-desk
   PYTHON scripts/install_econ_review.py --global --CLIENT --with-review-desk
   ```

   Run these commands from the verified checkout and replace `--CLIENT` with
   exactly one client flag. Use native path syntax on Windows. The setup copies
   the complete skill atomically, preserves a modified prior copy, creates or
   reuses a private user-owned environment, installs only the version-constrained
   core requirements, and installs the manifest-verified Review Desk. It never
   uploads a manuscript or alters a system Python environment. Default support
   paths are keyed by the core-requirements hash and Review Desk bundle hash;
   an update with different support content is additive rather than destructive.
6. Preserve the setup tool's PDF-readiness distinction. Exit `0` means the core
   runtime, PDF ingestion, and Review Desk passed. Exit `2` normally means the
   runtime and Review Desk are ready but Poppler is absent. Install Poppler only
   through an already configured trusted package manager, without `sudo`, and
   only when the user's installation request authorizes completing PDF support.
   Never install a new package manager or any unrelated optional backend. If
   policy or administrator access blocks Poppler, retain the completed skill,
   runtime, and Review Desk and report PDF ingestion as the remaining blocker.
7. Verify the installed standalone tree before removing anything else:
   - `SKILL.md` has `name: econ-review`, the expected trigger description, and
     no automatic-invocation opt-out.
   - `agents/openai.yaml` does not disable implicit invocation.
   - The installed tree matches the verified source manifest.
   - `setup_econ_review.py --runtime-path` returns the verified managed Python.
   - That interpreter passes
     `INSTALLED_SKILL/scripts/validate_skill_package.py INSTALLED_SKILL`.
   - The Review Desk launcher's printed integrity check succeeds.
8. Only after step 7 passes, remove same-client duplicates. Remove the exact
   native plugin through that client's plugin manager and remove the former
   marketplace plugin if present. Treat an untracked same-client project copy
   and a legacy direct Codex copy the same way: delete it only when
   byte-identical to the verified standalone tree; otherwise move it to a
   timestamped backup and report the path. Leave every tracked project copy
   unchanged. Never delete a parent skills directory, follow a symlink or
   junction, or touch an unrelated plugin. If duplicate removal fails, keep the
   verified standalone copy and report the duplicate as the one incomplete
   item.
9. Confirm the selected client now has exactly one active Econ Review copy. A
   tracked project source copy may remain, but must be identified rather than
   silently changed. If both clients were explicitly requested, repeat the
   install and verification independently and confirm that the two standalone
   trees are byte-identical.
10. Finish with the client, installed source revision, verification result, PDF
    readiness, Review Desk command and URL, any backup, and any genuine blocker.
    If skill discovery needs a new session or reload, say so once. Do not give
    the user more installation commands.

Never upload a manuscript, expose credentials, bypass client security, follow
an untrusted link or junction, silently elevate privileges, or delete an
unrecognized installation. Never paste a token or package-index credential into
chat, a URL, or a shell command.

## Direct standalone installation

These commands are for users or agents operating from a checkout. The README's
one-paste prompt is the recommended route because it selects the current client,
runs the dry run, handles migration, and verifies the result.

### macOS or Linux

```bash
git clone https://github.com/hanlulong/econ-paper-review-skill.git
cd econ-paper-review-skill
python3 scripts/install_econ_review.py --dry-run --global --all --with-review-desk
python3 scripts/install_econ_review.py --global --all --with-review-desk
```

Use `--claude` or `--codex` instead of `--all` to install only one client.

### Native Windows PowerShell

```powershell
git clone https://github.com/hanlulong/econ-paper-review-skill.git
cd econ-paper-review-skill
python scripts\install_econ_review.py --dry-run --global --all --with-review-desk
python scripts\install_econ_review.py --global --all --with-review-desk
```

Use the machine's working Python 3.10+ command; the optional `py` launcher is not
required. Native Windows does not require Bash.

### Project-local installation

```text
python3 scripts/install_econ_review.py --local PATH_TO_PROJECT --claude --with-review-desk
python3 scripts/install_econ_review.py --local PATH_TO_PROJECT --codex --with-review-desk
```

Mutable runtime, descriptor, and Review Desk state stay outside the manuscript
under `econ-review/projects/<project-hash>/` in the platform product-data root:

- macOS: `~/Library/Application Support/econ-review/`
- Linux: `${XDG_DATA_HOME:-$HOME/.local/share}/econ-review/`
- Windows: `%USERPROFILE%\.econ-review\`

`--runtime-dir`, `--review-desk-dir`, and `ECON_REVIEW_DESK_HOME` provide
explicit absolute-path overrides.

### Update

Fast-forward the original checkout and repeat the same client-scoped dry run and
setup command:

```bash
git pull --ff-only
python3 scripts/install_econ_review.py --dry-run --global --codex --with-review-desk
python3 scripts/install_econ_review.py --global --codex --with-review-desk
```

Replace `--codex` with `--claude` when appropriate. Rerunning setup is
idempotent: unchanged copies are retained, compatible runtime state is reused,
and Review Desk is verified before activation.

### Copy-only variant

To copy the skill without changing Python or installing Review Desk:

```bash
./scripts/install.sh --global --all
```

The equivalent cross-platform command is:

```text
python3 scripts/install_econ_review.py --copy-only --global --all
```

Both support `--dry-run`. Add `--check` to inspect the current Python and
Poppler after a copy-only install.

## Optional native plugin installation

OpenEconAI publishes the native `openeconai` catalog at
[`OpenEconAI/plugins`](https://github.com/OpenEconAI/plugins). Native plugins
are optional; do not combine one with a standalone copy in the same client.
Because plugin skills are namespaced, explicit invocation is
`/econ-review:econ-review` in Claude Code and `$econ-review:econ-review` in
Codex. Natural-language activation still uses the skill description.

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

Plugin clients do not provide a portable trusted post-install action. After a
direct plugin install, ask the agent:

```text
Run econ-review-setup now and finish its user-level setup with Review Desk.
```

The setup skill prepares support state without creating a standalone copy.
Reload or restart the client if it does not discover the installed plugin in the
current session.

### Update a native plugin

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

### Remove a native plugin

```bash
claude plugin uninstall econ-review@openeconai
codex plugin remove econ-review@openeconai
```

Run only the command for the applicable client. Keep the shared `openeconai`
catalog if another OpenEconAI plugin uses it. Plugin removal intentionally keeps
the user-owned runtime and Review Desk. To remove default support data too,
preview and then explicitly confirm the matching scope:

```text
PYTHON PLUGIN_ROOT/scripts/setup_econ_review.py --cleanup-support --global --dry-run
PYTHON PLUGIN_ROOT/scripts/setup_econ_review.py --cleanup-support --global --confirm-cleanup
```

Custom support locations are never inferred or deleted automatically.

### Migrate from the former marketplace

Remove only the selected client's old `econ-review@econ-paper-review` plugin
and `econ-paper-review` catalog. A report that either is already absent is
harmless. Do not remove the other client's installation.

## Runtime, PDF, and Review Desk notes

Review Desk readiness, manuscript-PDF ingestion, and professional report
rendering are separate capabilities.

- Review Desk is a verified prebuilt local application. Its stable launcher
  serves only release-manifest files on `127.0.0.1`, ships no manuscript or
  review bundle, and opens at `http://127.0.0.1:48127/`. Node.js and npm are not
  required unless modifying the viewer.
- PDF ingestion requires Poppler commands on `PATH`. Missing Poppler does not
  invalidate a completed skill, runtime, or Review Desk installation.
- A compatible LuaLaTeX or Tectonic installation is used when it passes a health
  compile. Otherwise Econ Review uses its maintained ReportLab renderer. Setup
  never installs or alters TeX, Pandoc, Tesseract, or optional PDF backends.

On Windows, `review-desk.cmd` is bound to the managed Python interpreter. The
launcher reuses a matching local server and reports port conflicts instead of
silently attaching to another process; use `--port PORT` for another loopback
port.

## Invocation and troubleshooting

- Standalone Claude Code: `/econ-review`
- Standalone Codex: `$econ-review` or the `/skills` menu
- Native Claude Code plugin: `/econ-review:econ-review`
- Native Codex plugin: `$econ-review:econ-review`

Both clients may invoke the skill automatically when a request matches the
frontmatter description. If the skill does not appear after a new top-level
skill directory is created, start a new session. If it appears twice, identify
which same-client copy is standalone and which is native or legacy; verify the
standalone copy first, then remove only the duplicate belonging to that client.
