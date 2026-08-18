// Source.txt §86-88 — mode descriptions live here; the switch itself is
// in the nav bar (available on every page).
import { useMode } from "../app/ModeContext";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8080";

export function SettingsPage() {
  const { mode } = useMode();

  return (
    <section>
      <h1>Settings</h1>
      <p>
        API base URL: <code>{API_BASE}</code>
      </p>
      <p>
        Current mode: <strong>{mode}</strong> (switch it from the nav bar)
      </p>
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
