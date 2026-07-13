import assert from "node:assert/strict";
import test from "node:test";

import { validateReviewRegistry } from "../lib/review-registry.ts";

const registry = {
  schema_version: 1,
  default_review: "synthetic-review",
  reviews: [{
    slug: "synthetic-review",
    title: "Synthetic Review",
    base_path: "/reviews/synthetic-review",
  }],
};

test("accepts a canonical same-origin review registry", () => {
  assert.deepEqual(validateReviewRegistry(registry), registry);
});

test("rejects malformed, ambiguous, or cross-origin registry entries", () => {
  for (const value of [
    { ...registry, schema_version: 2 },
    { ...registry, extra: true },
    { ...registry, default_review: "missing" },
    { ...registry, reviews: [] },
    { ...registry, reviews: [{ ...registry.reviews[0], slug: "../review" }] },
    { ...registry, default_review: "con", reviews: [{ slug: "con", title: "Reserved review", base_path: "/reviews/con" }] },
    { ...registry, reviews: [{ ...registry.reviews[0], title: " Review " }] },
    { ...registry, reviews: [{ ...registry.reviews[0], base_path: "https://example.test/review" }] },
    { ...registry, reviews: [registry.reviews[0], { ...registry.reviews[0] }] },
  ]) assert.throws(() => validateReviewRegistry(value), /Review registry/);
});
