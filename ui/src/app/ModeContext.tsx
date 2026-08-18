// Normal / Expert / Admin mode switch — Source.txt §86-88. Purely a
// client-side display filter: every mode calls the exact same real API,
// the mode only controls which fields of the real response render.
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

export type UiMode = "normal" | "expert" | "admin";

const STORAGE_KEY = "normalization-ui-mode";

interface ModeContextValue {
  mode: UiMode;
  setMode: (mode: UiMode) => void;
}

const ModeContext = createContext<ModeContextValue | null>(null);

function readStoredMode(): UiMode {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "normal" || stored === "expert" || stored === "admin") {
    return stored;
  }
  return "normal";
}

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<UiMode>(readStoredMode);

  const setMode = (next: UiMode) => {
    setModeState(next);
    window.localStorage.setItem(STORAGE_KEY, next);
  };

  const value = useMemo(() => ({ mode, setMode }), [mode]);

  return <ModeContext.Provider value={value}>{children}</ModeContext.Provider>;
}

export function useMode(): ModeContextValue {
  const ctx = useContext(ModeContext);
  if (!ctx) {
    throw new Error("useMode must be used within a ModeProvider");
  }
  return ctx;
}
