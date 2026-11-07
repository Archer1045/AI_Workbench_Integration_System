"""账号名 → 图鉴正式名的别名表测试（2026-10-11）。"""
from __future__ import annotations

import pytest

from game_assistant import servant_stats


@pytest.fixture()
def store() -> servant_stats.ServantStatsStore:
    servant_stats.reset_servant_stats()
    return servant_stats.get_servant_stats()


def test_alias_table_is_derived_from_variant_ids(store) -> None:
    """别名表必须来自导入行的 variant 编号，而不是手写。"""
    aliases = store.aliases()
    if not aliases:
        pytest.skip("本机没有别名表（需先跑 servant_stats --aliases-from）")
    assert len(aliases) >= 29, "至少覆盖此前未匹配的 29 个名字"
    sample = aliases["始皇帝"]
    assert sample["atlas_name"] == "祖政"
    assert sample["class_name"] == "Ruler"
    assert sample["evidence"].startswith("variant=")


def test_community_names_resolve_to_official_names(store) -> None:
    if not store.aliases():
        pytest.skip("本机没有别名表")
    cases = {
        "始皇帝": "祖政",
        "开膛手杰克": "雾都弃子",
        "虞美人": "雏罂",
        "岩窟王_基督山": "岩窟王　基督山",
        "司马懿〔莱妮丝〕": "莱妮丝",
        "杀生院祈荒": "瞑生院祈荒",
    }
    for account_name, atlas_name in cases.items():
        found = store.find(account_name, store.aliases()[account_name]["class_name"])
        assert found is not None, f"{account_name} 应能匹配"
        assert found["name"] == atlas_name, f"{account_name} 应解析为 {atlas_name}"


def test_alias_beats_plain_name_match_for_variants(store) -> None:
    """职阶/变体区分：别名必须优先于名字归一，否则会落到错误的从者。"""
    if not store.aliases():
        pytest.skip("本机没有别名表")
    assert store.find("织田信长(Avenger)", "Avenger", 5)["name"] == "魔王信长"
    assert store.find("贞德〔Alter〕(Berserker)", "Berserker", 5)["name"] == "贞德〔Alter〕"
    rider = store.find("阿尔托莉雅·潘德拉贡〔Alter〕(Rider)", "Rider", 5)
    assert rider["name"] == "阿尔托莉雅·潘德拉贡〔Alter〕"
