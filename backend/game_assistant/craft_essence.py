"""概念礼装库查询：把「抽象档位」换成真实礼装。

之前的礼装模型只知道「一张 +2000ATK 的假设礼装」和两个抽象的充能档位
（+50% / +100% 开局充能）。接入 `craft_essences_cn.json` 后，方案可以点名
真实存在的礼装（例：开局充能 100% → 万华镜），并区分充能 / 增伤两类角色。

注意：活动掉落加成礼装的效果**不在礼装数据里**（那是活动侧的加成表），
所以这里不假装能识别它，只按礼装自身效果分类。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import alias as alias_mod

STARTING_CHARGE_KIND = "charge"
DAMAGE_KINDS = ("attack_up", "card_up", "np_damage_up", "power_modifier")


class CraftEssenceStore:
    def __init__(self, path: Path | str | None = None) -> None:
        import config

        self.path = Path(path or Path(config.AI_PRODUCT_DIR) / "game_assistant_kb" / "craft_essences_cn.json")
        self._payload: dict[str, Any] | None = None

    def available(self) -> bool:
        return self.path.exists()

    def load(self) -> dict[str, Any]:
        if self._payload is None:
            if not self.path.exists():
                self._payload = {"items": []}
            else:
                self._payload = json.loads(self.path.read_text(encoding="utf-8"))
        return self._payload

    @property
    def items(self) -> list[dict[str, Any]]:
        return list(self.load().get("items") or [])

    def find(self, name: str) -> dict[str, Any] | None:
        """按名字取礼装：**先过别名表**（用户写「贝拉丽莎」也能对上「贝拉·丽莎」）。

        别名有歧义时直接报错而不是挑一个；没登记的写法按原文精确匹配（旧行为不变）。
        """
        resolved = alias_mod.resolve(str(name), domain=alias_mod.CRAFT_ESSENCE)
        if resolved.ambiguous:
            raise ValueError(resolved.report())
        wanted = resolved.target if resolved.matched else str(name)
        items = self.items() if callable(self.items) else self.items
        for item in items:
            if str(item.get("name") or "") == wanted:
                return item
        return None

    @staticmethod
    def starting_charge(item: dict[str, Any]) -> float:
        """礼装提供的开局宝具值（取通用充能效果的最大值）。"""
        return max(
            (
                float(effect.get("value") or 0.0)
                for effect in item.get("effects") or []
                if effect.get("kind") == STARTING_CHARGE_KIND
            ),
            default=0.0,
        )

    @staticmethod
    def damage_bonus(item: dict[str, Any]) -> float:
        """礼装的通用增伤合计（攻击力 / 卡色 / 宝具威力 / 威力提升）。"""
        return sum(
            float(effect.get("value") or 0.0)
            for effect in item.get("effects") or []
            if effect.get("kind") in DAMAGE_KINDS
        )

    def best_starting_charge(self, need: float) -> dict[str, Any] | None:
        """挑一张刚好满足需求的充能礼装：先够用，其次星级/增伤更高。"""
        candidates = [
            item
            for item in self.items
            if self.starting_charge(item) + 1e-9 >= need > 0
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                self.starting_charge(item),
                -(int(item.get("rarity") or 0)),
                -self.damage_bonus(item),
            )
        )
        return candidates[0]

    def label_for_charge(self, need: float) -> str:
        """给充能需求一个真实礼装名；库里没有就退回抽象描述。"""
        item = self.best_starting_charge(need)
        if item is None:
            return f"开局充能礼装（+{need * 100:.0f}% 宝具值）"
        return f"{item.get('name')}（+{self.starting_charge(item) * 100:.0f}% 宝具值）"


_STORE: CraftEssenceStore | None = None


def get_craft_essence_store() -> CraftEssenceStore:
    global _STORE
    if _STORE is None:
        _STORE = CraftEssenceStore()
    return _STORE


def reset_craft_essence_store() -> None:
    global _STORE
    _STORE = None
