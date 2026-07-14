import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";

import {
  discoverReviewDocuments,
  isSafeReviewDocumentPath,
  markdownHeadingSlug,
  resolveReviewDocumentLink,
  resolveReviewDocumentHref,
  safeExternalReviewDocumentHref,
  sortReviewDocuments,
  validateReviewDocumentManifest,
} from "../lib/review-documents.ts";

const FIXTURE = new URL("../../tests/fixtures/valid-review/", import.meta.url);

test("validates arbitrary review documents and rejects ambiguous manifests", async () => {
  const fixtureManifest = await readFile(new URL("review-manifest.json", FIXTURE), "utf8");
  const parsed = validateReviewDocumentManifest(fixtureManifest);
  assert.equal(parsed.review_id, "synthetic-valid-001");
  assert.deepEqual(parsed.documents.map((document) => document.path), [
    "README.md",
    "report.md",
    "editing-comments.md",
    "fix-plan.md",
  ]);

  const arbitrary = validateReviewDocumentManifest({
    schema_version: "0.1",
    review_id: "review-001",
    documents: [
      { id: "mechanism-note", title: "Mechanism note", group: "reports", path: "reports/mechanism-note.md", order: 70 },
    ],
  });
  assert.deepEqual(arbitrary.documents.map((document) => document.path), ["reports/mechanism-note.md"]);

  for (const broken of [
    { ...arbitrary, extra: true },
    { ...arbitrary, documents: [{ ...arbitrary.documents[0], id: "Mechanism Note" }] },
    { ...arbitrary, documents: [{ ...arbitrary.documents[0], title: " Mechanism note" }] },
    { ...arbitrary, documents: [{ ...arbitrary.documents[0], title: "Mechanism\nnote" }] },
    { ...arbitrary, documents: [...arbitrary.documents, { ...arbitrary.documents[0] }] },
    { ...arbitrary, documents: [{ ...arbitrary.documents[0], path: "reports/mechanism-note.txt" }] },
  ]) {
    assert.throws(() => validateReviewDocumentManifest(broken));
  }
});

test("rejects traversal, URLs, platform aliases, and non-Markdown paths", () => {
  for (const path of [
    "report.md",
    "reports/custom-analysis.md",
    "evidence/Table audit (appendix).md",
  ]) assert.equal(isSafeReviewDocumentPath(path), true, path);

  for (const path of [
    "../secret.md",
    "reports/../../secret.md",
    "/absolute/report.md",
    "reports\\windows.md",
    "https://example.com/report.md",
    "C:/review/report.md",
    "reports//empty.md",
    "reports/.hidden.md",
    "reports/report.md?download=1",
    "reports/report.txt",
    " reports/report.md",
    "audit./report.md",
    "e\u0301vidence/report.md",
    "audit/bad\u0000name.md",
    "audit/CON.md",
  ]) assert.equal(isSafeReviewDocumentPath(path), false, path);
});

test("rejects document paths that collide on common case-insensitive filesystems", () => {
  assert.throws(() => validateReviewDocumentManifest({
    schema_version: "0.1",
    review_id: "review-001",
    documents: [
      { id: "mechanism-note", title: "Mechanism note", group: "reports", path: "reports/mechanism-note.md", order: 70 },
      { id: "mechanism-copy", title: "Mechanism copy", group: "reports", path: "Reports/mechanism-note.md", order: 71 },
    ],
  }), /case-unambiguous/);
});

test("allows only explicit HTTP(S) links outside declared review documents", () => {
  assert.equal(safeExternalReviewDocumentHref("https://example.test/paper?q=1"), "https://example.test/paper?q=1");
  assert.equal(safeExternalReviewDocumentHref("HTTP://example.test/paper"), "http://example.test/paper");
  for (const unsafe of ["/internal", "../outside.md", "javascript:alert(1)", "data:text/html,x", "file:///private/paper.pdf", " https://example.test"]) {
    assert.equal(safeExternalReviewDocumentHref(unsafe), null);
  }
});

