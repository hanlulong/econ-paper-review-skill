# Output Contracts

Use `findings.json` as the canonical detailed state. Contract v0.4 adds source-grounded evidence, compositional audit burdens, canonical paper order, structured verification/computation/external-source records, and atomic finalization while retaining the v0.3 referee presentation. Derive `synthesis.json`, the substance `report.md`, companion `writing-report.md`, and unified `fix-plan.md` from canonical state. Existing v0.1–v0.3 reviews remain valid under their declared contracts without migration.

The installed schemas and validator support v0.4, v0.3, v0.2, and legacy v0.1. New reviews use v0.4. Select the contract explicitly in `run.json`; never relabel an existing review merely to obtain a new presentation or trust marker.

## `README.md` — v0.3/v0.4 start-here page

Generate this author-facing landing page from `run.json`, `synthesis.json`, `findings.json`, and the available human-readable artifacts. It must show the reviewer posture, active comment counts, reading order, principal concerns, a concise three-line account of what was and was not checked, and a file map. Keep the full assessment boundary in canonical state; do not reintroduce an `Assessment Boundary` section into `report.md`.

State plainly that the Markdown reports and plan are complete without the optional local viewer. Explain that checking a plan item records author progress but does not close a finding: later review must verify the `resolved_when` evidence. If `review-actions.json` is used, gloss author dispositions in ordinary language and point to the handoff protocol.

## `run.json`

Validate against `assets/run.schema.json`. Record:

- schema version and run status;
- mode, target venue/tier, paper family, and detected designs;
- source inventory and assessment boundary;
- identity handling (`identity_minimized`, `blinded`, or `not_applied`);
- stage states and lenses loaded;
- literature and code-execution availability;
- counts by severity and verification state;
- `comment_policy`: requested minimum target, optional maximum (`null` means uncapped), and exhaustive-coverage state.
- for v0.4, `activated_burdens`: open stable burden IDs, object type, `active`/`not_applicable` state, activation basis, source/claim/required-omission triggers, and a reason for every `not_applicable` burden. Completed full runs must decide `logical_validity`, `technical_validity`, and `methodological_validity` explicitly.
- for completed split-report runs, `telemetry`: the names of passes actually completed, the number of agents spawned, and observed wall-clock/token counts when the runtime exposes them. Use `null` for unavailable timing or token counts; never estimate them.

Do not fabricate a manuscript hash. Include it only when a tool computed it.

Within the assessment boundary, use `not_present` for figures or equations only after the complete rendered paper has been checked and the absence confirmed. Use `not_assessed` when the check was not performed; never collapse these two states.

## `review-actions.json` — optional author-response sidecar

Validate a supplied or viewer-exported handoff against `assets/review-actions.schema.json` and follow [review-actions-handoff.md](review-actions-handoff.md). This sidecar records author dispositions, optional notes, timestamps, and history. It does not alter `findings.json`: `ready_for_recheck` and `challenged` request another review; they are not verified resolution or counterevidence. `deferred` remains open until a later review verifies otherwise. Keep `run.review_id` stable only across intentional rounds on the same manuscript lineage, and keep a finding ID only for the same underlying issue.

## `review-manifest.json` — v0.3/v0.4 document index

Validate against `assets/review-manifest.schema.json`. Contracts v0.3/v0.4 require the manifest; older packages use conservative standard-path discovery. List every Markdown report, plan, or audit document intended for the local viewer with a stable ID, title, group (`overview`, `reports`, `plan`, or `audit`), safe package-relative path, and order. Include the generated `README.md` as the first overview document. The manifest makes the package viewer-ready but does not make the viewer mandatory. Never list a manuscript or confidential file merely to make it deployable.

## `findings.json`

Validate against `assets/findings.schema.json`. Use stable IDs with informative prefixes such as `LOGIC-01`, `DESIGN-01`, `INFER-01`, `CLARITY-01`, `CONTRIB-01`, or `REPRO-01`.

Each finding must contain:

