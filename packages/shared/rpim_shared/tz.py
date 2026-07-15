"""Application timezone — single source of truth (ADR 0032).

The operator mandated Pacific Time system-wide (explicitly confirmed twice,
against the recorded engineering recommendation of UTC storage for a
Tehran-audience product). Every wall-clock read goes through here so the
decision is reversible by flipping ONE env var: RPIM_TIMEZONE.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "America/Los_Angeles"


def app_timezone() -> ZoneInfo:
    return ZoneInfo(os.environ.get("RPIM_TIMEZONE", DEFAULT_TIMEZONE))


def now_app() -> datetime:
    """Timezone-aware 'now' in the application timezone."""
    return datetime.now(app_timezone())


def month_key(stamp: datetime | None) -> str | None:
    """YYYY-MM of a stamp in the app timezone. Aware stamps are converted;
    naive stamps (legacy rows / SQLite tests) are taken at face value."""
    if stamp is None:
        return None
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(app_timezone())
    return stamp.strftime("%Y-%m")
