from __future__ import annotations

import asyncio
import logging
import logging.handlers
import math
import os
import re
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from config import settings
from models import (
    HealthResponse,
    InstanceHealth,
    SearchResponse,
    TweetDetail,
    Tweet,
    UserProfile,
    UserRetweetsResponse,
    UserSearchResponse,
    UserTweetsResponse,
)
from nitter_client import client
from parser import parse_tweet_detail, parse_tweets, parse_user_profile, parse_user_search
from stats import stats_tracker, StatsMiddleware

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

def _setup_logging() -> None:
    """Configure 'twapi' logger with console + rotating file handlers."""
    twapi_log = logging.getLogger("twapi")
    if twapi_log.handlers:
        return
    twapi_log.setLevel(logging.DEBUG)
    twapi_log.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    twapi_log.addHandler(console)

    all_handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "twapi.log"), maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding="utf-8",
    )
    all_handler.setLevel(logging.DEBUG)
    all_handler.setFormatter(fmt)
    twapi_log.addHandler(all_handler)

    err_handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "error.log"), maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding="utf-8",
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(fmt)
    twapi_log.addHandler(err_handler)

_setup_logging()
log = logging.getLogger("twapi.main")

# Nitter returns ~20 tweets per page
PAGE_SIZE = 20
# Default per-request limit
DEFAULT_MAX_COUNT = 500
# Safety cap when all=true
ALL_TWEETS_CAP = 10000


def _effective_max_pages(count: int) -> int:
    return math.ceil(count / PAGE_SIZE)


# ---------------------------------------------------------------------------
# URL-safe helpers (fix path-traversal / SSRF)
# ---------------------------------------------------------------------------

def _safe_username(value: str) -> str:
    """Strip path separators and encode remaining chars."""
    cleaned = value.replace("/", "").replace("\\", "").replace("\x00", "")
    cleaned = cleaned.lstrip("@")
    return quote(cleaned, safe="")


def _safe_tweet_id(value: str) -> str:
    """Same treatment for tweet IDs."""
    cleaned = value.replace("/", "").replace("\\", "").replace("\x00", "")
    return quote(cleaned, safe="")


def _safe_cursor(value: str) -> str:
    """Cursor is usually base64-ish; still sanitise separators."""
    return value.replace("/", "").replace("\\", "").replace("\x00", "")


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

_TWITTER_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_TWITTER_TWEET_ID_RE = re.compile(r"^\d{10,20}$")


def _validate_username(value: str) -> str:
    """Validate Twitter username format."""
    cleaned = value.lstrip("@")
    if not _TWITTER_USERNAME_RE.match(cleaned):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid username format: '{value}'. Must be 1-15 alphanumeric chars or underscores.",
        )
    return cleaned


def _validate_tweet_id(value: str) -> str:
    """Validate tweet ID format."""
    if not _TWITTER_TWEET_ID_RE.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tweet ID format: '{value}'. Must be 10-20 digits.",
        )
    return value


# ---------------------------------------------------------------------------
# High-concurrency pagination helpers
# ---------------------------------------------------------------------------

async def _fetch_tweets_multi(
    path: str,
    extra_params: dict[str, str] | None,
    count: int,
    *,
    filter_retweets: bool = False,
) -> tuple[list[Tweet], str]:
    """Fetch up to *count* tweets with parallel page fetching."""
    all_tweets: list[Tweet] = []
    cursor = ""
    pages_fetched = 0
    max_pages = _effective_max_pages(count)

    if settings.enable_parallel_pagination and max_pages > 1:
        batch_size = min(settings.max_parallel_pages, max_pages)
        requests = []
        for i in range(batch_size):
            params: dict[str, str] = dict(extra_params or {})
            if i > 0 and cursor:
                params["cursor"] = cursor
            requests.append((path, params or None))

        results = await client.fetch_parallel(requests)
        for html, base in results:
            if html is None:
                continue
            tweets, next_cursor = parse_tweets(html, base)
            if not tweets:
                continue
            if filter_retweets:
                tweets = [t for t in tweets if t.is_retweet]
            all_tweets.extend(tweets)
            cursor = next_cursor
            pages_fetched += 1
            if not cursor:
                break

    while len(all_tweets) < count and pages_fetched < max_pages:
        params = dict(extra_params or {})
        if cursor:
            params["cursor"] = cursor
        html, base = await client.fetch(path, params=params or None)
        tweets, next_cursor = parse_tweets(html, base)
        if not tweets:
            break
        if filter_retweets:
            tweets = [t for t in tweets if t.is_retweet]
        all_tweets.extend(tweets)
        pages_fetched += 1
        cursor = next_cursor
        if not cursor:
            break

    return all_tweets[:count], cursor


