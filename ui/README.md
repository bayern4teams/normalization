# UI

React, Mantine and Vite. Five screens: Connections, New clone, Jobs, Review, Quality
([ADR-023](../docs/adr/ADR-023-ui-scope-and-technology.md)). The API serves the build at `/`.

```bash
npm ci && npm run build && npm run lint   # build into dist/
npm run dev                               # dev server, proxies the API
npm run test:e2e                          # Playwright specs, API stubbed with page.route
```
