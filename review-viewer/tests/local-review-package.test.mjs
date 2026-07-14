import assert from "node:assert/strict";
import test from "node:test";

import {
  inferReviewPackageRoot,
  matchReferencedImagePaths,
  normalizePackagePath,
  normalizeSelectedPackagePath,
  referencedExhibitHashes,
  referencedExhibitPaths,
  relativeToReviewRoot,
  reviewImageMediaType,
  selectReviewPackageFilePath,
  selectManuscriptPath,
  sha256ReviewBytes,
  validateExhibitManifest,
} from "../lib/local-review-package.ts";

test("infers a review root from its canonical pair without requiring a folder name", () => {
  const paths = [
    "paper/revision-output/findings.json",
    "paper/revision-output/run.json",
    "paper/revision-output/reports/referee.md",
    "paper/manuscript-v2.md",
  ];
  assert.equal(inferReviewPackageRoot(paths), "paper/revision-output");
  assert.equal(relativeToReviewRoot(paths[2], "paper/revision-output"), "reports/referee.md");
  assert.equal(relativeToReviewRoot(paths[3], "paper/revision-output"), null);
});

test("rejects missing, multiple, duplicate, and unsafe package roots", () => {
  assert.throws(() => inferReviewPackageRoot(["a/findings.json"]), /both findings\.json and run\.json/);
  assert.throws(() => inferReviewPackageRoot([
    "a/findings.json", "a/run.json", "b/findings.json", "b/run.json",
  ]), /Multiple complete review packages/);
  assert.throws(() => normalizePackagePath("review/../findings.json"), /Unsafe relative path/);
  for (const unsafe of [
    "/review/findings.json",
    "./review/findings.json",
    "review\\findings.json",
    "C:/review/findings.json",
    "review//findings.json",
    "review/./findings.json",
    "review/trailing.",
    "review/ spaced /findings.json",
    "review/e\u0301.json",
    "review/\u0000.png",
    "review/CON",
    "review/nul.txt",
    "review/Clock$.json",
    "review/com1.md",
    "review/LPT9.png",
  ]) {
    assert.throws(() => normalizePackagePath(unsafe), /Unsafe relative path/);
  }
  for (const portable of ["review/console.md", "review/com10.md", "review/lpt0.png"]) {
    assert.equal(normalizePackagePath(portable), portable);
  }
  assert.equal(normalizeSelectedPackagePath("review/e\u0301vidence.md"), "review/\u00e9vidence.md");
});

test("selects only a source-matched manuscript when run metadata is available", () => {
  const selected = selectManuscriptPath({
    paths: [
      "paper/output/findings.json",
      "paper/output/run.json",
      "paper/output/reports/methods.md",
      "paper/notes.md",
      "paper/test-paper-v2.md",
    ],
    reviewRoot: "paper/output",
    declaredDocumentPaths: ["reports/methods.md"],
    sourcePaths: ["/private/work/test-paper-v2.md"],
  });
  assert.equal(selected, "paper/test-paper-v2.md");
  assert.equal(selectManuscriptPath({
    paths: ["output/findings.json", "output/run.json", "notes.md"],
    reviewRoot: "output",
    sourcePaths: ["actual-paper.md"],
  }), null);
});

test("rejects ambiguous manuscript matches and permits one unambiguous individual file", () => {
  assert.throws(() => selectManuscriptPath({
    paths: ["findings.json", "run.json", "one/paper.md", "two/paper.md"],
    reviewRoot: "",
    sourcePaths: ["paper.md"],
  }), /Multiple manuscript files match/);
  assert.equal(selectManuscriptPath({
    paths: ["findings.json", "run.json", "draft.md", "README.md", "report.md", "editing-comments.md"],
    reviewRoot: "",
  }), "draft.md");
});

test("selects a generated PDF transcription from its source-manifest extraction path", () => {
  assert.equal(selectManuscriptPath({
    paths: [
      "paper/review/findings.json",
      "paper/review/run.json",
      "paper/review/evidence/pdf-ingestion/manuscript.md",
      "paper/review/evidence/notes.md",
    ],
    reviewRoot: "paper/review",
    sourcePaths: ["evidence/pdf-ingestion/manuscript.md", "evidence/pdf-ingestion/source/original.pdf"],
  }), "paper/review/evidence/pdf-ingestion/manuscript.md");
});

