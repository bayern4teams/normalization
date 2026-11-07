# ADR-023: UI Scope and Technology — Five Screens, React + Mantine, Served by the API

## Status
Accepted — 2026-10-28. Implements `docs/improvement-report.md` U1 (owner decisions R5-R8, R10,
R18-R23; plan decisions Q4, Q5, Q7, Q14). Built in Phase 4 of round 2.

## Context

The old UI has 18 page files and 13 navigation items, and no page shows the review queue. The
queue and the verdict route exist (ADR-018), so the human decision for every `AMBIGUOUS` value
can be made only by calling the API by hand. The owner judged looks, navigation, page count,
wording and speed to be wrong (R7).

## Decision

**Five screens:** Connections, New clone, Jobs, Review, Quality. Overview, Profiles, Fields,
Rules, Preview, Warnings, Collisions, Dictionaries, Settings and the mode switch go (R19), with
the Playwright specs of those pages (Q14). Their API routes stay.

**Technology (R8, Q7).** React + Mantine (`@mantine/core`, `@mantine/hooks`, exact versions).
`ui/` is replaced in place (Q5); the API client and types carry over where they still fit.

**One port.** The API serves the built UI, so there is no CORS. No CDN, no web fonts, no
telemetry. `/docs` and `/redoc` are switched off, because their Swagger and ReDoc assets come
from a CDN and no allowed dependency (Q7) supplies them; `/openapi.json` stays. Owner decision
2026-11-07: "2. a" (rule `/docs` out, no new dependency).

**Review screen.** One distinct value at a time, ordered by occurrences. One key each for
accept, other value, keep ambiguous and undo, and buttons for the same. No reading is
pre-selected: people accept a shown suggestion more often, right or wrong, so "other value" and
"keep ambiguous" cost the same one key as "accept". Budget: 0.1 s per key press, 1 s per page;
the full list loads once, with no server paging (R22).

**Raw value only in review (R23).** Only the review route returns the raw value and its
candidate readings (tested: `tests/unit/test_u1_review_route.py`).

**English only; no login, no WCAG target, no dark mode (R10).**

## Limits

- **R23 is met only for the review route.** These still carry raw values: the clone-job error
  text (`clone_executor.py`, "e.g. ..."), `disguised_missing[].value` in the job and quality
  responses (D4's confirm step needs the exact values), and `/preview`, `/field-test` and
  `/runs/{id}/values`. Owner decision 2026-11-07: "3. a" (recorded as open, not built).
- **New clone cannot pick tables.** Every table of the origin database is cloned, because the
  clone API has no table filter; the screen picks columns and their semantic types only. Owner
  decision 2026-11-07: "1. a" (recorded as a limit).

- Agents take no screenshots (Q4). Every screen is checked against the running stack by the
  owner (`docs/plans/round2/LOCAL_VERIFY.md`).
- The raw value is at rest in the metadata database already; the review route is the one place
  it leaves, and it relies on ADR-022's local-network-only policy.

## Consequences

`ui/` builds into the API image; `app.py` mounts it. A new route returns the unmasked queue
entry. Pages not in the list above are not rebuilt.
