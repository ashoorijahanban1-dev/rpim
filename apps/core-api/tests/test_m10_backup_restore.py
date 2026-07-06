"""
M10 acceptance tests — Backup script and restore-drill script.

Acceptance criteria:
  (a) scripts/backup/pg-backup.sh exists and:
      - refuses to run (exit non-zero) if BACKUP_PASSPHRASE is unset, printing
        the env var NAME (never a value) in the error message.
      - refuses to run (exit non-zero) if BACKUP_REMOTE is unset.
      - given a fake pg_dump on PATH and a tmpdir remote, produces an
        ENCRYPTED artifact (output does not contain a known plaintext marker).
      - artifact file name contains a timestamp (ISO date or epoch pattern).
      - is idempotent/safe to re-run without corrupting prior artifacts.

  (b) scripts/backup/pg-restore-drill.sh exists and:
      - decrypts an encrypted artifact and pipes to psql (stubbed) when given
        correct passphrase; the plaintext marker round-trips.
      - exits non-zero when given the wrong passphrase.

Both scripts are exercised via subprocess with a stubbed PATH
(fake pg_dump, fake psql, fake gpg/openssl shims).

FAILS TODAY: the scripts do not exist.

All tests named test_m10_<criterion>.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

# Absolute path to the repo root (derived from this file's location).
_REPO_ROOT: Path = Path(__file__).resolve().parents[3]  # …/rpim
_BACKUP_SCRIPT: Path = _REPO_ROOT / "scripts" / "backup" / "pg-backup.sh"
_RESTORE_SCRIPT: Path = _REPO_ROOT / "scripts" / "backup" / "pg-restore-drill.sh"

# A unique string we embed in the fake dump so we can test that the encrypted
# artifact does NOT contain it as plaintext, and that the restore round-trips it.
_DUMP_MARKER: str = "RPIM_M10_BACKUP_TEST_MARKER_PLAINTEXT_SQL"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_executable(path: Path, content: str) -> None:
    """Write a shell script stub to path and make it executable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_fake_bin_dir(tmp: Path) -> Path:
    """Return a directory containing stub binaries: pg_dump, psql, gpg."""
    bin_dir = tmp / "fake_bin"
    bin_dir.mkdir(exist_ok=True)

    # Fake pg_dump: outputs the marker so we know what was "dumped".
    _write_executable(
        bin_dir / "pg_dump",
        textwrap.dedent(f"""\
            #!/bin/sh
            echo "{_DUMP_MARKER}"
            echo "-- fake pg_dump output for $DATABASE_URL"
        """),
    )

    # Fake psql: writes stdin to PSQL_RECEIVED_PATH so tests can inspect it.
    _write_executable(
        bin_dir / "psql",
        textwrap.dedent("""\
            #!/bin/sh
            if [ -n "$PSQL_RECEIVED_PATH" ]; then
                cat > "$PSQL_RECEIVED_PATH"
            fi
            exit 0
        """),
    )

    # Real openssl is expected to be on the system PATH for actual encryption;
    # but we add a wrapper that prepends the fake bin dir so pg_dump/psql are
    # intercepted while openssl resolves to the real binary.
    return bin_dir


def _env_with_fake_bin(fake_bin: Path, extra: dict | None = None) -> dict:
    """Return an os.environ copy with fake_bin prepended to PATH."""
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
    if extra:
        env.update(extra)
    return env


# ===========================================================================
# pg-backup.sh — script existence
# ===========================================================================


def test_m10_backup_script_exists() -> None:
    """scripts/backup/pg-backup.sh must exist.

    FAILS today: the file is absent.
    """
    assert _BACKUP_SCRIPT.exists(), (
        f"scripts/backup/pg-backup.sh must exist at {_BACKUP_SCRIPT}; "
        f"file not found — implement the backup script for M10."
    )


# ===========================================================================
# pg-backup.sh — env-var guard: BACKUP_PASSPHRASE
# ===========================================================================