test("maps only uniquely referenced exhibit images", () => {
  const tables = { tables: [{ render_paths: ["renders/table-1.png"] }] };
  const figures = { figures: [{ extraction_paths: ["renders/figure-1.png", "renders/shared.png"] }] };
  const references = referencedExhibitPaths(tables, figures);
  assert.deepEqual(references, ["renders/table-1.png", "renders/figure-1.png", "renders/shared.png"]);
  const matches = matchReferencedImagePaths([
    "bundle/renders/table-1.png",
    "bundle/renders/figure-1.png",
    "bundle/a/renders/shared.png",
    "bundle/b/renders/shared.png",
    "bundle/unrelated.png",
    "another-package/renders/table-1.png",
  ], "bundle", references);
  assert.equal(matches.get("renders/table-1.png"), "bundle/renders/table-1.png");
  assert.equal(matches.get("renders/figure-1.png"), "bundle/renders/figure-1.png");
  assert.equal(matches.get("renders/shared.png"), null);
  assert.equal(Array.from(matches.values()).includes("bundle/unrelated.png"), false);
});

test("loads current figure assets and preserves their immutable hashes", () => {
  const figures = {
    schema_version: "0.2",
    review_id: "review-1",
    no_figures_confirmed: false,
    figures: [{
      label: "Figure 1: Main result",
      source_id: "SRC-01",
      pdf_pages: [4],
      source_locator: { source_id: "SRC-01", pages: [4] },
      identity_keys: ["Figure 1", "Main result"],
      assessment_boundary: null,
      rendered_assets: [
        {
          path: "evidence/figures/figure-1.png", sha256: "a".repeat(64), render_type: "crop",
          pdf_page: 4, source_object_id: "SRC-01-PDF-FIG-001",
          visible_identity: { basis: "figure_label", text: "Figure 1: Main result", status: "matched", notes: "Visible label matches the row." },
        },
        {
          path: "evidence/renders/page-0004.png", sha256: "b".repeat(64), render_type: "full_page",
          pdf_page: 4, source_object_id: null,
          visible_identity: { basis: "figure_label", text: "Figure 1: Main result", status: "matched", notes: "Full-page context shows the same label." },
        },
      ],
    }],
  };
  const checked = validateExhibitManifest(figures, "figures", "review-1");
  assert.deepEqual(referencedExhibitPaths(null, checked), [
    "evidence/figures/figure-1.png",
    "evidence/renders/page-0004.png",
  ]);
  assert.deepEqual(Array.from(referencedExhibitHashes(null, checked)), [
    ["evidence/figures/figure-1.png", "a".repeat(64)],
    ["evidence/renders/page-0004.png", "b".repeat(64)],
  ]);
  assert.throws(() => validateExhibitManifest({ ...figures, review_id: "other" }, "figures", "review-1"), /different review ID/);
  assert.throws(() => validateExhibitManifest({ ...figures, figures: [] }, "figures", "review-1"), /inventory state contradicts/);
});

test("loads current table assets, roles, and immutable hashes", () => {
  const tables = {
    schema_version: "0.2",
    review_id: "review-1",
    no_tables_confirmed: false,
    tables: [{
      label: "Table 1: Main estimates",
      source_id: "SRC-01",
      pdf_pages: [7],
      source_locator: { source_id: "SRC-01", pages: [7] },
      identity_keys: ["Table 1", "Main estimates"],
      assessment_boundary: null,
      render_status: "inspected",
      rendered_assets: [
        {
          path: "evidence/tables/table-1.png", sha256: "c".repeat(64), render_type: "crop",
          pdf_page: 7, source_object_id: "SRC-01-PDF-TBL-001",
          visible_identity: { basis: "table_label", text: "Table 1: Main estimates", status: "matched", notes: "Visible title matches the row." },
        },
        {
          path: "evidence/renders/page-0007.png", sha256: "d".repeat(64), render_type: "full_page",
          pdf_page: 7, source_object_id: null,
          visible_identity: { basis: "table_label", text: "Table 1: Main estimates", status: "matched", notes: "Full-page context shows the same title." },
        },
      ],
    }],
  };
  const checked = validateExhibitManifest(tables, "tables", "review-1");
  assert.deepEqual(referencedExhibitPaths(checked, null), [
    "evidence/tables/table-1.png",
    "evidence/renders/page-0007.png",
  ]);
  assert.deepEqual(Array.from(referencedExhibitHashes(checked, null)), [
    ["evidence/tables/table-1.png", "c".repeat(64)],
    ["evidence/renders/page-0007.png", "d".repeat(64)],
  ]);
  const bounded = validateExhibitManifest({
    ...tables,
    tables: [{
      ...tables.tables[0], label: "Table 1", render_status: "bounded", rendered_assets: [],
      assessment_boundary: {
        checked_scope: "The available table extraction.",
        status_basis: "unreadable_render",
        reason: "No complete render is available.",
        missing_input: "A readable table render.",
        decisive_evidence_needed: "A complete image of the table.",
      },
    }],
  }, "tables", "review-1");
  assert.deepEqual(referencedExhibitPaths(bounded, null), []);
  assert.throws(() => validateExhibitManifest({
    ...tables,
    tables: [{ ...tables.tables[0], label: "Table 1", rendered_assets: [] }],
  }, "tables", "review-1"), /no rendered assets/);
});

