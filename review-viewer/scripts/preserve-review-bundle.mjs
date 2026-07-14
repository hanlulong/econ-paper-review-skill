import { lstat, mkdir, mkdtemp, rename, rm } from "node:fs/promises";
import { basename, dirname, resolve } from "node:path";

async function pathExists(path) {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

/**
 * Run an operation with the target directory absent, then restore any prior
 * directory byte-for-byte even when the operation fails.
 */
export async function withPreservedReviewBundle(reviewsRoot, operation) {
  const parent = dirname(reviewsRoot);
  await mkdir(parent, { recursive: true });
  // Keep the temporary backup outside `public/`; otherwise the site build can
  // copy a confidential pre-test bundle into dist while the test is running.
  const backupRoot = await mkdtemp(resolve(dirname(parent), ".review-test-backup-"));
  const savedReviews = resolve(backupRoot, basename(reviewsRoot));
  const existed = await pathExists(reviewsRoot);
  if (existed) await rename(reviewsRoot, savedReviews);

  try {
    return await operation();
  } finally {
    await rm(reviewsRoot, { recursive: true, force: true });
    if (existed) await rename(savedReviews, reviewsRoot);
    await rm(backupRoot, { recursive: true, force: true });
  }
}
