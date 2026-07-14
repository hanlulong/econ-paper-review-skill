import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

/**
 * Return Python launcher candidates without shell parsing. Keeping the launcher
 * and its arguments separate makes paths with spaces safe on every platform.
 */
export function pythonValidationCandidates(platform = process.platform, environment = process.env) {
  const configured = environment.ECON_REVIEW_PYTHON?.trim();
  if (configured) return [{ command: configured, prefix: [] }];
  return platform === "win32"
    ? [{ command: "py", prefix: ["-3"] }, { command: "python", prefix: [] }]
    : [{ command: "python3", prefix: [] }, { command: "python", prefix: [] }];
}

/** Run the canonical package validator before any review is copied to public assets. */
export function validateReviewPackageWithPython(options) {
  const {
    repositoryRoot,
    reviewRoot,
    platform = process.platform,
    environment = process.env,
    spawn = spawnSync,
  } = options;
  const validator = resolve(repositoryRoot, "econ-review/scripts/validate_review.py");
  let lastMissing = null;

  for (const candidate of pythonValidationCandidates(platform, environment)) {
    const args = [...candidate.prefix, validator, reviewRoot];
    const result = spawn(candidate.command, args, {
      cwd: repositoryRoot,
      env: environment,
      encoding: "utf8",
      windowsHide: true,
    });
    if (result.error?.code === "ENOENT") {
      lastMissing = result.error;
      continue;
    }
    if (result.error) {
      throw new Error(`Could not run the canonical Python review validator: ${result.error.message}`);
    }
    if (result.status === 0) return;

    const detail = [result.stderr, result.stdout]
      .filter((value) => typeof value === "string" && value.trim())
      .map((value) => value.trim())
      .join("\n");
    throw new Error([
      `Canonical Python validation failed for ${reviewRoot}. Review assets were not synchronized.`,
      detail || `Validator exited with status ${result.status ?? "unknown"}.`,
    ].join("\n"));
  }

  throw new Error(
    "Python 3 is required to validate a review before synchronization. "
    + `Set ECON_REVIEW_PYTHON to a Python executable if it is not on PATH${lastMissing?.message ? ` (${lastMissing.message})` : ""}.`,
  );
}
