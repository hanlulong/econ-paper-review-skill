import { readdir, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const viewerRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const distClient = resolve(viewerRoot, "dist/client");

let copiedTestBackups = [];
try {
  copiedTestBackups = (await readdir(distClient))
    .filter((name) => name.startsWith(".review-test-backup-"))
    .map((name) => resolve(distClient, name));
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}

await Promise.all([
  rm(resolve(viewerRoot, "public/reviews"), { recursive: true, force: true }),
  rm(resolve(viewerRoot, "public/sample-review"), { recursive: true, force: true }),
  rm(resolve(viewerRoot, "dist/client/reviews"), { recursive: true, force: true }),
  rm(resolve(viewerRoot, "dist/client/sample-review"), { recursive: true, force: true }),
  ...copiedTestBackups.map((path) => rm(path, { recursive: true, force: true })),
]);
