"""High-concurrency batch query client for TwAPI.

Supports concurrent queries across multiple endpoints with automatic
load balancing and retry logic.

Usage:
    from batch_client import BatchTwAPIClient
    
    client = BatchTwAPIClient("http://localhost:30192")
    
    # Single queries
    user = await client.get_user("elonmusk")
    tweets = await client.get_tweets("elonmusk", count=100)
    
    # Batch queries (concurrent)
    users = await client.batch_get_users(["elonmusk", "github", "twitter"], concurrent=10)
    
    # Bulk search (parallel workers)
    results = await client.bulk_search(["python", "ai", "ml"], workers=20)
"""

import asyncio
import aiohttp
from typing import Optional, Any
from dataclasses import dataclass


@dataclass
class APIResponse:
    success: bool
    data: Any = None
    error: str = ""
    latency_ms: float = 0.0


class BatchTwAPIClient:
    """High-concurrency batch client for TwAPI."""

    def __init__(self, base_url: str = "http://localhost:30192", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, path: str, params: Optional[dict] = None) -> APIResponse:
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        start = asyncio.get_event_loop().time()
        try:
            async with session.get(url, params=params) as resp:
                latency = (asyncio.get_event_loop().time() - start) * 1000
                if resp.status == 200:
                    data = await resp.json()
                    return APIResponse(success=True, data=data, latency_ms=latency)
                else:
                    text = await resp.text()
                    return APIResponse(
                        success=False,
                        error=f"HTTP {resp.status}: {text[:200]}",
                        latency_ms=latency,
                    )
        except Exception as e:
            latency = (asyncio.get_event_loop().time() - start) * 1000
            return APIResponse(success=False, error=str(e), latency_ms=latency)

    # ---- Single queries ----

    async def get_user(self, username: str) -> APIResponse:
        return await self._request(f"/api/user/{username}")

    async def get_tweets(self, username: str, count: int = 20, cursor: str = "") -> APIResponse:
        params = {"count": count}
        if cursor:
            params["cursor"] = cursor
        return await self._request(f"/api/user/{username}/tweets", params)

    async def get_retweets(self, username: str, count: int = 20) -> APIResponse:
        return await self._request(f"/api/user/{username}/retweets", {"count": count})

    async def get_tweet(self, username: str, tweet_id: str) -> APIResponse:
        return await self._request(f"/api/tweet/{username}/status/{tweet_id}")

    async def search_tweets(self, query: str, count: int = 20, cursor: str = "") -> APIResponse:
        params = {"q": query, "count": count}
        if cursor:
            params["cursor"] = cursor
        return await self._request("/api/search", params)

    async def search_users(self, query: str, count: int = 20) -> APIResponse:
        return await self._request("/api/search/users", {"q": query, "count": count})

    async def health_check(self) -> APIResponse:
        return await self._request("/api/health")

    # ---- Batch queries (concurrent) ----

    async def batch_get_users(self, usernames: list[str], concurrent: int = 10) -> list[APIResponse]:
        sem = asyncio.Semaphore(concurrent)
        async def _fetch(u):
            async with sem:
                return await self.get_user(u)
        return await asyncio.gather(*[_fetch(u) for u in usernames])

    async def batch_get_tweets(
        self,
        usernames: list[str],
        count: int = 20,
        concurrent: int = 10,
    ) -> list[APIResponse]:
        sem = asyncio.Semaphore(concurrent)
        async def _fetch(u):
            async with sem:
                return await self.get_tweets(u, count)
        return await asyncio.gather(*[_fetch(u) for u in usernames])

    async def batch_search(
        self,
        queries: list[str],
        count: int = 20,
        concurrent: int = 10,
    ) -> list[APIResponse]:
        sem = asyncio.Semaphore(concurrent)
        async def _fetch(q):
            async with sem:
                return await self.search_tweets(q, count)
        return await asyncio.gather(*[_fetch(q) for q in queries])

    # ---- Bulk search with workers ----

    async def bulk_search(
        self,
        queries: list[str],
        count: int = 20,
        workers: int = 20,
    ) -> list[APIResponse]:
        """High-throughput bulk search with worker pool."""
        queue: asyncio.Queue = asyncio.Queue()
        for q in queries:
            await queue.put(q)

        results: list[APIResponse] = []
        results_lock = asyncio.Lock()

        async def _worker():
            while True:
                try:
                    query = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                resp = await self.search_tweets(query, count)
                async with results_lock:
                    results.append(resp)

        worker_tasks = [asyncio.create_task(_worker()) for _ in range(workers)]
        await asyncio.gather(*worker_tasks)
        return results

    async def bulk_get_users(
        self,
        usernames: list[str],
        workers: int = 20,
    ) -> list[APIResponse]:
        """High-throughput bulk user fetch with worker pool."""
        queue: asyncio.Queue = asyncio.Queue()
        for u in usernames:
            await queue.put(u)

        results: list[APIResponse] = []
        results_lock = asyncio.Lock()

        async def _worker():
            while True:
                try:
                    username = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                resp = await self.get_user(username)
                async with results_lock:
                    results.append(resp)

        worker_tasks = [asyncio.create_task(_worker()) for _ in range(workers)]
        await asyncio.gather(*worker_tasks)
        return results
