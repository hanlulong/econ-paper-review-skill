# Regression-Discontinuity Lens

Load this lens only when a cutoff, threshold, or kink identifies a headline claim. Use the generic empirical branch first.

## Scope

Determine whether the design is sharp, fuzzy, kink, geographic, time-based, or uses a discrete running variable. Do not force continuous-score diagnostics onto settings where their assumptions do not fit.

## Required design facts

Record:

- running variable, cutoff, assignment rule, and treatment jump;
- sharp, fuzzy, or kink structure;
- estimand and population at the cutoff;
- support, mass points, heaping, and observations near the cutoff;
- bandwidth, kernel, polynomial order, bias correction, and uncertainty method;
- institutional basis for continuity and absence of precise manipulation.

If the local design or estimand cannot be reconstructed, classify the judgment `inconclusive_from_text` before proposing a concern.

## Conditional checks

### RD-01 — The cutoff generates the claimed local comparison

Verify that treatment or exposure changes at the cutoff and that the reported interpretation remains local to the relevant population. For fuzzy RD, reconstruct the first stage and IV-style local interpretation. For kink designs, verify the slope-change argument and smoothness burden.

### RD-02 — Continuity and sorting are institutionally credible

Inspect how the running variable is measured and assigned, whether agents can manipulate it precisely, administrative heaping or mass points, sample construction around the threshold, and predetermined covariate behavior.

A density test is one piece of evidence, not proof of validity or invalidity. Use it when the running variable is sufficiently continuous and the test is informative. Combine statistical evidence with the assignment institution.

### RD-03 — Estimation and inference fit the local design

Inspect local polynomial order, bandwidth selection, kernel, bias correction, and standard errors. Prefer local polynomial analysis with robust bias-corrected inference when its assumptions fit. Treat global high-order polynomial specifications as a serious risk when they drive the headline result.

Distinguish a bandwidth optimized for point estimation from one chosen for interval coverage. Do not declare one fixed bandwidth multiplier mandatory.

### RD-04 — Visual and sensitivity evidence are diagnostic

Inspect the RD plot, binning, raw support, fitted curves, and estimates across a substantively reasonable range of bandwidths and local orders. Ask whether apparent instability reflects sparse data, functional form, manipulation, or a genuinely local effect.

### RD-05 — Falsification and design variants

Use predetermined covariate continuity, placebo cutoffs/outcomes, or donut specifications only when they target a credible threat. A donut design changes the effective local comparison and should be motivated by heaping or manipulation, not requested automatically. Discrete running variables and few support points require design-specific uncertainty and interpretation.

## Do not overclaim

- Do not call `rddensity` or any package inherently preferred; evaluate the method and assumptions.
- Do not treat failure to reject density continuity as proof of no sorting.
- Do not demand half/double bandwidths, donut RD, every placebo, or a specific kernel in all papers.
- Do not generalize the local effect beyond the cutoff population without separate evidence.
- Downgrade or dismiss the concern if the institution, raw support, local estimates, and relevant sensitivity checks jointly address it.

## Verified canonical sources

- Sebastian Calonico, Matias D. Cattaneo, and Rocío Titiunik (2014), “Robust Nonparametric Confidence Intervals for Regression-Discontinuity Designs,” *Econometrica*. [Official supplement and citation](https://www.econometricsociety.org/publications/econometrica/browse/2014/11/01/robust-nonparametric-confidence-intervals-regression/supp/ECTA11757SUPP.pdf). Supports robust bias-corrected inference. Verified 2026-07-11.
- Andrew Gelman and Guido Imbens (2019), “Why High-Order Polynomials Should Not Be Used in Regression Discontinuity Designs,” *Journal of Business & Economic Statistics*. [DOI record](https://doi.org/10.1080/07350015.2017.1366909). Supports avoiding global high-order polynomial specifications. Verified 2026-07-11.
- RD Packages, [`rdrobust`](https://rdpackages.github.io/rdrobust/) and [`rddensity`](https://rdpackages.github.io/rddensity/) documentation. Supports current local-polynomial, bias-correction, bandwidth, and manipulation-testing implementations; software is illustrative, not mandatory. Verified 2026-07-11.
