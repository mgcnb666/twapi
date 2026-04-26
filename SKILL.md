---
name: twapi-query
description: Query Twitter/X data via TwAPI Nitter proxy service
version: 2.0.0
tags: [twitter, social-media, api, nitter]
---

# TwAPI Query Skill

Query Twitter/X data through a local TwAPI service powered by Nitter instances.

## Features

- **Connection Pooling**: Persistent sessions per Nitter instance
- **Concurrency Control**: Global + per-instance semaphore limiting
- **Circuit Breaker**: Automatic instance health management
- **Parallel Pagination**: Fetch multiple pages concurrently
- **Instance Racing**: Query 3 healthy instances simultaneously

## Prerequisites

The TwAPI service must be running:
```bash
cd /root/twapi/src
uvicorn main:app --host 0.0.0.0 --port 30192 --workers 4
```

Or from the project root:
```bash
cd /root/twapi
uvicorn src.main:app --host 0.0.0.0 --port 30192 --workers 4
```

## Quick Query

```python
from twapi_client import TwAPIClient

client = TwAPIClient("http://localhost:30192")

# Get user profile
user = await client.get_user("elonmusk")

# Search tweets
results = await client.search_tweets("python", count=50)

# Get tweets
tweets = await client.get_tweets("github", count=40)

await client.close()
```

## API Endpoints

| Endpoint | Description | Parameters |
|----------|-------------|------------|
| `GET /api/user/{username}` | User profile | - |
| `GET /api/user/{username}/tweets` | User tweets | `page`, `count`, `cursor`, `all` |
| `GET /api/user/{username}/retweets` | User retweets | `page`, `count`, `cursor`, `all` |
| `GET /api/tweet/{username}/status/{id}` | Single tweet | `username`, `tweet_id` |
| `GET /api/search?q=keyword` | Search tweets | `q`, `page`, `count`, `cursor`, `all` |
| `GET /api/search/users?q=keyword` | Search users | `q`, `page`, `count` |
| `GET /api/health` | Instance health | - |

## Response Models

### UserProfile
- `username`, `display_name`, `avatar_url`, `banner_url`
- `bio`, `location`, `website`, `join_date`
- `tweets_count`, `following_count`, `followers_count`, `likes_count`

### Tweet
- `id`, `author`, `display_name`, `avatar_url`
- `text`, `date`, `retweets`, `quotes`, `likes`, `replies`
- `images`, `videos`, `is_retweet`, `is_pinned`, `link`

## Changelog

### v2.0.0
- Added connection pooling with persistent sessions
- Added circuit breaker pattern for instance health
- Added global and per-instance concurrency limiting
- Added parallel instance fetching (race mode)
- Added parallel pagination support
- Added input validation and security hardening

### v1.4.0
- Structured logging
- Search users API

## Notes

- Data is fetched live from Nitter instances (no caching)
- Some instances may be blocked; the client auto-rotates to healthy ones
