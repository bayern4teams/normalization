import type { TraceStep } from "../api/types";
import { technicalExplanationLine } from "../lib/explain";

export function TraceView({ trace }: { trace: TraceStep[] }) {
  if (trace.length === 0) {
    return <p className="hint">No trace steps recorded for this value.</p>;
  }
  return (
    <table className="data-table data-table--compact">
      <thead>
        <tr>
          <th>#</th>
          <th>Operation</th>
          <th>Explanation</th>
          <th>Reversibility</th>
          <th>Lossy</th>
          <th>Library</th>
        </tr>
      </thead>
      <tbody>
        {trace.map((step) => (
          <tr key={`${step.step_order}-${step.rule_id}`}>
            <td>{step.step_order}</td>
            <td>{step.operation}</td>
            <td>{technicalExplanationLine(step)}</td>
            <td>{step.reversibility}</td>
            <td>{step.lossy ? "yes" : "no"}</td>
            <td>
              {step.library ?? "—"} {step.library_version ?? ""}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
