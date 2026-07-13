import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";

import { withPreservedReviewBundle } from "../scripts/preserve-review-bundle.mjs";

async function fixture() {
  const root = await mkdtemp(resolve(tmpdir(), "review-bundle-test-"));
  const reviews = resolve(root, "reviews");
  await mkdir(reviews);
  await writeFile(resolve(reviews, "original.txt"), "original", "utf8");
  return { root, reviews };
}

test("restores a pre-existing review bundle after a successful test operation", async () => {
  const { root, reviews } = await fixture();
  try {
    await withPreservedReviewBundle(reviews, async () => {
      await mkdir(reviews);
      await writeFile(resolve(reviews, "synthetic.txt"), "synthetic", "utf8");
    });
    assert.equal(await readFile(resolve(reviews, "original.txt"), "utf8"), "original");
    await assert.rejects(readFile(resolve(reviews, "synthetic.txt"), "utf8"), /ENOENT/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("restores a pre-existing review bundle after a failed test operation", async () => {
  const { root, reviews } = await fixture();
  try {
    await assert.rejects(withPreservedReviewBundle(reviews, async () => {
      await mkdir(reviews);
      await writeFile(resolve(reviews, "synthetic.txt"), "synthetic", "utf8");
      throw new Error("expected failure");
    }), /expected failure/);
    assert.equal(await readFile(resolve(reviews, "original.txt"), "utf8"), "original");
    await assert.rejects(readFile(resolve(reviews, "synthetic.txt"), "utf8"), /ENOENT/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("runs when the review bundle parent does not exist in a fresh checkout", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "review-bundle-test-"));
  const reviews = resolve(root, "missing-parent", "reviews");
  try {
    await withPreservedReviewBundle(reviews, async () => {
      await mkdir(reviews);
      await writeFile(resolve(reviews, "synthetic.txt"), "synthetic", "utf8");
    });
    await assert.rejects(readFile(resolve(reviews, "synthetic.txt"), "utf8"), /ENOENT/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
