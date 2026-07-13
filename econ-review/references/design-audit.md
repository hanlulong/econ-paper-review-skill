# Design-Agnostic Audit

## Contents

- [Universal questions](#universal-questions)
- [Claim-to-burden map](#claim-to-burden-map)
- [Stable parent burden IDs](#stable-parent-burden-ids)
- [Audit each activated burden](#audit-each-activated-burden)
- [Conditional presets](#conditional-presets)
- [Clarity and finding threshold](#clarity-and-misleading-expression)

Start from the paper's claims and evidentiary objects, not its advertised method or a single paper-family label. A paper can activate several burdens at once: a descriptive fact may feed a causal interpretation, a theorem may discipline an estimated model, or a simulation may carry a policy claim. Audit that composition directly. Family, design, and coverage-branch tags are descriptive routing aids and examples, never mutually exclusive templates or scope authority.

## Universal questions

1. What exact economic object is the paper trying to learn?
2. What variation, restriction, equilibrium condition, institutional feature, or descriptive measurement reveals it?
3. Which assumptions connect the observed or modeled object to the stated claim?
4. What evidence in this paper is most diagnostic of those assumptions?
5. What alternative explanation or model can produce the same evidence?
6. What result would change the main interpretation?
7. Does the requested remedy discriminate between the paper's interpretation and a credible alternative?
8. Are groups, regimes, cases, and comparison samples fixed before the object of interest, or can treatment, shocks, selection, or equilibrium outcomes reclassify units?
9. Can every constructed measure and derived number be rebuilt from an explicit numerator, denominator or base, weights, transform, support rule, source inputs, and uncertainty calculation?
10. Does every stated assumption or restriction appear in the estimator, proof, model, algorithm, or code that is claimed to implement it?
11. What economic chain connects the measured, estimated, proved, or simulated object to the paper's claimed decision, equilibrium, welfare, contribution, or policy endpoint? Is the intermediate object a cause, mechanism, prerequisite, proxy, consequence, or merely a descriptive correlate?
12. What credible direct channel, reverse ordering, counterexample, or bypass can reach the endpoint without the paper's proposed intermediate step, and what evidence distinguishes it?
13. Does the focal condition differ from its benchmark only in the component named by the paper? For an intervention, what complete sequence of differential content, prompts, tasks, routing, timing, and platform features occurs before each outcome?
14. Are results used to explain one another actually comparable in treatment or model contrast, population or domain, horizon, support, estimand, and temporal or logical order?
15. Is every material object promised, motivated, preregistered, collected, modeled, or necessary for interpretation accounted for, even if the defensible accounting is a transparent reason for non-use?
16. Can every headline magnitude be interpreted against the comparison-specific baseline, feasible support, cell or case support, uncertainty, and an economically meaningful benchmark?
17. What supports any move from the observed sample, local estimand, calibrated domain, model class, or institutional setting to the paper's broader target?
18. Is each load-bearing exhibit or diagnostic direct evidence, a falsification implication, sensitivity evidence, targeted fit, independent validation, a numerical check, or an external benchmark? What can it establish, and which failure modes does it share with the headline result?
19. For every requested analysis, which favorable, adverse, or inconclusive outcome would change the supported claim or review assessment? If no branch changes the assessment, why request it?
20. Do source facts activate a participant-protection, registration, sensitive/restricted-data, reuse-rights, funding, conflict, or other governance burden? If so, what disclosure or claim boundary is needed, and which current official rule—if any—makes it specific rather than generic?

Do not begin with a canned estimator checklist. Derive the audit burden from these answers.

## Claim-to-burden map

Build one row for every load-bearing claim before choosing a method lens:

| Field | Record |
|---|---|
| Claim | Exact claim-family ID and strongest supported version |
| Object learned | Estimand, measurement, proposition, parameter, equilibrium, forecast, mechanism, welfare object, or contribution claim |
| Evidentiary bridge | Variation, assignment, measurement rule, restriction, proof, moment, calibration, computation, comparison, or cited source |
| Activated burdens | Every validity, uncertainty, implementation, interpretation, external-validity, and reproducibility burden created by that bridge |
| Trigger | Source anchor, claim ID, or required-but-missing object that activates each burden |
| Discriminating evidence | Existing or feasible evidence that would separate the paper's account from its strongest live alternative |
| Boundary | What cannot be assessed from the supplied material |

Activation follows the object, including required omissions. An estimate activates an uncertainty burden even when the paper reports no standard errors; a numerical counterfactual activates computation and sensitivity burdens even when called an illustration; a verbal mechanism activates a claim-evidence burden even when no formal mechanism test is promised. Conversely, a familiar method name does not activate every conventional diagnostic.

Use the smallest useful burden vocabulary and permit paper-specific extensions. Common burdens include logical validity and claim consistency; formal, algebraic, numerical, and implementation validity; measurement, causal or structural identification, calibration, uncertainty, and validation; equilibrium counterfactual validity; external validity; source support; and reproducibility. Record why a considered burden is `not_applicable`. For a hybrid paper, take the union of burdens created by its actual claim-evidence links, then audit the bridges between components.

## Stable parent burden IDs

Use two levels so that a review can be precise without becoming method-specific:

- `id` names the paper-specific burden actually audited, such as `index_time_comparability`, `equilibrium_selection`, or `clustered_assignment_inference`.
- `parent_id` classifies that row under one stable conceptual parent from the table below.

Every current strict v0.4 burden row must carry one non-null `parent_id`. The parent is a classification, not a second row that duplicates the same concern. When the row itself is already stated at the parent level, set `id` and `parent_id` to the same value. The three required audit-view rows—`logical_validity`, `technical_validity`, and `methodological_validity`—therefore self-parent. Do not create both `measurement` and `measurement_definition` merely to satisfy naming conventions; keep one precise row and classify it under `measurement_validity`.

These parents are interoperability keys, not a universal checklist. Activate a row only from a source-derived object, claim, evidentiary bridge, or required omission. Mark a row `not_applicable` only when that candidate burden was actually considered and the relevant object is absent. Do not add rows for every parent, and do not treat a capability boundary—such as code not supplied or execution not permitted—as a substantive burden by itself.

| Parent ID | Use when the source creates this burden |
|---|---|
| `logical_validity` | whether conclusions follow and remain internally consistent |
| `technical_validity` | formal, mathematical, numerical, or implementation correctness |
| `methodological_validity` | whether the way of learning can answer the stated economic question |
| `measurement_validity` | definition, construction, provenance, support, comparability, or interpretation of measured or encoded objects |
| `identification_validity` | whether evidence or restrictions distinguish the claimed causal, structural, mechanism, or other inferential object from live alternatives |
| `uncertainty_and_inference` | uncertainty or sensitivity created by sampling, assignment, estimation, posterior reasoning, simulation, calibration, forecasting, or numerical approximation |
| `formal_validity` | a definition, derivation, lemma, proposition, theorem, existence, uniqueness, equilibrium, or proof claim |
| `computational_validity` | calibrated inputs, algorithms, implementation, solution accuracy, simulation, or numerical outputs |
| `validation_and_fit` | fit, holdout, predictive, diagnostic, or other evidence used to validate a representation or result |
| `counterfactual_validity` | invariance, equilibrium response, welfare, transition, policy, or counterfactual interpretation |
| `scope_and_transport` | movement beyond the observed sample, source base, modeled domain, setting, model class, or policy margin |
| `source_support` | literature, archival, documentary, qualitative, or other source support for a load-bearing proposition |
| `reproducibility` | data, code, model, environment, or exhibit reconstruction needed to reproduce a material result |
| `research_integrity_and_governance` | a fact-triggered disclosure, registration, participant protection, rights, funding, conflict, provenance, or data-governance burden |
| `communication_integrity` | stable terminology, claim calibration, readability, grammar, usage, or optional style in the writing channel |
| `exhibit_integrity` | a separately inspected figure, table, equation display, or other exhibit and its correspondence to the paper's claims |

For example, `index_time_comparability` maps to `measurement_validity`; `sampling_or_randomization_uncertainty` and `posterior_sensitivity` map to `uncertainty_and_inference`; `solver_multiplicity` maps to `computational_validity`; `equilibrium_selection` maps to `formal_validity`; and `archive_selection` maps to `source_support`. The precise `id` carries the trigger and repair; `parent_id` supports cross-paper coverage and evaluation. Do not introduce a narrower ID when the parent itself is already precise enough.

Regardless of family, perform three separate views over the active burdens: `logical` asks whether each conclusion follows and remains internally consistent; `technical` checks the formal, mathematical, numerical, and implementation steps that carry the result; `methodological` asks whether the chosen way of learning—design, measurement system, model class, source strategy, validation exercise, or evidence synthesis—can answer the economic question at the claimed scope even if executed correctly. In a pure theory paper, for example, technical validity concerns the proof while methodological validity concerns whether the modeled domain and result bear on the economic question the paper claims to resolve. Mark a view `not_applicable` only when the source map confirms that the paper contains no relevant object.

## Audit each activated burden

For each active burden:

1. State the exact source-derived trigger.
2. Reconstruct the benchmark under which the claim would be justified.
3. Identify the strongest plausible alternative compatible with the current evidence.
4. Inspect the paper's most diagnostic existing evidence before requesting more work.
5. Classify the result as supported, partially supported, in conflict, bounded, or not assessed.
6. If adverse, request the minimum repair that would change the evaluation. For an additional diagnostic, state how each plausible result changes the claim; do not request a ritual diagnostic that cannot do so.

This burden record is the scope authority. Paper-family presets may suggest candidate checks, but they cannot add a mandatory check without a recorded trigger or remove a burden created by a claim.

Use [argument-evidence-audit.md](argument-evidence-audit.md) to make questions 11–19 explicit, and use [research-integrity-audit.md](research-integrity-audit.md) only when question 20 has a source-derived trigger. These checks do not mandate a theory model, a conventional robustness battery, population weights, new data, universal ethics boilerplate, or a universal set of outcomes. They require a source-grounded economic warrant, an honest account of what each evidence object can establish, and the smallest repair that supports the paper's own claim.

## Conditional presets

After the claim-to-burden map is built, load only the relevant components of [design-presets.md](design-presets.md). A hybrid paper may need several components. The preset suggests candidate reconstruction fields and threats; the burden record remains the scope authority.

## Clarity and misleading expression

Treat expression as substantive when wording changes the perceived evidence. Check:

- causal language for non-causal objects;
- `significant` used ambiguously;
- percentages, percentage points, elasticities, levels, logs, and standardized units;
- absolute versus relative baselines;
- robustness claims that exceed the displayed results;
- caveats weakened or dropped between body and abstract/conclusion;
- local or selected effects presented as universal;
- policy or welfare claims that require unmodeled incidence or equilibrium effects.

For a material wording issue, quote the current sentence and propose a faithful replacement. Keep ordinary style edits minor and optional.

## Finding threshold

Create a candidate only if all are true:

- the issue is demonstrated or the missing information is necessary to judge a material claim;
- the paper-specific consequence is clear;
- the evidence and locator are recorded;
- a plausible author response has been considered;
- the suggested fix is feasible or the limit is explicitly unfixable;
- resolving it would improve validity, interpretation, credibility, or venue readiness.

Apply the last condition literally. A correct observation without a useful, proportionate improvement path is not an author-facing criticism. When the ideal repair is infeasible, prefer faithful claim narrowing, transparent limitation language, or a bounded interpretation over demanding a different paper. Record relevant safeguards and strengths so the suggested change preserves what already works.
