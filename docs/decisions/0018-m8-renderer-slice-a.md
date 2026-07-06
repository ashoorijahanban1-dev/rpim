# ADR 0018 — M8 slice A: renderer service core (templates + fake PNG)

**Status:** accepted (M8, slice A)

**Decisions.**
- **New US-leg service `apps/renderer`** (blueprint §2: the renderer lives on
  the US VPS, 0.8–1.2GB RAM). Same internal trust boundary as the gateway:
  `POST /render` requires `X-Internal-Token` (401 otherwise); `/health`
  reports `service=renderer, leg=us`.
- **Persian text comes from the template engine, never a generative model**
  (blueprint v1.2 §3: image models render Persian glyphs badly). Three
  Jinja2 RTL templates (`announce`, `quote`, `product`) × three pinned sizes
  (`square` 1080×1080, `story` 1080×1920, `wide` 1280×720) — the §6.4
  acceptance matrix «۳ قالب × ۳ سایز». Autoescape is ON (tenant text is
  untrusted input into HTML).
- **RENDER_MODE=fake is the committed default**: a deterministic pure-Python
  PNG (exact target dimensions, color seeded from template+size+rendered
  HTML) — no Chromium, no network, byte-identical for identical requests, so
  cross-leg render jobs stay idempotent and CI stays light. Any other mode
  currently refuses with 503 rather than emitting a false image — the
  Chromium screenshot path is slice B.
- **Chromium (slice B) is a rendering engine, not browser automation.**
  Constitution rule 5 forbids browser automation against third-party
  platforms for distribution; headless Chromium screenshotting OUR OWN local
  template HTML involves no external site, no account, no platform — and the
  blueprint (§2) explicitly mandates it for the renderer. Recorded here so
  the reviewer gate has the boundary in writing before slice B lands.
- **Response contract**: JSON `{image_b64, meta{template, size, width,
  height, render_mode, tenant_id, text_sha256}}` — metadata travels with
  every asset from birth (blueprint v1.2: an asset without metadata leaves
  M9 measurement blind); `text_sha256` pins provenance of the copy.

**Consequences.** Slice B: Playwright/Chromium live path (proving
«رندر < ۵ ثانیه، متن فارسی سالم» on a real screenshot), renderer Dockerfile
+ compose service on the US leg, storage/attachment flow toward publish
jobs. Per-tenant brand palettes/logos join once the brand-profile schema
grows asset fields.
