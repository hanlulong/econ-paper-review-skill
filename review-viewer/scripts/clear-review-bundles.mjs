import { rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const viewerRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

await Promise.all([
  rm(resolve(viewerRoot, "public/reviews"), { recursive: true, force: true }),
  rm(resolve(viewerRoot, "public/sample-review"), { recursive: true, force: true }),
  rm(resolve(viewerRoot, "dist/client/reviews"), { recursive: true, force: true }),
  rm(resolve(viewerRoot, "dist/client/sample-review"), { recursive: true, force: true }),
]);
