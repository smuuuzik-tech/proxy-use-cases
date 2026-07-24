"""Provider-neutral HTTP client for proxy-backed B2B workloads."""

from .client import B2BHttpClient, RequestResult
from .config import ClientSettings, ConfigError

ProxyClient = B2BHttpClient

__all__ = [
    "B2BHttpClient",
    "ClientSettings",
    "ConfigError",
    "ProxyClient",
    "RequestResult",
]
__version__ = "0.1.0"
