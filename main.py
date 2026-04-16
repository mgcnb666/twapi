"""TwAPI – Twitter API powered by Nitter instances.

Every request fetches live data from Nitter (no caching) so results
are always up-to-date.

Endpoints
---------
GET /api/user/{username}              – user profile
GET /api/user/{username}/tweets       – user timeline
GET /api/user/{username}/likes        – user liked tweets
GET /api/user/{username}/retweets     – user retweets only
GET /api/tweet/{username}/status/{id} – single tweet + replies
GET /api/search?q=keyword             – search tweets
GET /api/health                       – instance health
"""

from __future__ import annotations

import math
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from config import settings
from models import (
    HealthResponse,
    InstanceHealth,
    SearchResponse,
    TweetDetail,
    Tweet,
    UserLikesResponse,
    UserProfile,
    UserRetweetsResponse,
    UserTweetsResponse,
)
from nitter_client import client
from parser import parse_tweet_detail, parse_tweets, parse_user_profile

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
    await client.start()
    yield
    await client.close()


app = FastAPI(
    title="TwAPI",
    description="Twitter/X REST API powered by public Nitter instances",
    version="1.2.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "name": "TwAPI",
        "version": "1.2.0",
        "docs": "/docs",
        "endpoints": [
            "GET /api/user/{username}",
            "GET /api/user/{username}/tweets?page=1&count=20&all=false",
            "GET /api/user/{username}/likes?page=1&count=20&all=false",
            "GET /api/user/{username}/retweets?page=1&count=20&all=false",
            "GET /api/tweet/{username}/status/{tweet_id}",
            "GET /api/search?q=keyword&page=1&count=20&all=false",
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
        raise HTTPException(status_code=502, detail=f"Nitter fetch failed: {e}")


@app.get("/api/user/{username}/likes", response_model=UserLikesResponse)
async def get_user_likes(
    username: str,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    count: int = Query(0, ge=0, le=DEFAULT_MAX_COUNT, description="Total liked tweets to fetch"),
    cursor: str = Query("", description="Raw pagination cursor"),
    all: bool = Query(False, description="Fetch ALL liked tweets"),
):
    """Get tweets liked by a user (from Nitter favorites page).

    Supports the same pagination modes as /tweets.
    """
    path = f"/{username}/favorites"
    try:
        if all:
            tweets, last_cursor = await _fetch_all_tweets(path, None)
            return UserLikesResponse(
                user=username, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        if cursor:
            html, base = await client.fetch(path, params={"cursor": cursor})
            tweets, next_cursor = parse_tweets(html, base)
            return UserLikesResponse(
                user=username, tweets=tweets, cursor=next_cursor,
                page=0, total_fetched=len(tweets),
            )

        if count > 0:
            tweets, last_cursor = await _fetch_tweets_multi(path, None, count)
            return UserLikesResponse(
                user=username, tweets=tweets, cursor=last_cursor,
                page=0, total_fetched=len(tweets),
            )

        tweets, next_cursor = await _fetch_page_n(path, None, page)
        return UserLikesResponse(
            user=username, tweets=tweets, cursor=next_cursor,
            page=page, total_fetched=len(tweets),
        )
    except HTTPException:
        raise
    except Exception as e:
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

    uvicorn.run("main:app", host="0.0.0.0", port=settings.port)
