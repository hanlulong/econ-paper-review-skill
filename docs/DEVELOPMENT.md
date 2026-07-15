# Development guide

Deep-dive documentation for contributors and advanced users. For the product overview, see the [README](../README.md).

## Requirements

- macOS, Linux, or native Windows; WSL remains supported as Linux. The installer and path contracts have native-Windows tests, while release acceptance should still include a real Windows smoke run when Windows hardware or CI is available.
- Python 3.10+
- Poppler utilities (`pdfinfo`, `pdftotext`, `pdftoppm`) for PDF ingestion; local Tesseract OCR optional
- A compatible LuaLaTeX or Tectonic executable for preferred professional report typesetting; the maintained ReportLab renderer is used only when neither is available
- Node.js 22.14+ only to change, test, or rebuild Review Desk (`.nvmrc` pins the runtime); installed users run its prebuilt bundle with Python

Check your machine:

```bash
python3 econ-review/scripts/pdf_ingestion.py doctor
```

The doctor compares every installed core Python distribution with `requirements-core.txt`, exits nonzero for a missing or unsupported required version, and reports optional ingestion backends as compatible, unavailable, or unsupported against their separate manifests. TeX report-renderer readiness is checked separately and never triggers an automatic system installation.

Release acceptance must use the exact managed runtime created from
`requirements-core.txt`, not whichever packages happen to be installed in a
developer interpreter. A full run in another environment is useful, but skipped
PDF-integration tests there do not establish compatibility. The managed-runtime
run must exercise those tests and treat only explicitly optional backend skips as
expected.

## Install variants

Use one installation method to avoid duplicate discovery. Remote installation is disabled unless both `ECON_REVIEW_ARCHIVE_URL` and the expected `ECON_REVIEW_ARCHIVE_SHA256` are supplied; the installer verifies the archive before safe extraction.

The native plugin is the primary user path. `econ-review/` is the canonical,
self-contained distribution unit: it carries both plugin manifests, the review
and setup skills, all deterministic scripts, dependency contracts, and the
verified Review Desk archive. Marketplace installation copies that immutable
package; the explicit `econ-review-setup` workflow then runs a dry run and uses
`scripts/setup_econ_review.py --support-only` to prepare mutable user-owned
support files without copying another skill.

For an alternative direct installation from a trusted checkout, the repository
wrapper delegates to the same canonical setup tool. It creates or reuses one
managed core runtime, installs for both agents, and runs the dependency and
Poppler doctor:

```bash
python3 scripts/install_econ_review.py --dry-run --global --all --with-review-desk
python3 scripts/install_econ_review.py --global --all --with-review-desk
```

On native Windows, use the machine's working Python 3.10+ command (normally
`python`) and backslash paths; the optional `py` launcher is not required. Project-local setup uses
`--local /path/to/project`; `--claude` and `--codex` select one agent. See
[INSTALL.md](../INSTALL.md) for the one-paste Codex/Claude prompt and non-admin
Poppler guidance.

The shell installer remains the lightweight copy-only path and has no Python
package prerequisites beyond Python 3.10 itself. On macOS or Linux,
`./scripts/install.sh --setup` delegates to the cross-platform managed installer.

```bash
./scripts/install.sh                        # Claude Code and Codex, globally
./scripts/install.sh --global --claude      # Claude Code only
./scripts/install.sh --global --codex       # Codex only
./scripts/install.sh --local /path/to/repo  # project-local install
./scripts/install.sh --dry-run              # inspect destinations without changing files
```

Without `--setup`, `scripts/install.sh` copies the `econ-review/` skill tree only; it
does not change the active Python environment or install Poppler, Tesseract,
Node.js, or the Review Desk. Global installs go to
`${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/econ-review` and
`${CODEX_HOME:-$HOME/.codex}/skills/econ-review`; project installs go to
`.claude/skills/econ-review` and `.agents/skills/econ-review`. Both direct and
plugin-managed setup bind the verified interpreter through a user-owned
descriptor in the platform product-data directory, outside copied skills,
versioned plugin caches, and manuscript trees. The copied install manifest is
an integrity record, not an executable runtime binding. This lets Claude Code
and Codex share one runtime without mutating plugin files. Setup never silently
installs administrator-managed system packages.

