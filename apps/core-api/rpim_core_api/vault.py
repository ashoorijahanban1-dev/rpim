"""Channel-credential vault (M16, ADR 0033) — rpim_core_api.vault.

Tenant channel tokens are DATA (like user passwords), not deploy config —
rule 4 still governs the KEY: it lives only in env CHANNEL_SECRET_KEY
(a Fernet key), never in code or the repo. Fernet = AES128-CBC + HMAC,
authenticated; no hand-rolled crypto.
"""

import os

from cryptography.fernet import Fernet, InvalidToken


class VaultKeyError(Exception):
    """Vault key missing/invalid — connections cannot be sealed or opened."""


def _fernet() -> Fernet:
    key = os.environ.get("CHANNEL_SECRET_KEY", "")
    if not key:
        # Name the env var, never a value (rule 4).
        raise VaultKeyError("missing key: env var CHANNEL_SECRET_KEY is not set")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise VaultKeyError("env var CHANNEL_SECRET_KEY is not a valid Fernet key") from exc


def seal(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def unseal(sealed: str) -> str:
    try:
        return _fernet().decrypt(sealed.encode()).decode()
    except InvalidToken as exc:
        raise VaultKeyError(
            "stored secret cannot be opened with the current CHANNEL_SECRET_KEY"
        ) from exc
