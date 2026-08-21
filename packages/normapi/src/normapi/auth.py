"""Lightweight API-key auth (M11) — a pragmatic addition from the
approved M9-M12 roadmap, not itself a numbered Source.txt spec section.
Scoped deliberately small: one shared secret, gating only state-
mutating requests, never a user-management/RBAC system — this project
has never specified or built one, and inventing one here would be scope
well beyond "lightweight."

The key itself is read ONCE at app-construction time (`create_app`'s
`api_key` param, defaulting to `NORM_API_KEY`) and stored on
`app.state.api_key` — the same pattern every other optional env-var-
configured feature in this app already follows (`postgres_dsn`,
`sidecar_parquet_root`, `sources_config_path`), rather than re-reading
`os.environ` on every request. `None` (the default — matching every
other optional-integration env var: `NORM_PG_DSN`, `NORM_SIDECAR_*`,
`NORM_SOURCES_CONFIG_PATH`) means auth is fully disabled: every existing
test's plain `TestClient(create_app())` construction is unaffected, and
local/dev usage needs no setup. When set, every POST/PUT/PATCH/DELETE
request must carry `Authorization: Bearer <key>`; every GET stays open
— read access is never gated, since gating it would break the read-only
integration/demo flows this project already relies on (curl smoke
checks, the UI's own read queries) for no real security benefit (nothing
in this API returns data a reader shouldn't already be able to compute
from a normal read-only credential).

Applied once, as a dependency on the whole `APIRouter` in routes.py —
not per-route — so a newly-added mutating route is protected by
construction, not by remembering to decorate it. `secrets.compare_digest`
avoids a timing side-channel on the comparison itself.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from normapi.dependencies import get_api_key

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def enforce_api_key_for_mutations(
    request: Request, expected: Annotated[str | None, Depends(get_api_key)]
) -> None:
    if expected is None or request.method not in _MUTATING_METHODS:
        return
    provided = request.headers.get("Authorization", "")
    if not provided.startswith("Bearer ") or not secrets.compare_digest(
        provided.removeprefix("Bearer "), expected
    ):
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
