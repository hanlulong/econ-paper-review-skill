import assert from "node:assert/strict";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  pythonValidationCandidates,
  validateReviewPackageWithPython,
} from "../scripts/validate-review-package.mjs";

const repositoryRoot = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const reviewRoot = resolve(repositoryRoot, "tests/fixtures/valid-review");

test("selects shell-free Python launchers on Windows and POSIX", () => {
  assert.deepEqual(pythonValidationCandidates("win32", {}), [
    { command: "py", prefix: ["-3"] },
    { command: "python", prefix: [] },
  ]);
  assert.deepEqual(pythonValidationCandidates("darwin", {}), [
    { command: "python3", prefix: [] },
    { command: "python", prefix: [] },
  ]);
  assert.deepEqual(pythonValidationCandidates("win32", { ECON_REVIEW_PYTHON: "C:\\Program Files\\Python\\python.exe" }), [
    { command: "C:\\Program Files\\Python\\python.exe", prefix: [] },
  ]);
});

test("falls back only when a Python launcher is missing and passes literal paths", () => {
  const calls = [];
  const spawn = (command, args, options) => {
    calls.push({ command, args, options });
    if (calls.length === 1) return { error: Object.assign(new Error("missing"), { code: "ENOENT" }) };
    return { status: 0, stdout: "econ-review validation passed", stderr: "" };
  };
  assert.doesNotThrow(() => validateReviewPackageWithPython({
    repositoryRoot,
    reviewRoot,
    platform: "win32",
    environment: {},
    spawn,
  }));
  assert.equal(calls[0].command, "py");
  assert.deepEqual(calls[0].args.slice(0, 2), ["-3", resolve(repositoryRoot, "econ-review/scripts/validate_review.py")]);
  assert.equal(calls[0].args.at(-1), reviewRoot);
  assert.equal(calls[1].command, "python");
  assert.equal(calls[1].options.cwd, repositoryRoot);
});

test("fails closed on canonical validation errors without trying another interpreter", () => {
  let calls = 0;
  assert.throws(() => validateReviewPackageWithPython({
    repositoryRoot,
    reviewRoot,
    platform: "linux",
    environment: {},
    spawn: () => {
      calls += 1;
      return { status: 1, stdout: "", stderr: "econ-review validation failed:\n- invalid fixture" };
    },
  }), /invalid fixture/);
  assert.equal(calls, 1);
});

test("reports a clear prerequisite when no Python launcher is available", () => {
  assert.throws(() => validateReviewPackageWithPython({
    repositoryRoot,
    reviewRoot,
    platform: "win32",
    environment: {},
    spawn: () => ({ error: Object.assign(new Error("not found"), { code: "ENOENT" }) }),
  }), /Set ECON_REVIEW_PYTHON/);
});
