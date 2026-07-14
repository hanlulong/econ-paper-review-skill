import {
  generateReviewActionsPayload,
  migrateLegacyWorkspace,
  parseReviewActions,
  reconcileReviewActions,
  type ReviewActionEntry,
  type ReviewActionsPayload,
} from "./review-actions.ts";
import { parseStrictJson } from "./strict-json.ts";

export const REVIEW_ACTION_STORAGE_VERSION = 4;
const PREVIOUS_FINGERPRINT_STORAGE_VERSION = 3;
const REVIEW_ID_ONLY_STORAGE_VERSION = 2;
const LEGACY_WORKSPACE_STORAGE_VERSION = 1;

export type ReviewActionStorage = Pick<Storage, "length" | "key" | "getItem" | "setItem" | "removeItem">;
export type StoredActionRestore = {
  entries: Record<string, ReviewActionEntry>;
  warning: string;
  rereview_required_finding_ids: string[];
};

export function reviewActionStoragePrefix(reviewId: string) {
  // Encode the component so clearing review "a" cannot match review "a:b".
  return `review-desk:v${REVIEW_ACTION_STORAGE_VERSION}:${encodeURIComponent(reviewId)}:`;
}

export function reviewActionStorageKey(reviewId: string, fingerprint: string) {
  return `${reviewActionStoragePrefix(reviewId)}${fingerprint}`;
}

function storageKeys(storage: ReviewActionStorage) {
  const keys: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key) keys.push(key);
  }
  return keys;
}

function parseStoredPayload(
  value: string,
  reviewId: string,
  fingerprint: string,
): ReviewActionsPayload {
  const parsed = parseStrictJson(value);
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed) && "kind" in parsed) {
    return parseReviewActions(parsed);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("saved browser actions are not an object");
  }
  return generateReviewActionsPayload({
    source_review_id: reviewId,
    source_review_fingerprint: fingerprint,
    entries: parsed as Record<string, ReviewActionEntry>,
  });
}

function joinWarnings(values: Array<string | undefined>) {
  return values.map((value) => value?.trim()).filter(Boolean).join(" ");
}

/**
 * Restore current actions without consuming an older ledger snapshot.
 *
 * The newest prior-fingerprint payload is reconciled by exact stable ID when
 * the current fingerprint has no payload yet. Every older payload remains
 * namespaced under its original fingerprint, including unmatched entries.
 */