async def _fetch_all_tweets(
    path: str,
    extra_params: dict[str, str] | None,
    *,
    filter_retweets: bool = False,
) -> tuple[list[Tweet], str]:
    """Fetch ALL available tweets with parallel pagination."""
    all_tweets: list[Tweet] = []
    cursor = ""
    pages_fetched = 0
    cap_pages = _effective_max_pages(ALL_TWEETS_CAP)

    while pages_fetched < cap_pages:
        batch_size = min(settings.max_parallel_pages, cap_pages - pages_fetched)
        requests = []
        for i in range(batch_size):
            params: dict[str, str] = dict(extra_params or {})
            if i == 0 and cursor:
                params["cursor"] = cursor
            elif i > 0:
                break
            requests.append((path, params or None))

        if len(requests) == 1:
            html, base = await client.fetch(path, params=requests[0][1])
            tweets, next_cursor = parse_tweets(html, base)
            if not tweets:
                break
            if filter_retweets:
                tweets = [t for t in tweets if t.is_retweet]
            all_tweets.extend(tweets)
            pages_fetched += 1
            cursor = next_cursor
            if not cursor:
                break
        else:
            results = await client.fetch_parallel(requests)
            for html, base in results:
                if html is None:
                    continue
                tweets, next_cursor = parse_tweets(html, base)
                if not tweets:
                    continue
                if filter_retweets:
                    tweets = [t for t in tweets if t.is_retweet]
                all_tweets.extend(tweets)
                pages_fetched += 1
                cursor = next_cursor

    return all_tweets, cursor


async def _fetch_page_n(
    path: str,
    extra_params: dict[str, str] | None,
    page: int,
) -> tuple[list[Tweet], str]:
    """Fetch page *page* (1-based) by auto-resolving cursors."""
    cursor = ""
    tweets: list[Tweet] = []
    for current in range(1, page + 1):
        params: dict[str, str] = dict(extra_params or {})
        if cursor:
            params["cursor"] = cursor
        html, base = await client.fetch(path, params=params or None)
        page_tweets, next_cursor = parse_tweets(html, base)
        if current == page:
            tweets = page_tweets
        cursor = next_cursor
        if not cursor:
            break
    return tweets, cursor


async def _fetch_users_multi(
    base_params: dict[str, str],
    count: int,
) -> tuple[list, str]:
    """Fetch multiple user search result pages."""
    all_users = []
    cursor = ""
    pages_fetched = 0
    max_pages = _effective_max_pages(count)

    while len(all_users) < count and pages_fetched < max_pages:
        params = dict(base_params)
        if cursor:
            params["cursor"] = cursor
        html, base = await client.fetch("/search", params=params)
        users, next_cursor = parse_user_search(html, base)
        if not users:
            break
        all_users.extend(users)
        pages_fetched += 1
        cursor = next_cursor
        if not cursor:
            break

    return all_users[:count], cursor


async def _fetch_users_page_n(
    base_params: dict[str, str],
    page: int,
) -> tuple[list, str]:
    """Fetch page N of user search results."""
    cursor = ""
    users = []
    for current in range(1, page + 1):
        params = dict(base_params)
        if cursor:
            params["cursor"] = cursor
        html, base = await client.fetch("/search", params=params)
        page_users, next_cursor = parse_user_search(html, base)
        if current == page:
            users = page_users
        cursor = next_cursor
        if not cursor:
            break
    return users, cursor


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("TwAPI v2.0.0 (High-Concurrency) starting on port %d", settings.port)
    stats_tracker.init_db()
    await client.start()
    log.info("Startup complete — Nitter client ready with %d instances", len(settings.instances))
    yield
    log.info("Shutting down")
    await client.close()


app = FastAPI(
    title="TwAPI",
    description="High-Concurrency Twitter/X REST API powered by public Nitter instances",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(StatsMiddleware)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "name": "TwAPI",
        "version": "2.0.0",
        "docs": "/docs",
        "dashboard": "/dashboard",
        "features": [
            "high-concurrency",
            "connection-pooling",
            "circuit-breaker",
            "parallel-pagination",
        ],
        "endpoints": [
            "GET /api/user/{username}",
            "GET /api/user/{username}/tweets?page=1&count=20&all=false",
            "GET /api/user/{username}/retweets?page=1&count=20&all=false",
            "GET /api/tweet/{username}/status/{tweet_id}",
            "GET /api/search?q=keyword&page=1&count=20&all=false",
            "GET /api/search/users?q=keyword&page=1&count=20",
            "GET /api/health",
            "GET /api/stats",
            "GET /dashboard",
        ],
    }


