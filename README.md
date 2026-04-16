# TwAPI – Twitter API via Nitter

[🇨🇳 中文文档](README_CN.md)

Self-hosted REST API that fetches real-time Twitter/X data through public Nitter instances.

### Features

- **Anubis Anti-Bot Bypass** — automatic PoW solvers (preact + fast formats)
- **Cloudflare Challenge Bypass** — SeleniumBase UC mode headless Chrome (optional)
- **TLS Fingerprint Impersonation** — `curl_cffi` mimics Chrome 124
- **Smart Instance Rotation** — latency-weighted selection with automatic health checks
- **Auto-Pagination** — `page=N`, `count=N`, or `all=true` to fetch everything
- **Retweets** — dedicated endpoint for user retweeted posts
- **Fetch All** — `all=true` retrieves all available tweets (safety cap 10,000)
- **User Search** — search Twitter users by keyword
- **Statistics Dashboard** — real-time API call tracking with web UI at `/dashboard`
- **Structured Logging** — rotating log files for all errors and runtime events

## Requirements

```bash
pip install -r requirements.txt
```

For Cloudflare bypass (optional):
```bash
apt-get install -y xvfb python3-tk google-chrome-stable
# Set enable_cf_browser = True in config.py
```

## Quick Start

```bash
python main.py
# Server starts at http://0.0.0.0:30192
```

## Configuration

Edit `config.py`:

```python
@dataclass
class Settings:
    port: int = 30192                # Server port
    instances: list[str] = ...       # Nitter instance list
    request_timeout: float = 15.0    # Per-request timeout
    max_retries: int = 5             # Cross-instance retries
    health_check_interval: int = 120 # Health check interval (seconds)
    enable_cf_browser: bool = False  # Enable Cloudflare bypass
```

Custom port:
```python
settings = Settings(port=8080)
```

---

## Instance Status

| Instance | Protection | Bypass Method | Status |
|---|---|---|---|
| xcancel.com | BotD (FingerprintJS) | TLS impersonation | ✅ Profile/timeline |
| nitter.privacyredirect.com | Anubis (preact) | SHA-256 hash | ✅ All endpoints |
| nitter.tiekoetter.com | Anubis PoW (fast) | SHA-256 brute-force | ✅ All endpoints |
| nitter.catsarch.com | Anubis PoW (fast) | SHA-256 brute-force | ✅ All endpoints |
| lightbrd.com | Cloudflare | Chrome browser (optional) | ⚠️ Needs CF browser |
| nitter.space | Cloudflare | Chrome browser (optional) | ⚠️ Needs CF browser |
| nuku.trabun.org | Cloudflare | Chrome browser (optional) | ⚠️ Needs CF browser |
| nitter.poast.org | Server down | N/A | ❌ 503 |

**4 instances available** by default; up to **7** with CF browser enabled.

---

## API Endpoints

### 1. User Profile

```
GET /api/user/{username}
```

Example: `GET /api/user/elonmusk`

Response:
```json
{
  "username": "@elonmusk",
  "display_name": "Elon Musk",
  "avatar_url": "https://pbs.twimg.com/profile_images/.../photo.jpg",
  "banner_url": "https://pbs.twimg.com/profile_banners/...",
  "bio": "...",
  "location": "",
  "website": "",
  "join_date": "Joined June 2009",
  "tweets_count": "101,354",
  "following_count": "1,311",
  "followers_count": "238,117,648",
  "likes_count": "222,894"
}
```

### 2. User Tweets (Timeline)

```
GET /api/user/{username}/tweets
```

**Pagination parameters:**

| Parameter | Description | Example |
|---|---|---|
| `page` | Page number (default 1, ~20 per page) | `?page=3` |
| `count` | Total tweets to fetch (max 500, auto-paginates) | `?count=100` |
| `all` | Fetch ALL available tweets | `?all=true` |
| `cursor` | Raw cursor (advanced) | `?cursor=DAAHCgAB...` |

```bash
# Page 1 (default)
GET /api/user/elonmusk/tweets

# Page 3
GET /api/user/elonmusk/tweets?page=3

# Latest 100 tweets
GET /api/user/elonmusk/tweets?count=100

# ALL tweets
GET /api/user/elonmusk/tweets?all=true
```

Response:
```json
{
  "user": "elonmusk",
  "tweets": [
    {
      "id": "2044683867630833961",
      "author": "@elonmusk",
      "display_name": "Elon Musk",
      "text": "Tweet content...",
      "date": "Apr 16, 2026 · 7:46 AM UTC",
      "retweets": "480",
      "quotes": "0",
      "likes": "4,413",
      "replies": "883",
      "images": [],
      "videos": [],
      "is_retweet": false,
      "is_pinned": true,
      "link": "/elonmusk/status/2044683867630833961#m"
    }
  ],
  "cursor": "DAAHCgABHGA6PFI__-sL...",
  "page": 1,
  "total_fetched": 20
}
```

### 3. User Retweets

```
GET /api/user/{username}/retweets
```

Fetches only retweeted posts from the user's timeline (`is_retweet=true`). Same pagination parameters.

```bash
# Page 1 of retweets
GET /api/user/elonmusk/retweets

# Latest 50 retweets
GET /api/user/elonmusk/retweets?count=50

# ALL retweets
GET /api/user/elonmusk/retweets?all=true
```

