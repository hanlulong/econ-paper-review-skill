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

## Optional semantic proposal

Microsoft MarkItDown is a permissible optional adapter because its source is
MIT-licensed. Treat its Markdown only as a secondary semantic proposal. Keep
the canonical PDF block/page map and require alignment before its prose can be
quoted. Never accept its equations, tables, figures, or symbols without the
normal render-backed checks. Keep Azure Document Intelligence and other remote
plugins disabled unless the user explicitly authorizes manuscript upload.

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
