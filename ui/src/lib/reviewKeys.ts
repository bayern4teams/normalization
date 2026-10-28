// Key handling of the Review screen as one pure function, so it can be read and tested
// without a browser. One key, no modifier, no chord (R18). Digits pick a reading; nothing is
// pre-selected, so "accept" is the pick itself.

export type ReviewAction =
  | { type: "pick"; index: number } // 0-based reading index
  | { type: "other" }
  | { type: "keep" }
  | { type: "undo" };

export const OTHER_KEY = "o";
export const KEEP_KEY = "k";
export const UNDO_KEY = "u";
/** Number keys reach readings 1..9; a tenth reading needs `o`. */
export const MAX_NUMBERED_READINGS = 9;

export interface KeyEventLike {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  repeat: boolean;
  isComposing?: boolean;
}

export interface TargetLike {
  tagName?: string;
  isContentEditable?: boolean;
}

const TEXT_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);

/** True while the person is typing; every review key is then ignored. */
export function isTextTarget(target: TargetLike | null | undefined): boolean {
  if (!target) return false;
  return Boolean(target.isContentEditable) || TEXT_TAGS.has((target.tagName ?? "").toUpperCase());
}

export function actionForKey(
  event: KeyEventLike,
  readingCount: number,
  target?: TargetLike | null,
): ReviewAction | null {
  // A held key repeats; one decision per press, or a held "1" would run through the list.
  if (event.repeat || event.isComposing) return null;
  if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return null;
  if (isTextTarget(target)) return null;
  const key = event.key.toLowerCase();
  if (/^[1-9]$/.test(key)) {
    const index = Number(key) - 1;
    return index < Math.min(readingCount, MAX_NUMBERED_READINGS) ? { type: "pick", index } : null;
  }
  if (key === OTHER_KEY) return { type: "other" };
  if (key === KEEP_KEY) return { type: "keep" };
  if (key === UNDO_KEY) return { type: "undo" };
  return null;
}
