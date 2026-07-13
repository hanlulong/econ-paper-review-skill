# Instrumental-Variables Lens

Load this lens only when an instrument identifies a headline empirical or structural claim. Use the generic empirical or structural branch first.

## Scope

Distinguish single from multiple instruments, one from multiple endogenous variables, just- from overidentification, linear from nonlinear models, clustered or heteroskedastic settings, shift-share constructions, examiner designs, and proxy SVARs. This core lens does not encode every design-specific IV variant.

Never apply a single magic first-stage threshold across these cases.

## Required design facts

Record:

- instrument construction and variation;
- endogenous variables, first stage, and reduced form;
- target parameter and population;
- just-/overidentification and number of instruments/endogenous variables;
- independence/exogeneity argument;
- exclusion channels;
- monotonicity, sign, or rank conditions relevant to interpretation;
- error structure, clustering, and weak-identification procedure.

If these cannot be reconstructed, use `inconclusive_from_text` and identify exactly what is needed to interpret the headline result.

## Conditional checks

### IV-01 — The instrument identifies the claimed object

Map instrument variation to the treatment margin and target population. Check whether the reported interpretation exceeds a local, marginal, or selected estimand. For heterogeneous effects, ask who changes treatment because of the instrument and whether the policy claim applies to that group.

### IV-02 — Relevance and inference are design-appropriate

Inspect the first-stage object appropriate to the model, not merely whether an F statistic is printed. Determine whether conventional Wald/t-ratio inference is credible or whether weak-identification-robust confidence sets or tests are needed.

The Lee–McCrary–Moreira–Porter `104.7` result concerns conventional 5 percent t-ratio inference in a single-IV model. Do not use it as a universal strength cutoff, do not compare Stock–Yogo critical values mechanically to a Kleibergen–Paap statistic, and do not assume one diagnostic covers multiple endogenous regressors or nonstandard errors.

Possible remedies include reporting the correct first-stage diagnostic, weak-ID-robust Anderson–Rubin or conditional-likelihood-ratio-style inference where supported, or narrowing claims when the data are weakly informative.

### IV-03 — Independence and exclusion survive plausible channels

Enumerate the strongest direct channel, common cause, or selection mechanism linking the instrument to the outcome outside the endogenous variable. Evaluate timing, institutional evidence, balance, reduced-form patterns, negative controls, and mechanism evidence.

Placebos, balance, and overidentification tests can challenge specific violations; they do not prove exclusion. Ask for the smallest test that discriminates the paper's channel from the credible alternative.

### IV-04 — Monotonicity, sign, and interpretation are coherent

Determine which units or margins respond, whether sign reversals or defiers are substantively plausible, and whether first-stage stability across relevant groups informs the interpretation. Do not require subgroup first stages without a paper-specific reason.

### IV-05 — Many-instrument or multiple-endogenous-variable branch

Activate only when triggered. Inspect instrument count relative to information, overfitting, concentration across endogenous variables, bias toward OLS, and whether the reported diagnostic has the claimed interpretation. Recommend LIML, jackknife, regularization, pruning, or alternative inference only when justified by the actual configuration.

## Do not overclaim

- Do not treat `F > 10` or `F > 104.7` as a universal pass/fail rule.
- Do not call exclusion “tested” by a Hansen J statistic, balance table, or placebo.
- Do not infer monotonicity failure merely from heterogeneous first stages.
- Do not hard-code judge-leniency, shift-share, or proxy-SVAR demands into every IV review.
- Downgrade or dismiss the concern when the paper uses design-appropriate weak-ID-robust inference and keeps interpretation within the identified object.

## Verified canonical source

- David S. Lee, Justin McCrary, Marcelo J. Moreira, and Jack Porter (2022), “Valid t-Ratio Inference for IV,” *American Economic Review*. [AEA record](https://www.aeaweb.org/articles?id=10.1257/aer.20211063). Supports F-dependent t-ratio adjustments in the single-IV setting and the conditional scope of the `104.7` result. Verified 2026-07-11.

Use general IV logic from the reconstructed design. Add further named sources only after live verification for the exact IV variant.
