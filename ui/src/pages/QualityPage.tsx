// Source.txt §93 Quality Dashboard.
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getQuality } from "../api/client";
import { QueryState } from "../components/QueryState";

export function QualityPage() {
  const query = useQuery({ queryKey: ["quality"], queryFn: getQuality });

  return (
    <section>
      <h1>Quality Dashboard</h1>
      <QueryState isLoading={query.isPending} isError={query.isError} error={query.error}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Semantic type</th>
              <th>Count</th>
              <th>Evaluated</th>
              <th>Rate</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {query.data?.metrics.map((m) => (
              <tr key={m.name}>
                <td>{m.name}</td>
                <td>{m.semantic_type}</td>
                <td>{m.count}</td>
                <td>{m.total_evaluated}</td>
                <td>{m.total_evaluated > 0 ? `${((m.count / m.total_evaluated) * 100).toFixed(1)}%` : "—"}</td>
                <td>
                  <Link to="/runs">Inspect runs</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </QueryState>
      <p className="hint">
        Each metric only counts runs of the matching semantic type — a metric with no matching
        runs correctly shows 0, not a fabricated number. Drill-down currently points at the Runs
        list (per-metric run filtering isn't wired up yet).
      </p>
    </section>
  );
}
