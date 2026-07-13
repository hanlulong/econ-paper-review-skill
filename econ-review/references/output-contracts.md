# Output Contracts

Use `findings.json` as the canonical detailed state. Contract v0.4 adds source-grounded evidence, compositional audit burdens, canonical paper order, structured verification/computation/external-source records, and fail-closed finalization while retaining the v0.3 referee presentation. Derive `synthesis.json`, the substance `report.md`, companion `writing-report.md`, and unified `fix-plan.md` from canonical state. Existing v0.1–v0.3 reviews remain valid under their declared contracts without migration.

The installed schemas and validator support v0.4, v0.3, v0.2, and legacy v0.1. New reviews use v0.4. Select the contract explicitly in `run.json`; never relabel an existing review merely to obtain a new presentation or trust marker. Current full v0.4 finalizations use receipt schema v0.3 and carry `structured_audit_v02` plus `burden_coverage_v02`; they require claims, analytical-audit, coverage, and writing schemas v0.2, v0.2, v0.2, and v0.4 respectively plus external-sources schema v0.3, figures v0.2 whenever figures are present, and tables v0.2 whenever tables are present. Current quick finalizations use receipt schema v0.2 without either full-review gate. Immutable v0.4 receipt schemas v0.1 and v0.2 remain readable and verifiable under the guarantees that created them; they do not acquire the newer trust claim unless regenerated.

## Contents

