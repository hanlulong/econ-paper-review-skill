import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const viewerRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const candidates = process.platform === "win32"
  ? [["py", "-3"], ["python", ""]]
  : [["python3", ""], ["python", ""]];

let lastError = null;
for (const [command, launcherArgument] of candidates) {
  const args = [
    ...(launcherArgument ? [launcherArgument] : []),
    "scripts/build_review_desk_release.py",
    ...process.argv.slice(2),
  ];
  const result = spawnSync(command, args, { cwd: viewerRoot, stdio: "inherit" });
  if (!result.error) process.exit(result.status ?? 1);
  lastError = result.error;
  if (result.error.code !== "ENOENT") break;
}
throw new Error(`Python 3.10 or newer is required to package Review Desk: ${lastError?.message || "not found"}`);