export function restoreBrowserReviewActions(
  storage: ReviewActionStorage,
  current: { review_id: string; review_fingerprint: string; finding_ids: string[] },
): StoredActionRestore {
  const exactKey = reviewActionStorageKey(current.review_id, current.review_fingerprint);
  const currentPrefix = reviewActionStoragePrefix(current.review_id);
  try {
    const keys = storageKeys(storage);
    const archivedCurrentKeys = keys.filter((key) => key.startsWith(currentPrefix) && key !== exactKey);
    const previousPrefix = `review-desk:v${PREVIOUS_FINGERPRINT_STORAGE_VERSION}:${encodeURIComponent(current.review_id)}:`;
    const previousKeys = keys.filter((key) => key.startsWith(previousPrefix));
    const exact = storage.getItem(exactKey);
    if (exact) {
      const result = reconcileReviewActions(
        parseStoredPayload(exact, current.review_id, current.review_fingerprint),
        current,
      );
      return {
        entries: result.entries,
        rereview_required_finding_ids: result.rereview_required_finding_ids,
        warning: joinWarnings([
          result.warnings.map((warning) => warning.message).join(" "),
          archivedCurrentKeys.length + previousKeys.length
            ? `${archivedCurrentKeys.length + previousKeys.length} prior ledger action snapshot${archivedCurrentKeys.length + previousKeys.length === 1 ? " remains" : "s remain"} archived in this browser under the original fingerprint${archivedCurrentKeys.length + previousKeys.length === 1 ? "" : "s"}; unmatched history has not been erased.`
            : undefined,
        ]),
      };
    }

    const priorPayloads: Array<{ payload: ReviewActionsPayload; key: string }> = [];
    const unreadableKeys: string[] = [];
    for (const key of archivedCurrentKeys) {
      const value = storage.getItem(key);
      if (!value) continue;
      try {
        priorPayloads.push({
          payload: parseStoredPayload(value, current.review_id, key.slice(currentPrefix.length)),
          key,
        });
      } catch {
        unreadableKeys.push(key);
      }
    }
    for (const key of previousKeys) {
      const value = storage.getItem(key);
      if (!value) continue;
      try {
        priorPayloads.push({
          payload: parseStoredPayload(value, current.review_id, key.slice(previousPrefix.length)),
          key,
        });
      } catch {
        unreadableKeys.push(key);
      }
    }

    const versionTwoKey = `review-desk:v${REVIEW_ID_ONLY_STORAGE_VERSION}:${current.review_id}`;
    const versionTwo = storage.getItem(versionTwoKey);
    if (versionTwo) {
      try {
        priorPayloads.push({
          // Review-ID-only storage cannot establish that its actions belong to
          // the current findings fingerprint. Treat a raw legacy map as a
          // prior round so carried actions reopen safely.
          payload: parseStoredPayload(versionTwo, current.review_id, "legacy-review-id-only"),
          key: versionTwoKey,
        });
      } catch {
        unreadableKeys.push(versionTwoKey);
      }
    }

    priorPayloads.sort((left, right) => (
      Date.parse(right.payload.exported_at) - Date.parse(left.payload.exported_at)
      || right.key.localeCompare(left.key)
    ));
    const newestPrior = priorPayloads[0];
    if (newestPrior) {
      const result = reconcileReviewActions(newestPrior.payload, current);
      return {
        entries: result.entries,
        rereview_required_finding_ids: result.rereview_required_finding_ids,
        warning: joinWarnings([
          "Actions from the most recent prior ledger snapshot were reconciled by exact stable finding ID. The complete prior payload remains archived in this browser under its original key, so unmatched history was not erased.",
          result.warnings.map((warning) => warning.message).join(" "),
          priorPayloads.length > 1
            ? `${priorPayloads.length} prior action snapshots remain archived; only the most recent was restored automatically.`
            : undefined,
          unreadableKeys.length
            ? `${unreadableKeys.length} archived action snapshot${unreadableKeys.length === 1 ? " was" : "s were"} unreadable and left untouched.`
            : undefined,
        ]),
      };
    }

    const legacyPrefix = `review-desk:v${LEGACY_WORKSPACE_STORAGE_VERSION}:${current.review_id}:`;
    const legacyKeys = keys.filter((key) => (
      key.startsWith(legacyPrefix) && /^[a-f0-9]{64}$/.test(key.slice(legacyPrefix.length))
    ));
    const exactLegacy = storage.getItem(`${legacyPrefix}${current.review_fingerprint}`);
    if (exactLegacy) {
      const entries = migrateLegacyWorkspace(parseStrictJson(exactLegacy));
      const allowed = new Set(current.finding_ids);
      return {
        entries: Object.fromEntries(Object.entries(entries).filter(([findingId]) => allowed.has(findingId))),
        rereview_required_finding_ids: [],
        warning: joinWarnings([
          "Actions for this exact legacy ledger were migrated to the current handoff format; the legacy payload remains archived.",
          legacyKeys.length > 1
            ? "Other legacy ledgers were not merged automatically; export and import them explicitly if needed."
            : undefined,
          unreadableKeys.length
            ? `${unreadableKeys.length} archived action snapshot${unreadableKeys.length === 1 ? " was" : "s were"} unreadable and left untouched.`
            : undefined,
        ]),
      };
    }
    if (legacyKeys.length) {
      return {
        entries: {},
        rereview_required_finding_ids: [],
        warning: "Older legacy actions exist for this review ID, but none match the current ledger fingerprint. They remain archived; export and import them explicitly to reconcile exact finding IDs.",
      };
    }
    if (unreadableKeys.length) {
      return {
        entries: {},
        rereview_required_finding_ids: [],
        warning: `${unreadableKeys.length} archived action snapshot${unreadableKeys.length === 1 ? " could" : "s could"} not be restored safely and ${unreadableKeys.length === 1 ? "was" : "were"} left untouched.`,
      };
    }
    return { entries: {}, warning: "", rereview_required_finding_ids: [] };
  } catch (error) {
    return {
      entries: {},
      rereview_required_finding_ids: [],
      warning: `Saved browser actions could not be restored safely and were left untouched: ${error instanceof Error ? error.message : "invalid local data"}`,
    };
  }
}

export function persistBrowserReviewActions(
  storage: ReviewActionStorage,
  payloadValue: ReviewActionsPayload,
) {
  const payload = parseReviewActions(payloadValue);
  storage.setItem(
    reviewActionStorageKey(payload.source_review_id, payload.source_review_fingerprint),
    JSON.stringify(payload),
  );
}

/** Delete every browser-side action snapshot for one review, including legacy formats. */
export function clearBrowserReviewActions(storage: ReviewActionStorage, reviewId: string): number {
  const currentPrefix = reviewActionStoragePrefix(reviewId);
  const previousPrefix = `review-desk:v${PREVIOUS_FINGERPRINT_STORAGE_VERSION}:${encodeURIComponent(reviewId)}:`;
  const legacyPrefix = `review-desk:v${LEGACY_WORKSPACE_STORAGE_VERSION}:${reviewId}:`;
  const exactKeys = new Set([`review-desk:v${REVIEW_ID_ONLY_STORAGE_VERSION}:${reviewId}`]);
  const keys = storageKeys(storage).filter((key) => (
    exactKeys.has(key)
    || key.startsWith(currentPrefix)
    || key.startsWith(previousPrefix)
    // Legacy v1 stored a SHA-256 ledger fingerprint after the final colon.
    // Checking the suffix prevents review "a" from clearing review "a:b".
    || (key.startsWith(legacyPrefix) && /^[a-f0-9]{64}$/.test(key.slice(legacyPrefix.length)))
  ));
  for (const key of keys) storage.removeItem(key);
  return keys.length;
}
