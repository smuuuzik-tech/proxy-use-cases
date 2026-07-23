from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit


_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")
_EMBEDDED_HTTP_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_SECRET_FIELDS = re.compile(
    r"(?i)\b(password|passwd|token|access[_-]?token|client[_-]?secret|"
    r"api[_-]?key|authorization)\b(\s*[:=]\s*)(?:bearer\s+|basic\s+)?([^\s,;&]+)"
)


def redact_url(value: str) -> str:
    """Return a URL that is safe to include in reports and logs."""
    try:
        parts = urlsplit(value)
        if not parts.scheme or not parts.hostname:
            return redact_text(value)
        hostname = parts.hostname
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        port = f":{parts.port}" if parts.port else ""
        credentials = "***:***@" if parts.username is not None else ""
        path = "/" if parts.path in {"", "/"} else "/<redacted-path>"
        query = "?<redacted-query>" if parts.query else ""
        return f"{parts.scheme}://{credentials}{hostname}{port}{path}{query}"
    except (TypeError, ValueError):
        return "<redacted-url>"


def redact_text(value: object, secrets: tuple[str, ...] = ()) -> str:
    text = str(value)
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        text = text.replace(secret, "***")
    text = _URL_CREDENTIALS.sub(lambda match: f"{match.group('scheme')}***:***@", text)
    text = _SECRET_FIELDS.sub(lambda match: f"{match.group(1)}{match.group(2)}***", text)
    text = _EMBEDDED_HTTP_URL.sub(lambda match: redact_url(match.group(0)), text)
    return text


def proxy_secrets(proxy_url: str) -> tuple[str, ...]:
    try:
        parts = urlsplit(proxy_url)
        username = parts.username or ""
        password = parts.password or ""
        encoded_username = quote(username, safe="") if username else ""
        encoded_password = quote(password, safe="") if password else ""
        decoded_username = unquote(username) if username else ""
        decoded_password = unquote(password) if password else ""
        return tuple(
            item
            for item in (
                proxy_url,
                username,
                password,
                encoded_username,
                encoded_password,
                decoded_username,
                decoded_password,
            )
            if item
        )
    except (TypeError, ValueError):
        return (proxy_url,) if proxy_url else ()
