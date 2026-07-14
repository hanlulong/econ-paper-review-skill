import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("review bundle sync requires explicit publication authorization", async () => {
  const registryUrl = new URL("../public/reviews/index.json", import.meta.url);
  const before = await readFile(registryUrl, "utf8");
  const environment = { ...process.env };
  delete environment.ALLOW_PUBLISH;

  const result = spawnSync(process.execPath, ["--experimental-strip-types", "scripts/sync-review.mjs"], {
    cwd: new URL("..", import.meta.url),
    env: environment,
    encoding: "utf8",
  });

  assert.notEqual(result.status, 0);
  assert.match(`${result.stdout}${result.stderr}`, /ALLOW_PUBLISH=1/);
  assert.match(`${result.stdout}${result.stderr}`, /confidential reviews/i);
  assert.equal(await readFile(registryUrl, "utf8"), before, "a refused sync must not delete or rewrite existing assets");
});

test("generated review assets are ignored at both repository scopes", async () => {
  const [rootIgnore, viewerIgnore] = await Promise.all([
    readFile(new URL("../../.gitignore", import.meta.url), "utf8"),
    readFile(new URL("../.gitignore", import.meta.url), "utf8"),
  ]);

  assert.match(rootIgnore, /^\/review-viewer\/public\/reviews\/$/m);
  assert.match(viewerIgnore, /^\/public\/reviews\/$/m);
});

test("viewer npm scripts use native-Windows-compatible environment handling", async () => {
  const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  for (const name of ["dev", "dev:bundled", "build", "build:bundled", "start"]) {
    assert.doesNotMatch(packageJson.scripts[name], /(?:^|&&\s*)[A-Z_][A-Z0-9_]*=/);
  }
  assert.match(packageJson.scripts["dev:bundled"], /--allow-publish/);
  assert.match(packageJson.scripts["build:bundled"], /--allow-publish/);
  const harness = await readFile(new URL("../scripts/test-viewer.mjs", import.meta.url), "utf8");
  assert.match(harness, /process\.env\.npm_execpath/);
  assert.match(harness, /process\.env\.ComSpec \|\| "cmd\.exe"/);
  assert.match(harness, /process\.execPath/);
});

test("authorized sync stages and validates before replacing published assets", async () => {
  const source = await readFile(new URL("../scripts/sync-review.mjs", import.meta.url), "utf8");
  assert.match(source, /prepareBundle/);
  assert.match(source, /verifyStagedBundle/);
  assert.match(source, /exhibitPaths/);
  assert.match(source, /source-manifest\.json/);
  assert.match(source, /computations\.json/);
  assert.match(source, /analytical-audit\.json/);
  assert.match(source, /claims\.json/);
  assert.match(source, /finalization\.json/);
  assert.match(source, /validateReviewPackageWithPython/);
  assert.match(source, /verifyReviewFinalization/);
  assert.match(source, /Object\.keys\(receipt\.artifacts\)\.map/);
  assert.match(source, /validateReviewComputationLinks/);
  assert.match(source, /Missing or unsafe exhibit render/);
  assert.match(source, /copyDeclaredDocument\(bundle\.reviewRoot, destination, relativePath\)/);
  assert.match(source, /rename\(stageRoot, publicRoot\)/);
  assert.doesNotMatch(source, /rm\(publicRoot/);
  assert.ok(source.indexOf("const prepared = await Promise.all") < source.indexOf("rename(publicRoot, backupRoot)"));
  assert.ok(source.indexOf("validateReviewPackageWithPython") < source.indexOf("rename(publicRoot, backupRoot)"));
});

test("test preservation and cleanup cannot leave a copied backup bundle in the build", async () => {
  const [preserver, cleanup, harness] = await Promise.all([
    readFile(new URL("../scripts/preserve-review-bundle.mjs", import.meta.url), "utf8"),
    readFile(new URL("../scripts/clear-review-bundles.mjs", import.meta.url), "utf8"),
    readFile(new URL("../scripts/test-viewer.mjs", import.meta.url), "utf8"),
  ]);
  assert.match(preserver, /mkdtemp\(resolve\(dirname\(parent\), "\.review-test-backup-"\)\)/);
  assert.match(cleanup, /name\.startsWith\("\.review-test-backup-"\)/);
  assert.match(cleanup, /copiedTestBackups\.map/);
  assert.match(harness, /finally\s*\{/);
  assert.match(harness, /scripts\/clear-review-bundles\.mjs/);
});
