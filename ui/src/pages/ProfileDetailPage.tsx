// Source.txt §95/§120 — profile detail, version history, rollback.
// "Activate"/"Deactivate" as standalone actions are NOT implemented
// server-side (only implicit via versioning/rollback) — no button here
// pretends otherwise; see the M7 verification pack for the disclosed gap.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { getProfile, listProfileVersions, rollbackProfile } from "../api/client";
import { useMode } from "../app/ModeContext";
import { QueryState } from "../components/QueryState";

export function ProfileDetailPage() {
  const { profileId } = useParams<{ profileId: string }>();
  const { mode } = useMode();
  const queryClient = useQueryClient();

  const profileQuery = useQuery({
    queryKey: ["profile", profileId],
    queryFn: () => getProfile(profileId as string),
    enabled: Boolean(profileId),
  });
  const versionsQuery = useQuery({
    queryKey: ["profile-versions", profileId],
    queryFn: () => listProfileVersions(profileId as string),
    enabled: Boolean(profileId),
  });

  const rollbackMutation = useMutation({
    mutationFn: (targetVersion: string) => rollbackProfile(profileId as string, targetVersion),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["profile", profileId] });
      queryClient.invalidateQueries({ queryKey: ["profile-versions", profileId] });
      queryClient.invalidateQueries({ queryKey: ["profiles"] });
    },
  });

  if (!profileId) return null;

  return (
    <section>
      <h1>Profile detail</h1>
      <QueryState
        isLoading={profileQuery.isPending}
        isError={profileQuery.isError}
        error={profileQuery.error}
      >
        {profileQuery.data && (
          <div className="detail-card">
            <h2>{profileQuery.data.name}</h2>
            <p>
              Active version <strong>{profileQuery.data.version}</strong> —{" "}
              <span className={`status-pill status-pill--${profileQuery.data.status.toLowerCase()}`}>
                {profileQuery.data.status}
              </span>
            </p>
            <p>{profileQuery.data.description || "No description."}</p>
            <p>
              Fields configured: <strong>{profileQuery.data.field_configs.length}</strong>
            </p>
            {mode !== "normal" && (
              <dl className="kv-list">
                <dt>id</dt>
                <dd>{profileQuery.data.id}</dd>
                <dt>created_by</dt>
                <dd>{profileQuery.data.created_by}</dd>
                <dt>created_at</dt>
                <dd>{profileQuery.data.created_at}</dd>
                <dt>parent_version</dt>
                <dd>{profileQuery.data.parent_version ?? "—"}</dd>
              </dl>
            )}
          </div>
        )}
      </QueryState>

      <h3>Version history</h3>
      <QueryState
        isLoading={versionsQuery.isPending}
        isError={versionsQuery.isError}
        error={versionsQuery.error}
        isEmpty={versionsQuery.data?.length === 0}
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Version</th>
              <th>Status</th>
              <th>Description</th>
              <th>Created at</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {versionsQuery.data?.map((v) => (
              <tr key={v.version}>
                <td>{v.version}</td>
                <td>
                  <span className={`status-pill status-pill--${v.status.toLowerCase()}`}>{v.status}</span>
                </td>
                <td>{v.description || "—"}</td>
                <td>{v.created_at}</td>
                <td>
                  {v.status !== "ACTIVE" && (
                    <button
                      type="button"
                      disabled={rollbackMutation.isPending}
                      onClick={() => rollbackMutation.mutate(v.version)}
                    >
                      Rollback to this version
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </QueryState>
      {rollbackMutation.isError && (
        <p className="state-message state-message--error">
          Rollback failed: {(rollbackMutation.error as Error).message}
        </p>
      )}
    </section>
  );
}
