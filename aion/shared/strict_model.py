"""StrictModel — Pydantic base for request body schemas.

Use this as the base class for any Pydantic model that parses JSON arriving
from the console (or any other untrusted source). Setting `extra="forbid"`
turns a typo or contract drift into a loud HTTP 422 instead of silently
discarding the unknown field — which was the root cause of the C2 finding
in qa-evidence/console-backend-integration.

Models that represent INTERNAL state (cached results, telemetry events,
contract objects passed between modules) should keep using `BaseModel`
directly — strict validation there would just create churn without
catching real contract bugs from external clients.

Example:
    from aion.shared.strict_model import StrictModel
    from pydantic import Field

    class WidgetConfig(StrictModel):
        name: str
        size: int = Field(default=10, ge=1, le=100)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """BaseModel variant that rejects unknown fields with HTTP 422.

    Inheriting from this is a one-line opt-in to the M2 contract guard.
    """

    model_config = ConfigDict(extra="forbid")
