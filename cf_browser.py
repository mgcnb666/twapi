"""Background Chromium browser for Cloudflare-protected Nitter instances.

Uses SeleniumBase UC (Undetected Chrome) with Xvfb virtual display to
solve Cloudflare managed challenges. All browser ops run in a single
dedicated worker thread for lifecycle safety.
"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
import time

log = logging.getLogger(__name__)

_DISPLAY = ":90"


class CloudflareBrowser:
    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._started = False
        self._thread: threading.Thread | None = None
        self._xvfb: subprocess.Popen | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        if self._started:
            return
        # Clean up stale lock file
        lock = f"/tmp/.X{_DISPLAY.replace(':', '')}-lock"
        try:
            os.remove(lock)
        except FileNotFoundError:
            pass
        self._xvfb = subprocess.Popen(
            ["Xvfb", _DISPLAY, "-screen", "0", "1920x1080x24"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = _DISPLAY
        time.sleep(0.5)
        self._thread = threading.Thread(target=self._worker, daemon=True, name="cf-browser")
        self._thread.start()
        self._started = True
        log.info("CloudflareBrowser started (display=%s)", _DISPLAY)

    def stop(self) -> None:
        if not self._started:
            return
        self._q.put(None)
        if self._thread:
            self._thread.join(timeout=15)
        if self._xvfb:
            self._xvfb.terminate()
            self._xvfb = None
        self._started = False

    def _worker(self) -> None:
        from seleniumbase import SB

        sb_ctx = None
        sb = None
        solved: set[str] = set()

        try:
            sb_ctx = SB(uc=True, headed=True, headless=False)
            sb = sb_ctx.__enter__()
            self._ready.set()
            log.info("CloudflareBrowser: Chrome ready")
        except Exception as exc:
            log.error("Chrome launch failed: %s", exc)
            self._ready.set()
            return

        while True:
            try:
                item = self._q.get(timeout=600)
            except queue.Empty:
                continue
            if item is None:
                break

            url, result = item
            base = _base(url)
            try:
                if base not in solved:
                    html = _solve(sb, url)
                    if html and "just a moment" not in html[:2000].lower():
                        solved.add(base)
                        result["html"] = html
                    else:
                        result["html"] = None
                else:
                    sb.open(url)
                    time.sleep(2)
                    if "just a moment" in sb.get_title().lower():
                        solved.discard(base)
                        html = _solve(sb, url)
                        if html and "just a moment" not in html[:2000].lower():
                            solved.add(base)
                            result["html"] = html
                        else:
                            result["html"] = None
                    else:
                        result["html"] = sb.get_page_source()
            except Exception as exc:
                log.error("Worker error: %s", exc)
                result["html"] = None
                try:
                    sb_ctx.__exit__(None, None, None)
                except Exception:
                    pass
                try:
                    sb_ctx = SB(uc=True, headed=True, headless=False)
                    sb = sb_ctx.__enter__()
                    solved.clear()
                    log.info("Browser restarted")
                except Exception:
                    log.error("Browser restart failed")
                    break
            finally:
                result["done"].set()

        if sb_ctx:
            try:
                sb_ctx.__exit__(None, None, None)
            except Exception:
                pass

    def fetch(self, url: str, timeout: float = 90.0) -> str | None:
        if not self._started:
            return None
        if not self._ready.wait(timeout=30):
            return None
        result: dict = {"html": None, "done": threading.Event()}
        self._q.put((url, result))
        result["done"].wait(timeout=timeout)
        return result["html"]

    def is_available(self) -> bool:
        return self._started and self._ready.is_set()


def _base(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _solve(sb, url: str) -> str | None:
    try:
        sb.uc_open_with_reconnect(url, reconnect_time=12)
    except Exception as exc:
        log.warning("uc_open_with_reconnect: %s", exc)
        return None
    for _ in range(4):
        if "just a moment" not in sb.get_title().lower():
            return sb.get_page_source()
        try:
            sb.uc_gui_click_captcha()
        except Exception:
            pass
        time.sleep(4)
    if "just a moment" not in sb.get_title().lower():
        return sb.get_page_source()
    return None


browser = CloudflareBrowser()
