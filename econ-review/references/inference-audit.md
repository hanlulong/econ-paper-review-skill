# Conditional Inference Audit

Load this lens whenever the reported object creates a sampling, randomization, dependence, simulation, numerical, or posterior uncertainty burden. The burden exists even when the manuscript omits uncertainty language. Activate individual checks from reconstructed facts; do not impose an applied-micro checklist on descriptive, theoretical, structural, macro, or mixed papers.

## Activation map

| Reconstructed fact | Conditional check |
|---|---|
| Errors may be dependent within groups, time, space, markets, networks, or common shocks | Reconstruct the assignment/sampling level and the dependence process before judging the covariance estimator. |
| Few clusters, few treated clusters, or highly unequal cluster sizes | Report cluster counts and leverage/size concentration; assess small-sample corrections or an appropriate cluster bootstrap. Do not prescribe a wild bootstrap without checking treated-cluster support and cluster-size balance. |
| Repeated observations with persistent outcomes or policy timing | Check whether serial correlation is reflected in the variance estimator or randomization scheme. |
| Many outcomes, arms, subgroups, horizons, specifications, or model moments | Reconstruct confirmatory families and distinguish preregistered from exploratory analysis; assess familywise or false-discovery control and simultaneous intervals where the claim requires them. |
| Treatment affects outcome observability, follow-up, employment, survival, or sample inclusion | Check response by assignment and define the observed-sample estimand. Use weighting, bounds, or claim narrowing only under their actual assumptions. |
| The claim targets a population broader than the recruited, observed, selected, calibrated, or linked sample | Define the sample and target estimands separately. Check overlap and defensible effect modifiers before suggesting weighting or standardization; otherwise narrow the claim. |
| Randomized estimates add covariates or omit a substantively prominent baseline variable | Recover the prespecified adjustment set, timing, prognostic rationale, and assignment-respecting specification. Do not require a named control for identification or permit post-treatment adjustment. |
| The paper motivates, preregisters, collects, or reports several related outcomes or margins | Reconcile the evidence-object inventory with the reported family. Distinguish a justified non-use from unexplained omission or selective emphasis before creating a finding. |
| Estimates are selected for significance or the design has low power | Ask for an ex ante or design-based minimum detectable effect and interpret large selected estimates cautiously; do not infer bias from low power alone. |
| A sufficiently complete family of comparable test statistics or p-values is available and selective reporting is a live concern | Inspect threshold heaping or discontinuities only after defining the test universe and reconciling rounding, discreteness, one- versus two-sided tests, and heterogeneous specifications. Treat the pattern as a diagnostic, never proof of manipulation. |
| Robustness is argued from coefficient stability after adding controls | Check the exact selection-on-observables argument and sensitivity parameters. Do not convert a conventional parameter value into a universal pass/fail threshold. |
| Random assignment is known | Prefer tests and intervals that respect the implemented assignment mechanism when feasible; do not call generic permutation a randomization test. |
| Structural, simulation, or Bayesian uncertainty is reported | Trace simulation error, numerical tolerance, posterior interval definition, prior sensitivity, and whether sampling and model uncertainty are being conflated. |

## Checks

### Dependence and clustered inference

Identify the level at which treatment, shocks, sampling, and residual dependence arise. Record the number of clusters, treated clusters, cluster-size concentration, fixed-effects structure, and whether the estimand is supported within clusters. A conventional cluster-robust standard error, a wild cluster bootstrap, and randomization inference answer different questions. Recommend a method only after matching its assumptions to the design.

Cameron, Gelbach, and Miller develop bootstrap refinements for clustered errors. MacKinnon and Webb show that few treated clusters and unequal cluster sizes can defeat otherwise familiar procedures. Bertrand, Duflo, and Mullainathan document severe over-rejection when serial correlation is ignored in difference-in-differences settings. Use these as conditional diagnostics, not universal numerical thresholds.

### Multiplicity and selective emphasis

Inventory outcomes, arms, subgroups, horizons, models, and displayed specifications. Define the family attached to each headline claim. When the paper makes joint or family-level claims, check adjusted p-values or simultaneous intervals; when it presents exploratory evidence, require clear labeling rather than mandatory correction of every exploratory test. Romano and Wolf provide stepwise familywise-error control that incorporates dependence among statistics.

### Attrition and selected outcome observation

If assignment changes whether an outcome is observed, an observed-sample comparison need not retain the original randomized estimand. Check arm-specific observation rates and baseline composition. Weighting requires a defensible response model; Lee-style bounds require the relevant monotonicity structure. If neither is credible, define the respondent-sample estimand and narrow the claim.

### Sample-to-target transport

A randomized effect in the recruited sample need not equal a population effect. State both objects before recommending a repair. Reweighting or standardization can help only when the target population is declared, overlap is adequate, the relevant effect modifiers are observed, and the adjustment model is credible. Nonprobability recruitment can leave selection on unobservables unresolved after demographic balance. When transport is not identified, describe the sample and narrow the claim rather than treating unavailable population data as a defect.

### Covariate adjustment in randomized designs

