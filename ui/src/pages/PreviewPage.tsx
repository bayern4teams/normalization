// Source.txt §83 (sample-based preview) + §118 (BEFORE/AFTER two-column
// with expandable DETAILS/TRACE) + §117 (explanation).
import { useMutation } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { preview } from "../api/client";
import { FIELD_SEMANTIC_TYPES, type FieldSemanticType, type NormalizedValue } from "../api/types";
import { ExplanationPanel } from "../components/ExplanationPanel";
import { useMode } from "../app/ModeContext";

const SAMPLE_PRESETS = [10, 100, 1000] as const;

export function PreviewPage() {
  const { mode } = useMode();
  const [fieldName, setFieldName] = useState("example_field");
  const [semanticType, setSemanticType] = useState<FieldSemanticType>("PERSON_NAME");
  const [rawValues, setRawValues] = useState('  José García, Jr.  \nJOSÉ GARCÍA\nJose Garcia');
  const [sampleSize, setSampleSize] = useState<number>(10);
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      const values = rawValues
        .split("\n")
        .map((v) => v.trim())
        .filter((v) => v.length > 0)
        .slice(0, sampleSize);
      return preview({ field_name: fieldName, semantic_type: semanticType, values });
    },
  });

  const originals = rawValues
    .split("\n")
    .map((v) => v.trim())
    .filter((v) => v.length > 0)
    .slice(0, sampleSize);

  return (
    <section>
      <h1>Preview</h1>
      <p className="hint">
        Never requires full-dataset processing — pick a sample size, paste values (one per line),
        and see BEFORE/AFTER against the real live dispatcher (§83).
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
            <select
              value={semanticType}
              onChange={(e) => setSemanticType(e.target.value as FieldSemanticType)}
            >
              {FIELD_SEMANTIC_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            Sample size
            <select value={sampleSize} onChange={(e) => setSampleSize(Number(e.target.value))}>
              {SAMPLE_PRESETS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
              <option value={originals.length || 1}>Custom (all pasted rows)</option>
            </select>
          </label>
        </div>
        <label className="preview-form__values">
          Values (one per line)
          <textarea
            rows={6}
            value={rawValues}
            onChange={(e) => setRawValues(e.target.value)}
          />
        </label>
        <button type="submit" disabled={mutation.isPending || originals.length === 0}>
          Run preview ({Math.min(originals.length, sampleSize)} values)
        </button>
      </form>

      {mutation.isError && (
        <p className="state-message state-message--error">
          Preview failed: {(mutation.error as Error).message}
        </p>
      )}

      {mutation.data && (
        <table className="data-table preview-table">
          <thead>
            <tr>
              <th>BEFORE</th>
              <th>AFTER (display)</th>
              <th>Comparison</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {mutation.data.map((result: NormalizedValue, index: number) => (
              <Fragment key={index}>
                <tr>
                  <td>{result.original ?? <em>null</em>}</td>
                  <td>{result.display ?? <em>null</em>}</td>
                  <td>{result.comparison ?? <em>null</em>}</td>
                  <td>
                    <span
                      className={`status-pill status-pill--${result.normalization_status.toLowerCase()}`}
                    >
                      {result.normalization_status}
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      onClick={() => setExpandedIndex(expandedIndex === index ? null : index)}
                    >
                      {expandedIndex === index ? "Hide" : "Details"}
                    </button>
                  </td>
                </tr>
                {expandedIndex === index && (
                  <tr>
                    <td colSpan={5}>
                      <ExplanationPanel result={result} />
                      {mode !== "normal" && Object.keys(result.structured).length > 0 && (
                        <>
                          <h4>Parsed structure</h4>
                          <dl className="kv-list">
                            {Object.entries(result.structured).map(([key, value]) => (
                              <Fragment key={key}>
                                <dt>{key}</dt>
                                <dd>{JSON.stringify(value)}</dd>
                              </Fragment>
                            ))}
                          </dl>
                        </>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
