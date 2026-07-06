"""
M9 slice B — Dashboard static checks (offline, no browser, no JS runner).

Verifies that the report page follows the same locale-only Persian invariant
that every other dashboard page obeys (see app/queue/page.tsx as the reference
page: no hardcoded Persian characters, all strings from locales/fa.json).

Path resolution uses Path(__file__).resolve().parents[N] for the repo root —
never hardcoded absolute paths (a previous CI failure came from that).

All tests named test_m9b_<criterion>.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root resolution — never hardcoded.
# Test file lives at: apps/core-api/tests/test_m9b_dashboard_locale.py
#   parents[0] = apps/core-api/tests/
#   parents[1] = apps/core-api/
#   parents[2] = apps/
#   parents[3] = <repo root>
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DASHBOARD = _REPO_ROOT / "apps" / "dashboard"
_PAGE_TSX = _DASHBOARD / "app" / "reports" / "page.tsx"
_FA_JSON = _DASHBOARD / "locales" / "fa.json"

# Persian Unicode block U+0600–U+06FF covers all Arabic/Persian chars used in Farsi.
_PERSIAN_RE = re.compile(r"[؀-ۿ]")

# Required keys inside fa.reports — every key must have a non-empty Persian value.
_REQUIRED_REPORTS_KEYS = {
    "title",
    "month_label",
    "drafts",
    "publish",
    "campaigns",
    "clicks",
    "costs",
    "empty",
}


# ===========================================================================
# 1. File existence
# ===========================================================================


def test_m9b_reports_page_exists():
    """apps/dashboard/app/reports/page.tsx must exist."""
    assert _PAGE_TSX.exists(), (
        f"Dashboard report page not found: {_PAGE_TSX}\n"
        "Implement apps/dashboard/app/reports/page.tsx for M9B."
    )


# ===========================================================================
# 2. No hardcoded Persian in page.tsx (mirrors queue/page.tsx invariant)
# ===========================================================================


def test_m9b_reports_page_no_hardcoded_persian():
    """app/reports/page.tsx must contain NO hardcoded Persian characters.

    All Persian text must come from locales/fa.json (same invariant as
    app/queue/page.tsx, which has zero Persian chars and uses fa.queue.*).
    Regex [؀-ۿ] must NOT match anywhere in the tsx source.
    """
    assert _PAGE_TSX.exists(), (
        f"page.tsx not found (implement first — see test_m9b_reports_page_exists): {_PAGE_TSX}"
    )
    source = _PAGE_TSX.read_text(encoding="utf-8")
    match = _PERSIAN_RE.search(source)
    assert match is None, (
        f"app/reports/page.tsx must not contain hardcoded Persian characters; "
        f"found {match.group()!r} at position {match.start()}. "  # type: ignore[union-attr]
        "Move all Persian text to locales/fa.json under fa.reports.*"
    )


# ===========================================================================
# 3. locales/fa.json has a well-formed "reports" object
# ===========================================================================


def test_m9b_fa_json_has_reports_object():
    """locales/fa.json must have a top-level 'reports' dict with all required keys."""
    assert _FA_JSON.exists(), f"locales/fa.json not found: {_FA_JSON}"
    with _FA_JSON.open(encoding="utf-8") as fh:
        locale = json.load(fh)
    assert "reports" in locale, (
        f"locales/fa.json must have a top-level 'reports' key. "
        f"Found keys: {sorted(locale.keys())}"
    )
    reports = locale["reports"]
    assert isinstance(reports, dict), (
        f"locales/fa.json 'reports' must be a JSON object, got {type(reports)!r}"
    )
    missing = _REQUIRED_REPORTS_KEYS - set(reports.keys())
    assert not missing, (
        f"locales/fa.json 'reports' is missing required keys: {sorted(missing)}\n"
        f"Present keys: {sorted(reports.keys())}"
    )


def test_m9b_fa_json_reports_values_are_persian():
    """Every required value in fa.reports must be a non-empty Persian string.

    Regex [؀-ۿ] MUST match each value — values that are non-Persian or empty
    are invalid because all UI labels must be in Farsi.
    """
    assert _FA_JSON.exists(), f"locales/fa.json not found: {_FA_JSON}"
    with _FA_JSON.open(encoding="utf-8") as fh:
        locale = json.load(fh)
    reports = locale.get("reports", {})
    for key in _REQUIRED_REPORTS_KEYS:
        if key not in reports:
            # Missing keys are caught by test_m9b_fa_json_has_reports_object.
            continue
        value = reports[key]
        assert isinstance(value, str) and value.strip(), (
            f"fa.reports[{key!r}] must be a non-empty string, got {value!r}"
        )
        assert _PERSIAN_RE.search(value), (
            f"fa.reports[{key!r}] must contain at least one Persian character "
            f"(regex [؀-ۿ] must match), got {value!r}"
        )


# ===========================================================================
# 4. page.tsx wires locale namespace and API path
# ===========================================================================


def test_m9b_reports_page_references_fa_reports():
    """app/reports/page.tsx must reference the string 'fa.reports' (locale namespace)."""
    assert _PAGE_TSX.exists(), (
        f"page.tsx not found (implement first — see test_m9b_reports_page_exists): {_PAGE_TSX}"
    )
    source = _PAGE_TSX.read_text(encoding="utf-8")
    assert "fa.reports" in source, (
        "app/reports/page.tsx must reference 'fa.reports' to serve Persian strings "
        "from the locale file. The string 'fa.reports' is absent from page.tsx."
    )


def test_m9b_reports_page_calls_api_monthly():
    """app/reports/page.tsx must contain the string '/reports/monthly' (the API endpoint)."""
    assert _PAGE_TSX.exists(), (
        f"page.tsx not found (implement first — see test_m9b_reports_page_exists): {_PAGE_TSX}"
    )
    source = _PAGE_TSX.read_text(encoding="utf-8")
    assert "/reports/monthly" in source, (
        "app/reports/page.tsx must contain the string '/reports/monthly' — "
        "the page must call the monthly-report API endpoint."
    )
