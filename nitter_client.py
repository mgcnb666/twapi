"""Nitter HTTP client with instance rotation, health checks, and anti-bot bypass.

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

log = logging.getLogger(__name__)

# Instances known to use Cloudflare managed challenges
CF_INSTANCES = {
    "https://lightbrd.com",
    "https://nitter.space",
    "https://nuku.trabun.org",
}


class NitterClient:
    """Manages multiple Nitter instances with health-aware rotation and
    automatic Anubis / Cloudflare challenge solving."""

    def __init__(self) -> None:
        self._instances = list(settings.instances)
        self._health: dict[str, float] = {u: 0.0 for u in self._instances}
        self._lock = asyncio.Lock()
        self._cookies: dict[str, dict[str, str]] = {u: {} for u in self._instances}
        self._cf_browser = None  # lazy import to avoid startup cost

    # ---- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        # Start CF browser in background thread first (non-blocking)
        asyncio.get_event_loop().run_in_executor(None, self._init_cf_browser)
        # Start health loop (checks non-CF instances immediately, CF later)
        asyncio.create_task(self._health_loop())

    def _init_cf_browser(self) -> None:
        try:
            from cf_browser import browser
            browser.start()
            self._cf_browser = browser
            log.info("CloudflareBrowser started")
        except Exception as exc:
            log.warning("CloudflareBrowser failed to start: %s", exc)

    async def close(self) -> None:
        if self._cf_browser:
            try:
                self._cf_browser.stop()
            except Exception:
                pass

    def _make_session(self, instance: str) -> AsyncSession:
        s = AsyncSession(impersonate="chrome124")
        for name, val in self._cookies.get(instance, {}).items():
            s.cookies.set(name, val)
        return s

    def _save_cookies(self, instance: str, session: AsyncSession) -> None:
        stored = self._cookies.setdefault(instance, {})
        for name, val in session.cookies.items():
            stored[name] = val

    # ---- instance selection -------------------------------------------------

    def _pick_instance(self) -> str:
        healthy = [u for u, lat in self._health.items() if lat >= 0]
        if not healthy:
            healthy = list(self._instances)
        weights = [1.0 / max(self._health.get(u, 1), 1) for u in healthy]
        return random.choices(healthy, weights=weights, k=1)[0]

    # ---- Anubis challenge solvers -------------------------------------------

    @staticmethod
    def _solve_anubis_preact(html: str) -> tuple[str, str] | None:
        """Extract preact-style Anubis challenge and compute the answer.
        Returns (pass_url_suffix, _) or None."""
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
    def _solve_anubis_fast(html: str, path: str) -> tuple[str, dict[str, str]] | None:
        """Extract fast-style Anubis PoW challenge and brute-force nonce.
        Returns (pass_url_path, params_dict) or None."""
        m = re.search(r'id="anubis_challenge"[^>]*>(\{.*?\})\s*<', html, re.DOTALL)
        if not m:
            return None
        try:
            cdata = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
        rules = cdata.get("rules", {})
        challenge = cdata.get("challenge", {})
        difficulty = rules.get("difficulty", challenge.get("difficulty", 1))
        random_data = challenge.get("randomData", "")
        challenge_id = challenge.get("id", "")
        if not random_data or not challenge_id:
            return None

        t0 = time.time()
        full_bytes = difficulty // 2
        check_nibble = difficulty % 2 != 0

        for nonce in range(10_000_000):
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
        """Attempt to solve an Anubis challenge. Returns True on success."""
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

        fast = self._solve_anubis_fast(html, path)
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
        """Fetch a page through the Cloudflare browser backend."""
        if not self._cf_browser or not self._cf_browser.is_available():
            return None
        url = base.rstrip("/") + "/" + path.lstrip("/")
        if params:
            url += "?" + urlencode(params)
        html = await asyncio.get_event_loop().run_in_executor(
            None, self._cf_browser.fetch, url
        )
        return html

    def _is_cf_instance(self, base: str) -> bool:
        return base in CF_INSTANCES

    # ---- core fetch ---------------------------------------------------------

    async def fetch(self, path: str, params: dict[str, Any] | None = None) -> tuple[str, str]:
        """Fetch *path* from a healthy instance. Returns (html, base_url).

        Routes Cloudflare instances through the browser backend; all others
        use curl_cffi with Anubis challenge solving.
        """
        last_exc: Exception | None = None
        tried: set[str] = set()

        for _ in range(settings.max_retries):
            base = self._pick_instance()
            if base in tried:
                candidates = [u for u, lat in self._health.items() if lat >= 0 and u not in tried]
                if candidates:
                    base = random.choice(candidates)
            tried.add(base)

            # --- Cloudflare instance: use browser ---
            if self._is_cf_instance(base):
                try:
                    html = await self._fetch_via_browser(base, path, params)
                    if html and not _is_antibot_page(html) and not _is_cf_page(html):
                        return html, base
                    async with self._lock:
                        self._health[base] = -1
                    last_exc = RuntimeError(f"{base} CF browser fetch failed")
                except Exception as exc:
                    last_exc = exc
                    async with self._lock:
                        self._health[base] = -1
                continue

            # --- Normal / Anubis instance: use curl_cffi ---
            url = base.rstrip("/") + "/" + path.lstrip("/")
            try:
                async with self._make_session(base) as session:
                    resp = await session.get(url, params=params, timeout=settings.request_timeout)
                    html = resp.text

                    if _is_anubis_page(html):
                        solved = await self._try_solve_anubis(session, base, "/" + path.lstrip("/"), html)
                        if solved:
                            resp = await session.get(url, params=params, timeout=settings.request_timeout)
                            html = resp.text
                            self._save_cookies(base, session)
                            if not _is_antibot_page(html) and not _is_anubis_page(html):
                                return html, base
                        async with self._lock:
                            self._health[base] = -1
                        last_exc = RuntimeError(f"{base} Anubis challenge failed")
                        continue

                    if _is_antibot_page(html):
                        async with self._lock:
                            self._health[base] = -1
                        last_exc = RuntimeError(f"{base} returned anti-bot page")
                        continue

                    if resp.status_code >= 500:
                        async with self._lock:
                            self._health[base] = -1
                        last_exc = RuntimeError(f"{base} returned HTTP {resp.status_code}")
                        continue

                    self._save_cookies(base, session)
                    return html, base

            except Exception as exc:
                last_exc = exc
                async with self._lock:
                    self._health[base] = -1

        raise last_exc or RuntimeError("All Nitter instances failed")

    # ---- health check -------------------------------------------------------

    async def _check_one(self, url: str) -> None:
        """Health-check a non-CF instance via curl_cffi."""
        if self._is_cf_instance(url):
            return  # CF instances checked separately
        try:
            async with self._make_session(url) as session:
                t0 = time.monotonic()
                resp = await session.get(url.rstrip("/") + "/elonmusk", timeout=8.0)
                html = resp.text

                if _is_anubis_page(html):
                    solved = await self._try_solve_anubis(session, url, "/elonmusk", html)
                    if solved:
                        resp = await session.get(url.rstrip("/") + "/elonmusk", timeout=8.0)
                        html = resp.text
                        self._save_cookies(url, session)

                latency = (time.monotonic() - t0) * 1000
                if resp.status_code < 400 and not _is_antibot_page(html) and not _is_anubis_page(html):
                    async with self._lock:
                        self._health[url] = latency
                else:
                    async with self._lock:
                        self._health[url] = -1
        except Exception:
            async with self._lock:
                self._health[url] = -1

    async def _check_cf_instances(self) -> None:
        """Check CF instances sequentially through the browser."""
        if not self._cf_browser or not self._cf_browser.is_available():
            return
        cf_list = [u for u in self._instances if self._is_cf_instance(u)]
        for url in cf_list:
            try:
                t0 = time.monotonic()
                test_url = url.rstrip("/") + "/elonmusk"
                loop = asyncio.get_event_loop()
                html = await asyncio.wait_for(
                    loop.run_in_executor(None, self._cf_browser.fetch, test_url),
                    timeout=90.0,
                )
                latency = (time.monotonic() - t0) * 1000
                if html and "profile-card" in html and not _is_cf_page(html):
                    async with self._lock:
                        self._health[url] = latency
                else:
                    async with self._lock:
                        self._health[url] = -1
            except Exception as exc:
                log.debug("CF check failed for %s: %s", url, exc)
                async with self._lock:
                    self._health[url] = -1

    async def check_health(self) -> dict[str, float]:
        """Check non-CF instances. CF status uses cached values."""
        await asyncio.gather(*(self._check_one(u) for u in self._instances))
        return dict(self._health)

    async def _health_loop(self) -> None:
        # First check non-CF instances quickly
        try:
            await asyncio.gather(*(self._check_one(u) for u in self._instances))
        except Exception:
            pass

        # Wait for CF browser to be ready, then do initial CF solve
        for _ in range(30):
            await asyncio.sleep(2)
            if self._cf_browser and self._cf_browser.is_available():
                break
        try:
            await self._check_cf_instances()
        except Exception:
            pass

        cf_counter = 0
        while True:
            await asyncio.sleep(settings.health_check_interval)
            try:
                await asyncio.gather(*(self._check_one(u) for u in self._instances))
            except Exception:
                pass
            cf_counter += 1
            # Re-check CF instances every 5 cycles (~10 min)
            if cf_counter >= 5:
                cf_counter = 0
                try:
                    await self._check_cf_instances()
                except Exception:
                    pass


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
    """Return True if the page is an Anubis bot-check page."""
    lower = html[:5000].lower()
    return ("making sure you" in lower and "not a bot" in lower) or "anubis_challenge" in html[:5000]


def _is_cf_page(html: str) -> bool:
    """Return True if the page is a Cloudflare challenge page."""
    lower = html[:3000].lower()
    return "just a moment" in lower and ("challenge-platform" in lower or "_cf_chl" in html[:5000])


def _is_antibot_page(html: str) -> bool:
    """Return True if the page is a non-Anubis bot-check / captcha page."""
    if _is_anubis_page(html):
        return False
    lower = html[:3000].lower()
    return any(marker in lower for marker in _ANTIBOT_MARKERS)


# module-level singleton
client = NitterClient()