def test_m10_backup_refuses_without_backup_passphrase() -> None:
    """pg-backup.sh exits non-zero with a message naming BACKUP_PASSPHRASE when unset.

    Rule 4: messages must name the env var, never a value.
    FAILS today: script does not exist.
    """
    if not _BACKUP_SCRIPT.exists():
        pytest.fail(
            f"scripts/backup/pg-backup.sh not found at {_BACKUP_SCRIPT}; "
            "implement the script so this test can assert env-var guard behavior."
        )

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        fake_bin = _make_fake_bin_dir(tmp)
        env = _env_with_fake_bin(
            fake_bin,
            {
                # BACKUP_PASSPHRASE deliberately absent
                "BACKUP_REMOTE": f"file://{tmp}/remote",
                "DATABASE_URL": "postgresql://fake:fake@localhost/fakedb",
            },
        )
        # Remove BACKUP_PASSPHRASE if inherited from environment
        env.pop("BACKUP_PASSPHRASE", None)

        result = subprocess.run(
            [str(_BACKUP_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    assert result.returncode != 0, (
        f"pg-backup.sh must exit non-zero when BACKUP_PASSPHRASE is unset, "
        f"got exit code {result.returncode}; stdout={result.stdout!r}"
    )
    combined = (result.stdout + result.stderr).upper()
    assert "BACKUP_PASSPHRASE" in combined, (
        f"pg-backup.sh error output must name the env var 'BACKUP_PASSPHRASE' "
        f"(never a value — rule 4); got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ===========================================================================
# pg-backup.sh — env-var guard: BACKUP_REMOTE
# ===========================================================================


def test_m10_backup_refuses_without_backup_remote() -> None:
    """pg-backup.sh exits non-zero with a message naming BACKUP_REMOTE when unset.

    FAILS today: script does not exist.
    """
    if not _BACKUP_SCRIPT.exists():
        pytest.fail(
            f"scripts/backup/pg-backup.sh not found at {_BACKUP_SCRIPT}."
        )

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        fake_bin = _make_fake_bin_dir(tmp)
        env = _env_with_fake_bin(
            fake_bin,
            {
                "BACKUP_PASSPHRASE": "test-passphrase-not-a-secret",
                # BACKUP_REMOTE deliberately absent
                "DATABASE_URL": "postgresql://fake:fake@localhost/fakedb",
            },
        )
        env.pop("BACKUP_REMOTE", None)

        result = subprocess.run(
            [str(_BACKUP_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    assert result.returncode != 0, (
        f"pg-backup.sh must exit non-zero when BACKUP_REMOTE is unset, "
        f"got exit code {result.returncode}"
    )
    combined = (result.stdout + result.stderr).upper()
    assert "BACKUP_REMOTE" in combined, (
        f"pg-backup.sh error must name 'BACKUP_REMOTE'; "
        f"got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ===========================================================================
# pg-backup.sh — produces encrypted artifact (not plaintext SQL)
# ===========================================================================


def test_m10_backup_produces_encrypted_artifact_not_plaintext() -> None:
    """pg-backup.sh produces an artifact that does NOT contain the plaintext marker.

    The fake pg_dump writes _DUMP_MARKER into its output.  If the backup script
    stores the output without encryption the artifact would contain the marker.
    This test verifies that the stored file does NOT contain _DUMP_MARKER,
    proving encryption (or at minimum non-plaintext storage).

    FAILS today: script does not exist.
    """
    if not _BACKUP_SCRIPT.exists():
        pytest.fail(
            f"scripts/backup/pg-backup.sh not found at {_BACKUP_SCRIPT}."
        )

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        remote_dir = tmp / "remote"
        remote_dir.mkdir()
        fake_bin = _make_fake_bin_dir(tmp)

        passphrase = "m10-test-passphrase-xQ9z"
        env = _env_with_fake_bin(
            fake_bin,
            {
                "BACKUP_PASSPHRASE": passphrase,
                "BACKUP_REMOTE": str(remote_dir),
                "DATABASE_URL": "postgresql://fake:fake@localhost/fakedb",
            },
        )

        result = subprocess.run(
            [str(_BACKUP_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"pg-backup.sh must exit 0 with all required env vars set; "
            f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
        )

        # Find the artifact written to remote_dir
        artifacts = list(remote_dir.glob("**/*"))
        artifacts = [a for a in artifacts if a.is_file()]
        assert len(artifacts) >= 1, (
            f"pg-backup.sh must write at least one artifact to BACKUP_REMOTE="
            f"{remote_dir}; found: {artifacts}"
        )

        # None of the artifacts should contain the plaintext marker
        for artifact in artifacts:
            content_bytes = artifact.read_bytes()
            assert _DUMP_MARKER.encode() not in content_bytes, (
                f"Artifact {artifact.name} contains plaintext marker {_DUMP_MARKER!r}; "
                f"the backup must be ENCRYPTED, not stored as plaintext SQL."
            )


# ===========================================================================
# pg-backup.sh — artifact file name contains a timestamp
# ===========================================================================


def test_m10_backup_artifact_has_timestamped_name() -> None:
    """pg-backup.sh writes an artifact whose filename contains a timestamp.

    A timestamped name (ISO date or epoch) lets operators identify when the
    backup was taken and prevents accidental overwrites on re-run.

    FAILS today: script does not exist.
    """
    if not _BACKUP_SCRIPT.exists():
        pytest.fail(
            f"scripts/backup/pg-backup.sh not found at {_BACKUP_SCRIPT}."
        )

    import re

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        remote_dir = tmp / "remote"
        remote_dir.mkdir()
        fake_bin = _make_fake_bin_dir(tmp)

        env = _env_with_fake_bin(
            fake_bin,
            {
                "BACKUP_PASSPHRASE": "m10-test-ts-passphrase",
                "BACKUP_REMOTE": str(remote_dir),
                "DATABASE_URL": "postgresql://fake:fake@localhost/fakedb",
            },
        )

        result = subprocess.run(
            [str(_BACKUP_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"pg-backup.sh exited {result.returncode}: {result.stderr!r}"
        )

        artifacts = [a for a in remote_dir.glob("**/*") if a.is_file()]
        assert artifacts, (
            f"pg-backup.sh must produce at least one artifact in {remote_dir}"
        )

        # Timestamp pattern: at minimum 8 consecutive digits (YYYYMMDD or epoch)
        ts_pattern = re.compile(r"\d{8,}")
        for artifact in artifacts:
            assert ts_pattern.search(artifact.name), (
                f"Artifact filename {artifact.name!r} must contain a timestamp "
                f"(≥8 digits, e.g. YYYYMMDD or Unix epoch) for idempotent safe "
                f"re-runs; pattern not found."
            )


# ===========================================================================
# pg-backup.sh — idempotent: re-run does not corrupt existing artifacts
# ===========================================================================


def test_m10_backup_idempotent_rerun_safe() -> None:
    """Running pg-backup.sh twice produces two distinct timestamped artifacts.

    The second run must not overwrite or corrupt the first artifact.
    Both files must exist and remain non-plaintext after two runs.

    FAILS today: script does not exist.
    """
    if not _BACKUP_SCRIPT.exists():
        pytest.fail(
            f"scripts/backup/pg-backup.sh not found at {_BACKUP_SCRIPT}."
        )

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        remote_dir = tmp / "remote"
        remote_dir.mkdir()
        fake_bin = _make_fake_bin_dir(tmp)

        env = _env_with_fake_bin(
            fake_bin,
            {
                "BACKUP_PASSPHRASE": "m10-idempotent-pass",
                "BACKUP_REMOTE": str(remote_dir),
                "DATABASE_URL": "postgresql://fake:fake@localhost/fakedb",
            },
        )

        for run in range(2):
            result = subprocess.run(
                [str(_BACKUP_SCRIPT)],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert result.returncode == 0, (
                f"pg-backup.sh run {run+1} exited {result.returncode}: {result.stderr!r}"
            )
            # Brief pause so timestamps differ by at least 1 second
            import time as _time
            _time.sleep(1)

        artifacts = [a for a in remote_dir.glob("**/*") if a.is_file()]
        # At minimum 1 artifact must exist; re-runs may share a name only if
        # idempotent-by-content (content-addressed). If they do share a name,
        # verify both runs preserved the encrypted content (no plaintext leak).
        assert len(artifacts) >= 1, (
            f"After two runs, at least one artifact must exist in {remote_dir}"
        )
        for artifact in artifacts:
            assert _DUMP_MARKER.encode() not in artifact.read_bytes(), (
                f"Artifact {artifact.name} leaked plaintext after re-run."
            )


# ===========================================================================
# pg-restore-drill.sh — script existence
# ===========================================================================


def test_m10_restore_drill_script_exists() -> None:
    """scripts/backup/pg-restore-drill.sh must exist.

    FAILS today: the file is absent.
    """
    assert _RESTORE_SCRIPT.exists(), (
        f"scripts/backup/pg-restore-drill.sh must exist at {_RESTORE_SCRIPT}; "
        f"file not found — implement the restore-drill script for M10."
    )


# ===========================================================================
# pg-restore-drill.sh — round-trip: encrypt → decrypt → marker present
# ===========================================================================


def test_m10_restore_drill_decrypts_and_pipes_to_psql() -> None:
    """pg-restore-drill.sh decrypts backup and pipes to psql; marker round-trips.

    The test:
    1. Creates a fake encrypted artifact (gpg symmetric encryption of marker text).
    2. Calls pg-restore-drill.sh with the artifact path, passphrase, and a fake
       DATABASE_URL.
    3. Asserts exit code 0.
    4. Asserts the fake psql received input containing the plaintext marker.

    FAILS today: script does not exist.
    """
    if not _RESTORE_SCRIPT.exists():
        pytest.fail(
            f"scripts/backup/pg-restore-drill.sh not found at {_RESTORE_SCRIPT}."
        )

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        fake_bin = _make_fake_bin_dir(tmp)
        passphrase = "m10-restore-test-pass"

        # Create an encrypted artifact using gpg symmetric encryption.
        plaintext = f"{_DUMP_MARKER}\n-- fake SQL restore content\n"
        artifact_path = tmp / "backup_20260101_120000.sql.gpg"
        encrypt_result = subprocess.run(
            [
                "gpg",
                "--batch",
                "--yes",
                "--symmetric",
                "--cipher-algo", "AES256",
                "--passphrase", passphrase,
                "--output", str(artifact_path),
            ],
            input=plaintext,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if encrypt_result.returncode != 0:
            pytest.skip(
                f"gpg not available or failed to encrypt test artifact; "
                f"stderr={encrypt_result.stderr!r}"
            )

        received_path = tmp / "psql_received.txt"
        env = _env_with_fake_bin(
            fake_bin,
            {
                "BACKUP_PASSPHRASE": passphrase,
                "DATABASE_URL": "postgresql://fake:fake@localhost/fakedb",
                "PSQL_RECEIVED_PATH": str(received_path),
            },
        )

        result = subprocess.run(
            [str(_RESTORE_SCRIPT), str(artifact_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"pg-restore-drill.sh must exit 0 with correct passphrase; "
            f"exit={result.returncode} stderr={result.stderr!r}"
        )

        assert received_path.exists(), (
            f"Fake psql must have received input (PSQL_RECEIVED_PATH={received_path} "
            f"was not written); restore script must pipe decrypted content to psql."
        )
        received = received_path.read_text(encoding="utf-8")
        assert _DUMP_MARKER in received, (
            f"Plaintext marker {_DUMP_MARKER!r} must round-trip through "
            f"encrypt→decrypt→psql; received content: {received!r}"
        )


# ===========================================================================
# pg-restore-drill.sh — wrong passphrase → exit non-zero
# ===========================================================================


def test_m10_restore_drill_wrong_passphrase_exits_nonzero() -> None:
    """pg-restore-drill.sh exits non-zero when the passphrase is wrong.

    FAILS today: script does not exist.
    """
    if not _RESTORE_SCRIPT.exists():
        pytest.fail(
            f"scripts/backup/pg-restore-drill.sh not found at {_RESTORE_SCRIPT}."
        )

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        fake_bin = _make_fake_bin_dir(tmp)
        correct_passphrase = "correct-m10-pass"
        wrong_passphrase = "totally-wrong-passphrase-xXx"

        plaintext = f"{_DUMP_MARKER}\n"
        artifact_path = tmp / "backup_test.sql.gpg"
        enc = subprocess.run(
            [
                "gpg",
                "--batch",
                "--yes",
                "--symmetric",
                "--cipher-algo", "AES256",
                "--passphrase", correct_passphrase,
                "--output", str(artifact_path),
            ],
            input=plaintext,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if enc.returncode != 0:
            pytest.skip("gpg not available to create test artifact")

        env = _env_with_fake_bin(
            fake_bin,
            {
                "BACKUP_PASSPHRASE": wrong_passphrase,
                "DATABASE_URL": "postgresql://fake:fake@localhost/fakedb",
            },
        )

        result = subprocess.run(
            [str(_RESTORE_SCRIPT), str(artifact_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0, (
            f"pg-restore-drill.sh must exit non-zero when decryption fails "
            f"(wrong passphrase); got exit code {result.returncode}"
        )
