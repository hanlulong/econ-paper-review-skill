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
| PyYAML | MIT | Agent-skill package validation | Python dependency; not vendored |
| `requests` | Apache-2.0 | Server-side calls to an explicitly authorized Mathpix job | Python dependency; not vendored |
| Tesseract | Apache-2.0 | Optional local prose OCR | External executable; not bundled |
| Poppler utilities | GPL | Page metadata, text geometry, and rendering | External executables; not bundled |

Invoking a separately installed executable is not permission to redistribute
its binary. If an online or desktop distribution later bundles Poppler or
Tesseract, perform a new packaging and license review first.

## Review Desk dependency boundary

The Review Desk's direct JavaScript dependencies are declared in
`review-viewer/package.json`, and `package-lock.json` records the exact resolved
tree. They are downloaded by npm and are not vendored in this source archive.
The tree is predominantly permissively licensed, but current transitive build
and image dependencies also include MPL-2.0 components and libvips platform
packages under LGPL-3.0-or-later. A production build or hosted deployment may
therefore carry notice, source-availability, relinking, or other obligations
that do not arise merely from publishing this source tree.

Before a commercial deployment, generate an SBOM from the exact lockfile,
identify which transitive components enter the deployed artifact, preserve all
required notices, and obtain a legal review of the resulting distribution and
hosting model. `npm audit` checks known security advisories; it is not a license
or attribution audit.

## Evaluated conversion backends

- [Docling](https://github.com/docling-project/docling) is an optional local
  semantic-structure proposal backend. Its repository code is
  [MIT-licensed](https://github.com/docling-project/docling/blob/main/LICENSE),
  while model artifacts have separate licenses and revision histories. The
  lightweight install does not include Docling. `requirements-docling.txt`
  pins the evaluated code version; model downloads remain a separate explicit
  action. Re-audit code, transitive dependencies, model licenses, and model
  revisions before distribution or a hosted release.
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

## Hosted service boundary

[Mathpix PDF API](https://docs.mathpix.com/reference/post-v3-pdf) is an optional
hosted premium service, not bundled software. A call transmits the complete PDF
to Mathpix and is permitted only after manuscript-specific upload authorization
and acknowledgement of the current provider-retention policy. The adapter reads
its permissively licensed HTTP client from the separately installed
`requirements-mathpix.txt` environment. Mathpix itself remains governed by the
customer's service contract and is not redistributed by this project. The adapter
reads credentials from server-side environment variables, requests remote deletion,
and stores a non-secret deletion receipt. Deletion confirmation does not promise
instant removal from every cache, billing record, or audit system.

Before commercial launch, review the current Mathpix pricing, privacy and
[data-retention terms](https://docs.mathpix.com/concepts/data-retention), obtain
any required data-processing agreement or written product-use confirmation, and
confirm the restriction on using service output to develop competing models.
Provider terms and prices can change independently of this repository.

No cloud OCR, hosted converter, or external model may receive a manuscript by
default. Any future external backend requires explicit user consent, a data
retention and confidentiality review, and a recorded processing policy.
