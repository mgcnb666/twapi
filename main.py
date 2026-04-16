"""TwAPI – Twitter API powered by Nitter instances.

Every request fetches live data from Nitter (no caching) so results
are always up-to-date.

Endpoints
---------
GET /api/user/{username}            – user profile
GET /api/user/{username}/tweets     – user timeline (supports page/count)
GET /api/tweet/{username}/status/{tweet_id} – single tweet + replies
GET /api/search                     – search tweets (supports page/count)
GET /api/health                     – instance health
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from config import settings
from models import (
    HealthResponse,
    InstanceHealth,
    SearchResponse,
    TweetDetail,
    Tweet,
    UserProfile,
    UserTweetsResponse,
)
from nitter_client import client
from parser import parse_tweet_detail, parse_tweets, parse_user_profile

# Max tweets per auto-pagination request to prevent abuse
MAX_COUNT = 500
# Nitter returns ~20 tweets per page
PAGE_SIZE = 20


async def _fetch_tweets_multi(
    path: str,
    extra_params: dict[str, str] | None,
    count: int,
) -> tuple[list[Tweet], str]:
    """Fetch up to *count* tweets by auto-paginating through Nitter pages.

    Returns (accumulated_tweets, last_cursor).
    """
    all_tweets: list[Tweet] = []
    cursor = ""
    pages_fetched = 0
    max_pages = (count + PAGE_SIZE - 1) // PAGE_SIZE  # ceil division

    while len(all_tweets) < count and pages_fetched < max_pages:
        params: dict[str, str] = dict(extra_params or {})
        if cursor:
            params["cursor"] = cursor
        html, base = await client.fetch(path, params=params or None)
        tweets, next_cursor = parse_tweets(html, base)
        if not tweets:
            break
        all_tweets.extend(tweets)
        pages_fetched += 1
        cursor = next_cursor
        if not cursor:
            break

    return all_tweets[:count], cursor


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    yield
    await client.close()


app = FastAPI(
    title="TwAPI",
    description="Twitter/X REST API powered by public Nitter instances",
    version="1.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "name": "TwAPI",
        "version": "1.1.0",
        "docs": "/docs",
        "endpoints": [
            "GET /api/user/{username}",
            "GET /api/user/{username}/tweets?page=1&count=20",
            "GET /api/tweet/{username}/status/{tweet_id}",
            "GET /api/search?q=keyword&page=1&count=20",
            "GET /api/health",
        ],
    }


@app.get("/api/user/{username}", response_model=UserProfile)
async def get_user_profile(username: str):
    """Get a Twitter user's profile information."""
    try:
        html, base = await client.fetch(f"/{username}")
        return parse_user_profile(html, base)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nitter fetch failed: {e}")


@app.get("/api/user/{username}/tweets", response_model=UserTweetsResponse)
async def get_user_tweets(
    username: str,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    count: int = Query(0, ge=0, le=MAX_COUNT, description="Total tweets to fetch (overrides page)"),
    cursor: str = Query("", description="Raw pagination cursor (advanced)"),
):
    """Get a user's tweets.

    - **page=N**: fetch page N (~20 tweets per page). Pages are auto-resolved.
    - **count=N**: fetch up to N tweets total (auto-paginates).
    - **cursor**: raw Nitter cursor for manual pagination.
    """
    try:
        # Mode 1: explicit cursor (backward compat)
        if cursor:
            html, base = await client.fetch(f"/{username}", params={"cursor": cursor})
            tweets, next_cursor = parse_tweets(html, base)
            return UserTweetsResponse(
                user=username, tweets=tweets, cursor=next_cursor,
                page=0, total_fetched=len(tweets),
            )

        # Mode 2: count – fetch up to N tweets
        if count > 0:
            tweets, last_cursor = await _fetch_tweets_multi(
                f"/{username}", None, count,
            )
            return UserTweetsResponse(
                user=username, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        # Mode 3: page number – auto-resolve cursors
        tweets, next_cursor = await _fetch_page_n(f"/{username}", None, page)
        return UserTweetsResponse(
            user=username, tweets=tweets, cursor=next_cursor,
            page=page, total_fetched=len(tweets),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nitter fetch failed: {e}")


@app.get("/api/tweet/{username}/status/{tweet_id}", response_model=TweetDetail)
async def get_tweet(username: str, tweet_id: str):
    """Get a single tweet and its replies."""
    try:
        html, base = await client.fetch(f"/{username}/status/{tweet_id}")
        main_tweet, replies = parse_tweet_detail(html, base)
        if not main_tweet:
            raise HTTPException(status_code=404, detail="Tweet not found")
        return TweetDetail(tweet=main_tweet, replies=replies)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nitter fetch failed: {e}")


@app.get("/api/search", response_model=SearchResponse)
async def search_tweets(
    q: str = Query(..., description="Search query"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    count: int = Query(0, ge=0, le=MAX_COUNT, description="Total tweets to fetch (overrides page)"),
    cursor: str = Query("", description="Raw pagination cursor (advanced)"),
):
    """Search tweets by keyword.

    - **page=N**: fetch page N of search results.
    - **count=N**: fetch up to N search results total.
    - **cursor**: raw Nitter cursor for manual pagination.
    """
    base_params: dict[str, str] = {"f": "tweets", "q": q}
    try:
        if cursor:
            params = {**base_params, "cursor": cursor}
            html, base = await client.fetch("/search", params=params)
            tweets, next_cursor = parse_tweets(html, base)
            return SearchResponse(
                query=q, tweets=tweets, cursor=next_cursor,
                page=0, total_fetched=len(tweets),
            )

        if count > 0:
            tweets, last_cursor = await _fetch_tweets_multi(
                "/search", base_params, count,
            )
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)
