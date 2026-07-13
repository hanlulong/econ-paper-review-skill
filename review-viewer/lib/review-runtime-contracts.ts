export type BurdenTrigger = {
  kind: "anchor" | "claim" | "required_omission";
  ref: string;
  rationale: string;
};

export type ActivatedBurden = {
  id: string;
  object_type: "claim" | "design" | "measurement" | "inference" | "theory" | "computation" | "literature" | "writing" | "exhibit" | "reproducibility" | "other";
  status: "active" | "not_applicable";
  activation_basis: "observed" | "missing_required" | "mixed" | "not_applicable";
  triggers: BurdenTrigger[];
  nonactivation_reason: string | null;
};

const OBJECT_TYPES = new Set([
  "claim", "design", "measurement", "inference", "theory", "computation",
  "literature", "writing", "exhibit", "reproducibility", "other",
]);
const ACTIVATION_BASES = new Set(["observed", "missing_required", "mixed", "not_applicable"]);
const TRIGGER_KINDS = new Set(["anchor", "claim", "required_omission"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/**
 * Check the viewer-facing invariants of v0.4 burden activation metadata.
 * The canonical Python validator remains responsible for the full run schema.
 */
export function validateActivatedBurdens(value: unknown): ActivatedBurden[] {
  if (!Array.isArray(value) || !value.length) throw new Error("v0.4 run.json must declare at least one activated burden");
  const ids = new Set<string>();
  return value.map((raw, index) => {
    const label = `activated_burdens[${index}]`;
    if (!isRecord(raw) || typeof raw.id !== "string" || !/^[a-z][a-z0-9_]{2,79}$/.test(raw.id) || ids.has(raw.id)) {
      throw new Error(`${label}.id must be a unique canonical burden ID`);
    }
    if (typeof raw.object_type !== "string" || !OBJECT_TYPES.has(raw.object_type)) throw new Error(`${label}.object_type is unsupported`);
    if (raw.status !== "active" && raw.status !== "not_applicable") throw new Error(`${label}.status is unsupported`);
    if (typeof raw.activation_basis !== "string" || !ACTIVATION_BASES.has(raw.activation_basis)) throw new Error(`${label}.activation_basis is unsupported`);
    if (!Array.isArray(raw.triggers)) throw new Error(`${label}.triggers must be an array`);
    const triggers = raw.triggers.map((trigger, triggerIndex) => {
      if (
        !isRecord(trigger) || typeof trigger.kind !== "string" || !TRIGGER_KINDS.has(trigger.kind)
        || typeof trigger.ref !== "string" || !trigger.ref.trim()
        || typeof trigger.rationale !== "string" || !trigger.rationale.trim()
      ) throw new Error(`${label}.triggers[${triggerIndex}] is malformed`);
      return { kind: trigger.kind, ref: trigger.ref, rationale: trigger.rationale } as BurdenTrigger;
    });
    if (raw.status === "active") {
      if (!triggers.length || raw.nonactivation_reason !== null) throw new Error(`${label} active burdens need a trigger and null nonactivation_reason`);
    } else if (triggers.length || typeof raw.nonactivation_reason !== "string" || !raw.nonactivation_reason.trim()) {
      throw new Error(`${label} not-applicable burdens need no triggers and a reason`);
    }
    ids.add(raw.id);
    return {
      id: raw.id,
      object_type: raw.object_type,
      status: raw.status,
      activation_basis: raw.activation_basis,
      triggers,
      nonactivation_reason: raw.nonactivation_reason,
    } as ActivatedBurden;
  });
}
