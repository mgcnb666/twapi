import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import dashboard
import main
import stats
from models import Tweet
from parser import parse_tweets
from nitter_client import NitterClient


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.cookies = {}

    async def get(self, *args, **kwargs):
        return self.response


def test_stats_endpoints_require_dashboard_auth():
    client = TestClient(main.app)

    stats_response = client.get("/api/stats")
    recent_response = client.get("/api/stats/recent")

    assert stats_response.status_code == 401
    assert recent_response.status_code == 401
    assert stats_response.headers["www-authenticate"].startswith("Basic")


def test_default_admin_admin_credentials_are_not_accepted_without_env():
    client = TestClient(main.app)

    response = client.get("/dashboard", auth=("admin", "admin"))

    assert response.status_code == 401


def test_dashboard_escapes_endpoint_names_before_inner_html_rendering():
    assert "${esc(e.endpoint)}" in dashboard.DASHBOARD_HTML


def test_parallel_pagination_does_not_issue_duplicate_first_page_requests(monkeypatch):
    requests_seen = []

    async def fake_fetch_parallel(requests):
        requests_seen.extend(requests)
        return [("PARALLEL", "https://nitter.test") for _ in requests]

    async def fake_fetch(path, params=None):
        requests_seen.append((path, params))
        if params and params.get("cursor") == "CUR1":
            return "PAGE2", "https://nitter.test"
        return "PAGE1", "https://nitter.test"

    def fake_parse(html, base):
        if html == "PAGE1":
            return [Tweet(id="1", author="a", text="one")], "CUR1"
        if html == "PAGE2":
            return [Tweet(id="2", author="a", text="two")], "CUR2"
        return [Tweet(id="parallel", author="a", text="duplicate")], "CURX"

    monkeypatch.setattr(main.client, "fetch", fake_fetch)
    monkeypatch.setattr(main.client, "fetch_parallel", fake_fetch_parallel)
    monkeypatch.setattr(main, "parse_tweets", fake_parse)
    monkeypatch.setattr(main.settings, "enable_parallel_pagination", True)
    monkeypatch.setattr(main.settings, "max_parallel_pages", 3)

    tweets, cursor = asyncio.run(main._fetch_tweets_multi("/u", None, 40))

    assert [t.id for t in tweets] == ["1", "2"]
    assert requests_seen == [("/u", None), ("/u", {"cursor": "CUR1"})]


def test_stats_time_window_uses_real_datetime_not_lexicographic_text(tmp_path, monkeypatch):
    db_path = tmp_path / "api_stats.db"
    monkeypatch.setattr(stats, "DB_PATH", str(db_path))
    tracker = stats.StatsTracker()
    tracker.init_db()
    conn = tracker._conn()

    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=2)
    recent = now - timedelta(minutes=10)
    for ts, path, endpoint in [
        (old.isoformat(), "/old", "old"),
        (recent.isoformat(), "/recent", "recent"),
    ]:
        conn.execute(
            """INSERT INTO api_calls
               (timestamp, method, path, endpoint, query, status_code,
                latency_ms, client_ip, user_agent, error)
               VALUES (?, 'GET', ?, ?, '', 200, 1.0, '', '', '')""",
            (ts, path, endpoint),
        )
    conn.commit()

    summary = tracker.get_summary(hours=1)

    assert summary["total_calls"] == 1
    assert summary["top_paths"] == [{"path": "/recent", "calls": 1}]


def test_retweet_detection_uses_timeline_item_scope():
    html = """
    <div class="timeline-item">
      <div class="retweet-header">Retweeted</div>
      <a class="tweet-link" href="/alice/status/1234567890"></a>
      <div class="tweet-body">
        <div class="tweet-header"><a class="username">@alice</a><a class="fullname">Alice</a></div>
        <div class="tweet-content">hello</div>
      </div>
    </div>
    """

    tweets, _ = parse_tweets(html, "https://nitter.test")

    assert len(tweets) == 1
    assert tweets[0].is_retweet is True


def test_overlong_cursor_is_rejected():
    client = TestClient(main.app)

    response = client.get("/api/search", params={"q": "x", "cursor": "a" * 1001})

    assert response.status_code == 400
    assert "Cursor too long" in response.text


def test_all_true_requires_dashboard_auth_before_fetch(monkeypatch):
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("expensive all=true fetch should not run without auth")

    monkeypatch.setattr(main, "_fetch_all_tweets", fail_if_called)
    client = TestClient(main.app)

    response = client.get("/api/search", params={"q": "x", "all": "true"})

    assert response.status_code == 401


def test_upstream_404_html_is_returned_to_parser_without_circuit_failure(monkeypatch):
    base = "https://nitter.test"
    monkeypatch.setattr(main.settings, "instances", [base])
    client = NitterClient()
    client._sessions[base] = FakeSession(FakeResponse(404, "<html>not found</html>"))

    result = asyncio.run(client._fetch_single(base, "/missing", None))

    assert result == ("<html>not found</html>", base)
    assert client._circuit_breakers[base].failures == 0
