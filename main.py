"""TwAPI – Twitter API powered by Nitter instances.

Every request fetches live data from Nitter (no caching) so results
are always up-to-date.

Endpoints
---------
GET /api/user/{username}            – user profile
GET /api/user/{username}/tweets     – user timeline
GET /api/tweet/{username}/status/{tweet_id} – single tweet + replies
GET /api/search                     – search tweets
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
    UserProfile,
    UserTweetsResponse,
)
from nitter_client import client
from parser import parse_tweet_detail, parse_tweets, parse_user_profile


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    yield
    await client.close()


app = FastAPI(
    title="TwAPI",
    description="Twitter/X REST API powered by public Nitter instances",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "name": "TwAPI",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": [
            "GET /api/user/{username}",
            "GET /api/user/{username}/tweets",
            "GET /api/tweet/{username}/status/{tweet_id}",
            "GET /api/search?q=keyword",
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
    cursor: str = Query("", description="Pagination cursor"),
):
    """Get a user's tweets (timeline)."""
    params = {}
    if cursor:
        params["cursor"] = cursor
    try:
        html, base = await client.fetch(f"/{username}", params=params)
        tweets, next_cursor = parse_tweets(html, base)
        return UserTweetsResponse(user=username, tweets=tweets, cursor=next_cursor)
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
    cursor: str = Query("", description="Pagination cursor"),
):
    """Search tweets by keyword."""
    params: dict[str, str] = {"f": "tweets", "q": q}
    if cursor:
        params["cursor"] = cursor
    try:
        html, base = await client.fetch("/search", params=params)
        tweets, next_cursor = parse_tweets(html, base)
        return SearchResponse(query=q, tweets=tweets, cursor=next_cursor)
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
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)
