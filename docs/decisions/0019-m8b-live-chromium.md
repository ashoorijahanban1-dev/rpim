# ADR 0019 — M8 slice B: live Chromium rendering + deploy wiring

**Status:** accepted (M8, slice B — completes the milestone)

**Decisions.**
- **`rpim_renderer.chromium.screenshot_png`** drives headless Chromium via
  Playwright's sync API: viewport = target size, `set_content` of our own
  template HTML, viewport screenshot. Any launch/render failure surfaces as
  `RenderUnavailable` → HTTP 503 naming only the engine ("playwright" /
  "chromium"), never paths or args (rule 4). A missing engine can never
  produce a fake PNG labeled "live" — false success is worse than downtime.
- **Acceptance proven in-session, self-skipping elsewhere.** The §6.4 test
  («رندر < ۵ ثانیه، متن فارسی سالم») runs against the real pre-installed
  Chromium in the dev sandbox (passed: 1080×1080 Persian frame in ~2s;
  Persian-vs-Latin frames differ, so glyphs are actually painted) and skips
  automatically where no browser binary exists (CI runners). `playwright`
  sits in the root dev group for that; the runtime dependency lives only in
  the renderer's `live` extra.
- **Dockerfile** installs the `live` extra plus `playwright install
  --with-deps chromium` and `fonts-vazirmatn`, so the deployed container
  renders the brand font stack for real; committed default stays
  `RENDER_MODE=fake` until ops flips it.
- **Compose exposure follows the gateway pattern**: the renderer binds
  `${RENDERER_BIND:-127.0.0.1}:${RENDERER_PORT:-8091}` — loopback locally,
  the WireGuard IP on the real server, never public.
- Binary resolution: explicit `RPIM_CHROMIUM_PATH` → sandbox symlink
  `/opt/pw-browsers/chromium` → Playwright's own managed browser (the
  container case).

**Consequences.** M8 acceptance is met end-to-end. Follow-ups queued for
M9/M7-integration: attaching rendered assets to publish jobs and persisting
them (MinIO/disk budget per blueprint §2), per-tenant brand palettes.
