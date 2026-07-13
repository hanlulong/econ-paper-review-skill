import { lstat, readdir } from "node:fs/promises";
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const viewerRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const reviewsRoot = resolve(viewerRoot, "public/reviews");

async function pathExists(path) {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

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

const bundlePredatedTest = await pathExists(reviewsRoot);

try {
  await run("npm", ["run", "build"], { ALLOW_PUBLISH: "1" });
  const tests = (await readdir(resolve(viewerRoot, "tests")))
    .filter((name) => name.endsWith(".test.mjs"))
    .sort()
    .map((name) => resolve(viewerRoot, "tests", name));
  await run(process.execPath, ["--test", ...tests]);
} finally {
  // Do not erase a bundle that was already serving a local preview when the
  // test began. Tests clean up only assets they created themselves.
  if (!bundlePredatedTest) await run(process.execPath, ["scripts/clear-review-bundles.mjs"]);
}