- a unique consecutive `importance_rank` determining report order;
- a paper-appropriate dimension label, severity, status, and essential flag. Dimension labels are intentionally open-ended so empirical, descriptive, experimental, structural, quantitative, macro, theoretical, and mixed papers are not forced into an irrelevant taxonomy; use stable descriptive labels such as `measurement`, `identification`, `proof`, `computation`, `interpretation`, `writing`, or `reporting`;
- `critique_basis`, identifying whether the concern is a formal error, identification/inference issue, avoidable data handling, claim overreach, internal inconsistency, reader-clarity problem, reporting/reproducibility issue, or contribution issue;
- `data_limitation`, classifying the concern under the reader-claim audit. Never leave an inherent, properly disclosed, claim-bounded limitation active;
- `claim_ids`, linking claim-related findings to the canonical claim-family audit, and `reader_effect`, stating what becomes unclear, inconsistent, overstated, or unconvincing for a reader;
- paper-specific issue and consequence;
- one or more typed evidence records;
- support state;
- confidence and what would change the assessment;
- strongest author reply, search scope, and completed fairness result for every substantive finding. A minor substantive finding may use a brief check. An objective source-verified mechanical correction records fairness as `not_applicable` rather than inventing an author-side defense;
- a proportionate fix strategy, effort, dependency, publishability rationale, and `resolved_when` condition stating the observable evidence that closes the comment, plus structured flags for whether the primary repair requires new data and whether the current design can support it. If an inherent data limit only creates claim overreach, require a no-new-data claim-narrowing alternative rather than requesting unavailable data;
- verification state.

Split-report contracts route each finding with `report_channel`:

- `substance` (the default): design, identification, theory, inference, results, contribution, reproducibility, load-bearing clarity, misleading expression, and citation-support problems;
- `writing`: grammar, spelling, article usage, language mechanics, terminology or label consistency, exhibit presentation, and optional style.

When in doubt, use `substance`. A writing problem that obscures the science and a citation that does not support a load-bearing claim are substantive. Contract v0.1 omits this field and keeps its existing report behavior.

Use `null` for genuinely inapplicable patch or refutation fields; do not use placeholder prose.

Contracts v0.3 and v0.4 require `title`, `decision_role`, and `repairability` for every finding. Use `decision_role` to distinguish rejection risk from technical severity:

- `potentially_dispositive`: could justify rejection if unresolved;
- `posture_material`: could change the recommendation independently or cumulatively;
- `revision_value`: a verified improvement that does not determine the posture;
- `polish`: writing, presentation, metadata, or optional refinement.

Use `repairability` to state the smallest credible route: current-design repair, claim narrowing, additional analysis, new evidence, redesign, unclear, or no clear fix. The legacy `essential` field mirrors `potentially_dispositive` only for compatibility with shared counts and older tooling.

Contract v0.4 also requires canonical `paper_position`; stable evidence IDs and representations; `evidence_boundary`; `minimum_repair`; one `display_evidence_id`; and explicit related evidence/locations. Every evidence item resolves to a source anchor, checked scope, computation, or external-source record as its representation requires. Paper order comes from the source manifest, never lexical section labels.

## `synthesis.json` — v0.3/v0.4 referee synthesis

Validate against `assets/synthesis.schema.json`. Record the overall assessment, specific strengths, review posture, posture rationale, upgrade conditions, convincingness, companion writing count, and principal concerns. A principal concern may group several findings with one root cause or several findings that jointly determine the posture. Every potentially dispositive finding must appear in a principal concern. Do not create a new concern during synthesis; all linked findings must already be active, verified, and routed to substance. In v0.4, `support_mappings` must cover every overall-assessment, strength, posture, upgrade, principal-concern, and convincingness statement with resolving claim, finding, and/or evidence IDs.

## `report.md` — v0.3/v0.4 substance report

Immediately below the H1 title, add one compact navigation line linking `README.md`, `report.md`, `writing-report.md` when present, `fix-plan.md`, and the audit trail. Use the same generated line in every author-facing report and plan so authors can move among artifacts without returning to the file browser.

Use this structure:

