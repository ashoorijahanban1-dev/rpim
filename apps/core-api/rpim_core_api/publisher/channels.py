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


SUPPORTED_CHANNELS = ("telegram", "bale", "eitaa", "wordpress")

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
    url: str,
    chat_id: str,
    caption: str,
    image_png: bytes,
    headers: dict | None = None,
    request_id: str | None = None,
    bot_token: str | None = None,
) -> None:
    data = {"chat_id": chat_id, "caption": caption}
    if request_id:
        data["request_id"] = request_id
    if bot_token:
        data["bot_token"] = bot_token
    try:
        response = httpx.post(
            url,
            data=data,
            files={"photo": ("post.png", image_png, "image/png")},
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # Never echo the URL: bot-API URLs embed the token (rule 4).
        raise ChannelSendError(f"channel endpoint failed: {type(exc).__name__}") from exc


def send_photo(
    channel: str,
    chat_id: str,
    caption: str,
    image_png: bytes,
    job_id: str,
    creds: dict | None = None,
) -> None:
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
                "creds_source": "tenant" if creds else "env",
            }
        )
        return
    if mode != "live":
        raise ChannelSendError("PUBLISH_MODE must be 'fake' or 'live'")

    if channel == "bale":
        token = _tenant_secret(creds) or _require_env("BALE_BOT_TOKEN")
        _post_photo(f"https://tapi.bale.ai/bot{token}/sendPhoto", chat_id, caption, image_png)
    elif channel == "eitaa":
        token = _tenant_secret(creds) or _require_env("EITAA_BOT_TOKEN")
        _post_photo(f"https://eitaayar.ir/api/{token}/sendFile", chat_id, caption, image_png)
    elif channel == "telegram":
        # Cross-leg multipart; the gateway photo passthrough is the follow-up
        # slice — until it exists this fails transiently and the job waits.
        gateway = _require_env("GATEWAY_URL").rstrip("/")
        internal = _require_env("INTERNAL_TOKEN")
        # job_id doubles as the cross-leg idempotency key (rule 8): a tunnel
        # drop after telegram accepted the send cannot double-post on retry.
        _post_photo(
            f"{gateway}/publish/telegram-photo",
            chat_id,
            caption,
            image_png,
            headers={"X-Internal-Token": internal},
            request_id=job_id,
            bot_token=_tenant_secret(creds),
        )
    elif channel == "wordpress":
        # Media is a two-step wp flow (upload → featured_media) — follow-up
        # slice. Transient failure keeps the job queued (telegram-photo
        # precedent), never a silent drop or a false "sent".
        raise ChannelSendError("wordpress photo posts need the media slice — job stays queued")
    else:
        raise ChannelSendError(f"unsupported channel {channel}")


def _tenant_secret(creds: dict | None) -> str | None:
    if creds and str(creds.get("secret", "")).strip():
        return str(creds["secret"]).strip()
    return None


def _wordpress_send(text: str, creds: dict | None = None) -> None:
    if creds is not None:
        config = creds.get("config") or {}
        base = str(config.get("base_url", "")).rstrip("/")
        user = str(config.get("user", ""))
        app_password = _tenant_secret(creds) or ""
        if not base or not user or not app_password:
            # Name the missing FIELD, never a value (rule 4).
            raise ChannelSendError(
                "wordpress connection incomplete: base_url, user and secret are required"
            )
    else:
        base = _require_env("WORDPRESS_BASE_URL").rstrip("/")
        user = _require_env("WORDPRESS_USER")
        app_password = _require_env("WORDPRESS_APP_PASSWORD")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0] if lines else text
    try:
        response = httpx.post(
            f"{base}/wp-json/wp/v2/posts",
            json={"title": title, "content": text, "status": "publish"},
            auth=(user, app_password),
            timeout=30,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # Never echo the URL or credentials (rule 4).
        raise ChannelSendError(f"channel endpoint failed: {type(exc).__name__}") from exc


def send(
    channel: str, chat_id: str, text: str, job_id: str, creds: dict | None = None
) -> None:
    mode = os.environ.get("PUBLISH_MODE", "fake")
    if mode == "fake":
        if channel in _FAIL_NEXT:
            _FAIL_NEXT.remove(channel)
            raise ChannelSendError(f"injected transient failure for {channel}")
        _OUTBOX.append(
            {
                "channel": channel,
                "chat_id": chat_id,
                "text": text,
                "job_id": job_id,
                "creds_source": "tenant" if creds else "env",
            }
        )
        return
    if mode != "live":
        # Explicit or nothing: a typo'd mode must not silently dry-run
        # (false "sent") nor accidentally go live — fail loud, job stays queued.
        raise ChannelSendError("PUBLISH_MODE must be 'fake' or 'live'")

    payload = {"chat_id": chat_id, "text": text}
    if channel == "bale":
        token = _tenant_secret(creds) or _require_env("BALE_BOT_TOKEN")
        _post_json(f"https://tapi.bale.ai/bot{token}/sendMessage", payload)
    elif channel == "eitaa":
        token = _tenant_secret(creds) or _require_env("EITAA_BOT_TOKEN")
        _post_json(f"https://eitaayar.ir/api/{token}/sendMessage", payload)
    elif channel == "telegram":
        # Cross-leg: telegram is only reachable from the us leg (rule 5);
        # job_id rides along as the idempotency key (rule 8).
        gateway = _require_env("GATEWAY_URL").rstrip("/")
        internal = _require_env("INTERNAL_TOKEN")
        tenant_token = _tenant_secret(creds)
        _post_json(
            f"{gateway}/publish/telegram",
            {
                **payload,
                "request_id": job_id,
                **({"bot_token": tenant_token} if tenant_token else {}),
            },
            headers={"X-Internal-Token": internal},
        )
    elif channel == "wordpress":
        # Official wp-json REST with an application password (rule 5).
        # chat_id has no wordpress meaning and is ignored; title = the
        # text's first non-empty line.
        _wordpress_send(text, creds)
    else:
        raise ChannelSendError(f"unsupported channel {channel}")
