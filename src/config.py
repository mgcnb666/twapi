"""Nitter instances configuration and app settings."""

import os
from dataclasses import dataclass, field


# Public Nitter instances (online & working as of wiki)
NITTER_INSTANCES = [
    "https://xcancel.com",
    "https://nitter.poast.org",
    "https://nitter.privacyredirect.com",
    "https://lightbrd.com",
    "https://nitter.space",
    "https://nitter.tiekoetter.com",
    "https://nuku.trabun.org",
    "https://nitter.catsarch.com",
]


def _env_list(key: str, default: list[str]) -> list[str]:
    """Parse comma-separated env var as list."""
    val = os.getenv(key)
    return [v.strip() for v in val.split(",") if v.strip()] if val else default


def _env_int(key: str, default: int) -> int:
    """Parse env var as int with fallback."""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float) -> float:
    """Parse env var as float with fallback."""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    """Parse env var as bool with fallback."""
    val = os.getenv(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    port: int = field(default_factory=lambda: _env_int("TWAPI_PORT", 30192))
    instances: list[str] = field(default_factory=lambda: _env_list("TWAPI_INSTANCES", list(NITTER_INSTANCES)))
    request_timeout: float = field(default_factory=lambda: _env_float("TWAPI_REQUEST_TIMEOUT", 15.0))
    max_retries: int = field(default_factory=lambda: _env_int("TWAPI_MAX_RETRIES", 5))
    health_check_interval: int = field(default_factory=lambda: _env_int("TWAPI_HEALTH_CHECK_INTERVAL", 120))
    enable_cf_browser: bool = field(default_factory=lambda: _env_bool("TWAPI_ENABLE_CF_BROWSER", False))
    
    # === High Concurrency Settings ===
    max_concurrent_requests: int = field(default_factory=lambda: _env_int("TWAPI_MAX_CONCURRENT", 1000))
    instance_concurrent_limit: int = field(default_factory=lambda: _env_int("TWAPI_INSTANCE_CONCURRENT", 50))
    fetch_timeout: float = field(default_factory=lambda: _env_float("TWAPI_FETCH_TIMEOUT", 10.0))
    circuit_breaker_failures: int = field(default_factory=lambda: _env_int("TWAPI_CB_FAILURES", 5))
    circuit_breaker_recovery: float = field(default_factory=lambda: _env_float("TWAPI_CB_RECOVERY", 30.0))
    enable_parallel_pagination: bool = field(default_factory=lambda: _env_bool("TWAPI_PARALLEL_PAGES", True))
    max_parallel_pages: int = field(default_factory=lambda: _env_int("TWAPI_MAX_PARALLEL_PAGES", 5))


settings = Settings()