`--with-review-desk` verifies and installs the prebuilt static bundle under an
immutable manifest-digest directory, then writes a stable Python dispatcher for
the current version. The launcher verifies the installed files again and serves
only manifest-listed assets at `http://127.0.0.1:48127/`. It contains no bundled
review, needs no Node.js or npm, and reports its path and launch command
separately from the PDF doctor. Omit the flag when Review Desk is not wanted. See
[INSTALL.md](../INSTALL.md) for platform paths and overrides.

## Optional PDF semantic backends

The default `--semantic-backend auto` uses Docling only when its command and required model artifacts are already available; it does not download models unless `--allow-model-downloads` is supplied. Review the code and model licenses before enabling downloads in a distributed product. See `THIRD_PARTY_NOTICES.md` and `econ-review/references/pdf-backends.md` before adding, invoking, or distributing another conversion backend.

```bash
python3 -m pip install -r econ-review/requirements-docling.txt     # optional local semantic structure
python3 -m pip install -r econ-review/requirements-markitdown.txt  # optional local comparison only
python3 -m pip install -r econ-review/requirements-mathpix.txt     # hosted premium adapter (server-side only)
```

Hosted deployments may request a Mathpix proposal, but only after the user authorizes that specific manuscript upload and acknowledges the provider's retention policy. Credentials must come from server-side environment variables, never browser code or review artifacts:

```bash
export MATHPIX_APP_ID='...'
export MATHPIX_APP_KEY='...'
python3 econ-review/scripts/pdf_ingestion.py ingest manuscript.pdf review \
  --review-id REVIEW-ID --source-id SRC-01 --mathpix \
  --authorize-external-upload mathpix --accept-mathpix-retention
```

The integration downloads the proposal and requests remote deletion even when processing fails. A confirmed deletion request does not imply instantaneous removal from every provider cache or billing/audit system. Mathpix output, Docling output, and LLM-assisted visual readings remain unverified until disagreements and load-bearing objects are adjudicated against the saved page renders or supplied source.

## PDF ingestion model

If only a PDF is available, the skill creates a local render-backed ingestion package before review: structured Markdown for reading and stable quotation anchors, with rendered pages and separate crops preserved as the authority for tables, figures, equations, and ambiguous symbols. The package emits hashed page-adjudication packets that route renders, native blocks, detected objects, and proposal artifacts without changing canonical Markdown. A Docling or MarkItDown result can be stored beside that evidence as a proposal; it never silently replaces the canonical page/block map.

## Report PDF rendering

`econ-review/scripts/latex_pdf_renderer.py` and
`econ-review/assets/review-report-template.tex` implement the preferred
professional renderer. The controlled built-in Markdown emitter supplies the
template directly; Pandoc is not bundled or required.

Renderer selection is explicit and reproducible. `auto` prefers, in order, a
compatible `latexmk` + LuaLaTeX toolchain, direct LuaLaTeX, and an explicitly
installed Tectonic executable. The supported explicit selections are
`latexmk-lualatex`, `lualatex`, and `tectonic`. ReportLab is the maintained
fallback only when no supported TeX renderer is available. Once a TeX renderer
has been selected, any conversion or compilation failure stops finalization and
preserves the prior verified PDF; it must never trigger a silent ReportLab
fallback.

Every current finalization requires a clean, nonempty `run.json.paper_title`
verified against the manuscript. The cover contains only that title, “Referee
Report,” and the assessment date. It contains no execution-mode, audience,
product, recommendation, count, or workflow cards. PDF metadata uses the
manuscript title and “Referee Report,” without product or run-mode suffixes.
The visible contents page lists each included document and useful level-two
reader sections—for example,
Overall Assessment, Main Grounds, Closest Literature and Key Differences when
present, Detailed Comments, Highest-Return Editing Revisions, Detailed Editing
Comments, and the P0/P1/P2 revision-plan sections.
Individual comments remain out of the visible contents and may use deeper PDF
bookmarks.

The selected engine and template are recorded in an internal renderer profile;
that profile and the compilation diagnostics are not author-facing report
content. A check reuses the recorded engine and
template profile rather than auto-selecting a different backend. Compile in an
isolated temporary directory, retain diagnostics only for internal debugging,
and do not install or modify TeX Live, MacTeX, MiKTeX, or Tectonic automatically.

## Output contract (v0.4)

Contract v0.4 retains the v0.3 two-report presentation and adds a source-grounded trust spine. New runs put canonical state under `review/supporting/`, leaving a clean reader root:

