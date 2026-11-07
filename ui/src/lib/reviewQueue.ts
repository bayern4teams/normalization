// The Review screen's state as a pure reducer: which value is current, which decisions are
// held back for undo, which were kept ambiguous. Side effects (timers, POSTs) live in the
// page; this file only moves state, so a key press updates the DOM without waiting for the
// network (0.1 s budget, NN/g).

// How long a decision is held back before it is sent, so `u` can still cancel it.
// ponytail: verdicts are append-only with no revoke route (ADR-018), so undo exists only
// while nothing has been sent; 5 s is a judgement, not a measured value. Upgrade path: a
// revoking verdict in the API, then no hold is needed.
export const UNDO_WINDOW_MS = 5000;

export type ItemStatus = "pending" | "held" | "sending" | "saved" | "skipped";

export interface QueueItem {
  key: string;
  status: ItemStatus;
  /** The decided_value held or sent, and the rationale that goes with it. */
  value?: string;
  rationale?: string;
  /** The API's text when the last send failed; the item is pending again. */
  error?: string;
}

export interface QueueState {
  items: QueueItem[];
  /** Index of the current value; items.length when none is left. */
  cursor: number;
  /** Item indexes in the order they were acted on, for undo. */
  history: number[];
  notice: string | null;
}

export type QueueAction =
  | { type: "decide"; value: string; rationale: string }
  | { type: "skip" }
  | { type: "undo" }
  | { type: "sending"; key: string }
  | { type: "saved"; key: string }
  | { type: "failed"; key: string; message: string }
  | { type: "goto"; index: number }
  | { type: "reviewAgain" }
  | { type: "notice"; text: string | null };

export function initialQueue(keys: string[]): QueueState {
  return {
    items: keys.map((key) => ({ key, status: "pending" as const })),
    cursor: 0,
    history: [],
    notice: null,
  };
}

const firstPending = (items: QueueItem[], from: number): number => {
  const i = items.findIndex((item, n) => n >= from && item.status === "pending");
  return i === -1 ? items.length : i;
};

export const isCurrent = (state: QueueState): boolean =>
  state.cursor < state.items.length && state.items[state.cursor].status === "pending";

const patch = (items: QueueItem[], index: number, change: Partial<QueueItem>): QueueItem[] =>
  items.map((item, n) => (n === index ? { ...item, ...change } : item));

const indexOfKey = (state: QueueState, key: string): number => state.items.findIndex((i) => i.key === key);

export function queueReducer(state: QueueState, action: QueueAction): QueueState {
  switch (action.type) {
    case "decide": {
      if (!isCurrent(state)) return state;
      const items = patch(state.items, state.cursor, {
        status: "held",
        value: action.value,
        rationale: action.rationale,
        error: undefined,
      });
      return {
        items,
        cursor: firstPending(items, state.cursor + 1),
        history: [...state.history, state.cursor],
        notice: null,
      };
    }
    case "skip": {
      // Keep ambiguous: nothing is stored and the entry stays pending on the server.
      if (!isCurrent(state)) return state;
      const items = patch(state.items, state.cursor, { status: "skipped" });
      return {
        items,
        cursor: firstPending(items, state.cursor + 1),
        history: [...state.history, state.cursor],
        notice: null,
      };
    }
    case "undo": {
      const last = state.history[state.history.length - 1];
      if (last === undefined) return { ...state, notice: "Nothing to undo." };
      const status = state.items[last].status;
      if (status === "sending" || status === "saved") {
        // ponytail: verdicts are append-only and the API has no revoke route, so only a
        // decision still held back can be undone. Upgrade path: a revoking verdict.
        return { ...state, notice: "Already saved. Verdicts are append-only and cannot be undone here." };
      }
      return {
        items: patch(state.items, last, { status: "pending", value: undefined }),
        cursor: last,
        history: state.history.slice(0, -1),
        notice: null,
      };
    }
    case "sending": {
      const i = indexOfKey(state, action.key);
      if (i === -1 || state.items[i].status !== "held") return state;
      return { ...state, items: patch(state.items, i, { status: "sending" }) };
    }
    case "saved": {
      const i = indexOfKey(state, action.key);
      if (i === -1) return state;
      return { ...state, items: patch(state.items, i, { status: "saved" }) };
    }
    case "failed": {
      const i = indexOfKey(state, action.key);
      if (i === -1) return state;
      // Back to pending with the API's text; the cursor stays where the person is.
      return {
        ...state,
        items: patch(state.items, i, { status: "pending", value: undefined, error: action.message }),
        history: state.history.filter((n) => n !== i),
      };
    }
    case "goto":
      return { ...state, cursor: action.index, notice: null };
    case "reviewAgain": {
      const items = state.items.map((item) =>
        item.status === "skipped" ? { ...item, status: "pending" as const } : item,
      );
      return { ...state, items, cursor: firstPending(items, 0), notice: null };
    }
    case "notice":
      return { ...state, notice: action.text };
  }
}
