"""Provider-neutral HTTP client for proxy-backed B2B workloads."""

from .client import B2BHttpClient, RequestResult
from .config import ClientSettings, ConfigError
from .execution import (
    ExecutionContract,
    ExecutionCost,
    ExecutionQuality,
    ExecutionRoute,
)

ProxyClient = B2BHttpClient

__all__ = [
    "B2BHttpClient",
    "ClientSettings",
    "ConfigError",
    "ExecutionContract",
    "ExecutionCost",
    "ExecutionQuality",
    "ExecutionRoute",
    "ProxyClient",
    "RequestResult",
]
__version__ = "0.3.0"
