// Source.txt §86-88 — mode descriptions live here; the switch itself is
// in the nav bar (available on every page).
import { useState } from "react";
import { clearApiKey, getApiKey, setApiKey } from "../api/authStore";
import { useMode } from "../app/ModeContext";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8080";

export function SettingsPage() {
  const { mode } = useMode();
  const [apiKeyInput, setApiKeyInput] = useState(getApiKey() ?? "");
  const [saved, setSaved] = useState(false);

  return (
    <section>
      <h1>Settings</h1>
      <p>
        API base URL: <code>{API_BASE}</code>
      </p>
      <p>
        Current mode: <strong>{mode}</strong> (switch it from the nav bar)
      </p>

      <h2>API key (M11)</h2>
      <p className="hint">
        Only needed if this deployment has <code>NORM_API_KEY</code> configured — read/list
        requests always work without one. Stored only in this browser's local storage, sent as{" "}
        <code>Authorization: Bearer &lt;key&gt;</code> on every request.
      </p>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (apiKeyInput.trim()) {
            setApiKey(apiKeyInput.trim());
          } else {
            clearApiKey();
          }
          setSaved(true);
        }}
      >
        <input
          type="password"
          placeholder="API key (leave blank for none)"
          value={apiKeyInput}
          onChange={(e) => {
            setApiKeyInput(e.target.value);
            setSaved(false);
          }}
        />
        <button type="submit">Save</button>
      </form>
      {saved && <p className="state-message state-message--success">Saved.</p>}
      <dl className="kv-list">
        <dt>Normal (§87)</dt>
        <dd>Field, detected type, recommended normalization, preview, warnings, impact, apply.</dd>
        <dt>Expert (§86)</dt>
        <dd>
          Adds: exact pipeline, technical trace, Unicode forms, locale, dictionary/library
          versions, parsing/validation settings, error policy, lossy transformations.
        </dd>
        <dt>Admin (§88)</dt>
        <dd>
          Adds: rule definitions, versioning internals, dependency versions, benchmarks, cache
          statistics, raw error detail, transformation counts.
        </dd>
      </dl>
    </section>
  );
}
