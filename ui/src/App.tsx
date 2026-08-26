import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMemo } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./app/Layout";
import { ModeProvider } from "./app/ModeContext";
import { CollisionsPage } from "./pages/CollisionsPage";
import { ComparisonPage } from "./pages/ComparisonPage";
import { ConnectPage } from "./pages/ConnectPage";
import { DictionariesPage } from "./pages/DictionariesPage";
import { ExploreLandingPage, ExplorePage } from "./pages/ExplorePage";
import { FieldDetailPage } from "./pages/FieldDetailPage";
import { FieldsPage } from "./pages/FieldsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PreviewPage } from "./pages/PreviewPage";
import { ProfileDetailPage } from "./pages/ProfileDetailPage";
import { ProfilesPage } from "./pages/ProfilesPage";
import { QualityPage } from "./pages/QualityPage";
import { ReportPage } from "./pages/ReportPage";
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
              {/* M21: the 3-step Connect / Explore / Report flow is now
                  the primary entry point (decision: the 3-step UI cannot
                  be built before M18, which is done). */}
              <Route index element={<Navigate to="/connect" replace />} />
              <Route path="connect" element={<ConnectPage />} />
              <Route path="explore" element={<ExploreLandingPage />} />
              <Route path="explore/:connectionId" element={<ExplorePage />} />
              <Route path="report/:runId" element={<ReportPage />} />

              {/* Every pre-M21 page stays reachable at its original path
                  — nothing deleted — and is ALSO reachable under
                  /advanced/* per the plan's own routing decision, so
                  either URL shape keeps working. */}
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
              <Route path="settings" element={<SettingsPage />} />
              <Route path="overview" element={<OverviewPage />} />

              <Route path="advanced" element={<Navigate to="/advanced/overview" replace />} />
              <Route path="advanced/overview" element={<OverviewPage />} />
              <Route path="advanced/profiles" element={<ProfilesPage />} />
              <Route path="advanced/profiles/:profileId" element={<ProfileDetailPage />} />
              <Route path="advanced/fields" element={<FieldsPage />} />
              <Route path="advanced/fields/:fieldRef" element={<FieldDetailPage />} />
              <Route path="advanced/rules" element={<RulesPage />} />
              <Route path="advanced/preview" element={<PreviewPage />} />
              <Route path="advanced/runs" element={<RunsPage />} />
              <Route path="advanced/runs/:runId" element={<RunDetailPage />} />
              <Route path="advanced/warnings" element={<WarningsPage />} />
              <Route path="advanced/collisions" element={<CollisionsPage />} />
              <Route path="advanced/compare" element={<ComparisonPage />} />
              <Route path="advanced/dictionaries" element={<DictionariesPage />} />
              <Route path="advanced/quality" element={<QualityPage />} />
              <Route path="advanced/settings" element={<SettingsPage />} />
            </Route>
          </Routes>
        </HashRouter>
      </ModeProvider>
    </QueryClientProvider>
  );
}
