"""URL validation, normalization and SSRF guards.

Every network target passes through :func:`validate_target` before a request is
made. Private / loopback / link-local addresses are refused unless the config
explicitly allows them (the local test harness does).
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

from .config import AuditConfig

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid",
}

NON_PAGE_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif",
    ".css", ".js", ".mjs", ".map", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".zip", ".gz", ".tar", ".rar", ".7z", ".dmg", ".exe", ".pkg",
    ".mp4", ".mp3", ".webm", ".mov", ".avi", ".wav", ".ogg",
    ".xml", ".rss", ".atom", ".json", ".txt", ".csv", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx",
)


HOSTNAME_RE = re.compile(
    r"^(?:\d{1,3}(?:\.\d{1,3}){3}|\[[0-9a-f:]+\]|"
    r"(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?)$", re.I)


class UnsafeUrlError(ValueError):
    """Raised when a URL must not be fetched."""


@dataclass(frozen=True, slots=True)
class Target:
    url: str
    host: str
    scheme: str
    registrable_host: str


def normalize_url(url: str, base: str | None = None) -> str | None:
    """Return a canonical absolute URL, or ``None`` if not a usable page URL."""
    if not url:
        return None
    url = url.strip()
    if not url or url.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    if base:
        url = urljoin(base, url)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None
    netloc = host
    if parts.port and not (
        (parts.scheme == "http" and parts.port == 80)
        or (parts.scheme == "https" and parts.port == 443)
    ):
        netloc = f"{host}:{parts.port}"
    path = parts.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if k.lower() not in TRACKING_PARAMS]
    )
    return urlunsplit((parts.scheme, netloc, path, query, ""))


def absolutize(url: str, base: str) -> str | None:
    """Resolve a URL against *base* without the trailing-slash normalization.

    ``normalize_url`` deliberately treats ``/x`` and ``/x/`` as one URL, which is
    right for de-duplication but wrong for *following* a redirect: a server that
    redirects ``/x`` to ``/x/`` would otherwise look like it was redirecting to
    itself. Redirects are therefore followed with this function and normalized
    only for storage and comparison.
    """
    if not url:
        return None
    joined = urljoin(base, url.strip())
    parts = urlsplit(joined)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    netloc = parts.hostname.lower()
    if parts.port and not (
        (parts.scheme == "http" and parts.port == 80)
        or (parts.scheme == "https" and parts.port == 443)
    ):
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def looks_like_page(url: str) -> bool:
    """Heuristic: is this URL likely an HTML page rather than an asset?"""
    path = urlsplit(url).path.lower()
    return not path.endswith(NON_PAGE_SUFFIXES)


def registrable_host(host: str) -> str:
    """Strip a leading ``www.`` so ``www.x.com`` and ``x.com`` compare equal.

    This is intentionally simple: full public-suffix handling would add a
    dependency and a data file for negligible benefit in this audit.
    """
    host = host.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def same_site(a: str, b: str) -> bool:
    ha, hb = urlsplit(a).hostname or "", urlsplit(b).hostname or ""
    ra, rb = registrable_host(ha), registrable_host(hb)
    return ra == rb or ra.endswith("." + rb) or rb.endswith("." + ra)


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_multicast or addr.is_reserved or addr.is_unspecified
    )


def resolve_is_private(host: str) -> bool:
    """True when *host* resolves (entirely or partly) to a non-public address."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    return any(_is_private_ip(info[4][0]) for info in infos)


def validate_target(url: str, config: AuditConfig) -> Target:
    """Validate a user-supplied audit target. Raises :class:`UnsafeUrlError`."""
    raw = (url or "").strip()
    if not raw:
        raise UnsafeUrlError("empty URL")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in config.allowed_schemes:
        raise UnsafeUrlError(f"scheme not allowed: {parts.scheme!r}")
    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeUrlError("URL has no host")
    if parts.username or parts.password:
        raise UnsafeUrlError("credentials in URL are not allowed")
    if not HOSTNAME_RE.match(host):
        raise UnsafeUrlError(f"not a valid hostname: {host!r}")
    if not config.allow_private_networks and resolve_is_private(host):
        raise UnsafeUrlError(
            f"refusing to audit non-public address for host {host!r}"
        )
    normalized = normalize_url(raw)
    if normalized is None:
        raise UnsafeUrlError("URL could not be normalized")
    return Target(
        url=normalized,
        host=host,
        scheme=parts.scheme,
        registrable_host=registrable_host(host),
    )


def path_depth(url: str) -> int:
    """Number of path segments (homepage = 0)."""
    path = urlsplit(url).path.strip("/")
    return 0 if not path else len(path.split("/"))
