// Source.txt §89 Fields list — derived from real profile field_configs.
// Also hosts §61 automatic field type detection and §62/§84 profile
// auto-suggestion — both real, both suggestion-only (§85: accept/modify/
// reject, never auto-applied).
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { detectType, listFields, suggestProfile } from "../api/client";
import type { ProfileSuggestion, TypeSuggestion } from "../api/types";
import { QueryState } from "../components/QueryState";

export function FieldsPage() {
  const query = useQuery({ queryKey: ["fields"], queryFn: listFields });

  const [fieldName, setFieldName] = useState("mobile");
  const [sampleValuesRaw, setSampleValuesRaw] = useState("");
  const [typeSuggestions, setTypeSuggestions] = useState<TypeSuggestion[] | null>(null);
  const [profileSuggestion, setProfileSuggestion] = useState<ProfileSuggestion | null>(null);

  const detectMutation = useMutation({
    mutationFn: () => {
      const samples = sampleValuesRaw
        .split("\n")
        .map((v) => v.trim())
        .filter((v) => v.length > 0);
      return detectType(fieldName, samples);
    },
    onSuccess: (suggestions) => {
      setTypeSuggestions(suggestions);
      setProfileSuggestion(null);
    },
  });

  const profileMutation = useMutation({
    mutationFn: (suggestion: TypeSuggestion) => {
      const firstSample = sampleValuesRaw.split("\n").map((v) => v.trim()).find((v) => v);
      return suggestProfile(suggestion.semantic_type, firstSample);
    },
    onSuccess: (suggestion) => setProfileSuggestion(suggestion),
  });

  return (
    <section>
      <h1>Fields</h1>

      <h3>Suggest a semantic type (§61) and normalization profile (§62/§84)</h3>
      <p className="hint">
        A suggestion only — nothing here is applied automatically. Detects from the field name,
        confirmed or demoted by real parsing if you paste sample values.
      </p>
      <form
        className="preview-form"
        onSubmit={(e) => {
          e.preventDefault();
          detectMutation.mutate();
        }}
      >
        <div className="preview-form__row">
          <label>
            Field name
            <input value={fieldName} onChange={(e) => setFieldName(e.target.value)} />
          </label>
        </div>
        <label className="preview-form__values">
          Sample values (optional, one per line)
          <textarea
            rows={3}
            value={sampleValuesRaw}
            onChange={(e) => setSampleValuesRaw(e.target.value)}
          />
        </label>
        <button type="submit" disabled={detectMutation.isPending}>
          Detect type
        </button>
      </form>

      {typeSuggestions && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Semantic type</th>
              <th>Confidence</th>
              <th>Reason</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {typeSuggestions.map((s) => (
              <tr key={s.semantic_type}>
                <td>{s.semantic_type}</td>
                <td>{(s.confidence * 100).toFixed(0)}%</td>
                <td>{s.reason}</td>
                <td>
                  <button type="button" onClick={() => profileMutation.mutate(s)}>
                    Suggest profile
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {profileSuggestion && (
        <div className="detail-card">
          <h4>Recommended normalization for {profileSuggestion.semantic_type}</h4>
          <p>{profileSuggestion.recommended_summary}</p>
          <p className="warning-list">⚠ {profileSuggestion.risk}</p>
          {profileSuggestion.real_steps.length > 0 && (
            <>
              <p>Real pipeline steps (from the live registry):</p>
              <ul className="plain-list">
                {profileSuggestion.real_steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      <h3>Configured fields</h3>
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
