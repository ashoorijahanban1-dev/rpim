"""Channel adapters for the publish engine.

PUBLISH_MODE=fake (tests + CI) routes every send through the in-process
_OUTBOX seam. Live mode (M7 slice B) uses official bot APIs only (rule 5):
Bale and Eitaa directly from the iran leg, Telegram forwarded to the us-leg
gateway — the iran leg never talks to api.telegram.org itself.
"""

import os

import httpx


class ChannelSendError(Exception):
    """Transient send failure — the job stays queued and is retried later."""


SUPPORTED_CHANNELS = ("telegram", "bale", "eitaa")

# Fake seam: tests inspect _OUTBOX and inject one-shot failures by appending
# channel names to _FAIL_NEXT (consumed one entry per failed send).
_OUTBOX: list[dict] = []
_FAIL_NEXT: list[str] = []


def _post_json(url: str, payload: dict, headers: dict | None = None) -> None:
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # Never echo the URL: bot-API URLs embed the token (rule 4).
        raise ChannelSendError(f"channel endpoint failed: {type(exc).__name__}") from exc


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        # Name the env var, never a value (rule 4).
        raise ChannelSendError(f"missing credential: env var {name} is not set")
    return value


def _post_photo(
    url: str, chat_id: str, caption: str, image_png: bytes, headers: dict | None = None
) -> None:
    try:
        response = httpx.post(
            url,
            data={"chat_id": chat_id, "caption": caption},
            files={"photo": ("post.png", image_png, "image/png")},
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # Never echo the URL: bot-API URLs embed the token (rule 4).
        raise ChannelSendError(f"channel endpoint failed: {type(exc).__name__}") from exc


def send_photo(channel: str, chat_id: str, caption: str, image_png: bytes, job_id: str) -> None:
    mode = os.environ.get("PUBLISH_MODE", "fake")
    if mode == "fake":
        if channel in _FAIL_NEXT:
            _FAIL_NEXT.remove(channel)
            raise ChannelSendError(f"injected transient failure for {channel}")
        _OUTBOX.append(
            {
                "channel": channel,
                "chat_id": chat_id,
                "caption": caption,
                "job_id": job_id,
                "kind": "photo",
                "image_size": len(image_png),
            }
        )
        return
    if mode != "live":
        raise ChannelSendError("PUBLISH_MODE must be 'fake' or 'live'")

    if channel == "bale":
        token = _require_env("BALE_BOT_TOKEN")
        _post_photo(f"https://tapi.bale.ai/bot{token}/sendPhoto", chat_id, caption, image_png)
    elif channel == "eitaa":
        token = _require_env("EITAA_BOT_TOKEN")
        _post_photo(f"https://eitaayar.ir/api/{token}/sendFile", chat_id, caption, image_png)
    elif channel == "telegram":
        # Cross-leg multipart; the gateway photo passthrough is the follow-up
        # slice — until it exists this fails transiently and the job waits.
        gateway = _require_env("GATEWAY_URL").rstrip("/")
        internal = _require_env("INTERNAL_TOKEN")
        _post_photo(
            f"{gateway}/publish/telegram-photo",
            chat_id,
            caption,
            image_png,
            headers={"X-Internal-Token": internal},
        )
    else:
        raise ChannelSendError(f"unsupported channel {channel}")


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
    if mode != "live":
        # Explicit or nothing: a typo'd mode must not silently dry-run
        # (false "sent") nor accidentally go live — fail loud, job stays queued.
        raise ChannelSendError("PUBLISH_MODE must be 'fake' or 'live'")

    payload = {"chat_id": chat_id, "text": text}
    if channel == "bale":
        token = _require_env("BALE_BOT_TOKEN")
        _post_json(f"https://tapi.bale.ai/bot{token}/sendMessage", payload)
    elif channel == "eitaa":
        token = _require_env("EITAA_BOT_TOKEN")
        _post_json(f"https://eitaayar.ir/api/{token}/sendMessage", payload)
    elif channel == "telegram":
        # Cross-leg: telegram is only reachable from the us leg (rule 5).
        gateway = _require_env("GATEWAY_URL").rstrip("/")
        internal = _require_env("INTERNAL_TOKEN")
        _post_json(
            f"{gateway}/publish/telegram",
            payload,
            headers={"X-Internal-Token": internal},
        )
    else:
        raise ChannelSendError(f"unsupported channel {channel}")
