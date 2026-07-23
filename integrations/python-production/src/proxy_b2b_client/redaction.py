"""Small, deterministic redaction helpers for user-facing output."""

from __future__ import annotations

from urllib.parse import urlsplit


def redact_url(value: str) -> str:
    """Return only the target origin plus opaque path/query markers."""

    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.hostname:
            return "<redacted-url>"
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        netloc = host
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        path = "/" if parsed.path in {"", "/"} else "/<redacted-path>"
        query = "?<redacted-query>" if parsed.query else ""
        return f"{parsed.scheme}://{netloc}{path}{query}"
    except (TypeError, ValueError):
        return "<redacted-url>"