- `review/paper-review.pdf` — primary professional report containing the author-facing referee report, editing comments, revision plan, and prior-round progress when present, with a restrained title page, balanced contents, bookmarks, quotes, tables, and page numbers.
- `review/README.md` and `review/reports/` — clean reader map plus Markdown copies of the referee report, editing comments, and revision plan.
- `review/supporting/report.md` — substance-only referee report; a conventional referee assessment first, an optional deduplicated `## Closest literature and key differences` section after convincingness, then `## Detailed Comments (N)` for every active substance finding.
- `review/supporting/editing-comments.md` — writing quality, mechanics, terminology, exhibit presentation, optional style improvements, and `## Detailed Editing Comments (N)`. Journal fit remains opt-in.
- `review/supporting/fix-plan.md` — active findings from both channels exactly once, ordered by severity and dependency.
- `review/supporting/review-manifest.json` — indexes the deliberate author-facing reports and plans for the PDF and Review Desk. Internal audit documents are not reader navigation entries.
- `review/supporting/findings.json`, `run.json`, `synthesis.json` + evidence ledgers — canonical state. v0.4 evidence includes source/anchor provenance, exact activated-burden coverage, structured verification, computations, and external sources.
- `review/supporting/finalization.json` — internal completion metadata recording the version, mode, checks, and generated-file hashes, including the PDF. It remains supporting material and is not included in the author-facing PDF.

Legacy v0.1–v0.3 reviews validate under their declared contracts without silent migration.

The checked-in `tests/fixtures/valid-review/` directory is the canonical
supporting package used by generators and validators. It is intentionally flat:
during delivery, `create_delivery.py` projects that canonical package into
`review/supporting/` and creates the clean reader root around it. End-to-end
delivery tests exercise the nested layout, rebuild, rollback, and dirty-parent
guards. Do not duplicate the fixture merely to mirror its delivered location.

`upgrade_review_v03.py` is a maintainer-only helper for deliberate v0.2-to-v0.3
migration and rank repair. Current user workflows do not migrate old packages
silently: validate an old package under its declared contract, or copy it and run
the helper explicitly only when a migration is actually required.

### Detailed-comment format

```markdown
### 1. Section 3.1: short issue title

**Issue**: Exact diagnosis.

**Relevant text**:
> Exact manuscript evidence.

**Concern**: State the evidence boundary and paper-specific consequence without repeating the issue.

**Suggestions**: Give the minimum repair first and add one decisive check only when needed.

**Status**: [Pending]
```

When the relevant evidence is a reviewer observation, comparison, computation, or checked absence, the report uses an unquoted note in the same field; internal provenance tokens such as `[Reviewer observation]` never appear in author-facing prose. `N` is the actual number of verified findings. Full review continues discovery through coverage closure and neither pads nor suppresses issues; the 100-substance and 30-writing capacities are output capacities, and unresolved overflow pauses completion instead of silently truncating.

### Strict full-review source workflow

For a new strict full review, build the canonical source manifest and coverage units before filling claim or writing ledgers. Both proposal commands are read-only: the first proposes Markdown/LaTeX outline inventory rows; the second prints exact occurrence and evidence-reference templates from accepted anchors.

```bash
python3 econ-review/scripts/propose_source_inventory.py REVIEW_DIR SRC-01 UNIT-ID
python3 econ-review/scripts/propose_source_bindings.py REVIEW_DIR --source-id SRC-01
```

The source-inventory proposer may run immediately after the source manifest, before
`coverage.json` exists. In that case `UNIT-ID` names the source-bound unit you will
create, the result marks it `planned`, and `coverage_unit_anchor_ids_to_add` lists
the exact granular and scope anchors that unit must receive. If coverage already
exists, the helper fails unless that unit exists and belongs to the selected source.

Inspect every proposal against the retained source. Create a narrower anchor when a proposed span is broader than the quoted text, and record checked absence only after searching the complete declared scope.

## Review Desk (development)

The checked-in `econ-review/assets/review-desk.zip` is the runtime-free user
artifact carried by the plugin. `review-viewer/scripts/build_review_desk_release.py`
is its sole builder. Development mode starts with no manuscript or private review embedded.
Canonical files remain read-only; author actions are an append-only local event
history; a later review reconciles exported actions by stable finding ID and
independently verifies closure.

