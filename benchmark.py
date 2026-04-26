"""High-concurrency load test and benchmark for TwAPI.

Usage:
    python benchmark.py --endpoint search --query "python" --concurrent 50 --requests 200
    python benchmark.py --endpoint user --username "elonmusk" --concurrent 20 --requests 100
    python benchmark.py --endpoint tweets --username "elonmusk" --count 100 --concurrent 30 --requests 150
"""

import argparse
import asyncio
import time
import statistics
from dataclasses import dataclass, field
from typing import Optional

import aiohttp


@dataclass
class BenchmarkResult:
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    latencies: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def total_time(self) -> float:
        return self.end_time - self.start_time

    @property
    def rps(self) -> float:
        return self.total_requests / self.total_time if self.total_time > 0 else 0

    @property
    def success_rate(self) -> float:
        return self.successful / self.total_requests * 100 if self.total_requests > 0 else 0

    @property
    def avg_latency(self) -> float:
        return statistics.mean(self.latencies) if self.latencies else 0

    @property
    def min_latency(self) -> float:
        return min(self.latencies) if self.latencies else 0

    @property
    def max_latency(self) -> float:
        return max(self.latencies) if self.latencies else 0

    @property
    def p50_latency(self) -> float:
        return statistics.median(self.latencies) if self.latencies else 0

    @property
    def p99_latency(self) -> float:
        if not self.latencies:
            return 0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * 0.99)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    def print_report(self):
        print("\n" + "=" * 60)
        print("           HIGH-CONCURRENCY BENCHMARK REPORT")
        print("=" * 60)
        print(f"Total Requests:      {self.total_requests}")
        print(f"Successful:          {self.successful} ({self.success_rate:.1f}%)")
        print(f"Failed:              {self.failed}")
        print(f"Total Time:          {self.total_time:.2f}s")
        print(f"Requests/Second:     {self.rps:.1f}")
        print(f"Avg Latency:         {self.avg_latency:.1f}ms")
        print(f"Min Latency:         {self.min_latency:.1f}ms")
        print(f"P50 Latency:         {self.p50_latency:.1f}ms")
        print(f"P99 Latency:         {self.p99_latency:.1f}ms")
        print(f"Max Latency:         {self.max_latency:.1f}ms")
        if self.errors:
            print(f"\nTop Errors:")
            from collections import Counter
            for err, count in Counter(self.errors).most_common(5):
                print(f"  {count}x: {err[:80]}")
        print("=" * 60)


class TwAPIBenchmark:
    def __init__(self, base_url: str = "http://localhost:30192"):
        self.base_url = base_url.rstrip("/")
        self.results = BenchmarkResult()
        self._semaphore: Optional[asyncio.Semaphore] = None

    async def _fetch(self, session: aiohttp.ClientSession, url: str) -> dict:
        start = time.monotonic()
        try:
            async with self._semaphore:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    latency = (time.monotonic() - start) * 1000
                    self.results.latencies.append(latency)
                    if resp.status == 200:
                        self.results.successful += 1
                        return await resp.json()
                    else:
                        self.results.failed += 1
                        text = await resp.text()
                        self.results.errors.append(f"HTTP {resp.status}: {text[:100]}")
                        return {}
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            self.results.latencies.append(latency)
            self.results.failed += 1
            self.results.errors.append(str(e))
            return {}

    async def run_search_benchmark(
        self,
        query: str,
        concurrent: int,
        total_requests: int,
    ) -> BenchmarkResult:
        self.results = BenchmarkResult()
        self._semaphore = asyncio.Semaphore(concurrent)
        self.results.start_time = time.monotonic()

        urls = [
            f"{self.base_url}/api/search?q={query}&count=20"
            for _ in range(total_requests)
        ]

        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch(session, url) for url in urls]
            await asyncio.gather(*tasks, return_exceptions=True)

        self.results.end_time = time.monotonic()
        self.results.total_requests = total_requests
        return self.results

    async def run_user_benchmark(
        self,
        username: str,
        concurrent: int,
        total_requests: int,
    ) -> BenchmarkResult:
        self.results = BenchmarkResult()
        self._semaphore = asyncio.Semaphore(concurrent)
        self.results.start_time = time.monotonic()

        urls = [
            f"{self.base_url}/api/user/{username}"
            for _ in range(total_requests)
        ]

        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch(session, url) for url in urls]
            await asyncio.gather(*tasks, return_exceptions=True)

        self.results.end_time = time.monotonic()
        self.results.total_requests = total_requests
        return self.results

    async def run_tweets_benchmark(
        self,
        username: str,
        count: int,
        concurrent: int,
        total_requests: int,
    ) -> BenchmarkResult:
        self.results = BenchmarkResult()
        self._semaphore = asyncio.Semaphore(concurrent)
        self.results.start_time = time.monotonic()

        urls = [
            f"{self.base_url}/api/user/{username}/tweets?count={count}"
            for _ in range(total_requests)
        ]

        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch(session, url) for url in urls]
            await asyncio.gather(*tasks, return_exceptions=True)

        self.results.end_time = time.monotonic()
        self.results.total_requests = total_requests
        return self.results

    async def run_mixed_benchmark(
        self,
        concurrent: int,
        total_requests: int,
    ) -> BenchmarkResult:
        """Mixed workload: 40% search, 30% user, 30% tweets"""
        self.results = BenchmarkResult()
        self._semaphore = asyncio.Semaphore(concurrent)
        self.results.start_time = time.monotonic()

        import random
        endpoints = [
            ("search", f"{self.base_url}/api/search?q=python&count=20"),
            ("search", f"{self.base_url}/api/search?q=ai&count=20"),
            ("search", f"{self.base_url}/api/search?q=news&count=20"),
            ("user", f"{self.base_url}/api/user/elonmusk"),
            ("user", f"{self.base_url}/api/user/github"),
            ("tweets", f"{self.base_url}/api/user/elonmusk/tweets?count=40"),
        ]

        urls = [random.choice(endpoints)[1] for _ in range(total_requests)]

        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch(session, url) for url in urls]
            await asyncio.gather(*tasks, return_exceptions=True)

        self.results.end_time = time.monotonic()
        self.results.total_requests = total_requests
        return self.results


async def main():
    parser = argparse.ArgumentParser(description="TwAPI High-Concurrency Benchmark")
    parser.add_argument("--endpoint", choices=["search", "user", "tweets", "mixed"], default="search")
    parser.add_argument("--query", default="python")
    parser.add_argument("--username", default="elonmusk")
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--concurrent", type=int, default=50)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--url", default="http://localhost:30192")

    args = parser.parse_args()

    benchmark = TwAPIBenchmark(args.url)

    print(f"Starting benchmark: endpoint={args.endpoint}, concurrent={args.concurrent}, requests={args.requests}")

    if args.endpoint == "search":
        result = await benchmark.run_search_benchmark(args.query, args.concurrent, args.requests)
    elif args.endpoint == "user":
        result = await benchmark.run_user_benchmark(args.username, args.concurrent, args.requests)
    elif args.endpoint == "tweets":
        result = await benchmark.run_tweets_benchmark(args.username, args.count, args.concurrent, args.requests)
    else:
        result = await benchmark.run_mixed_benchmark(args.concurrent, args.requests)

    result.print_report()


if __name__ == "__main__":
    asyncio.run(main())
