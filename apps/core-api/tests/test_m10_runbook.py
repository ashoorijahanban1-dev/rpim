"""
M10 acceptance tests — Ops runbook.

Acceptance criteria:
  docs/ops/runbook.md exists and covers the following topics (asserted by
  section heading, case-insensitive):
    - kill switch
    - backup
    - restore
    - deploy
    - silence mode

The check is LENIENT — headings must be present but exact prose is not checked.
A heading is any Markdown ATX (#, ##, ###, …) or setext (underline ===, ---) line
whose content contains the required keyword (case-insensitive).

FAILS TODAY: docs/ops/runbook.md does not exist.

All tests named test_m10_<criterion>.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
_RUNBOOK: Path = _REPO_ROOT / "docs" / "ops" / "runbook.md"

# Required topic keywords — matched case-insensitively against heading text.
_REQUIRED_TOPICS: list[str] = [
    "kill switch",
    "backup",
    "restore",
    "deploy",
    "silence",
]


def _extract_headings(text: str) -> list[str]:
    """Return a list of heading text strings from Markdown content."""
    headings: list[str] = []

    # ATX headings: lines starting with one or more '#' characters.
    atx_pattern = re.compile(r"^#{1,6}\s+(.+)", re.MULTILINE)
    for match in atx_pattern.finditer(text):
        headings.append(match.group(1).strip())

    # Setext headings: a line followed by === or --- underline.
    lines = text.splitlines()
    for i, line in enumerate(lines[:-1]):
        next_line = lines[i + 1]
        stripped = line.strip()
        if stripped and re.match(r"^[=\-]{2,}$", next_line.strip()):
            headings.append(stripped)

    return headings


# ===========================================================================
# 1. Runbook file exists
# ===========================================================================


def test_m10_runbook_file_exists() -> None:
    """docs/ops/runbook.md must exist.

    FAILS today: the file is absent from the repository.
    """
    assert _RUNBOOK.exists(), (
        f"docs/ops/runbook.md must exist at {_RUNBOOK}; "
        f"create the runbook as part of M10 operational safety."
    )


# ===========================================================================
# 2–6. Required section headings (one test per topic)
# ===========================================================================


@pytest.mark.parametrize("topic", _REQUIRED_TOPICS)
def test_m10_runbook_covers_required_topic(topic: str) -> None:
    """docs/ops/runbook.md must contain a heading covering '{topic}' (case-insensitive).

    FAILS today: the file does not exist.
    """
    if not _RUNBOOK.exists():
        pytest.fail(
            f"docs/ops/runbook.md not found at {_RUNBOOK}; "
            f"cannot assert coverage of topic '{topic}'."
        )

    content = _RUNBOOK.read_text(encoding="utf-8")
    headings = _extract_headings(content)

    matching = [h for h in headings if topic.lower() in h.lower()]
    assert matching, (
        f"docs/ops/runbook.md must contain a heading covering '{topic}' "
        f"(case-insensitive); found headings: {headings!r}"
    )


# ===========================================================================
# 7. Runbook is non-empty (prose sanity check)
# ===========================================================================


def test_m10_runbook_is_not_empty() -> None:
    """docs/ops/runbook.md must contain meaningful content (>200 characters).

    Guards against a placeholder file with only headings and no instructions.
    FAILS today: file does not exist.
    """
    if not _RUNBOOK.exists():
        pytest.fail(
            f"docs/ops/runbook.md not found at {_RUNBOOK}."
        )

    content = _RUNBOOK.read_text(encoding="utf-8").strip()
    assert len(content) > 200, (
        f"docs/ops/runbook.md must contain meaningful prose (>200 chars); "
        f"got {len(content)} characters.  Add operational procedures for each section."
    )
