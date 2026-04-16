# TwAPI – 基于 Nitter 的 Twitter API

[🇬🇧 English](README.md)

自托管的 REST API，通过公共 Nitter 实例获取 Twitter/X 实时数据。

### 功能特性

- **Anubis 反爬破解** — 自动 PoW 求解器（preact + fast 两种格式）
- **Cloudflare 挑战绕过** — SeleniumBase UC 模式无头 Chrome（可选）
- **TLS 指纹伪装** — `curl_cffi` 模拟 Chrome 124 浏览器指纹
- **智能实例轮换** — 按延迟加权选择，自动健康检查
- **自动分页** — 支持 `page=N` 页码和 `count=N` 指定数量获取
- **获取全部** — `all=true` 获取用户所有推文（安全上限 10000 条）
- **转发** — 独立 API 获取用户转发推文
- **用户搜索** — 按关键词搜索 Twitter 用户
- **统计面板** — 实时 API 调用统计，Web 界面位于 `/dashboard`
- **结构化日志** — 滚动日志文件记录所有错误和运行事件

## 系统要求

```bash
# Python 依赖
pip install -r requirements.txt
```

如需启用 Cloudflare 绕过（可选）：
```bash
apt-get install -y xvfb python3-tk google-chrome-stable
# 在 config.py 中设置 enable_cf_browser = True
```

## 快速开始

```bash
python main.py
# 服务启动在 http://0.0.0.0:30192
```

## 配置

编辑 `config.py`：

```python
@dataclass
class Settings:
    port: int = 30192                # 服务端口
    instances: list[str] = ...       # Nitter 实例列表
    request_timeout: float = 15.0    # 单次请求超时
    max_retries: int = 5             # 跨实例重试次数
    health_check_interval: int = 120 # 健康检查间隔（秒）
    enable_cf_browser: bool = False  # 启用 Cloudflare 绕过
```

自定义端口：
```python
settings = Settings(port=8080)
```

---

## 实例状态

| 实例 | 保护方式 | 绕过方法 | 状态 |
|---|---|---|---|
| xcancel.com | BotD (FingerprintJS) | TLS 指纹伪装 | ✅ 个人页/时间线 |
| nitter.privacyredirect.com | Anubis (preact) | SHA-256 哈希 | ✅ 所有端点 |
| nitter.tiekoetter.com | Anubis PoW (fast) | SHA-256 暴力破解 | ✅ 所有端点 |
| nitter.catsarch.com | Anubis PoW (fast) | SHA-256 暴力破解 | ✅ 所有端点 |
| lightbrd.com | Cloudflare | Chrome 浏览器（可选） | ⚠️ 需启用 CF 浏览器 |
| nitter.space | Cloudflare | Chrome 浏览器（可选） | ⚠️ 需启用 CF 浏览器 |
| nuku.trabun.org | Cloudflare | Chrome 浏览器（可选） | ⚠️ 需启用 CF 浏览器 |
| nitter.poast.org | 服务器宕机 | N/A | ❌ 503 |

默认模式下 **4 个实例可用**，启用 CF 浏览器后最多 **7 个实例**。

### 反爬破解原理

**Anubis Preact**（privacyredirect）：从 `<script id="preact_info">` 提取挑战字符串，
计算 `SHA-256(challenge)` 提交即可获得 JWT cookie（有效期约 7 天）。

**Anubis Fast PoW**（tiekoetter, catsarch）：从 `<script id="anubis_challenge">` 提取 `randomData` 和 `difficulty`，
暴力搜索 nonce 使得 `SHA-256(randomData + nonce)` 的前 N 位为 0。

**Cloudflare**（lightbrd, nitter.space, nuku.trabun.org）：
后台 Chrome 浏览器通过 SeleniumBase UC 模式绕过 Turnstile 验证。
首次解决约需 20-40 秒，后续请求复用会话约 2-3 秒。

---

## API 端点

### 1. 用户资料

```
GET /api/user/{username}
```

示例：`GET /api/user/elonmusk`

返回：
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
  "followers_count": "238,117,648",
  "likes_count": "222,894"
}
```

### 2. 用户推文（时间线）

```
GET /api/user/{username}/tweets
```

**分页参数（三种方式）：**

| 参数 | 说明 | 示例 |
|---|---|---|
| `page` | 页码（默认 1，每页约 20 条） | `?page=3` 获取第 3 页 |
| `count` | 指定获取总数（自动翻页，最大 500） | `?count=100` 获取最新 100 条 |
| `all` | 获取所有推文（自动翻页至结束） | `?all=true` |
| `cursor` | 原始游标值（高级用法） | `?cursor=DAAHCgAB...` |

示例：

```bash
# 获取第 1 页（默认）
GET /api/user/elonmusk/tweets

