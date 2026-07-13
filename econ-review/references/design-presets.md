# Conditional Design Presets

Load only components activated by the claim-to-burden map in `design-audit.md`. These are candidate prompts, not requirements.

## Empirical causal and experimental

Reconstruct treatment/exposure, outcome, unit, timing, population, estimand, assignment/variation, counterfactual, interference, anticipation, compliance, attrition, measurement, selection, and the uncertainty level implied by assignment and sampling. Audit whether variation identifies the stated object, conditioning changes the comparison, uncertainty matches the design, and interpretation stays within the estimand. Recommend a test only when it distinguishes a live alternative. This component covers unfamiliar designs even without a named gate.

## Descriptive, measurement, and forecasting

Reconstruct the population and measurement target; frame, coverage, missingness, linkage, classification, revisions; variable/index algebra and weights; validation benchmark and measurement error; and, for forecasts, target, horizon, information set, loss, and out-of-sample design. Audit construct validity, representativeness, denominators, zero/missing rules, changing weights, index bases/chaining, look-ahead, benchmark choice, uncertainty, and whether policy or mechanism language outruns descriptive evidence. Hold universe, transformation, weights, normalization, and support fixed before attributing differences to a method.

## Prediction and machine learning

Reconstruct the prediction target, unit, horizon, information available at the prediction date, training/tuning/evaluation split, preprocessing learned from each split, benchmark, loss, calibration, deployment population, and how predictions enter any decision. Audit leakage, repeated use of the test set, temporal or group dependence across splits, tuning against the reported holdout, class or support imbalance, calibration and decision thresholds, distribution shift, and uncertainty for the comparison actually claimed. Separate predictive performance from causal, mechanism, welfare, or policy claims. Interpretability or subgroup analysis is required only when it carries one of those claims or a stated decision objective, not as a universal machine-learning ritual.

## Institutional, historical, archival, and qualitative evidence

Reconstruct the source universe, provenance, preservation and access process, case and document selection, chronology, coding or classification rules, missing or silent records, and the inferential move from recorded evidence to the paper's economic claim. Audit source criticism, selection on survival or availability, contemporaneous versus retrospective accounts, corroboration across sources with meaningfully different failure modes, treatment of contrary evidence, and whether a case establishes existence, mechanism plausibility, typicality, or a broader causal claim. Do not impose sampling-based inference or a fixed source count when the paper's object is interpretive, institutional, or historical; require transparency and claim scope appropriate to the evidence.

## Evidence synthesis and meta-analysis

Reconstruct the review question, search universe and dates, inclusion and exclusion rules, screening and coding process, effect-size harmonization, dependence among estimates, estimand comparability, and synthesis model. Audit selective study or specification inclusion, duplicated samples, publication and availability selection, incompatible populations or outcomes, heterogeneity, weighting, uncertainty, and whether a pooled summary answers a stable economic question. Do not demand one named bias diagnostic or a universal random-effects model; request the smallest sensitivity or scope change that distinguishes the live selection or comparability concern.

## Structural and quantitative

Reconstruct primitives, timing, information, equilibrium, data mapping, parameter-to-moment links, calibration versus estimation, targeted and untargeted moments, solution/optimization/simulation, counterfactual policy, fixed objects, and welfare criterion. Audit identification rather than fit, functional-form/calibration sensitivity, numerical stability, equilibrium selection, counterfactual validity, and untargeted validation. Activate algorithm-specific checks—weight concentration, tail coverage, Monte Carlo error, tolerances, multiple starts, or approximation error—only when used. Trace welfare and counterfactual summaries to formulas, inputs, baselines, units, uncertainty, and endogenous type changes.

## Formal theory

Reconstruct primitives, feasible actions, timing, information, beliefs, solution concept, existence, mechanism, assumptions, proof dependencies, domains, boundaries, and the formal-to-verbal mapping. Audit logical validity, hidden assumptions, existence/selection, limit or expectation interchange, local versus global scope, circular mechanisms, and results embedded in assumptions. Crosswalk assumptions to proof steps. When activated by the mathematics, test closure versus attainment, scaling/homogeneity, dimensional and relabeling invariance, degeneracies, ties, zero denominators, and representation dependence; do not impose spectral or topological checks otherwise.

## Macro and dynamic equilibrium

Combine this with the empirical, structural, or theory component warranted by the claim. Reconstruct states, stocks, flows, accounting, timing, expectations, clearing, steady state or balanced growth, transition, selection/determinacy, shocks and policy rules, units/horizon, filtering and transformations, parameter mapping, solution method, responses/decompositions, welfare, and what counterfactuals hold fixed. Audit stock-flow consistency, aggregation, stationarity/initial conditions, information timing, shock normalization, determinacy/stability, approximation error, transition feasibility, and represented equilibrium margins. Do not treat an accounting decomposition as causal or an impulse response as interpretable without its shock, sign, units, horizon, information set, and uncertainty.

## Mixed components

Connect the maps: which proposition motivates each empirical specification; which data object identifies or disciplines each theoretical parameter or mechanism; whether signs, margins, populations, and units align; whether evidence discriminates the model from alternatives; and whether counterfactuals use objects disciplined by supplied evidence. Treat a broken bridge as material only when it affects a claimed contribution.
