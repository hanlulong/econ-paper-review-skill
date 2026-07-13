# Development guide

Deep-dive documentation for contributors and advanced users. For the product overview, see the [README](../README.md).

## Requirements

- macOS, Linux, or Windows through WSL (native Windows untested)
- Python 3.10+
- Poppler utilities (`pdfinfo`, `pdftotext`, `pdftoppm`) for PDF ingestion; local Tesseract OCR optional
- Node.js 22.14+ only for the optional Review Desk (`.nvmrc` pins the runtime)

Check your machine:

```bash
python3 econ-review/scripts/pdf_ingestion.py doctor
```

The doctor compares every installed core Python distribution with `requirements-core.txt`, exits nonzero for a missing or unsupported required version, and reports optional backends as compatible, unavailable, or unsupported against their separate manifests.

## Install variants

Use one installation method to avoid duplicate discovery. Remote installation is disabled unless both `ECON_REVIEW_ARCHIVE_URL` and the expected `ECON_REVIEW_ARCHIVE_SHA256` are supplied; the installer verifies the archive before safe extraction.

```bash
python3 -m pip install -r requirements.txt
./install.sh                        # Claude Code and Codex, globally
./install.sh --global --claude      # Claude Code only
./install.sh --global --codex       # Codex only
./install.sh --local /path/to/repo  # project-local install
./install.sh --dry-run              # inspect destinations without changing files
```

The installer copies the `econ-review/` skill tree only; it does not change the active Python environment or install Poppler, Tesseract, Node.js, or the Review Desk. Global installs go to `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/econ-review` and `${CODEX_HOME:-$HOME/.codex}/skills/econ-review`; project installs go to `.claude/skills/econ-review` and `.agents/skills/econ-review`.

## Optional PDF semantic backends

The default `--semantic-backend auto` uses Docling only when its command and required model artifacts are already available; it does not download models unless `--allow-model-downloads` is supplied. Review the code and model licenses before enabling downloads in a distributed product. See `THIRD_PARTY_NOTICES.md` and `econ-review/references/pdf-backends.md` before adding, invoking, or distributing another conversion backend.

```bash
python3 -m pip install -r requirements-docling.txt     # optional local semantic structure
python3 -m pip install -r requirements-markitdown.txt  # optional local comparison only
python3 -m pip install -r requirements-mathpix.txt     # hosted premium adapter (server-side only)
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

## Output contract (v0.4)

Contract v0.4 retains the v0.3 two-report presentation and adds a source-grounded trust spine:

- `review/README.md` — generated start-here page: posture, priority concerns, coverage, reading order, artifact map.
- `review/synthesis.json` — overall assessment, reviewer recommendation, principal rejection risks, other major issues, repairability, upgrade conditions.
- `review/report.md` — substance-only referee report; a conventional referee assessment first, then `## Detailed Comments (N)` for every active substance finding.
- `review/writing-report.md` — writing quality, grammar and mechanics, language consistency, exhibit presentation, optional style improvements, and `## Detailed Writing Comments (N)`. The preamble is generated from writing-audit v0.4. Journal-fit guidance appears only when `run.json.requested_addons` includes `journal_fit`; assessment-boundary detail stays out of both reports.
- `review/fix-plan.md` — active findings from both channels exactly once, ordered by severity and dependency.
- `review/review-manifest.json` — indexes every intended report, plan, and readable audit document for the Review Desk, without listing the manuscript.
- `review/findings.json`, `run.json`, `synthesis.json` + evidence ledgers — canonical state. v0.4 evidence includes source/anchor provenance, exact activated-burden coverage, structured verification, computations, and external sources.
- `review/finalization.json` — records the exact version/mode/source gate set and every artifact hash; changing or adding an artifact invalidates completion. Per-file atomic replacement with ordinary-failure rollback; the receipt is written last. Full receipts use schema v0.3; quick receipts use schema v0.2 with full-review gates absent. The unsigned receipt is an integrity and completeness manifest, not proof of authorship or origin.

Legacy v0.1–v0.3 reviews validate under their declared contracts without silent migration.

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

When the relevant evidence is a reviewer observation, comparison, computation, or checked absence, the report uses an unquoted note in the same field; internal provenance tokens such as `[Reviewer observation]` never appear in author-facing prose. `N` is the actual number of verified findings — the skill neither pads nor truncates to a target, and no verified dispositive issue is hidden to satisfy a numerical cap.

### Strict full-review source workflow

For a new strict full review, build the canonical source manifest and coverage units before filling claim or writing ledgers. Both proposal commands are read-only: the first proposes Markdown/LaTeX outline inventory rows; the second prints exact occurrence and evidence-reference templates from accepted anchors.

```bash
python3 econ-review/scripts/propose_source_inventory.py REVIEW_DIR SRC-01 UNIT-ID
python3 econ-review/scripts/propose_source_bindings.py REVIEW_DIR --source-id SRC-01
```

Inspect every proposal against the retained source. Create a narrower anchor when a proposed span is broader than the quoted text, and record checked absence only after searching the complete declared scope.

## Review Desk (development)

Development mode starts with no manuscript or private review embedded. Canonical files remain read-only; author actions are an append-only local event history; a later review reconciles exported actions by stable finding ID and independently verifies closure.

```bash
cd review-viewer
nvm use
npm ci
npm run dev            # empty desk; open a review folder via the picker
npm run dev:bundled    # bundles ONLY the synthetic validator fixture
```

Production build/sync refuses to copy review materials unless `ALLOW_PUBLISH=1` is set. Use that override only for cleared or synthetic inputs.

## Validation suite

```bash
python3 econ-review/scripts/validate_skill_package.py econ-review
python3 -m unittest discover -s tests -v
python3 econ-review/scripts/generate_reports.py --check tests/fixtures/valid-review
python3 econ-review/scripts/generate_fix_plan.py --check tests/fixtures/valid-review
python3 econ-review/scripts/generate_sources.py --check tests/fixtures/valid-review
python3 econ-review/scripts/generate_coverage.py --check tests/fixtures/valid-review
python3 econ-review/scripts/validate_review.py tests/fixtures/valid-review
python3 econ-review/scripts/finalize_review.py --check tests/fixtures/valid-review
python3 econ-review/scripts/pdf_ingestion.py doctor
python3 benchmarks/evaluate.py                # exploratory: evaluate available packages
python3 benchmarks/evaluate.py --require-all  # strict: fail if any case was not run
python3 -m unittest discover -s tests -p 'test_stat_recompute.py' -v
python3 scripts/build_public_release.py --check
cd review-viewer && npm run lint && npx tsc --noEmit && npm test
bash -n install.sh
```

## Benchmark harness

A public-safe six-family synthetic benchmark supplies rubric-only manuscripts for testing core routing, connective issue recall, and clean false-positive traps; additional contract tests cover the newer conditional lenses. Review outputs are not shipped, so a clean checkout reports every case as `not_run` until those packages are generated. The harness is not evidence of superiority; strict end-to-end review results must be reported before making comparative quality claims.

## Release process

Private development papers and comparison research are ignored by git and are never viewer bundles or distributable skill assets. Internal strategy documents remain in the private repository and are excluded from the public-release allowlist and archive. After the owner-level license and release decision:

```bash
python3 scripts/build_public_release.py --output /path/to/release.zip
```

Never publish the private working tree directly.