```markdown
# Referee Report

## Overall assessment
[A cohesive referee narrative: question, design/model, evidence, main answer, verified contribution, specific strengths, and bottom-line credibility judgment.]

## Recommendation and main grounds
**Recommendation**: [Reject / Weak R&R / Strong R&R / Accept / Not assessed]

[Explain why the assessment follows, what is repairable, and what observable revision would change it.]

## Issues that could prevent publication
### 1. [Principal concern title]
<!-- principal_concern_id: PC-01 -->
[State the claim, evidence delivered, exact gap, decision consequence, linked finding IDs, repairability, and upgrade condition.]

## Other major issues
[Synthesize every posture-material finding not already grouped above. Name the finding IDs.]

## Is the argument convincing?
[State which links in the central claim-evidence-warrant chain are convincing, which remain provisional, and the smallest concrete changes that would make the argument persuasive.]

## Detailed Comments (N)

### 1. Section 3.1: [short issue title]

**Issue**: [One-sentence diagnosis matching the canonical ledger issue.]

**Relevant text**:
> [Verbatim manuscript quote, equation, table cell, verified figure evidence, or nearest statement creating an omission burden.]

**Concern**: [What the paper establishes, where the evidence stops, and which claim or interpretation is affected.]

**Suggestions**: [The minimum concrete repair, followed by one decisive check only if the broader claim is retained.]

**Status**: [Pending]
```

Render `Relevant text` from the finding's designated display evidence. A `verbatim` record may appear as an ordinary quotation. Prefix other representations inside the block with `[Rendered transcription]`, `[Reviewer comparison]`, `[Figure observation]`, `[Table observation]`, `[Checked absence]`, or `[Computation]` as applicable. Never make reviewer prose, a composite comparison, an omission, or a computed result look like manuscript text. Multi-location findings list the related checked anchors in `Concern`.

Set `N` to the actual number of surviving substance-channel comments. Do not pad or truncate the list to a target count. Sort by `importance_rank`, not manuscript order. Number comments consecutively and use the visible format exactly:

```markdown
### {number}. {location}: {short issue title}

**Issue**: {canonical issue}

**Relevant text**:
> {evidence}

**Concern**: {evidence boundary and paper-specific consequence}

**Suggestions**: {minimum concrete repair and any necessary decisive check}

**Status**: [Pending]
```

Use the field meanings in [comment-style.md](comment-style.md). `Concern` diagnoses without repeating `Issue`; `Suggestions` starts with the minimum defensible repair and omits recommendation signposting. Keep `fix.what`, `fix.how`, and the full resolution condition distinct in `findings.json`. For critical and major findings, state the affirmative evidence boundary (`the paper establishes X; it does not yet establish Y`) and the paper-specific consequence. For an inherent data limit, say explicitly that the concern is claim scope rather than the data constraint and lead with a no-new-data repair.

Apply the clarity register in [comment-style.md](comment-style.md). Open with the concrete problem, gloss reviewer-introduced non-obvious acronyms and load-bearing specialist terms, explain what a named diagnostic checks, and identify the paper-specific conclusion or object at risk. Merge overlapping repair prose rather than concatenating it. These are semantic requirements; automated lints intentionally cover only high-confidence surface failures.

Do not use repeated courtroom or competitor-style boilerplate such as `As written`, `the strongest author-side defense`, `supports that defense only to this extent`, `a proportionate repair`, `there seems to be an issue`, or `the document would benefit from`. Do not mechanically lowercase titles into prose. Preserve acronyms, proper names, exhibit labels, and mathematical notation. Titles must describe the observed object and consequence; reserve `invalid`, `incorrect`, `severe`, `fatal`, and similar labels for formally established errors.

Use `[Pending]` for open or challenged findings and place it as the final visible field. The active detailed-comment inventory excludes resolved, dismissed, and refuted candidates.

Place a machine-readable ledger link in a hidden Markdown comment immediately below each heading, for example `<!-- finding_id: LOGIC-01 -->`, so the visible format remains unchanged.

For an omission, quote the nearest statement that creates the disclosure burden, then explain the checked absence scope in `Concern`; do not invent a quote saying the paper omits something. For a table, figure, equation, or code finding, render the exact typed evidence in the block quote and name the exhibit or file in the heading.

For claim-consistency or overclaim findings, link all material occurrences in the ledger even when the visible quote shows only one representative sentence. Name the conflicting or qualifier-dropping locations in `Concern`.

Keep the synthesis prioritized even when the detailed-comment section is long. The cap of three applies only to essential, verdict-determining substance issues. Apply no page or word limit to `report.md`; give every comment enough space for evidence, consequence, fairness, and a concrete repair. Put writing mechanics, venue analysis, scope, and verification logs in their designated companion or evidence files, not in the substance report, and never shorten substantive feedback to meet a length norm.

