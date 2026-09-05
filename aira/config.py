"""Runtime configuration for an audit run.

All operational bounds live here rather than as constants scattered through the
code, so that a caller can tighten limits without editing modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(slots=True)
class AuditConfig:
    """Bounded, read-only crawl + audit settings."""

    # --- crawl bounds -----------------------------------------------------
    max_pages: int = 20
    max_depth: int = 3
    concurrency: int = 4
    request_timeout: float = 12.0
    total_crawl_budget_s: float = 150.0
    delay_between_requests_s: float = 0.15
    max_bytes_per_page: int = 3_000_000
    max_redirects: int = 5

    # --- rendering --------------------------------------------------------
    render: bool = True
    max_rendered_pages: int = 8
    render_timeout_s: float = 15.0
    render_budget_s: float = 75.0  # wall-clock cap for the whole rendering stage

    # --- safety -----------------------------------------------------------
    respect_robots: bool = True
    same_site_only: bool = True
    allow_private_networks: bool = False  # test harness sets this True
    user_agent: str = (
        "AIRA-AIReadinessAuditBot/1.0 (+read-only website audit; respects robots.txt)"
    )
    allowed_schemes: tuple[str, ...] = ("http", "https")

    # --- analysis tuning --------------------------------------------------
    js_dependency_ratio: float = 0.35  # rendered text must exceed raw by this share
    min_raw_words_for_ratio: int = 30
    thin_content_words: int = 80
    stale_days: int = 540
    name_similarity_threshold: float = 0.72

    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
