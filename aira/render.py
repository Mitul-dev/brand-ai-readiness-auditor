"""Optional headless rendering, used only to measure the raw-vs-rendered gap.

Rendering is a *measurement instrument* here, not a scraper: we load the page,
wait for the network to settle, and record the resulting DOM text. A single
browser instance is reused for the whole run and the number of rendered pages is
capped. If Playwright or its browser binary is unavailable the audit degrades
gracefully - rendering-dependent checks then report NOT APPLICABLE rather than
guessing.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .config import AuditConfig

log = logging.getLogger("aira.render")


@dataclass(slots=True)
class RenderedPage:
    url: str
    ok: bool
    html: str = ""
    error: str | None = None


def renderer_available() -> tuple[bool, str | None]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:
        return False, f"playwright not importable: {exc}"
    return True, None


def _guard_route(route, request) -> None:
    """Abort any sub-request that is not plain http(s)."""
    try:
        if request.url.split(":", 1)[0].lower() not in ("http", "https"):
            route.abort()
        else:
            route.continue_()
    except Exception:
        try:
            route.continue_()
        except Exception:
            pass


def render_pages(urls: list[str], config: AuditConfig) -> dict[str, RenderedPage]:
    """Render up to ``config.max_rendered_pages`` URLs. Never raises."""
    out: dict[str, RenderedPage] = {}
    if not config.render or not urls:
        return out
    ok, why = renderer_available()
    if not ok:
        log.warning("rendering skipped: %s", why)
        return out
    from playwright.sync_api import sync_playwright

    subset = urls[: config.max_rendered_pages]
    started = time.perf_counter()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                context = browser.new_context(
                    user_agent=config.user_agent,
                    java_script_enabled=True,
                    bypass_csp=False,
                )
                context.set_default_timeout(config.render_timeout_s * 1000)
                # Read-only rendering: never let the page start a download, and
                # never let it navigate the browser to a non-web scheme.
                context.on("page", lambda p: p.on("download", lambda d: d.cancel()))
                context.route("**/*", _guard_route)
                for url in subset:
                    # The five-minute audit budget is a hard requirement, and
                    # rendering is the only unbounded-ish stage, so the whole
                    # stage is capped in wall-clock terms as well as by count.
                    if time.perf_counter() - started > config.render_budget_s:
                        log.warning("rendering budget of %.0fs exhausted after "
                                    "%d page(s)", config.render_budget_s, len(out))
                        break
                    page = context.new_page()
                    # Read-only: block nothing we need, but never allow downloads
                    try:
                        page.goto(url, wait_until="domcontentloaded",
                                  timeout=config.render_timeout_s * 1000)
                        try:
                            page.wait_for_load_state(
                                "networkidle",
                                timeout=min(6000, config.render_timeout_s * 1000),
                            )
                        except Exception:
                            pass  # networkidle is best-effort
                        out[url] = RenderedPage(url=url, ok=True,
                                                html=page.content())
                    except Exception as exc:
                        out[url] = RenderedPage(url=url, ok=False,
                                                error=f"{type(exc).__name__}: {exc}")
                    finally:
                        try:
                            page.close()
                        except Exception:
                            pass
            finally:
                browser.close()
    except Exception as exc:
        log.warning("renderer failed to start: %s", exc)
    return out