# 获取第 3 页
GET /api/user/elonmusk/tweets?page=3

# 获取最新 100 条推文
GET /api/user/elonmusk/tweets?count=100

# 获取用户所有推文
GET /api/user/elonmusk/tweets?all=true
```

返回：
```json
{
  "user": "elonmusk",
  "tweets": [
    {
      "id": "2044683867630833961",
      "author": "@elonmusk",
      "display_name": "Elon Musk",
      "avatar_url": "https://pbs.twimg.com/...",
      "text": "推文内容...",
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

### 3. 用户转发

```
GET /api/user/{username}/retweets
```

获取用户转发的推文（从时间线中筛选 `is_retweet=true` 的推文）。

```bash
# 获取第 1 页转发
GET /api/user/elonmusk/retweets

# 获取最新 50 条转发
GET /api/user/elonmusk/retweets?count=50

# 获取所有转发
GET /api/user/elonmusk/retweets?all=true
```

返回：
```json
{
  "user": "elonmusk",
  "tweets": [ ... ],
  "cursor": "...",
  "page": 1,
  "total_fetched": 5
}
```

### 4. 推文详情

```
GET /api/tweet/{username}/status/{tweet_id}
```

示例：`GET /api/tweet/elonmusk/status/2044664503598760073`

返回：
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
    { "id": "...", "author": "@user", "text": "回复内容..." }
  ]
}
```

### 5. 搜索推文

```
GET /api/search?q=关键词
```

**分页参数**（同用户推文）：

```bash
# 搜索 "tesla" 第 1 页
GET /api/search?q=tesla

# 搜索 "AI" 前 80 条结果
GET /api/search?q=AI&count=80

# 搜索第 2 页
GET /api/search?q=tesla&page=2

# 搜索所有结果
GET /api/search?q=tesla&all=true
```

### 6. 搜索用户

```
GET /api/search/users?q=关键词
```

按关键词搜索 Twitter 用户，支持 `page` 和 `count` 分页。

```bash
# 搜索用户 "elonmusk"
GET /api/search/users?q=elonmusk

# 获取 50 个匹配用户
GET /api/search/users?q=bitcoin&count=50
```

返回：
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

### 7. 实例健康状态

```
GET /api/health
```

返回：
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

### 8. API 统计

```
GET /api/stats?hours=24
```

返回指定时间窗口内的聚合调用统计。

返回：
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

### 9. 最近调用

```
GET /api/stats/recent?limit=50
```

返回最近的 API 调用记录，包含完整详情（时间戳、状态码、延迟、路径、查询参数等）。

### 10. 统计面板

```
GET /dashboard
```

交互式 Web 仪表板，包含实时图表、KPI 卡片、端点分析和调用日志。每 30 秒自动刷新。

---

## 错误响应

| 状态码 | 示例 |
|---|---|
| 404 | `{"detail": "Profile card not found – user may not exist"}` |
| 502 | `{"detail": "Nitter fetch failed: All Nitter instances failed"}` |

## 日志

所有运行事件和错误写入 `logs/` 目录下的滚动日志文件：

| 文件 | 内容 |
|---|---|
| `logs/twapi.log` | 所有级别（DEBUG+）— 完整请求追踪 |
| `logs/error.log` | 仅错误（ERROR+）— 快速问题定位 |

日志滚动：每个文件 5MB，保留 3 个备份。日志包含时间戳、级别、模块名称，错误时包含完整堆栈追踪。

## 架构

```
客户端 → FastAPI (端口 30192)
           ↓
         NitterClient
           ├─ 实例轮换（延迟加权）
           ├─ Anubis PoW 求解器（preact + fast）
           ├─ TLS 指纹伪装（curl_cffi）
           ├─ Cloudflare 绕过（Chrome，可选）
           ├─ Cookie 持久化
           ├─ 自动分页（page/count/all）
           └─ 健康检查（每 120 秒）
           ↓
         Nitter 实例 → Twitter/X
           ↓
         StatsMiddleware → SQLite (api_stats.db)
           ↓
         /dashboard（实时 Web 面板）
```

## 文件说明

| 文件 | 说明 |
|---|---|
| `main.py` | FastAPI 应用、路由、分页逻辑、入口 |
| `config.py` | 配置（端口、实例、超时、CF 开关） |
| `nitter_client.py` | HTTP 客户端、实例轮换、Anubis 求解、CF 集成 |
| `cf_browser.py` | Cloudflare 绕过 — SeleniumBase UC Chrome 工作线程 |
| `parser.py` | HTML→JSON 解析器 |
| `models.py` | Pydantic 响应模型 |
| `stats.py` | API 调用统计跟踪器（SQLite）+ ASGI 中间件 |
| `dashboard.py` | 统计面板 HTML/CSS/JS 前端 |
| `requirements.txt` | Python 依赖 |
