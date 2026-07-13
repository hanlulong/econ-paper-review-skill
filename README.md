# econ-review

`econ-review` is a beta Agent Skill for constructive, author-side review of economics papers. Its objective is to improve the paper. It reconstructs the paper before judging it, activates logical, technical, and methodological checks from the actual claims and evidentiary objects, verifies surviving findings against source anchors, and saves a prioritized referee report, a separate writing report, and a dependency-aware fix plan.

The architecture is intended for empirical, experimental, descriptive, structural/quantitative, theoretical, macro, and mixed papers. A public-safe six-family synthetic benchmark now tests routing, seeded-issue recall, and clean false-positive traps. It is a regression harness, not evidence of superiority; end-to-end review results must be reported before making comparative quality claims.

## Current v0.4 scope

- `quick` and `full` modes with a method-agnostic reconstruction core
- claim-family, derivation, methods, terminology/variable, reader-claim, analytical, figure, and table audits
- render-backed PDF-to-structured-Markdown ingestion with page/bounding-box provenance, complete page renders, table/figure/equation crops, symbol warnings, and optional non-authoritative semantic proposals
- rendered inspection of figures and tables, with extraction conflicts resolved against the page image
- conditional DiD, IV, RDD, and cross-cutting inference lenses activated by design facts rather than paper labels
- fairness rules for inherent, disclosed, claim-bounded data limitations
- independent refutation and verification passes when agents are available
- source manifests, SHA-256 hashes, stable anchors, typed evidence representations, reciprocal verification mappings, and JSON Schema validation
- bounded deterministic checks for declared numeric identities; unsupported computations require another auditable tool or a bounded finding
- an exhaustive, importance-ranked inventory with no arbitrary comment, page, or word cap
- a source-linked referee synthesis plus separate substance and writing reports, while preserving legacy v0.1–v0.3 validation
- transactional finalization with atomic, symlink-resistant output writes and a hashed completion receipt
- append-only author-action history with backward-compatible v0.1/v0.2 imports
- a local Review Desk for filtering, annotating, tracking, and exporting review work without mutating canonical artifacts

The broader challenge/deep-dive/rereview/respond loop, additional conditional method lenses, and measured blinded cross-family evaluation remain planned. No superiority claim should be made before an independent benchmark reports precision, recall, false-positive burden, usefulness, and reviewer agreement.

## Install

Use one installation method to avoid duplicate discovery. Remote installation is disabled unless both `ECON_REVIEW_ARCHIVE_URL` and the expected `ECON_REVIEW_ARCHIVE_SHA256` are supplied; the installer verifies the archive before safe extraction.

From a local checkout:

```bash
cd /path/to/econ-paper-review-skill
python3 -m pip install -r requirements.txt
./install.sh                         # Claude Code and Codex, globally
./install.sh --global --claude      # Claude Code only
./install.sh --global --codex       # Codex only
./install.sh --local /path/to/repo  # project-local install
```

The requirements file installs the schema validator plus permissively licensed PDF parsing/cropping libraries. PDF ingestion also requires separately installed Poppler commands (`pdfinfo`, `pdftotext`, and `pdftoppm`); local Tesseract OCR is optional. Those executables are not bundled. Check the machine with `python3 econ-review/scripts/pdf_ingestion.py doctor`.

Docling is an optional local semantic-structure backend and is deliberately kept out of the lightweight environment:

```bash
python3 -m pip install -r requirements-docling.txt
```

Install the hosted premium adapter only in the server environment that needs it:

```bash
python3 -m pip install -r requirements-mathpix.txt
```

The default `--semantic-backend auto` uses Docling only when its command and required model artifacts are already available. It does not download models unless `--allow-model-downloads` is supplied. Review the code and model licenses before enabling downloads in a distributed product. The canonical package is `econ-review/`; installers copy that one tree rather than maintaining platform-specific source variants. See `THIRD_PARTY_NOTICES.md` and `econ-review/references/pdf-backends.md` before adding, invoking, or distributing another conversion backend.

## Use

Put the manuscript in your working directory and give the agent its path. Supply the PDF plus LaTeX or Markdown source when available; for a Word manuscript, include a PDF export so equations, tables, figures, and page layout can be checked against the rendered document. Add the appendix and replication materials if they are in scope.

If only a PDF is available, the skill creates a local render-backed ingestion package before review. It produces structured Markdown for reading and stable quotation anchors, while preserving rendered pages and separate crops as authority for tables, figures, equations, and ambiguous symbols. A local Docling or MarkItDown result can be stored beside that evidence as a proposal; it never silently replaces the canonical page/block map.

Hosted premium deployments may request a Mathpix proposal, but only after the user authorizes that specific manuscript upload and acknowledges the provider's retention policy. Credentials must come from server-side environment variables, never browser code or review artifacts:

```bash
export MATHPIX_APP_ID='...'
export MATHPIX_APP_KEY='...'
python3 econ-review/scripts/pdf_ingestion.py ingest manuscript.pdf review \
  --review-id REVIEW-ID --source-id SRC-01 --mathpix \
  --authorize-external-upload mathpix --accept-mathpix-retention
```