test("rejects malformed exhibit boundaries and page bindings before local display", () => {
  const base = {
    schema_version: "0.2",
    review_id: "review-1",
    no_tables_confirmed: false,
    tables: [{
      label: "Table 1",
      source_id: "SRC-01",
      pdf_pages: [7],
      source_locator: { source_id: "SRC-01", pages: [7] },
      identity_keys: ["Table 1"],
      render_status: "bounded",
      assessment_boundary: {
        checked_scope: "The available page.",
        status_basis: "unreadable_render",
        reason: "The table is unreadable.",
        missing_input: "A legible render.",
        decisive_evidence_needed: "A legible full-page image.",
      },
      rendered_assets: [],
    }],
  };
  const missingBoundaryField = structuredClone(base);
  delete missingBoundaryField.tables[0].assessment_boundary.missing_input;
  assert.throws(() => validateExhibitManifest(missingBoundaryField, "tables", "review-1"), /malformed assessment_boundary/);

  const unboundedWithBoundary = structuredClone(base);
  unboundedWithBoundary.tables[0].render_status = "inspected";
  unboundedWithBoundary.tables[0].rendered_assets = [{
    path: "evidence/tables/table-1.png", sha256: "a".repeat(64), render_type: "crop",
    pdf_page: 7, source_object_id: "SRC-01-PDF-TBL-001",
    visible_identity: { basis: "table_label", text: "Table 1", status: "matched", notes: "The label is visible." },
  }];
  assert.throws(() => validateExhibitManifest(unboundedWithBoundary, "tables", "review-1"), /must set assessment_boundary to null/);

  const locatorMismatch = structuredClone(base);
  locatorMismatch.tables[0].source_locator.pages = [8];
  assert.throws(() => validateExhibitManifest(locatorMismatch, "tables", "review-1"), /source locator pages differ/);

  const assetPageMismatch = structuredClone(unboundedWithBoundary);
  assetPageMismatch.tables[0].assessment_boundary = null;
  assetPageMismatch.tables[0].rendered_assets[0].pdf_page = 8;
  assert.throws(() => validateExhibitManifest(assetPageMismatch, "tables", "review-1"), /page differs from pdf_pages/);
});

