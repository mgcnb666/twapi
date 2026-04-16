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
- **点赞/转发** — 独立 API 获取用户点赞和转发推文

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

### 3. 用户点赞

```
GET /api/user/{username}/likes
```

获取用户点赞过的推文（来自 Nitter 收藏页面）。

> ⚠️ **注意：** 大多数公共 Nitter 实例不公开收藏页面（需要服务端认证），此端点可能返回空结果。自托管 Nitter 配置 guest 账号后可正常使用。

**分页参数**（同用户推文）：

```bash
# 获取点赞
GET /api/user/elonmusk/likes

# 获取最新 100 条点赞
GET /api/user/elonmusk/likes?count=100
```

返回：
```json
{
  "user": "elonmusk",
  "tweets": [ ... ],
  "cursor": "...",
  "page": 1,
  "total_fetched": 20
}
```

### 4. 用户转发

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

### 5. 推文详情

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

### 6. 搜索推文

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

返回：
```json
{
  "query": "tesla",
  "tweets": [ ... ],
  "cursor": "...",
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

## 错误响应

| 状态码 | 示例 |
|---|---|
| 404 | `{"detail": "Profile card not found – user may not exist"}` |
| 502 | `{"detail": "Nitter fetch failed: All Nitter instances failed"}` |

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
           ├─ 点赞/转发 API
           └─ 健康检查（每 120 秒）
           ↓
         Nitter 实例 → Twitter/X
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
| `requirements.txt` | Python 依赖 |
