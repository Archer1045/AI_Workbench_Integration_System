"""提示词 AI 语义校验开关接口测试。"""
from __future__ import annotations


def test_semantic_check_default_off(client):
    response = client.get("/api/settings/prompt-semantic-check")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}


def test_semantic_check_toggle(client):
    enabled = client.post("/api/settings/prompt-semantic-check", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json() == {"enabled": True}
    disabled = client.post("/api/settings/prompt-semantic-check", json={"enabled": False})
    assert disabled.json() == {"enabled": False}


def test_parse_semantic_items_valid_fenced_json():
    from routers.prompt import parse_semantic_items

    text = '```json\n[{"type":"warning","message":"环境矛盾"},{"type":"error","message":"人数矛盾"}]\n```'
    assert parse_semantic_items(text) == [
        {"type": "warning", "message": "环境矛盾"},
        {"type": "error", "message": "人数矛盾"},
    ]


def test_parse_semantic_items_invalid_returns_empty():
    from routers.prompt import parse_semantic_items

    assert parse_semantic_items("没有数组内容") == []
    assert parse_semantic_items('[{"type":"debug","message":"x"}]') == []


def test_parse_semantic_items_trims_to_five():
    from routers.prompt import parse_semantic_items

    text = "[" + ",".join(f'{{"type":"warning","message":"i{n}"}}' for n in range(8)) + "]"
    assert len(parse_semantic_items(text)) == 5