- [`README.md`, run state, actions, and manifest](#readmemd--v03v04-start-here-page)
- [Canonical findings and synthesis](#findingsjson)
- [Substance and writing reports](#reportmd--v03v04-substance-report)
- [Revision plan](#fix-planmd)
- [Evidence files](#evidence-files)
- [Ship gate](#ship-gate)

## `README.md` — v0.3/v0.4 start-here page

Generate this author-facing landing page from `run.json`, `synthesis.json`, `findings.json`, and the available human-readable artifacts. It must show the reviewer posture, active comment counts, reading order, principal concerns, a concise three-line account of what was and was not checked, and a file map. Keep the full assessment boundary in canonical state; do not reintroduce an `Assessment Boundary` section into either author-facing report.

State plainly that the Markdown reports and plan are complete without the optional local viewer. Explain that checking a plan item records author progress but does not close a finding: later review must verify the `resolved_when` evidence. If `review-actions.json` is used, gloss author dispositions in ordinary language and point to the handoff protocol.

## `run.json`

Validate against `assets/run.schema.json`. Record:

- schema version and run status;
- mode, target venue/tier, paper family, and detected designs;
- `requested_addons`: an explicit inventory of optional author-facing analyses; current full reviews use `[]` when none were requested and add `journal_fit` only after an explicit venue-analysis request;
- source inventory and assessment boundary;
- identity handling (`identity_minimized`, `blinded`, or `not_applied`);
- stage states and lenses loaded;
- literature and code-execution availability;
- counts by severity and verification state;
- `comment_policy`: requested minimum target, maximum, and exhaustive-coverage state. Current v0.4 full reviews require `maximum: null`; bounded quick and legacy contracts retain their declared behavior.
- for v0.4, `activated_burdens`: a precise row `id`, one stable conceptual `parent_id` from the design audit, object type, `active`/`not_applicable` state, activation basis, source/claim/required-omission triggers, and a reason for every `not_applicable` burden. The parent classifies the row; do not add a duplicate alias or parent row. Completed full runs must decide and self-parent `logical_validity`, `technical_validity`, and `methodological_validity` explicitly.
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

Validate against `assets/synthesis.schema.json`. Record the overall assessment, specific strengths, review posture, posture rationale, upgrade conditions, convincingness, companion writing count, and principal concerns. When both target venue and tier are unspecified, use `not_assessed` for the publication posture while retaining a decisive technical and revision assessment. A principal concern may group several findings with one root cause or several findings that jointly determine the posture. Every potentially dispositive finding must appear in a principal concern. Do not create a new concern during synthesis; all linked findings must already be active, verification-passed, and routed to substance. In v0.4, `support_mappings` must cover every overall-assessment, strength, posture, upgrade, principal-concern, and convincingness statement with resolving claim, finding, and/or evidence IDs. Current strict full reviews resolve claim IDs only from anchored canonical claim families, never from a finding's self-declared links. Finding and evidence support is eligible only while the owning finding remains active and verification-passed; every evidence ID must name its reciprocal finding owner in the same mapping. A clean strength uses one or more precisely anchored canonical claims without adverse finding evidence. Each principal-concern rationale and upgrade mapping uses exactly that concern's linked active, verification-passed findings. These rules keep a dismissed concern, failed verification, or orphaned quotation from silently supporting the referee synthesis.

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
[Use a block quote for manuscript text. Use an unquoted note for reviewer observations, comparisons, computations, or checked absences.]

**Concern**: [What the paper establishes, where the evidence stops, and which claim or interpretation is affected.]

**Suggestions**: [The minimum concrete repair, followed by one decisive check only if the broader claim is retained.]

**Status**: [Pending]
```

Render `Relevant text` from the finding's designated display evidence. Render `verbatim` records and normalized source transcriptions as quotations. Render reviewer observations, comparisons, computations, and checked absences as unquoted evidence notes, without internal bracket labels such as `[Reviewer observation]`. Canonical `representation` metadata—not a prose prefix—preserves provenance. A composite comparison must cite at least two source anchors and verify every cited component. Never make reviewer prose, a composite comparison, an omission, or a computed result look like manuscript text. Multi-location findings list the related checked anchors in `Concern`. When evidence declares `locator.page`, that page must agree with every referenced source anchor; leave it null for cross-page composites until the contract defines explicit anchor roles. Legacy canonical content may retain a matching prefix, but deterministic report generation removes it.

Set `N` to the actual number of surviving substance-channel comments. Do not pad or truncate the list to a target count. Sort by `importance_rank`, not manuscript order. Number comments consecutively and use the visible format exactly:

```markdown
### {number}. {location}: {short issue title}

**Issue**: {canonical issue}

**Relevant text**:
{quoted source excerpt or unquoted evidence note}

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

Keep the synthesis prioritized even when the detailed-comment section is long. It will normally contain only a few root-cause essentials, but there is no numerical cap: preserve every independently or cumulatively dispositive concern. Apply no page or word limit to `report.md`; give every comment enough space for evidence, consequence, fairness, and a concrete repair. Put writing mechanics, venue analysis, scope, and verification logs in their designated companion or evidence files, not in the substance report, and never shorten substantive feedback to meet a length norm.

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

## Style and writing improvements
[Concrete optional or recommended revisions plus the redundancy map. Distinguish objective corrections from matters of style.]

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

Set `N` to the active writing-channel count. Use the same hidden finding link and issue-first, status-last contract as `report.md`. Writing-channel comments are normally compact. Both reports preserve global `importance_rank`; visible numbering is consecutive within each report. Do not impose an artificial comment or length cap on the writing report. Current full packages use writing-audit schema v0.4 and generate the seven core sections above entirely from `evidence/writing.json`; hand-edited or stale preambles fail synchronization. Older writing-audit and receipt versions remain validator-compatible under their declared guarantees.

Add `## Journal fit and submission strategy` only when `run.json.requested_addons` contains `journal_fit`. When the add-on is absent, record `venue_fit.status: not_requested` and emit no placeholder section or dated/candidate/finding payload. When requested and current literature access exists, give 3–6 candidate journals. For each, cite dated official scope evidence, verify 1–2 recent comparator papers with HTTPS links and access dates, state the evidence standard currently met versus still needed, and include verifiable format constraints when relevant. Evidence dates cannot be later than the venue assessment date or current date. Give an ambitious-to-safe sequence and revision-contingent fit. Use qualitative tiers only and never invent acceptance probabilities. If search is unavailable, mark the requested assessment `bounded`.

Do not put an `Assessment Boundary` section in either author-facing report. Scope state remains available in `run.json`, `evidence/writing.json`, the landing page's compact coverage summary, and the readable audit trail.

The split is presentational, not a loss of coverage. `fix-plan.md`, counts, coverage, and evidence artifacts continue to cover all active findings across both channels exactly once.

## `fix-plan.md`

Start with: “Objective: improve the paper for [venue/tier or intended audience] by resolving the verified concerns below.”

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

- `evidence/source-manifest.json`: v0.4 source hashes, normalized extractions, stable anchors, and source-derived paper order. Manuscript, appendix, supplement, supplied-code, and supplied-data-dictionary rows are internal sources and join exactly to `run.json.assessment_boundary`; external literature records stay outside that boundary in `external-sources.json`.
- `evidence/verification.json`: v0.4 finding-by-evidence verification records; every pass resolves to an anchor, computation, external source, or checked-absence scope.
- `evidence/computations.json`: v0.4 reproducible numerical/algebraic checks with input anchors, tool/method, tolerance, result artifact, and hash. Legacy computation schema v0.1 requires reciprocal finding links. Schema v0.2 also permits a clean audit-only computation when its `audit_links` match exactly the analytical entry or magnitude assessment that canonically cites it; orphan and one-way links fail validation.
- `evidence/external-sources.json`: v0.4 confidentiality policy and verified external records with stable IDs, dated access, supported propositions, and saved snapshots. New or re-finalized full reviews use schema v0.3 and bind every supported proposition to an exact UTF-8 snapshot span and hash, proposition kind, access scope, reviewer-assessed support state, and reciprocal finding links. Scope-completeness claims require a concrete basis; abstract and metadata captures support only narrow statements they actually contain; a single source record cannot certify frontier exhaustiveness. The ledger records a `complete`, `bounded`, or `not_assessed` frontier audit. In each closest-paper row, the citation, question, design/object, and main result resolve to their own source-owned support records, while the overlap and difference cite the manuscript anchors compared. Partial or conflicting load-bearing support makes that comparison bounded. A complete audit contains confidentiality-safe query logs and at least one complete closest-paper comparison. Bounded and not-assessed states carry a structured boundary. Schema v0.2 remains compatible as the frontier-only legacy contract; v0.1 remains compatible with older source-ledger contracts and immutable receipt-schema-v0.1 packages.
- `evidence/reconstruction.md`: claim inventory, derivation ledger, methods map, digest.
- `evidence/reader-claim-audit.md`: reader map, cross-section claim ledger, economic argument and evidence audit, convincingness assessment, data-limitation classifications, and report-tone check.
- `evidence/claims.json`: schema-valid audit scope, claim families, canonical supported claims, occurrence comparisons, reader map, comprehensive terminology/variable definitions, structured central-argument assessment, and structured writing audit. New or re-finalized full reviews use claims-audit schema v0.2 and also record economic links, full comparison or intervention content, cross-result relationships, evidence-object completeness, magnitude context, and population/domain transport under `argument_audit`; legacy v0.1 claims audits remain validator-compatible under older contracts and immutable v0.4 receipt-schema-v0.1 packages. Its coverage-unit list must match the manuscript coverage inventory. In the current strict full contract, every claim occurrence binds exact or normalized text and its locator to one precise source anchor, and a claim family's anchors equal the union of its occurrence anchors. Reader rows identify their claim families and resolve back to those anchors; clean reader states also cite a source-wide scope anchor as `checked_absence`. Term rows bind first use to a precise anchor, cite direct support, and use scope-anchored absence for clean or undefined states. Only active, passed finding evidence can satisfy a reciprocal row-to-finding join. Computations and external **support records** may supplement source support but cannot replace the manuscript anchor for a manuscript claim. The `terminology_inventory` adjudicates every PDF-ingestion symbol candidate as `mapped_term`, `standard_unambiguous_notation`, `prose_noise`, `extraction_artifact`, or `non_load_bearing`, with a reason and exact occurrence anchors; non-PDF manuscript sources declare a candidate inventory or a bounded manual scope. Mapped load-bearing terms record first-use and definition anchors, or a scope-anchored definition absence when genuinely undefined. Every unsafe claim occurrence, inconsistent or unresolved reader state, undefined, inconsistent, or overloaded load-bearing term, and adverse v0.2 argument-audit state must map to an active verified finding or a structured bounded state permitted by the schema. Row-level bounded states propagate to collection and coverage status, and a bounded headline argument propagates to the central assessment.
- `evidence/figures.md`: readable per-figure inventory, visual findings, checked-clean results, and caption/text reconciliation.
- `evidence/figures.json`: schema-valid separate rendered-figure audit. New or materially refreshed audits use v0.2 rows that bind each figure to both its source-manifest row and coverage unit, plus hashed full-page and optional crop assets, visible identity evidence, pages, visual checks, correspondence status, and finding mappings. For PDF sources, the asset path, digest, and page must join exactly to the authenticated PDF-ingestion page-render or figure-crop record; legacy v0.1 rows remain valid. A figure-free paper must explicitly confirm that the rendered manuscript contains no figures.
- `evidence/tables.md`: readable per-table rendered audit, extraction conflicts, table-contract results, checked-clean states, and text/claim reconciliation.
- `evidence/tables.json`: schema-valid separate rendered-table audit. New or materially refreshed populated inventories use schema v0.2, with structured source bindings and immutable, role-declared render assets joined to canonical PDF-ingestion pages and table objects where applicable. Version 0.1 remains readable only for backward compatibility. Every table coverage unit must map exactly once; extraction/render conflicts must be resolved from the rendered page or bounded. A table-free paper must explicitly confirm that the rendered manuscript contains no tables.
- `evidence/analytical-audit.md`: readable partition/regime, measure-algebra, assumption-implementation, derived-number, comparison-harmonization, timing/test, and availability/exclusivity ledgers.
- `evidence/analytical-audit.json`: schema-valid analytical ledgers covering all seven domains, with every adverse state mapped to an active finding and every bounded or inapplicable domain explained. New or re-finalized full reviews use analytical-audit schema v0.2. Every typed locator has a `record_ref` that appears directly in the entry's evidence references and reconciles the locator's source, locator, and representation-appropriate content to one canonical anchor, finding-evidence, computation, or external-source record. A bounded v0.2 entry or check propagates to the domain and reciprocal coverage dimension. Legacy v0.1 ledgers remain validator-compatible under older contracts and immutable v0.4 receipt-schema-v0.1 packages, and must still contain substantive source-specific evidence.
- `evidence/writing.md`: readable language-mechanics, consistency, style, and optional venue audit. Routine bibliography and citation-accuracy checking is outside the default writing report; load-bearing source support stays substantive.
- `evidence/writing.json`: schema-valid assessment, terminology and exhibit summaries; section and redundancy audits; mechanics corrections; consistency groups; style suggestions; and optional dated evidence-backed venue candidates. Current source-derived rows cite canonical evidence and coverage units: issue occurrences bind exact or normalized text to anchors, while checked-clean mechanics and consistent terminology use scope anchors with `checked_absence`. Only active, passed finding evidence can support an adverse row. Citation accuracy and source-support verification stay in the substantive source audit, not this writing artifact. Review-contract and writing-audit versions are independent; current full runs use writing schema v0.4, while legacy packages retain their declared versions.
- `evidence/coverage.md`: deterministic rendering of source units, source-inventory closure, the activated-burden audit, applicable audit dimensions, second-sweep state, and bounded areas.
- `evidence/coverage.json`: schema-valid source/anchor-bound units, an exact audit row for every activated burden, extensible descriptive lens tags, applicable structured dimensions, finding mappings, and second-sweep state. Current full reviews also partition every syntax-derived Markdown/LaTeX heading or environment and every authenticated PDF page, block, table, figure, and equation in `source_inventory`; covered objects map to source-bound units and covered PDF tables/figures map reciprocally to rendered-audit rows. Duplicate, false-positive, bounded, and non-substantive outline exclusions are explicit object decisions, never silent omissions. A source-wide scope anchor can support checked absence but cannot certify granular coverage. Every internal source and anchor is covered; a code-range anchor requires a typed code unit. Supplied code, a supplied data dictionary, or a supplied-code capability state (`not_permitted`, `static_only`, or `executed`) activates a reproducibility or computational-validity burden whose audit covers all units derived from those materials. This exhaustive artifact is full-mode only; quick mode records the trigger and active burden without claiming full unit coverage. Family and branch tags are routing metadata only; activated burdens control scope.
- `evidence/sources.md`: deterministic rendering of the external-source ledger, including actual queries, verified records, supported propositions, access dates, closest-paper comparisons, and structured boundaries.
- `evidence/verification.md`: pass/fail matrix and corrections made.
- `finalization.json`: v0.4 receipt listing the exact version/mode/source gate set and hashes of every finalized canonical/generated artifact. It is produced only by the fail-closed finalizer, after per-file atomic replacement and ordinary-failure rollback; it does not assert filesystem-wide multi-file atomicity. Current full receipts use schema v0.3 and include `structured_audit_v02` plus `burden_coverage_v02`; current quick receipts use schema v0.2 and include neither. Immutable schema-v0.1 and schema-v0.2 receipts retain only their original guarantees.

Any claimed numerical mismatch must link to an auditable recomputation input/output (use `scripts/stat_recompute.py` for its supported identities) and the exact manuscript locator. Hand arithmetic is not verification. Conditional inference findings must record which reconstructed fact activated the check; absence of an irrelevant conventional diagnostic is not a finding.

## Ship gate

For contract v0.4, run `python3 "$SKILL_ROOT/scripts/finalize_review.py" <review-dir>` as the only completion path. The finalizer stages a completed run plus generated reports/plans, verifies source integrity and structured evidence, rejects unsafe paths, validates the staged package, replaces each generated artifact atomically, attempts rollback on ordinary failures, and writes the hashed finalization receipt last so an interruption cannot leave a receipt-valid partial package. Use `--check` and the individual generators or validator to diagnose failures, not to bypass the transaction.

Contract v0.3 uses `generate_reports.py --check`, `generate_fix_plan.py --check`, and `validate_review.py`; v0.1/v0.2 use only gates applicable to their archived layouts. Fix every error and do not deliver a nonpassing package as final. Archived v0.3 reports remain structurally valid, but current deterministic generation requires `Issue`, `Relevant text`, `Concern`, `Suggestions`, and `Status`.
