"""The M1 scaffold's placeholder profile, used by /preview and
/field-test to exercise the real Dispatcher without requiring a caller to
have already created a profile via POST /normalization/profiles first.

Lives in its own module (not normapi.app) purely to avoid a circular
import between normapi.app (which builds the FastAPI app and dispatcher)
and normapi.routes (which needs this constant).
"""

from __future__ import annotations

from normcore import NormalizationProfile

SCAFFOLD_PROFILE = NormalizationProfile(
    id="scaffold",
    name="M1 scaffold profile",
    version="v0",
    description="Placeholder profile for /preview and /field-test before real profiles exist.",
    created_at="1970-01-01T00:00:00Z",
    updated_at="1970-01-01T00:00:00Z",
    created_by="normapi-scaffold",
)
