import { copyFile, lstat, mkdir, readFile, realpath, rename, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import {
  validateReviewComputationLinks,
  validateReviewComputations,
} from "../lib/review-computations-contract.ts";
import { validateReviewDocumentManifest } from "../lib/review-documents.ts";
import { validateReviewLedger } from "../lib/review-ledger-contract.ts";
import { parseStrictJson } from "../lib/strict-json.ts";
import {
  referencedExhibitHashes,
  referencedExhibitPaths,
  validateExhibitManifest,
} from "../lib/local-review-package.ts";
import {
  validateFinalizationReceipt,
  verifyReviewFinalization,
} from "../lib/review-finalization.ts";
import { validateReviewRegistry } from "../lib/review-registry.ts";

const arguments_ = process.argv.slice(2);
const cliAuthorized = arguments_.length === 1 && arguments_[0] === "--allow-publish";
if (process.env.ALLOW_PUBLISH !== "1" && !cliAuthorized) {
  console.error([
    "Refusing to copy review manuscripts and findings into public build assets.",
    "Set ALLOW_PUBLISH=1, or use the explicit bundled npm script, only after confirming every bundled review is cleared for publication.",
    "For confidential reviews, run npm run dev and use the local file picker instead.",
  ].join("\n"));
  process.exit(1);
}
if (arguments_.length && !cliAuthorized) {
  console.error("Unsupported sync-review argument. Use only --allow-publish for an explicitly cleared bundled review.");
  process.exit(1);
}

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const publicRoot = resolve(root, "review-viewer/public/reviews");
const legacyRoot = resolve(root, "review-viewer/public/sample-review");
const publicParent = dirname(publicRoot);
const transactionId = `${process.pid}-${Date.now()}`;
const stageRoot = resolve(publicParent, `.reviews-stage-${transactionId}`);
const backupRoot = resolve(publicParent, `.reviews-backup-${transactionId}`);

const bundles = [
  {
    slug: "synthetic-theory-v03",
    title: "Synthetic Theory Review",
    reviewRoot: resolve(root, "tests/fixtures/valid-review"),
    manuscript: resolve(root, "tests/fixtures/valid-review/synthetic-paper.md"),
  },
];

function resolveInside(rootDirectory, relativePath) {
  const target = resolve(rootDirectory, relativePath);
  if (!target.startsWith(`${rootDirectory}${sep}`)) {
    throw new Error(`Refusing to resolve a review asset outside its bundle: ${relativePath}`);
  }
  return target;
}

async function copyRegularFile(source, destination) {
  const sourceInfo = await lstat(source);
  if (!sourceInfo.isFile() || sourceInfo.isSymbolicLink()) {
    throw new Error(`Refusing to bundle a non-regular review asset: ${source}`);
  }
  await mkdir(dirname(destination), { recursive: true });
  await copyFile(source, destination);
}

async function sha256File(path) {
  return createHash("sha256").update(await readFile(path)).digest("hex");
}

async function copyDeclaredDocument(sourceRoot, destinationRoot, relativePath) {
  const source = resolveInside(sourceRoot, relativePath);
  const sourceInfo = await lstat(source);
  if (sourceInfo.isSymbolicLink()) {
    throw new Error(`Refusing to bundle a symbolic-link review document: ${relativePath}`);
  }
  const [canonicalRoot, canonicalSource] = await Promise.all([realpath(sourceRoot), realpath(source)]);
  if (!canonicalSource.startsWith(`${canonicalRoot}${sep}`)) {
    throw new Error(`Refusing to bundle a review document outside its source package: ${relativePath}`);
  }
  await copyRegularFile(source, resolveInside(destinationRoot, relativePath));
}

async function pathExists(path) {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

async function parseObject(path, label) {
  const value = parseStrictJson(await readFile(path, "utf8"));
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must contain a JSON object`);
  }
  return value;
}

async function finalizedArtifactBytes(reviewRoot, receipt) {
  return new Map(await Promise.all(Object.keys(receipt.artifacts).map(async (relativePath) => {
    const source = resolveInside(reviewRoot, relativePath);
    const info = await lstat(source);
    if (!info.isFile() || info.isSymbolicLink()) {
      throw new Error(`Finalization receipt references a missing or unsafe artifact: ${relativePath}`);
    }
    return [relativePath, new Uint8Array(await readFile(source))];
  })));
}

async function prepareBundle(bundle) {
  const [manifestText, run, findings, synthesis, figures, tables, sourceManifest, computations, finalization] = await Promise.all([
    readFile(resolve(bundle.reviewRoot, "review-manifest.json"), "utf8"),
    parseObject(resolve(bundle.reviewRoot, "run.json"), `${bundle.slug} run.json`),
    parseObject(resolve(bundle.reviewRoot, "findings.json"), `${bundle.slug} findings.json`),
    parseObject(resolve(bundle.reviewRoot, "synthesis.json"), `${bundle.slug} synthesis.json`),
    parseObject(resolve(bundle.reviewRoot, "evidence/figures.json"), `${bundle.slug} figures.json`),
    parseObject(resolve(bundle.reviewRoot, "evidence/tables.json"), `${bundle.slug} tables.json`),
    parseObject(resolve(bundle.reviewRoot, "evidence/source-manifest.json"), `${bundle.slug} source-manifest.json`),
    parseObject(resolve(bundle.reviewRoot, "evidence/computations.json"), `${bundle.slug} computations.json`),
    parseObject(resolve(bundle.reviewRoot, "finalization.json"), `${bundle.slug} finalization.json`),
  ]);
  const manifest = validateReviewDocumentManifest(manifestText);
  const checkedFindings = validateReviewLedger(findings);
  const checkedComputations = validateReviewComputations(computations);
  const checkedFigures = validateExhibitManifest(figures, "figures", run.review_id);
  const checkedTables = validateExhibitManifest(tables, "tables", run.review_id);
  validateReviewComputationLinks(checkedFindings, checkedComputations, sourceManifest);
  if (!run.review_id || manifest.review_id !== run.review_id || findings.review_id !== run.review_id || synthesis.review_id !== run.review_id || sourceManifest.review_id !== run.review_id) {
    throw new Error(`Review IDs do not match across the canonical package for ${bundle.slug}`);
  }
  if (!Array.isArray(findings.findings) || !Array.isArray(figures.figures) || !Array.isArray(tables.tables)) {
    throw new Error(`Canonical package arrays are malformed for ${bundle.slug}`);
  }
  const receipt = validateFinalizationReceipt(finalization);
  const artifactBytes = await finalizedArtifactBytes(bundle.reviewRoot, receipt);
  const trust = await verifyReviewFinalization({
    receipt,
    reviewId: run.review_id,
    reviewContractVersion: run.schema_version,
    reviewMode: run.mode,
    hasPdfSource: sourceManifest.sources.some((source) => source?.media_type === "application/pdf"),
    artifactBytes,
    requireExactInventory: false,
  });
  if (trust.status !== "verified") throw new Error(`Source package is not finalized for ${bundle.slug}: ${trust.detail}`);
  const exhibitPaths = referencedExhibitPaths(checkedTables, checkedFigures);
  const exhibitHashes = referencedExhibitHashes(checkedTables, checkedFigures);
  for (const [index, relativePath] of exhibitPaths.entries()) {
    if (typeof relativePath !== "string" || !relativePath.trim() || !/\.(png|jpe?g|webp)$/i.test(relativePath)) {
      throw new Error(`Invalid exhibit render path at position ${index + 1} for ${bundle.slug}`);
    }
    const source = resolveInside(bundle.reviewRoot, relativePath);
    const info = await lstat(source);
    if (!info.isFile() || info.isSymbolicLink()) throw new Error(`Missing or unsafe exhibit render for ${bundle.slug}: ${relativePath}`);
    const expectedHash = exhibitHashes.get(relativePath);
    if (expectedHash && await sha256File(source) !== expectedHash) {
      throw new Error(`Exhibit render hash mismatch for ${bundle.slug}: ${relativePath}`);
    }
  }
  // Resolve every source now. Any missing, linked, or escaping file fails before
  // the currently published bundle is touched.
  await Promise.all([
    lstat(bundle.manuscript),
    ...manifest.documents.map(async (document) => {
      const source = resolveInside(bundle.reviewRoot, document.path);
      const info = await lstat(source);
      if (!info.isFile() || info.isSymbolicLink()) {
        throw new Error(`Refusing to bundle a non-regular review document: ${document.path}`);
      }
    }),
  ]);
  for (const requiredPath of [
    "findings.json", "run.json", "synthesis.json", "review-manifest.json",
    "evidence/figures.json", "evidence/tables.json", "evidence/source-manifest.json", "evidence/computations.json",
    ...manifest.documents.map((document) => document.path), ...exhibitPaths,
  ]) {
    if (!receipt.artifacts[requiredPath]) throw new Error(`Finalization receipt omits required bundled artifact for ${bundle.slug}: ${requiredPath}`);
  }
  return { bundle, manifest, exhibitPaths, receipt };
}

async function verifyStagedBundle(bundle, manifest, exhibitPaths, receipt) {
  const destination = resolve(stageRoot, bundle.slug);
  const [stagedManifestText, stagedRun, stagedFindings, stagedComputations, stagedSourceManifest, stagedFigures, stagedTables, stagedFinalization] = await Promise.all([
    readFile(resolve(destination, "review-manifest.json"), "utf8"),
    parseObject(resolve(destination, "run.json"), `${bundle.slug} staged run.json`),
    parseObject(resolve(destination, "findings.json"), `${bundle.slug} staged findings.json`),
    parseObject(resolve(destination, "evidence/computations.json"), `${bundle.slug} staged computations.json`),
    parseObject(resolve(destination, "evidence/source-manifest.json"), `${bundle.slug} staged source-manifest.json`),
    parseObject(resolve(destination, "evidence/figures.json"), `${bundle.slug} staged figures.json`),
    parseObject(resolve(destination, "evidence/tables.json"), `${bundle.slug} staged tables.json`),
    parseObject(resolve(destination, "finalization.json"), `${bundle.slug} staged finalization.json`),
  ]);
  const stagedManifest = validateReviewDocumentManifest(stagedManifestText);
  if (stagedManifest.review_id !== manifest.review_id || stagedRun.review_id !== manifest.review_id || stagedFindings.review_id !== manifest.review_id) {
    throw new Error(`Staged review IDs do not match for ${bundle.slug}`);
  }
  validateReviewComputationLinks(
    validateReviewLedger(stagedFindings),
    validateReviewComputations(stagedComputations),
    stagedSourceManifest,
  );
  const checkedFigures = validateExhibitManifest(stagedFigures, "figures", stagedRun.review_id);
  const checkedTables = validateExhibitManifest(stagedTables, "tables", stagedRun.review_id);
  const checkedReceipt = validateFinalizationReceipt(stagedFinalization);
  if (JSON.stringify(checkedReceipt) !== JSON.stringify(receipt)) throw new Error(`Staged finalization receipt differs from its source for ${bundle.slug}`);
  const trust = await verifyReviewFinalization({
    receipt: checkedReceipt,
    reviewId: stagedRun.review_id,
    reviewContractVersion: stagedRun.schema_version,
    reviewMode: stagedRun.mode,
    hasPdfSource: stagedSourceManifest.sources.some((source) => source?.media_type === "application/pdf"),
    artifactBytes: await finalizedArtifactBytes(destination, checkedReceipt),
    requireExactInventory: false,
  });
  if (trust.status !== "verified") throw new Error(`Staged package is not finalized for ${bundle.slug}: ${trust.detail}`);
  const stagedExhibitPaths = referencedExhibitPaths(checkedTables, checkedFigures);
  if (JSON.stringify([...stagedExhibitPaths].sort()) !== JSON.stringify([...exhibitPaths].sort())) {
    throw new Error(`Staged exhibit inventory differs from its source package for ${bundle.slug}`);
  }
  const stagedHashes = referencedExhibitHashes(checkedTables, checkedFigures);
  for (const relativePath of stagedExhibitPaths) {
    const expectedHash = stagedHashes.get(relativePath);
    if (expectedHash && await sha256File(resolveInside(destination, relativePath)) !== expectedHash) {
      throw new Error(`Staged exhibit render hash mismatch for ${bundle.slug}: ${relativePath}`);
    }
  }
  await Promise.all([
    "synthesis.json", "finalization.json", "evidence/figures.json", "evidence/tables.json", "evidence/source-manifest.json", "evidence/computations.json",
    ...manifest.documents.map((document) => document.path), ...exhibitPaths,
  ].map(async (relativePath) => {
    const info = await lstat(resolveInside(destination, relativePath));
    if (!info.isFile() || info.isSymbolicLink()) throw new Error(`Invalid staged review asset: ${relativePath}`);
  }));
}

await mkdir(publicParent, { recursive: true });
await Promise.all([
  rm(stageRoot, { recursive: true, force: true }),
  rm(backupRoot, { recursive: true, force: true }),
]);

let movedCurrentToBackup = false;
let published = false;
try {
  const prepared = await Promise.all(bundles.map(prepareBundle));
  await mkdir(stageRoot, { recursive: true });
  for (const { bundle, manifest, exhibitPaths, receipt } of prepared) {
    const destination = resolve(stageRoot, bundle.slug);
    await mkdir(destination, { recursive: true });
    await Promise.all([
      ...Object.keys(receipt.artifacts).map((relativePath) => copyDeclaredDocument(bundle.reviewRoot, destination, relativePath)),
      copyRegularFile(resolve(bundle.reviewRoot, "finalization.json"), resolve(destination, "finalization.json")),
    ]);
    await verifyStagedBundle(bundle, manifest, exhibitPaths, receipt);
  }

  const registry = {
    schema_version: 1,
    default_review: "synthetic-theory-v03",
    reviews: bundles.map(({ slug, title }) => ({ slug, title, base_path: `/reviews/${slug}` })),
  };
  await writeFile(resolve(stageRoot, "index.json"), `${JSON.stringify(registry, null, 2)}\n`);
  const stagedRegistry = validateReviewRegistry(
    await parseObject(resolve(stageRoot, "index.json"), "staged review registry"),
  );
  if (stagedRegistry.reviews.length !== bundles.length) throw new Error("Staged review registry is incomplete");

  if (await pathExists(publicRoot)) {
    await rename(publicRoot, backupRoot);
    movedCurrentToBackup = true;
  }
  try {
    await rename(stageRoot, publicRoot);
    published = true;
  } catch (error) {
    if (movedCurrentToBackup && !(await pathExists(publicRoot))) {
      await rename(backupRoot, publicRoot);
      movedCurrentToBackup = false;
    }
    throw error;
  }
  await rm(backupRoot, { recursive: true, force: true });
  movedCurrentToBackup = false;
  await rm(legacyRoot, { recursive: true, force: true });
} finally {
  await rm(stageRoot, { recursive: true, force: true });
  if (!published && movedCurrentToBackup && !(await pathExists(publicRoot))) {
    await rename(backupRoot, publicRoot);
    movedCurrentToBackup = false;
  }
  if (!movedCurrentToBackup) await rm(backupRoot, { recursive: true, force: true });
}
