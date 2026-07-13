# Detailed-Comment House Style

Use the v0.3/v0.4 issue-first, status-last presentation in both detailed-comment sections: substance findings in `report.md` and writing findings in `writing-report.md`. Existing v0.1 and v0.2 reviews retain their legacy formats. Make the reasoning reader-centered and recognizably useful to an author rather than diagnosis-only feedback.

## Fixed current-contract field order

Use these visible fields exactly once and in this order:

1. `Issue`: a one-sentence paper-specific diagnosis matching the ledger.
2. `Relevant text`: the shortest sufficient verbatim passage. For a render transcription, figure/table observation, computation, reviewer comparison, or checked absence, prefix the block with `[Rendered transcription]`, `[Figure observation]`, `[Table observation]`, `[Computation]`, `[Reviewer comparison]`, or `[Checked absence]`. Never present reviewer prose or an omission as manuscript text.
3. `Concern`: what the evidence establishes, where it stops, and the paper-specific consequence. Do not repeat the issue.
4. `Suggestions`: the minimum repair first, stated directly. Add one decisive check only if the broader claim is retained; label optional strengthening as optional.
5. `Status`: `[Pending]`, always last.

The visible merge is presentational. Keep `fix.what`, `fix.how`, and `fix.resolved_when` distinct in canonical state. Also store `evidence_boundary`, `minimum_repair`, one `display_evidence_id`, and any `related_evidence_ids` or `related_locations`. Multi-location conflicts must expose the other checked locations in a compact sentence. Do not copy the same recommendation into multiple fields.

Leave a blank line after the block quote. This is a rendering requirement, not cosmetic: without it, CommonMark may absorb the following bold label into the quotation.

## Reader-decision style

Write each substantive comment to answer five questions:

1. What exact decision or interpretation does a reader need to make?
2. What does the current evidence establish, and where does it stop?
3. Which paper-specific claim, estimate, proposition, counterfactual, or interpretation is affected?
4. What is the minimum sufficient repair, and what single decisive check is needed only if the broader claim remains?
5. What observable revision would close the comment?

Prefer the affirmative boundary: `The current evidence establishes X; it does not yet establish Y.` Credit an existing safeguard only when it materially narrows the consequence or repair. Do not invent an author motive or hypothetical defense.

## Clarity register — non-specialist economist test

Write for a competent economist who does not work in the paper's method or setting. Preserve the technical content, but make the logic recoverable in one reading:

- Begin `Concern` with the observed gap or concrete consequence, not a bare test name, estimator name, acronym, or meta-instruction. Delete openings such as `The reader needs to`, `A reader should`, `This matters because`, or `The concern is`.
- Expand a non-obvious acronym introduced by the reviewer at its first use in each comment, then use the acronym consistently. If the quoted manuscript passage contains the acronym, gloss it in the author-facing prose before relying on it. Do not manufacture expansions for mathematical symbols, exhibit labels, standard units, or an acronym that appears only inside the verbatim quote.
- Give a short functional gloss for a load-bearing specialist term when an economist outside the subfield may not know what inference it controls. Explain what a named test or estimator checks before recommending it. Do not turn the comment into a glossary, and do not force a one-method-per-sentence rule when a comparison among methods is itself the issue.
- State the consequence in paper-specific terms: name the estimate, sign, proposition, counterfactual, exhibit, population, or interpretation that could change, or say what a reader could wrongly conclude. Avoid stopping at abstractions such as `threatens identification` or `changes the estimand`.
- State each repair once. Merge strategic direction and implementation into one sequence; do not concatenate two versions of the same recommendation.

The validator enforces only high-signal surface failures: prohibited meta-scaffolding at the start of `Concern` or `Suggestions`, malformed acronym capitalization, and near-duplicate sentences within `Suggestions`. Acronym and jargon adequacy remains a semantic verification pass because a universal hard-coded dictionary would misclassify field-standard vocabulary, manuscript-defined terms, symbols, and quoted text across empirical and theoretical papers.

## Major technical comment

The fixed fields provide scanability. Within `Concern` and `Suggestions`, use one to three cohesive paragraphs only when the issue needs more explanation:

```markdown
**Concern**: The paper establishes [X], but not [Y], because [specific gap, contradiction, or unreported sensitivity]. [Affected result, proposition, counterfactual, or interpretation.]

**Suggestions**: [Minimum repair.] If the broader claim is retained, [one decisive analysis, derivation, or validation check]. [Optional strengthening, only if useful.]

**Status**: [Pending]
```

The structural labels are mandatory and therefore exempt from repeated-label lint. Vary paragraph count, openings, and sentence cadence inside the fields. Do not repeat any nontechnical sentence across three comments. Resolution conditions remain paper-specific observables in the ledger rather than generic report boilerplate.

## Theory, structural, and macro variants

For theory, name the assumption, definition, domain, proof step, equilibrium object, and verbal claim that must share the same scope. Ask for the smallest missing lemma, domain restriction, corrected statement, or counterexample exclusion.

For structural or quantitative work, distinguish identified, calibrated, assumed, validated, and extrapolated objects. Lead with the minimum parameter-to-moment mapping or diagnostic; request one targeted sensitivity only when it can change the counterfactual or welfare ranking.

For macro work, name the aggregate object, accounting or equilibrium relation, shock or policy normalization, units, horizon, information set, and transition or welfare claim that the concern affects. Distinguish accounting decompositions, identified responses, calibrated mechanisms, and model counterfactuals rather than treating each as causal evidence.

## Minor correction

For an objective local reporting, citation, notation, or copyediting issue, write one compact paragraph:

```markdown
**Issue**: [Exact local error.]

**Relevant text**:
> [Exact source text.]

**Concern**: [Why the error affects correctness, consistency, traceability, or presentation.]

**Suggestions**: [Direct correction.] Replacement: "[text]".

**Status**: [Pending]
```

Do not add a defense, rebuttal, robustness battery, or resolution heading to a mechanical correction.

Writing-channel comments use this compact correction form by default. If an apparent writing problem changes the scientific interpretation or obscures a load-bearing claim, route it to substance and use the substantive style instead.

## Tone and title rules

- Describe the manuscript object, not the authors' competence or intent.
- Use consequence-centered titles; avoid `invalid`, `incorrect`, `severe`, `fatal`, `obvious`, and `fundamental` unless the state is formally proven.
- Do not begin with generic boilerplate such as `As written`, `There seems to be an issue`, or `The document would benefit from`.
- Avoid courtroom phrases such as `the strongest author-side defense` and `supports that defense only to this extent`.
- Preserve uppercase acronyms, proper names, exhibit labels, and mathematical symbols. Never create prose by lowercasing a title.
- Reserve venue-tier language for posture calibration and an explicitly requested `writing-report.md` journal-fit addendum; do not insert it into detailed comments.
- Vary length and cadence by severity; do not force every comment through one paragraph mold.

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
