import { parseStrictJson } from "./strict-json.ts";
import { normalizePackagePath } from "./local-review-package.ts";

export const REVIEW_ACTIONS_SCHEMA_VERSION = "0.4" as const;
const SUPPORTED_REVIEW_ACTIONS_SCHEMA_VERSIONS = new Set(["0.1", "0.2", "0.3", REVIEW_ACTIONS_SCHEMA_VERSION]);
export const REVIEW_ACTIONS_KIND = "econ-review-actions" as const;

export const REVIEW_ACTION_DISPOSITIONS = [
  "open",
  "ready_for_recheck",
  "challenged",
  "deferred",
  "not_relevant",
  "not_addressable",
] as const;

export const REVIEW_ACTION_PRIORITIES = ["P0", "P1", "P2"] as const;

export type ReviewActionDisposition = (typeof REVIEW_ACTION_DISPOSITIONS)[number];
export type ReviewActionPriority = (typeof REVIEW_ACTION_PRIORITIES)[number];
export type LegacyWorkspaceStatus = "open" | "addressed" | "parked";

export type ReviewActionHistoryEntry = {
  disposition: ReviewActionDisposition;
  at: string;
};

export const REVIEW_ACTION_EVENT_TYPES = [
  "disposition_changed",
  "note_revised",
  "priority_changed",
  "reviewed_changed",
  "imported",
  "reversed",
] as const;
export type ReviewActionEventType = (typeof REVIEW_ACTION_EVENT_TYPES)[number];
export type ReviewActionEvent = {
  event_id: string;
  type: ReviewActionEventType;
  at: string;
  disposition?: ReviewActionDisposition;
  note?: string | null;
  user_priority?: ReviewActionPriority | null;
  reviewed?: boolean;
  parent_event_id?: string | null;
  origin?: "local" | "import";
};

export type ReviewActionEntry = {
  finding_id: string;
  disposition: ReviewActionDisposition;
  response_note: string;
  changed_locations: string[];
  user_priority: ReviewActionPriority | null;
  reviewed: boolean;
  updated_at: string;
  status_history: ReviewActionHistoryEntry[];
  events: ReviewActionEvent[];
};

export type ReviewActionSourceManuscript = {
  path: string;
  sha256: string | null;
};

export type ReviewActionsPayload = {
  schema_version: typeof REVIEW_ACTIONS_SCHEMA_VERSION;
  kind: typeof REVIEW_ACTIONS_KIND;
  source_review_id: string;
  source_review_fingerprint: string;
  source_manuscripts: ReviewActionSourceManuscript[];
  exported_at: string;
  entries: ReviewActionEntry[];
};

type ReviewActionSourceInput = {
  path: string;
  sha256?: string | null;
};

export type LegacyWorkspaceEntry = {
  status: LegacyWorkspaceStatus;
  note: string;
};

export type ReconciliationWarning = {
  code: "review_id_mismatch" | "fingerprint_mismatch" | "unmatched_entries";
  message: string;
};

export type ReviewActionsReconciliation = {
  entries: Record<string, ReviewActionEntry>;
  matched_finding_ids: string[];
  unmatched_entry_ids: string[];
  untouched_finding_ids: string[];
  rereview_required_finding_ids: string[];
  review_id_matches: boolean;
  fingerprint_matches: boolean;
  warnings: ReconciliationWarning[];
};

export type ReviewActionMergeWarning = {
  code: "equal_timestamp_divergence" | "non_prefix_history";
  finding_id: string;
  message: string;
};

export type ReviewActionMergeResult = {
  entries: Record<string, ReviewActionEntry>;
  applied_finding_ids: string[];
  stale_finding_ids: string[];
  conflict_finding_ids: string[];
  warnings: ReviewActionMergeWarning[];
};

const FINDING_ID = /^[A-Z][A-Z0-9_-]*-[0-9]{2,}$/;
const SHA256 = /^[a-f0-9]{64}$/;
const DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-](\d{2}):(\d{2}))$/;
const MAX_NOTE_CHARS = 10_000;
const MAX_LOCATION_CHARS = 1_000;
const DISPOSITIONS = new Set<string>(REVIEW_ACTION_DISPOSITIONS);
const PRIORITIES = new Set<string>(REVIEW_ACTION_PRIORITIES);
const EVENT_TYPES = new Set<string>(REVIEW_ACTION_EVENT_TYPES);
const LEGACY_STATUSES = new Set<string>(["open", "addressed", "parked"]);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function assertExactKeys(value: Record<string, unknown>, allowed: readonly string[], label: string): void {
  const allowedSet = new Set(allowed);
  const extras = Object.keys(value).filter((key) => !allowedSet.has(key));
  if (extras.length) throw new Error(`${label} has unsupported fields: ${extras.sort().join(", ")}`);
}

