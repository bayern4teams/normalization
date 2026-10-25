# Verified Resources — UI/UX for a Minimal Single-User Review and Job Console (Replacing the 18-Page React UI)

**Scope:** for the `normalization` web UI that must cover exactly five jobs (connect a database, start a clone/normalization job, watch progress, review the `AMBIGUOUS` queue as human-in-the-loop, see a run's quality report), for one technical user on localhost or LAN, offline, English only, dark mode, WCAG 2.2 AA, fast. Three technology families (React + library, Python-only UI, open-source internal-tool builders), published tools that solve the same jobs, authoritative UX/accessibility guidance, and speed.

**Verification:** 150 entries below. Every URL was fetched in a final pass and returned HTTP 200 with a page that matches the stated name (GitHub repository pages show an empty title to a script, so repository existence, license, release dates and advisory counts were read with the GitHub API via `gh api`; npm versions and dates with `npm view`). 0 entries are listed as bot-walled: about 15 npm and PyPI package pages returned 403 or a challenge page and were dropped (their data came from `npm view` and the GitHub API instead). About 36 further candidate URLs were dropped (404, 410, timeout, redirect to an unrelated page, or a JavaScript shell with no readable title; examples: Mantine accessibility guide, Ant Design accessibility page, Zingg interactive-labeler page, the old GOV.UK task-list-pages URL). Two entries carry a caveat in their text (Google Cloud Dataprep blog: title confirmed by search; Zingg: page body not readable). Release numbers and dates are as of 2026-10-25. Counts of releases, issues and advisories are GitHub API counts for the 12 months before that date. Anything not checked is stated as "not checked". The effort ratings in the table are my judgement, not measurements.

**Current UI (measured from the repository, not from entries):** `ui/src/pages` has 18 page files with 2,426 lines in total; dependencies are only React 19, TanStack Query, react-router and Vite, with no component library; `normapi` already has routes for connections, clone jobs (plan, start, quality, errors, lineage), `/adjudication/queue` and `/quality`.

---
## 1. React component libraries, data grids and admin frameworks (27)

1. Mantine — https://mantine.dev/ — MIT, v9.7.3 (2026-10-17); AppShell, forms, Progress, Combobox, built-in dark mode; no data grid in core.
2. Mantine repository — https://github.com/mantinedev/mantine — 39 releases in the last 12 months, 41 open issues, 1 published security advisory (medium) in 12 months; health signal for the 'React + library' family.
3. Are Mantine components accessible? (official FAQ) — https://help.mantine.dev/q/are-mantine-components-accessible — Claims WAI-ARIA roles, axe checks via jest-axe, manual VoiceOver testing; no WCAG conformance level is claimed.
4. Mantine use-hotkeys — https://mantine.dev/hooks/use-hotkeys/ — Keyboard-shortcut hook for a review queue; single-key shortcuts must satisfy WCAG 2.1.4 (see the Character Key Shortcuts entry).
5. mantine-datatable — https://github.com/icflorescu/mantine-datatable — Third-party table for Mantine; MIT, npm 9.4.0 (2026-07-15, via npm registry); no GitHub releases found; accessibility not checked.
6. shadcn/ui — https://ui.shadcn.com/ — MIT, CLI v4.22.1 (2026-10-18); copies component source into your repo (no runtime dependency on the kit); 75 releases in 12 months, 1,775 open issues.
7. shadcn/ui Data Table — https://ui.shadcn.com/docs/components/data-table — Documented data-table recipe; the table logic is still TanStack Table that you wire yourself.
8. Radix Primitives accessibility — https://www.radix-ui.com/primitives/docs/overview/accessibility — Accessibility baseline of the primitives used under many shadcn components; @radix-ui/react-dialog 1.3.1 (2026-10-14, npm).
9. Base UI — https://base-ui.com/ — Unstyled accessible components; @base-ui/react 1.9.0 (2026-10-09, npm); shadcn docs now also use base-ui paths.
10. Ant Design — https://ant.design/ — MIT, antd 6.6.7 (2026-10-20); 45 releases in 12 months, 1,105 open issues; large built-in set (Table, Form, Progress, Steps).
11. Chakra UI — https://www.chakra-ui.com/ — MIT, @chakra-ui/react 3.37.0 (2026-08-28); 48 releases in 12 months, 19 open issues.
12. React Aria — https://react-aria.adobe.com/ — Apache-2.0, react-aria-components 1.22.1 (2026-10-09); unstyled hooks and components focused on accessibility; you supply all styling.
13. React Aria quality and accessibility — https://react-aria.adobe.com/quality#accessibility — Claims screen-reader testing (VoiceOver, JAWS, NVDA, TalkBack) and keyboard support; does not claim a WCAG level.
14. React Aria Table — https://react-aria.adobe.com/Table — Accessible table with selection and keyboard navigation; useful base for the review queue.
15. Material UI — https://mui.com/material-ui/ — MIT, v9.5.0 (2026-10-09); large component set with theming.
16. MUI X Data Grid — https://mui.com/x/react-data-grid/ — Full data grid; GitHub license field for mui-x is empty, so which features are MIT and which are Pro is not verified.
17. Tremor repository — https://github.com/tremorlabs/tremor — Apache-2.0, last push 2025-10-10, 0 releases in 12 months; npm @tremor/react 3.18.7 last published 2025-01-13: stale.
18. react-admin — https://marmelab.com/react-admin/ — MIT, v5.15.5 (2026-10-19); 22 releases in 12 months; CRUD-oriented admin framework.
19. react-admin Admin component docs (disableTelemetry) — https://github.com/marmelab/react-admin/blob/master/docs/Admin.md — In production an anonymous request with the admin domain goes to react-admin-telemetry.marmelab.com on mount unless disableTelemetry is set.
20. react-admin supported data providers — https://marmelab.com/react-admin/DataProviderList.html — Lists data-provider adapters; a custom provider is needed for the normapi routes.
21. Refine — https://refine.dev/ — MIT, @refinedev/core 5.0.12 (npm 2026-04-20); last GitHub release 2026-04-02, so no release in about 6.5 months at 2026-10-25.
22. Refine telemetry guide — https://refine.dev/core/docs/further-readings/telemetry/ — Request on app load (providers, version, resource count, IP); opt out with the disableTelemetry option, CLI with REFINE_NO_TELEMETRY.
23. TanStack Table — https://tanstack.com/table/latest — Headless table logic, @tanstack/react-table 9.3.1 (2026-10-12); you build the markup (and its accessibility).
24. TanStack Virtual — https://tanstack.com/virtual/latest — Row virtualization for long lists (distinct-value queues).
25. TanStack Query — https://tanstack.com/query/latest — Already used by the current UI; 5.104.5 (2026-10-19, npm).
26. AG Grid React Data Grid — https://www.ag-grid.com/react-data-grid/ — ag-grid-community 36.2.0 (2026-09-16, MIT per npm); heavy but very fast grid; enterprise features are paid.
27. Fontsource — https://fontsource.org/ — Self-host fonts via npm, required if any kit defaults to Google Fonts and the UI must work offline.

## 2. Python-only UI frameworks (32)

28. Streamlit — https://streamlit.io/ — Apache-2.0, 1.66.1 (2026-10-21); 23 releases in 12 months, 1,189 open issues, 5 published advisories (1 in 12 months, medium).
29. Run your Streamlit app — https://docs.streamlit.io/develop/concepts/architecture/run-your-app — Official description of the rerun-the-script model (the speed question for a review queue).
30. Streamlit config.toml reference — https://docs.streamlit.io/develop/api-reference/configuration/config.toml — Shows gatherUsageStats with 'Default: true'; must be set to false for no telemetry.
31. Streamlit fragments — https://docs.streamlit.io/develop/concepts/architecture/fragments — Official way to limit a rerun to one block of the page.
32. Streamlit st.progress — https://docs.streamlit.io/develop/api-reference/status/st.progress — Progress bar element for the job-watch screen.
33. Streamlit st.dataframe — https://docs.streamlit.io/develop/api-reference/data/st.dataframe — Interactive table; per search results it uses glide-data-grid (a canvas grid); screen-reader behaviour not verified.
34. Streamlit user authentication — https://docs.streamlit.io/develop/concepts/connections/authentication — Official login page; whether a simple local login works without an external identity provider was not checked.
35. Streamlit forum: 508 compliance — https://discuss.streamlit.io/t/508-compliance-for-streamlit/13579 — Only accessibility statement found: 508 accessibility was 'added to the roadmap' without a timeline (old thread).
36. NiceGUI — https://nicegui.io/ — MIT, v3.18.0 (2026-10-07); event-driven Python UI on FastAPI/Quasar/Vue; 24 releases in 12 months, 57 open issues.
37. NiceGUI repository — https://github.com/zauberzeug/nicegui — 21 published advisories, 18 in the last 12 months (4 high, 14 medium); code search for 'telemetry' and 'posthog' found 0 hits.
38. NiceGUI ui.aggrid — https://nicegui.io/documentation/aggrid — AG Grid wrapper; a source docstring mentions a jsDelivr URL only as an override example (default offline behaviour not fully verified).
39. NiceGUI ui.keyboard — https://nicegui.io/documentation/keyboard — Global key handler for keyboard-first review.
40. NiceGUI ui.timer — https://nicegui.io/documentation/timer — Server-side timer for polling job progress.
41. NiceGUI storage — https://nicegui.io/documentation/storage — Per-user and general storage; basis for a simple login.
42. NiceGUI FastAPI example — https://github.com/zauberzeug/nicegui/tree/main/examples/fastapi — Official example of running NiceGUI next to a FastAPI app in one process.
43. Reflex — https://reflex.dev/ — Apache-2.0, v0.10.0 (2026-10-08); Python compiled to a React front end plus Python backend; 356 open issues, 2 advisories total.
44. Reflex telemetry — https://reflex.dev/docs/api-reference/telemetry/ — Anonymous usage stats; opt out with telemetry_enabled=False in rxconfig.py or REFLEX_TELEMETRY_ENABLED=false (the only way outside an app directory).
45. Reflex installation — https://reflex.dev/docs/getting-started/installation/ — Lists Python 3.11+ and uv; does not say whether init downloads anything (offline install not verified).
46. Reflex: wrapping React — https://reflex.dev/docs/wrapping-react/overview/ — Escape hatch to use any React component, which brings React back into the stack.
47. Panel — https://panel.holoviz.org/ — BSD-3-Clause, v1.10.0 (2026-10-23); 14 releases in 12 months, 875 open issues, 0 advisories; geared to data apps.
48. Panel Tabulator — https://panel.holoviz.org/en/docs/latest/reference/widgets/Tabulator.html — Rich table widget (Tabulator-based).
49. Panel in FastAPI — https://panel.holoviz.org/en/docs/latest/how_to/integrations/FastAPI.html — Official way to run Panel apps inside FastAPI.
50. Dash — https://dash.plotly.com/ — MIT, v4.4.1 (2026-07-21); 21 releases in 12 months, 433 open issues, 0 advisories; callback model.
51. Dash forum: telemetry in Dash source (answered: no) — https://community.plotly.com/t/is-there-telemetry-data-in-dash-source-code-answered-no/5923 — Old community answer: no telemetry; not an official policy statement. Dash source shows serve_locally defaulting to True.
52. dash-mantine-components — https://www.dash-mantine-components.com/ — Mantine components for Dash; gives a better look than default Dash.
53. Dash background callbacks — https://dash.plotly.com/background-callbacks — Long-running job support (needs a cache/queue backend; details not read).
54. Gradio — https://www.gradio.app/ — Apache-2.0, gradio@6.30.0 (2026-10-08); built for model demos; 29 advisories (4 in 12 months).
55. Gradio environment variables — https://www.gradio.app/guides/environment-variables — GRADIO_ANALYTICS_ENABLED has default 'True'.
56. Gradio theming guide — https://www.gradio.app/guides/theming-guide — Default theme font is GoogleFont (IBM Plex Sans), loaded from Google Fonts, which breaks offline unless a system font is set.
57. htmx — https://htmx.org/ — Extra option (not requested): server-rendered HTML with FastAPI; v4.0.0 (2026-08-28); no JS build step; SSE extension available.
58. htmx SSE extension — https://htmx.org/extensions/sse/ — Server-sent events for job progress without a front-end framework.
59. Pico CSS — https://picocss.com/ — Classless semantic CSS with dark mode; small, offline-friendly (accessibility claims not checked).

## 3. Open-source internal-tool builders (8)

60. Appsmith — https://www.appsmith.com/ — Apache-2.0 (community edition), v2.5.1 (2026-10-21); 4,513 open issues; 44 advisories, 41 in 12 months (6 critical, 20 high).
61. Appsmith telemetry docs — https://docs.appsmith.com/product/telemetry — Telemetry on unless APPSMITH_DISABLE_TELEMETRY=true; a keep-alive ping every 2 hours and a setup ping are sent even when telemetry is off.
62. ToolJet — https://www.tooljet.com/ — AGPL-3.0, v3.20.249-lts (2026-10-22); 905 open issues; 13 advisories in 12 months (1 critical).
63. ToolJet tracking docs — https://docs.tooljet.com/docs/3.0.0-LTS/tracking/ — 24-hour update check (CHECK_FOR_UPDATES=0 disables) and client usage tracking (ENABLE_TRACKING=0); default of tracking not stated.
64. ToolJet LICENSE — https://github.com/ToolJet/ToolJet/blob/develop/LICENSE — LICENSE file is GNU AGPL v3 (copyleft; ask the owner before use per project rule F7).
65. Budibase — https://budibase.com/ — v3.50.0 (2026-10-19); 255 open issues; 91 advisories, 89 in 12 months (23 critical, 52 high).
66. Budibase analytics docs — https://docs.budibase.com/docs/analytics — Events go through PostHog; opt-out is a portal setting (Organisation page); no environment variable is documented on this page.
67. Budibase LICENSE — https://github.com/Budibase/budibase/blob/master/LICENSE — File says per-package licenses and 'GPLv3 licensed overall' (copyleft).

## 4. Reference tools: human review queues and clerical review (17)

68. OpenRefine — https://github.com/OpenRefine/OpenRefine — BSD-3-Clause, 3.10.1 (2026-03-04); local-first desktop-in-browser tool, the closest UX ancestor of 'review distinct values'.
69. OpenRefine: cell editing and Cluster and edit — https://openrefine.org/docs/manual/cellediting — Per-cluster list of variants with a chosen value, re-cluster after merge, histograms; the pattern for 'one decision, many rows'.
70. OpenRefine: facets — https://openrefine.org/docs/manual/facets — Facets list distinct values with counts and filter rows; model for a distinct-value queue.
71. Argilla — https://github.com/argilla-io/argilla — Apache-2.0; last non-prerelease on GitHub v2.8.0 (2025-03-11), repo pushed 2026-10-19; review UI reference.
72. Argilla: annotate datasets — https://docs.argilla.io/latest/how_to_guides/annotate/ — Pending/Draft/Submitted/Discarded queues, number-key and Enter/Backspace shortcuts, focus view (one record, auto-advance) versus bulk view.
73. Prodigy — https://prodi.gy/ — Commercial, scriptable annotation tool; one decision at a time.
74. Prodigy web application — https://prodi.gy/docs/api-web-app — Default keys: a accept, x reject, space ignore, backspace undo.
75. Prodigy review recipe — https://prodi.gy/docs/review — Shows conflicting decisions side by side; auto-accept of agreement leaves only disputed items.
76. Potato annotation tool — https://github.com/davidjurgens/potato — GPL-3.0 (copyleft), v2.12.1 (2026-10-24); lightweight self-hosted annotator.
77. dedupe — https://github.com/dedupeio/dedupe — MIT; last push 2025-07-29; active learning with human yes/no pair labels.
78. Splink — https://github.com/moj-analytical-services/splink — MIT, v5.0.0 (2026-09-18); probabilistic linkage with review dashboards.
79. Splink discussion: mark what has been reviewed — https://github.com/moj-analytical-services/splink/discussions/1346 — Users asked for 'reviewed' markers in the comparison viewer; maintainers pointed to a clerical-labelling tool.
80. Splink evaluation overview — https://moj-analytical-services.github.io/splink/topic_guides/evaluation/overview.html — How linkage output is evaluated, including manual review.
81. Zingg — https://github.com/zinggAI/zingg — AGPL-3.0 (copyleft), v0.7.0 (2026-08-10); entity resolution with an interactive labeler (its docs page could not be read: GitBook shell only).
82. Dataprep by Trifacta: end of life and deprecated features — https://help.alteryx.com/dataprep/en/release-notes/end-of-life-and-deprecated-features.html — Alteryx now documents Dataprep; no dated Google or Alteryx shutdown notice was found.
83. Cloud Dataprep by Trifacta generally available (Google Cloud Blog) — https://cloud.google.com/blog/products/data-analytics/cloud-dataprep-by-trifacta-now-generally-available — Title confirmed via search; page body only shows a generic title when fetched by script.
84. Wrangler: interactive visual specification of data transformation scripts — https://idl.uw.edu/papers/wrangler — CHI 2011; suggests transforms and previews effects before commit; the Trifacta lineage.

## 5. Reference tools: data quality reports (4)

85. Great Expectations — https://github.com/fivetran/great_expectations — Apache-2.0, 1.24.1 (2026-10-22); repository now under fivetran (old great-expectations path redirects).
86. Great Expectations: configure Data Docs — https://docs.greatexpectations.io/docs/core/configure_project_settings/configure_data_docs/ — Data Docs are static web pages built from results, stored on the filesystem; a static report model that works offline.
87. Soda Core — https://github.com/sodadata/soda-core — v4.28.0 (2026-10-20); GitHub license field NOASSERTION (not verified which); check-based quality.
88. ydata-profiling (now fg-data-profiling) — https://github.com/Data-Centric-AI-Community/fg-data-profiling — MIT, 4.20.0 (2026-09-11); repo moved from ydataai; one-line HTML profile report.

## 6. Reference tools: database connection setup (5)

89. DBeaver — https://github.com/dbeaver/dbeaver — Apache-2.0, 26.2.3 (2026-10-18).
90. DBeaver: create connection — https://dbeaver.com/docs/dbeaver/Create-Connection/ — Driver pick, Main tab (host, port, database, credentials), Test Connection, Finish.
91. Metabase: adding and managing databases — https://www.metabase.com/docs/latest/databases/connecting — Short add-database flow; per-database field pages; does not recommend a read-only user on this page.
92. Airbyte: add and manage sources — https://docs.airbyte.com/platform/using-airbyte/getting-started/add-a-source — Source form followed by a check step before saving.
93. Airbyte: connections and streams — https://docs.airbyte.com/platform/using-airbyte/getting-started/set-up-a-connection — Stream (table) and sync-mode selection; the 'choose tables' step of job 2.

## 7. Reference tools: job progress views (8)

94. Airflow UI overview — https://airflow.apache.org/docs/apache-airflow/stable/ui.html — Grid (task by run, colour by state), graph, task-instance list, logs tab.
95. Dagster webserver and UI — https://dagster.io/docs/guides/operate/webserver — Runs page filterable by status, run detail with Gantt, structured and raw logs, re-execute.
96. Prefect flows — https://docs.prefect.io/v3/concepts/flows — Flow-run states and the run view.
97. MDN: server-sent events — https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events — One-way push from server, a fit for job progress.
98. FastAPI server-sent events — https://fastapi.tiangolo.com/tutorial/server-sent-events/ — Built-in SSE support in the backend framework.
99. TanStack Query useQuery reference — https://tanstack.com/query/latest/docs/framework/react/reference/functions/useQuery — Polling via refetchInterval for the job status endpoint.
100. MDN: progress element — https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/progress — Native, accessible progress bar; no library needed.
101. MDN: ARIA status role — https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Roles/status_role — Announce progress/state changes to screen readers (matches WCAG 4.1.3).

## 8. UX guidance: Nielsen Norman Group (10)

102. 10 Usability Heuristics — https://www.nngroup.com/articles/ten-usability-heuristics/ — The baseline checklist (visibility of status, error prevention, minimalist design).
103. Response Time Limits — https://www.nngroup.com/articles/response-times-3-important-limits/ — 0.1 s / 1 s / 10 s limits as the speed budget for the UI.
104. Progress Indicators Make a Slow System Less Insufferable — https://www.nngroup.com/articles/progress-indicators/ — Spinner for 2-9 s, percent-done for 10 s and longer, 'item 3 of 50' for batch work.
105. Error-Message Guidelines — https://www.nngroup.com/articles/error-message-guidelines/ — Wording of connection and job errors.
106. Data Tables: Four Major User Tasks — https://www.nngroup.com/articles/data-tables/ — Side panel (nonmodal) for single-row edit; batch actions via checkboxes; sticky identifier column.
107. Wizards: Definition and Design Recommendations — https://www.nngroup.com/articles/wizards/ — When a stepwise flow beats one big form (job creation).
108. Confirmation Dialogs Can Prevent User Errors — https://www.nngroup.com/articles/confirmation-dialog/ — When a confirmation is worth its friction (start of a costly job).
109. 8 Design Guidelines for Complex Applications — https://www.nngroup.com/articles/complex-application-design/ — Guidance for expert, task-heavy tools.
110. Dark Mode vs. Light Mode — https://www.nngroup.com/articles/dark-mode/ — Evidence and trade-offs for the dark-mode requirement.
111. User Control and Freedom (Heuristic 3) — https://www.nngroup.com/articles/user-control-and-freedom/ — Undo of a review decision.

## 9. UX guidance: GOV.UK Design System and other design systems (7)

112. GOV.UK Task list — https://design-system.service.gov.uk/components/task-list/ — Use when users need to pick their own order; not for fixed-order services or for showing answers; short status labels with colour.
113. GOV.UK Complete multiple tasks — https://design-system.service.gov.uk/patterns/complete-multiple-tasks/ — The renamed task-list pattern (the old pattern URL returns 410).
114. GOV.UK Check answers — https://design-system.service.gov.uk/patterns/check-answers/ — Review screen before commit: the model for 'review job plan, then Start'.
115. GOV.UK Recover from validation errors — https://design-system.service.gov.uk/patterns/validation/ — Error pattern: summary at top plus message at the field.
116. GOV.UK Error summary — https://design-system.service.gov.uk/components/error-summary/ — Accessible error list that moves focus.
117. GOV.UK Design System accessibility — https://design-system.service.gov.uk/accessibility/ — How the system tests components against WCAG.
118. Carbon data table guidelines — https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines — Table density, selection and batch-action patterns.

## 10. Accessibility: WCAG 2.2, ARIA Authoring Practices, testing (12)

119. WCAG 2.2 (W3C Recommendation) — https://www.w3.org/TR/WCAG22/ — The normative text for the AA target.
120. SC 2.5.8 Target Size (Minimum) — https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html — 24 by 24 CSS px targets: dense decision buttons must respect it.
121. SC 3.3.8 Accessible Authentication (Minimum) — https://www.w3.org/WAI/WCAG22/Understanding/accessible-authentication-minimum.html — Login must allow paste/password managers.
122. SC 4.1.3 Status Messages — https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html — Progress and 'saved' messages must be announced.
123. SC 1.4.3 Contrast (Minimum) — https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html — 4.5:1 text contrast, to be met in both themes.
124. SC 2.1.4 Character Key Shortcuts — https://www.w3.org/WAI/WCAG22/Understanding/character-key-shortcuts.html — Single-key review shortcuts need turn-off/remap or must be active only on focus.
125. ARIA Authoring Practices Guide — https://www.w3.org/WAI/ARIA/apg/ — Keyboard models for widgets built by hand.
126. APG Grid pattern — https://www.w3.org/WAI/ARIA/apg/patterns/grid/ — Keyboard model for interactive tables; read before building an editable grid.
127. axe-core — https://github.com/dequelabs/axe-core — Automated checker, usable in the existing Playwright e2e setup.
128. axe-core Playwright package — https://github.com/dequelabs/axe-core-npm/blob/develop/packages/playwright/README.md — Runs axe inside Playwright tests.
129. Playwright accessibility testing — https://playwright.dev/docs/accessibility-testing — Official guide; notes that automated checks catch only part of the issues.
130. Lighthouse overview — https://developer.chrome.com/docs/lighthouse/overview — Local audit of performance and accessibility (no cloud).

## 11. Research papers on human-in-the-loop review and cleaning (7)

131. Bansal et al.: Does the Whole Exceed its Parts? (CHI 2021) — https://arxiv.org/abs/2006.14779 — Explanations raised the chance people accepted AI advice whether right or wrong: argues against pre-selecting a reading.
132. Bias in the Loop: How Humans Evaluate AI-Generated Suggestions — https://arxiv.org/abs/2509.08514 — Randomized study (2,784 participants): people corrected AI suggestions less when correction took more effort.
133. Beck: Improving annotation quality (LMU dissertation, 2025) — https://edoc.ub.uni-muenchen.de/36241/ — Covers annotator bias on pre-annotations; claims taken from a search summary, not read in full.
134. Raha: a configuration-free error detection system (SIGMOD 2019) — https://dspace.mit.edu/entities/publication/f19685bd-d937-4287-b6dc-0563809e1987 — Selects representative values for user labels; reports strong results with at most 20 labeled tuples per dataset.
135. Semi-supervised data cleaning with Raha and Baran (CIDR 2021) — https://vldb.org/cidrdb/2021/semi-supervised-data-cleaning-with-raha-and-baran.html — Label a few values, learn the rest: supports reviewing distinct values, not rows.
136. CrowdER: crowdsourcing entity resolution — https://arxiv.org/abs/1208.1927 — Machine filter first, human only for the uncertain candidates.
137. Human-in-the-Loop Machine Learning, ch. 11: Interfaces for data annotation — https://livebook.manning.com/book/human-in-the-loop-machine-learning/chapter-11 — Practitioner chapter incl. keyboard shortcuts and input devices (not a controlled study).

## 12. Speed, integration with FastAPI, security (13)

138. React lazy — https://react.dev/reference/react/lazy — Route-level code splitting.
139. web.dev: Interaction to Next Paint — https://web.dev/articles/inp — The metric for sluggish interactions.
140. web.dev: virtualize large lists — https://web.dev/articles/virtualize-long-lists-react-window — Why render only visible rows.
141. TkDodo: Practical React Query — https://tkdodo.eu/blog/practical-react-query — Caching/refetch settings that avoid slow, chatty screens.
142. Use The Index, Luke: keyset pagination — https://use-the-index-luke.com/no-offset — Server paging that stays fast on large result sets.
143. FastAPI — https://fastapi.tiangolo.com/ — Backend framework already in use; generates OpenAPI.
144. FastAPI static files — https://fastapi.tiangolo.com/tutorial/static-files/ — Serve a built front end from the same process (one port, no CORS).
145. FastAPI: self-hosting the docs UI assets — https://fastapi.tiangolo.com/how-to/custom-docs-ui-assets/ — Default /docs loads Swagger assets from a CDN; this page shows the offline fix.
146. FastAPI HTTP Basic auth — https://fastapi.tiangolo.com/advanced/security/http-basic-auth/ — Simplest login for a one-user internal tool.
147. openapi-typescript — https://openapi-ts.dev/ — Generates TypeScript types from the FastAPI OpenAPI schema.
148. Orval — https://orval.dev/ — OpenAPI client generator with TanStack Query hooks.
149. OWASP Authentication cheat sheet — https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html — Minimum bar for the optional login.
150. OWASP Content Security Policy cheat sheet — https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html — A strict CSP can also enforce 'no external hosts' as a test of offline use.

---

## Comparison table

Release dates are the latest non-prerelease on GitHub (or npm where stated), 2026-10-25. "Rel/12m" = releases in the last 12 months. "Adv" = published GitHub security advisories (total; in the last 12 months). Effort for the five jobs is my estimate (S small, M medium, L large), not measured; every option needs the review queue built by hand, because none of them ships one. Entry numbers in brackets.

| Candidate | License | Latest release (date) | Health | Offline / telemetry | a11y | Fit for the 5 jobs (effort) | Notes |
|---|---|---|---|---|---|---|---|
| **Family 1: React + library** | | | | | | | |
| Mantine [1] | MIT | 9.7.3 (2026-10-17) | 39 rel/12m; 41 open issues; 1 adv (1 medium) [2] | No code-search hits for telemetry/posthog (storybook only); fonts not checked | FAQ: WAI-ARIA, jest-axe, VoiceOver; no WCAG level [3] | M: forms, progress, shell built in; table and queue custom | Needs TanStack Table or a third-party table [5] |
| shadcn/ui [6] | MIT | CLI 4.22.1 (2026-10-18) | 75 rel/12m; 1,775 open issues; 0 adv | Source is copied into the repo; whether the CLI needs the network only at add time: not checked | Radix/Base UI primitives [8] [9]; no WCAG level | M: tables via TanStack recipe [7], needs Tailwind | You own and maintain the copied code |
| Ant Design [10] | MIT | 6.6.7 (2026-10-20) | 45 rel/12m; 1,105 open issues; 0 adv | Telemetry: not checked | No official statement found | S-M: Table, Form, Progress in the box | Heavy default look; bundle size not measured |
| Chakra UI [11] | MIT | 3.37.0 (2026-08-28) | 48 rel/12m; 19 open issues; 0 adv | Only a storybook hit for "telemetry" | Not checked | M | No table logic |
| React Aria Components [12] | Apache-2.0 | 1.22.1 (2026-10-09, npm) | 17 rel/12m (monorepo); 653 open issues; 0 adv | 0 hits for telemetry/posthog | Tested on VoiceOver, JAWS, NVDA, TalkBack; no WCAG level [13] | M-L: unstyled, all styling is yours; Table helps [14] | Strongest a11y base, most styling work |
| Material UI + MUI X [15] [16] | MIT (MUI); MUI X: GitHub license field empty, split not verified | 9.5.0 (2026-10-09) | Not tabulated | Not checked | Grid has an accessibility page | M | Check which grid features are paid |
| react-admin [18] | MIT | 5.15.5 (2026-10-19) | 22 rel/12m; 67 open issues; 1 adv (0 in 12m) | Telemetry request in production unless `disableTelemetry` [19] | Not checked (docs page returned 404) | M-L: CRUD-resource shaped; queue and progress do not fit well (judgement) | Needs a custom data provider |
| Refine [21] | MIT | core 5.0.12 (GitHub 2026-04-02) | No release for ~6.5 months | Telemetry on, opt-out [22] | Not checked | M-L | Same shape issue as react-admin |
| Tremor [17] | Apache-2.0 | npm 3.18.7 (2025-01-13) | Stale: 0 releases in 12m | Not checked | Not checked | Charts only | Not a fit as a base |
| **Family 2: Python-only UI** | | | | | | | |
| Streamlit [28] | Apache-2.0 | 1.66.1 (2026-10-21) | 23 rel/12m; 1,189 open issues; 5 adv (1 in 12m) | `gatherUsageStats` default true [30] | No statement; only a 508 roadmap thread [35] | S: fastest first draft (judgement); rerun model [29] fights a keyboard-driven queue | Table is a canvas grid [33]: screen-reader support not verified |
| NiceGUI [36] | MIT | 3.18.0 (2026-10-07) | 24 rel/12m; 57 open issues; 21 adv (18 in 12m: 4 high, 14 medium) [37] | No hits for telemetry/posthog; whether all assets are bundled: not fully verified | Not checked (Quasar underneath) | S-M: event handlers, keyboard [39], timer polling [40], FastAPI example [42] | Advisory count is the highest of the "small" options |
| Reflex [43] | Apache-2.0 | 0.10.0 (2026-10-08) | 356 open issues; 2 adv | Telemetry opt-out [44]; offline install not verified [45] | Not checked | M: Python compiled to React | Escape hatch brings React back [46] |
| Panel [47] | BSD-3-Clause | 1.10.0 (2026-10-23) | 14 rel/12m; 875 open issues; 0 adv | Not checked | Not checked | M: data-app oriented; Tabulator [48] | Runs inside FastAPI [49] |
| Dash [50] | MIT | 4.4.1 (2026-07-21) | 21 rel/12m; 433 open issues; 0 adv | Forum answer: no telemetry [51] | Not checked | M: callback model; long jobs need background callbacks [53] | Mantine components available [52] |
| Gradio [54] | Apache-2.0 | 6.30.0 (2026-10-08) | 29 adv (4 in 12m) | Analytics default True [55]; default theme loads Google Fonts [56] | Not checked | S for forms, poor for a queue (judgement) | Built for model demos |
| **Family 3: internal-tool builders** | | | | | | | |
| Appsmith [60] | Apache-2.0 (community) | 2.5.1 (2026-10-21) | 4,513 open issues; 44 adv (41 in 12m; 6 critical) | Pings sent even with telemetry off [61] | Not checked | M: visual editor; keyboard queue unlikely | UI lives in its database, not in the repo (inference) |
| ToolJet [62] | AGPL-3.0 | 3.20.249-lts (2026-10-22) | 905 open issues; 13 adv (1 critical) | Update check + tracking switches [63] | Not checked | M | Copyleft: ask before use (64) |
| Budibase [65] | GPLv3 overall | 3.50.0 (2026-10-19) | 255 open issues; 91 adv (89 in 12m; 23 critical) | PostHog; portal opt-out [66] | Not checked | M | Copyleft; largest advisory count |
| **Extra (not requested)** | | | | | | | |
| FastAPI + server-rendered HTML + htmx [57] | htmx license not checked | htmx 4.0.0 (2026-08-28) | 8 rel/12m | No JS build; SSE extension [58]; Pico CSS [59] | Native HTML semantics (no claim) | S-M: pages are plain forms and tables | Fewest moving parts; keyboard queue needs small JS |


## Findings

- **No option ships a review queue.** Every candidate gives tables, forms and progress bars; the AMBIGUOUS queue (value, candidate readings, decide, undo) is custom code in all three families. Entries 1 10 12 28 36 60.
- **Telemetry is on by default in most candidates that have any, and every one has an off switch except part of Appsmith.** Streamlit 30, Gradio 55, react-admin 19, Refine 22, Reflex 44, ToolJet 63, Budibase 66; Appsmith keeps sending keep-alive and setup pings with telemetry off 61. Code search found no telemetry in NiceGUI 37, React Aria 12 or Mantine 2; Dash has only an old forum answer 51.
- **"Offline" fails in quiet places.** Gradio's default theme loads Google Fonts 56; FastAPI's default `/docs` loads assets from a CDN 145; fonts can be bundled with 27; a strict CSP is a cheap way to prove nothing leaves the host 150. Reflex offline install is not verified 45.
- **The builders have the worst security and licence profile for a tool that holds database credentials.** Advisories: Budibase 91 (23 critical), Appsmith 44 (6 critical), ToolJet 13 65 60 62; ToolJet is AGPL 64 and Budibase GPLv3 67, which project rule F7 says to ask about first. Localhost-only exposure reduces but does not remove the risk.
- **NiceGUI is the Python option with the most recent advisories** (21, of which 18 in 12 months, none critical) 37; they are fixed quickly in the releases (24 in 12 months) but this is a real maintenance signal.
- **No framework claims WCAG 2.2 AA.** The best statements are Mantine's test practice 3 and React Aria's four-screen-reader testing 13; Ant Design and Streamlit have no statement found 35. AA must be shown by the project's own tests: axe in Playwright 128 and manual keyboard checks, knowing automation covers only part 129.
- **The Streamlit rerun model is documented as re-running the script on each interaction** 29, with fragments as the mitigation 31. I found no published measured comparison of Streamlit, Dash and NiceGUI latency; only vendor and blog opinions. A local spike would be the only real evidence.
- **Review-queue UX has a consistent shape across published tools:** a focus view of one record that auto-advances, plus a bulk list 72; single-key accept/reject/undo 74; cluster-and-pick with re-cluster after merge 69; facets that list distinct values with counts 70; showing only disputed items 75. This supports "review distinct values, not rows".
- **Few labels can go a long way:** Raha reports strong detection with at most 20 labeled tuples per dataset 134 135; CrowdER sends only uncertain candidates to people 136. Both support ordering the queue by uncertainty and impact, not by row.
- **Do not pre-select a reading.** Explanations raised acceptance of AI advice whether right or wrong 131, and people corrected suggestions less when correcting cost more effort 132. For an engine that exists to refuse to guess, show candidates neutrally and make "other value" and "keep ambiguous" as cheap as accepting one.
- **Keyboard-first review has an accessibility rule attached.** Single-character shortcuts must be remappable, turn-off-able, or active only on focus 124; undo is a heuristic, not a nicety 111; targets must be at least 24 by 24 px 120.
- **Progress:** spinner for 2-9 s, percent-done from about 10 s, "item 3 of 50" for batch work 104; Airflow, Dagster and Prefect all combine a state-filterable runs list, a run detail and logs 94 95 96. Polling with TanStack Query 99 is the least code; SSE 98 97 is the push option; announce changes to screen readers 122 101.
- **Quality report:** the established offline model is a static HTML report written to disk (Data Docs 86, ydata-profiling 88); tables need headers and captions for AA 126.
- **Few-page navigation and forms:** GOV.UK task list for "pick your own order" and check-answers before a commit 112 114; a wizard only where steps depend on each other 107; connection forms in DBeaver and Metabase end in an explicit Test Connection / Save step 90 91; error summary plus field message 115.
- **Integration cost is similar across React options:** serve the build from FastAPI to get one port and no CORS 144; generate typed clients from OpenAPI 147 148; HTTP Basic is the smallest login 146 and must allow password managers 121. NiceGUI and Panel can run inside FastAPI 42 49.


## Open questions for the owner

1. Is "Python only, no Node build" a hard preference, or is keeping React acceptable? (This decides family 1 versus family 2; the research does not favour either.)
2. Is a login needed at all if the server binds to 127.0.0.1, or is HTTP Basic enough for LAN use?
3. How many distinct ambiguous values does a typical run produce: tens, thousands or hundreds of thousands? (It decides server paging, virtualization and whether a grid is needed.)
4. Should the review screen be keyboard-first with single-key shortcuts (WCAG 2.1.4 needs a remap or off switch), or button-first with optional shortcuts?
5. Should the review screen ever pre-select a reading, or always start neutral? (The cited studies point to neutral.)
6. Is a copyleft tool (AGPL/GPL) acceptable at all? (Project rule F7 requires an explicit yes.)
7. Should the quality report also be a downloadable static HTML file (like Great Expectations Data Docs), or only a live page?
8. Must job progress survive a page reload and show several jobs at once, or one job at a time?
9. Dark mode: follow the operating system only, or also a manual toggle?
10. Scope: confirm that rules, dictionaries, profiles, preview, comparison, collisions, warnings, field detail and settings are out of the new UI.
11. Who verifies WCAG 2.2 AA by hand (screen reader pass), given that automated tools cover only part?

## Could not verify (stated plainly)

- Screen-reader behaviour of Streamlit's `st.dataframe`; accessibility statements for Ant Design, Chakra, react-admin, Panel, Reflex, Dash, NiceGUI, Gradio and the three builders.
- Telemetry beyond a code search for "telemetry"/"posthog" for Mantine, Ant Design, shadcn/ui, Panel, Chakra; ToolJet's tracking default; Budibase's self-host default; Reflex's `telemetry_enabled` default value (the docs say it collects unless disabled).
- Whether NiceGUI, Panel and Reflex fully work with no internet at install and run time; whether the shadcn CLI needs the network only when adding components.
- Any measured speed comparison between frameworks (none found); bundle sizes (no package was installed).
- Licenses reported as NOASSERTION by GitHub (Soda Core, Metabase, Airbyte) and the MUI X community/Pro split.
- Google Cloud Dataprep's current status (no dated shutdown notice found); Zingg's interactive labeler page content.
- Paper claims in entries marked "search summary" were not checked against the full text.
