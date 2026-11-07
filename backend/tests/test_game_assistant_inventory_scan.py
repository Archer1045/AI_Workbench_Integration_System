"""库存截图扫描（VLM 读数 → KB 匹配）回归测试：不调真 VLM、不读真图。"""
from __future__ import annotations

import json

import pytest

import config
from game_assistant import inventory_scan


@pytest.fixture()
def scan_env(tmp_path, monkeypatch):
    """临时 KB（含同名/别名两类边界）+ 三张假截图。"""
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "craft_essences_cn.json").write_text(json.dumps({
        "library": "craft_essences",
        "items": [
            {"id": 1, "collection_no": 67, "name": "2030年的碎片", "rarity": 5, "cost": 12,
             "atk_max": 0, "hp_max": 3000, "effects": [{"kind": "stars_per_turn", "value": 8}]},
            {"id": 2, "collection_no": 100, "name": "贝拉·丽莎", "rarity": 5, "cost": 12,
             "atk_max": 0, "hp_max": 0, "effects": []},
            {"id": 3, "collection_no": 101, "name": "同名礼装", "rarity": 4, "cost": 9,
             "atk_max": 0, "hp_max": 0, "effects": []},
            {"id": 4, "collection_no": 102, "name": "同名礼装", "rarity": 5, "cost": 12,
             "atk_max": 0, "hp_max": 0, "effects": []},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    (kb_dir / "mystic_codes_cn.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    monkeypatch.setattr(config, "GAME_ASSISTANT_KB_DIR", kb_dir)
    images_dir = tmp_path / "shots"
    images_dir.mkdir()
    for name in ("page_01.png", "page_02.png", "page_03.png"):
        (images_dir / name).write_bytes(b"fake-png")
    return images_dir


def test_scan_matches_kb_flags_anomalies_and_caches(scan_env, tmp_path) -> None:
    images = sorted(scan_env.iterdir())
    calls = {"n": 0}
    payloads = [
        [{"name": "2030年的碎片", "level": 20, "limit_break": 0},
         {"name": "贝拉丽莎", "level": 1, "limit_break": 0}],      # 靠归一化（去间隔号）命中
        [{"name": "同名礼装", "level": 1, "limit_break": 0},        # KB 同名两条 ⇒ 异常
         {"name": "", "level": 5, "limit_break": 0}],              # 名称读不出 ⇒ 异常
        [{"name": "不存在的礼装", "level": 1, "limit_break": 0}],   # KB 没有 ⇒ 异常
    ]

    def vision(_image_bytes, _model, _hint=""):
        payload = payloads[calls["n"]]
        calls["n"] += 1
        return payload

    out_dir = tmp_path / "out"
    summary = inventory_scan.scan_images(
        images, kind="ce", model="fake", out_dir=out_dir, cache_dir=out_dir / "cache", vision=vision
    )

    assert summary["images_processed"] == 3 and summary["rows_total"] == 5
    assert summary["rows_matched"] == 2 and summary["rows_unmatched"] == 3
    rows = json.loads((out_dir / "rows.json").read_text(encoding="utf-8"))
    matched = {row["name"]: row for row in rows if row["kb_match"]}
    assert matched["贝拉丽莎"]["collection_no"] == 100, "别名/归一化要能命中"
    assert matched["2030年的碎片"]["hp"] == 3000 and matched["2030年的碎片"]["effects"]
    anomalies = json.loads((out_dir / "anomalies.json").read_text(encoding="utf-8"))
    reasons = " ".join(item["reason"] for item in anomalies)
    assert "同名" in reasons and "读不出" in reasons and "没有这个名字" in reasons
    assert (out_dir / "review.html").exists() and (out_dir / "rows.csv").exists()

    # 断点续跑：第二次同样的图，VLM 不该再被调用（全部命中缓存）
    before = calls["n"]
    inventory_scan.scan_images(
        images, kind="ce", model="fake", out_dir=out_dir, cache_dir=out_dir / "cache", vision=vision
    )
    assert calls["n"] == before, "缓存命中时不该重复调 VLM"


def test_scan_limit_and_vlm_failure_are_tolerated(scan_env, tmp_path) -> None:
    images = sorted(scan_env.iterdir())

    def vision(_image_bytes, _model, _hint=""):
        raise RuntimeError("ollama down")

    out_dir = tmp_path / "out2"
    summary = inventory_scan.scan_images(
        images, kind="ce", model="fake", out_dir=out_dir, cache_dir=out_dir / "cache",
        limit=1, vision=vision,
    )
    assert summary["images_processed"] == 1 and summary["rows_total"] == 0
    anomalies = json.loads((out_dir / "anomalies.json").read_text(encoding="utf-8"))
    assert anomalies and "VLM 调用失败" in anomalies[0]["reason"]
