# PDF Backend Selection

Use the local, loss-aware ingestion contract as the stable interface. A backend
may propose structure or text, but the PDF render, source hash, page geometry,
and unresolved-conflict ledger remain authoritative.

## Approved core path

Use separately installed Poppler utilities for page metadata, native text with
geometry, and deterministic page rendering. Use `pdfplumber` for independent
geometry/table candidates, `pypdf` for non-executing structural inspection,
Pillow for crops, and optional local Tesseract for prose regions whose native
text layer is absent or unusable. Do not bundle system executables with the
skill release.

## Optional local semantic proposals

[Docling](https://github.com/docling-project/docling) is the preferred local
semantic-structure proposal. Its code is MIT-licensed, but its runtime downloads
separately licensed model artifacts. Pin and audit the exact Docling version and
every model revision before release. The default `auto` mode uses existing local
artifacts and degrades cleanly; model downloads require the separate
`--allow-model-downloads` flag. Formula enrichment is opt-in and remains
render-bounded.

Microsoft MarkItDown is a permissible optional adapter because its source is
MIT-licensed. Treat its Markdown only as a secondary semantic proposal. Keep
the canonical PDF block/page map and require alignment before its prose can be
quoted. Never accept its equations, tables, figures, or symbols without the
normal render-backed checks. Keep Azure Document Intelligence and other remote
plugins disabled unless the user explicitly authorizes manuscript upload.

Neither local backend is an evidence authority. It may improve reading order,
headings, paragraph grouping, or object discovery, but it cannot mark an
equation, table, figure, symbol, quotation, or page anchor verified.

## Premium hosted proposal

[Mathpix PDF API](https://docs.mathpix.com/reference/post-v3-pdf) may be used as
an optional premium scientific-OCR proposal. It is a remote service, not a
redistributed dependency. The adapter must:

1. require manuscript-specific upload authorization and a separate retention
   acknowledgement before reading credentials or opening a connection;
2. read `MATHPIX_APP_ID` and `MATHPIX_APP_KEY` only from the server process
   environment and never expose them to a browser or persist them in a report;
3. set `metadata.improve_mathpix=false`, download only the declared result
   artifacts, and record their hashes and request ID;
4. request deletion after success or failure and fail closed when deletion is
   not confirmed; and
5. keep the result non-authoritative until a reviewer adjudicates load-bearing
   content against page renders or supplied TeX/Markdown.

Mathpix documents source/page-image retention of up to 30 days and text
retention of up to 90 days for the PDF endpoint unless deletion and applicable
settings shorten it; CDN removal may lag. Read the current
[data-retention policy](https://docs.mathpix.com/concepts/data-retention),
[privacy documentation](https://docs.mathpix.com/concepts/privacy), pricing,
and contract before launch. Its terms restrict using service output to develop
competing models. Obtain written confirmation and an appropriate data-processing
agreement for the intended hosted product; do not generalize a user account or
subscription into commercial processing rights.

## LLM-assisted visual adjudication

When the active review environment permits it, the agent may inspect the saved
page and object images with the user's model subscription. This is best used to
resolve a bounded disagreement among native text and semantic proposals. It is
not an automatic conversion backend, should not receive credentials, and must
not promote its reading without page/object provenance. Record the inspected
scope and retain an explicit boundary wherever symbols or layout remain unclear.

This hybrid division is intentional:

| Layer | Role | Authority |
|---|---|---|
| Poppler/pdfplumber/pypdf/renders | stable pages, geometry, hashes, and local candidates | evidence and visual authority |
| Docling or MarkItDown | local semantic proposal | non-authoritative |
| Mathpix | explicitly authorized premium scientific-OCR proposal | non-authoritative |
| reviewer/LLM render inspection | conflict adjudication with recorded scope | verified only for the inspected object and evidence link |

`reconciliation/page-packets.json` is the handoff between these layers. It
contains selected/native/OCR references, stable block text and geometry,
adjacent-page renders, complete object-crop evidence, normalized backend
candidates, overlap/text-agreement diagnostics, and hashes. It contains no
merged text, adjudication decision, or hidden backend preference.
Converter agreement may prioritize a page for quick review, but only an
explicit render-backed decision can verify load-bearing content. Canonical
Markdown is never rewritten merely because a proposal exists.

Record that later pass in `reconciliation-decisions.json` under the strict
decision schema and validate it with `scripts/pdf_reconciliation.py`. A
`verified_scope` ledger means only that every listed decision was checked
against its declared render/crop evidence; it does not claim that unlisted
pages or objects were verified.

## Backends not approved for this product

Do not integrate or invoke Datalab Marker under its public code/model terms.
The combination of GPL code and model-license commercial restrictions,
including a competing-product restriction, is incompatible with the planned
standard and paid product absent a separate written license and legal review.

Do not integrate or invoke Nutrient/PSPDFKit PDF-to-Markdown under its free
license. Its proprietary terms include a competing-product restriction. A
commercial agreement and legal review are required before evaluation inside
the product.

## Adding another backend

Before code or model installation, record:

1. exact code, model, and output licenses;
2. commercial, hosting, volume, attribution, telemetry, and competitor terms;
3. whether binaries, weights, or notices would be redistributed;
4. local versus external processing and manuscript-retention behavior;
5. the backend's role in the proposal/reconciliation pipeline;
6. a fixture-based comparison covering prose, reading order, tables, figures,
   equations, symbols, page anchors, and failure disclosure.

Reject any backend that weakens provenance, silently uploads documents, or
turns extraction confidence into verification.
