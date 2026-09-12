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
from dataclasses import dataclass, field

from .config import AuditConfig

log = logging.getLogger("aira.render")


# Why the rendering stage produced what it produced. "0 pages rendered" is
# ambiguous on its own - it can mean the browser was missing, every navigation
# failed, the budget ran out, or nothing needed rendering - and a report that
# cannot tell those apart invites a reader to conclude that JavaScript was
# irrelevant when in fact nothing was ever measured.
NOT_REQUESTED = "not_requested"
NO_CANDIDATES = "no_candidates"
BROWSER_UNAVAILABLE = "browser_unavailable"
ALL_FAILED = "all_failed"
PARTIAL = "partial"
COMPLETE = "complete"
BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(slots=True)
class RenderRun:
    """Outcome of the rendering stage, including why it stopped."""
    status: str = NOT_REQUESTED
    pages: dict[str, "RenderedPage"] = field(default_factory=dict)
    requested: int = 0
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    error_sample: str | None = None
    detail: str = ""

    @property
    def evidence_available(self) -> bool:
        return self.succeeded > 0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "evidence_available": self.evidence_available,
            "requested": self.requested,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "error_sample": self.error_sample,
            "detail": self.detail,
        }


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


def render_pages(urls: list[str], config: AuditConfig) -> RenderRun:
    """Render up to ``config.max_rendered_pages`` URLs. Never raises.

    Always returns a :class:`RenderRun` describing what happened, so the report
    can state the rendering situation instead of leaving a zero to be guessed at.
    """
    run = RenderRun()
    out: dict[str, RenderedPage] = run.pages
    if not config.render:
        run.status = NOT_REQUESTED
        run.detail = "rendering was disabled for this run"
        return run
    if not urls:
        run.status = NO_CANDIDATES
        run.detail = "no successfully fetched HTML page was eligible for rendering"
        return run
    ok, why = renderer_available()
    if not ok:
        log.warning("rendering skipped: %s", why)
        run.status = BROWSER_UNAVAILABLE
        run.error_sample = why
        run.detail = (f"the headless browser could not be started ({why}); "
                      "raw-versus-rendered comparison was not possible")
        return run
    from playwright.sync_api import sync_playwright

    subset = urls[: config.max_rendered_pages]
    run.requested = len(subset)
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
                        run.status = BUDGET_EXHAUSTED
                        run.detail = (
                            f"the rendering time budget of {config.render_budget_s:.0f}s "
                            f"was reached after {len(out)} of {len(subset)} page(s)")
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
        run.status = BROWSER_UNAVAILABLE
        run.error_sample = f"{type(exc).__name__}: {exc}"
        run.detail = ("the headless browser failed to start; raw-versus-rendered "
                      "comparison was not possible")
        return run

    run.attempted = len(out)
    run.succeeded = sum(1 for r in out.values() if r.ok)
    run.failed = run.attempted - run.succeeded
    run.error_sample = next((r.error for r in out.values() if r.error), None)
    if run.status != BUDGET_EXHAUSTED:
        if run.succeeded == 0:
            run.status = ALL_FAILED
            run.detail = (f"all {run.attempted} rendering attempt(s) failed "
                          f"({run.error_sample or 'no error recorded'})")
        elif run.succeeded < run.requested:
            run.status = PARTIAL
            run.detail = (f"{run.succeeded} of {run.requested} page(s) rendered; "
                          f"{run.failed} failed")
        else:
            run.status = COMPLETE
            run.detail = f"{run.succeeded} of {run.requested} page(s) rendered"
    return run
