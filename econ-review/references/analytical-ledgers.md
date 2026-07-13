# Analytical Ledgers

Use these ledgers in every full review. They are design-agnostic: activate the entries implied by the paper's claims, not by a canned method label. Save the structured result in `evidence/analytical-audit.json` and the readable result in `evidence/analytical-audit.md`.

Each applicable domain declares only the coverage units containing relevant objects—not the entire paper by default. Each entry records its own nonempty coverage-unit subset, one or more source/locator/content records, unique typed checks, status, and finding links. For a `complete` domain, the union of entry coverage must equal the declared domain scope. Entry status and check status must agree, and domain finding links must match the corresponding coverage dimension. These reciprocal constraints prevent a one-line assertion from standing in for a source-derived inventory.

Do not collapse a domain into a generic sentence such as `checked`, `clear`, or `reviewed`. Split materially different paper objects into separate entries and quote or summarize the source-specific evidence for each one. The validator rejects generic evidence and check results, but substantive completeness still requires the reviewer to inventory the paper rather than optimize for schema passage.

## 1. Partition and regime ledger

Inventory every subgroup, regime, bin, type, state, case, equilibrium region, or sample split. For each one record:

- the assignment rule and the population from which cutoffs are computed;
- whether assignment is predetermined, fixed, contemporaneous, post-treatment, estimated, or equilibrium-determined;
- whether treatment, shocks, selection, attrition, or model outcomes can move units across groups;
- support, zero cells, overlap, and whether the compared groups retain the same interpretation;
- whether the reported response combines behavior with reclassification or changing composition.

This applies equally to empirical income bins, shock-defined regimes, theory cases defined by endogenous choices, structural types inferred from outcomes, and machine-learning subgroups.

## 2. Measure-algebra ledger

For every load-bearing rate, share, index, growth rate, elasticity, hazard, normalized response, welfare object, or constructed variable, write the exact algebra and record:

- numerator event or quantity;
- denominator, population at risk, and time at risk;
- unit, scale, sign convention, transform domain, base period, and normalization;
- fixed or changing weights, chaining rule, entry/exit, and composition effects;
- handling of zeros, missing values, censoring, interpolation, rounding, trimming, and numerical failures;
- mapping from raw record to person, household, firm, market, model state, or aggregate object.

Test index-number invariance when normalized levels are aggregated. Changing weights can move an aggregate level even when component growth is unchanged; compare growth rates or use a valid chain when level bases differ. Call a denominator problem an estimand mismatch unless the target and direction of bias are established.

## 3. Assumption-to-implementation crosswalk

List every maintained assumption, moment condition, exclusion, sign or zero restriction, prior, normalization, equilibrium condition, theorem hypothesis, calibration restriction, and algorithmic acceptance rule. Map each one to the exact:

- equation or matrix restriction;
- proof step or lemma;
- estimator, objective, likelihood, or moment;
- code or algorithm step;
- diagnostic or exhibit that verifies it.

Flag a stated assumption that is absent from the implementation, a constrained object described as estimated, a prior or selection rule described as data-driven, and a displayed estimator that does not implement the prose restriction. For weighted estimators or pseudo-likelihoods, state the implied variance model, sampling interpretation, and target estimand.

## 4. Derived-number ledger

Trace every number not copied directly from a displayed result. Record source cells or parameters, formula, units, baseline values, uncertainty method, rounding, and producing code when available. This includes:

- back-of-envelope calculations and rescalings;
- elasticities and percentage-point conversions;
- welfare, incidence, and cost-benefit calculations;
- calibrated targets and decompositions;
- counterfactual summaries and theorem examples;
- literature benchmarks quoted with an exact magnitude.

Recompute simple quantities with an auditable tool. For every adverse numerical conclusion, preserve a structured computation record: exact input anchor IDs, tool and version when available, method, tolerance, output artifact, artifact hash, and linked finding IDs. Hand arithmetic can create a candidate but cannot verify a finding. When execution is unavailable, verify algebra and inputs from the paper and label the result bounded rather than calling it wrong.

## 5. Comparison-harmonization ledger

Before attributing a difference to a method, model, robustness choice, group, sample, version, or benchmark, reconcile:

- outcome and estimand definitions;
- support, sample window, unit, and missingness;
- weights, transformations, normalization, and information set;
- tuning, priors, restrictions, equilibrium selection, and uncertainty summaries.

If more than the focal component changes, label the comparison compound and do not attribute the entire difference to one method. Record why the baseline was chosen. If an alternative more closely satisfies the maintained assumptions, make it the baseline or explain the tradeoff and display the headline result under it.

## 6. Timing and test ledger

Create a timeline from raw event through matching, aggregation, treatment or shock, outcome, and reporting. Define every date field, information set, lag, boundary period, initial condition, terminal condition, and reconciliation rule. Account for unexplained sample gaps and for timing mismatches that can create seasonality, anticipation, or look-ahead.

For every reported test or formal claim, record the null or proposition, restriction matrix or proof statement, unit, degrees of freedom, covariance, multiplicity family, and label. Verify that `pairwise`, `joint`, `system`, `causal`, `necessary`, `sufficient`, and similar terms match the actual calculation. Do not construct a system statistic by aggregating equation-level tests unless the joint covariance and algebra justify it.

For Bayesian, simulation, sign-restricted, set-identified, or search procedures, also record the sampling unit, proposals per draw, accepted objects, discarded draws, weighting rule, effective support, prior over admissible objects, Monte Carlo error, and convergence evidence.

## 7. Availability and exclusivity ledger

Verify load-bearing uses of `unavailable`, `only`, `first`, `cannot`, `no data`, and `no method`. Check the relevant period, geography, population, access restrictions, quality, and fitness for purpose. The existence of an alternative does not make it suitable; report availability and fitness separately. Apply the same rule to novelty claims about theorems, algorithms, datasets, and empirical findings.

## Admission and fairness rules

- Map every adverse ledger state to an active verified finding or remove it.
- Give every check a stable general-purpose ID and paper-specific result. Do not hard-code estimator names as universal requirements; define the applicable object after reconstruction.
- Use `bounded` when code, data, a proof appendix, or source access prevents a conclusion.
- Treat inherent, disclosed, claim-bounded data limits as checked-clean.
- Prefer the smallest decisive repair: exact wording, disclosure, existing-data diagnostic, targeted sensitivity, then new data or redesign.
- State a computation as a confirmed error only after derivation, execution, or sufficient internal evidence establishes it. Otherwise state the precise unresolved question and what would decide it.
- Keep reviewer observations, render transcriptions, source quotations, checked absences, external-source claims, and computed results as distinct evidence representations. Never render the first four as an unattributed manuscript quotation.