function assertNonemptyString(value: unknown, label: string, maximum?: number): asserts value is string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a nonempty string`);
  if (value !== value.trim()) throw new Error(`${label} must be trimmed`);
  if (maximum !== undefined && value.length > maximum) throw new Error(`${label} exceeds ${maximum} characters`);
}

function assertDateTime(value: unknown, label: string): asserts value is string {
  const match = typeof value === "string" ? DATE_TIME.exec(value) : null;
  if (!match || Number.isNaN(Date.parse(value as string))) {
    throw new Error(`${label} must be an RFC 3339 date-time`);
  }
  const [, year, month, day, hour, minute, second, offsetHour = "00", offsetMinute = "00"] = match;
  const numericMonth = Number(month);
  const numericDay = Number(day);
  const validDay = numericMonth >= 1
    && numericMonth <= 12
    && numericDay >= 1
    && numericDay <= new Date(Date.UTC(Number(year), numericMonth, 0)).getUTCDate();
  if (
    !validDay || Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59
    || Number(offsetHour) > 23 || Number(offsetMinute) > 59
  ) {
    throw new Error(`${label} must be an RFC 3339 date-time`);
  }
}

function assertFindingId(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || !FINDING_ID.test(value)) {
    throw new Error(`${label} must be an exact canonical finding ID`);
  }
}

function assertDisposition(value: unknown, label: string): asserts value is ReviewActionDisposition {
  if (typeof value !== "string" || !DISPOSITIONS.has(value)) {
    throw new Error(`${label} has an unsupported disposition`);
  }
}

function assertPriority(value: unknown, label: string): asserts value is ReviewActionPriority | null {
  if (!(value === null || (typeof value === "string" && PRIORITIES.has(value)))) {
    throw new Error(`${label} must be P0, P1, P2, or null`);
  }
}

/**
 * Remove local directory names from a portable action handoff.
 *
 * The review package retains full source provenance in run.json. The exported
 * sidecar needs only a recognizable file label and an optional content hash;
 * copying an absolute path would expose usernames and confidential folders.
 */
export function privacySafeSourceManuscripts(
  sources: readonly ReviewActionSourceInput[],
): ReviewActionSourceManuscript[] {
  const basenames = sources.map((source, index) => {
    const pathWithoutQuery = String(source.path || "").replaceAll("\\", "/").split(/[?#]/, 1)[0];
    const basename = pathWithoutQuery.split("/").filter(Boolean).at(-1)?.trim()
      .normalize("NFC")
      .replace(/[:\u0000-\u001f\u007f]/g, "-")
      .replace(/[.\s]+$/g, "");
    const fallback = `manuscript-${index + 1}`;
    if (!basename || basename === "." || basename === "..") return fallback;
    try {
      return normalizePackagePath(basename);
    } catch {
      return fallback;
    }
  });
  const totals = new Map<string, number>();
  for (const basename of basenames) {
    const key = basename.toLowerCase();
    totals.set(key, (totals.get(key) || 0) + 1);
  }
  const seen = new Map<string, number>();
  return sources.map((source, index) => {
    const basename = basenames[index];
    const key = basename.toLowerCase();
    const duplicateIndex = (seen.get(key) || 0) + 1;
    seen.set(key, duplicateIndex);
    return {
      path: (totals.get(key) || 0) > 1 ? `source-${duplicateIndex}-${basename}` : basename,
      sha256: source.sha256 || null,
    };
  });
}

function cloneHistory(value: unknown, label: string): ReviewActionHistoryEntry[] {
  if (!Array.isArray(value) || !value.length) throw new Error(`${label} must contain at least one entry`);
  let previousTime = -Infinity;
  return value.map((raw, index) => {
    if (!isRecord(raw)) throw new Error(`${label}[${index}] must be an object`);
    assertExactKeys(raw, ["disposition", "at"], `${label}[${index}]`);
    assertDisposition(raw.disposition, `${label}[${index}].disposition`);
    assertDateTime(raw.at, `${label}[${index}].at`);
    const time = Date.parse(raw.at);
    if (time < previousTime) throw new Error(`${label} must be chronological`);
    previousTime = time;
    return { disposition: raw.disposition, at: raw.at };
  });
}

function stableUuid(seed: string): string {
  const digest = [0x811c9dc5, 0x9e3779b9, 0x85ebca6b, 0xc2b2ae35].map((initial, salt) => {
    let hash = initial;
    for (let index = 0; index < seed.length; index += 1) {
      hash ^= seed.charCodeAt(index) + salt * 131;
      hash = Math.imul(hash, 0x01000193);
    }
    return (hash >>> 0).toString(16).padStart(8, "0");
  }).join("");
  return `${digest.slice(0, 8)}-${digest.slice(8, 12)}-5${digest.slice(13, 16)}-a${digest.slice(17, 20)}-${digest.slice(20, 32)}`;
}

function newEventId(seed: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return stableUuid(`${seed}:${Date.now()}:${Math.random()}`);
}

function legacyEvents(
  findingId: string,
  history: ReviewActionHistoryEntry[],
  note: string,
  updatedAt: string,
): ReviewActionEvent[] {
  const events: ReviewActionEvent[] = [];
  for (const [index, item] of history.entries()) {
    events.push({
      event_id: stableUuid(`${findingId}:legacy:disposition:${index}:${item.disposition}:${item.at}`),
      type: index ? "disposition_changed" : "disposition_changed",
      at: item.at,
      disposition: item.disposition,
      parent_event_id: events.at(-1)?.event_id || null,
      origin: "import",
    });
  }
  if (note) {
    events.push({
      event_id: stableUuid(`${findingId}:legacy:note:${updatedAt}:${note}`),
      type: "note_revised",
      at: updatedAt,
      note,
      parent_event_id: events.at(-1)?.event_id || null,
      origin: "import",
    });
  }
  return events;
}

function cloneEvents(value: unknown, label: string, sourceVersion: "0.3" | "0.4" = REVIEW_ACTIONS_SCHEMA_VERSION): ReviewActionEvent[] {
  if (!Array.isArray(value) || !value.length) throw new Error(`${label} must contain at least one event`);
  let previousTime = -Infinity;
  let previousId: string | null = null;
  const ids = new Set<string>();
  return value.map((raw, index) => {
    if (!isRecord(raw)) throw new Error(`${label}[${index}] must be an object`);
    assertExactKeys(
      raw,
      sourceVersion === "0.4"
        ? ["event_id", "type", "at", "disposition", "note", "user_priority", "reviewed", "parent_event_id", "origin"]
        : ["event_id", "type", "at", "disposition", "note", "parent_event_id", "origin"],
      `${label}[${index}]`,
    );
    if (typeof raw.event_id !== "string" || !UUID.test(raw.event_id) || ids.has(raw.event_id)) {
      throw new Error(`${label}[${index}].event_id must be a unique UUID`);
    }
    if (typeof raw.type !== "string" || !EVENT_TYPES.has(raw.type)) throw new Error(`${label}[${index}].type is unsupported`);
    if (sourceVersion === "0.3" && ["priority_changed", "reviewed_changed"].includes(raw.type)) {
      throw new Error(`${label}[${index}].type is unsupported under action schema v0.3`);
    }
    assertDateTime(raw.at, `${label}[${index}].at`);
    if (Date.parse(raw.at) < previousTime) throw new Error(`${label} must be chronological`);
    if ((raw.parent_event_id ?? null) !== previousId) throw new Error(`${label}[${index}] must reference the preceding event as parent`);
    if (raw.origin !== undefined && raw.origin !== "local" && raw.origin !== "import") throw new Error(`${label}[${index}].origin is unsupported`);
    const type = raw.type as ReviewActionEventType;
    if (type === "disposition_changed") {
      assertDisposition(raw.disposition, `${label}[${index}].disposition`);
      if (raw.note !== undefined || raw.user_priority !== undefined || raw.reviewed !== undefined) {
        throw new Error(`${label}[${index}] disposition events cannot carry another state field`);
      }
    } else if (type === "reversed") {
      if (raw.disposition === undefined && raw.note === undefined) throw new Error(`${label}[${index}] reversal must carry a disposition or note`);
      if (raw.disposition !== undefined) assertDisposition(raw.disposition, `${label}[${index}].disposition`);
      if (!(raw.note === undefined || raw.note === null || typeof raw.note === "string") || (typeof raw.note === "string" && raw.note.length > MAX_NOTE_CHARS)) {
        throw new Error(`${label}[${index}].note must be null or text of at most ${MAX_NOTE_CHARS} characters`);
      }
      if (raw.user_priority !== undefined || raw.reviewed !== undefined) throw new Error(`${label}[${index}] reversal cannot carry priority or reviewed state`);
    } else if (type === "note_revised") {
      if (!(raw.note === null || typeof raw.note === "string") || (typeof raw.note === "string" && raw.note.length > MAX_NOTE_CHARS)) {
        throw new Error(`${label}[${index}].note must be null or text of at most ${MAX_NOTE_CHARS} characters`);
      }
      if (raw.disposition !== undefined || raw.user_priority !== undefined || raw.reviewed !== undefined) {
        throw new Error(`${label}[${index}] note events cannot carry another state field`);
      }
    } else if (type === "priority_changed") {
      if (!("user_priority" in raw)) throw new Error(`${label}[${index}] priority events must carry user_priority`);
      assertPriority(raw.user_priority, `${label}[${index}].user_priority`);
      if (raw.disposition !== undefined || raw.note !== undefined || raw.reviewed !== undefined) {
        throw new Error(`${label}[${index}] priority events cannot carry another state field`);
      }
    } else if (type === "reviewed_changed") {
      if (typeof raw.reviewed !== "boolean") throw new Error(`${label}[${index}] reviewed events must carry a boolean`);
      if (raw.disposition !== undefined || raw.note !== undefined || raw.user_priority !== undefined) {
        throw new Error(`${label}[${index}] reviewed events cannot carry another state field`);
      }
    } else if (raw.disposition !== undefined || raw.note !== undefined || raw.user_priority !== undefined || raw.reviewed !== undefined) {
      throw new Error(`${label}[${index}] import events cannot carry state fields`);
    }
    const event: ReviewActionEvent = {
      event_id: raw.event_id,
      type,
      at: raw.at,
      parent_event_id: raw.parent_event_id as string | null | undefined,
      origin: raw.origin as "local" | "import" | undefined,
    };
    if (raw.disposition !== undefined) event.disposition = raw.disposition as ReviewActionDisposition;
    if (raw.note !== undefined) event.note = raw.note as string | null;
    if ("user_priority" in raw) event.user_priority = raw.user_priority as ReviewActionPriority | null;
    if (raw.reviewed !== undefined) event.reviewed = raw.reviewed as boolean;
    ids.add(event.event_id);
    previousId = event.event_id;
    previousTime = Date.parse(event.at);
    return event;
  });
}

function cloneEntry(value: unknown, label: string, sourceVersion: "0.1" | "0.2" | "0.3" | "0.4" = REVIEW_ACTIONS_SCHEMA_VERSION): ReviewActionEntry {
  if (!isRecord(value)) throw new Error(`${label} must be an object`);
  assertExactKeys(
    value,
    sourceVersion === "0.4"
      ? ["finding_id", "disposition", "response_note", "changed_locations", "user_priority", "reviewed", "updated_at", "status_history", "events"]
      : sourceVersion === "0.3"
        ? ["finding_id", "disposition", "response_note", "changed_locations", "updated_at", "status_history", "events"]
        : ["finding_id", "disposition", "response_note", "changed_locations", "updated_at", "status_history"],
    label,
  );
  assertFindingId(value.finding_id, `${label}.finding_id`);
  assertDisposition(value.disposition, `${label}.disposition`);
  if (sourceVersion !== "0.4" && ["not_relevant", "not_addressable"].includes(value.disposition)) {
    throw new Error(`${label}.disposition is unsupported under action schema v${sourceVersion}`);
  }
  if (typeof value.response_note !== "string" || value.response_note.length > MAX_NOTE_CHARS) {
    throw new Error(`${label}.response_note must be text of at most ${MAX_NOTE_CHARS} characters`);
  }
  if (!Array.isArray(value.changed_locations)) throw new Error(`${label}.changed_locations must be an array`);
  const changedLocations = value.changed_locations.map((location, index) => {
    assertNonemptyString(location, `${label}.changed_locations[${index}]`, MAX_LOCATION_CHARS);
    return location;
  });
  if (new Set(changedLocations).size !== changedLocations.length) {
    throw new Error(`${label}.changed_locations must not contain duplicates`);
  }
  const userPriority = sourceVersion === "0.4" ? value.user_priority : null;
  assertPriority(userPriority, `${label}.user_priority`);
  const reviewed = sourceVersion === "0.4" ? value.reviewed : false;
  if (typeof reviewed !== "boolean") throw new Error(`${label}.reviewed must be a boolean`);
  if (["not_relevant", "not_addressable"].includes(value.disposition) && !reviewed) {
    throw new Error(`${label}.${value.disposition} must be marked reviewed`);
  }
  if (sourceVersion === "0.1" && value.disposition === "ready_for_recheck" && !value.response_note.trim() && !changedLocations.length) {
    throw new Error(`${label} needs an author response or changed location under action schema v0.1`);
  }
  if (sourceVersion === "0.1" && value.disposition === "challenged" && !value.response_note.trim()) {
    throw new Error(`${label} needs an author response explaining the challenge under action schema v0.1`);
  }
  assertDateTime(value.updated_at, `${label}.updated_at`);
  const statusHistory = cloneHistory(value.status_history, `${label}.status_history`);
  if (statusHistory.at(-1)?.disposition !== value.disposition) {
    throw new Error(`${label}.disposition must match the final status_history entry`);
  }
  if (Date.parse(statusHistory.at(-1)!.at) > Date.parse(value.updated_at)) {
    throw new Error(`${label}.updated_at cannot precede its final status history entry`);
  }
  const events = sourceVersion === "0.3" || sourceVersion === "0.4"
    ? cloneEvents(value.events, `${label}.events`, sourceVersion)
    : legacyEvents(value.finding_id, statusHistory, value.response_note, value.updated_at);
  let replayDisposition: ReviewActionDisposition = "open";
  let replayNote = "";
  let replayPriority: ReviewActionPriority | null = null;
  let replayReviewed = false;
  const replayHistory: ReviewActionHistoryEntry[] = [];
  for (const event of events) {
    if (event.type === "disposition_changed" || event.type === "reversed") {
      if (event.disposition !== undefined) {
        replayDisposition = event.disposition;
        replayHistory.push({ disposition: replayDisposition, at: event.at });
      }
      if (event.type === "reversed" && event.note !== undefined) replayNote = event.note || "";
    } else if (event.type === "note_revised") {
      replayNote = event.note || "";
    } else if (event.type === "priority_changed") {
      replayPriority = event.user_priority ?? null;
    } else if (event.type === "reviewed_changed") {
      replayReviewed = Boolean(event.reviewed);
    }
  }
  if (
    replayDisposition !== value.disposition
    || replayNote !== value.response_note
    || replayPriority !== userPriority
    || replayReviewed !== reviewed
  ) {
    throw new Error(`${label} current state must equal replayed events`);
  }
  if (replayHistory.length !== statusHistory.length || replayHistory.some((item, index) => (
    item.disposition !== statusHistory[index].disposition || item.at !== statusHistory[index].at
  ))) throw new Error(`${label}.status_history must equal replayed disposition events`);
  if (Date.parse(events.at(-1)!.at) > Date.parse(value.updated_at)) throw new Error(`${label}.updated_at cannot precede its final event`);
  return {
    finding_id: value.finding_id,
    disposition: value.disposition,
    response_note: value.response_note,
    changed_locations: changedLocations,
    user_priority: userPriority,
    reviewed,
    updated_at: value.updated_at,
    status_history: statusHistory,
    events,
  };
}

/** Parse a handoff payload without accepting unknown fields or coercing malformed values. */
export function parseReviewActions(value: unknown): ReviewActionsPayload {
  let raw = value;
  if (typeof raw === "string") {
    try {
      raw = parseStrictJson(raw);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "invalid JSON";
      throw new Error(`review actions contain invalid JSON: ${detail}`);
    }
  }
  if (!isRecord(raw)) throw new Error("review actions must be an object");
  assertExactKeys(
    raw,
    ["schema_version", "kind", "source_review_id", "source_review_fingerprint", "source_manuscripts", "exported_at", "entries"],
    "review actions",
  );
  if (typeof raw.schema_version !== "string" || !SUPPORTED_REVIEW_ACTIONS_SCHEMA_VERSIONS.has(raw.schema_version)) {
    throw new Error("review actions have an unsupported schema_version");
  }
  if (raw.kind !== REVIEW_ACTIONS_KIND) throw new Error("review actions have an unsupported kind");
  assertNonemptyString(raw.source_review_id, "source_review_id");
  assertNonemptyString(raw.source_review_fingerprint, "source_review_fingerprint");
  assertDateTime(raw.exported_at, "exported_at");
  if (!Array.isArray(raw.source_manuscripts)) throw new Error("source_manuscripts must be an array");
  const sourceManuscripts = raw.source_manuscripts.map((source, index) => {
    if (!isRecord(source)) throw new Error(`source_manuscripts[${index}] must be an object`);
    assertExactKeys(source, ["path", "sha256"], `source_manuscripts[${index}]`);
    assertNonemptyString(source.path, `source_manuscripts[${index}].path`);
    if (!(source.sha256 === null || (typeof source.sha256 === "string" && SHA256.test(source.sha256)))) {
      throw new Error(`source_manuscripts[${index}].sha256 must be null or a lowercase SHA-256 digest`);
    }
    let path: string;
    try {
      path = normalizePackagePath(source.path);
    } catch {
      throw new Error(`source_manuscripts[${index}].path must be a canonical portable relative path`);
    }
    return { path, sha256: source.sha256 };
  });
  const sourcePaths = sourceManuscripts.map((source) => source.path.toLocaleLowerCase("en-US"));
  if (new Set(sourcePaths).size !== sourcePaths.length) {
    throw new Error("source_manuscripts must have unique paths and be case-unambiguous");
  }
  if (!Array.isArray(raw.entries)) throw new Error("entries must be an array");
  const sourceVersion = raw.schema_version as "0.1" | "0.2" | "0.3" | "0.4";
  const entries = raw.entries.map((entry, index) => cloneEntry(entry, `entries[${index}]`, sourceVersion));
  const ids = entries.map((entry) => entry.finding_id);
  if (new Set(ids).size !== ids.length) throw new Error("entries must have unique finding IDs");
  const eventIds = entries.flatMap((entry) => entry.events.map((event) => event.event_id));
  if (new Set(eventIds).size !== eventIds.length) throw new Error("entries must have globally unique event IDs");
  for (const [index, entry] of entries.entries()) {
    if (Date.parse(entry.updated_at) > Date.parse(raw.exported_at)) {
      throw new Error(`entries[${index}].updated_at cannot be later than exported_at`);
    }
  }
  return {
    schema_version: REVIEW_ACTIONS_SCHEMA_VERSION,
    kind: REVIEW_ACTIONS_KIND,
    source_review_id: raw.source_review_id,
    source_review_fingerprint: raw.source_review_fingerprint,
    source_manuscripts: sourceManuscripts,
    exported_at: raw.exported_at,
    entries,
  };
}

export function generateReviewActionsPayload(options: {
  source_review_id: string;
  source_review_fingerprint: string;
  source_manuscripts?: ReviewActionSourceManuscript[];
  exported_at?: string;
  entries: ReviewActionEntry[] | Record<string, ReviewActionEntry>;
}): ReviewActionsPayload {
  let entries: ReviewActionEntry[];
  if (Array.isArray(options.entries)) {
    entries = options.entries;
  } else {
    entries = Object.entries(options.entries).map(([findingId, entry]) => {
      if (findingId !== entry.finding_id) {
        throw new Error(`action map key ${findingId} does not match entry finding ID ${entry.finding_id}`);
      }
      return entry;
    });
  }
  const canonicalEntries = entries.map((entry, index) => cloneEntry(
    entry,
    `entries[${index}]`,
    "user_priority" in entry && "reviewed" in entry
      ? "0.4"
      : Array.isArray((entry as Partial<ReviewActionEntry>).events) ? "0.3" : "0.2",
  ));
  return parseReviewActions({
    schema_version: REVIEW_ACTIONS_SCHEMA_VERSION,
    kind: REVIEW_ACTIONS_KIND,
    source_review_id: options.source_review_id,
    source_review_fingerprint: options.source_review_fingerprint,
    source_manuscripts: privacySafeSourceManuscripts(options.source_manuscripts || []),
    exported_at: options.exported_at || new Date().toISOString(),
    entries: canonicalEntries.sort((left, right) => left.finding_id.localeCompare(right.finding_id)),
  });
}

function legacyDisposition(status: LegacyWorkspaceStatus): ReviewActionDisposition {
  if (status === "addressed") return "ready_for_recheck";
  if (status === "parked") return "deferred";
  return "open";
}

/** Convert the v1 browser workspace map (or its full exported wrapper) into typed action entries. */
export function migrateLegacyWorkspace(value: unknown, at = new Date().toISOString()): Record<string, ReviewActionEntry> {
  assertDateTime(at, "legacy migration timestamp");
  let raw = value;
  let migrationTime = at;
  if (isRecord(raw) && "findings" in raw) {
    assertExactKeys(raw, ["schema_version", "review_id", "review_fingerprint", "exported_at", "findings"], "legacy workspace");
    if (raw.exported_at !== undefined) {
      assertDateTime(raw.exported_at, "legacy workspace exported_at");
      migrationTime = raw.exported_at;
    }
    raw = raw.findings;
  }
  if (!isRecord(raw)) throw new Error("legacy workspace findings must be an object");
  const entries: Record<string, ReviewActionEntry> = {};
  for (const [findingId, candidate] of Object.entries(raw)) {
    assertFindingId(findingId, "legacy workspace finding ID");
    if (!isRecord(candidate)) throw new Error(`legacy workspace ${findingId} must be an object`);
    assertExactKeys(candidate, ["status", "note"], `legacy workspace ${findingId}`);
    if (typeof candidate.status !== "string" || !LEGACY_STATUSES.has(candidate.status)) {
      throw new Error(`legacy workspace ${findingId} has an unsupported status`);
    }
    if (typeof candidate.note !== "string" || candidate.note.length > MAX_NOTE_CHARS) {
      throw new Error(`legacy workspace ${findingId}.note must be text of at most ${MAX_NOTE_CHARS} characters`);
    }
    const legacyStatus = candidate.status as LegacyWorkspaceStatus;
    // An old "addressed" click without a response is not enough evidence to
    // claim that a later reviewer can recheck an implementation.
    const disposition = legacyStatus === "addressed" && !candidate.note.trim()
      ? "open"
      : legacyDisposition(legacyStatus);
    entries[findingId] = {
      finding_id: findingId,
      disposition,
      response_note: candidate.note,
      changed_locations: [],
      user_priority: null,
      reviewed: false,
      updated_at: migrationTime,
      status_history: [{ disposition, at: migrationTime }],
      events: [{
        event_id: stableUuid(`${findingId}:migration:${disposition}:${migrationTime}`),
        type: "disposition_changed",
        at: migrationTime,
        disposition,
        parent_event_id: null,
        origin: "import",
      }, ...(candidate.note ? [{
        event_id: stableUuid(`${findingId}:migration-note:${migrationTime}:${candidate.note}`),
        type: "note_revised" as const,
        at: migrationTime,
        note: candidate.note,
        parent_event_id: stableUuid(`${findingId}:migration:${disposition}:${migrationTime}`),
        origin: "import" as const,
      }] : [])],
    };
  }
  return entries;
}

/** Apply a user action while preserving prior timestamps and append-only disposition history. */
export function updateReviewAction(
  current: ReviewActionEntry | undefined,
  findingId: string,
  patch: Partial<Pick<ReviewActionEntry, "disposition" | "response_note" | "changed_locations" | "user_priority" | "reviewed">>,
  at = new Date().toISOString(),
  eventOptions: { type?: "disposition_changed" | "reversed"; origin?: "local" | "import" } = {},
): ReviewActionEntry {
  assertFindingId(findingId, "findingId");
  assertDateTime(at, "action timestamp");
  const base: ReviewActionEntry = current
    ? cloneEntry(current, `action ${findingId}`)
    : {
        finding_id: findingId,
        disposition: "open",
        response_note: "",
        changed_locations: [],
        user_priority: null,
        reviewed: false,
        updated_at: at,
        status_history: [{ disposition: "open", at }],
        events: [{
          event_id: newEventId(`${findingId}:initial`),
          type: "disposition_changed",
          at,
          disposition: "open",
          parent_event_id: null,
          origin: eventOptions.origin || "local",
        }],
      };
  if (base.finding_id !== findingId) throw new Error("current action belongs to a different finding ID");
  if (Date.parse(at) < Date.parse(base.updated_at)) throw new Error("action timestamp cannot move backwards");
  const disposition = patch.disposition ?? base.disposition;
  assertDisposition(disposition, "action disposition");
  const responseNote = patch.response_note ?? base.response_note;
  if (typeof responseNote !== "string" || responseNote.length > MAX_NOTE_CHARS) {
    throw new Error(`action response_note must be text of at most ${MAX_NOTE_CHARS} characters`);
  }
  const changedLocations = patch.changed_locations ?? base.changed_locations;
  if (!Array.isArray(changedLocations)) throw new Error("action changed_locations must be an array");
  const normalizedLocations = changedLocations.map((location, index) => {
    assertNonemptyString(location, `action changed_locations[${index}]`, MAX_LOCATION_CHARS);
    return location;
  });
  if (new Set(normalizedLocations).size !== normalizedLocations.length) {
    throw new Error("action changed_locations must not contain duplicates");
  }
  const userPriority = patch.user_priority === undefined ? base.user_priority : patch.user_priority;
  assertPriority(userPriority, "action user_priority");
  const reviewed = patch.reviewed ?? base.reviewed;
  if (typeof reviewed !== "boolean") throw new Error("action reviewed must be a boolean");
  if (["not_relevant", "not_addressable"].includes(disposition) && !reviewed) {
    throw new Error(`action ${disposition} must be marked reviewed`);
  }
  const locationsUnchanged = normalizedLocations.length === base.changed_locations.length
    && normalizedLocations.every((location, index) => location === base.changed_locations[index]);
  if (
    current
    && disposition === base.disposition
    && responseNote === base.response_note
    && locationsUnchanged
    && userPriority === base.user_priority
    && reviewed === base.reviewed
  ) return base;
  const statusHistory = base.status_history.map((entry) => ({ ...entry }));
  if (disposition !== base.disposition) statusHistory.push({ disposition, at });
  const events = base.events.map((event) => ({ ...event }));
  const appendEvent = (event: Omit<ReviewActionEvent, "event_id" | "parent_event_id">) => {
    events.push({
      ...event,
      event_id: newEventId(`${findingId}:${event.type}`),
      parent_event_id: events.at(-1)?.event_id || null,
    });
  };
  if (disposition !== base.disposition) appendEvent({
    type: eventOptions.type || "disposition_changed",
    at,
    disposition,
    origin: eventOptions.origin || "local",
  });
  if (responseNote !== base.response_note) appendEvent({
    type: "note_revised",
    at,
    note: responseNote || null,
    origin: eventOptions.origin || "local",
  });
  if (userPriority !== base.user_priority) appendEvent({
    type: "priority_changed",
    at,
    user_priority: userPriority,
    origin: eventOptions.origin || "local",
  });
  if (reviewed !== base.reviewed) appendEvent({
    type: "reviewed_changed",
    at,
    reviewed,
    origin: eventOptions.origin || "local",
  });
  return cloneEntry({
    finding_id: findingId,
    disposition,
    response_note: responseNote,
    changed_locations: normalizedLocations,
    user_priority: userPriority,
    reviewed,
    updated_at: at,
    status_history: statusHistory,
    events,
  }, `action ${findingId}`);
}

/** Add provenance for an imported entry without changing its replayed state. */
export function recordReviewActionImport(entry: ReviewActionEntry, at = new Date().toISOString()): ReviewActionEntry {
  const checked = cloneEntry(entry, `action ${entry.finding_id}`);
  const effectiveAt = Date.parse(at) < Date.parse(checked.updated_at) ? checked.updated_at : at;
  const events = [...checked.events, {
    event_id: newEventId(`${checked.finding_id}:imported`),
    type: "imported" as const,
    at: effectiveAt,
    parent_event_id: checked.events.at(-1)?.event_id || null,
    origin: "import" as const,
  }];
  return cloneEntry({ ...checked, updated_at: effectiveAt, events }, `action ${entry.finding_id}`);
}

const ROUND_EXCLUSIONS = new Set<ReviewActionDisposition>(["not_relevant", "not_addressable"]);
const ROUND_ACTIVE_DISPOSITIONS = new Set<ReviewActionDisposition>(["open", "ready_for_recheck", "challenged"]);

function nextActionTimestamp(entry: ReviewActionEntry, requestedAt: string): string {
  assertDateTime(requestedAt, "round rollover timestamp");
  const previous = Date.parse(entry.updated_at);
  const requested = Date.parse(requestedAt);
  const next = Math.max(requested, previous + 1);
  const rendered = new Date(next).toISOString();
  // RFC 3339 in this contract intentionally uses a four-digit year. At the
  // representable ceiling, retaining the previous timestamp is still
  // monotonic and keeps the append-only event chain valid.
  return /^\d{4}-/.test(rendered) ? rendered : entry.updated_at;
}

/**
 * Carry an exact-ID action into a changed-fingerprint review round.
 *
 * Notes, personal priority, changed locations, and the complete event trail
 * remain intact. Active workflow claims reopen and all surviving comments must
 * be considered again. Explicit reviewed exclusions retain their reviewed
 * state because the v0.4 contract requires it; they normally do not survive as
 * active findings in the next ledger.
 */
export function rolloverReviewActionForNextRound(
  entryValue: ReviewActionEntry,
  at = new Date().toISOString(),
): ReviewActionEntry {
  const entry = cloneEntry(entryValue, `action ${entryValue.finding_id}`);
  const preservesReviewedExclusion = ROUND_EXCLUSIONS.has(entry.disposition);
  const disposition = ROUND_ACTIVE_DISPOSITIONS.has(entry.disposition) ? "open" : entry.disposition;
  const reviewed = preservesReviewedExclusion ? true : false;
  if (disposition === entry.disposition && reviewed === entry.reviewed) return entry;
  return updateReviewAction(
    entry,
    entry.finding_id,
    { disposition, reviewed },
    nextActionTimestamp(entry, at),
    { origin: "import" },
  );
}

/** Reconcile exact canonical IDs. A different review ID is never applied; a revised fingerprint starts a safe new-round rollover. */
export function reconcileReviewActions(
  payloadValue: unknown,
  current: { review_id: string; review_fingerprint: string; finding_ids: string[] },
  options: { rollover_at?: string } = {},
): ReviewActionsReconciliation {
  const payload = parseReviewActions(payloadValue);
  assertNonemptyString(current.review_id, "current review_id");
  assertNonemptyString(current.review_fingerprint, "current review_fingerprint");
  const findingIds = current.finding_ids.map((findingId, index) => {
    assertFindingId(findingId, `current finding_ids[${index}]`);
    return findingId;
  });
  if (new Set(findingIds).size !== findingIds.length) throw new Error("current finding_ids must be unique");
  const reviewIdMatches = payload.source_review_id === current.review_id;
  const fingerprintMatches = payload.source_review_fingerprint === current.review_fingerprint;
  const warnings: ReconciliationWarning[] = [];
  if (!reviewIdMatches) {
    warnings.push({
      code: "review_id_mismatch",
      message: `Actions belong to review ${payload.source_review_id}; current review is ${current.review_id}. No actions were applied.`,
    });
  }
  if (!fingerprintMatches) {
    warnings.push({
      code: "fingerprint_mismatch",
      message: reviewIdMatches
        ? "The review ledger changed after these actions were exported. Notes and personal priorities were carried forward for exact surviving finding IDs, but current comments must be reviewed again; active workflow states were reopened. Explicit not-relevant or not-addressable exclusions remain reviewed if their exact IDs still survive."
        : "The action file also has a different review fingerprint. No actions were applied because its review ID does not match the current review.",
    });
  }

  const allowed = new Set(findingIds);
  const matchedEntries = reviewIdMatches
    ? payload.entries.filter((entry) => allowed.has(entry.finding_id))
    : [];
  const matchedIds = new Set(matchedEntries.map((entry) => entry.finding_id));
  const unmatchedEntryIds = reviewIdMatches
    ? payload.entries.filter((entry) => !allowed.has(entry.finding_id)).map((entry) => entry.finding_id)
    : payload.entries.map((entry) => entry.finding_id);
  if (unmatchedEntryIds.length) {
    warnings.push({
      code: "unmatched_entries",
      message: `${unmatchedEntryIds.length} action ${unmatchedEntryIds.length === 1 ? "entry does" : "entries do"} not match an exact current finding ID.`,
    });
  }
  const reconciledEntries = matchedEntries.map((entry) => (
    fingerprintMatches
      ? cloneEntry(entry, `entry ${entry.finding_id}`)
      : rolloverReviewActionForNextRound(entry, options.rollover_at)
  ));
  const rereviewRequiredIds = fingerprintMatches ? [] : reconciledEntries
    .filter((entry) => !ROUND_EXCLUSIONS.has(entry.disposition))
    .map((entry) => entry.finding_id);
  return {
    entries: Object.fromEntries(reconciledEntries.map((entry) => [entry.finding_id, entry])),
    matched_finding_ids: matchedEntries.map((entry) => entry.finding_id),
    unmatched_entry_ids: unmatchedEntryIds,
    untouched_finding_ids: findingIds.filter((findingId) => !matchedIds.has(findingId)),
    rereview_required_finding_ids: rereviewRequiredIds,
    review_id_matches: reviewIdMatches,
    fingerprint_matches: fingerprintMatches,
    warnings,
  };
}

function cloneEntryMap(value: Record<string, ReviewActionEntry>, label: string): Record<string, ReviewActionEntry> {
  if (!isRecord(value)) throw new Error(`${label} must be an entry map`);
  const cloned: Record<string, ReviewActionEntry> = {};
  for (const [findingId, entry] of Object.entries(value)) {
    assertFindingId(findingId, `${label} finding ID`);
    const checked = cloneEntry(entry, `${label} ${findingId}`);
    if (checked.finding_id !== findingId) {
      throw new Error(`${label} map key ${findingId} does not match entry finding ID ${checked.finding_id}`);
    }
    cloned[findingId] = checked;
  }
  return cloned;
}

function historyIsPrefix(
  prefix: ReviewActionHistoryEntry[],
  complete: ReviewActionHistoryEntry[],
): boolean {
  return prefix.length <= complete.length && prefix.every((entry, index) => (
    entry.disposition === complete[index].disposition && entry.at === complete[index].at
  ));
}

function entriesAreIdentical(left: ReviewActionEntry, right: ReviewActionEntry): boolean {
  return left.finding_id === right.finding_id
    && left.disposition === right.disposition
    && left.response_note === right.response_note
    && left.user_priority === right.user_priority
    && left.reviewed === right.reviewed
    && left.updated_at === right.updated_at
    && left.changed_locations.length === right.changed_locations.length
    && left.changed_locations.every((value, index) => value === right.changed_locations[index])
    && left.status_history.length === right.status_history.length
    && historyIsPrefix(left.status_history, right.status_history)
    && left.events.length === right.events.length
    && left.events.every((event, index) => JSON.stringify(event) === JSON.stringify(right.events[index]));
}

function eventsArePrefix(prefix: ReviewActionEvent[], complete: ReviewActionEvent[]): boolean {
  return prefix.length <= complete.length && prefix.every((event, index) => JSON.stringify(event) === JSON.stringify(complete[index]));
}

/**
 * Merge exact-ID action entries without losing newer browser work or truncating history.
 *
 * A newer import is applied only when the current event chain is a prefix of the
 * imported chain. An older import is stale only when its events are a prefix
 * of the current chain. Equal, byte-equivalent logical entries are idempotent;
 * equal timestamps with divergent content and non-prefix histories are conflicts.
 */
export function mergeReviewActionEntries(
  currentValue: Record<string, ReviewActionEntry>,
  importedValue: Record<string, ReviewActionEntry>,
): ReviewActionMergeResult {
  const current = cloneEntryMap(currentValue, "current actions");
  const imported = cloneEntryMap(importedValue, "imported actions");
  const merged = cloneEntryMap(current, "current actions");
  const applied: string[] = [];
  const stale: string[] = [];
  const conflicts: string[] = [];
  const warnings: ReviewActionMergeWarning[] = [];

  for (const findingId of Object.keys(imported).sort()) {
    const incoming = imported[findingId];
    const existing = current[findingId];
    if (!existing) {
      merged[findingId] = cloneEntry(incoming, `imported actions ${findingId}`);
      applied.push(findingId);
      continue;
    }
    if (entriesAreIdentical(existing, incoming)) {
      applied.push(findingId);
      continue;
    }

    const incomingTime = Date.parse(incoming.updated_at);
    const existingTime = Date.parse(existing.updated_at);
    if (incomingTime === existingTime) {
      conflicts.push(findingId);
      warnings.push({
        code: "equal_timestamp_divergence",
        finding_id: findingId,
        message: `${findingId} has different action content at the same updated_at timestamp; current work was kept.`,
      });
      continue;
    }

    if (incomingTime > existingTime) {
      if (eventsArePrefix(existing.events, incoming.events)) {
        merged[findingId] = cloneEntry(incoming, `imported actions ${findingId}`);
        applied.push(findingId);
      } else {
        conflicts.push(findingId);
        warnings.push({
          code: "non_prefix_history",
          finding_id: findingId,
          message: `${findingId} has a newer import whose event chain does not extend current history; current work was kept.`,
        });
      }
      continue;
    }

    if (eventsArePrefix(incoming.events, existing.events)) {
      stale.push(findingId);
    } else {
      conflicts.push(findingId);
      warnings.push({
        code: "non_prefix_history",
        finding_id: findingId,
        message: `${findingId} has an older import with a non-prefix event chain; current work was kept.`,
      });
    }
  }

  return {
    entries: merged,
    applied_finding_ids: applied,
    stale_finding_ids: stale,
    conflict_finding_ids: conflicts,
    warnings,
  };
}
