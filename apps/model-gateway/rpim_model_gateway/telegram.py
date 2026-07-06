"""Telegram sender for the us leg.

The iran leg never calls api.telegram.org directly — it forwards to this
module via POST /publish/telegram over the tunnel. Official bot API only
(rule 5). PUBLISH_MODE=fake records into _SENT instead of hitting the
network (tests + CI).
"""

import os

import httpx

# Fake seam: tests and CI inspect _SENT.
_SENT: list[dict] = []


class TelegramNotConfigured(Exception):
    """TELEGRAM_BOT_TOKEN is missing — the route maps this to 503."""


class TelegramSendError(Exception):
    """Transient telegram send failure — the route maps this to 502."""


def _post_json(url: str, payload: dict, headers: dict | None = None) -> None:
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # Never echo the URL: it embeds the bot token (rule 4).
        raise TelegramSendError(f"telegram api failed: {type(exc).__name__}") from exc


def _post_multipart(url: str, data: dict, files: dict) -> None:
    try:
        response = httpx.post(url, data=data, files=files, timeout=60)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # Never echo the URL: it embeds the bot token (rule 4).
        raise TelegramSendError(f"telegram api failed: {type(exc).__name__}") from exc


def send_telegram_photo(chat_id: str, caption: str, photo_png: bytes) -> dict:
    mode = os.environ.get("PUBLISH_MODE", "fake")
    if mode == "fake":
        _SENT.append(
            {
                "chat_id": chat_id,
                "caption": caption,
                "kind": "photo",
                "image_size": len(photo_png),
            }
        )
        return {"ok": True, "mode": "fake"}
    if mode != "live":
        raise TelegramSendError("PUBLISH_MODE must be 'fake' or 'live'")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        # Name the env var, never a value (rule 4).
        raise TelegramNotConfigured(
            "env var TELEGRAM_BOT_TOKEN is not set — telegram publishing disabled"
        )
    _post_multipart(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        {"chat_id": chat_id, "caption": caption},
        {"photo": ("post.png", photo_png, "image/png")},
    )
    return {"ok": True, "mode": "live"}


def send_telegram(chat_id: str, text: str) -> dict:
    mode = os.environ.get("PUBLISH_MODE", "fake")
    if mode == "fake":
        _SENT.append({"chat_id": chat_id, "text": text})
        return {"ok": True, "mode": "fake"}
    if mode != "live":
        # Explicit or nothing — a typo'd mode fails loud instead of guessing.
        raise TelegramSendError("PUBLISH_MODE must be 'fake' or 'live'")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        # Name the env var, never a value (rule 4).
        raise TelegramNotConfigured(
            "env var TELEGRAM_BOT_TOKEN is not set — telegram publishing disabled"
        )
    _post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat_id, "text": text},
    )
    return {"ok": True, "mode": "live"}
