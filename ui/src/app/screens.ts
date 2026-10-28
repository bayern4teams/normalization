// The five screens (ADR-023). One list drives the navigation; routes.tsx holds the route table.
export const SCREENS = [
  { path: "/connections", label: "Connections" },
  { path: "/new-clone", label: "New clone" },
  { path: "/jobs", label: "Jobs" },
  { path: "/review", label: "Review" },
  { path: "/quality", label: "Quality" },
] as const;
