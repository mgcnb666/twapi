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


settings = Settings()
