"""Brand templates: HTML is the single source of Persian text on images.

Generative image models render Persian glyphs badly (blueprint v1.2 §3):
every character on a rendered asset comes from these RTL HTML templates, so
brand consistency lives in template + palette, never in a prompt.
"""

from jinja2 import Environment

SIZES: dict[str, tuple[int, int]] = {
    "square": (1080, 1080),
    "story": (1080, 1920),
    "wide": (1280, 720),
}

# Layout intents per template; shared skeleton keeps the font stack and RTL
# direction identical everywhere.
TEMPLATES: dict[str, dict] = {
    "announce": {"accent_block": True, "body_size": 44},
    "quote": {"accent_block": False, "body_size": 56},
    "product": {"accent_block": True, "body_size": 40},
}

_PAGE = """<!doctype html>
<html dir="rtl" lang="fa">
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { width: {{ width }}px; height: {{ height }}px; }
  body {
    font-family: Vazirmatn, Tahoma, "Segoe UI", sans-serif;
    background: {{ background }};
    color: {{ foreground }};
    display: flex; flex-direction: column; justify-content: center;
    padding: {{ pad }}px; text-align: right; line-height: 1.8;
  }
  .kind-{{ template }} .title { font-weight: 800; }
  .title { font-size: {{ title_size }}px; margin-bottom: 0.6em; }
  .body { font-size: {{ body_size }}px; }
  .cta {
    font-size: {{ cta_size }}px; margin-top: 1.2em; font-weight: 700;
    {% if accent_block %}background: {{ foreground }}; color: {{ background }};
    padding: 0.4em 0.9em; border-radius: 14px; align-self: flex-start;{% endif %}
  }
</style>
</head>
<body class="kind-{{ template }}">
  <div class="title">{{ title }}</div>
  {% if body %}<div class="body">{{ body }}</div>{% endif %}
  {% if cta %}<div class="cta">{{ cta }}</div>{% endif %}
</body>
</html>
"""

_env = Environment(autoescape=True)
_page = _env.from_string(_PAGE)


def html_for(template: str, size: str, text: dict) -> str:
    if template not in TEMPLATES:
        raise ValueError(f"unknown template: {template}")
    if size not in SIZES:
        raise ValueError(f"unknown size: {size}")
    width, height = SIZES[size]
    spec = TEMPLATES[template]
    return _page.render(
        template=template,
        width=width,
        height=height,
        pad=round(width * 0.08),
        title_size=round(width * 0.065),
        body_size=spec["body_size"],
        cta_size=round(width * 0.035),
        accent_block=spec["accent_block"],
        background="#101418",
        foreground="#f5f1e8",
        title=text.get("title", ""),
        body=text.get("body", ""),
        cta=text.get("cta", ""),
    )
