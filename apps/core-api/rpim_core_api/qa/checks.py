"""Layer-1 automated QA (blueprint M6): claim verification against the brand
brain, Persian sensitivity blacklist (asymmetric policy — wrong silence is
cheap, wrong publish is a disaster), and channel spec checks.

The blacklist here is the STARTER list; the curated per-vertical list is an
ops asset that grows in production (ADR 0015). A sensitivity hit is always
level="block" → mandatory human review, no exceptions (constitution rule 1).
"""

import json
import re
from importlib import resources

_NUM_RE = re.compile(r"[0-9۰-۹]{2,}")

_CHANNEL_CAPS = {"telegram": 4096, "bale": 4096, "eitaa": 4096, "instagram": 2200}
_CHANNEL_FA = {"تلگرام": "telegram", "بله": "bale", "ایتا": "eitaa", "اینستاگرام": "instagram"}

_SENSITIVE: dict[str, list[str]] = json.loads(
    resources.files("rpim_core_api").joinpath("qa/sensitive_fa.json").read_text("utf-8")
)

# User-facing labels stay Persian (rule 6); machine fields stay English codes.
_CATEGORY_FA = {
    "political": "سیاسی",
    "religious": "مذهبی",
    "ethnic": "قومی",
    "gender": "جنسیتی",
    "health": "سلامت",
}
_CHANNEL_LABEL_FA = {v: k for k, v in _CHANNEL_FA.items()}


def check_claims(text: str, context: str) -> list[dict]:
    context_numbers = set(_NUM_RE.findall(context or ""))
    flags = []
    for number in _NUM_RE.findall(text or ""):
        if number not in context_numbers:
            flags.append(
                {
                    "check": "claims",
                    "level": "review",
                    "code": "unsourced_number",
                    "reason": f"عدد بدون پشتوانه در مغز برند: {number}",
                }
            )
    return flags


def check_sensitivity(text: str) -> list[dict]:
    flags = []
    for category, terms in _SENSITIVE.items():
        for term in terms:
            if term in (text or ""):
                flags.append(
                    {
                        "check": "sensitivity",
                        "category": category,
                        "level": "block",
                        "code": "sensitive_term",
                        "reason": f"واژه حساس ({_CATEGORY_FA.get(category, category)}): {term}",
                    }
                )
                break  # one flag per category is enough to force human review
    return flags


def check_channel(text: str, channel: str) -> list[dict]:
    normalized = _CHANNEL_FA.get((channel or "").strip(), (channel or "").strip().lower())
    cap = _CHANNEL_CAPS.get(normalized)
    if cap is None:
        return [
            {
                "check": "channel",
                "level": "review",
                "code": "unknown_channel",
                "reason": f"کانال ناشناخته: {channel}",
            }
        ]
    if len(text or "") > cap:
        return [
            {
                "check": "channel",
                "level": "review",
                "code": "over_cap",
                "reason": (
                    f"طول متن {len(text)} از سقف {cap} کانال "
                    f"{_CHANNEL_LABEL_FA.get(normalized, normalized)} بیشتر است"
                ),
            }
        ]
    return []


def run_all(text: str, context: str, channel: str) -> list[dict]:
    return check_claims(text, context) + check_sensitivity(text) + check_channel(text, channel)
