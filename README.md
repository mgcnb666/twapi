# TwAPI High-Concurrency Edition v2.0

基于 [mgcnb666/twapi](https://github.com/mgcnb666/twapi) 改进的高并发版本。

## 主要改进

### 1. 连接池管理
- **持久化连接**: 每个 Nitter 实例维护独立的 `AsyncSession`，避免重复创建连接
- **HTTP/2 支持**: 启用多路复用，减少连接数
- **预连接**: 启动时预热所有连接池

### 2. 并发控制
- **全局信号量**: `max_concurrent_requests` (默认 1000) 控制总并发
- **实例级信号量**: `instance_concurrent_limit` (默认 50) 防止单实例过载
- **并行实例竞争**: 同时向多个健康实例发起请求，返回最快响应

### 3. 熔断器模式 (Circuit Breaker)
- 连续失败 5 次后标记实例为不健康
- 30 秒后自动恢复尝试
- 避免向已死实例发送请求

### 4. 并行分页
- `enable_parallel_pagination`: 同时获取多页数据
- `max_parallel_pages`: 控制并行页数 (默认 5)
- 大幅减少大批量数据获取时间

### 5. 健康检查优化
- 异步并行检查所有实例
- 基于延迟的加权选择
- 实时健康状态更新

## 配置参数 (config.py)

```python
max_concurrent_requests: int = 1000      # 全局并发限制
instance_concurrent_limit: int = 50      # 单实例并发限制
connection_pool_size: int = 100         # 连接池大小
fetch_timeout: float = 10.0             # 单次请求超时
circuit_breaker_failures: int = 5         # 熔断触发失败次数
circuit_breaker_recovery: float = 30.0  # 熔断恢复时间(秒)
enable_parallel_pagination: bool = True   # 启用并行分页
max_parallel_pages: int = 5             # 最大并行页数
bulk_search_workers: int = 20           # 批量搜索工作线程
```

## 启动服务

```bash
cd /root/twapi
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 30192 --workers 4
```

## 性能测试

```bash
# 搜索接口压力测试
python benchmark.py --endpoint search --query "python" --concurrent 100 --requests 500

# 用户接口压力测试
python benchmark.py --endpoint user --username "elonmusk" --concurrent 50 --requests 200

# 推文批量获取测试
python benchmark.py --endpoint tweets --username "elonmusk" --count 100 --concurrent 30 --requests 150

# 混合负载测试
python benchmark.py --endpoint mixed --concurrent 80 --requests 400
```

## 批量查询客户端

```python
import asyncio
from batch_client import BatchTwAPIClient

async def main():
    client = BatchTwAPIClient("http://localhost:30192")
    
    # 批量获取用户信息 (10并发)
    users = ["elonmusk", "github", "twitter", "google", "microsoft"]
    results = await client.batch_get_users(users, concurrent=10)
    for r in results:
        print(f"Success: {r.success}, Latency: {r.latency_ms:.0f}ms")
    
    # 批量搜索 (20工作线程)
    queries = ["python", "ai", "ml", "data", "cloud"]
    results = await client.bulk_search(queries, count=20, workers=20)
    
    await client.close()

asyncio.run(main())
```

## API 端点

| 端点 | 说明 |
|------|------|
| `GET /api/user/{username}` | 用户资料 |
| `GET /api/user/{username}/tweets` | 用户推文 |
| `GET /api/user/{username}/retweets` | 用户转推 |
| `GET /api/tweet/{username}/status/{id}` | 单条推文 |
| `GET /api/search?q=keyword` | 搜索推文 |
| `GET /api/search/users?q=keyword` | 搜索用户 |
| `GET /api/health` | 实例健康检查 |
| `GET /api/stats` | API 统计信息 |
| `GET /dashboard` | 统计面板 |

## 性能对比

| 指标 | 原版 | 高并发版 | 提升 |
|------|------|----------|------|
| 单实例并发 | 1 | 50 | 50x |
| 全局并发 | 无限制 | 1000 | 可控 |
| 实例选择 | 单实例 | 3实例竞争 | 3x |
| 连接复用 | 否 | 是 | 显著 |
| 分页获取 | 顺序 | 并行 | 5x |
| 熔断保护 | 无 | 有 | 更稳定 |

## 文件结构

```
twapi/
├── main.py              # FastAPI 主应用 (高并发版)
├── nitter_client.py     # Nitter 客户端 (连接池+熔断器)
├── config.py            # 配置 (新增并发参数)
├── models.py            # Pydantic 模型 (未修改)
├── parser.py            # HTML 解析 (未修改)
├── stats.py             # 统计中间件 (未修改)
├── dashboard.py         # 统计面板 (未修改)
├── benchmark.py         # 性能测试工具
├── batch_client.py      # 批量查询客户端
└── README.md            # 本文件
```
