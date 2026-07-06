"""
M10 acceptance tests — Operational assets (static, offline checks).

All file paths derived from __file__ — no hardcoded absolute paths.

Checks:
  1. scripts/backup.sh   — exists, executable, required strings, no secret literals
  2. scripts/restore-verify.sh — exists, executable, required strings
  3. Both scripts pass `bash -n` (syntax check)
  4. .github/workflows/ci.yml smoke job has backup.sh + restore-verify.sh steps
  5. docs/ops/runbook.md — exists, six Persian section markers, no token-like literals
  6. Makefile — has `backup:` and `kill-drill:` targets

Blueprint §6.4 acceptance:
  - DB restore from encrypted backup tested on a clean environment
  - Deploy script
  - Runbook

All tests named test_m10_<criterion>.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

# Derive repo root from __file__ (test lives at apps/core-api/tests/…):
#   parents[0] = tests/   parents[1] = core-api/   parents[2] = apps/   parents[3] = repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
DOCS_OPS = REPO_ROOT / "docs" / "ops"
MAKEFILE = REPO_ROOT / "Makefile"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


# ===========================================================================
# 1. scripts/backup.sh — exists, executable, content, no hardcoded secrets
# ===========================================================================


def test_m10_backup_sh_exists_and_valid():
    """scripts/backup.sh must exist, be executable, contain required operational
    strings, and contain NO literal secret values.

    Blueprint §6.4: DB encrypted backup.
    Constitution rule 4: env var NAMES only — no secret values in repo.
    """
    path = SCRIPTS / "backup.sh"
    assert path.exists(), f"scripts/backup.sh does not exist at {path}"
    assert os.access(path, os.X_OK), f"scripts/backup.sh is not executable: {path}"
    text = path.read_text()

    required_fragments = (
        "pg_dump",
        "openssl enc",
        "-aes-256",
        "-pbkdf2",
        "BACKUP_PASSPHRASE",
        "set -euo pipefail",
    )
    for fragment in required_fragments:
        assert fragment in text, (
            f"scripts/backup.sh is missing required fragment: {fragment!r}"
        )

    # Rule 4: must not contain any 32+ char hex literal (would be a raw secret value)
    hex_literals = re.findall(r"[0-9a-fA-F]{32,}", text)
    assert not hex_literals, (
        f"scripts/backup.sh appears to contain a literal hex secret "
        f"(32+ hex chars — rule 4 violation): {hex_literals[:2]}"
    )


# ===========================================================================
# 2. scripts/restore-verify.sh — exists, executable, decrypt + verify strings
# ===========================================================================


def test_m10_restore_verify_sh_exists_and_valid():
    """scripts/restore-verify.sh must exist, be executable, and contain the
    strings needed to prove a clean-environment restore (decrypt → restore → verify schema).

    Blueprint §6.4: clean-environment restore proof.
    """
    path = SCRIPTS / "restore-verify.sh"
    assert path.exists(), f"scripts/restore-verify.sh does not exist at {path}"
    assert os.access(path, os.X_OK), f"scripts/restore-verify.sh is not executable: {path}"
    text = path.read_text()

    required_fragments = (
        "openssl enc",
        "-d",  # decrypt flag
        "psql",
        "alembic_version",  # schema-version table proves migrations ran
        "tenants",  # core tenant table proves data integrity
        "set -euo pipefail",
    )
    for fragment in required_fragments:
        assert fragment in text, (
            f"scripts/restore-verify.sh is missing required fragment: {fragment!r}"
        )


# ===========================================================================
# 3. Both scripts pass bash -n (syntax check)
# ===========================================================================


def test_m10_backup_sh_passes_bash_n():
    """scripts/backup.sh passes `bash -n` (no syntax errors)."""
    path = SCRIPTS / "backup.sh"
    assert path.exists(), "scripts/backup.sh missing — bash -n cannot run"
    result = subprocess.run(
        ["bash", "-n", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"bash -n FAILED for scripts/backup.sh:\n{result.stderr}"
    )


def test_m10_restore_verify_sh_passes_bash_n():
    """scripts/restore-verify.sh passes `bash -n` (no syntax errors)."""
    path = SCRIPTS / "restore-verify.sh"
    assert path.exists(), "scripts/restore-verify.sh missing — bash -n cannot run"
    result = subprocess.run(
        ["bash", "-n", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"bash -n FAILED for scripts/restore-verify.sh:\n{result.stderr}"
    )


# ===========================================================================
# 4. .github/workflows/ci.yml smoke job has backup + restore-verify steps
# ===========================================================================


def test_m10_ci_smoke_has_backup_restore_steps():
    """.github/workflows/ci.yml smoke job must include steps that run both
    scripts/backup.sh and scripts/restore-verify.sh.

    Blueprint §6.4: CI is the automated clean-environment restore drill —
    the backup+restore cycle runs on every merge to prove recoverability.
    """
    assert CI_WORKFLOW.exists(), f"ci.yml not found at {CI_WORKFLOW}"
    data = yaml.safe_load(CI_WORKFLOW.read_text())
    smoke_steps = data["jobs"]["smoke"]["steps"]
    # Collect all `run:` text from every step (steps without `run:` return "")
    step_runs = [s.get("run", "") for s in smoke_steps if isinstance(s, dict)]
    joined = "\n---\n".join(r for r in step_runs if r)

    assert any("backup.sh" in r for r in step_runs), (
        "CI smoke job must have a step that runs backup.sh. "
        "Current step run texts:\n" + joined
    )
    assert any("restore-verify.sh" in r for r in step_runs), (
        "CI smoke job must have a step that runs restore-verify.sh. "
        "Current step run texts:\n" + joined
    )


# ===========================================================================
# 5. docs/ops/runbook.md — six Persian sections, no token-like literals
# ===========================================================================


def test_m10_runbook_exists_with_sections_and_no_secrets():
    """docs/ops/runbook.md must exist, contain the six required operational
    section markers (Persian), and contain NO token-like literal values.

    Section markers (blueprint operational runbook requirements):
      کلید قطع    = kill switch
      حالت سکوت   = silence mode
      بکاپ        = backup
      بازیابی     = restore
      چرخش توکن   = token rotation
      قطع تونل    = tunnel outage

    Constitution rule 4: no literal secret values anywhere in the repo.
    Blueprint §6.4 acceptance: runbook.
    """
    path = DOCS_OPS / "runbook.md"
    assert path.exists(), f"docs/ops/runbook.md does not exist at {path}"
    text = path.read_text()

    required_sections = (
        "کلید قطع",
        "حالت سکوت",
        "بکاپ",
        "بازیابی",
        "چرخش توکن",
        "قطع تونل",
    )
    for section in required_sections:
        assert section in text, (
            f"docs/ops/runbook.md is missing required section marker: {section!r}"
        )

    # Rule 4: strip https?:// URLs first (they may be long but are not secrets),
    # then assert no 30+ char token-like literal remains.
    url_stripped = re.sub(r"https?://\S+", "", text)
    token_matches = re.findall(r"[A-Za-z0-9_|]{30,}", url_stripped)
    assert not token_matches, (
        f"docs/ops/runbook.md contains token-like literals (rule 4 — no secrets in repo): "
        f"{token_matches[:3]}"
    )


# ===========================================================================
# 6. Makefile has backup: and kill-drill: targets
# ===========================================================================


def test_m10_makefile_has_backup_and_kill_drill_targets():
    """Makefile must define both `backup:` and `kill-drill:` targets.

    Blueprint §6.4: operational procedures accessible via `make backup`
    and `make kill-drill`.
    """
    assert MAKEFILE.exists(), f"Makefile not found at {MAKEFILE}"
    text = MAKEFILE.read_text()

    target_lines = [
        ln for ln in text.splitlines() if ":" in ln[:40] and not ln.startswith("\t")
    ][:15]
    assert "backup:" in text, (
        f"Makefile is missing 'backup:' target. "
        f"Existing target lines: {target_lines}"
    )
    assert "kill-drill:" in text, (
        f"Makefile is missing 'kill-drill:' target. "
        f"Existing target lines: {target_lines}"
    )
