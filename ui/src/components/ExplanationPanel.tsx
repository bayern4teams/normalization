// Source.txt §117 — "Why did this change?" Normal-mode users see plain
// language only; expert/admin also see the raw technical trace.
import type { NormalizedValue } from "../api/types";
import { useMode } from "../app/ModeContext";
import { plainLanguageExplanation } from "../lib/explain";
import { TraceView } from "./TraceView";

export function ExplanationPanel({ result }: { result: NormalizedValue }) {
  const { mode } = useMode();

  return (
    <div className="explanation-panel">
      <p className="explanation-panel__plain">{plainLanguageExplanation(result.trace)}</p>
      {mode !== "normal" && (
        <details className="explanation-panel__technical">
          <summary>Technical trace</summary>
          <TraceView trace={result.trace} />
        </details>
      )}
    </div>
  );
}
