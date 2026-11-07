// Route table for the five screens (screens.ts). Hash routing, because the API serves ui/dist at
// "/" with no fallback to index.html for deep paths.
import { createHashRouter, Navigate } from "react-router-dom";
import { ConnectionsPage } from "../pages/ConnectionsPage";
import { JobDetailPage } from "../pages/JobDetailPage";
import { JobsPage } from "../pages/JobsPage";
import { NewClonePage } from "../pages/NewClonePage";
import { QualityPage } from "../pages/QualityPage";
import { ReviewPage } from "../pages/ReviewPage";
import { Layout } from "./Layout";
import { NotFound } from "./NotFound";

export const router = createHashRouter([
  {
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/connections" replace /> },
      { path: "connections", element: <ConnectionsPage /> },
      { path: "new-clone", element: <NewClonePage /> },
      { path: "jobs", element: <JobsPage /> },
      { path: "jobs/:jobId", element: <JobDetailPage /> },
      { path: "review", element: <ReviewPage /> },
      { path: "quality", element: <QualityPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);
