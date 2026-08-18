// Source.txt §90 — Normalization Overview dashboard.
import { useQuery } from "@tanstack/react-query";
import { getOverview } from "../api/client";
import { QueryState } from "../components/QueryState";

const CARDS: { key: keyof Awaited<ReturnType<typeof getOverview>>; label: string }[] = [
  { key: "fields_analyzed", label: "Fields analyzed" },
  { key: "fields_normalized", label: "Fields normalized" },
  { key: "rows_processed", label: "Rows processed" },
  { key: "values_changed", label: "Changed values" },
  { key: "warnings", label: "Warnings" },
  { key: "potential_collisions", label: "Potential collisions" },
  { key: "ambiguous_values", label: "Ambiguous values" },
  { key: "errors", label: "Errors" },
];

export function OverviewPage() {
  const query = useQuery({ queryKey: ["overview"], queryFn: getOverview });

  return (
    <section>
      <h1>Normalization Overview</h1>
      <QueryState isLoading={query.isPending} isError={query.isError} error={query.error}>
        {query.data && (
          <div className="card-grid">
            {CARDS.map((card) => (
              <div className="card" key={card.key}>
                <div className="card__value">{query.data[card.key].toLocaleString()}</div>
                <div className="card__label">{card.label}</div>
              </div>
            ))}
          </div>
        )}
      </QueryState>
      <p className="hint">
        Aggregated from every profile's configured fields and every executed run's real metrics —
        create a profile and run it (Runs page) to see these numbers move.
      </p>
    </section>
  );
}
