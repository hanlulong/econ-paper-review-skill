# Design-Agnostic Audit

Start from the paper's claims and evidentiary objects, not its advertised method or a single paper-family label. A paper can activate several burdens at once: a descriptive fact may feed a causal interpretation, a theorem may discipline an estimated model, or a simulation may carry a policy claim. Audit that composition directly. The family sections below are routing aids and examples, never mutually exclusive templates.

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

Regardless of family, perform three separate views over the active burdens: `logical` asks whether each conclusion follows and remains internally consistent; `technical` checks the formal, mathematical, numerical, and implementation steps that carry the result; `methodological` checks whether the evidence-producing design and validation support the object claimed. Mark a view `not_applicable` only when the source map confirms that the paper contains no relevant object.

## Audit each activated burden

For each active burden:

1. State the exact source-derived trigger.
2. Reconstruct the benchmark under which the claim would be justified.
3. Identify the strongest plausible alternative compatible with the current evidence.
4. Inspect the paper's most diagnostic existing evidence before requesting more work.
5. Classify the result as supported, partially supported, in conflict, bounded, or not assessed.
6. If adverse, request the minimum repair that would change the evaluation; do not request a ritual diagnostic that cannot do so.

This burden record is the scope authority. Paper-family presets may suggest candidate checks, but they cannot add a mandatory check without a recorded trigger or remove a burden created by a claim.

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
