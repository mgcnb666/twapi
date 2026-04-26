"""Nitter instances configuration and app settings."""

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


@dataclass
class Settings:
    port: int = 30192
    instances: list[str] = field(default_factory=lambda: list(NITTER_INSTANCES))
    request_timeout: float = 15.0
    max_retries: int = 5
    health_check_interval: int = 120  # seconds
    enable_cf_browser: bool = False   # enable Cloudflare bypass (requires Chrome + Xvfb)
    
    # === High Concurrency Settings ===
    max_concurrent_requests: int = 1000  # global semaphore limit
    instance_concurrent_limit: int = 50  # per-instance semaphore limit
    fetch_timeout: float = 10.0          # timeout for individual fetch
    circuit_breaker_failures: int = 5    # failures before marking unhealthy
    circuit_breaker_recovery: float = 30.0  # seconds before retrying unhealthy instance
    enable_parallel_pagination: bool = True  # fetch multiple pages concurrently
    max_parallel_pages: int = 5          # max pages to fetch in parallel


settings = Settings()
