# Workflow and Run State

## Contents

- [Mode matrix](#mode-matrix)
- [Stage and overall run state](#stage-state)
- [Assessment boundary](#assessment-boundary)
- [Identity and literature degradation](#best-effort-identity-minimization)
- [Parsing and numerical degradation](#parsing-degradation)
- [Checkpoint behavior](#checkpoint-behavior)

## Mode matrix

| Stage | `quick` | `full` |
|---|---|---|
| Intake and boundary | Required, compact | Required, exhaustive inventory |
| Reconstruction | Central claim, design, and key exhibit | Claim inventory, derivation ledger, methods map |
| User checkpoint | Optional | Pause by default when interactive |
| Literature frontier | Closest papers needed for contribution risk; venue work only when requested | Full closest-paper and claimed-gap check; add venue evidence only when requested |
| Candidate audit | Top risks only | Exhaustive section, rendered table/figure, analytical-ledger, and dimension sweeps; conditional lenses |
| Counterargument | Required for reported major risks | Independent refutation where available for critical/major; fairness check for every minor |
| Synthesis | Up to 3 central risks in the bounded pass | Normally a few root-cause essentials, with every independently or cumulatively dispositive concern preserved, plus every surviving detailed comment ranked 1..N |
| Verification | Required | Required for every detailed comment, line by line |
| Outputs | Current-contract core (`run.json`, `findings.json`, `synthesis.json`, `report.md`, `fix-plan.md`); `writing-report.md` when writing findings exist or writing analysis is requested | Complete current-contract package, including structured source/verification records, `synthesis.json`, and `writing-report.md` |

Do not market `quick` as a low-quality review. Make it narrower and explicit about what was not assessed. Its categorical risk label is technical or revision risk when no venue or broad tier supplies a publication bar; in that case publication posture remains `Not assessed`.

Set expectations qualitatively rather than promising a fixed runtime. A quick review is one bounded pass over the central claim and largest risks; a full review is a multi-pass inventory of every available section and exhibit and will take materially longer. During an interactive run, report each material stage transition (intake, reconstruction, audit, synthesis, and verification), including a short progress result and the next stage. Do not stream every internal check or substitute progress messages for the saved `stage_status` record.

Contract v0.4 adds a source-grounded trust spine and fail-closed finalization with per-file atomic replacement while retaining canonical synthesis plus separate substance and writing reports. Current full runs record optional author-facing analyses in `requested_addons` and generate the writing-report preamble from writing-audit v0.4; journal fit appears only under its explicit flag. Existing v0.1–v0.3 reviews remain valid under their declared layouts. Select only a version supported by the installed schemas and validator; never relabel an existing review merely to obtain a new presentation or trust marker.

## Stage state

Record each stage as `pending`, `in_progress`, `passed`, `bounded`, `failed`, or `not_applicable`. Use `bounded` when the stage ran but missing inputs or tools limited its conclusion.

For full mode, also record `comment_policy`: the user-requested minimum target, `maximum: null`, and whether exhaustive coverage passed. A current full review is never truncated by a comment cap; when the user wants a fixed-size output, use the explicitly bounded `quick` mode or ask which objective controls. No universal comment count exists. Run a second sweep when an explicit user target remains unmet, source-derived coverage is incomplete, an activated burden is thinly audited relative to the objects it contains, manuscript scale warrants another pass, or the first pass was visibly dominated by one issue class. If fewer comments survive than an explicit target, document the source-specific shortfall and never pad. Do not set `exhaustive=true` until every source-derived unit and activated burden appears in `evidence/coverage.json` and its readable rendering. Treat `paper_family`, `designs`, and coverage branches as descriptive routing metadata; none activates or suppresses a burden.

Use overall run states:

- `draft`: work is incomplete.
- `awaiting_checkpoint`: reconstruction is ready for user correction.
- `blocked`: a required input or user decision prevents further meaningful work.
- `verification_failed`: a draft exists but one or more surviving detailed comments failed verification.
- `complete`: all promised stages and artifact consistency checks passed.

Never set `complete` merely because files exist. For the current contract, use the finalization command defined by the installed scripts. It stages a completed run and generated artifacts, verifies source integrity, structured evidence, deterministic source/coverage/report generation, contract consistency, safe paths, exact gate semantics, and hashes, atomically replaces each generated artifact with rollback on ordinary failures, and writes the finalization receipt last so a partial update cannot remain receipt-valid. Legacy contracts retain their documented compatibility gates.

Do not set `complete` when a comment target remains unexplained. After the required second sweep, a documented evidence-based shortfall is acceptable when exhaustive coverage is otherwise complete; weak comments added to meet a number are not.

## Assessment boundary

Record:

- every internal source file supplied, including code and data dictionaries, joined by source ID, path, and hash to the source manifest;
- whether each was fully read, partially read, unreadable, or not opened;
- appendix and exhibit coverage;
- whether figures were visually inspected, only captions/text were available, were not assessed, or were confirmed not present;
- whether equations were preserved by extraction, render-verified, bounded, not assessed, or confirmed not present;
- whether literature search was available;
- whether code was not supplied, supplied but review was not permitted, inspected statically, or executed with permission;
- any page, token, OCR, access, or tool limitations.
- every section, exhibit, appendix component, and audit dimension checked, through `evidence/coverage.md` in full mode.
- whether every table was rendered and separately audited, and whether extraction conflicts were resolved;
- whether all seven analytical-ledger domains were complete, bounded, or not applicable with reasons.
- the source manifest, normalized extractions, stable anchors, and source-derived paper order;
- every considered evidentiary burden, its `active`/`not_applicable` state, the exact trigger for activation, and a reason for nonapplication;
- the outbound-search policy (`forbidden`, `deidentified`, or `exact_allowed`) and every query actually sent;
- structured verification, computation, and external-source records supporting any final finding.

Promise full-file inventory and chunked review, not an unlimited-context claim.

Use `not_present` only after inspecting the complete rendered manuscript and confirming that the relevant object does not exist. It is affirmative coverage, not a synonym for `not_assessed`. For figures, `run.json` must agree with `evidence/figures.json.no_figures_confirmed`.

## Best-effort identity minimization

In a single-agent run, avoid recording identities in reconstruction and evaluation artifacts. If duplicate-publication checks need author variants, perform them after the substantive internal audit and keep identity-bearing queries in the sources audit trail. Label the procedure `identity_minimized`, not `blinded`.

## Literature degradation

If live web search or full-text access is unavailable:

1. Do not fill gaps from memory.
2. Set novelty, citation support, duplicate-publication, and venue-positioning fields to `not_assessed` or `bounded`.
3. Remove unverified named sources from the report.
4. Continue internal logic, design, consistency, and clarity review when possible.

For a confidential or unpublished manuscript, default outbound search to `deidentified`. Do not send an exact title, distinctive phrase, author identity, manuscript identifier, or unpublished numerical fingerprint unless the user explicitly permits exact search. When deidentification would make the required search uninformative, mark that judgment bounded rather than leaking the manuscript.

## Parsing degradation

- For every PDF source, use the local verified-transcription workflow in [pdf-ingestion.md](pdf-ingestion.md). It creates the Markdown reading surface, complete page renders, candidate object crops, symbol warnings, hashes, and page/bounding-box provenance. Validate the package before using its source-manifest fragment.
- Prefer source TeX or structured text when it preserves equations and tables better than PDF extraction.
- If the manuscript is supplied only as `.docx`, keep it read-only and use a reliable Word-to-PDF conversion when available. Compare extracted text with the rendered PDF; if faithful rendering is unavailable, ask for a PDF export and mark equations, tables, figures, and layout as bounded rather than inferring them from document XML.
- Compare extracted text with rendered pages for load-bearing equations, tables, and figures.
- Treat the rendered page as authoritative for visible table content. Never admit a missing-cell, shifted-row, blank-panel, symbol, or alignment finding from extraction alone.
- A blank cell in Markdown, OCR, or extracted text is only a candidate. Confirm it on the rendered PDF: reject the candidate when the rendered cell is populated; retain it only when the render is also unexpectedly blank and the table contract or nearby claim requires content. Legitimately blank cells remain checked-clean.
- If an image or table cannot be read, do not criticize its content. Record the boundary and inspect surrounding claims only.
- Do not call any extraction verified or deterministic unless the recorded toolchain was actually run, the package check passed, and the relevant rendered object was reconciled. A valid ingestion package proves integrity and provenance, not mathematical or visual correctness.

### How to render PDF evidence

The current workflow should normally use `scripts/pdf_ingestion.py`, which performs this rendering and records hashes and page mappings. For a bounded legacy or diagnostic run, prefer direct inspection of the original PDF pages when the environment exposes a reliable PDF viewer. Otherwise render pages at readable resolution, for example:

```bash
mkdir -p review/evidence/renders/pages
pdftoppm -png -r 200 manuscript.pdf review/evidence/renders/pages/page
```

Record the source PDF and page mapping, then save figure/table crops or page renders under the corresponding evidence directories. Recheck every proposed visual finding against the original rendered page, not only a crop or OCR layer. If PDF rendering is unavailable or fails, mark figure/table coverage `partial`, `captions_only`, or `not_assessed` as the applicable schema permits, explain the limitation in `run.json.assessment_boundary`, and never fabricate a visual observation or call the audit complete.

## Numerical recomputation

Do not diagnose a numerical error from mental or hand arithmetic. For the bounded identities supported by `scripts/stat_recompute.py`, prepare a JSON check with the exact source locator, run the script, and preserve the input and output in the verification trail. For other identities, use an auditable external computation tool or record the check as bounded. A machine-reported mismatch still requires source, unit, rounding, transformation, and sample reconciliation before it becomes a finding.

For `grim_mean`, supply the reported mean, integer sample size, and displayed decimal precision, but omit `reported`: the script derives arithmetic compatibility rather than comparing against a second reported statistic. `match` means the rounded mean is compatible with an integer-valued total at that precision; `mismatch` means it is not. Neither status establishes misconduct or even a manuscript error without first reconciling rounding conventions, missingness, weights, non-integer outcomes, and the exact analysis sample.

## Checkpoint behavior

Before showing the understanding digest, persist:

- one-sentence research question;
- central contribution claimed;
- target economic object or estimand;
- design/model and variation or restrictions doing the identifying work;
- headline results and evidence locations;
- key maintained assumptions;
- remaining reconstruction uncertainties.

Ask: “Is this a fair account of the paper's question, design, and main result? Please correct any substantive misreading before I critique it.”

If the user corrects the digest, update the reconstruction and re-trace affected claims before proceeding.
