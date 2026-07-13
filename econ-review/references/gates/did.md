# Difference-in-Differences Lens

Load this lens only when a headline claim uses a difference-in-differences or event-study design. Use the generic empirical branch first.

## Scope

Activate after determining whether treatment timing is simultaneous or staggered, absorbing or reversible, and whether the data are panel or repeated cross-sections. Do not apply staggered-adoption critiques to a simple two-group/two-period design without showing relevance.

This lens produces candidate findings, not a verdict or a mandatory robustness list.

## Required design facts

Before judging, record:

- target ATT or other estimand and its aggregation;
- treatment cohorts, timing, reversals, anticipation window, and spillovers;
- comparison units at each event time;
- maintained parallel-trends condition, conditional variables, and overlap;
- estimator, weights/aggregation, base period, and event-time window;
- inference level implied by assignment and sampling.

If a material fact is missing, first classify the relevant judgment `inconclusive_from_text`. Raise a reporting finding only when the missing fact blocks evaluation of a headline claim.

## Conditional checks

### DID-01 — Estimand, comparisons, and estimator agree

**Trigger:** multiple periods or treatment cohorts.

Inspect which units serve as controls, how cohort-time effects are aggregated, and whether already-treated observations enter comparisons. Ask whether treatment-effect heterogeneity or dynamics can make the reported coefficient differ from the target effect.

Do not automatically demand a decomposition. A modern group-time, imputation, interaction-weighted, or otherwise design-compatible estimator is evidence to evaluate, not an automatic pass. A conventional TWFE coefficient is not automatically invalid; show the material comparison or weighting problem for this design.

Possible remedies include clarifying the estimand, re-aggregating compatible cohort-time effects, presenting a diagnostic decomposition when informative, or narrowing interpretation.

### DID-02 — Parallel trends and anticipation burden

**Trigger:** the causal interpretation relies on untreated potential-outcome trends.

Inspect the institutional argument, pre-treatment outcome dynamics, group composition, differential shocks, anticipation, spillovers, and whether covariates are predetermined. Treat insignificant pre-period coefficients as neither proof nor failure by themselves; assess power and the confounding pattern that would threaten the estimate.

Sensitivity analysis is useful when it quantifies a plausible violation and the data contain informative pre-periods. Do not demand one mechanically when the design or pre-period structure cannot support it.

### DID-03 — Conditioning and sample stability

**Trigger:** conditional parallel trends, changing composition, time-varying controls, or selective observation.

Determine whether controls are predetermined, whether treatment affects observation or group membership, and whether overlap exists in the comparison sample. Recommend weighting, outcome-regression, doubly robust, trimming, or bounding approaches only when they address the actual conditioning problem.

### DID-04 — Dynamic presentation supports the claim

**Trigger:** event-study or dynamic-effect language.

Verify base period, omitted leads/lags, cohort composition by event time, simultaneous confidence needs, bins, and whether the plotted object matches the headline estimand. Distinguish evidence of anticipation from low power, compositional changes, or normalization artifacts.

### DID-05 — Inference matches assignment and serial dependence

**Trigger:** treatment varies at an aggregate level or outcomes are serially correlated.

Audit the clustering or randomization level from the design, number and balance of clusters, treated-cluster count, and time dependence. Do not use a universal cluster-count cutoff. Ask whether the chosen inference remains credible in the observed configuration and whether a design-appropriate alternative changes the conclusion.

## Do not overclaim

- Do not call negative weights material without establishing that the estimator and treatment timing permit them and that heterogeneity could affect the headline object.
- Do not equate a visible pre-trend with automatic failure or flat pre-coefficients with proof.
- Do not prescribe a software package as the fix.
- Do not require every modern estimator. Prefer the smallest analysis that distinguishes the live threat.
- Downgrade or dismiss the concern if the appendix already maps comparisons, reports a design-compatible estimand, and shows the conclusion is stable under a relevant alternative.

## Verified canonical sources

- Andrew Goodman-Bacon (2021), “Difference-in-Differences with Variation in Treatment Timing,” *Journal of Econometrics*. [DOI record](https://doi.org/10.1016/j.jeconom.2021.03.014). Supports the 2×2 comparison decomposition and the need to understand timing-group comparisons. Verified 2026-07-11.
- Jonathan Roth (2022), “Pretest with Caution: Event-Study Estimates after Testing for Parallel Trends,” *American Economic Review: Insights*. [AEA record](https://www.aeaweb.org/articles?id=10.1257/aeri.20210236). Supports low-power and conditioning concerns around pre-trend tests. Verified 2026-07-11.
- Ashesh Rambachan and Jonathan Roth (2023), “A More Credible Approach to Parallel Trends,” *Review of Economic Studies*. [Journal record](https://doi.org/10.1093/restud/rdad018). Supports sensitivity analysis under structured deviations from parallel trends. Verified 2026-07-11.

Use these sources to frame questions, not to imply that every DiD paper must run every associated procedure.