@app.get("/api/user/{username}", response_model=UserProfile)
async def get_user_profile(username: str):
    """Get a Twitter user's profile information."""
    validated = _validate_username(username)
    safe = _safe_username(validated)
    try:
        html, base = await client.fetch(f"/{safe}")
        return parse_user_profile(html, base)
    except ValueError as e:
        log.warning("Profile not found for %s: %s", username, e)
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("Failed to fetch profile for %s: %s", username, e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Nitter fetch failed: {e}")


@app.get("/api/user/{username}/tweets", response_model=UserTweetsResponse)
async def get_user_tweets(
    username: str,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    count: int = Query(0, ge=0, le=DEFAULT_MAX_COUNT, description="Total tweets to fetch (overrides page)"),
    cursor: str = Query("", description="Raw pagination cursor (advanced)"),
    all: bool = Query(False, description="Fetch ALL tweets (ignores page/count limits)"),
):
    """Get a user's tweets with high-concurrency pagination."""
    validated = _validate_username(username)
    safe_user = _safe_username(validated)
    safe_cursor = _safe_cursor(cursor)
    try:
        if all:
            tweets, last_cursor = await _fetch_all_tweets(f"/{safe_user}", None)
            return UserTweetsResponse(
                user=username, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        if safe_cursor:
            html, base = await client.fetch(f"/{safe_user}", params={"cursor": safe_cursor})
            tweets, next_cursor = parse_tweets(html, base)
            return UserTweetsResponse(
                user=username, tweets=tweets, cursor=next_cursor,
                page=0, total_fetched=len(tweets),
            )

        if count > 0:
            tweets, last_cursor = await _fetch_tweets_multi(f"/{safe_user}", None, count)
            return UserTweetsResponse(
                user=username, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        tweets, next_cursor = await _fetch_page_n(f"/{safe_user}", None, page)
        return UserTweetsResponse(
            user=username, tweets=tweets, cursor=next_cursor,
            page=page, total_fetched=len(tweets),
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to fetch tweets for %s: %s", username, e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Nitter fetch failed: {e}")


@app.get("/api/user/{username}/retweets", response_model=UserRetweetsResponse)
async def get_user_retweets(
    username: str,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    count: int = Query(0, ge=0, le=DEFAULT_MAX_COUNT, description="Total retweets to fetch"),
    cursor: str = Query("", description="Raw pagination cursor"),
    all: bool = Query(False, description="Fetch ALL retweets"),
):
    """Get a user's retweets (filtered from timeline)."""
    validated = _validate_username(username)
    safe_user = _safe_username(validated)
    safe_cursor = _safe_cursor(cursor)
    try:
        if all:
            tweets, last_cursor = await _fetch_all_tweets(
                f"/{safe_user}", None, filter_retweets=True,
            )
            return UserRetweetsResponse(
                user=username, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        if safe_cursor:
            html, base = await client.fetch(f"/{safe_user}", params={"cursor": safe_cursor})
            tweets, next_cursor = parse_tweets(html, base)
            tweets = [t for t in tweets if t.is_retweet]
            return UserRetweetsResponse(
                user=username, tweets=tweets, cursor=next_cursor,
                page=0, total_fetched=len(tweets),
            )

        if count > 0:
            tweets, last_cursor = await _fetch_tweets_multi(
                f"/{safe_user}", None, count, filter_retweets=True,
            )
            return UserRetweetsResponse(
                user=username, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        tweets, next_cursor = await _fetch_page_n(f"/{safe_user}", None, page)
        tweets = [t for t in tweets if t.is_retweet]
        return UserRetweetsResponse(
            user=username, tweets=tweets, cursor=next_cursor,
            page=page, total_fetched=len(tweets),
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to fetch retweets for %s: %s", username, e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Nitter fetch failed: {e}")


@app.get("/api/tweet/{username}/status/{tweet_id}", response_model=TweetDetail)
async def get_tweet(username: str, tweet_id: str):
    """Get a single tweet and its replies."""
    validated_user = _validate_username(username)
    validated_id = _validate_tweet_id(tweet_id)
    safe_user = _safe_username(validated_user)
    safe_id = _safe_tweet_id(validated_id)
    try:
        html, base = await client.fetch(f"/{safe_user}/status/{safe_id}")
        main_tweet, replies = parse_tweet_detail(html, base)
        if not main_tweet:
            log.warning("Tweet not found: %s/status/%s", username, tweet_id)
            raise HTTPException(status_code=404, detail="Tweet not found")
        return TweetDetail(tweet=main_tweet, replies=replies)
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to fetch tweet %s/status/%s: %s", username, tweet_id, e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Nitter fetch failed: {e}")


@app.get("/api/search", response_model=SearchResponse)
async def search_tweets(
    q: str = Query(..., description="Search query"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    count: int = Query(0, ge=0, le=DEFAULT_MAX_COUNT, description="Total tweets to fetch (overrides page)"),
    cursor: str = Query("", description="Raw pagination cursor (advanced)"),
    all: bool = Query(False, description="Fetch ALL search results"),
):
    """Search tweets by keyword with high-concurrency pagination."""
    safe_cursor = _safe_cursor(cursor)
    base_params: dict[str, str] = {"f": "tweets", "q": q}
    try:
        if all:
            tweets, last_cursor = await _fetch_all_tweets("/search", base_params)
            return SearchResponse(
                query=q, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        if safe_cursor:
            params = {**base_params, "cursor": safe_cursor}
            html, base = await client.fetch("/search", params=params)
            tweets, next_cursor = parse_tweets(html, base)
            return SearchResponse(
                query=q, tweets=tweets, cursor=next_cursor,
                page=0, total_fetched=len(tweets),
            )

        if count > 0:
            tweets, last_cursor = await _fetch_tweets_multi("/search", base_params, count)
            return SearchResponse(
                query=q, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        tweets, next_cursor = await _fetch_page_n("/search", base_params, page)
        return SearchResponse(
            query=q, tweets=tweets, cursor=next_cursor,
            page=page, total_fetched=len(tweets),
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error("Search failed for q=%s: %s", q, e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Nitter fetch failed: {e}")


@app.get("/api/search/users", response_model=UserSearchResponse)
async def search_users(
    q: str = Query(..., description="Search query"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    count: int = Query(0, ge=0, le=DEFAULT_MAX_COUNT, description="Total users to fetch"),
    cursor: str = Query("", description="Raw pagination cursor"),
):
    """Search Twitter users by keyword."""
    safe_cursor = _safe_cursor(cursor)
    base_params: dict[str, str] = {"f": "users", "q": q}
    try:
        if safe_cursor:
            params = {**base_params, "cursor": safe_cursor}
            html, base = await client.fetch("/search", params=params)
            users, next_cursor = parse_user_search(html, base)
            return UserSearchResponse(
                query=q, users=users, cursor=next_cursor,
                page=0, total_fetched=len(users),
            )

        if count > 0:
            users, last_cursor = await _fetch_users_multi(base_params, count)
            return UserSearchResponse(
                query=q, users=users, cursor=last_cursor,
                page=0, total_fetched=len(users),
            )

        users, next_cursor = await _fetch_users_page_n(base_params, page)
        return UserSearchResponse(
            query=q, users=users, cursor=next_cursor,
            page=page, total_fetched=len(users),
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error("User search failed for q=%s: %s", q, e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Nitter fetch failed: {e}")


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Check health of all configured Nitter instances."""
    status = await client.check_health()
    instances = [
        InstanceHealth(url=url, healthy=lat >= 0, latency_ms=round(lat, 1))
        for url, lat in status.items()
    ]
    active = sum(1 for i in instances if i.healthy)
    return HealthResponse(
        instances=instances,
        active_count=active,
        total_count=len(instances),
    )


@app.get("/api/stats")
async def get_stats(
    hours: int = Query(24, ge=1, le=720, description="Hours of history to include"),
):
    """Get API call statistics as JSON."""
    return stats_tracker.get_summary(hours=hours)


@app.get("/api/stats/recent")
async def get_recent_calls(
    limit: int = Query(50, ge=1, le=500, description="Number of recent calls"),
):
    """Get recent API call log."""
    return stats_tracker.get_recent(limit=limit)


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    """API statistics dashboard."""
    from dashboard import DASHBOARD_HTML
    return DASHBOARD_HTML


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("TWAPI_HOST", "0.0.0.0")
    port = int(os.getenv("TWAPI_PORT", str(settings.port)))
    workers = int(os.getenv("TWAPI_WORKERS", "1"))
    uvicorn.run("main:app", host=host, port=port, workers=workers)
