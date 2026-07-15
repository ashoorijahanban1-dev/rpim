"""Visual Prompt Studio expander (M15) — استودیوی پرامپت بصری.

Deterministic prompt engineering: a small marketing brief becomes a
professional generative-model prompt (English — the target models are
English-prompted; the Persian subject rides along verbatim). No LLM call —
the expansion is algorithmic, reviewable, and free; a T2-polished variant
is a later slice.
"""

# Channel → aspect ratio for Persian social/web surfaces.
_ASPECTS = {
    "telegram": "1:1",
    "bale": "1:1",
    "eitaa": "1:1",
    "instagram": "4:5",
    "story": "9:16",
    "wordpress": "16:9",
}
_DEFAULT_ASPECT = "1:1"

_IMAGE_QUALITY = (
    "photorealistic, high detail, studio lighting, sharp focus, "
    "professional product photography, clean composition, 8k"
)
_VIDEO_QUALITY = (
    "cinematic, smooth camera motion, slow dolly-in, shallow depth of field, "
    "natural motion blur, 24fps, 6-second loop"
)
_NEGATIVE = (
    "Negative prompt: text artifacts, watermark, logo distortion, extra fingers, "
    "low quality, oversaturated, cluttered background"
)


def expand(kind: str, brief: dict, tone: str | None) -> str:
    subject = str(brief.get("subject", "")).strip()
    mood = str(brief.get("mood", "") or "").strip()
    channel = str(brief.get("channel", "") or "").strip().lower()
    aspect = _ASPECTS.get(channel, _DEFAULT_ASPECT)

    lines = [
        f"Marketing visual for: {subject}",
        f"Brand tone (Persian): {tone.strip()}" if tone and tone.strip() else "",
        f"Mood: {mood}" if mood else "",
        f"Aspect ratio: {aspect}",
        _VIDEO_QUALITY if kind == "video" else _IMAGE_QUALITY,
    ]
    prompt = "\n".join(line for line in lines if line)
    if kind == "image":
        prompt = f"{prompt}\n{_NEGATIVE}"
    return prompt
