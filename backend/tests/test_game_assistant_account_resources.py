from __future__ import annotations

from game_assistant.account_domain import (
    CraftEssenceRecordInput,
    MysticCodeRecordInput,
    MysticCodeSkill,
    SupportPreferenceRecordInput,
)
from game_assistant.account_store import AccountSnapshotStore


def test_craft_essence_crud(tmp_path) -> None:
    store = AccountSnapshotStore(tmp_path / "account.db")
    created = store.upsert_craft_essence(
        CraftEssenceRecordInput(
            name="黑之圣杯",
            rarity=5,
            level=100,
            max_level=100,
            limit_break=4,
            attack=2400,
            hp=0,
            cost=12,
            effects=[{"effect_id": "black_grail", "effect_type": "np_damage_up", "value": 0.6}],
        )
    )
    assert created.record_id
    assert created.limit_break == 4
    assert store.list_craft_essences()[0].effects[0]["effect_type"] == "np_damage_up"
    assert store.delete_craft_essence(created.record_id) is True


def test_mystic_code_crud(tmp_path) -> None:
    store = AccountSnapshotStore(tmp_path / "account.db")
    created = store.upsert_mystic_code(
        MysticCodeRecordInput(
            name="迦勒底战斗服",
            level=10,
            skills=[
                MysticCodeSkill(
                    skill_id="mc_charge",
                    name="全体充能",
                    level=10,
                    cooldown=15,
                    effects=[{"effect_id": "mc_charge", "effect_type": "charge", "value": 20}],
                )
            ],
        )
    )
    assert created.skills[0].skill_id == "mc_charge"
    assert store.list_mystic_codes()[0].skills[0].level == 10
    assert store.delete_mystic_code(created.record_id) is True


def test_support_preference_crud(tmp_path) -> None:
    store = AccountSnapshotStore(tmp_path / "account.db")
    created = store.upsert_support_preference(
        SupportPreferenceRecordInput(
            name="河上彦斋",
            class_name="Assassin",
            np_level=5,
            skill_1=10,
            skill_2=10,
            skill_3=10,
            append_2=10,
            craft_essence_name="黑之圣杯",
            friend_only=True,
        )
    )
    assert created.friend_only is True
    assert store.list_support_preferences()[0].name == "河上彦斋"
    assert store.delete_support_preference(created.record_id) is True
