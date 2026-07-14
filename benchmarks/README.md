# Cross-family review benchmark

This benchmark is designed to test whether `econ-review` routes checks from claims and evidentiary objects rather than from a single paper label. It is a framework regression harness, not a completed evaluation or a claim that the skill outperforms another product.

The six synthetic rubric cases cover empirical causal, descriptive/measurement, structural/quantitative, macro/dynamic, formal theory, and mixed theory-empirical work. Each case contains:

- a short original manuscript with seeded, independently checkable issues;
- expected active conceptual burden parents, plus exact facets only where the distinction is part of the test;
- required issue concepts stated as alternative text patterns, not prescribed reviewer prose;
- clean traps that should not become findings;
- a case-specific rubric in `cases.json`.

The clean traps matter as much as recall. For example, the descriptive case must not be criticized for lacking causal identification when it makes no causal claim, and the individually randomized experiment must not receive a ritual cluster-robustness comment without a dependence trigger.

The seeded issues also test connective review work that can be missed by method-name checklists: whether a claimed endpoint follows from the paper's economic objects, whether a direct or alternative channel bypasses the preferred explanation, whether promised or collected objects are supported in the results, whether results that are interpreted jointly are coherent, and whether quantitative magnitudes and transport claims have an appropriate benchmark. Applicability is part of the test: a scoped descriptive signal should not receive a fabricated population-overreach criticism, and a qualitative theory result should not receive a ritual effect-size or statistical-power demand.

## Rubrics versus executed packages

`cases.json` and `papers/` contain rubric-only seeds. They are not reviews and do not count as executed evidence. A completed end-to-end run exists only when a full review package has been generated under `reviews/<case-id>/`; generated packages are intentionally excluded from the distributed repository.

The evaluator reports `rubric_case_count`, `executed_package_count`, and `missing_review_packages` separately. Do not report benchmark recall, false-positive performance, or cross-family completion from rubric files alone.

## Run an evaluation

Create a full review package for a case under `benchmarks/reviews/<case-id>/`, then run:

```bash
python3 benchmarks/evaluate.py
```

The default available-only mode checks parent-level burden routing, selected paper-specific facets, required issue-concept recall, forbidden false positives, and the atomic finalizer's `--check` for review packages that exist. A draft or receipt-less directory never counts as executed benchmark evidence, even when its intermediate JSON happens to validate. Parent states aggregate through each row's stable `parent_id`: active takes precedence over a not-applicable sibling, while an absent parent remains unassessed. A required issue must appear in the reviewer-authored diagnosis fields of one finding; words split across comments or copied only in manuscript evidence cannot satisfy a pattern. Missing packages are reported as `not_run` and do not fail this exploratory command. A present but unreadable or unfinalized package does fail.

Use strict mode for CI, release readiness, or any end-to-end performance claim:

```bash
python3 benchmarks/evaluate.py --require-all
```

Strict mode fails if any rubric lacks `reviews/<case-id>/`, as well as when an executed package is invalid or misses its rubric. The distributed package intentionally contains no generated reviews, so strict mode is expected to fail on a clean checkout until all six packages have been produced. The evaluator reports each dimension separately and never collapses them into an unsupported quality or superiority score.

The benchmark manuscripts and rubrics are public-safe synthetic fixtures. Real manuscripts, competitor reports, and private evaluation labels do not belong here.
