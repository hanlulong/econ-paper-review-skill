# Verification Protocol

Run this protocol after drafting and before presenting any output as final.

## 1. Build the structured verification ledger

For every surviving finding, including minor comments, record:

| Check | Result |
|---|---|
| Evidence exists and matches the ledger | pass/fail |
| Locator resolves | pass/fail |
| Quote is verbatim or typed evidence is exact | pass/fail |
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
| Critical/major feedback has a reader decision, minimum repair, and observable resolution condition | pass/fail |
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

## 4. Verify literature statements

Open every named source. Confirm metadata and the exact claim attributed. Do not rely on search snippets for nuanced support. If only an abstract is available, narrow the attribution accordingly. Store the stable identifier, URL, access date, supported proposition, and a hashed local snapshot or bounded-access note in the external-source ledger. Apply the recorded outbound-search policy before every query.

## 5. Verify artifact consistency

- Every report issue must cite one or more ledger IDs.
- Every active ledger item must appear exactly once in `Detailed Comments`, in unique consecutive importance-rank order.
- Every essential issue must appear as P0 in the fix plan.
- Every P0/P1/P2 item must map to an active finding, and every active finding must appear in the fix plan.
- Dismissed or refuted findings must not appear as recommendations.
- Counts and posture must agree across `run.json`, `report.md`, and `findings.json`.
- Full mode must include a complete `evidence/coverage.md` matrix and satisfy the recorded comment policy without truncating verified issues; enforce a maximum only when the user explicitly requested one.
- Full-mode coverage must record reader clarity, cross-section claim consistency, terminology/variable definitions, data-limitation fairness, review tone, and writing/typographical passes.
- Every table coverage unit must appear exactly once in the separate rendered-table audit. Extraction/render conflicts must be resolved or bounded, and every adverse table state must map to an active finding.
- The analytical audit must contain all seven ledger domains. Every adverse entry or check must map to an active finding; every bounded or inapplicable domain must explain why.
- The detailed-comment section must follow the reader-decision style: critical and major comments end with an observable resolution condition, minor mechanics remain compact, and prohibited repeated boilerplate or malformed acronyms are absent.
- Every synthesis strength, posture rationale, convincingness judgment, principal concern, and upgrade condition must link to existing claim IDs, finding IDs, and/or evidence IDs. Synthesis cannot create unsupported facts or concerns.
- Every claimed arithmetic, statistical, algebraic, simulation, or numerical mismatch must resolve to a computation record with immutable inputs, method, tolerance, output, and artifact hash. A prose description of hand arithmetic is insufficient.
- Every quote-like display must be generated from an evidence record whose representation permits quotation. Reviewer observations, comparisons, computations, and checked absences must remain visibly labeled as such.

## 6. Atomic ship gate

Pass only when every surviving detailed comment passes all applicable checks. A minor comment may use a shorter fairness analysis than a major finding, but its evidence, locator, issue, fix, and verification must still pass.

On failure:

- correct the evidence or wording;
- downgrade the severity;
- convert the claim to an unresolved question; or
- remove it.

Set `run.json.status` to `verification_failed` until the corrected artifacts pass. Never hide a failed check in an appendix while presenting the report as final.

Use one finalization command for the current contract. It must stage the generated files and completed run state, reject symlinked or escaping paths, run every gate, commit the staged artifacts atomically, and write the hash receipt last as the completion marker. A failure must leave the package visibly non-complete and must not partially replace a previously valid report. Do not hand-edit a generated report after finalization; change canonical state and finalize again.
