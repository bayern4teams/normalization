// Main navigation — Source.txt §89's exact list.
import { NavLink } from "react-router-dom";
import { useMode, type UiMode } from "./ModeContext";

const NAV_ITEMS: { to: string; label: string }[] = [
  { to: "/", label: "Overview" },
  { to: "/profiles", label: "Profiles" },
  { to: "/fields", label: "Fields" },
  { to: "/rules", label: "Rules" },
  { to: "/preview", label: "Preview" },
  { to: "/runs", label: "Runs" },
  { to: "/warnings", label: "Warnings" },
  { to: "/collisions", label: "Collisions" },
  { to: "/dictionaries", label: "Dictionaries" },
  { to: "/quality", label: "Quality" },
  { to: "/connections", label: "Connections" },
  { to: "/clone", label: "Clone" },
  { to: "/settings", label: "Settings" },
];

const MODES: UiMode[] = ["normal", "expert", "admin"];

export function Nav() {
  const { mode, setMode } = useMode();

  return (
    <nav className="app-nav">
      <div className="app-nav__brand">Normalization Engine</div>
      <ul className="app-nav__links">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink to={item.to} end={item.to === "/"} className="app-nav__link">
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
