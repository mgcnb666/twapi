"""Pydantic models for API responses."""

from pydantic import BaseModel


class UserProfile(BaseModel):
    username: str
    display_name: str
    avatar_url: str = ""
    banner_url: str = ""
    bio: str = ""
    location: str = ""
    website: str = ""
    join_date: str = ""
    tweets_count: str = ""
    following_count: str = ""
    followers_count: str = ""
    likes_count: str = ""


class Tweet(BaseModel):
    id: str = ""
    author: str = ""
    display_name: str = ""
    avatar_url: str = ""
    text: str = ""
    date: str = ""
    retweets: str = "0"
    quotes: str = "0"
    likes: str = "0"
    replies: str = "0"
    images: list[str] = []
    videos: list[str] = []
    is_retweet: bool = False
    is_pinned: bool = False
    link: str = ""


class TweetDetail(BaseModel):
    tweet: Tweet
    replies: list[Tweet] = []


class UserTweetsResponse(BaseModel):
    user: str
    tweets: list[Tweet]
    cursor: str = ""
    page: int = 1
    total_fetched: int = 0


class SearchResponse(BaseModel):
    query: str
    tweets: list[Tweet]
    cursor: str = ""
    page: int = 1
    total_fetched: int = 0


class UserLikesResponse(BaseModel):
    user: str
    tweets: list[Tweet]
    cursor: str = ""
    page: int = 1
    total_fetched: int = 0


class UserRetweetsResponse(BaseModel):
    user: str
    tweets: list[Tweet]
    cursor: str = ""
    page: int = 1
    total_fetched: int = 0


class InstanceHealth(BaseModel):
    url: str
    healthy: bool
    latency_ms: float = -1


class HealthResponse(BaseModel):
    instances: list[InstanceHealth]
    active_count: int
    total_count: int
