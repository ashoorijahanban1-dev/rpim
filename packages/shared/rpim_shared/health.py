from typing import Literal

from pydantic import BaseModel


class HealthStatus(BaseModel):
    """Health contract every RPIM HTTP service returns from GET /health."""

    status: Literal["ok", "degraded"] = "ok"
    service: str
    leg: Literal["iran", "us"] | None = None
