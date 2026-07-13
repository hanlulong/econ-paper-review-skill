# Third-Party Components and PDF Backend Policy

This file records the present dependency boundary. It is not a substitute for
legal advice. Recheck package versions and license terms before any public or
commercial release.

## Used by the local core

| Component | License | Current use | Distribution boundary |
|---|---|---|---|
| `jsonschema` | MIT | Review-contract validation | Python dependency; not vendored |
| `pdfplumber` / `pdfminer.six` | MIT | PDF geometry and table candidates | Python dependencies; not vendored |
| `pypdf` | BSD-3-Clause | PDF structural and safety inspection | Python dependency; not vendored |
| Pillow | HPND | Image inspection and deterministic crops | Python dependency; not vendored |
| Tesseract | Apache-2.0 | Optional local prose OCR | External executable; not bundled |
| Poppler utilities | GPL | Page metadata, text geometry, and rendering | External executables; not bundled |

Invoking a separately installed executable is not permission to redistribute
its binary. If an online or desktop distribution later bundles Poppler or
Tesseract, perform a new packaging and license review first.

## Evaluated conversion backends

- [Microsoft MarkItDown](https://github.com/microsoft/markitdown) is
  [MIT-licensed](https://github.com/microsoft/markitdown/blob/main/LICENSE) and may be evaluated as an optional
  local semantic proposal backend. Its PDF conversion is not a substitute for
  page/bounding-box provenance or render verification, so it must not become
  the sole authority for equations, tables, figures, or symbols.
- [Datalab Marker](https://github.com/datalab-to/marker) is not approved for integration. Its repository code is
  [GPL-3.0](https://github.com/datalab-to/marker/blob/master/LICENSE) and its
  [model license](https://github.com/datalab-to/marker/blob/master/MODEL_LICENSE) adds commercial restrictions, including a
  competing-product restriction. Do not install, call, host, redistribute, or
  use Marker-generated output in the product without a separate written
  commercial license and legal review.
- [Nutrient/PSPDFKit PDF-to-Markdown](https://github.com/PSPDFKit/pdf-to-markdown) is not approved for integration under its
  [free license](https://github.com/PSPDFKit/pdf-to-markdown/blob/main/LICENSE.md). The license is proprietary and includes a competing-product
  restriction. Use requires a written commercial agreement and legal review.

No cloud OCR, hosted converter, or external model may receive a manuscript by
default. Any future external backend requires explicit user consent, a data
retention and confidentiality review, and a recorded processing policy.
