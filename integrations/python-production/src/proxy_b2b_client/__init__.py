"""Provider-neutral HTTP client for proxy-backed B2B workloads."""

from .client import B2BHttpClient, RequestResult
from .config import ClientSettings, ConfigError

__all__ = ["B2BHttpClient", "ClientSettings", "ConfigError", "RequestResult"]
__version__ = "0.1.0"
