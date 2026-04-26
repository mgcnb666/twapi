"""High-concurrency Nitter HTTP client with instance rotation, connection pooling,
circuit breaker pattern, and anti-bot bypass.

Supports three bypass strategies:
- Anubis preact: SHA-256 hash of challenge string
- Anubis fast PoW: Brute-force nonce for leading-zero hash
- Cloudflare managed challenge: Background Chrome browser (SeleniumBase UC)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import time
from typing import Any
from urllib.parse import urlencode

from curl_cffi.requests import AsyncSession

from config import settings

log = logging.getLogger("twapi.nitter_client")

# Instances known to use Cloudflare managed challenges
CF_INSTANCES = {
    "https://lightbrd.com",
    "https://nitter.space",
    "https://nuku.trabun.org",
}


class CircuitBreaker:
    """Simple circuit breaker for instance health."""

    def __init__(self, fail_threshold: int, recovery_time: float):
        self.fail_threshold = fail_threshold
        self.recovery_time = recovery_time
        self.failures = 0
        self.last_failure = 0.0
        self._open = False
        self._lock = asyncio.Lock()

    async def record_success(self) -> None:
        async with self._lock:
            self.failures = 0
            self._open = False

    async def record_failure(self) -> bool:
        """Returns True if circuit is now open."""
        async with self._lock:
            now = time.monotonic()
            if self._open and now - self.last_failure < self.recovery_time:
                return True
            self.failures += 1
            self.last_failure = now
            if self.failures >= self.fail_threshold:
                self._open = True
                return True
            return False

    async def can_try(self) -> bool:
        async with self._lock:
            if not self._open:
                return True
            now = time.monotonic()
            if now - self.last_failure >= self.recovery_time:
                self._open = False
                self.failures = 0
                return True
            return False


class NitterClient:
    """High-concurrency Nitter client with:
    - Per-instance connection pools
    - Semaphore-based concurrency limiting
    - Circuit breaker pattern
    - Parallel instance fetching (race mode)
    """

    def __init__(self) -> None:
        self._instances = list(settings.instances)
        self._health: dict[str, float] = {u: 0.0 for u in self._instances}
        self._circuit_breakers: dict[str, CircuitBreaker] = {
            u: CircuitBreaker(settings.circuit_breaker_failures, settings.circuit_breaker_recovery)
            for u in self._instances
        }
        self._lock = asyncio.Lock()
        self._cookies: dict[str, dict[str, str]] = {u: {} for u in self._instances}
        self._cf_browser = None  # lazy import
        self._health_task: asyncio.Task | None = None

        # Global concurrency limit across all instances
        self._global_sem = asyncio.Semaphore(settings.max_concurrent_requests)
        # Per-instance concurrency limits
        self._instance_sems: dict[str, asyncio.Semaphore] = {
            u: asyncio.Semaphore(settings.instance_concurrent_limit) for u in self._instances
        }
        # Per-instance connection pools (persistent sessions)
        self._sessions: dict[str, AsyncSession | None] = {u: None for u in self._instances}

    # ---- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        if settings.enable_cf_browser:
            try:
                asyncio.get_event_loop().run_in_executor(None, self._init_cf_browser)
            except Exception:
                pass
        # Pre-warm connection pools
        await asyncio.gather(*(self._warm_pool(u) for u in self._instances), return_exceptions=True)
        self._health_task = asyncio.create_task(self._health_loop())

    async def _warm_pool(self, instance: str) -> None:
        """Initialize persistent session for an instance."""
        try:
            session = self._make_session(instance)
            self._sessions[instance] = session
            log.debug("Connection pool warmed for %s", instance)
        except Exception as exc:
            log.warning("Failed to warm pool for %s: %s", instance, exc)

    def _init_cf_browser(self) -> None:
        try:
            from cf_browser import browser
            browser.start()
            self._cf_browser = browser
            for url in self._instances:
                if self._is_cf_instance(url):
                    self._health[url] = 5000.0
            log.info("CloudflareBrowser started")
        except Exception as exc:
            log.warning("CloudflareBrowser failed to start: %s", exc)
            self._cf_browser = None

    async def close(self) -> None:
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        for session in self._sessions.values():
            if session:
                try:
                    await session.close()
                except Exception:
                    pass
        if self._cf_browser:
            try:
                self._cf_browser.stop()
            except Exception:
                pass

    def _make_session(self, instance: str) -> AsyncSession:
        s = AsyncSession(
            impersonate="chrome124",
            timeout=settings.fetch_timeout,
        )
        for name, val in self._cookies.get(instance, {}).items():
            s.cookies.set(name, val)
        return s

    def _get_session(self, instance: str) -> AsyncSession:
        """Get or create persistent session for instance."""
        session = self._sessions.get(instance)
        if session is None:
            session = self._make_session(instance)
            self._sessions[instance] = session
        return session

    def _save_cookies(self, instance: str, session: AsyncSession) -> None:
        stored = self._cookies.setdefault(instance, {})
        for name, val in session.cookies.items():
            stored[name] = val
        # Limit cookie size per instance to prevent unbounded growth
        if len(stored) > 50:
            # Remove oldest entries (simple: keep last 50)
            keys = list(stored.keys())
            for k in keys[:-50]:
                del stored[k]

    def _close_and_remove_session(self, instance: str) -> None:
        """Force-close a session and remove it from the pool."""
        session = self._sessions.pop(instance, None)
        if session:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(session.close())
                else:
                    loop.run_until_complete(session.close())
            except Exception:
                pass

    # ---- instance selection -------------------------------------------------

    def _pick_instance(self, exclude: set[str] | None = None) -> str | None:
        """Pick a healthy instance, weighted by latency."""
        exclude = exclude or set()
        healthy = [
            u for u, lat in self._health.items()
            if lat >= 0 and u not in exclude
        ]
        if not healthy:
            # Fallback: try any instance not in exclude
            candidates = [u for u in self._instances if u not in exclude]
            if not candidates:
                return None
            return random.choice(candidates)
        weights = [1.0 / max(self._health.get(u, 1), 1) for u in healthy]
        return random.choices(healthy, weights=weights, k=1)[0]

    async def _get_healthy_instances(self, count: int = 3) -> list[str]:
        """Get multiple healthy instances for parallel fetching."""
        healthy = [
            u for u, lat in self._health.items()
            if lat >= 0 and await self._circuit_breakers[u].can_try()
        ]
        if not healthy:
            healthy = list(self._instances)
        # Sort by latency, take top N
        healthy.sort(key=lambda u: self._health.get(u, float('inf')))
        # Return more instances to increase chance of success
        return healthy[:max(count, 5)]

    # ---- Anubis challenge solvers -------------------------------------------

    @staticmethod
    def _solve_anubis_preact(html: str) -> tuple[str, str] | None:
        m = re.search(r'id="preact_info"[^>]*>\s*(\{.*?\})\s*<', html)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
        challenge = data.get("challenge", "")
        redir = data.get("redir", "")
        if not challenge or not redir:
            return None
        result = hashlib.sha256(challenge.encode()).hexdigest()
        return redir + "&result=" + result, ""

    @staticmethod
    def _solve_anubis_fast_sync(cdata: dict, path: str) -> tuple[str, dict[str, str]] | None:
        """Synchronous CPU-bound PoW solver (run in executor)."""
        rules = cdata.get("rules", {})
        challenge = cdata.get("challenge", {})
        difficulty = rules.get("difficulty", challenge.get("difficulty", 1))
        random_data = challenge.get("randomData", "")
        challenge_id = challenge.get("id", "")
        if not random_data or not challenge_id:
            return None

        t0 = time.time()
        deadline = t0 + 8.0  # max 8 seconds
        full_bytes = difficulty // 2
        check_nibble = difficulty % 2 != 0

        for nonce in range(10_000_000):
            if time.time() > deadline:
                return None
            h = hashlib.sha256((random_data + str(nonce)).encode()).digest()
            ok = all(h[i] == 0 for i in range(full_bytes))
            if ok and check_nibble and (h[full_bytes] >> 4) != 0:
                ok = False
            if ok:
                elapsed = int((time.time() - t0) * 1000)
                params = {
                    "id": challenge_id,
                    "response": h.hex(),
                    "nonce": str(nonce),
                    "redir": path,
                    "elapsedTime": str(max(elapsed, 100)),
                }
                return "/.within.website/x/cmd/anubis/api/pass-challenge", params
        return None

    async def _try_solve_anubis(self, session: AsyncSession, base: str, path: str, html: str) -> bool:
        preact = self._solve_anubis_preact(html)
        if preact:
            url_path, _ = preact
            await session.get(
                base.rstrip("/") + url_path,
                allow_redirects=True,
                timeout=settings.request_timeout,
            )
            self._save_cookies(base, session)
            return True

        m = re.search(r'id="anubis_challenge"[^>]*>(\{.*?\})\s*<', html, re.DOTALL)
        if not m:
            return False
        try:
            cdata = json.loads(m.group(1))
        except json.JSONDecodeError:
            return False

        loop = asyncio.get_event_loop()
        try:
            fast = await asyncio.wait_for(
                loop.run_in_executor(None, self._solve_anubis_fast_sync, cdata, "/" + path.lstrip("/")),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            log.warning("Anubis fast PoW timed out for %s", base)
            return False

        if fast:
            url_path, params = fast
            await session.get(
                base.rstrip("/") + url_path,
                params=params,
                allow_redirects=True,
                timeout=settings.request_timeout,
            )
            self._save_cookies(base, session)
            return True
        return False

    # ---- Cloudflare browser fetch -------------------------------------------

    async def _fetch_via_browser(self, base: str, path: str, params: dict[str, Any] | None) -> str | None:
        if not self._cf_browser or not self._cf_browser.is_available():
            return None
        url = base.rstrip("/") + "/" + path.lstrip("/")
        if params:
            url += "?" + urlencode(params)
        try:
            html = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, self._cf_browser.fetch, url
                ),
                timeout=90.0,
            )
            return html
        except asyncio.TimeoutError:
            log.warning("CF browser timeout for %s", url)
            return None

    def _is_cf_instance(self, base: str) -> bool:
        # Runtime detection: check if instance recently returned CF challenge
        if base in CF_INSTANCES:
            return True
        # Dynamic detection: if health check shows CF page, mark as CF
        # (health check already detects this via _is_cf_page)
        return False

    # ---- core fetch ---------------------------------------------------------

    async def _fetch_single(
        self,
        base: str,
        path: str,
        params: dict[str, Any] | None,
    ) -> tuple[str, str] | None:
        """Fetch from a single instance. Returns (html, base) or None on failure."""
        # Check circuit breaker
        if not await self._circuit_breakers[base].can_try():
            return None

        async with self._instance_sems[base]:  # Per-instance limit
            # Cloudflare instance: use browser
            if self._is_cf_instance(base):
                try:
                    html = await self._fetch_via_browser(base, path, params)
                    if html and not _is_antibot_page(html) and not _is_cf_page(html):
                        await self._circuit_breakers[base].record_success()
                        return html, base
                    await self._circuit_breakers[base].record_failure()
                    return None
                except Exception as exc:
                    log.error("CF browser exception for %s: %s", base, exc)
                    await self._circuit_breakers[base].record_failure()
                    return None

            # Normal instance: use persistent session
            url = base.rstrip("/") + "/" + path.lstrip("/")
            try:
                session = self._get_session(base)
                resp = await session.get(url, params=params, timeout=settings.request_timeout)
                html = resp.text

                if _is_anubis_page(html):
                    solved = await self._try_solve_anubis(session, base, "/" + path.lstrip("/"), html)
                    if solved:
                        resp = await session.get(url, params=params, timeout=settings.request_timeout)
                        html = resp.text
                        self._save_cookies(base, session)
                        if not _is_antibot_page(html) and not _is_anubis_page(html):
                            await self._circuit_breakers[base].record_success()
                            return html, base
                    await self._circuit_breakers[base].record_failure()
                    return None

                if _is_antibot_page(html):
                    await self._circuit_breakers[base].record_failure()
                    return None

                if resp.status_code >= 500:
                    await self._circuit_breakers[base].record_failure()
                    return None

                self._save_cookies(base, session)
                await self._circuit_breakers[base].record_success()
                return html, base

            except Exception as exc:
                log.error("Request exception for %s%s: %s", base, path, exc)
                await self._circuit_breakers[base].record_failure()
                # Force-close session on repeated failures to prevent stale connections
                cb = self._circuit_breakers[base]
                if cb.failures >= cb.fail_threshold - 1:
                    self._close_and_remove_session(base)
                return None

    async def fetch(self, path: str, params: dict[str, Any] | None = None) -> tuple[str, str]:
        """High-concurrency fetch with parallel instance racing."""
        async with self._global_sem:
            instances = await self._get_healthy_instances(count=3)
            if not instances:
                instances = list(self._instances)

            tasks = [
                asyncio.create_task(self._fetch_single(inst, path, params))
                for inst in instances
            ]

            pending = set(tasks)
            errors: list[Exception] = []
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    try:
                        result = task.result()
                        if result is not None:
                            # Cancel remaining tasks and await to suppress CancelledError
                            for t in pending:
                                t.cancel()
                            if pending:
                                await asyncio.gather(*pending, return_exceptions=True)
                            return result
                    except Exception as exc:
                        errors.append(exc)
                        log.warning("Instance failed for %s: %s", path, exc)

            # All failed
            last_error = errors[-1] if errors else None
            log.error("All Nitter instances failed for %s (tried %s). Errors: %s",
                      path, instances, [str(e) for e in errors])
            raise last_error or RuntimeError("All Nitter instances failed")

    # ---- parallel batch fetch -----------------------------------------------

    async def fetch_parallel(
        self,
        requests: list[tuple[str, dict[str, Any] | None]],
    ) -> list[tuple[str, str] | None]:
        """Fetch multiple pages in parallel.
        requests: list of (path, params) tuples
        Returns: list of (html, base) or None results
        """
        # DoS protection: limit request batch size
        MAX_PARALLEL = 50
        if len(requests) > MAX_PARALLEL:
            log.warning("fetch_parallel batch truncated from %d to %d", len(requests), MAX_PARALLEL)
            requests = requests[:MAX_PARALLEL]

        async with self._global_sem:
            # Distribute requests across instances
            instances = await self._get_healthy_instances(count=min(len(requests), 5))
            if not instances:
                instances = list(self._instances)

            tasks = []
            for i, (path, params) in enumerate(requests):
                inst = instances[i % len(instances)]
                task = asyncio.create_task(self._fetch_single(inst, path, params))
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            return [
                r if not isinstance(r, Exception) else None
                for r in results
            ]

    # ---- health check -------------------------------------------------------

    async def _check_one(self, url: str) -> None:
        if self._is_cf_instance(url):
            return
        if not await self._circuit_breakers[url].can_try():
            return
        try:
            session = self._get_session(url)
            t0 = time.monotonic()
            # Use root path instead of hardcoded user for health check
            resp = await session.get(url.rstrip("/") + "/", timeout=8.0)
            html = resp.text

            if _is_anubis_page(html):
                solved = await self._try_solve_anubis(session, url, "/", html)
                if solved:
                    resp = await session.get(url.rstrip("/") + "/", timeout=8.0)
                    html = resp.text
                    self._save_cookies(url, session)

            latency = (time.monotonic() - t0) * 1000
            if resp.status_code < 400 and not _is_antibot_page(html) and not _is_anubis_page(html):
                async with self._lock:
                    self._health[url] = latency
                await self._circuit_breakers[url].record_success()
            else:
                async with self._lock:
                    self._health[url] = -1
                await self._circuit_breakers[url].record_failure()
        except Exception as exc:
            log.debug("Health check exception for %s: %s", url, exc)
            async with self._lock:
                self._health[url] = -1
            await self._circuit_breakers[url].record_failure()

    async def check_health(self) -> dict[str, float]:
        await asyncio.gather(*(self._check_one(u) for u in self._instances))
        return dict(self._health)

    async def _health_loop(self) -> None:
        while True:
            try:
                await asyncio.gather(*(self._check_one(u) for u in self._instances))
            except Exception:
                pass
            try:
                await asyncio.sleep(settings.health_check_interval)
            except asyncio.CancelledError:
                break


# ---------------------------------------------------------------------------
# Anti-bot detection helpers
# ---------------------------------------------------------------------------

_ANTIBOT_MARKERS = [
    "just a moment",
    "checking your browser",
    "enable javascript",
    "challenge-platform",
    "cf-browser-verification",
]


def _is_anubis_page(html: str) -> bool:
    lower = html[:5000].lower()
    return ("making sure you" in lower and "not a bot" in lower) or "anubis_challenge" in html[:5000]


def _is_cf_page(html: str) -> bool:
    lower = html[:3000].lower()
    return "just a moment" in lower and ("challenge-platform" in lower or "_cf_chl" in html[:5000])


def _is_antibot_page(html: str) -> bool:
    if _is_anubis_page(html):
        return False
    lower = html[:3000].lower()
    return any(marker in lower for marker in _ANTIBOT_MARKERS)


# module-level singleton
client = NitterClient()
