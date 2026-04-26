# TwAPI v2.0

Twitter/X REST API powered by public Nitter instances.

Fetches live data from Nitter (no caching) so results are always up-to-date.

## Features

- **Connection Pooling**: Persistent `AsyncSession` per Nitter instance
- **Concurrency Control**: Global + per-instance semaphore limiting
- **Circuit Breaker**: Automatic instance health management
- **Parallel Pagination**: Fetch multiple pages concurrently
- **Instance Racing**: Query 3 healthy instances simultaneously, return fastest
- **Auto-Rotation**: Seamless failover between Nitter instances

## Quick Start

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 30192 --workers 4
```

## API Endpoints

| Endpoint | Description | Parameters |
|----------|-------------|------------|
| `GET /api/user/{username}` | User profile | - |
| `GET /api/user/{username}/tweets` | User tweets | `page`, `count`, `cursor`, `all` |
| `GET /api/user/{username}/retweets` | User retweets | `page`, `count`, `cursor`, `all` |
| `GET /api/tweet/{username}/status/{id}` | Single tweet + replies | - |
| `GET /api/search?q=keyword` | Search tweets | `q`, `page`, `count`, `cursor`, `all` |
| `GET /api/search/users?q=keyword` | Search users | `q`, `page`, `count` |
| `GET /api/health` | Instance health | - |
| `GET /api/stats` | API statistics | `hours` |
| `GET /dashboard` | Stats dashboard | - |

### Examples

```bash
# User profile
curl http://localhost:30192/api/user/elonmusk

# Search tweets
curl "http://localhost:30192/api/search?q=python&count=50"

# Get tweets (with auto-pagination)
curl "http://localhost:30192/api/user/github/tweets?count=100"

# Get ALL tweets
curl "http://localhost:30192/api/user/elonmusk/tweets?all=true"
```

## Python Client

```python
import asyncio
from twapi_client import TwAPIClient

async def main():
    client = TwAPIClient("http://localhost:30192")
    
    # Get user profile
    user = await client.get_user("elonmusk")
    print(user["display_name"], user["followers_count"])
    
    # Search tweets
    results = await client.search_tweets("python programming", count=50)
    for tweet in results["tweets"]:
        print(tweet["author"], tweet["text"][:100])
    
    # Get user's recent tweets
    tweets = await client.get_tweets("github", count=40)
    
    await client.close()

asyncio.run(main())
```

## Batch Queries

```python
from batch_client import BatchTwAPIClient

async def main():
    client = BatchTwAPIClient("http://localhost:30192")
    
    # Batch user lookup (10 concurrent)
    users = ["elonmusk", "github", "twitter", "google"]
    results = await client.batch_get_users(users, concurrent=10)
    
    # Bulk search (20 workers)
    queries = ["python", "ai", "ml", "data"]
    results = await client.bulk_search(queries, count=20, workers=20)
    
    await client.close()
```

## Configuration

Edit `config.py`:

```python
max_concurrent_requests: int = 1000   # Global limit
instance_concurrent_limit: int = 50    # Per-instance limit
fetch_timeout: float = 10.0            # Request timeout
circuit_breaker_failures: int = 5       # Failures before marking unhealthy
circuit_breaker_recovery: float = 30.0 # Recovery time (seconds)
enable_parallel_pagination: bool = True  # Parallel page fetching
max_parallel_pages: int = 5            # Max parallel pages
```

## Benchmark

```bash
# Search endpoint
python benchmark.py --endpoint search --query "python" --concurrent 100 --requests 500

# Mixed workload
python benchmark.py --endpoint mixed --concurrent 80 --requests 400
```

## Response Models

### UserProfile
```json
{
  "username": "elonmusk",
  "display_name": "Elon Musk",
  "avatar_url": "...",
  "bio": "...",
  "tweets_count": "...",
  "following_count": "...",
  "followers_count": "...",
  "likes_count": "..."
}
```

### Tweet
```json
{
  "id": "123456789",
  "author": "elonmusk",
  "display_name": "Elon Musk",
  "text": "...",
  "date": "...",
  "retweets": "...",
  "likes": "...",
  "replies": "...",
  "images": [],
  "videos": [],
  "is_retweet": false,
  "link": "..."
}
```

## File Structure

```
twapi/
├── main.py              # FastAPI application
├── nitter_client.py     # Nitter client with pooling & circuit breaker
├── config.py            # Settings
├── models.py            # Pydantic models
├── parser.py            # HTML parser
├── stats.py             # API statistics
├── dashboard.py         # Stats dashboard HTML
├── twapi_client.py      # Simple async client
├── batch_client.py      # Batch query client
├── benchmark.py         # Performance testing
└── README.md            # This file
```

## Changelog

### v2.0.0
- Added connection pooling with persistent sessions
- Added circuit breaker pattern for instance health
- Added global and per-instance concurrency limiting
- Added parallel instance fetching (race mode)
- Added parallel pagination support
- Added batch query client (`batch_client.py`)
- Added benchmark tool (`benchmark.py`)
- Added simple async client (`twapi_client.py`)

### v1.4.0
- Structured logging
- Search users API

### v1.3.0
- API stats dashboard
- Removed likes endpoint

## License

MIT
