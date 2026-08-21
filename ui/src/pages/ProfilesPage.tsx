// Source.txt §89 Profiles list + create — real POST/GET /normalization/profiles.
// Creates a bare profile (name/description/created_by) — locale_policy
// and per-field locale_overrides/dictionary_refs/error_policy (real,
// backend-wired since M10, see NormalizationProfile.build_context) have
// no editor UI yet. A full field-config editor (repeatable rows with
// locale key/value pairs, dictionary multi-select, error-policy select)
// is real, separate UI work not attempted in M12's catch-up pass —
// disclosed here, not silently omitted. Setting locale_policy today
// requires POSTing directly (see tests/golden/test_m10_corpus.py for
// the exact shape).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { createProfile, listProfiles } from "../api/client";
import { QueryState } from "../components/QueryState";

export function ProfilesPage() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["profiles"], queryFn: listProfiles });
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [createdBy, setCreatedBy] = useState("");

  const createMutation = useMutation({
    mutationFn: () => createProfile({ name, description, created_by: createdBy || "ui-user" }),
    onSuccess: () => {
      setName("");
      setDescription("");
      queryClient.invalidateQueries({ queryKey: ["profiles"] });
    },
  });

  return (
    <section>
      <h1>Profiles</h1>

      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) createMutation.mutate();
        }}
      >
        <input
          placeholder="Profile name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <input
          placeholder="Description (optional)"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <input
          placeholder="Created by"
          value={createdBy}
          onChange={(e) => setCreatedBy(e.target.value)}
        />
        <button type="submit" disabled={createMutation.isPending}>
          Create profile
        </button>
      </form>
      {createMutation.isError && (
        <p className="state-message state-message--error">
          Create failed: {(createMutation.error as Error).message}
        </p>
      )}

      <QueryState
        isLoading={query.isPending}
        isError={query.isError}
        error={query.error}
        isEmpty={query.data?.length === 0}
        emptyMessage="No profiles yet — create one above."
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Version</th>
              <th>Status</th>
              <th>Fields</th>
              <th>Created by</th>
            </tr>
          </thead>
          <tbody>
            {query.data?.map((profile) => (
              <tr key={profile.id}>
                <td>
                  <Link to={`/profiles/${profile.id}`}>{profile.name}</Link>
                </td>
                <td>{profile.version}</td>
                <td>
                  <span className={`status-pill status-pill--${profile.status.toLowerCase()}`}>
                    {profile.status}
                  </span>
                </td>
                <td>{profile.field_configs.length}</td>
                <td>{profile.created_by}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </QueryState>
    </section>
  );
}
