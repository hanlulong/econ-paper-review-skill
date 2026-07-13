import assert from "node:assert/strict";
import test from "node:test";

import {
  inferReviewPackageRoot,
  matchReferencedImagePaths,
  normalizePackagePath,
  referencedExhibitPaths,
  relativeToReviewRoot,
  selectReviewPackageFilePath,
  selectManuscriptPath,
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
    paths: ["findings.json", "run.json", "draft.md", "README.md", "report.md"],
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
