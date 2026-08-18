// "Why did this change?" — Source.txt §117. Builds plain-language and
// technical explanations from the REAL trace steps a normalizer
// returned — never fabricated copy. The technical line mirrors
// TraceStep.to_explanation_line() (normcore/trace.py) exactly, since
// that method's output isn't itself serialized over the API.
import type { TraceStep } from "../api/types";

// Curated, not exhaustive (this project's established "curated subset,
// extend on evidence" policy) — operations not listed here still render
// correctly via the humanization fallback below, just less idiomatically.
const KNOWN_PHRASES: Record<string, string> = {
  "unicode.repair": "repaired mojibake/encoding damage",
  "unicode.nfc": "applied Unicode NFC normalization",
  "unicode.nfkc": "applied Unicode NFKC normalization",
  "text.trim": "trimmed leading/trailing whitespace",
  "text.collapse_whitespace": "collapsed repeated whitespace",
  "text.casefold": "lowercased the comparison representation",
  "text.strip_diacritics": "stripped accents/diacritics",
  "text.transliterate_ascii": "transliterated to ASCII",
  "text.normalize_punctuation": "normalized punctuation",
  "name.parse": "parsed into name components",
  "company.strip_suffix": "stripped a recognized legal entity suffix",
  "phone.parse": "parsed as a phone number",
  "email.validate": "validated and normalized the email address",
  "address.parse": "parsed the address into components",
  "date.parse": "parsed the date",
  "country.resolve": "resolved the country code",
  "language.resolve": "resolved the language code",
  "script.detect": "detected the dominant Unicode script",
  "identifier.normalize": "normalized digit representation",
  "numeric.parse": "parsed the number using locale rules",
  "currency.resolve": "resolved the currency code",
  "unit.convert": "converted to canonical SI base units",
  "boolean.resolve": "resolved to a canonical boolean",
  "url.normalize": "normalized the URL",
};

function humanizeOperation(operation: string): string {
  if (KNOWN_PHRASES[operation]) return KNOWN_PHRASES[operation];
  return operation.replace(/[._]/g, " ");
}

export function plainLanguageExplanation(trace: TraceStep[]): string {
  const changedSteps = trace.filter((step) => step.changed);
  if (changedSteps.length === 0) {
    return "No change — the value already matched its canonical form.";
  }
  const phrases = changedSteps.map((step) => humanizeOperation(step.operation));
  if (phrases.length === 1) return `${capitalize(phrases[0])}.`;
  const allButLast = phrases.slice(0, -1).join(", ");
  return `${capitalize(allButLast)}, and ${phrases[phrases.length - 1]}.`;
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function technicalExplanationLine(step: TraceStep): string {
  const verb = step.changed ? "changed" : "checked, no change";
  const lossyNote = step.lossy ? " (lossy — original preserved)" : "";
  return `Step ${step.step_order}: ${step.operation} — ${verb}${lossyNote}`;
}
