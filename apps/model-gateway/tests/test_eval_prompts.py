"""Guards for the phase-0 Persian eval assets (scripts/eval/).

The eval decides MODEL_T2 (CLAUDE.md), so its prompt set and runner must
stay intact: exactly 50 well-formed Persian prompts, and the runner must
work end-to-end offline through the gateway's fake provider adapter.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EVAL_DIR = _REPO_ROOT / "scripts" / "eval"
_PROMPTS = _EVAL_DIR / "prompts_fa.jsonl"
_RUNNER = _EVAL_DIR / "run_eval.py"

_ALLOWED_CATEGORIES = {
    "tone_post",
    "hook_cta",
    "rag_grounded",
    "summarize_rewrite",
    "qa_safety",
}

_PERSIAN_CHARS = re.compile(r"[؀-ۿ]")


def _load_items() -> list[dict]:
    assert _PROMPTS.exists(), f"prompt set missing: {_PROMPTS}"
    return [
        json.loads(line)
        for line in _PROMPTS.read_text("utf-8").splitlines()
        if line.strip()
    ]


def test_eval_prompt_set_is_50_wellformed_persian_prompts() -> None:
    items = _load_items()
    assert len(items) == 50, f"the eval is defined as 50 prompts, got {len(items)}"

    ids = [item["id"] for item in items]
    assert len(set(ids)) == 50, "prompt ids must be unique"

    for item in items:
        assert set(item) >= {"id", "category", "prompt", "criteria"}, item["id"]
        assert item["category"] in _ALLOWED_CATEGORIES, item["id"]
        assert len(item["prompt"]) >= 20, item["id"]
        assert _PERSIAN_CHARS.search(item["prompt"]), (
            f"{item['id']}: prompt must contain Persian text"
        )
        assert item["criteria"], item["id"]


def test_eval_prompt_set_covers_all_categories_evenly() -> None:
    items = _load_items()
    counts: dict[str, int] = {}
    for item in items:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    assert counts == {category: 10 for category in _ALLOWED_CATEGORIES}, counts


def test_eval_runner_works_offline_via_fake_adapter(tmp_path: Path) -> None:
    """run_eval.py end-to-end with the gateway's offline fake provider."""
    env = os.environ.copy()
    env.update(
        {
            "EVAL_CANDIDATES": "fake:echo",
            "EVAL_LIMIT": "3",
            "EVAL_RESULTS_DIR": str(tmp_path),
            "EVAL_DELAY_S": "0",  # no pacing needed for the offline adapter
        }
    )
    env.pop("EVAL_JUDGE", None)

    result = subprocess.run(
        [sys.executable, str(_RUNNER)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"runner failed: {result.stderr}"

    rows = [
        json.loads(line)
        for line in (tmp_path / "fake-echo.jsonl").read_text("utf-8").splitlines()
    ]
    assert len(rows) == 3 and all(row["ok"] for row in rows), rows

    summary = json.loads((tmp_path / "summary.json").read_text("utf-8"))
    assert summary[0]["candidate"] == "fake:echo"
    assert summary[0]["ok"] == 3 and summary[0]["errors"] == 0
