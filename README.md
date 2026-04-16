# TwAPI – Twitter API powered by Nitter

A self-hosted REST API that fetches real-time Twitter/X data through public Nitter instances.
Every request returns **fresh, live data** — no caching.

Features:
- **Anubis anti-bot bypass** — automatic PoW solver (preact + fast formats)
- **Cloudflare managed challenge bypass** — headless Chrome via SeleniumBase UC mode
- **TLS fingerprint impersonation** — `curl_cffi` with Chrome 124 fingerprint
- **Smart instance rotation** — latency-weighted selection with automatic health checks
- **7 of 8 instances working** — only `nitter.poast.org` (server down) excluded

## Prerequisites

```bash
# System packages (Debian/Ubuntu)
apt-get install -y xvfb python3-tk google-chrome-stable

# Python dependencies
pip install -r requirements.txt
```

> **Chrome** is needed for the Cloudflare bypass. If Chrome is not installed, CF
> instances are simply skipped and the remaining 4 non-CF instances still work.

## Quick Start

```bash
python main.py
# Server starts on http://0.0.0.0:30192
```

## Configuration

Edit `config.py`:

```python
@dataclass
class Settings:
    port: int = 30192                # API server port
    instances: list[str] = ...       # Nitter instance URLs
    request_timeout: float = 15.0    # per-request timeout
    max_retries: int = 5             # retries across instances
    health_check_interval: int = 120 # seconds between health loops
```

Custom port example:
```python
settings = Settings(port=8080)
```

---

## Instance Status

| Instance | Protection | Bypass Method | Status |
|---|---|---|---|
| xcancel.com | BotD (FingerprintJS) | TLS impersonation | ✅ Profile/Timeline |
| nitter.privacyredirect.com | Anubis (preact) | SHA-256 hash | ✅ All endpoints |
| nitter.tiekoetter.com | Anubis PoW (fast) | SHA-256 brute-force | ✅ All endpoints |
| nitter.catsarch.com | Anubis PoW (fast) | SHA-256 brute-force | ✅ All endpoints |
| lightbrd.com | Cloudflare | SeleniumBase UC Chrome | ✅ All endpoints |
| nitter.space | Cloudflare | SeleniumBase UC Chrome | ✅ All endpoints |
| nuku.trabun.org | Cloudflare | SeleniumBase UC Chrome | ✅ All endpoints |
| nitter.poast.org | Server down | N/A | ❌ 503 |

**7 of 8 instances active.** The system automatically rotates between healthy instances, weighting by latency.

### Anti-Bot Bypass Details

**Anubis Preact** (privacyredirect): Challenge string in `<script id="preact_info">`.
Solution = `SHA-256(challenge_hex)`. Submit to redirect URL → JWT cookie valid ~7 days.

**Anubis Fast PoW** (tiekoetter, catsarch): `randomData` + `difficulty` in `<script id="anubis_challenge">`.
Find nonce where `SHA-256(randomData + nonce)` has N leading zero hex digits. Submit hash + nonce → JWT cookie.

**Cloudflare Managed Challenge** (lightbrd, nitter.space, nuku.trabun.org):
A background Chrome browser (SeleniumBase UC mode) runs in a worker thread with Xvfb virtual display.
It solves the turnstile challenge via `uc_gui_click_captcha()`. Once solved per domain, subsequent
requests reuse the session cookies and complete in ~2-3 seconds.

> CF cookies are TLS-fingerprint-bound, so the browser must be used for all requests to CF instances
> (cookies cannot be transferred to curl_cffi).

**xcancel.com**: Profile/timeline work with Chrome TLS impersonation (`curl_cffi`).
Tweet detail and search are blocked by FingerprintJS BotD (requires real browser JS execution).

---

## API Endpoints

### 1. User Profile

```
GET /api/user/{username}
```

Response:
```json
{
  "username": "@elonmusk",
  "display_name": "Elon Musk",
  "avatar_url": "https://pbs.twimg.com/profile_images/.../photo.jpg",
  "banner_url": "https://pbs.twimg.com/profile_banners/...",
  "bio": "Terafab.ai",
  "location": "",
  "website": "",
  "join_date": "Joined June 2009",
  "tweets_count": "101,354",
  "following_count": "1,311",
  "followers_count": "238,107,708",
  "likes_count": "222,894"
}
```

