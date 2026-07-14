# Workflow and Run State

## Contents

- [Mode matrix](#mode-matrix)
- [Stage and overall run state](#stage-state)
- [Efficient execution without scope loss](#efficient-execution-without-scope-loss)
- [Assessment boundary](#assessment-boundary)
- [Identity and literature degradation](#best-effort-identity-minimization)
- [Parsing degradation and conditional recomputation](#parsing-degradation)
- [Checkpoint behavior](#checkpoint-behavior)

## Mode matrix

| Stage | `quick` | `full` |
|---|---|---|
| Intake and boundary | Required, compact | Required, exhaustive inventory |
| Reconstruction | Central claim, design, and key exhibit | Claim inventory, derivation ledger, methods map |
| User checkpoint | Optional | Pause by default when interactive |
| Literature frontier | Central contribution claims when safely searchable; otherwise state the narrower boundary | Core claim inventory, complementary search, candidate/version screening, attribution audit, and documented closure; `bounded` when safe search or decisive source access is unavailable; add venue evidence only when requested |
| Candidate audit | Top risks only | Independent source-order and cross-unit discovery, rendered table/figure, analytical-ledger, and applicable object-specific passes; compact candidate ledger before full verification |
| Counterargument | Required for reported major risks | Independent refutation where available for critical/major; fairness check for every minor |
| Synthesis | Up to 3 central risks in the bounded pass | Normally a few root-cause essentials, with every independently or cumulatively dispositive concern preserved, plus every surviving detailed comment ranked 1..N |
| Verification | Required | Required for every detailed comment, line by line |
| Outputs | Current-contract core (`run.json`, `findings.json`, `synthesis.json`, `report.md`, `fix-plan.md`); `editing-comments.md` when writing findings exist or writing analysis is requested | Complete current-contract package, including structured source/verification records, `synthesis.json`, and `editing-comments.md` |

Do not market `quick` as a low-quality review. Make it narrower and explicit about what was not assessed. Its categorical risk label is technical or revision risk when no venue or broad tier supplies a publication bar; in that case publication posture remains `Not assessed`.

Set expectations qualitatively rather than promising a fixed runtime. A quick review is one bounded pass over the central claim and largest risks; a full review is a multi-pass inventory of every available section and exhibit and will take materially longer. During an interactive run, report each material stage transition (intake, reconstruction, audit, synthesis, and verification), including a short progress result and the next stage. Do not stream every internal check or substitute progress messages for the saved `stage_status` record.

Contract v0.4 adds a source-grounded trust spine and fail-closed finalization with per-file atomic replacement while retaining canonical synthesis plus separate substance and editing comments. Current full runs record optional author-facing analyses in `requested_addons` and generate the editing-comments preamble from writing-audit v0.4; journal fit appears only under its explicit flag. A later round on the same manuscript lineage may activate `run.json.prior_round`; that path requires immutable handoff snapshots, reviewer-owned reconciliation JSON, a deterministic readable round report, and a fresh whole-paper review. Existing v0.1–v0.3 reviews remain valid under their declared layouts. Select only a version supported by the installed schemas and validator; never relabel an existing review merely to obtain a new presentation or trust marker.

## Stage state

Record each stage as `pending`, `in_progress`, `passed`, `bounded`, `failed`, or `not_applicable`. Use `bounded` when the stage ran but missing inputs or tools limited its conclusion.

For full mode, record `comment_policy.minimum_target`, deprecated aggregate `maximum: null`, `substance_maximum: 100`, `writing_maximum: 30`, and whether exhaustive coverage passed. The channel maxima are author-facing publication capacities, not discovery limits: continue candidate generation through source and burden closure even after reaching either number. Never pad toward a capacity or suppress a distinct survivor to stay below it. Merge only a true shared root cause while retaining every material location. If independently defensible survivors still exceed a channel capacity, preserve them, record the overflow, and pause completion for explicit user resolution.

Treat the second sweep as a saturation loop. Run a complete independent sweep when an explicit user target remains unmet, source-derived coverage is incomplete, an activated burden is thinly audited relative to the objects it contains, manuscript scale warrants another pass, or the first pass was visibly dominated by one issue class. Whenever a sweep produces a new retained finding, update the candidate ledger and repeat the complete sweep. A full review stops only after the final round revisits every non-excluded unit and active burden and produces zero new retained findings. If fewer comments survive than an explicit target, document the source-specific shortfall and never pad. Do not set `exhaustive=true` until every source-derived unit and activated burden appears in `evidence/coverage.json`, every candidate has a disposition, and the zero-yield round is recorded. Treat `paper_family`, `designs`, and coverage branches as descriptive routing metadata; none activates or suppresses a burden.

Use overall run states:

- `draft`: work is incomplete.
- `awaiting_checkpoint`: reconstruction is ready for user correction.
- `blocked`: a required input or user decision prevents further meaningful work.
- `verification_failed`: a draft exists but one or more surviving detailed comments failed verification.
- `complete`: all promised stages and artifact consistency checks passed.

Never set `complete` merely because files exist. For the current contract, use the finalization command defined by the installed scripts. It stages a completed run and generated artifacts, verifies source integrity, structured evidence, deterministic source/coverage/report generation, contract consistency, safe paths, exact gate semantics, and hashes, atomically replaces each generated artifact with rollback on ordinary failures, and writes the finalization receipt last so a partial update cannot remain receipt-valid. Legacy contracts retain their documented compatibility gates.

Do not set `complete` when a comment target remains unexplained or a channel capacity has unresolved overflow. After documented candidate closure and a zero-yield saturation round, an evidence-based shortfall is acceptable when exhaustive coverage is otherwise complete; weak comments added to meet a number are not.

## Efficient execution without scope loss

Complete reconstruction before starting dependent audit work. Once the source map, claims, and active burdens are stable, run literature, logical/technical/methodological, exhibit, replication, and writing-reader discovery concurrently when their inputs do not depend on one another. Each worker returns compact candidate rows; only the coordinator writes `candidates.json`, `findings.json`, and other canonical ledgers.

Retrieve exact source slices by source, page, anchor, unit, or object instead of loading complete multi-megabyte ingestion files into model context. Batch candidate verification by shared claim, exhibit, computation, or external source, while preserving a separate disposition and evidence chain for each candidate. Reuse hash-matched ingestion and reconstruction artifacts; rerun them only when the source or recorded pipeline fingerprint changes.

Do not optimize by sampling pages, lowering render fidelity, skipping separate figure/table/equation inspection, weakening literature closure, or combining genuinely independent problems. Record observed wall time and token counts when the runtime exposes them so a slow stage can be diagnosed rather than guessed.

## Assessment boundary

Record:

- every internal source file supplied, including code and data dictionaries, joined by source ID, path, and hash to the source manifest;
- whether each was fully read, partially read, unreadable, or not opened;
- appendix and exhibit coverage;
- whether figures were visually inspected, only captions/text were available, were not assessed, or were confirmed not present;
- whether equations were preserved by extraction, render-verified, bounded, not assessed, or confirmed not present;
- the claim-level literature frontier state, search availability, unresolved candidates, and any access or chronology boundary;
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

If live web search or sufficient source access is unavailable:

1. Do not fill gaps from memory.
2. In full mode, set affected novelty, contribution, attribution, citation-support, duplicate-publication, and requested venue-positioning judgments to `bounded`; use `not_assessed` only for work explicitly outside a quick review's narrower scope.
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

Use `scripts/pdf_ingestion.py` for rendering, hashes, and page mappings. The complete command, fallback-rendering, crop, and degradation rules live in [pdf-ingestion.md](pdf-ingestion.md); do not duplicate or improvise them here.

Load the numerical-recomputation section of [verification-protocol.md](verification-protocol.md) only when a candidate depends on arithmetic, algebra, or a reported numerical identity.

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
