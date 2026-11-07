// Reads the candidate readings out of a review entry's `detail`. Normalizers put them in
// `detail.structured.candidates` (date: {interpretation, day, month, year}; name:
// {given_name, family_name}; currency and others: plain strings). A shape this file does
// not know is shown as JSON text and cannot be sent: a reading is never invented (AGENTS.md
// section 4, "Never guess on ambiguous data").

export interface Reading {
  /** What the person sees for this reading. */
  shown: string;
  /** Short tag such as "DMY"; empty when the normalizer gave none. */
  tag: string;
  /** The decided_value string the API accepts, or null when this shape cannot be sent. */
  value: string | null;
  /** Why `value` is null; empty otherwise. */
  note: string;
}

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const digits = (v: unknown): string | null =>
  (typeof v === "string" || typeof v === "number") && /^\d{1,4}$/.test(String(v)) ? String(v) : null;

function candidateList(detail: unknown): unknown[] {
  if (!isObj(detail)) return [];
  const structured = detail.structured;
  if (isObj(structured) && Array.isArray(structured.candidates)) return structured.candidates;
  return Array.isArray(detail.candidates) ? detail.candidates : [];
}

function fromObject(c: Obj): Reading {
  const tag = typeof c.interpretation === "string" ? c.interpretation : "";
  const day = digits(c.day);
  const month = digits(c.month);
  const year = digits(c.year);
  if (day !== null && month !== null && year !== null) {
    const iso = `${year.padStart(4, "0")}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
    // A two-digit year has no century in the data; choosing one would be a guess.
    if (year.length === 4) return { shown: iso, tag, value: iso, note: "" };
    return {
      shown: `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`,
      tag,
      value: null,
      note: "The year has no century in the data. Type the full date with o.",
    };
  }
  const given = c.given_name;
  const family = c.family_name;
  if (typeof given === "string" && typeof family === "string") {
    // The "Family, Given" form is the one the name normalizer itself treats as unambiguous
    // (normalizers/name.py, the `"," not in cleaned` test). The API still checks it (422).
    return { shown: `${given} ${family}`, tag: "given, family", value: `${family}, ${given}`, note: "" };
  }
  return { shown: JSON.stringify(c), tag, value: null, note: "Unknown reading shape. Type the value with o." };
}

export function extractReadings(detail: unknown): Reading[] {
  return candidateList(detail).map((c) => {
    if (typeof c === "string") return { shown: c, tag: "", value: c, note: "" };
    if (isObj(c)) return fromObject(c);
    return { shown: JSON.stringify(c), tag: "", value: null, note: "Unknown reading shape. Type the value with o." };
  });
}

/** Warnings and errors the normalizer attached; plain strings only. */
export function extractNotes(detail: unknown): string[] {
  if (!isObj(detail)) return [];
  return [detail.warnings, detail.errors].flatMap((v) =>
    Array.isArray(v) ? v.filter((s): s is string => typeof s === "string") : [],
  );
}
