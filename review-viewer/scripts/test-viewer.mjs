import { readdir } from "node:fs/promises";
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { withPreservedReviewBundle } from "./preserve-review-bundle.mjs";

const viewerRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const reviewsRoot = resolve(viewerRoot, "public/reviews");

function run(command, args, extraEnv = {}) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(command, args, {
      cwd: viewerRoot,
      env: { ...process.env, ...extraEnv },
      stdio: "inherit",
    });
    child.on("error", rejectRun);
    child.on("exit", (code, signal) => {
      if (code === 0) resolveRun();
      else rejectRun(new Error(`${command} ${args.join(" ")} failed${signal ? ` with signal ${signal}` : ` with exit code ${code}`}`));
    });
  });
}

await withPreservedReviewBundle(reviewsRoot, async () => {
  await run("npm", ["run", "build"], { ALLOW_PUBLISH: "1" });
  const tests = (await readdir(resolve(viewerRoot, "tests")))
    .filter((name) => name.endsWith(".test.mjs"))
    .sort()
    .map((name) => resolve(viewerRoot, "tests", name));
  // Node 22.18+ strips erasable TypeScript syntax by default. Keep the test
  // harness runnable on the project's supported 22.14 baseline as well.
  await run(process.execPath, ["--experimental-strip-types", "--test", ...tests]);
});
