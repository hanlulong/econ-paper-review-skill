import assert from "node:assert/strict";
import test from "node:test";
import { formatUserFacingLocator } from "../lib/review-locator.ts";

test("omits internal paths and deduplicates a section that already names the equation", () => {
  assert.equal(formatUserFacingLocator({
    file: "evidence/pdf-ingestion/SRC-01/manuscript.md",
    section: "Appendix B.2, equation (115)",
    equation: "Appendix B.2, equation (115)",
    page: 48,
  }), "Appendix B.2, equation (115) · p. 48");
});

test("keeps distinct section, equation, exhibit, page, paragraph, and line information", () => {
  assert.equal(formatUserFacingLocator({
    file: "/private/internal/source.md",
    section: "3.1",
    paragraph: "2",
    exhibit: "Table 4",
    equation: "(36)",
    page: 10,
    lines: "120-126",
  }), "Section 3.1 · para. 2 · Table 4 · Eq. (36) · p. 10 · lines 120-126");
});

test("does not prepend Eq. to an already descriptive equation label", () => {
  assert.equal(formatUserFacingLocator({ equation: "Equation (4)", page: 2 }), "Equation (4) · p. 2");
  assert.equal(formatUserFacingLocator({ file: "internal.md" }), "Manuscript");
  assert.equal(formatUserFacingLocator(undefined), "Location unavailable");
});
