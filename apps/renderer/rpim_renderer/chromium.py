"""Chromium screenshot backend for RENDER_MODE=live.

This renders OUR OWN template HTML in a headless browser — no external site,
no account, no third-party platform — which is the blueprint-mandated engine
(§2) and outside the scope of rule 5's automation ban (ADR 0018).
"""

import os


class RenderUnavailable(Exception):
    """Playwright missing or Chromium failed to launch/render."""


def _executable_path() -> str | None:
    """Prefer an explicitly provided binary; fall back to playwright's own."""
    explicit = os.environ.get("RPIM_CHROMIUM_PATH", "")
    if explicit:
        return explicit
    candidate = "/opt/pw-browsers/chromium"
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return None


def screenshot_png(html: str, width: int, height: int) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderUnavailable("playwright is not installed") from exc

    try:
        with sync_playwright() as pw:
            launch_kwargs: dict = {"headless": True}
            exe = _executable_path()
            if exe:
                launch_kwargs["executable_path"] = exe
            browser = pw.chromium.launch(**launch_kwargs)
            try:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.set_content(html, wait_until="load")
                return page.screenshot(type="png", full_page=False)
            finally:
                browser.close()
    except RenderUnavailable:
        raise
    except Exception as exc:
        # Never echo paths or launch args — name the engine only (rule 4).
        raise RenderUnavailable(f"chromium render failed: {type(exc).__name__}") from exc