## `writing-report.md` — v0.3/v0.4 companion report

Full mode requires this separate report. Quick mode creates it only when writing-channel findings exist or the user requests writing analysis. Journal fit is an opt-in addendum.

```markdown
# Writing report

## Writing assessment
[Reader-facing diagnosis, specific strengths, and overall revision priority.]

## Highest-return writing revisions
[Three to five concise, ranked actions linked to detailed finding IDs.]

## Section-by-section reader audit
[For each relevant section: current job, what works, reader friction, revision direction, and finding IDs. Adapt the lens to the paper type.]

## Terminology, definitions, and notation
[Canonical terms, treatment/group labels, units, horizons, abbreviations, variables, and cross-reference style.]

## Tables and figures as writing
[Caption self-containment, titles, units, continuation headings, accessibility, and layout. Route scientifically misleading exhibit content to the substance report.]

## Mechanics and copyedit inventory
[Exact verified occurrences grouped by correction rule and source provenance. Record a render/source check for every occurrence and separate main text from instruments.]

## Detailed Writing Comments (N)

### 1. Section 3.1: [short writing issue title]
<!-- finding_id: WRT-01 -->

**Issue**: [Exact writing, consistency, or presentation problem.]

**Relevant text**:
> [Exact manuscript evidence]

**Concern**: [Why the expression is incorrect, inconsistent, or difficult to read.]

**Suggestions**: [The exact replacement or bounded edit sequence.]

**Status**: [Pending]
```

Set `N` to the active writing-channel count. Use the same hidden finding link and issue-first, status-last contract as `report.md`. Writing-channel comments are normally compact. Both reports preserve global `importance_rank`; visible numbering is consecutive within each report. Do not impose an artificial comment or length cap on the writing report. New packages use writing-audit schema v0.3 and the six-section structure above; v0.1 and v0.2 packages remain validator-compatible.

Add `## Journal fit and submission strategy` only when the user explicitly requests venue analysis. When requested and current literature access exists, give 3–6 candidate journals. For each, cite dated official scope evidence, verify 1–2 recent comparator papers with URL/DOI and access date, state the evidence standard currently met versus still needed, and include verifiable format constraints when relevant. Give an ambitious-to-safe sequence and revision-contingent fit. Use qualitative tiers only and never invent acceptance probabilities. If search is unavailable, mark the requested assessment `bounded`.

The split is presentational, not a loss of coverage. `fix-plan.md`, counts, coverage, and evidence artifacts continue to cover all active findings across both channels exactly once.

## `fix-plan.md`

Start with: “Objective: make the paper more publishable at [venue/tier] by resolving the verified concerns below.”

Use:

- **P0 — before submission:** every essential issue, dependency ordered.
- **P1 — strengthens the paper:** major correctable items ranked by payoff relative to effort.
- **P2 — optional polish:** minor items only.

Include every active detailed comment exactly once in P0, P1, or P2. A long exhaustive review may therefore have a long fix plan.

Render the author action as a Markdown task checkbox while retaining a stable finding-ID heading for machine reconciliation. At the top, explain that ticking a box means “I believe I made this change,” not “the reviewer verified closure,” and that report comments remain pending until rechecked. Gloss `open` as not yet addressed, `ready_for_recheck` as “I've made the change—please verify it,” `challenged` as “I disagree—please consider my evidence,” and `deferred` as an issue kept open for a later round.

For each item include:

- finding ID;
- objective and exact steps;
- affected sections, equations, tables, figures, or code;
- prerequisite items;
- estimated effort (`hours`, `days`, `weeks`, `new-data`, or `not-estimable`);
- decisive completion evidence;
- objection preempted and publishability payoff;
- whether the current design can support the fix.

Render `Done when` from the finding's own `fix.resolved_when` and `Payoff` from `fix.publishability`. Reject migration boilerplate such as `ID closes when...`, `The revised paper implements this repair...`, or `Closing ID removes the submission risk...`; do not reconstruct either field from the action, issue, or severity at presentation time.

Do not convert an unfixable issue into a long task list. State the portfolio choice: redesign, narrow the claim, collect new evidence, or retarget.

## Evidence files

