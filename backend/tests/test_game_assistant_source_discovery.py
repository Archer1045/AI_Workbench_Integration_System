from __future__ import annotations

from pathlib import Path

import pytest

from game_assistant import router as game_router
from game_assistant import source_discovery
from game_assistant.source_domain import SourceDiscoverIngestRequest
from game_assistant.source_service import SourceManager
from game_assistant.source_store import SourceStore
from game_assistant.store import GameAssistantStore
from web_tools import FetchResponse, SearchResponse, SearchResult, WebToolsError


def _result(url: str, *, authority: int | None = 3) -> SearchResult:
    return SearchResult(
        title=url,
        url=url,
        summary="summary",
        date="2026-10-18",
        authority=authority,
        site_name="site",
    )


def test_filter_keeps_only_whitelisted_domains_and_drops_low_authority() -> None:
    items, filtered = source_discovery.filter_results(
        [
            _result("https://fgo.wiki/w/万圣节2026"),
            _result("https://api.biligame.com/news/18454.action"),
            _result("https://fgo.163.com/news/1.html"),
            _result("https://example.com/fgo"),
            _result("https://evil-fgo.wiki/w/x"),
            _result("https://fgo.wiki/w/low", authority=0),
        ]
    )
    assert [item["url"] for item in items] == [
        "https://fgo.wiki/w/万圣节2026",
        "https://api.biligame.com/news/18454.action",
        "https://fgo.163.com/news/1.html",
    ]
    assert [item["source_type"] for item in items] == ["wiki", "official", "official"]
    assert filtered == 3


def test_url_allowed_rejects_suffix_lookalikes() -> None:
    assert source_discovery.url_allowed("https://fgo.wiki/w/x")
    assert source_discovery.url_allowed("https://api.biligame.com/news/1.action")
    assert not source_discovery.url_allowed("https://evil-fgo.wiki/w/x")
    assert not source_discovery.url_allowed("https://fgo.wiki.example.com/w/x")
    assert not source_discovery.url_allowed("https://news.fate-go.jp/2026/10/halloween2026/")
    assert not source_discovery.url_allowed("file:///etc/passwd")


def test_discovery_uses_searches_and_returns_candidates(monkeypatch) -> None:
    calls: list[dict] = []

    class _Service:
        def search(self, query, **kwargs):
            calls.append({"query": query, **kwargs})
            return SearchResponse(
                provider="deepseek",
                results=[
                    _result("https://fgo.wiki/w/万圣节2026"),
                    _result("https://example.com/no"),
                ],
            )

    monkeypatch.setattr(source_discovery, "get_web_tools_service", lambda: _Service())
    payload = source_discovery.discover("FGO 国服 万圣节 2026", count=5, days=30)
    assert payload["provider"] == "deepseek"
    assert len(payload["results"]) == 1
    assert payload["filtered_out"] == 1
    assert calls[0]["app"] == "game-assistant-source-discover"
    assert "after:" in calls[0]["query"]
    assert calls[0]["ori_question"] == "FGO 国服 万圣节 2026"


def test_discovery_rejects_empty_query(monkeypatch) -> None:
    with pytest.raises(WebToolsError):
        source_discovery.discover("   ")


def test_ingest_discovered_source_saves_snapshot_without_publishing(tmp_path: Path, monkeypatch) -> None:
    manager = SourceManager(
        source_store=SourceStore(tmp_path / "sources"),
        game_store=GameAssistantStore(tmp_path / "ga.db"),
    )

    class _Service:
        def fetch(self, url, *, app="unknown"):
            assert url == "https://fgo.wiki/w/万圣节2026"
            assert app == "game-assistant-source-ingest"
            return FetchResponse(
                url=url,
                title="万圣节2026",
                content="# 万圣节2026\n\n正文\n\n![图](https://fgo.wiki/images/a.png)",
            )

    monkeypatch.setattr(game_router, "get_source_manager", lambda: manager)
    monkeypatch.setattr(game_router, "get_web_tools_service", lambda: _Service())
    record = game_router.ingest_discovered_source(
        SourceDiscoverIngestRequest(
            url="https://fgo.wiki/w/万圣节2026",
            source_type="wiki",
            title="万圣节2026",
        )
    )
    assert record.fetched_via == "url"
    assert record.content_type == "text/markdown"
    assert record.text.startswith("# 万圣节2026")
    assert record.images == ["https://fgo.wiki/images/a.png"]
    assert record.extraction is None
    assert record.published_revision is None


def test_ingest_discovered_source_rejects_non_whitelisted_url(monkeypatch) -> None:
    with pytest.raises(Exception) as info:
        game_router.ingest_discovered_source(
            SourceDiscoverIngestRequest(url="https://example.com/fgo")
        )
    assert "白名单" in str(info.value)


def test_extract_image_urls_deduplicates() -> None:
    text = "![a](https://fgo.wiki/a.png) ![a](https://fgo.wiki/a.png) https://fgo.wiki/b.webp"
    assert source_discovery.extract_image_urls(text) == [
        "https://fgo.wiki/a.png",
        "https://fgo.wiki/b.webp",
    ]


def test_normalize_fetched_page_unwraps_official_news_json() -> None:
    payload = (
        '{"data":{"title":"万圣节2026","content":'
        '"<p>活动时间</p><p>2026年10月17日</p>'
        '<img src=\\"https://i0.hdslb.com/a.png\\">"}}'
    )
    title, text, images = source_discovery.normalize_fetched_page("", payload)
    assert title == "万圣节2026"
    assert "活动时间" in text
    assert "2026年10月17日" in text
    assert images == ["https://i0.hdslb.com/a.png"]


def test_normalize_fetched_page_unwraps_markdown_escaped_json() -> None:
    payload = (
        '\\{\\"data\\"\\:\\{\\"title\\"\\:\\"万圣节2026\\"\\,'
        '\\"content\\"\\:\\"\\<p\\>活动时间\\<\\/p\\>\\"\\}\\}'
    )
    title, text, _ = source_discovery.normalize_fetched_page("", payload)
    assert title == "万圣节2026"
    assert "活动时间" in text