### 2. User Tweets (Timeline)

```
GET /api/user/{username}/tweets?cursor=
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
      "avatar_url": "https://pbs.twimg.com/profile_images/.../photo_bigger.jpg",
      "text": "Look at the tiny cars in the foreground...",
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
  "cursor": "DAAHCgABHGA6PFI__-sL..."
}
```

Use the `cursor` value for pagination:
```
GET /api/user/elonmusk/tweets?cursor=DAAHCgABHGA6PFI__-sL...
```

### 3. Tweet Detail

```
GET /api/tweet/{username}/status/{tweet_id}
```

Response:
```json
{
  "tweet": {
    "id": "2044664503598760073",
    "author": "@elonmusk",
    "display_name": "Elon Musk",
    "text": "Starship Super Heavy Booster, the most powerful moving object ever made by far",
    "date": "Apr 16, 2026 · 6:29 AM UTC",
    "retweets": "2,670",
    "likes": "24,260",
    "replies": "2,027",
    "images": ["https://pbs.twimg.com/orig/media/HF_XtVIXcAQ5jrN.jpg"],
    "videos": [],
    "is_retweet": false,
    "is_pinned": false,
    "link": "/elonmusk/status/2044664503598760073#m"
  },
  "replies": [
    {
      "id": "...",
      "author": "@user",
      "text": "Amazing!",
      "likes": "42",
      "replies": "3"
    }
  ]
}
```

### 4. Search Tweets

```
GET /api/search?q=keyword&cursor=
```

Response:
```json
{
  "query": "tesla",
  "tweets": [
    {
      "id": "...",
      "author": "@user",
      "text": "Tesla AI5 chip is incredible...",
      "likes": "1,234"
    }
  ],
  "cursor": "..."
}
```

### 5. Instance Health

```
GET /api/health
```

Response:
```json
{
  "instances": [
    { "url": "https://xcancel.com", "healthy": true, "latency_ms": 155.0 },
    { "url": "https://nitter.poast.org", "healthy": false, "latency_ms": -1.0 },
    { "url": "https://nitter.privacyredirect.com", "healthy": true, "latency_ms": 1086.0 },
    { "url": "https://lightbrd.com", "healthy": true, "latency_ms": 48221.0 },
    { "url": "https://nitter.space", "healthy": true, "latency_ms": 14451.0 },
    { "url": "https://nitter.tiekoetter.com", "healthy": true, "latency_ms": 366.0 },
    { "url": "https://nuku.trabun.org", "healthy": true, "latency_ms": 11648.0 },
    { "url": "https://nitter.catsarch.com", "healthy": true, "latency_ms": 481.0 }
  ],
  "active_count": 7,
  "total_count": 8
}
```

---

## Error Responses

| Status | Example |
|---|---|
| 404 | `{"detail": "Profile card not found – user may not exist"}` |
| 502 | `{"detail": "Nitter fetch failed: All Nitter instances failed"}` |

## Architecture

```
Client → FastAPI (port 30192)
           ↓
         NitterClient
           ├─ Instance rotation (latency-weighted)
           ├─ Anubis PoW solver (preact + fast)
           ├─ TLS fingerprint impersonation (curl_cffi)
           ├─ Cloudflare bypass (SeleniumBase UC Chrome + Xvfb)
           ├─ Cookie persistence per instance
           └─ Auto health checks every 120s (CF every ~10 min)
           ↓
         Nitter Instances → Twitter/X
```

```
Non-CF instances:  curl_cffi (Chrome TLS fingerprint)
                     ├─ Anubis challenge → auto-solve PoW → JWT cookie
                     └─ Direct fetch with saved cookies

CF instances:      SeleniumBase UC Chrome (worker thread)
                     ├─ First visit → uc_gui_click_captcha() → cf_clearance cookie
                     └─ Subsequent visits → reuse session (~2-3s)
```

## Files

| File | Description |
|---|---|
| `main.py` | FastAPI app, routes, entry point |
| `config.py` | Settings (port, instances, timeouts) |
| `nitter_client.py` | HTTP client, instance rotation, Anubis solver, CF integration |
| `cf_browser.py` | Cloudflare bypass — SeleniumBase UC Chrome in worker thread |
| `parser.py` | HTML→JSON parser for Nitter pages |
| `models.py` | Pydantic response models |
| `requirements.txt` | Python dependencies |
