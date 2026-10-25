from __future__ import annotations

from pathlib import Path

import pytest

import config
import database
from web_tools import (
    SearchResult,
    WebToolsError,
    WebToolsService,
    WebToolsSettings,
    reset_web_tools_service,
)


class _Response:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def _service(tmp_path: Path, monkeypatch) -> WebToolsService:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "WEB_TOOLS_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "WEB_TOOLS_EVENTS_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(config, "WEB_TOOLS_SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-test")
    database.init_db()
    reset_web_tools_service()
    monkeypatch.setattr("web_tools._resolve_host", lambda hostname, port: ["93.184.216.34"])
    service = WebToolsService()
    service.secrets.get = lambda provider, settings: ("sk-test", "environment")
    return service


def test_settings_defaults_and_validation() -> None:
    settings = WebToolsSettings()
    assert settings.provider == "deepseek"
    assert settings.default_count == 5
    with pytest.raises(ValueError):
        WebToolsSettings(base_url="file:///etc/passwd")
    with pytest.raises(ValueError):
        WebToolsSettings(max_qps=6)


def test_deepseek_search_parses_results_and_caches(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    service.save_settings(WebToolsSettings(cache_ttl_seconds=60))
    calls: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _Response(
            {
                "results": [
                    {
                        "title": "Example",
                        "url": "https://example.com",
                        "snippet": "short",
                        "summary": "long summary",
                        "site_name": "Example",
                        "authority": 3,
                        "rerank_score": 2.1,
                    }
                ]
            }
        )

    monkeypatch.setattr("web_tools.requests.post", fake_post)
    first = service.search("DeepSeek API", count=3, app="test")
    second = service.search("DeepSeek API", count=3, app="test")
    assert first.provider == "deepseek"
    assert first.results[0].summary == "long summary"
    assert first.cached is False
    assert second.cached is True
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/v1/tools/search")
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert calls[0]["json"]["count"] == 3


def test_deepseek_fetch_returns_markdown(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "web_tools.requests.post",
        lambda *args, **kwargs: _Response({"title": "Page", "content": "# Page\n\nBody"}),
    )
    result = service.fetch("https://example.com/page", app="test")
    assert result.title == "Page"
    assert result.content.startswith("# Page")


def test_deepseek_error_is_classified(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "web_tools.requests.post",
        lambda *args, **kwargs: _Response({"error": {"message": "quota"}}, status_code=402),
    )
    with pytest.raises(WebToolsError) as info:
        service.search("query", app="test")
    assert info.value.status_code == 402
    assert info.value.retryable is False


def test_search_rejects_long_query_and_out_of_range_count(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    with pytest.raises(WebToolsError, match="128"):
        service.search("x" * 129)
    with pytest.raises(WebToolsError, match="1–50"):
        service.search("query", count=51)
    with pytest.raises(WebToolsError, match="1–50"):
        service.search("query", count=0)


def test_fetch_rejects_invalid_url(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    with pytest.raises(WebToolsError):
        service.fetch("file:///etc/passwd")


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8500/api/system/busy",
        "http://127.0.0.1:8500/",
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1/",
    ],
)
def test_fetch_rejects_local_and_private_addresses(tmp_path: Path, monkeypatch, url: str) -> None:
    service = _service(tmp_path, monkeypatch)
    with pytest.raises(WebToolsError, match="本机|内网"):
        service.fetch(url)


def test_fetch_rejects_hostname_resolving_to_private_ip(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    monkeypatch.setattr("web_tools._resolve_host", lambda hostname, port: ["127.0.0.1"])
    with pytest.raises(WebToolsError, match="本机或内网"):
        service.fetch("https://internal.example.com/")


def test_fetch_normalizes_connection_error(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)

    def fail(*args, **kwargs):
        raise __import__("requests").ConnectionError("boom")

    monkeypatch.setattr("web_tools.requests.post", fail)
    with pytest.raises(WebToolsError) as info:
        service.fetch("https://example.com/page")
    assert info.value.retryable is True
    assert "ConnectionError" in str(info.value)


def test_fetch_many_respects_limit_and_deduplicates(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    service.save_settings(WebToolsSettings(max_fetch_per_query=2))
    calls: list[str] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json["url"])
        return _Response({"title": json["url"], "content": "body"})

    monkeypatch.setattr("web_tools.requests.post", fake_post)
    results = service.fetch_many(
        ["https://example.com/a", "https://example.com/a", "https://example.com/b", "https://example.com/c"],
        app="test",
    )
    assert len(results) == 2
    assert calls == ["https://example.com/a", "https://example.com/b"]


def test_events_record_cache_hits_and_failures(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    service.save_settings(WebToolsSettings(cache_ttl_seconds=60))
    monkeypatch.setattr(
        "web_tools.requests.post",
        lambda *args, **kwargs: _Response({"results": [{"title": "A", "url": "https://example.com"}]}),
    )
    service.search("cache me", app="test")
    service.search("cache me", app="test")
    monkeypatch.setattr(
        "web_tools.requests.post",
        lambda *args, **kwargs: _Response({"error": {"message": "no"}}, status_code=402),
    )
    with pytest.raises(WebToolsError):
        service.search("fail me", app="test")
    import json

    events = [
        json.loads(line)
        for line in config.WEB_TOOLS_EVENTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["cached"] for event in events] == [False, True, False]
    assert events[-1]["ok"] is False
    assert events[-1]["status_code"] == 402
    assert all("cache me" not in json.dumps(event, ensure_ascii=False) for event in events)


def test_settings_api_does_not_return_api_key(client, monkeypatch) -> None:
    monkeypatch.setattr(config, "WEB_TOOLS_SECRETS_PATH", Path("unused.json"))
    reset_web_tools_service()
    response = client.get("/api/settings/web-tools")
    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["provider"] == "deepseek"
    assert "api_key" not in payload
    assert "api_key_configured" in payload


def test_normalized_search_result_model() -> None:
    result = SearchResult(title="t", url="https://example.com", summary="s")
    assert result.summary == "s"