```bash
cd review-viewer
nvm use
npm ci
npm run dev            # empty desk; open a review folder via the picker
npm run dev:bundled    # bundles ONLY the synthetic validator fixture
npm run build:release  # static build + deterministic verified user bundle
python3 scripts/build_review_desk_release.py --check
```

The static release build excludes source maps, `node_modules`, and every review
bundle. Its archive contains a canonical per-file hash manifest and both Python
launchers. Run the release check after any viewer change. Production build/sync
refuses to copy review materials unless `ALLOW_PUBLISH=1` is set. Use that
override only for cleared or synthetic inputs.

## Validation suite

An individual generator's `--check` verifies only the artifact owned by that
generator. It can therefore pass while an unrelated sibling artifact is stale.
`finalize_review.py --check` is the whole-package completion gate and is the
command that supports a claim that a review is final.

```bash
python3 econ-review/scripts/validate_skill_package.py econ-review
python3 -m unittest discover -s tests -v
python3 econ-review/scripts/generate_reports.py --check tests/fixtures/valid-review
python3 econ-review/scripts/generate_fix_plan.py --check tests/fixtures/valid-review
python3 econ-review/scripts/generate_sources.py --check tests/fixtures/valid-review
python3 econ-review/scripts/generate_coverage.py --check tests/fixtures/valid-review
python3 econ-review/scripts/generate_verification.py --check tests/fixtures/valid-review
python3 econ-review/scripts/generate_pdf_report.py tests/fixtures/valid-review --check
python3 econ-review/scripts/validate_review.py tests/fixtures/valid-review
python3 econ-review/scripts/finalize_review.py --check tests/fixtures/valid-review
python3 econ-review/scripts/pdf_ingestion.py doctor
python3 benchmarks/evaluate.py                # exploratory: evaluate available packages
python3 benchmarks/evaluate.py --require-all  # strict: fail if any case was not run
python3 -m unittest discover -s tests -p 'test_stat_recompute.py' -v
python3 scripts/build_public_release.py --check
cd review-viewer && npm run lint && npx tsc --noEmit && npm test
cd review-viewer && npm run build:release && python3 scripts/build_review_desk_release.py --check
bash -n scripts/install.sh
```

## Benchmark harness

A public-safe six-family synthetic benchmark supplies rubric-only manuscripts for testing core routing, connective issue recall, and clean false-positive traps; additional contract tests cover the newer conditional lenses. Review outputs are not shipped, so a clean checkout reports every case as `not_run` until those packages are generated. The harness is not evidence of superiority; strict end-to-end review results must be reported before making comparative quality claims.

## Release process

Private development papers and comparison research are ignored by git and are never viewer bundles or distributable skill assets. Internal strategy documents remain outside the public-release allowlist and archive. To assemble a release from the current source-available tree:

```bash
python3 scripts/build_public_release.py --output /path/to/release.zip
```

The plugin version is declared in `econ-review/.claude-plugin/plugin.json` and
`econ-review/.codex-plugin/plugin.json`. Bump both to the same semantic version
for every plugin release; the test suite rejects drift. This source repository
ships the native plugin package but no marketplace. Before the release commit,
validate the package and both client manifests:

```bash
claude plugin validate econ-review --strict
python3 tests/test_native_plugin.py -v
```

Release validation must also prove that the native package contains the
canonical support installer and Review Desk, that support-only setup leaves a
read-only plugin cache unchanged, and that it writes no direct skill copies.

The sole public catalog is [`OpenEconAI/plugins`](https://github.com/OpenEconAI/plugins),
with marketplace name `openeconai`. Do not add a repository-root marketplace
here. After publishing a verified source release, update the `econ-review`
entry in that catalog to the new tagged source and test fresh Claude Code and
Codex installs through `econ-review@openeconai`. Keeping catalog and package
changes in separate repositories makes ownership explicit; the catalog's tests
must reject a missing tag or manifest-version mismatch.

The release builder validates the files in the current working tree. Passing it
does not prove that uncommitted work can be reconstructed from Git. Stage and
commit intended files explicitly and verify a clean status before creating a
release tag:

```bash
git status --short
```

Finally, repeat the managed-runtime test suite, Review Desk bundle check, and
public-release check from a fresh worktree or clone. Create and push the
`econ-review--v<version>` tag only from that verified release commit. Never
publish the private working tree directly.
