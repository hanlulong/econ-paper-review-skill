# Verification Protocol

Run this protocol after drafting and before presenting any output as final.

## Contents

- [Structured finding verification](#1-build-the-structured-verification-ledger)
- [Negative and directional claims](#2-verify-negative-claims)
- [Numerical recomputation](#numerical-recomputation)
- [Literature verification](#4-verify-literature-statements)
- [Artifact consistency](#5-verify-artifact-consistency)
- [Atomic ship gate](#6-atomic-ship-gate)

## 1. Build the structured verification ledger

For every surviving finding, including minor comments, record:

| Check | Result |
|---|---|
| Evidence exists and matches the ledger | pass/fail |
| Locator resolves | pass/fail |
| Quote is verbatim or typed evidence is exact | pass/fail |
| Any contradiction preserves the exact operative words and qualifiers on both sides | pass/fail/not applicable |
| Omission search scope is explicit | pass/fail/not applicable |
| Main text, notes, appendix, and relevant exhibits checked | pass/fail |
| Paper's estimand/design variant is represented correctly | pass/fail |
| Direction, sign, timing, unit, and magnitude are correct | pass/fail |
| Strongest author reply or proportionate fairness check considered | pass/fail |
| Suggested fix addresses the demonstrated threat | pass/fail |
| Reader inference and strongest supported claim are stated correctly | pass/fail |
| Load-bearing terms, symbols, units, domains, and variants are cleanly defined | pass/fail/not applicable |
| Data limitation classified; inherent and properly bounded limitations removed | pass/fail/not applicable |
| Feedback tone is neutral, constructive, and proportionate | pass/fail |
| Severity follows from paper-specific consequence | pass/fail |
| Named external sources verified live | pass/fail/not applicable |
| Report, ledger, and fix plan map consistently | pass/fail |
| Every table finding verified against the rendered page, not extraction alone | pass/fail/not applicable |
| All seven analytical-ledger domains present; adverse and bounded states resolved | pass/fail |
| Every headline claim has a source-specific economic link, object-role map, alternative channel or ordering, and strongest supported contribution | pass/fail |
| Every load-bearing comparison records all differential content before its target object, including intervention prompts, tasks, routing, and timing when applicable | pass/fail/not applicable |
| Cross-result relationships, promised or measured evidence objects, magnitude context, and sample/domain transport are completely reconciled | pass/fail/not applicable |
| Every load-bearing diagnostic is classified by evidentiary role; its shared assumptions, limits, and assessment-changing outcomes are stated without treating nonrejection as proof | pass/fail/not applicable |
| Any activated research-integrity or data-governance concern is source-triggered, current-rule verified when rule-specific, non-accusatory, and limited to the least intrusive disclosure or scope repair | pass/fail/not applicable |
| Any replication conclusion distinguishes static traceability, authorized execution, reproduced output, scientific correctness, package failure, result mismatch, and reviewer-side boundary | pass/fail/not applicable |
| Figure rows are bound to immutable rendered assets whose visible identity matches the declared figure label and PDF page | pass/fail/not applicable |
| Critical/major feedback has a reader decision, minimum repair, and observable resolution condition | pass/fail |
| Alternative repair paths are distinguished from cumulative requirements, and each requested analysis has at least one plausible result that changes the claim or assessment | pass/fail/not applicable |
| Detailed-comment boilerplate and acronym lints pass | pass/fail |

Store the canonical results in `review/evidence/verification.json` and generate `review/evidence/verification.md` from that state. Each finding record must identify each evidence item, its evidence representation, the source anchor or computation/external-source record that verifies it, the result, and any boundary. Prose that says a check passed without resolving those links is not verification.

Use the representation-specific rule:

- `verbatim`: compare the exact normalized span with its source anchor;
- `normalized_transcription`: compare the render-visible content and record the permitted normalization;
- `composite_comparison`: verify every component anchor and label the displayed text as a comparison, never a single quotation;
- `reviewer_observation`: resolve to the rendered exhibit or inspected code object and label it as observation;
- `checked_absence`: preserve the searched scope and synonyms;
- `computed_result`: resolve to an immutable computation record, inputs, tool, tolerance, result artifact, and hash.

No free-standing `pass` value can override a failed or missing evidence link.

For a derivation-based finding, preserve enough source and reviewer work for another economist to audit the step: the rendered equation or exact source span plus either a reproducible derivation/computation artifact or a concise corrected derivative or algebraic step. If extraction damage or missing assumptions prevent that check, mark the finding bounded rather than presenting a confirmed error.

For every data-related candidate, record whether it is avoidable handling, an inherent limit paired with claim overreach, an inherent and properly bounded limit, or unclear. Remove the third category from active findings. For unavoidable limits paired with overclaim, verify that the requested remedy narrows or clarifies the claim rather than demands unavailable data.

## 2. Verify negative claims

For “the paper does not…” or “the authors fail to…” claims:

1. Search synonyms and notation variants.
2. Inspect the main methods/results sections, footnotes, table and figure notes, and relevant appendix sections.
3. Inspect supplied code or documentation when the claim concerns implementation and permission allows.
4. Record the checked scope in an `absence_scope` evidence item.

If the search is incomplete, replace the claim with a bounded disclosure question or remove it.

## 3. Rebuttal-proof directional claims

Check both sides of any distinction: treatment/control, inflow/outflow, tightening/easing, pre/post, high/low, extensive/intensive, partial/general equilibrium, men/women, or subgroup contrasts. Verify denominators, normalizations, and base periods.

For subgroup, regime, type, or case comparisons, verify whether assignment is fixed, predetermined, selected, contemporaneous, post-treatment, or equilibrium-determined. Check whether units can move across groups and whether the reported comparison combines response with reclassification.

## Numerical recomputation

Do not diagnose a numerical error from mental or hand arithmetic. For identities supported by `scripts/stat_recompute.py`, prepare a JSON check with the exact source locator, run the script, and preserve its input and output in the computation ledger. For other identities, use an auditable computation tool or mark the check bounded. Reconcile source, unit, rounding, transformation, and sample before admitting a machine-reported mismatch.

For `grim_mean`, supply the reported mean, integer sample size, and displayed precision, but omit `reported`: the script tests compatibility with an integer-valued total. Neither `match` nor `mismatch` establishes a manuscript error without reconciling rounding conventions, missingness, weights, non-integer outcomes, and the exact analysis sample.

## 4. Verify literature statements

Open every named source. Confirm metadata and the exact claim attributed. Do not rely on search snippets for nuanced support. If only an abstract is available, narrow the attribution accordingly. Store the stable identifier, URL, access date, supported proposition, and a hashed local snapshot or bounded-access note in the external-source ledger. Apply the recorded outbound-search policy before every query.

## 5. Verify artifact consistency

- Every report issue must cite one or more ledger IDs.
- Every active ledger item must appear exactly once in `Detailed Comments`, in unique consecutive importance-rank order; that order is globally critical, major, minor, then informational, with decision role used only within a severity tier.
- Every essential issue must appear as P0 in the fix plan.
- Every critical issue must be potentially dispositive, essential, and P0; no lower-severity item may precede it within P0 or serve as a lower-severity prerequisite that breaks the global order.
- Every P0/P1/P2 item must map to an active finding, and every active finding must appear in the fix plan.
- Dismissed or refuted findings must not appear as recommendations.
- Counts and posture must agree across `run.json`, `report.md`, and `findings.json`.
- Full mode must include a complete `evidence/coverage.md` matrix and satisfy the recorded comment policy without truncating verified issues. Author-facing channel capacities never authorize stopping discovery or omitting an active finding; unresolved overflow pauses completion.
- Full-mode coverage must record reader clarity, cross-section claim consistency, terminology/variable definitions, data-limitation fairness, review tone, and writing/typographical passes.
- Every table coverage unit must appear exactly once in the separate rendered-table audit. Extraction/render conflicts must be resolved or bounded, and every adverse table state must map to an active finding.
- The analytical audit must contain all seven ledger domains. In v0.2, every evidence locator must bind through `record_ref` to the same canonical record cited directly by its entry, and its source, locator, and representation-appropriate content must reconcile to that record. Every adverse entry or check must map to an active finding; every bounded entry or check propagates to a bounded domain and reciprocal coverage dimension; every bounded or inapplicable domain must explain why.
- New claims-audit v0.2 packages must cover every headline claim in the economic-link ledger and include reciprocal coverage rows for the economic argument, comparison content, cross-result coherence, evidence-object completeness, magnitude plausibility, and population/domain transport. Every adverse state maps to an active finding; a not-applicable state names the absent paper object.
- For each load-bearing evidence object, verify that the prose distinguishes direct evidence, falsification or implication checks, sensitivity, targeted fit, independent validation, numerical diagnostics, and external benchmarks as applicable. A clean diagnostic cannot be described as proving a maintained assumption merely because it fails to reject, and several checks that share the same failure mode cannot be presented as independent triangulation.
- An experimental treatment is the full arm-differential experience through each outcome. Verify the order of prompts, required responses, routing, checks, delays, and platform features before accepting a component-level attribution. Apply the same compound-comparison rule to models, counterfactuals, robustness comparisons, and theory cases.
- Every figure in claims-audit-era output must map to one coverage unit and one or more hash-verified rendered assets. At least one inspected asset must visibly identify the declared figure on a declared source page. A crop filename, ordinal position, caption-only inference, or existence check is not semantic verification.
- The detailed-comment section must follow the reader-decision style: every comment is self-contained, explains the evidence-to-consequence chain in plain language, and makes the repair understandable without consulting a ledger. Critical and major comments end with an observable resolution condition, minor mechanics remain proportionate, and machine-like audit narration, compressed shorthand, repeated boilerplate, and malformed acronyms are absent.
- Every synthesis strength, posture rationale, convincingness judgment, principal concern, and upgrade condition must link to existing claim IDs, finding IDs, and/or evidence IDs. Synthesis cannot create unsupported facts or concerns.
- Every claimed arithmetic, statistical, algebraic, simulation, or numerical mismatch must resolve to a computation record with immutable inputs, method, tolerance, output, and artifact hash. Computation-to-finding links are reciprocal. A clean audit-only computation is allowed only under computation schema v0.2 when its reciprocal `audit_links` name the analytical or magnitude row that canonically cites it. A prose description of hand arithmetic is insufficient.
- Every quote-like display must be generated from an evidence record whose representation permits quotation. Reviewer observations, comparisons, computations, and checked absences render as unquoted evidence notes; their typed representation remains available in canonical state without an author-facing bracket label.
- Every requested additional analysis must have an assessment-changing branch. When claim narrowing, reframing, analysis, new evidence, or redesign are alternative ways to close one finding, the report and fix plan must identify the minimum path and must not require all alternatives cumulatively.
- Every activated research-integrity or data-governance finding must resolve to a source fact and scoped absence search. Never infer misconduct or illegality from missing prose; verify venue-, registry-, provider-, or jurisdiction-specific requirements from current official sources or mark specific compliance bounded.
- Every code or replication finding must record whether it arose from static inspection or authorized execution, the execution boundary actually used, data and environment availability, and the command/output or source anchors supporting it. A successful run does not certify scientific correctness, and a failed run must be reconciled against environment, data, dependency, resource, randomness, and reviewer-side limits before it becomes a package defect.

## 6. Atomic ship gate

Pass only when every surviving detailed comment passes all applicable checks. A minor comment may use a shorter fairness analysis than a major finding, but its evidence, locator, issue, fix, and verification must still pass.

On failure:

- correct the evidence or wording;
- downgrade the severity;
- convert the claim to an unresolved question; or
- remove it.

Set `run.json.status` to `verification_failed` until the corrected artifacts pass. Never hide a failed check in an appendix while presenting the report as final.

Use one finalization command for the current contract. It must stage the generated files, deterministic all-in-one PDF, and completed run state; reject symlinked or escaping paths; run every gate; replace each generated artifact atomically; attempt rollback on ordinary failures; and write the hash receipt last so an interruption cannot leave a receipt-valid partial package. Verify that a second PDF render is byte-identical, that all manifest documents appear, and that representative rendered pages contain no clipping, overlap, missing glyphs, or broken quotes or tables. Do not claim filesystem-wide multi-file atomicity. A caught failure must restore the prior generated package; a process kill or power loss may require rerunning finalization, but cannot leave a valid receipt for mixed bytes. Do not hand-edit a generated report after finalization; change canonical state and finalize again.
