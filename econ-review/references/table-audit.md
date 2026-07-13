# Separate Rendered-Table Audit

Use this protocol for every table in a full review. A coverage-matrix row is not enough. Inspect the rendered table separately from extracted Markdown or OCR, save `evidence/tables.json`, and summarize the results in `evidence/tables.md`.

Write new or materially refreshed inventories against `tables.schema.json`
version `0.2`. Version `0.1` remains readable for backward compatibility; do
not relabel a populated v0.1 inventory without replacing its bare
`render_paths` with the v0.2 source and immutable-asset records.

## 1. Inventory and render

Inventory every main-text and appendix table, including multi-page continuations and tables embedded as images. Map each table to its coverage-unit ID and rendered PDF page. If the paper has no tables, confirm that from the rendered manuscript.

Save at least one inspectable PNG/JPEG/WebP render for every table marked
`inspected`. In v0.2, record each retained image in `rendered_assets` with its
portable review-relative path, lowercase SHA-256 digest, `crop` or `full_page`
role, source-location page (or `null` when pagination is not meaningful), and
`source_object_id`. Full-page assets use a null object ID. A PDF crop uses the
exact table-object ID from the authenticated PDF-ingestion manifest; a
filename, page, or matching hash cannot substitute for that join. Retain a
canonical full-page render for every declared PDF page so a crop cannot conceal
its source context. Non-PDF assets use a null object ID.

A page number or prose statement is not render evidence. Keep assets inside
the review directory; reject traversal, external symlink targets, missing
files, extension/signature mismatches, incomplete image decodes, and stale
hashes. Recompute the digest and re-inspect whenever an asset's bytes change.

Do not admit a blank-cell, missing-statistic, row-shift, symbol, or alignment finding from extraction alone. Inspect the exact rendered page. When extraction and rendering conflict, treat the rendering as authoritative for visible content and record `conflict_resolved_from_render`.

## 2. Check the table contract

For each table, verify:

1. numbering, title, panel labels, and continuation labels;
2. row/column alignment, horizon or model-column count, and repeated headers;
3. cell completeness, intentional blanks, and all statistics promised by the notes;
4. units, transformations, normalization, base, and sign conventions;
5. sample, denominator, population at risk, weights, missingness, and support;
6. uncertainty, standard-error or posterior-interval definition, clustering, stars, and multiplicity language;
7. abbreviations, group labels, variable definitions, and source notes;
8. consistency of repeated objects and shared columns across tables;
9. numerical identities, rescalings, totals, differences, and derived quantities that can be checked;
10. correspondence between the table, surrounding prose, abstract/introduction/conclusion claims, and any figure showing the same object.

Check every row and column, not only headline cells. For dynamic or subgroup tables, reconcile all displayed horizons and groups before accepting words such as `persistent`, `uniform`, `both`, `all`, or `robust`.

Reconcile every prose reference to table numbers, panels, rows, and column ranges against the rendered exhibit's actual cardinality. A declared column, row, or panel range that does not match the rendered exhibit—or a reference to a nonexistent exhibit part—is an objective cross-reference error even when the estimates themselves are correct. Aggregate repeated range errors by correction rule rather than inflating the finding count.

## 3. Verify comparisons and calculations

Use the analytical ledgers for tables that compare methods, samples, regimes, or constructed measures. Confirm that the comparison holds outcome, support, transformation, weights, and information set fixed. Trace any number computed from multiple table cells through the derived-number ledger.

When code is unavailable, distinguish:

- a visible table defect;
- an internally inconsistent calculation;
- an untraceable calculation;
- a computation that cannot be assessed from the manuscript.

Only the first two justify categorical error language.

## 4. Output and ship gate

Record each table's source, rendered pages, immutable rendered assets,
extraction status, typed table-contract checks (`clear`, `issue`, `bounded`, or
`not_applicable` plus a result), claim correspondence, finding IDs, and
boundary. Every adverse state must map to an active verified finding. Every
table coverage unit must appear exactly once in `evidence/tables.json`.

Do not ship a complete full review when any inventoried table lacks a saved inspected render, when an extraction/render conflict remains unresolved, or when a `table_cell` finding is not mapped back from the matching table-audit row. A bounded unrendered table keeps the run incomplete; it is not a way to certify a complete review.