The integration downloads the proposal and requests remote deletion even when processing fails. A confirmed deletion request does not imply instantaneous removal from every provider cache or billing/audit system. The package also emits hashed page-adjudication packets that route renders, native blocks, detected objects, and proposal artifacts without changing canonical Markdown. Mathpix output, Docling output, and LLM-assisted visual readings remain unverified until disagreements and load-bearing objects are adjudicated against the saved page renders or supplied source.

```text
Use $econ-review in full mode to review this paper for a leading field journal.
Use $econ-review in quick mode and identify the three largest submission risks.
Use $econ-review to reconstruct the theory and empirical design before giving detailed comments.
```

`quick` is a bounded pass over the central claim and largest submission risks. `full` is a materially longer, multi-pass review of every available section and exhibit. Runtime varies with paper length, browsing, rendering, and replication work, so the skill reports stage transitions and material access limits instead of promising a fixed number of minutes.

The skill treats manuscripts as read-only and writes artifacts under `review/` unless the user requests an analysis-only response. Open `review/README.md` first when the run finishes.

## Output contract

Contract v0.4 retains the v0.3 two-report presentation and adds a source-grounded trust spine:

- `review/README.md` is the generated start-here page: posture, priority concerns, review coverage, reading order, and a map of the human-readable artifacts.
- `review/synthesis.json` stores the overall assessment, reviewer posture, principal rejection risks, other major issues, repairability, and upgrade conditions.
- `review/report.md` is the substance-only referee report. It begins with a conventional referee assessment and prioritizes issues that could prevent publication before `## Detailed Comments (N)` for every active substance finding.
- `review/writing-report.md` contains writing quality, grammar and mechanics, language consistency, exhibit presentation, optional style improvements, and `## Detailed Writing Comments (N)` for active writing findings. It is required in full mode; journal-fit guidance is added only when explicitly requested.
- `review/fix-plan.md` covers active findings from both channels exactly once, ordered by severity and dependency.
- `review/review-manifest.json` indexes every intended report, plan, and readable audit document; it makes the package open cleanly in the optional Review Desk without listing the manuscript.
- `review/findings.json`, `run.json`, `synthesis.json`, and the evidence ledgers are canonical state. v0.4 evidence includes the source manifest, structured verification, computations, and external sources.
- `review/finalization.json` records the gates and artifact hashes produced by the atomic finalizer; changing an artifact invalidates completion.

The Markdown landing page, reports, and revision plan are the complete author-facing output; they work without Node.js or the Review Desk. The local viewer is optional and adds overview-first reading, filtering, source/exhibit context, paper-order and principal-concern navigation, deep links, local author-response event history, and privacy controls.

Legacy v0.1–v0.3 reviews validate under their declared contracts without silent migration.

Detailed comments preserve the requested outer format while allowing a natural reader-centered voice:

```markdown
## Detailed Comments (N)

### 1. Section 3.1: short issue title

**Issue**: Exact diagnosis.

**Relevant text**:
> Exact manuscript evidence.

**Concern**: State the evidence boundary and paper-specific consequence without repeating the issue.

**Suggestions**: Give the minimum repair first and add one decisive check only when needed.

**Status**: [Pending]
```

`N` is the actual number of verified findings. The skill neither pads nor truncates to a target. Principal concerns are root-cause merged and concise, but no verified dispositive issue is hidden to satisfy a numerical cap.

## Local Review Desk

Development mode starts with no manuscript or private review embedded. Users can open a review folder containing canonical JSON, every manifest-listed report and plan, and optional rendered exhibit context. The viewer opens on the overall assessment, keeps the queue beside reports and comment detail, supports importance, paper-order, and principal-concern workflows, and records author actions as an append-only local event history. Canonical files remain read-only; a later review reconciles exported actions by stable finding ID and independently verifies closure.

```bash
cd review-viewer
nvm use
npm install
npm run dev
```

The explicitly gated bundled build contains only the synthetic validator fixture:

```bash
npm run dev:bundled
```

Production build/sync refuses to copy review materials unless `ALLOW_PUBLISH=1` is set. Use that override only for cleared or synthetic inputs.

## Validate development builds

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" econ-review
python3 -m unittest discover -s tests -v
python3 econ-review/scripts/generate_reports.py --check tests/fixtures/valid-review
python3 econ-review/scripts/generate_fix_plan.py --check tests/fixtures/valid-review
python3 econ-review/scripts/validate_review.py tests/fixtures/valid-review
python3 econ-review/scripts/finalize_review.py --check tests/fixtures/valid-review
python3 econ-review/scripts/pdf_ingestion.py doctor
python3 benchmarks/evaluate.py
python3 -m unittest discover -s tests -p 'test_stat_recompute.py' -v
python3 scripts/build_public_release.py --check
cd review-viewer && npm run lint && npx tsc --noEmit && npm test
bash -n install.sh
```

Private development papers and comparison research are ignored by git and are not viewer bundles or distributable skill assets. The project code and documentation are proprietary and all rights reserved. Third-party components remain governed by their own licenses.

Internal strategy documents remain local and ignored rather than entering Git history. Public archives are built from an exact allowlist. After making the owner-level license and release decision, create an archive with `python3 scripts/build_public_release.py --output /path/to/release.zip`; never publish the private working tree directly.
