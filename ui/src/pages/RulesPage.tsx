// Source.txt §81/§116 Rule Builder UX. Renders the REAL pipeline steps a
// live field-test call actually executed (NormalizedValue.trace) — not
// an invented generic pipeline. Drag-to-reorder and enable/disable are
// visual-only affordances: per-field pipeline configuration isn't
// threaded into individual normalizers yet (the same disclosed gap
// carried since M2 — see the M7 verification pack), so these controls
// do not change what the backend actually runs. "Test" re-runs
// field-test for real against whatever value you type.
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { fieldTest } from "../api/client";
import { FIELD_SEMANTIC_TYPES, type FieldSemanticType, type TraceStep } from "../api/types";
import { technicalExplanationLine } from "../lib/explain";

interface StepCard {
  step: TraceStep;
  enabled: boolean;
}

export function RulesPage() {
  const [fieldName, setFieldName] = useState("example_field");
  const [semanticType, setSemanticType] = useState<FieldSemanticType>("PERSON_NAME");
  const [testValue, setTestValue] = useState("  José García, Jr.  ");
  const [steps, setSteps] = useState<StepCard[]>([]);
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  const mutation = useMutation({
    mutationFn: () => fieldTest({ field_name: fieldName, semantic_type: semanticType, value: testValue }),
    onSuccess: (result) => {
      setSteps(result.trace.map((step) => ({ step, enabled: true })));
    },
  });

  function onDrop(targetIndex: number) {
    if (dragIndex === null || dragIndex === targetIndex) return;
    setSteps((prev) => {
      const next = [...prev];
      const [moved] = next.splice(dragIndex, 1);
      next.splice(targetIndex, 0, moved);
      return next;
    });
    setDragIndex(null);
  }

  return (
    <section>
      <h1>Rule Builder</h1>
      <p className="hint">
        Loads the real pipeline the live dispatcher executed for a test value. Drag to reorder and
        the enable/disable toggle are visualization aids only — they do not change what the server
        runs (per-field pipeline configuration isn't wired into normalizers yet).
      </p>

      <form
        className="preview-form"
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <div className="preview-form__row">
          <label>
            Field name
            <input value={fieldName} onChange={(e) => setFieldName(e.target.value)} />
          </label>
          <label>
            Semantic type
            <select value={semanticType} onChange={(e) => setSemanticType(e.target.value as FieldSemanticType)}>
              {FIELD_SEMANTIC_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            Test value
            <input value={testValue} onChange={(e) => setTestValue(e.target.value)} />
          </label>
        </div>
        <button type="submit" disabled={mutation.isPending}>
          Load pipeline
        </button>
      </form>

      {mutation.isError && (
        <p className="state-message state-message--error">{(mutation.error as Error).message}</p>
      )}

      {mutation.data && (
        <p>
          Result: <strong>{mutation.data.display ?? "null"}</strong> (
          {mutation.data.normalization_status})
        </p>
      )}

      {steps.length > 0 && (
        <ol className="pipeline-list">
          {steps.map((card, index) => (
            <li
              key={`${card.step.step_order}-${card.step.rule_id}`}
              draggable
              className={`pipeline-step${card.enabled ? "" : " pipeline-step--disabled"}`}
              onDragStart={() => setDragIndex(index)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => onDrop(index)}
            >
              <div className="pipeline-step__header">
                <span className="pipeline-step__handle">⠿</span>
                <strong>{card.step.operation}</strong>
                <label className="pipeline-step__toggle">
                  <input
                    type="checkbox"
                    checked={card.enabled}
                    onChange={() =>
                      setSteps((prev) =>
                        prev.map((s, i) => (i === index ? { ...s, enabled: !s.enabled } : s)),
                      )
                    }
                  />
                  enabled
                </label>
              </div>
              <p className="pipeline-step__detail">{technicalExplanationLine(card.step)}</p>
              <p className="pipeline-step__meta">
                reversibility={card.step.reversibility} lossy={String(card.step.lossy)} library=
                {card.step.library ?? "—"}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