test("rejects duplicate or conflicting current exhibit asset roles", () => {
  const asset = {
    path: "evidence/renders/page-0004.png", sha256: "b".repeat(64), render_type: "full_page",
    pdf_page: 4, source_object_id: null,
    visible_identity: { basis: "figure_label", text: "Figure 1", status: "matched", notes: "The label is visible." },
  };
  const figures = {
    schema_version: "0.2",
    review_id: "review-1",
    no_figures_confirmed: false,
    figures: [{
      label: "Figure 1", source_id: "SRC-01", pdf_pages: [4],
      source_locator: { source_id: "SRC-01", pages: [4] }, identity_keys: ["Figure 1"],
      assessment_boundary: null, rendered_assets: [asset],
    }],
  };
  const duplicatePath = structuredClone(figures);
  duplicatePath.figures[0].rendered_assets.push(structuredClone(asset));
  assert.throws(() => validateExhibitManifest(duplicatePath, "figures", "review-1"), /duplicate rendered asset path/);

  const duplicateRole = structuredClone(figures);
  duplicateRole.figures[0].rendered_assets.push({ ...structuredClone(asset), path: "evidence/renders/alternate-page-0004.png" });
  assert.throws(() => validateExhibitManifest(duplicateRole, "figures", "review-1"), /duplicate full-page role/);

  const cropOnly = structuredClone(figures);
  cropOnly.figures[0].rendered_assets[0] = {
    ...cropOnly.figures[0].rendered_assets[0], render_type: "crop", source_object_id: "SRC-01-PDF-FIG-001",
  };
  assert.throws(() => validateExhibitManifest(cropOnly, "figures", "review-1"), /full-page assets do not cover pdf_pages/);

  const incompletePageContext = structuredClone(figures);
  incompletePageContext.figures[0].pdf_pages = [4, 5];
  incompletePageContext.figures[0].source_locator.pages = [4, 5];
  assert.throws(() => validateExhibitManifest(incompletePageContext, "figures", "review-1"), /full-page assets do not cover pdf_pages/);

  const conflictingOwner = structuredClone(figures);
  conflictingOwner.figures.push({
    ...structuredClone(conflictingOwner.figures[0]),
    label: "Figure 2",
    identity_keys: ["Figure 2"],
    rendered_assets: [{
      ...structuredClone(asset), render_type: "crop", source_object_id: "SRC-01-PDF-FIG-002",
      visible_identity: { ...structuredClone(asset.visible_identity), text: "Figure 2" },
    }],
  });
  assert.throws(() => validateExhibitManifest(conflictingOwner, "figures", "review-1"), /conflicting rows or roles/);
});

test("rejects disguised local exhibit files and verifies selected bytes", async () => {
  const png = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const jpeg = Uint8Array.from([0xff, 0xd8, 0xff, 0xdb]);
  const webp = Uint8Array.from([0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50]);
  assert.equal(reviewImageMediaType("renders/a.png", png), "image/png");
  assert.equal(reviewImageMediaType("renders/a.jpeg", jpeg), "image/jpeg");
  assert.equal(reviewImageMediaType("renders/a.webp", webp), "image/webp");
  assert.throws(() => reviewImageMediaType("renders/a.png", new TextEncoder().encode("<script>")), /not a valid PNG/);
  assert.throws(() => reviewImageMediaType("renders/a.jpg", png), /matching its extension/);
  assert.equal(await sha256ReviewBytes(new TextEncoder().encode("abc")), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});

test("selects canonical evidence manifests from a normal generated review package", () => {
  const paths = [
    "paper/review/findings.json",
    "paper/review/run.json",
    "paper/review/evidence/figures.json",
    "paper/review/evidence/tables.json",
    "paper/review/evidence/figures/figure-1.png",
  ];
  assert.equal(selectReviewPackageFilePath({
    paths,
    reviewRoot: "paper/review",
    canonicalPath: "evidence/figures.json",
    fallbackPaths: ["figures.json"],
  }), "paper/review/evidence/figures.json");
  assert.equal(selectReviewPackageFilePath({
    paths,
    reviewRoot: "paper/review",
    canonicalPath: "evidence/tables.json",
    fallbackPaths: ["tables.json"],
  }), "paper/review/evidence/tables.json");
});

test("prefers canonical evidence manifests and falls back to legacy root manifests", () => {
  assert.equal(selectReviewPackageFilePath({
    paths: ["review/evidence/figures.json", "review/figures.json"],
    reviewRoot: "review",
    canonicalPath: "evidence/figures.json",
    fallbackPaths: ["figures.json"],
  }), "review/evidence/figures.json");
  assert.equal(selectReviewPackageFilePath({
    paths: ["review/figures.json"],
    reviewRoot: "review",
    canonicalPath: "evidence/figures.json",
    fallbackPaths: ["figures.json"],
  }), "review/figures.json");
  assert.throws(() => selectReviewPackageFilePath({
    paths: ["review/evidence/figures.json", "review/evidence/Figures.json"],
    reviewRoot: "review",
    canonicalPath: "evidence/figures.json",
    fallbackPaths: ["figures.json"],
  }), /Multiple evidence\/figures\.json files/);
});