test("sorts documents by stable group, explicit order, title, ID, and path", () => {
  const input = [
    { id: "audit-z", title: "Zeta", group: "audit", path: "audit/zeta.md", order: 1 },
    { id: "report-b", title: "Beta", group: "reports", path: "reports/beta.md", order: 20 },
    { id: "overview-b", title: "Beta", group: "overview", path: "overview/beta.md", order: 20 },
    { id: "overview-a", title: "Alpha", group: "overview", path: "overview/alpha.md", order: 20 },
    { id: "plan-a", title: "Alpha", group: "plan", path: "plan/alpha.md", order: 0 },
    { id: "report-a", title: "Alpha", group: "reports", path: "reports/alpha.md", order: 20 },
  ];
  assert.deepEqual(sortReviewDocuments(input).map((document) => document.id), [
    "overview-a",
    "overview-b",
    "report-a",
    "report-b",
    "plan-a",
    "audit-z",
  ]);
  assert.equal(input[0].id, "audit-z", "sorting must not mutate the caller's array");
});

test("resolves only manifest-known relative Markdown links", () => {
  const documents = [
    { id: "start", title: "Start", group: "overview", path: "README.md", order: 0 },
    { id: "report", title: "Report", group: "overview", path: "report.md", order: 10 },
    { id: "audit", title: "Audit", group: "audit", path: "evidence/audit.md", order: 10 },
  ];
  assert.equal(resolveReviewDocumentHref("README.md", "report.md", documents)?.id, "report");
  assert.equal(resolveReviewDocumentHref("evidence/audit.md", "../report.md#top", documents)?.id, "report");
  assert.equal(resolveReviewDocumentHref("README.md", "missing.md", documents), null);
  assert.equal(resolveReviewDocumentHref("README.md", "https://example.com/report.md", documents), null);
  assert.equal(resolveReviewDocumentHref("README.md", "../outside.md", documents), null);
});

test("preserves safe same-document and cross-document fragments without resolving external URLs", () => {
  const documents = [
    { id: "start", title: "Start", group: "overview", path: "README.md", order: 0 },
    { id: "report", title: "Report", group: "overview", path: "report.md", order: 10 },
  ];
  assert.deepEqual(resolveReviewDocumentLink("README.md", "report.md#1-main-concern", documents), {
    document: documents[1],
    fragment: "1-main-concern",
  });
  assert.deepEqual(resolveReviewDocumentLink("report.md", "#unknown-but-safe", documents), {
    document: documents[1],
    fragment: "unknown-but-safe",
  });
  assert.equal(resolveReviewDocumentLink("README.md", "https://example.com/report.md#private", documents), null);
  assert.equal(resolveReviewDocumentLink("README.md", "javascript:alert(1)", documents), null);
  assert.equal(resolveReviewDocumentLink("README.md", "report.md#bad%00fragment", documents), null);
});

test("heading slugs match generated numbered report anchors", () => {
  assert.equal(markdownHeadingSlug("1. Main concern: scope & evidence"), "1-main-concern-scope-evidence");
  assert.equal(markdownHeadingSlug("Section 3.4 — sample exclusions"), "section-34-sample-exclusions");
  assert.equal(markdownHeadingSlug(""), "section");
});

