"""Channel adapters for the publish engine.

PUBLISH_MODE=fake (tests + CI) routes every send through the in-process
_OUTBOX seam. Real adapters — Bale/Eitaa direct from the iran leg, Telegram
via the us-leg gateway — land in M7 slice B, official APIs only (rule 5).
"""

import os


class ChannelSendError(Exception):
    """Transient send failure — the job stays queued and is retried later."""


SUPPORTED_CHANNELS = ("telegram", "bale", "eitaa")

# Fake seam: tests inspect _OUTBOX and inject one-shot failures by appending
# channel names to _FAIL_NEXT (consumed one entry per failed send).
_OUTBOX: list[dict] = []
_FAIL_NEXT: list[str] = []


def send(channel: str, chat_id: str, text: str, job_id: str) -> None:
    mode = os.environ.get("PUBLISH_MODE", "fake")
    if mode == "fake":
        if channel in _FAIL_NEXT:
            _FAIL_NEXT.remove(channel)
            raise ChannelSendError(f"injected transient failure for {channel}")
        _OUTBOX.append(
            {"channel": channel, "chat_id": chat_id, "text": text, "job_id": job_id}
        )
        return
    # Slice B wires the live adapters; failing loudly beats dropping silently.
    raise ChannelSendError(f"no live adapter configured for channel {channel}")
