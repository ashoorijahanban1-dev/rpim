"""Image-generation adapters (M21) — the M17 text-provider pattern, mirrored.
Official APIs only (rule 5): OpenAI images/generations, Gemini Imagen.
Keys come from env NAMES, travel ONLY in headers, and a missing key is a
failed chain link (the /image route falls through to the next link)."""

import base64
import hashlib
import os

import httpx


class ImageProviderError(Exception):
    pass


def _fake_image(model: str, prompt: str, size: str = "1024x1024", timeout: float = 120.0) -> dict:
    """Deterministic offline provider for tests/CI/dev — bytes seeded by the
    prompt so dedupe-by-sha256 is exercisable without a real model."""
    seed = hashlib.sha256(f"{model}:{prompt}:{size}".encode()).hexdigest()
    payload = f"PNG-FAKE:{seed}".encode()
    return {"image_b64": base64.b64encode(payload).decode(), "units": 1}


def _openai_image(model: str, prompt: str, size: str = "1024x1024", timeout: float = 120.0) -> dict:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ImageProviderError("OPENAI_API_KEY not set")
    response = httpx.post(
        "https://api.openai.com/v1/images/generations",
        json={
            "model": model,
            "prompt": prompt,
            "size": size,
            "n": 1,
            "response_format": "b64_json",
        },
        # Key in the header, NEVER the URL (rule 4).
        headers={"Authorization": f"Bearer {key}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return {"image_b64": response.json()["data"][0]["b64_json"], "units": 1}


def _gemini_image(model: str, prompt: str, size: str = "1024x1024", timeout: float = 120.0) -> dict:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise ImageProviderError("GEMINI_API_KEY not set")
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict",
        json={"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1}},
        # Official header — a query-param key would leak via httpx error URLs.
        headers={"x-goog-api-key": key},
        timeout=timeout,
    )
    response.raise_for_status()
    prediction = response.json()["predictions"][0]
    return {"image_b64": prediction["bytesBase64Encoded"], "units": 1}


IMAGE_PROVIDERS = {
    "fake": _fake_image,
    "openai": _openai_image,
    "gemini": _gemini_image,
}

# USD per IMAGE (not per token) — list prices; unknown models cost 0 and are
# visible in the ledger as such (the PRICES convention, providers.py).
IMAGE_PRICES: dict[str, float] = {
    "dall-e-3": 0.04,
    "gpt-image-1": 0.04,
    "imagen-3.0-generate-002": 0.03,
}