test("discovers manifest documents and conservative standard report groups", () => {
  const manifest = {
    schema_version: "0.1",
    review_id: "arbitrary-review",
    documents: [
      { id: "overview", title: "Editorial overview", group: "overview", path: "overview/editorial.md", order: 4 },
      { id: "custom-report", title: "Custom robustness report", group: "reports", path: "reports/robustness.md", order: 8 },
      { id: "custom-plan", title: "Round two plan", group: "plan", path: "plan/round-two.md", order: 3 },
      { id: "custom-audit", title: "Symbol audit", group: "audit", path: "audit/symbols.md", order: 2 },
    ],
  };
  const paths = manifest.documents.map((document) => document.path);
  assert.deepEqual(discoverReviewDocuments(paths, manifest).map((document) => document.id), [
    "overview",
    "custom-report",
    "custom-plan",
    "custom-audit",
  ]);
  assert.throws(
    () => discoverReviewDocuments(paths.slice(1), manifest),
    /references missing files: overview\/editorial\.md/,
  );

  const discovered = discoverReviewDocuments([
    "notes.md",
    "README.md",
    "report.md",
    "editing-comments.md",
    "writing-report.md",
    "fix-plan.md",
    "reports/mechanism-note.md",
    "plan/round-two.md",
    "evidence/custom-proof-audit.md",
  ]);
  assert.deepEqual(discovered.map((document) => document.path), [
    "README.md",
    "report.md",
    "editing-comments.md",
    "reports/mechanism-note.md",
    "fix-plan.md",
    "plan/round-two.md",
    "evidence/custom-proof-audit.md",
  ]);
  assert.equal(discovered.some((document) => document.path === "notes.md"), false);
  assert.equal(discovered.some((document) => document.path === "writing-report.md"), false);
  assert.deepEqual(
    discovered.find((document) => document.path === "editing-comments.md"),
    { id: "editing-comments", title: "Editing comments", group: "reports", path: "editing-comments.md", order: 10 },
  );
});

test("the synthetic manifest exposes every author-facing document and keeps audit working papers internal", async () => {
  const manifest = validateReviewDocumentManifest(await readFile(new URL("review-manifest.json", FIXTURE), "utf8"));
  const entries = await readdir(FIXTURE, { recursive: true, withFileTypes: true });
  const markdown = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".md"))
    .map((entry) => {
      const parent = entry.parentPath.replace(new URL(FIXTURE).pathname.replace(/\/$/, ""), "").replace(/^\//, "");
      return parent ? `${parent}/${entry.name}` : entry.name;
    })
    .filter((path) => path !== "synthetic-paper.md")
    .sort();
  const authorFacing = markdown.filter((path) => !path.startsWith("evidence/"));
  const internalAudits = markdown.filter((path) => path.startsWith("evidence/"));
  assert.deepEqual(manifest.documents.map((document) => document.path).sort(), authorFacing);
  assert.ok(internalAudits.length > 0, "the fixture must exercise internal audit working papers");
  assert.equal(manifest.documents.some((document) => document.path.startsWith("evidence/")), false);
});

test("every synced manifest reference exists and remains inside its synthetic bundle", async () => {
  const registry = JSON.parse(await readFile(new URL("../public/reviews/index.json", import.meta.url), "utf8"));
  for (const entry of registry.reviews) {
    const base = new URL(`../public/reviews/${entry.slug}/`, import.meta.url);
    const manifest = validateReviewDocumentManifest(await readFile(new URL("review-manifest.json", base), "utf8"));
    const run = JSON.parse(await readFile(new URL("run.json", base), "utf8"));
    const sourceManifest = JSON.parse(await readFile(new URL("evidence/source-manifest.json", base), "utf8"));
    const sourceMarkdown = new Set(sourceManifest.sources.flatMap((source) => [source.path, source.extraction?.path])
      .filter((path) => typeof path === "string" && /\.md$/i.test(path)));
    assert.equal(manifest.review_id, run.review_id);
    for (const document of manifest.documents) {
      assert.equal(isSafeReviewDocumentPath(document.path), true);
      assert.ok((await readFile(new URL(document.path, base), "utf8")).trim().length > 0, document.path);
    }
    const bundledEntries = await readdir(base, { recursive: true, withFileTypes: true });
    const bundledMarkdown = bundledEntries
      .filter((candidate) => candidate.isFile() && candidate.name.endsWith(".md"))
      .map((candidate) => {
        const parent = candidate.parentPath.replace(new URL(base).pathname.replace(/\/$/, ""), "").replace(/^\//, "");
        return parent ? `${parent}/${candidate.name}` : candidate.name;
      })
      .filter((path) => !sourceMarkdown.has(path) && !path.startsWith("evidence/"))
      .sort();
    assert.deepEqual(
      bundledMarkdown,
      manifest.documents.map((document) => document.path).sort(),
      "bundles must not expose undeclared Markdown documents",
    );
  }
});
