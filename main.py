"""TwAPI – Twitter API powered by Nitter instances.

Every request fetches live data from Nitter (no caching) so results
are always up-to-date.

Endpoints
---------
GET /api/user/{username}              – user profile
GET /api/user/{username}/tweets       – user timeline
GET /api/user/{username}/retweets     – user retweets only
GET /api/tweet/{username}/status/{id} – single tweet + replies
GET /api/search?q=keyword             – search tweets
GET /api/search/users?q=keyword       – search users
GET /api/health                       – instance health
GET /dashboard                        – API statistics dashboard
"""

from __future__ import annotations

import logging
import logging.handlers
import math
import os
from contextlib import asynccontextmanager

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
        return  # already configured (uvicorn reloads the module)
    twapi_log.setLevel(logging.DEBUG)
    twapi_log.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    twapi_log.addHandler(console)

    # Rotating file handler – all levels
    all_handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "twapi.log"), maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding="utf-8",
    )
    all_handler.setLevel(logging.DEBUG)
    all_handler.setFormatter(fmt)
    twapi_log.addHandler(all_handler)

    # Error-only file handler for quick diagnosis
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


async def _fetch_tweets_multi(
    path: str,
    extra_params: dict[str, str] | None,
    count: int,
    *,
    filter_retweets: bool = False,
) -> tuple[list[Tweet], str]:
    """Fetch up to *count* tweets by auto-paginating through Nitter pages.

    If *filter_retweets* is True, only keep tweets where is_retweet=True.
    Returns (accumulated_tweets, last_cursor).
    """
    all_tweets: list[Tweet] = []
    cursor = ""
    pages_fetched = 0
    max_pages = _effective_max_pages(count)

    while len(all_tweets) < count and pages_fetched < max_pages:
        params: dict[str, str] = dict(extra_params or {})
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
    """Fetch ALL available tweets (up to safety cap)."""
    all_tweets: list[Tweet] = []
    cursor = ""
    pages_fetched = 0
    cap_pages = _effective_max_pages(ALL_TWEETS_CAP)

    while pages_fetched < cap_pages:
        params: dict[str, str] = dict(extra_params or {})
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

    return all_tweets, cursor


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("TwAPI v1.4.0 starting on port %d", settings.port)
    stats_tracker.init_db()
    await client.start()
    log.info("Startup complete — Nitter client ready")
    yield
    log.info("Shutting down")
    await client.close()


app = FastAPI(
    title="TwAPI",
    description="Twitter/X REST API powered by public Nitter instances",
    version="1.4.0",
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
        "version": "1.4.0",
        "docs": "/docs",
        "dashboard": "/dashboard",
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
    try:
        html, base = await client.fetch(f"/{username}")
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
    """Get a user's tweets.

    - **page=N**: fetch page N (~20 tweets per page).
    - **count=N**: fetch up to N tweets total (max 500).
    - **all=true**: fetch ALL available tweets (auto-paginate until end).
    - **cursor**: raw Nitter cursor for manual pagination.
    """
    try:
        if all:
            tweets, last_cursor = await _fetch_all_tweets(f"/{username}", None)
            return UserTweetsResponse(
                user=username, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        if cursor:
            html, base = await client.fetch(f"/{username}", params={"cursor": cursor})
            tweets, next_cursor = parse_tweets(html, base)
            return UserTweetsResponse(
                user=username, tweets=tweets, cursor=next_cursor,
                page=0, total_fetched=len(tweets),
            )

        if count > 0:
            tweets, last_cursor = await _fetch_tweets_multi(f"/{username}", None, count)
            return UserTweetsResponse(
                user=username, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        tweets, next_cursor = await _fetch_page_n(f"/{username}", None, page)
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
    """Get a user's retweets (filtered from timeline).

    Fetches the user timeline and returns only retweeted posts.
    Supports the same pagination modes as /tweets.
    """
    try:
        if all:
            tweets, last_cursor = await _fetch_all_tweets(
                f"/{username}", None, filter_retweets=True,
            )
            return UserRetweetsResponse(
                user=username, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        if cursor:
            html, base = await client.fetch(f"/{username}", params={"cursor": cursor})
            tweets, next_cursor = parse_tweets(html, base)
            tweets = [t for t in tweets if t.is_retweet]
            return UserRetweetsResponse(
                user=username, tweets=tweets, cursor=next_cursor,
                page=0, total_fetched=len(tweets),
            )

        if count > 0:
            tweets, last_cursor = await _fetch_tweets_multi(
                f"/{username}", None, count, filter_retweets=True,
            )
            return UserRetweetsResponse(
                user=username, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        tweets, next_cursor = await _fetch_page_n(f"/{username}", None, page)
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
    try:
        html, base = await client.fetch(f"/{username}/status/{tweet_id}")
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
    """Search tweets by keyword.

    - **page=N**: fetch page N of search results.
    - **count=N**: fetch up to N search results total (max 500).
    - **all=true**: fetch ALL available results (auto-paginate until end).
    - **cursor**: raw Nitter cursor for manual pagination.
    """
    base_params: dict[str, str] = {"f": "tweets", "q": q}
    try:
        if all:
            tweets, last_cursor = await _fetch_all_tweets("/search", base_params)
            return SearchResponse(
                query=q, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        if cursor:
            params = {**base_params, "cursor": cursor}
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
    """Search Twitter users by keyword.

    - **page=N**: fetch page N of user results (~20 per page).
    - **count=N**: fetch up to N users total (max 500).
    - **cursor**: raw Nitter cursor for manual pagination.
    """
    base_params: dict[str, str] = {"f": "users", "q": q}
    try:
        if cursor:
            params = {**base_params, "cursor": cursor}
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


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """API statistics dashboard."""
    from dashboard import DASHBOARD_HTML
    return DASHBOARD_HTML


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_page_n(
    path: str,
    extra_params: dict[str, str] | None,
    page: int,
) -> tuple[list[Tweet], str]:
    """Fetch page *page* (1-based) by auto-resolving cursors for preceding pages."""
    cursor = ""
    tweets: list[Tweet] = []
    for current in range(1, page + 1):
        params: dict[str, str] = dict(extra_params or {})
        if cursor:
            params["cursor"] = cursor
        html, base = await client.fetch(path, params=params or None)
        tweets, next_cursor = parse_tweets(html, base)
        cursor = next_cursor
        if not cursor and current < page:
            break  # no more pages available
    return tweets, cursor


async def _fetch_users_page_n(
    base_params: dict[str, str],
    page: int,
) -> tuple[list, str]:
    """Fetch page N of user search results."""
    from models import UserSearchResult
    cursor = ""
    users: list[UserSearchResult] = []
    for current in range(1, page + 1):
        params = dict(base_params)
        if cursor:
            params["cursor"] = cursor
        html, base = await client.fetch("/search", params=params)
        users, next_cursor = parse_user_search(html, base)
        cursor = next_cursor
        if not cursor and current < page:
            break
    return users, cursor


async def _fetch_users_multi(
    base_params: dict[str, str],
    count: int,
) -> tuple[list, str]:
    """Fetch up to *count* users by auto-paginating."""
    from models import UserSearchResult
    all_users: list[UserSearchResult] = []
    cursor = ""
    max_pages = _effective_max_pages(count)
    pages_fetched = 0
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=settings.port)
