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

test("authorized sync stages and validates before replacing published assets", async () => {
  const source = await readFile(new URL("../scripts/sync-review.mjs", import.meta.url), "utf8");
  assert.match(source, /prepareBundle/);
  assert.match(source, /verifyStagedBundle/);
  assert.match(source, /exhibitPaths/);
  assert.match(source, /source-manifest\.json/);
  assert.match(source, /computations\.json/);
  assert.match(source, /validateReviewComputationLinks/);
  assert.match(source, /Missing or unsafe exhibit render/);
  assert.match(source, /exhibitPaths\.map\(\(relativePath\) => copyDeclaredDocument/);
  assert.match(source, /rename\(stageRoot, publicRoot\)/);
  assert.doesNotMatch(source, /rm\(publicRoot/);
  assert.ok(source.indexOf("const prepared = await Promise.all") < source.indexOf("rename(publicRoot, backupRoot)"));
});