- `evidence/source-manifest.json`: v0.4 source hashes, normalized extractions, stable anchors, and source-derived paper order.
- `evidence/verification.json`: v0.4 finding-by-evidence verification records; every pass resolves to an anchor, computation, external source, or checked-absence scope.
- `evidence/computations.json`: v0.4 reproducible numerical/algebraic checks with input anchors, tool/method, tolerance, result artifact, and hash.
- `evidence/external-sources.json`: v0.4 confidentiality policy and verified external records with stable IDs, dated access, supported propositions, and snapshots.
- `evidence/reconstruction.md`: claim inventory, derivation ledger, methods map, digest.
- `evidence/reader-claim-audit.md`: reader map, cross-section claim ledger, convincingness assessment, data-limitation classifications, and report-tone check.
- `evidence/claims.json`: schema-valid audit scope, claim families, canonical supported claims, occurrence comparisons, reader map, comprehensive terminology/variable definitions, structured central-argument assessment, and structured writing audit. Its coverage-unit list must match the manuscript coverage inventory. Every unsafe claim occurrence, inconsistent or unresolved reader state, and undefined, inconsistent, or overloaded load-bearing term must map to an active verified finding or an explicit bounded reason permitted by the schema.
- `evidence/figures.md`: readable per-figure inventory, visual findings, checked-clean results, and caption/text reconciliation.
- `evidence/figures.json`: schema-valid separate rendered-figure audit, including extraction paths, pages, visual checks, correspondence status, and finding mappings. A figure-free paper must explicitly confirm that the rendered manuscript contains no figures.
- `evidence/tables.md`: readable per-table rendered audit, extraction conflicts, table-contract results, checked-clean states, and text/claim reconciliation.
- `evidence/tables.json`: schema-valid separate rendered-table audit. Every table coverage unit must map exactly once; extraction/render conflicts must be resolved from the rendered page or bounded. A table-free paper must explicitly confirm that the rendered manuscript contains no tables.
- `evidence/analytical-audit.md`: readable partition/regime, measure-algebra, assumption-implementation, derived-number, comparison-harmonization, timing/test, and availability/exclusivity ledgers.
- `evidence/analytical-audit.json`: schema-valid analytical ledgers covering all seven domains, with every adverse state mapped to an active finding and every bounded or inapplicable domain explained.
- `evidence/writing.md`: readable language-mechanics, consistency, style, reference, and venue audit.
- `evidence/writing.json`: schema-valid mechanics corrections, consistency groups, style suggestions, and optional dated evidence-backed venue candidates. Citation accuracy and source-support verification stay in the substantive source audit, not this writing artifact. Review-contract and writing-audit versions are independent; use a writing schema version actually supported by the installed schema and validator, and preserve legacy packages under their declared versions.
- `evidence/coverage.md`: section/exhibit matrix, audit-dimension matrix, second-sweep record, and bounded areas.
- `evidence/coverage.json`: schema-valid coverage units, applicable paper-family branches, finding mappings, and second-sweep state.
- `evidence/sources.md`: queries, verified records, exact support claims, access dates.
- `evidence/verification.md`: pass/fail matrix and corrections made.
- `finalization.json`: v0.4 receipt listing the gates and hashes of every finalized canonical/generated artifact. It is produced only by the atomic finalizer.

Any claimed numerical mismatch must link to an auditable recomputation input/output (use `scripts/stat_recompute.py` for its supported identities) and the exact manuscript locator. Hand arithmetic is not verification. Conditional inference findings must record which reconstructed fact activated the check; absence of an irrelevant conventional diagnostic is not a finding.

## Ship gate

For contract v0.4, run `python3 scripts/finalize_review.py <review-dir>` from the skill package (or the equivalent absolute path) as the only completion path. The finalizer stages a completed run plus generated reports/plans, verifies source integrity and structured evidence, rejects unsafe paths, validates the staged package, commits the staged artifacts atomically, and writes the hashed finalization receipt last as the completion marker. Use `--check` and the individual generators or validator to diagnose failures, not to bypass the transaction.

Contract v0.3 uses `generate_reports.py --check`, `generate_fix_plan.py --check`, and `validate_review.py`; v0.1/v0.2 use only gates applicable to their archived layouts. Fix every error and do not deliver a nonpassing package as final. Archived v0.3 reports remain structurally valid, but current deterministic generation requires `Issue`, `Relevant text`, `Concern`, `Suggestions`, and `Status`.
