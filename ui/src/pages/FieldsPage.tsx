// Source.txt §89 Fields list — derived from real profile field_configs.
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listFields } from "../api/client";
import { QueryState } from "../components/QueryState";

export function FieldsPage() {
  const query = useQuery({ queryKey: ["fields"], queryFn: listFields });

  return (
    <section>
      <h1>Fields</h1>
      <QueryState
        isLoading={query.isPending}
        isError={query.isError}
        error={query.error}
        isEmpty={query.data?.length === 0}
        emptyMessage="No fields configured yet — add field_configs to a profile."
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Field</th>
              <th>Semantic type</th>
              <th>Profiles</th>
            </tr>
          </thead>
          <tbody>
            {query.data?.map((field) => (
              <tr key={field.field_ref}>
                <td>
                  <Link to={`/fields/${encodeURIComponent(field.field_ref)}`}>{field.field_ref}</Link>
                </td>
                <td>{field.semantic_type}</td>
                <td>{field.profile_ids.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </QueryState>
    </section>
  );
}
