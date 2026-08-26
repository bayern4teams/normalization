// Main navigation — Source.txt §89's original list, now behind
// ModeContext (M21): the 3-step Connect/Explore/Report flow always
// shows; the 11 legacy engine-vocabulary tabs only render when the user
// has switched out of "normal" mode (decision 3 of the M13-M22 program —
// reuses useMode() completely unchanged, no new machinery).
import { NavLink } from "react-router-dom";
import { useMode, type UiMode } from "./ModeContext";

const PRIMARY_NAV_ITEMS: { to: string; label: string }[] = [
  { to: "/connect", label: "Connect" },
  { to: "/explore", label: "Explore" },
  { to: "/advanced/runs", label: "Reports" },
];

const LEGACY_NAV_ITEMS: { to: string; label: string }[] = [
  { to: "/advanced/overview", label: "Overview" },
  { to: "/advanced/profiles", label: "Profiles" },
  { to: "/advanced/fields", label: "Fields" },
  { to: "/advanced/rules", label: "Rules" },
  { to: "/advanced/preview", label: "Preview" },
  { to: "/advanced/runs", label: "Runs" },
  { to: "/advanced/warnings", label: "Warnings" },
  { to: "/advanced/collisions", label: "Collisions" },
  { to: "/advanced/dictionaries", label: "Dictionaries" },
  { to: "/advanced/quality", label: "Quality" },
  { to: "/advanced/settings", label: "Settings" },
];

const MODES: UiMode[] = ["normal", "expert", "admin"];

export function Nav() {
  const { mode, setMode } = useMode();
  const showLegacy = mode !== "normal";

  return (
    <nav className="app-nav">
      <div className="app-nav__brand">Normalization Engine</div>
      <ul className="app-nav__links">
        {PRIMARY_NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink to={item.to} className="app-nav__link">
              {item.label}
            </NavLink>
          </li>
        ))}
        {showLegacy &&
          LEGACY_NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} className="app-nav__link app-nav__link--legacy">
                {item.label}
              </NavLink>
            </li>
          ))}
      </ul>
      <div className="app-nav__mode" role="radiogroup" aria-label="UI mode">
        {MODES.map((m) => (
          <button
            key={m}
            type="button"
            className={`app-nav__mode-btn${mode === m ? " app-nav__mode-btn--active" : ""}`}
            aria-pressed={mode === m}
            onClick={() => setMode(m)}
          >
            {m}
          </button>
        ))}
      </div>
    </nav>
  );
}