Baseline covariates are not required for identification under valid randomization. Audit whether the adjustment set was prespecified, measured before assignment, prognostic or precision-motivated, and implemented consistently with blocks or assignment probabilities. If heterogeneity by a baseline variable is central, ask for the direct interaction or subgroup contrast and its uncertainty; do not infer that putting that variable in the main-effect control vector tests heterogeneity.

### Outcome and margin completeness

Use the argument-and-evidence inventory to trace outcomes and margins mentioned in the motivation, registration, instrument, methods, and results. An unreported collected variable is not automatically selective reporting. Retain a concern when non-reporting breaks a stated promise, hides a relevant margin needed to interpret the headline result, conflicts with a registration, or makes the reported family incomplete. A transparent explanation, relegation of an immaterial exploratory item, or correction of the motivating prose may be the sufficient repair.

### Power, minimum detectable effects, and winner's curse

Use the design's assignment unit, variance, allocation, and testing family to compute power or a minimum detectable effect. A non-significant estimate is not evidence of absence without an economically meaningful equivalence region. A significant estimate from a low-powered, selectively reported design may be exaggerated, but low power alone does not prove bias. Ioannidis, Stanley, and Doucouliagos document low power and exaggeration across empirical economics literatures; the appropriate paper-level response is a design-specific calculation.

### Distributional diagnostics for reported tests

Activate a threshold-heaping or discontinuity check only when the manuscript or replication package exposes a sufficiently complete, comparable universe of reported tests. Define that universe before looking at conventional significance cutoffs. Reconcile rounded p-values, discrete randomization tests, one- and two-sided transformations, repeated specifications, and tests with different null distributions. A visible concentration around a cutoff may motivate a targeted reporting audit; it does not by itself identify selective reporting, p-hacking, or misconduct. With few or selectively collected statistics, mark the diagnostic uninformative rather than treating its absence as reassurance or its noise as evidence.

### Selection on observables and sensitivity

Coefficient stability after controls is informative only through an explicit relationship between selection on observables and unobservables. If an Oster-style exercise is used, report the baseline and controlled coefficients and R-squared values, the chosen maximum R-squared, the target coefficient or identified set, and the sensitivity parameter. Treat conventional parameter choices as sensitivity scenarios, not pass/fail rules.

### Assignment-respecting inference

When treatment was randomized, reconstruct the actual assignment: blocks, clusters, unequal probabilities, rerandomization, saturation, or interference restrictions. Randomization tests must draw from that assignment distribution. Young shows that assignment-respecting tests can materially change conclusions in experimental applications; use this as a reason to verify the implemented design, not to assume conventional inference is wrong.

## Do not overclaim

- Do not use a fixed cluster-count threshold as a theorem.
- Do not prescribe state clustering merely because states appear in the data.
- Do not treat multiplicity adjustment as mandatory for every descriptive or exploratory result.
- Do not call inverse-probability weighting a cure without checking overlap and the response model.
- Do not prescribe population reweighting merely because sample demographics differ from a census target.
- Do not require a substantively prominent baseline covariate in the default control set merely because it predicts the outcome or appears in heterogeneity analysis.
- Do not demand Lee bounds unless the selection structure and monotonicity interpretation fit.
- Do not treat an Oster sensitivity parameter of one as a universal validity threshold.
- Do not assert a numerical inconsistency from hand arithmetic. Recompute it with `scripts/stat_recompute.py` or mark the check bounded.

## Verified primary sources

Accessed 2026-07-12.

- Cameron, Gelbach, and Miller (2008), “Bootstrap-Based Improvements for Inference with Clustered Errors,” *Review of Economics and Statistics* 90(3), 414–427. [DOI](https://doi.org/10.1162/rest.90.3.414)
- Bertrand, Duflo, and Mullainathan (2004), “How Much Should We Trust Differences-in-Differences Estimates?” *Quarterly Journal of Economics* 119(1), 249–275. [NBER working-paper record](https://www.nber.org/papers/w8841)
- MacKinnon and Webb (2018), “The Wild Bootstrap for Few (Treated) Clusters,” *Econometrics Journal* 21(2), 114–135. [Journal DOI](https://doi.org/10.1111/ectj.12107)
- Romano and Wolf (2005), “Stepwise Multiple Testing as Formalized Data Snooping,” *Econometrica* 73(4), 1237–1282. [DOI](https://doi.org/10.1111/j.1468-0262.2005.00615.x)
- Lee (2009), “Training, Wages, and Sample Selection: Estimating Sharp Bounds on Treatment Effects,” *Review of Economic Studies* 76(3), 1071–1102. [Author manuscript](https://www.princeton.edu/~davidlee/wp/resrevision8.pdf)
- Oster (2019), “Unobservable Selection and Coefficient Stability: Theory and Evidence,” *Journal of Business & Economic Statistics* 37(2), 187–204. [DOI](https://doi.org/10.1080/07350015.2016.1227711)
- Ioannidis, Stanley, and Doucouliagos (2017), “The Power of Bias in Economics Research,” *Economic Journal* 127(605), F236–F265. [DOI](https://doi.org/10.1111/ecoj.12461)
- Young (2019), “Channeling Fisher: Randomization Tests and the Statistical Insignificance of Seemingly Significant Experimental Results,” *Quarterly Journal of Economics* 134(2), 557–598. [DOI](https://doi.org/10.1093/qje/qjy029)
