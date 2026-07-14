# Detailed-Comment House Style

Use the issue-first, status-last presentation in both detailed-comment sections: substance findings in `report.md` and editing findings in `editing-comments.md`. Make the reasoning reader-centered and recognizably useful to an author rather than diagnosis-only feedback. Current author-facing capacities are 100 substantive and 30 editing comments; they never justify shortening, padding, merging unrelated issues, stopping discovery, or omitting a verified finding.

## Contents

- [Field order](#fixed-current-contract-field-order)
- [Reader-decision style and clarity register](#reader-decision-style)
- [Major and design-specific variants](#major-technical-comment)
- [Minor corrections](#minor-correction)
- [Tone, repair, and lint rules](#tone-and-title-rules)

## Fixed current-contract field order

Use these visible fields exactly once and in this order:

1. `Issue`: a one-sentence paper-specific diagnosis matching the ledger.
2. `Relevant text`: the shortest sufficient evidence. Render verbatim passages and normalized source transcriptions as block quotes. Render reviewer observations, figure/table observations, computations, comparisons, and checked absences as unquoted evidence notes. Do not expose internal bracket labels such as `[Reviewer observation]` in the report. Canonical `representation` metadata preserves provenance; never present reviewer prose or an omission as manuscript text.
3. `Concern`: explain, in complete sentences, what the evidence establishes, where it stops, the missing logical step, and the paper-specific consequence. Do not merely rename or repeat the issue.
4. `Suggestions`: give the minimum repair first, explain how it resolves the concern, and say what the proposed check would teach the reader if the broader claim is retained. Label optional strengthening as optional.
5. `Status`: `[Pending]`, always last.

The visible merge is presentational. Keep `fix.what`, `fix.how`, and `fix.resolved_when` distinct in canonical state. Also store `evidence_boundary`, `minimum_repair`, one `display_evidence_id`, and any `related_evidence_ids` or `related_locations`. Multi-location conflicts must expose the other checked locations in a compact sentence. Do not copy the same recommendation into multiple fields.

Leave a blank line after the block quote. This is a rendering requirement, not cosmetic: without it, CommonMark may absorb the following bold label into the quotation.

For a claimed contradiction, retain the exact operative words on both sides—especially direction, rounding language, qualifiers, domain, timing, units, and benchmark. Do not replace `rounded down` with `rounded`, or make an equivalent compression, when the omitted word changes the diagnosis. If exact wording defeats the contradiction, recast only the narrower concern that remains or delete the comment.

## Reader-decision style

Write each substantive comment to answer five questions:

1. What exact decision or interpretation does a reader need to make?
2. What does the current evidence establish, and where does it stop?
3. Which paper-specific claim, estimate, proposition, counterfactual, or interpretation is affected?
4. What is the minimum sufficient repair, and what single decisive check is needed only if the broader claim remains?
5. What observable revision would close the comment?

Prefer the affirmative boundary: `The current evidence establishes X; it does not yet establish Y.` Credit an existing safeguard only when it materially narrows the consequence or repair. Do not invent an author motive or hypothetical defense.

Make every comment self-contained. Do not assume the author has read the ledger, another comment, or an audit appendix. Walk through the reasoning in the order a reader encounters it: what the paper says, what follows from that evidence, which step does not follow, why that changes the interpretation, and how the proposed revision closes the gap. Critical and major comments normally need three to six clear sentences in `Concern` and enough explanation in `Suggestions` to make the repair executable; minor editing comments may remain compact. These are guides to completeness, not word caps or a template to pad. When a recommendation calls for a diagnostic, explain what it tests and how the plausible outcomes would change the paper's claim. The author should never have to infer why a requested exercise matters.

Order comments by reader priority, not by where they happen to appear in the manuscript. Assign `importance_rank` by severity first (`critical`, `major`, `minor`, `info`), then decision role, the consequence for the paper, and the value of a feasible repair. Use manuscript position only to break a genuine tie. A critical finding is a verified issue that can invalidate or make uninterpretable a central claim and could plausibly drive rejection; classify it as potentially dispositive and reviewer P0. This is a substantive judgment, not a keyword, occurrence-count, or quota rule. Both Markdown reports and the viewer must preserve this ordering by default. The author's own P0/P1/P2 work choices remain separate.

Write like a thoughtful human referee speaking to an economist. Use natural transitions, varied cadence, and ordinary words where they preserve precision. Do not expose workflow language such as `canonical record`, `verification passed`, `coverage unit`, `finding ID`, `audit gate`, or `the checked manuscript` in author-facing prose. Avoid telegraphic noun strings, canned AI signposting, and identical sentence patterns across comments. A technically correct comment still fails the style check if the author must reverse-engineer the reasoning.

## Clarity register — non-specialist economist test

Write for a competent economist who does not work in the paper's method or setting. Preserve the technical content, but make the logic recoverable in one reading:

- Begin `Concern` with the observed gap or concrete consequence, not a bare test name, estimator name, acronym, or meta-instruction. Delete openings such as `The reader needs to`, `A reader should`, `This matters because`, or `The concern is`.
- Expand a non-obvious acronym introduced by the reviewer at its first use in each comment, then use the acronym consistently. If the quoted manuscript passage contains the acronym, gloss it in the author-facing prose before relying on it. Do not manufacture expansions for mathematical symbols, exhibit labels, standard units, or an acronym that appears only inside the verbatim quote.
- Give a short functional gloss for a load-bearing specialist term when an economist outside the subfield may not know what inference it controls. Explain what a named test or estimator checks before recommending it. Do not turn the comment into a glossary, and do not force a one-method-per-sentence rule when a comparison among methods is itself the issue.
- State the consequence in paper-specific terms: name the estimate, sign, proposition, counterfactual, exhibit, population, or interpretation that could change, or say what a reader could wrongly conclude. Avoid stopping at abstractions such as `threatens identification` or `changes the estimand`.
- State each repair once. Merge strategic direction and implementation into one sequence; do not concatenate two versions of the same recommendation. Explain why the change is sufficient and, when a diagnostic is requested, how each possible result would affect the claim.

The validator enforces only high-signal surface failures: prohibited meta-scaffolding at the start of `Concern` or `Suggestions`, malformed acronym capitalization, and near-duplicate sentences within `Suggestions`. Acronym and jargon adequacy remains a semantic verification pass because a universal hard-coded dictionary would misclassify field-standard vocabulary, manuscript-defined terms, symbols, and quoted text across empirical and theoretical papers.

## Major technical comment

The fixed fields provide scanability, not an excuse for compressed reasoning. Use cohesive paragraphs inside `Concern` and `Suggestions` whenever the issue needs explanation. State the affirmative evidence boundary, show the missing link, name the affected object, give the minimum repair, and—only if the broader claim remains—one decisive check. The labels are mandatory and exempt from repeated-label lint. Vary paragraph count, openings, and cadence; do not repeat any nontechnical sentence across three comments. Keep resolution conditions as paper-specific observables in the ledger, not report boilerplate.

## Theory, structural, and macro variants

For theory, name the assumption, definition, domain, proof step, equilibrium object, and verbal claim that must share the same scope. Ask for the smallest missing lemma, domain restriction, corrected statement, or counterexample exclusion.

For structural or quantitative work, distinguish identified, calibrated, assumed, validated, and extrapolated objects. Lead with the minimum parameter-to-moment mapping or diagnostic; request one targeted sensitivity only when it can change the counterfactual or welfare ranking.

For macro work, name the aggregate object, accounting or equilibrium relation, shock or policy normalization, units, horizon, information set, and transition or welfare claim that the concern affects. Distinguish accounting decompositions, identified responses, calibrated mechanisms, and model counterfactuals rather than treating each as causal evidence.

## Minor correction

For an objective local reporting, citation, notation, or copyediting issue, use the same fields in one compact paragraph and give the direct correction or exact replacement. Do not add a defense, rebuttal, robustness battery, or resolution heading to a mechanical correction.

Editing-channel comments use this compact correction form by default. If an apparent editing problem changes the scientific interpretation or obscures a load-bearing claim, route it to substance and use the substantive style instead.

## Tone and title rules

- Describe the manuscript object, not the authors' competence or intent.
- Use consequence-centered titles; avoid `invalid`, `incorrect`, `severe`, `fatal`, `obvious`, and `fundamental` unless the state is formally proven.
- Do not begin with generic boilerplate such as `As written`, `There seems to be an issue`, or `The document would benefit from`.
- Avoid courtroom phrases such as `the strongest author-side defense` and `supports that defense only to this extent`.
- Preserve uppercase acronyms, proper names, exhibit labels, and mathematical symbols. Never create prose by lowercasing a title.
- Delimit reviewer-authored mathematics explicitly, for example `$R_b$` and `$b_j$`. Do not alter a verified source span merely to add delimiters; keep its evidence representation and let the renderer handle unambiguous legacy notation.
- Reserve venue-tier language for posture calibration and an explicitly requested `editing-comments.md` journal-fit addendum; do not insert it into detailed comments.
- Vary length and cadence by severity; do not force every comment through one paragraph mold.
- Prefer collegial, direct sentences over audit narration. The report should sound like advice from an engaged referee, not output from a validation engine.

## Repair and scanability rules

- Put the primary repair before optional strengthening.
- If a repair contains more than three actions, separate minimum repair, decisive check, and optional strengthening.
- Require a resolution condition for every critical or major comment.
- Keep record inventories, derivations, and search logs in evidence artifacts; cite representative examples in the comment.
- Quote the shortest passage that exposes the issue, normally one to three sentences or one equation with its interpretation.
- Use a no-new-data wording or disclosure fix before analysis when it fully resolves claim scope.

## Lint phrases

Remove these repeated constructions from detailed feedback unless they are inside a manuscript quote:

- `As written,`
- `A careful reader cannot tell whether the stated claim is supported at the precision and scope presented.`
- `A careful reader may misread the object, unit, comparison, or evidentiary strength at this location.`
- `The strongest author-side defense is that`
- `The checked manuscript supports that defense only to this extent`
- `A proportionate repair is to`
- `leading-field verification requires`
- `the authors fail to`
- `the authors ignore`

Also reject malformed leading acronyms such as `vAR`, `iRF`, `hPI`, `sVAR`, and `fOMC`. Re-read the full detailed-comment section for repeated openings and nontechnical sentences before shipping.

In current comments, reject `Concern` openings that merely announce concern and `Suggestions` openings such as `I suggest`, `I recommend`, `To address this issue`, or `A possible fix is`. Reject repeated recommendation sentences; distinct tests, boundaries, and implementation steps are not duplicates.
