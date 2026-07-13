# Reader-Centered Claim Audit

Use this protocol in every full review and whenever the user asks whether a paper is clear, internally consistent, convincing, or appropriately calibrated. The audit asks what a careful economics reader would understand after one pass. It is not a copy-editing checklist and does not reward a preferred style.

## Contents

- [Reader and cross-section claim maps](#1-build-the-reader-map)
- [Terminology and variable definitions](#3-build-the-terminology-and-variable-map)
- [Claim calibration and convincingness](#4-calibrate-the-claim-strength)
- [Data-limit fairness](#6-apply-the-data-limitation-fairness-gate)
- [Tone and writing passes](#7-audit-author-facing-tone)
- [Admission and verification](#9-admission-and-verification-rules)

## 1. Build the reader map

For the title, abstract, introduction, each substantive section, and conclusion, record:

- the main takeaway a careful reader is expected to retain;
- the economic object, population, comparison or benchmark, time horizon, and uncertainty needed to interpret it;
- any term, variable, mechanism, or transition that is not understandable at first use;
- the evidence or formal result that is supposed to make the takeaway convincing;
- any question a reasonable reader must answer by searching elsewhere in the paper.

Mark `clear` when the passage is understandable and supported. Do not manufacture a comment merely because a sentence could be written differently.

## 2. Build the cross-section claim ledger

Trace every headline claim through the abstract, introduction, methods or model, results, robustness or extensions, and conclusion. For each occurrence, reconcile:

- object or variable measured;
- population, sample, and subgroup labels;
- treatment, shock, comparison, or counterfactual;
- sign, magnitude, unit, denominator, baseline, and horizon;
- uncertainty and evidentiary threshold;
- causal, descriptive, mechanism, welfare, policy, robustness, or contribution status;
- qualifiers, maintained assumptions, and scope limitations.

A later summary may be shorter, but it may not silently strengthen the claim, change the object, broaden the population, suppress a reversal, or drop a load-bearing qualifier. Merge repeated wording problems when one claim-level repair resolves them; keep distinct contradictions when they require different factual corrections.

## 3. Build the terminology and variable map

Inventory every load-bearing economic term, constructed measure, acronym, symbol, index, parameter, shock, group label, transformation, and normalization. Check:

- whether it is defined at or before first substantive use;
- whether the definition states its unit, denominator, baseline, domain, indices, timing, aggregation, and sign convention when relevant;
- whether prose, equations, tables, figures, notes, and appendices use the same label for the same object;
- whether one label is overloaded across different objects or one object receives unexplained alternative labels;
- whether every displayed equation defines new symbols and makes dimensions and index ranges recoverable;
- whether cumulative, per-period, level, log, percentage, percentage-point, elasticity, normalized, and standardized objects are distinguished;
- whether abbreviations and group labels remain stable.

Do not require definitions of universally standard notation when the local meaning is unambiguous. Create a finding only when an absent, remote, inconsistent, or overloaded definition creates a plausible interpretive error or material search cost.

Record the manuscript coverage units checked for terminology and variables, including numbered equations and definition-bearing exhibit notes. Mark the inventory complete within the declared assessment boundary. An undefined, inconsistent, or overloaded load-bearing item cannot remain as an unmapped adverse state: link it to a verified finding. A remotely defined item needs a finding only when the search cost is material.

Make this inventory auditable rather than retrospective. For every PDF source, reconcile the exact `ingestion.json.symbols` inventory and assign each candidate one disposition: mapped load-bearing term, standard unambiguous notation, prose noise, extraction artifact, or non-load-bearing notation. Retain the candidate's exact codepoints and all block-derived occurrence anchors. For structured Markdown or TeX, declare the candidate inventory produced by the source pass; if no dependable candidate pass can be completed, use a bounded manual scope with the reason instead of claiming completeness. Every mapped term records a precise first-use anchor and, when defined, at least one definition anchor. An undefined mapped term records a source-wide checked-absence anchor. Standard notation still records its first occurrence and a paper-specific reason; “standard” is not a catch-all for unexamined symbols.

The structured claim ledger uses the same typed evidence-reference vocabulary as the writing audit. `direct_support` resolves to a precise anchor, passed finding evidence, computation, or verified external support record; `checked_absence` resolves to a source-wide scope anchor or passed absence-scope evidence. A clean reader or term state cannot be certified by free text, an unrelated anchor, reviewer observation, or evidence attached to a dismissed, resolved, pending, failed, or bounded finding.

## 4. Calibrate the claim strength

Use the strongest level supported by the paper, not the strongest available verb:

1. **Description:** `documents`, `measures`, `is associated with`, or `moves with`.
2. **Design-supported effect:** `estimates the effect of` only when the design identifies that effect for the stated population and margin.
3. **Mechanism evidence:** `is consistent with` unless the paper distinguishes the mechanism from credible alternatives or performs a valid mediation/decomposition.
4. **Welfare or incidence:** require the relevant utility, prices, quantities, ownership, transfers, equilibrium responses, or accounting objects.
5. **Policy prescription:** require that the evidence or model evaluates the policy margin, target population, and material tradeoffs.
6. **Robustness or generality:** state exactly which conclusion survives which alternative; a stable sign is not automatically stable magnitude, precision, mechanism, welfare, or external validity.

Flag an overclaim only when the wording is stronger than the maximum supported level. State the strongest wording the evidence does support.

## 5. Test whether the argument is convincing

For every important inference, verify that a reader can see the complete chain:

`claim -> evidence or result -> warrant connecting evidence to claim -> uncertainty or maintained assumptions -> bounded takeaway`.

For headline contributions, expand this into the economic chain required by [argument-evidence-audit.md](argument-evidence-audit.md): identify the role of each measured or modeled intermediate object, the decision or equilibrium endpoint, and the strongest bypass channel or reverse ordering. A reader may understand the prose while remaining unconvinced that an intermediate outcome is necessary, causal, or economically consequential. Do not repair that gap by demanding a formal model automatically; first state the missing warrant and the strongest narrower contribution.

Create a finding when a missing or contradictory link changes what the reader is entitled to conclude. Ask for intuition only when the formal or empirical step is otherwise hard to evaluate. Do not demand more discussion when the chain is already clear.

In the report, answer the reader-level question directly: identify which parts of the central argument are convincing, which links remain provisional or unsupported, and the smallest changes that would make the argument persuasive. Distinguish a technically valid but poorly explained step from a well-explained step that lacks evidentiary support.

Also reconcile results the paper asks the reader to connect. A difference is not an inconsistency until comparison, population or domain, horizon, estimand, support, and ordering have been checked. Record explained differences as checked-clean rather than manufacturing a concern.

## 6. Apply the data-limitation fairness gate

Classify every data, measurement, linkage, sample, or coverage candidate before retaining it:

- `avoidable_handling`: a feasible construction, validation, cleaning, weighting, uncertainty, documentation, or reproducibility step is missing or inconsistent;
- `inherent_but_claim_exceeds`: the limitation is unavoidable with the available data, but a claim extends beyond the observed object or population;
- `inherent_and_properly_bounded`: the limitation is unavoidable, disclosed, and the claims respect it;
- `unclear`: the materials do not establish whether the limitation is inherent or how it affects the claim;
- `not_data_related`.

`inherent_and_properly_bounded` is not an active criticism. Record it as a boundary or strength and remove the candidate. For `inherent_but_claim_exceeds`, criticize the claim scope and propose narrowing or clarification; do not demand unavailable data. For `avoidable_handling`, request only a feasible, decision-relevant repair. Use `unclear` as a bounded disclosure question until the paper or supplied materials resolve it.

Do not recommend new data merely because ideal data would be better. Recommend new data only when the central claim cannot be supported otherwise, and present claim narrowing or retargeting as the alternative.

## 7. Audit author-facing tone

Write feedback so a reasonable author can recognize the evidence and act on it:

- describe the text, result, or reader inference before judging it;
- distinguish `the paper does not establish` from claims about author effort, intent, or competence;
- acknowledge a limitation or caveat the paper already states before explaining what remains unresolved;
- use calibrated modal language: `may` for a live possibility, `can` for a demonstrated mechanism, and direct language for verified contradictions;
- avoid ridicule, motive attribution, advocacy, inflated adjectives, and adversarial labels such as `obvious`, `fatal`, `careless`, or `invalid` unless the precise technical meaning is essential and established;
- match the request to the issue: correct, clarify, narrow, validate, reorganize, or redesign;
- explain the reader or publication payoff rather than merely ordering a change.

The issue title should name the observable mismatch, not accuse the author. Prefer `The abstract describes the normalization as the treatment` to `The abstract is misleading`.

## 8. Run a dedicated writing and typographical pass

Keep this pass separate from the methods judgment. Use applicable economics-writing guidance to check:

- whether the question, benchmark, principal finding, and contribution are intelligible to an economist outside the narrow subfield;
- whether paragraphs lead with their point and each paragraph performs one identifiable job;
- whether key terms, acronyms, variables, and group labels are defined at first use and used consistently;
- whether transitions explain why the next section or exercise is needed;
- whether magnitudes name the unit, denominator, baseline, horizon, and uncertainty;
- whether tables and figures are self-contained and match the surrounding prose;
- whether repetition, throat-clearing, overloaded sentences, vague pronouns, or unnecessary taxonomy obstruct the argument;
- whether equations, table cells, internal cross-references, spelling, punctuation, notation, and typographical details are correct.

Report a typo or copy-edit only when the correction is objectively identifiable. Aggregate repeated mechanical errors by type and list their locations; do not inflate the comment count by treating every occurrence as a separate finding.

## 9. Admission and verification rules

Retain a clarity, consistency, or tone finding only when:

- exact text or exhibit evidence is recorded;
- the likely reader inference is stated;
- the manuscript's other occurrences and qualifiers were checked;
- the strongest supported replacement claim or concrete clarification is supplied;
- the fix improves comprehension, evidentiary calibration, or credibility rather than enforcing taste.

For current full reviews, exact quotations and source-derived locators in the claim and writing ledgers must reconcile to the canonical source anchor. Normalized transcription may reconcile quote marks, Unicode composition, and whitespace for comparison; it must not apply compatibility normalization, fold letter case, or change words, symbols, signs, or meaning. Claim-family, reader-row, term-row, writing-row, evidence, and coverage links are reciprocal, so removing or dismissing one side cannot leave a falsely clean certification.

Before shipping, run a cold-reader pass on the report itself. Check that its summary, severity, descriptions, and fixes do not overclaim the evidence, treat inherent data limits as faults, or use a harsher tone than the manuscript evidence warrants.
