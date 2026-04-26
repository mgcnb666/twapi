"""TwAPI Python Client - Easy Twitter/X data queries via Nitter.

This module provides a simple async client for querying Twitter data
through the local TwAPI service.

Usage:
    from twapi_client import TwAPIClient
    
    client = TwAPIClient()
    
    # Get user profile
    user = await client.get_user("elonmusk")
    
    # Search tweets
    tweets = await client.search_tweets("python", count=50)
    
    # Get user tweets
    tweets = await client.get_tweets("github", count=40)
    
    await client.close()
"""

import aiohttp
from typing import Optional, Any


class TwAPIClient:
    """Async client for TwAPI Twitter/X proxy service."""
    
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
    
    async def _request(self, path: str, params: Optional[dict] = None) -> dict:
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()
    
    # ---- User Endpoints ----
    
    async def get_user(self, username: str) -> dict:
        """Get user profile information.
        
        Args:
            username: Twitter username (without @)
            
        Returns:
            UserProfile dict with username, display_name, bio, 
            followers_count, etc.
        """
        return await self._request(f"/api/user/{username}")
    
    async def get_tweets(
        self, 
        username: str, 
        count: int = 20,
        page: int = 1,
        cursor: str = "",
        all_tweets: bool = False
    ) -> dict:
        """Get user's tweets.
        
        Args:
            username: Twitter username
            count: Number of tweets to fetch (max 500)
            page: Page number for pagination
            cursor: Pagination cursor for advanced use
            all_tweets: If True, fetch ALL available tweets
            
        Returns:
            UserTweetsResponse with tweets list and cursor
        """
        params = {}
        if count > 0:
            params["count"] = count
        if page > 1:
            params["page"] = page
        if cursor:
            params["cursor"] = cursor
        if all_tweets:
            params["all"] = "true"
        return await self._request(f"/api/user/{username}/tweets", params)
    
    async def get_retweets(
        self,
        username: str,
        count: int = 20,
        page: int = 1,
        cursor: str = "",
        all_retweets: bool = False
    ) -> dict:
        """Get user's retweets only.
        
        Args:
            username: Twitter username
            count: Number of retweets to fetch
            page: Page number
            cursor: Pagination cursor
            all_retweets: If True, fetch ALL retweets
            
        Returns:
            UserRetweetsResponse with filtered retweets
        """
        params = {}
        if count > 0:
            params["count"] = count
        if page > 1:
            params["page"] = page
        if cursor:
            params["cursor"] = cursor
        if all_retweets:
            params["all"] = "true"
        return await self._request(f"/api/user/{username}/retweets", params)
    
    # ---- Tweet Endpoints ----
    
    async def get_tweet(self, username: str, tweet_id: str) -> dict:
        """Get a single tweet with replies.
        
        Args:
            username: Tweet author's username
            tweet_id: Tweet ID
            
        Returns:
            TweetDetail with tweet and replies list
        """
        return await self._request(f"/api/tweet/{username}/status/{tweet_id}")
    
    # ---- Search Endpoints ----
    
    async def search_tweets(
        self,
        query: str,
        count: int = 20,
        page: int = 1,
        cursor: str = "",
        all_results: bool = False
    ) -> dict:
        """Search tweets by keyword.
        
        Args:
            query: Search query string
            count: Number of results (max 500)
            page: Page number
            cursor: Pagination cursor
            all_results: If True, fetch ALL results
            
        Returns:
            SearchResponse with matching tweets
        """
        params = {"q": query}
        if count > 0:
            params["count"] = count
        if page > 1:
            params["page"] = page
        if cursor:
            params["cursor"] = cursor
        if all_results:
            params["all"] = "true"
        return await self._request("/api/search", params)
    
    async def search_users(
        self,
        query: str,
        count: int = 20,
        page: int = 1,
        cursor: str = ""
    ) -> dict:
        """Search users by keyword.
        
        Args:
            query: Search query string
            count: Number of results
            page: Page number
            cursor: Pagination cursor
            
        Returns:
            UserSearchResponse with matching users
        """
        params = {"q": query}
        if count > 0:
            params["count"] = count
        if page > 1:
            params["page"] = page
        if cursor:
            params["cursor"] = cursor
        return await self._request("/api/search/users", params)
    
    # ---- Health ----
    
    async def health_check(self) -> dict:
        """Check health of all Nitter instances.
        
        Returns:
            HealthResponse with instance status and latencies
        """
        return await self._request("/api/health")


# Convenience functions for direct use

async def get_user(username: str, base_url: str = "http://localhost:30192") -> dict:
    """Quick fetch user profile."""
    client = TwAPIClient(base_url)
    try:
        return await client.get_user(username)
    finally:
        await client.close()


async def search_tweets(query: str, count: int = 20, base_url: str = "http://localhost:30192") -> dict:
    """Quick search tweets."""
    client = TwAPIClient(base_url)
    try:
        return await client.search_tweets(query, count)
    finally:
        await client.close()


async def get_tweets(username: str, count: int = 20, base_url: str = "http://localhost:30192") -> dict:
    """Quick fetch user tweets."""
    client = TwAPIClient(base_url)
    try:
        return await client.get_tweets(username, count)
    finally:
        await client.close()