### 4. Tweet Detail

```
GET /api/tweet/{username}/status/{tweet_id}
```

Example: `GET /api/tweet/elonmusk/status/2044664503598760073`

Response:
```json
{
  "tweet": {
    "id": "2044664503598760073",
    "author": "@elonmusk",
    "text": "Starship Super Heavy Booster...",
    "likes": "24,260",
    "retweets": "2,670",
    "images": ["https://pbs.twimg.com/orig/media/...jpg"]
  },
  "replies": [
    { "id": "...", "author": "@user", "text": "Reply content..." }
  ]
}
```

### 5. Search Tweets

```
GET /api/search?q=keyword
```

Same pagination parameters as tweets (`page`, `count`, `all`, `cursor`).

```bash
# Search "tesla" page 1
GET /api/search?q=tesla

# First 80 results for "AI"
GET /api/search?q=AI&count=80

# ALL results
GET /api/search?q=tesla&all=true
```

### 6. Search Users

```
GET /api/search/users?q=keyword
```

Search Twitter users by keyword. Supports `page` and `count` pagination.

```bash
# Search users "elonmusk"
GET /api/search/users?q=elonmusk

# Get 50 matching users
GET /api/search/users?q=bitcoin&count=50
```

Response:
```json
{
  "query": "elonmusk",
  "users": [
    {
      "username": "@elonmusk",
      "display_name": "Elon Musk",
      "avatar_url": "https://pbs.twimg.com/profile_images/.../photo.jpg",
      "bio": "Terafab.ai",
      "verified": true
    }
  ],
  "cursor": "DAAFCgAB...",
  "page": 1,
  "total_fetched": 20
}
```

### 7. Instance Health

```
GET /api/health
```

Response:
```json
{
  "instances": [
    { "url": "https://xcancel.com", "healthy": true, "latency_ms": 155.0 },
    { "url": "https://nitter.poast.org", "healthy": false, "latency_ms": -1.0 }
  ],
  "active_count": 4,
  "total_count": 8
}
```

---

### 8. API Statistics

```
GET /api/stats?hours=24
```

Returns aggregated call statistics for the specified time window.

Response:
```json
{
  "total_calls": 150,
  "success_count": 142,
  "error_count": 8,
  "success_rate": 94.7,
  "avg_latency_ms": 1250.5,
  "min_latency_ms": 320.0,
  "max_latency_ms": 8500.0,
  "by_endpoint": [
    { "endpoint": "user/tweets", "calls": 80, "success": 76, "avg_ms": 1100.0 }
  ],
  "by_status_code": [
    { "status_code": 200, "count": 142 },
    { "status_code": 502, "count": 8 }
  ],
  "by_hour": [
    { "hour": "2026-04-17T14:00", "calls": 12, "errors": 1, "avg_ms": 980.0 }
  ],
  "top_paths": [
    { "path": "/api/user/elonmusk/tweets", "calls": 45 }
  ]
}
```

### 9. Recent Calls

```
GET /api/stats/recent?limit=50
```

Returns the most recent API calls with full details (timestamp, status, latency, path, query, etc.).

### 10. Dashboard

```
GET /dashboard
```

Interactive web dashboard with real-time charts, KPI cards, endpoint breakdown, and call logs. Auto-refreshes every 30 seconds.

---

## Error Responses

| Status | Example |
|---|---|
| 404 | `{"detail": "Profile card not found – user may not exist"}` |
| 502 | `{"detail": "Nitter fetch failed: All Nitter instances failed"}` |

## Logging

All runtime events and errors are written to rotating log files in `logs/`:

| File | Contents |
|---|---|
| `logs/twapi.log` | All log levels (DEBUG+) – full request tracing |
| `logs/error.log` | Errors only (ERROR+) – quick problem diagnosis |

Log rotation: 5 MB per file, 3 backup files retained. Logs include timestamps, level, module name, and full stack traces for errors.

## Architecture

```
Client → FastAPI (port 30192)
           ↓
         NitterClient
           ├─ Instance rotation (latency-weighted)
           ├─ Anubis PoW solvers (preact + fast)
           ├─ TLS fingerprint (curl_cffi)
           ├─ Cloudflare bypass (Chrome, optional)
           ├─ Cookie persistence
           ├─ Auto-pagination (page/count/all)
           └─ Health checks (every 120s)
           ↓
         Nitter instances → Twitter/X
           ↓
         StatsMiddleware → SQLite (api_stats.db)
           ↓
         /dashboard (real-time web UI)
```

## Files

| File | Description |
|---|---|
| `main.py` | FastAPI app, routes, pagination logic, entry point |
| `config.py` | Settings (port, instances, timeouts, CF toggle) |
| `nitter_client.py` | HTTP client, instance rotation, Anubis solver, CF integration |
| `cf_browser.py` | Cloudflare bypass — SeleniumBase UC Chrome worker thread |
| `parser.py` | HTML → JSON parser |
| `models.py` | Pydantic response models |
| `stats.py` | API call statistics tracker (SQLite) + ASGI middleware |
| `dashboard.py` | Dashboard HTML/CSS/JS frontend |
| `requirements.txt` | Python dependencies |
