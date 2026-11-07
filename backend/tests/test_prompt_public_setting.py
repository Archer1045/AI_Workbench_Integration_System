from __future__ import annotations

from web_tools import SearchResponse, SearchResult


def test_public_setting_lookup_returns_candidates_without_fetch(client, monkeypatch) -> None:
    class _Service:
        def search(self, query, **kwargs):
            assert query == "流萤 崩坏：星穹铁道"
            assert kwargs["app"] == "prompt-agent-public-setting"
            return SearchResponse(
                provider="deepseek",
                results=[
                    SearchResult(
                        title="流萤 - 官方角色页",
                        url="https://example.com/liuying",
                        summary="银白色短发，绿色眼睛，身穿格拉默铁骑制服。",
                        date="2026-10-01",
                        authority=3,
                    ),
                    SearchResult(
                        title="重复结果",
                        url="https://example.com/liuying#section",
                        summary="重复",
                        authority=3,
                    ),
                    SearchResult(
                        title="无摘要",
                        url="https://example.com/empty",
                        summary="",
                        authority=3,
                    ),
                    SearchResult(
                        title="百度百科重复",
                        url="https://baike.baidu.com/item/流萤?bst=123&fromModule=lemma",
                        summary="重复条目",
                        authority=3,
                    ),
                    SearchResult(
                        title="百度百科重复",
                        url="https://baike.baidu.com/item/流萤?bst=456&fromModule=lemma",
                        summary="重复条目",
                        authority=3,
                    ),
                ],
            )

        def fetch(self, *args, **kwargs):
            raise AssertionError("公开设定查询不应抓取整页")

    monkeypatch.setattr("routers.prompt.get_web_tools_service", lambda: _Service())
    response = client.post(
        "/api/prompt-agent/public-setting-lookup",
        json={"query": "流萤 崩坏：星穹铁道", "count": 6},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 2
    assert payload["results"][0]["url"] == "https://example.com/liuying"
    assert sum("baike.baidu.com" in item["url"] for item in payload["results"]) == 1
    assert "content" not in payload["results"][0]
    assert "不自动覆盖" in payload["note"]


def test_public_setting_lookup_rejects_empty_query(client) -> None:
    response = client.post("/api/prompt-agent/public-setting-lookup", json={"query": "  "})
    assert response.status_code == 400
