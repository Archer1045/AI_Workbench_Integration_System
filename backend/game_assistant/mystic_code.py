"""Mystic Code modelling: free NP charge and buffs that cost no Craft Essence slot.

The account's own Mystic Code list was read from the game's 御主装备 screen and
the skill values come from Mooncell. A Mystic Code is *free* — switching it does
not consume a drop-bonus slot — so plans should spend Mystic Code charge before
spending Craft Essence slots.

Effects are recognised by keyword from the official effect text. Anything not
recognised is reported as unmodeled instead of being guessed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import config

TABLE_FILENAME = "mystic_codes_cn.json"
OWNED_FILENAME = "owned_mystic_codes.json"

CARD_NAMES = {"quick": "Quick", "arts": "Arts", "buster": "Buster"}

# 关键词 -> (效果类型, 取第几个捕获组作为卡色)
EFFECT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"NP(?:小幅)?增加"), "charge"),
    (re.compile(r"NP获得量提升"), "np_gain_up"),
    (re.compile(r"(Quick|Arts|Buster)指令卡性能提升"), "card_up"),
    (re.compile(r"宝具威力提升"), "np_damage_up"),
    (re.compile(r"攻击力(?:极大)?提升"), "attack_up"),
    # Mooncell 的写法两种都有：「Arts指令卡暴击星集中度提升」与「Arts指令卡的暴击星集中度提升」。
    # 漏掉可选的「的」会让卡色限制丢失，进而把某卡色的集中度错当成通用集中度。
    (re.compile(r"(Quick|Arts|Buster)指令卡(?:的)?暴击星集中度提升"), "star_weight_up_card"),
    (re.compile(r"暴击星集中度提升"), "star_weight_up"),
    (re.compile(r"暴击威力提升"), "critical_up"),
    (re.compile(r"暴击星发生率提升"), "star_drop_up"),
    (re.compile(r"获得(?:大量)?暴击星"), "stars"),
    # 阿特拉斯院制服技能 3：己方单体的技能冷却减少 2 回合（数值只写在文案里）。
    (re.compile(r"技能冷却减少\s*(\d+)"), "shorten_skill"),
]

UNMODELED_HINTS = (
    "HP回复", "回避", "无敌", "毅力", "弱化", "眩晕", "强化无效", "必中",
    "贯通", "技能冷却", "交换", "洗牌", "充能阶段", "耐性", "解除",
)


@dataclass
class MysticCodeEffect:
    kind: str
    value: float = 0.0
    card: str = ""
    target: str = "ally_one"
    text: str = ""


@dataclass
class MysticCodeProfile:
    name: str
    level: int
    effects: list[MysticCodeEffect] = field(default_factory=list)
    unmodeled: list[str] = field(default_factory=list)

    def charge_for(self, card: str | None = None) -> float:
        return sum(effect.value for effect in self.effects if effect.kind == "charge")

    def buff_sum(self, card: str) -> float:
        total = 0.0
        for effect in self.effects:
            if effect.kind not in {"card_up", "np_damage_up", "attack_up"}:
                continue
            if effect.card and effect.card != card:
                continue
            total += effect.value
        return total

    def stars(self) -> float:
        return sum(effect.value for effect in self.effects if effect.kind == "stars")


def _parse_value(text: str) -> float:
    text = text.strip()
    if text.endswith("%"):
        return float(text[:-1]) / 100.0
    return float(text)


def _level_value(values: list[str], level: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return _parse_value(values[0])
    index = min(max(level, 1), len(values)) - 1
    return _parse_value(values[index])


class MysticCodeTable:
    def __init__(self, table_path: Path | str | None = None, owned_path: Path | str | None = None) -> None:
        root = Path(config.GAME_ASSISTANT_COMBAT_DIR)
        self.table_path = Path(table_path or root / TABLE_FILENAME)
        self.owned_path = Path(owned_path or root / OWNED_FILENAME)

    def available(self) -> bool:
        return self.table_path.exists()

    def _entries(self) -> dict[str, dict]:
        if not self.table_path.exists():
            return {}
        payload = json.loads(self.table_path.read_text(encoding="utf-8"))
        return {entry["name"]: entry for entry in payload.get("mystic_codes") or []}

    def owned(self) -> list[dict]:
        if not self.owned_path.exists():
            return []
        payload = json.loads(self.owned_path.read_text(encoding="utf-8"))
        return list(payload.get("mystic_codes") or [])

    def profile(self, name: str, level: int) -> MysticCodeProfile | None:
        entry = self._entries().get(name)
        if entry is None:
            return None
        profile = MysticCodeProfile(name=name, level=level)
        for skill in entry.get("skills") or []:
            for effect in skill.get("effects") or []:
                text = str(effect.get("text") or "")
                values = [str(item) for item in (effect.get("values") or [])]
                matched = False
                for pattern, kind in EFFECT_PATTERNS:
                    match = pattern.search(text)
                    if not match:
                        continue
                    card = ""
                    if kind in {"card_up", "star_weight_up_card"} and match.groups():
                        card = str(match.group(1)).lower()
                    value = _level_value(values, level)
                    if kind == "shorten_skill" and not values and match.groups():
                        # 数值只写在文案里：「技能冷却减少2回合」
                        value = float(match.group(1))
                    effective_kind = "star_weight_up" if kind == "star_weight_up_card" else kind
                    profile.effects.append(
                        MysticCodeEffect(
                            kind=effective_kind,
                            value=value,
                            card=card,
                            target="ally_all" if "全体" in text else "ally_one",
                            text=text,
                        )
                    )
                    matched = True
                    break
                if not matched and any(hint in text for hint in UNMODELED_HINTS):
                    profile.unmodeled.append(text)
                elif not matched and text:
                    profile.unmodeled.append(text)
        return profile

    def profiles(self) -> list[MysticCodeProfile]:
        result = []
        for item in self.owned():
            profile = self.profile(str(item.get("name")), int(item.get("level") or 1))
            if profile is not None:
                result.append(profile)
        return result

    def best_for(self, card: str, need_charge: float) -> MysticCodeProfile | None:
        """在持有礼装中挑一件：优先补充能，其次补该卡色的增伤。"""
        best: tuple[float, MysticCodeProfile] | None = None
        for profile in self.profiles():
            charge = min(profile.charge_for(card), max(0.0, need_charge))
            score = charge * 100.0 + profile.buff_sum(card) + profile.stars() / 100.0
            if best is None or score > best[0]:
                best = (score, profile)
        return best[1] if best else None

    def equipped(self) -> MysticCodeProfile | None:
        """账号当前装备的御主礼装。

        推荐不能用“更好的礼装”替换它：用户的实测操作依赖当前装备的礼装技能
        （例：阿特拉斯院制服技能 3 的冷却 −2 是整个 2T 的关键）。
        """
        if not self.owned_path.exists():
            return None
        payload = json.loads(self.owned_path.read_text(encoding="utf-8"))
        name = str(payload.get("equipped") or "")
        if not name:
            return None
        level = next(
            (int(item.get("level") or 1) for item in self.owned() if str(item.get("name")) == name),
            0,
        )
        if not level:
            return None
        return self.profile(name, level)
