import { normalizePackagePath, sha256ReviewBytes } from "./local-review-package.ts";

export const FINALIZATION_EXCLUDED_ROOT_PATHS = new Set([
  "finalization.json",
  "review-actions.json",
]);

const RECEIPT_KEYS = new Set(["schema_version", "review_id", "contract_version", "artifacts", "gates"]);
const RECEIPT_VERSIONS = new Set(["0.1", "0.2", "0.3"]);
const FINALIZATION_GATES = new Set([
  "source_integrity",
  "source_ingestion",
  "structured_verification",
  "structured_audit_v02",
  "burden_coverage_v02",
  "report_generation",
  "fix_plan_generation",
  "contract_validation",
]);
const BASE_GATES = [
  "source_integrity",
  "structured_verification",
  "report_generation",
  "fix_plan_generation",
  "contract_validation",
] as const;

export type FinalizationReceipt = {
  schema_version: "0.1" | "0.2" | "0.3";
  review_id: string;
  contract_version: "0.4";
  artifacts: Record<string, string>;
  gates: string[];
};

export type FinalizationTrust = {
  status: "verified" | "unverified";
  receipt_present: boolean;
  receipt_version: FinalizationReceipt["schema_version"] | null;
  detail: string;
};

export const NO_FINALIZATION_RECEIPT: FinalizationTrust = {
  status: "unverified",
  receipt_present: false,
  receipt_version: null,
  detail: "No finalization receipt was included, so package integrity has not been verified in this viewer.",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function basename(path: string) {
  return path.split("/").at(-1) || path;
}

export function isFinalizationArtifactPath(path: string) {
  const normalized = normalizePackagePath(path);
  return !FINALIZATION_EXCLUDED_ROOT_PATHS.has(normalized) && basename(normalized) !== ".DS_Store";
}

/** Validate the complete browser-facing finalization receipt contract. */
export function validateFinalizationReceipt(value: unknown): FinalizationReceipt {
  if (!isRecord(value)
    || Object.keys(value).length !== RECEIPT_KEYS.size
    || Object.keys(value).some((key) => !RECEIPT_KEYS.has(key))) {
    throw new Error("finalization.json has an unsupported structure");
  }
  if (typeof value.schema_version !== "string" || !RECEIPT_VERSIONS.has(value.schema_version)) {
    throw new Error("finalization.json has an unsupported schema_version");
  }
  if (typeof value.review_id !== "string" || !value.review_id.trim()) {
    throw new Error("finalization.json has no review_id");
  }
  if (value.contract_version !== "0.4") {
    throw new Error("finalization.json does not declare review contract 0.4");
  }
  if (!isRecord(value.artifacts) || !Object.keys(value.artifacts).length) {
    throw new Error("finalization.json has no artifact inventory");
  }
  const artifacts = Object.create(null) as Record<string, string>;
  const caseFoldedPaths = new Set<string>();
  for (const [rawPath, rawHash] of Object.entries(value.artifacts)) {
    const path = normalizePackagePath(rawPath);
    if (path !== rawPath || !isFinalizationArtifactPath(path)) {
      throw new Error(`finalization.json declares an unsafe or excluded artifact path: ${rawPath}`);
    }
    if (caseFoldedPaths.has(path.toLowerCase())) {
      throw new Error(`finalization.json declares case-ambiguous artifact paths: ${path}`);
    }
    if (typeof rawHash !== "string" || !/^[a-f0-9]{64}$/.test(rawHash)) {
      throw new Error(`finalization.json has an invalid SHA-256 hash for ${path}`);
    }
    caseFoldedPaths.add(path.toLowerCase());
    artifacts[path] = rawHash;
  }
  if (!Array.isArray(value.gates) || value.gates.length < 3
    || value.gates.some((gate) => typeof gate !== "string" || !FINALIZATION_GATES.has(gate))
    || new Set(value.gates).size !== value.gates.length) {
    throw new Error("finalization.json has invalid or duplicate gates");
  }
  return {
    schema_version: value.schema_version as FinalizationReceipt["schema_version"],
    review_id: value.review_id,
    contract_version: "0.4",
    artifacts,
    gates: [...value.gates] as string[],
  };
}

export function expectedFinalizationGates(options: {
  receiptVersion: FinalizationReceipt["schema_version"];
  reviewMode: unknown;
  hasPdfSource: boolean;
}) {
  if (options.reviewMode !== "full" && options.reviewMode !== "quick") {
    throw new Error("run.json must declare full or quick mode before receipt gates can be verified");
  }
  const gates = [...BASE_GATES] as string[];
  if (options.receiptVersion !== "0.1" && options.reviewMode === "full") gates.splice(2, 0, "structured_audit_v02");
  if (options.receiptVersion === "0.3" && options.reviewMode === "full") {
    gates.splice(gates.indexOf("structured_audit_v02") + 1, 0, "burden_coverage_v02");
  }
  if (options.hasPdfSource) gates.splice(1, 0, "source_ingestion");
  return gates;
}

function sameSet(left: Iterable<string>, right: Iterable<string>) {
  const leftSet = new Set(left);
  const rightSet = new Set(right);
  return leftSet.size === rightSet.size && Array.from(leftSet).every((value) => rightSet.has(value));
}

/**
 * Verify the receipt's identity, semantic gates, complete inventory, and bytes.
 * Failures become an explicit unverified state so a local package can still be
 * inspected without being represented as finalized.
 */
export async function verifyReviewFinalization(options: {
  receipt: unknown | null | undefined;
  reviewId: string;
  reviewContractVersion: unknown;
  reviewMode: unknown;
  hasPdfSource: boolean;
  artifactBytes: ReadonlyMap<string, Uint8Array>;
  requireExactInventory?: boolean;
}): Promise<FinalizationTrust> {
  if (options.receipt === null || options.receipt === undefined) return { ...NO_FINALIZATION_RECEIPT };
  let receipt: FinalizationReceipt | undefined;
  try {
    receipt = validateFinalizationReceipt(options.receipt);
    if (receipt.review_id !== options.reviewId) throw new Error("finalization.json has a different review ID");
    if (options.reviewContractVersion !== receipt.contract_version) {
      throw new Error("run.json and finalization.json declare different review contracts");
    }
    const expectedGates = expectedFinalizationGates({
      receiptVersion: receipt.schema_version,
      reviewMode: options.reviewMode,
      hasPdfSource: options.hasPdfSource,
    });
    if (!sameSet(receipt.gates, expectedGates)) {
      throw new Error("finalization.json gates do not match the review mode, receipt version, and source types");
    }
    const normalizedBytes = new Map<string, Uint8Array>();
    for (const [rawPath, bytes] of options.artifactBytes) {
      const path = normalizePackagePath(rawPath);
      if (!isFinalizationArtifactPath(path)) continue;
      if (normalizedBytes.has(path)) throw new Error(`the loaded package contains duplicate artifact path ${path}`);
      normalizedBytes.set(path, bytes);
    }
    const declaredArtifacts = receipt.artifacts;
    const declaredPaths = Object.keys(declaredArtifacts);
    if (options.requireExactInventory !== false && !sameSet(declaredPaths, normalizedBytes.keys())) {
      const missing = declaredPaths.filter((path) => !normalizedBytes.has(path));
      const unexpected = Array.from(normalizedBytes.keys()).filter((path) => !Object.hasOwn(declaredArtifacts, path));
      const details = [
        missing.length ? `missing ${missing.slice(0, 3).join(", ")}${missing.length > 3 ? "…" : ""}` : "",
        unexpected.length ? `undeclared ${unexpected.slice(0, 3).join(", ")}${unexpected.length > 3 ? "…" : ""}` : "",
      ].filter(Boolean).join("; ");
      throw new Error(`the loaded artifact inventory does not match finalization.json${details ? ` (${details})` : ""}`);
    }
    for (const path of declaredPaths) {
      const bytes = normalizedBytes.get(path);
      if (!bytes) throw new Error(`the loaded package is missing finalized artifact ${path}`);
      if (await sha256ReviewBytes(bytes) !== declaredArtifacts[path]) {
        throw new Error(`finalized artifact ${path} does not match its declared SHA-256 hash`);
      }
    }
    return {
      status: "verified",
      receipt_present: true,
      receipt_version: receipt.schema_version,
      detail: `Finalization receipt ${receipt.schema_version} and ${declaredPaths.length} artifact hash${declaredPaths.length === 1 ? "" : "es"} verified for integrity in this viewer. This unsigned receipt does not establish authorship or origin.`,
    };
  } catch (error) {
    return {
      status: "unverified",
      receipt_present: true,
      receipt_version: receipt?.schema_version || null,
      detail: error instanceof Error ? error.message : "The finalization receipt could not be verified.",
    };
  }
}
