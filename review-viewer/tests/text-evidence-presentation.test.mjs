import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  EvidenceSemanticFrame,
  textEvidencePresentation,
} from "../lib/review-text-evidence-presentation.ts";

test("uses source-excerpt presentation only for source-derived representations", () => {
  assert.deepEqual(textEvidencePresentation("verbatim"), {
    kind: "source_excerpt",
    label: "Verbatim source excerpt",
  });
  assert.deepEqual(textEvidencePresentation("normalized_transcription"), {
    kind: "source_excerpt",
    label: "Rendered source transcription",
  });
});

test("maps every reviewer-derived representation to a neutral, accurate evidence note", () => {
  const matrix = {
    reviewer_observation: "Reviewer observation",
    composite_comparison: "Reviewer comparison",
    computed_result: "Computed result",
    checked_absence: "Checked absence",
  };
  for (const [representation, label] of Object.entries(matrix)) {
    assert.deepEqual(textEvidencePresentation(representation), { kind: "evidence_note", label });
  }
});

test("missing legacy representation does not imply a quotation", () => {
  assert.deepEqual(textEvidencePresentation(), {
    kind: "evidence_note",
    label: "Evidence note",
  });
});

test("renders the representation matrix with source excerpts and neutral notes", () => {
  for (const representation of ["verbatim", "normalized_transcription"]) {
    const html = renderToStaticMarkup(React.createElement(
      EvidenceSemanticFrame,
      { representation },
      "[Rendered transcription] Source content.",
    ));
    assert.match(html, /^<blockquote class="source-excerpt" aria-label="[^"]+">/);
    assert.doesNotMatch(html, /role="note"|evidence-note/);
  }

  for (const representation of ["reviewer_observation", "composite_comparison", "computed_result", "checked_absence"]) {
    const html = renderToStaticMarkup(React.createElement(
      EvidenceSemanticFrame,
      { representation },
      "[Reviewer comparison] Reviewer-derived content.",
    ));
    assert.match(html, /^<div class="evidence-note" role="note" aria-label="[^"]+">/);
    assert.doesNotMatch(html, /<blockquote|source-excerpt/);
  }
});

test("representation beats a misleading legacy prefix and compact mode keeps identical semantics", () => {
  const content = "[Rendered transcription] This prefix remains visible exactly once.";
  const full = renderToStaticMarkup(React.createElement(EvidenceSemanticFrame, { representation: "reviewer_observation" }, content));
  const compact = renderToStaticMarkup(React.createElement(EvidenceSemanticFrame, { representation: "reviewer_observation", compact: true }, content));
  for (const html of [full, compact]) {
    assert.match(html, /role="note" aria-label="Reviewer observation"/);
    assert.doesNotMatch(html, /<blockquote|source-excerpt/);
    assert.equal((html.match(/\[Rendered transcription\]/g) || []).length, 1);
  }
  assert.match(compact, /class="evidence-note compact"/);
});
