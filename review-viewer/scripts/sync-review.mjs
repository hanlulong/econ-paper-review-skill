import { copyFile, lstat, mkdir, readFile, realpath, rename, rm, writeFile } from "node:fs/promises";
import { dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import {
  validateReviewComputationLinks,
  validateReviewComputations,
} from "../lib/review-computations-contract.ts";
import { validateReviewDocumentManifest } from "../lib/review-documents.ts";
import { validateReviewLedger } from "../lib/review-ledger-contract.ts";

if (process.env.ALLOW_PUBLISH !== "1") {
  console.error([
    "Refusing to copy review manuscripts and findings into public build assets.",
    "Set ALLOW_PUBLISH=1 only after confirming every bundled review is cleared for publication.",
    "For confidential reviews, run npm run dev and use the local file picker instead.",
  ].join("\n"));
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
  const value = JSON.parse(await readFile(path, "utf8"));
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must contain a JSON object`);
  }
  return value;
}

async function prepareBundle(bundle) {
  const [manifestText, run, findings, synthesis, figures, tables, sourceManifest, computations] = await Promise.all([
    readFile(resolve(bundle.reviewRoot, "review-manifest.json"), "utf8"),
    parseObject(resolve(bundle.reviewRoot, "run.json"), `${bundle.slug} run.json`),
    parseObject(resolve(bundle.reviewRoot, "findings.json"), `${bundle.slug} findings.json`),
    parseObject(resolve(bundle.reviewRoot, "synthesis.json"), `${bundle.slug} synthesis.json`),
    parseObject(resolve(bundle.reviewRoot, "evidence/figures.json"), `${bundle.slug} figures.json`),
    parseObject(resolve(bundle.reviewRoot, "evidence/tables.json"), `${bundle.slug} tables.json`),
    parseObject(resolve(bundle.reviewRoot, "evidence/source-manifest.json"), `${bundle.slug} source-manifest.json`),
    parseObject(resolve(bundle.reviewRoot, "evidence/computations.json"), `${bundle.slug} computations.json`),
  ]);
  const manifest = validateReviewDocumentManifest(manifestText);
  const checkedFindings = validateReviewLedger(findings);
  const checkedComputations = validateReviewComputations(computations);
  validateReviewComputationLinks(checkedFindings, checkedComputations, sourceManifest);
  if (!run.review_id || manifest.review_id !== run.review_id || findings.review_id !== run.review_id || synthesis.review_id !== run.review_id || sourceManifest.review_id !== run.review_id) {
    throw new Error(`Review IDs do not match across the canonical package for ${bundle.slug}`);
  }
  if (!Array.isArray(findings.findings) || !Array.isArray(figures.figures) || !Array.isArray(tables.tables)) {
    throw new Error(`Canonical package arrays are malformed for ${bundle.slug}`);
  }
  const exhibitPaths = Array.from(new Set([
    ...figures.figures.flatMap((row) => Array.isArray(row?.extraction_paths) ? row.extraction_paths : []),
    ...tables.tables.flatMap((row) => Array.isArray(row?.render_paths) ? row.render_paths : []),
  ]));
  for (const [index, relativePath] of exhibitPaths.entries()) {
    if (typeof relativePath !== "string" || !relativePath.trim() || !/\.(png|jpe?g|webp)$/i.test(relativePath)) {
      throw new Error(`Invalid exhibit render path at position ${index + 1} for ${bundle.slug}`);
    }
    const source = resolveInside(bundle.reviewRoot, relativePath);
    const info = await lstat(source);
    if (!info.isFile() || info.isSymbolicLink()) throw new Error(`Missing or unsafe exhibit render for ${bundle.slug}: ${relativePath}`);
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
  return { bundle, manifest, exhibitPaths };
}

async function verifyStagedBundle(bundle, manifest, exhibitPaths) {
  const destination = resolve(stageRoot, bundle.slug);
  const [stagedManifestText, stagedRun, stagedFindings, stagedComputations, stagedSourceManifest] = await Promise.all([
    readFile(resolve(destination, "review-manifest.json"), "utf8"),
    parseObject(resolve(destination, "run.json"), `${bundle.slug} staged run.json`),
    parseObject(resolve(destination, "findings.json"), `${bundle.slug} staged findings.json`),
    parseObject(resolve(destination, "computations.json"), `${bundle.slug} staged computations.json`),
    parseObject(resolve(destination, "source-manifest.json"), `${bundle.slug} staged source-manifest.json`),
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
  await Promise.all([
    "synthesis.json", "manuscript.md", "figures.json", "tables.json", "source-manifest.json", "computations.json",
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
  for (const { bundle, manifest, exhibitPaths } of prepared) {
    const destination = resolve(stageRoot, bundle.slug);
    await mkdir(destination, { recursive: true });
    await Promise.all([
      copyRegularFile(resolve(bundle.reviewRoot, "findings.json"), resolve(destination, "findings.json")),
      copyRegularFile(resolve(bundle.reviewRoot, "run.json"), resolve(destination, "run.json")),
      copyRegularFile(resolve(bundle.reviewRoot, "synthesis.json"), resolve(destination, "synthesis.json")),
      copyRegularFile(bundle.manuscript, resolve(destination, "manuscript.md")),
      copyRegularFile(resolve(bundle.reviewRoot, "evidence/figures.json"), resolve(destination, "figures.json")),
      copyRegularFile(resolve(bundle.reviewRoot, "evidence/tables.json"), resolve(destination, "tables.json")),
      copyRegularFile(resolve(bundle.reviewRoot, "evidence/source-manifest.json"), resolve(destination, "source-manifest.json")),
      copyRegularFile(resolve(bundle.reviewRoot, "evidence/computations.json"), resolve(destination, "computations.json")),
      ...manifest.documents.map((document) => copyDeclaredDocument(bundle.reviewRoot, destination, document.path)),
      ...exhibitPaths.map((relativePath) => copyDeclaredDocument(bundle.reviewRoot, destination, relativePath)),
    ]);
    await writeFile(resolve(destination, "review-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
    await verifyStagedBundle(bundle, manifest, exhibitPaths);
  }

  const registry = {
    schema_version: 1,
    default_review: "synthetic-theory-v03",
    reviews: bundles.map(({ slug, title }) => ({ slug, title, base_path: `/reviews/${slug}` })),
  };
  await writeFile(resolve(stageRoot, "index.json"), `${JSON.stringify(registry, null, 2)}\n`);
  const stagedRegistry = await parseObject(resolve(stageRoot, "index.json"), "staged review registry");
  if (!Array.isArray(stagedRegistry.reviews) || stagedRegistry.reviews.length !== bundles.length) {
    throw new Error("Staged review registry is malformed");
  }

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
