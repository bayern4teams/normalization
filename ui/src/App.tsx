import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMemo } from "react";
import { HashRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./app/Layout";
import { ModeProvider } from "./app/ModeContext";
import { CloneJobDetailPage } from "./pages/CloneJobDetailPage";
import { CloneJobNewPage } from "./pages/CloneJobNewPage";
import { CollisionsPage } from "./pages/CollisionsPage";
import { ComparisonPage } from "./pages/ComparisonPage";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { DictionariesPage } from "./pages/DictionariesPage";
import { FieldDetailPage } from "./pages/FieldDetailPage";
import { FieldsPage } from "./pages/FieldsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PreviewPage } from "./pages/PreviewPage";
import { ProfileDetailPage } from "./pages/ProfileDetailPage";
import { ProfilesPage } from "./pages/ProfilesPage";
import { QualityPage } from "./pages/QualityPage";
import { RulesPage } from "./pages/RulesPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { WarningsPage } from "./pages/WarningsPage";

export default function App() {
  const queryClient = useMemo(() => new QueryClient(), []);

  return (
    <QueryClientProvider client={queryClient}>
      <ModeProvider>
        <HashRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<OverviewPage />} />
              <Route path="profiles" element={<ProfilesPage />} />
              <Route path="profiles/:profileId" element={<ProfileDetailPage />} />
              <Route path="fields" element={<FieldsPage />} />
              <Route path="fields/:fieldRef" element={<FieldDetailPage />} />
              <Route path="rules" element={<RulesPage />} />
              <Route path="preview" element={<PreviewPage />} />
              <Route path="runs" element={<RunsPage />} />
              <Route path="runs/:runId" element={<RunDetailPage />} />
              <Route path="warnings" element={<WarningsPage />} />
              <Route path="collisions" element={<CollisionsPage />} />
              <Route path="compare" element={<ComparisonPage />} />
              <Route path="dictionaries" element={<DictionariesPage />} />
              <Route path="quality" element={<QualityPage />} />
              <Route path="connections" element={<ConnectionsPage />} />
              <Route path="clone" element={<CloneJobNewPage />} />
              <Route path="clone/:jobId" element={<CloneJobDetailPage />} />
              <Route path="settings" element={<SettingsPage />} />
            </Route>
          </Routes>
        </HashRouter>
      </ModeProvider>
    </QueryClientProvider>
  );
}
