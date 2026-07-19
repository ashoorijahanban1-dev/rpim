"""Channel-credential vault (M16 ADR 0033, M24 v2 — ADR 0038).

Tenant channel tokens are DATA (like user passwords), not deploy config —
rule 4 still governs the KEYS: they live only in env, never in code or the
repo. Two sealed formats coexist:

  v2 (current): "v2:" + base64url(nonce ‖ ciphertext), AES-GCM-256 keyed by
      CHANNEL_SECRET_KEY_V2, AAD = "{tenant_id}:{channel}" — the blob is
      BOUND to its row; copied into another row it will not open.
  v1 (legacy):  a raw Fernet token (always starts "gAAAA") keyed by
      CHANNEL_SECRET_KEY — readable forever during the transition, upgraded
      lazily by the publisher (best-effort, never blocking).

Rollout safety: seal() prefers v2 but falls back to v1 while
CHANNEL_SECRET_KEY_V2 is not yet deployed — a key-rollout gap must never
break the connect flow or the publish pipeline. EVERY failure surfaces as
VaultKeyError so the publisher's per-job isolation holds.
"""

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_V2_PREFIX = "v2:"
_NONCE_LEN = 12


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


def _gcm() -> AESGCM:
    key = os.environ.get("CHANNEL_SECRET_KEY_V2", "")
    if not key:
        raise VaultKeyError("missing key: env var CHANNEL_SECRET_KEY_V2 is not set")
    try:
        raw = base64.urlsafe_b64decode(key.encode())
    except (ValueError, binascii.Error) as exc:
        raise VaultKeyError("env var CHANNEL_SECRET_KEY_V2 is not valid base64") from exc
    if len(raw) != 32:
        raise VaultKeyError("env var CHANNEL_SECRET_KEY_V2 must decode to 32 bytes")
    return AESGCM(raw)


def _aad(tenant_id: str, channel: str) -> bytes:
    return f"{tenant_id}:{channel}".encode()


def is_v2(sealed: str) -> bool:
    return sealed.startswith(_V2_PREFIX)


def seal(plaintext: str, *, tenant_id: str, channel: str) -> str:
    if not os.environ.get("CHANNEL_SECRET_KEY_V2", ""):
        # Rollout gap: V2 key not deployed yet → v1 sealing keeps working.
        # If v1 is ALSO absent, this raises and the API door 503s (M16).
        # An INVALID key is different: that is a config error the operator
        # must see — _gcm() below raises instead of silently degrading.
        return _fernet().encrypt(plaintext.encode()).decode()
    gcm = _gcm()
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = gcm.encrypt(nonce, plaintext.encode(), _aad(tenant_id, channel))
    return _V2_PREFIX + base64.urlsafe_b64encode(nonce + ciphertext).decode()


def unseal(sealed: str, *, tenant_id: str, channel: str) -> str:
    if is_v2(sealed):
        try:
            raw = base64.urlsafe_b64decode(sealed[len(_V2_PREFIX) :].encode())
            if len(raw) <= _NONCE_LEN:
                raise VaultKeyError("sealed v2 value is truncated")
            return _gcm().decrypt(
                raw[:_NONCE_LEN], raw[_NONCE_LEN:], _aad(tenant_id, channel)
            ).decode()
        except VaultKeyError:
            raise
        except (InvalidTag, ValueError, binascii.Error) as exc:
            # Wrong AAD (blob moved between rows), rotated/lost key, or a
            # corrupt blob — one VaultKeyError contract for all of them so a
            # single bad row can never abort a whole dispatch batch.
            raise VaultKeyError(
                "stored secret cannot be opened with CHANNEL_SECRET_KEY_V2 for this row"
            ) from exc
    try:
        return _fernet().decrypt(sealed.encode()).decode()
    except InvalidToken as exc:
        raise VaultKeyError(
            "stored secret cannot be opened with the current CHANNEL_SECRET_KEY"
        ) from exc
