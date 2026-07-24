from __future__ import annotations

import re
from urllib.parse import urlsplit


_CREDENTIAL_URL = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@",
    re.IGNORECASE,
)
_PASSWORD = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)\s*([=:])\s*[^\s,;]+"
)


def redact_text(value: object, limit: int = 1200) -> str:
    text = str(value)
    text = _CREDENTIAL_URL.sub(r"\g<scheme>***:***@", text)
    text = _PASSWORD.sub(r"\1\2***", text)
    return text[:limit]


def safe_proxy(value: str) -> dict[str, object]:
    parsed = urlsplit(value)
    return {
        "scheme": parsed.scheme.lower(),
        "host": parsed.hostname or "",
        "port": parsed.port,
        "authentication": "configured" if parsed.username else "separate_or_none",
    }


def safe_target(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme.lower()}://{host}{port}/"
