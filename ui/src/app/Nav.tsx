import { Group } from "@mantine/core";
import { NavLink } from "react-router-dom";
import { SCREENS } from "./screens";

export function Nav() {
  return (
    <Group component="nav" aria-label="Main" gap="lg">
      {SCREENS.map((s) => (
        <NavLink
          key={s.path}
          to={s.path}
          style={({ isActive }) => ({
            color: "inherit",
            fontWeight: isActive ? 700 : 400,
            textDecoration: isActive ? "underline" : "none",
          })}
        >
          {s.label}
        </NavLink>
      ))}
    </Group>
  );
}
