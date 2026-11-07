"""Extract damage / charge / star / card-control effects from Atlas skill data.

Why this module exists: the first recommender only scored raw Noble Phantasm
damage, so skill effects (self buffs, support charge, star generation, card
control) were invisible. That made a fully-built level-100 damage dealer lose to
an unbuilt NP5 servant, and made support servants unrepresentable.

Rules enforced here:

- **Target scope is respected.** A ``target=self`` buff applies only to the
  owner. 泳装 BB's 自我改造 is self-only and must never be counted as a buff for
  another servant.
- **Percent values are scaled.** Atlas per-mille values are divided by 10
  (``gainNp`` 3000 -> 30%, ``upAtk`` 300 -> +30%).
- **Unmodeled effects are reported, not silently dropped.** Defensive and
  utility effects (invincible, guts, taunt, ...) are counted so the caller can
  surface them as ``missing_data``.
- Nothing here guesses: every number comes from the catalog's per-skill-level
  ``svals`` table.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SKILLS_FILENAME = "servant_skills_cn.json"
SKILL_LEVELS = 10

# funcType -> handler
CHARGE_FUNCS = {"gainNp", "regainNp", "gainNpTargetSum", "gainNpIndividualSum", "gainNpFromTargets"}
STAR_FUNCS = {"gainStar"}
CONTROL_FUNCS = {"cardReset": "shuffle"}
NP_DAMAGE_PREFIX = "damageNp"

# buff type -> (our effect type, category, value scale)
#   percent      : Atlas 数值 / 10（300 -> 30%）
#   raw_star     : 直接是星数（regainStar 5 -> 每回合 5 星）
#   np_fraction  : Atlas 数值 / 10000（3000 -> 30% 宝具值）
BUFF_EFFECTS: dict[str, tuple[str, str, str]] = {
    # 进攻
    "upAtk": ("attack_up", "offense", "percent"),
    "upCommandall": ("card_up", "offense", "percent"),
    "upNpdamage": ("np_damage_up", "offense", "percent"),
    "upDamage": ("power_modifier", "offense", "percent"),
    "addDamage": ("flat_damage", "offense", "raw"),  # 与ダメージプラス：原始平坦加算值
    "upCriticaldamage": ("critical_up", "offense", "percent"),
    "specialAttack": ("special_attack", "offense", "percent"),
    # 暴击与星星
    "upCriticalrate": ("crit_rate_up", "crit", "percent"),
    "upStarweight": ("star_weight_up", "crit", "percent"),
    "upCriticalpoint": ("star_drop_up", "crit", "percent"),
    "regainStar": ("stars_per_turn", "crit", "raw_star"),
    "regainNp": ("np_regen", "charge", "np_fraction"),
    # 敌方减益（打手收益）
    "downDefence": ("defense_down", "debuff", "percent"),
    "downDefencecommandall": ("card_resist_down", "debuff", "percent"),
    "downAtk": ("attack_down", "debuff", "percent"),
    "downNpdamage": ("np_damage_down", "debuff", "percent"),
    "downDefenceNpdamage": ("np_resist_down", "debuff", "percent"),
}


def _scale_value(raw: float, scale: str) -> float:
    if scale == "percent":
        return raw / 10.0
    if scale == "np_fraction":
        return raw / 10000.0
    return raw  # raw_star / raw（平坦伤害）

# buff type -> card-control / condition flag
CONTROL_BUFFS: dict[str, str] = {
    "fixCommandcard": "hand_fixed",           # 手牌固定
    "donotSelectCommandcard": "others_locked",  # 其他人无法被抽到指令卡
}

# 间接引用或功能性函数：不参与伤害计算，但也不属于“未分类缺口”。
UNMODELED_FUNCS = {
    "addIndividuality",
    "commandattackAfterFunction",
    "gainHp",
    "regainHp",
    "lossHpSafe",
    "lossNp",
    "delayNpturn",
    "hastenNpturn",
    "shortenSkill",
}
UNMODELED_BUFFS = {
    "addIndividuality",
    "commandattackAfterFunction",
    "upChagetd",
    "upDefence",
    "downCriticalrate",
    "downCriticalpoint",
    "avoidance",
    "invincible",
    "guts",
    "upHate",
    "downHate",
    "donotAct",
    "donotSkill",
    "donotNoble",
    "upTolerance",
    "downTolerance",
    "pierceInvincible",
    "pierceDefence",
    "avoidState",
    "regainHp",
    "downGainHp",
    "upDefence",
    "subSelfdamage",
    "upDropnp",
    "downDropnp",
}

TARGET_SCOPES = {
    "self": "self",
    "ptOne": "ally_one",
    "ptAll": "ally_all",
    "ptOther": "ally_other",
    "enemy": "enemy_one",
    "enemyAll": "enemy_all",
}

# 卡色限制：图鉴把它记在 buff 的 tvals / ckSelfIndv / ckOpIndv 里。
# 例：杀狐「NFF特别服务」是 upCommandall + cardBuster（只提升红卡），
# C呆「选定之剑」是 upCommandall + cardArts（只提升蓝卡）。
CARD_TAGS = {
    "cardArts": "arts",
    "cardBuster": "buster",
    "cardQuick": "quick",
    "cardExtra": "extra",
    "cardNP": "np",
}

# 不是“附加条件”的标记：
# - canBeInBattle 只是“战斗中生效”的说明；
# - faceCard 表示只作用于指令卡（对宝具无效），单独作为条件处理。
# - unknown 是图鉴没有解析出名字的形态/变身标记（如杰基尔变身、玉兔的两个形态），
#   不是敌人特性条件，不能因此把无条件的自身增益排掉。
NON_CONDITION_TAGS = {"canBeInBattle", "unknown"}
FACE_CARD_TAG = "faceCard"

# 只写在 buff 文本里的条件（结构字段是空的），同样不能按固定收益计算：
# - 「仅在〔水边〕/〔都市〕/阳光照射的战场」：场地限制
# - 「当生命值低于 99%时」：血量阈值（逆境类）
# - 「自身的〔增殖〕越多」：按叠加数递增
TEXT_CONDITION_MARKERS = ("仅限", "当生命值", "越多")
TEXT_CONDITION_TAG = "textCondition"


def _card_restriction(function: dict[str, Any], buff: dict[str, Any] | None) -> str:
    """返回该效果的卡色限制（空字符串表示对所有卡生效）。"""
    for source in (buff or {}, function):
        for field in ("tvals", "ckSelfIndv", "ckOpIndv", "functvals"):
            for tag in source.get(field) or []:
                if not isinstance(tag, dict):
                    continue
                card = CARD_TAGS.get(str(tag.get("name") or ""))
                if card:
                    return card
    return ""


def _condition(function: dict[str, Any], buff: dict[str, Any] | None) -> tuple[str, str]:
    """返回该效果的附加条件 ``(标签, 中文说明)``；空字符串表示无附加条件。

    图鉴把条件写在 buff/function 的 ``tvals`` / ``ckSelfIndv`` / ``ckOpIndv`` /
    ``functvals`` 里。**被限制的增益不能当作固定伤害**：例如
    「杀戮技巧（人）A」实际是两条对〔人类〕/〔人之力〕的条件特攻，
    只有敌人具备该特性时才生效，而战斗档案里并没有敌人特性数据。

    另有一类条件只写在 buff 文本里（见 ``TEXT_CONDITION_MARKERS``）：场地限制
    「仅在〔水边〕的战场」、血量阈值「当生命值低于 99%时」、按叠加上限递增的
    「自身的〔增殖〕越多」。这些同样无法按固定收益计算。
    """
    tags: list[str] = []
    for source in (buff or {}, function):
        for field in ("tvals", "ckSelfIndv", "ckOpIndv", "functvals"):
            for tag in source.get(field) or []:
                if not isinstance(tag, dict):
                    continue
                name = str(tag.get("name") or "")
                if not name or name in CARD_TAGS or name in NON_CONDITION_TAGS:
                    continue
                if name not in tags:
                    tags.append(name)
    label = str(
        (buff or {}).get("detail")
        or (buff or {}).get("name")
        or function.get("funcPopupText")
        or ""
    )
    if any(marker in label for marker in TEXT_CONDITION_MARKERS) and TEXT_CONDITION_TAG not in tags:
        tags.append(TEXT_CONDITION_TAG)
    if not tags:
        return "", ""
    if FACE_CARD_TAG in tags and "指令卡" not in label:
        label = (label + "（仅指令卡，对宝具无效）").strip()
    return ",".join(tags), label


@dataclass
class SkillEffect:
    kind: str            # attack_up / card_up / charge / stars / control / unmodeled ...
    value: float = 0.0   # 满级(10)取值：百分比（0.3 = 30%）或星数或充能比例
    values: list[float] = field(default_factory=list)  # 技能等级 1..10 的逐级取值
    duration: int = 0
    target: str = ""     # self / ally_one / ally_all / ally_other / enemy_one / enemy_all
    source: str = ""     # buff type / funcType
    card: str = ""       # 卡色限制：arts / buster / quick / extra / np；空表示通用
    condition: str = ""  # 附加条件标签（特攻/限定状态）；非空表示条件生效，不能按固定伤害计算
    condition_label: str = ""  # 条件的中文说明，用于方案里的提示

    def value_at(self, level: int) -> float:
        if not self.values:
            return self.value
        index = min(max(int(level), 1), SKILL_LEVELS) - 1
        return self.values[min(index, len(self.values) - 1)]


@dataclass
class ParsedSkill:
    slot: int
    name: str
    rank: str = ""
    cooldowns: list[int] = field(default_factory=list)
    effects: list[SkillEffect] = field(default_factory=list)

    def by_kind(self, kind: str, target: str | None = None) -> list[SkillEffect]:
        return [
            effect
            for effect in self.effects
            if effect.kind == kind and (target is None or effect.target == target)
        ]


def _level_value(svals: list[dict[str, Any]], level: int) -> tuple[float | None, int]:
    """取指定技能等级的数值与持续回合。level 为 1..10。"""
    if not svals:
        return None, 0
    index = min(max(int(level), 1), SKILL_LEVELS) - 1
    index = min(index, len(svals) - 1)
    entry = svals[index]
    value = entry.get("Value")
    turns = entry.get("Turn") or 0
    return (float(value) if isinstance(value, (int, float)) else None), int(turns or 0)


def _level_values(svals: list[dict[str, Any]], scale: str) -> list[float]:
    """返回技能等级 1..10 的逐级取值（缺失时顺延最后一级）。"""
    raw: list[float] = []
    for item in svals[:SKILL_LEVELS]:
        value = item.get("Value")
        raw.append(float(value) if isinstance(value, (int, float)) else 0.0)
    while len(raw) < SKILL_LEVELS:
        raw.append(raw[-1] if raw else 0.0)
    return [_scale_value(value, scale) for value in raw]


def parse_skill(skill: dict[str, Any], level: int = SKILL_LEVELS) -> ParsedSkill:
    """把一个图鉴技能解析成带目标域的效果列表（按给定技能等级取值）。"""
    slot = int(skill.get("num") or 0)
    parsed = ParsedSkill(
        slot=slot,
        name=str(skill.get("name") or ""),
        rank=str(skill.get("rank") or ""),
        cooldowns=[int(value) for value in (skill.get("coolDown") or []) if isinstance(value, (int, float))],
    )
    for function in skill.get("functions") or []:
        if not isinstance(function, dict):
            continue
        func_type = str(function.get("funcType") or "")
        scope = TARGET_SCOPES.get(str(function.get("funcTargetType") or ""), "unknown")
        svals = [item for item in (function.get("svals") or []) if isinstance(item, dict)]
        value, turns = _level_value(svals, level)
        buff_objects = [b for b in (function.get("buffs") or []) if isinstance(b, dict)]
        buffs = [str(b.get("type")) for b in buff_objects]
        card = _card_restriction(function, buff_objects[0] if buff_objects else None)

        if func_type in CHARGE_FUNCS and value is not None:
            parsed.effects.append(
                SkillEffect(
                    kind="charge",
                    value=_scale_value(value, "np_fraction"),
                    values=_level_values(svals, "np_fraction"),
                    duration=0,
                    target=scope,
                    source=func_type,
                )
            )
            continue
        if func_type in STAR_FUNCS and value is not None:
            parsed.effects.append(
                SkillEffect(
                    kind="stars",
                    value=value,
                    values=_level_values(svals, "raw_star"),
                    duration=0,
                    target=scope,
                    source=func_type,
                )
            )
            continue
        if func_type in CONTROL_FUNCS:
            parsed.effects.append(
                SkillEffect(kind="control", value=0.0, duration=0, target=scope, source=CONTROL_FUNCS[func_type])
            )
            continue
        if func_type.startswith(NP_DAMAGE_PREFIX):
            continue
        if func_type in UNMODELED_FUNCS:
            parsed.effects.append(
                # 同样保留数值：`shortenSkill` 的数值就是“减少几个回合冷却”，
                # 丢掉它就无法做技能复用（用户的 2T 操作依赖这个）。
                SkillEffect(
                    kind="unmodeled",
                    value=float(value or 0.0),
                    duration=turns,
                    target=scope,
                    source=func_type,
                )
            )
            continue

        for buff_object in buff_objects or [{}]:
            buff = str(buff_object.get("type") or "")
            effect_card = _card_restriction(function, buff_object) if buff_object else ""
            if buff in CONTROL_BUFFS:
                parsed.effects.append(
                    SkillEffect(kind="control", value=0.0, duration=turns, target=scope, source=CONTROL_BUFFS[buff])
                )
                continue
            mapped = BUFF_EFFECTS.get(buff)
            if mapped and value is not None:
                condition, condition_label = _condition(function, buff_object)
                parsed.effects.append(
                    SkillEffect(
                        kind=mapped[0],
                        value=_scale_value(value, mapped[2]),
                        values=_level_values(svals, mapped[2]),
                        duration=turns,
                        target=scope,
                        source=buff,
                        card=effect_card,
                        condition=condition,
                        condition_label=condition_label,
                    )
                )
                continue
            if buff in UNMODELED_BUFFS:
                parsed.effects.append(
                    # 保留数值：有些“未建模”的增益其实带关键数值
                    # （例：upChagetd = 过量充能阶级提升 +1/+2，直接影响宝具伤害）。
                    SkillEffect(
                        kind="unmodeled",
                        value=float(value or 0.0),
                        duration=turns,
                        target=scope,
                        source=buff,
                    )
                )
                continue
            # 未分类的 buff：显式记录，便于后续补齐映射表。
            parsed.effects.append(
                SkillEffect(kind="unmapped", value=0.0, duration=turns, target=scope, source=buff or func_type)
            )
    return parsed


def build_skill_table(atlas_path: Path | str) -> dict[str, Any]:
    """把图鉴压缩成 per-servant 技能表（含每级冷却与效果）。"""
    from .servant_stats import normalize_class, normalize_name  # 复用同一套归一

    entries = json.loads(Path(atlas_path).read_text(encoding="utf-8"))
    servants: list[dict[str, Any]] = []
    unmapped_counter: dict[str, int] = {}
    for entry in entries:
        skills = []
        for skill in entry.get("skills") or []:
            parsed = parse_skill(skill)
            skills.append(
                {
                    "slot": parsed.slot,
                    "name": parsed.name,
                    "rank": parsed.rank,
                    "cooldowns": parsed.cooldowns,
                    "effects": [
                        {
                            "kind": effect.kind,
                            "value": effect.value,
                            "values": [round(item, 4) for item in effect.values],
                            "duration": effect.duration,
                            "target": effect.target,
                            "source": effect.source,
                            "card": effect.card,
                            "condition": effect.condition,
                            "condition_label": effect.condition_label,
                        }
                        for effect in parsed.effects
                    ],
                }
            )
            for effect in parsed.effects:
                if effect.kind in {"unmapped", "unmodeled"}:
                    unmapped_counter[effect.source] = unmapped_counter.get(effect.source, 0) + 1
        servants.append(
            {
                "name": entry.get("name") or "",
                "normalized_name": normalize_name(entry.get("name") or ""),
                "class_name": normalize_class(entry.get("className", "")),
                "collection_no": entry.get("collectionNo"),
                # 罕见度用于同名同职阶消歧（图鉴里有两条 `BB`：4★ 原版 166 / 5★ 水着 220）
                "rarity": entry.get("rarity"),
                "star_gen": entry.get("starGen"),
                "star_absorb": entry.get("starAbsorb"),
                "cards": entry.get("cards") or [],
                "hit_distribution": entry.get("hitsDistribution") or {},
                "skills": skills,
            }
        )
    servants.sort(key=lambda item: (item["class_name"], item["normalized_name"]))
    return {
        "source": {"entries": len(servants)},
        "unmodeled_counts": dict(sorted(unmapped_counter.items(), key=lambda item: -item[1])),
        "servants": servants,
    }


class SkillTableStore:
    """技能表读取与按名字/职阶匹配（复用基础数据表同一套归一规则）。"""

    def __init__(self, path: Path | str | None = None) -> None:
        import config

        self.path = Path(path or Path(config.GAME_ASSISTANT_COMBAT_DIR) / SKILLS_FILENAME)
        self._payload: dict[str, Any] | None = None
        self._index: dict[str, dict[str, list[dict[str, Any]]]] | None = None

    def available(self) -> bool:
        return self.path.exists()

    def load(self) -> dict[str, Any]:
        if self._payload is None:
            if not self.path.exists():
                self._payload = {"source": {}, "servants": []}
            else:
                self._payload = json.loads(self.path.read_text(encoding="utf-8"))
        return self._payload

    @property
    def servants(self) -> list[dict[str, Any]]:
        return list(self.load().get("servants") or [])

    def find(self, name: str, class_name: str = "", rarity: int | None = None) -> dict[str, Any] | None:
        from .servant_stats import lookup_entry, make_lookup

        if self._index is None:
            self._index = make_lookup(self.servants)
        return lookup_entry(self._index, name, class_name, rarity)

    def candidates(self, name: str, class_name: str = "") -> list[dict[str, Any]]:
        from .servant_stats import lookup_candidates, make_lookup

        if self._index is None:
            self._index = make_lookup(self.servants)
        return lookup_candidates(self._index, name, class_name)

    def skill(self, name: str, class_name: str, slot: int) -> dict[str, Any] | None:
        entry = self.find(name, class_name)
        if entry is None:
            return None
        return next((skill for skill in entry.get("skills") or [] if skill.get("slot") == slot), None)


_STORE: SkillTableStore | None = None


def get_skill_table() -> SkillTableStore:
    global _STORE
    if _STORE is None:
        _STORE = SkillTableStore()
    return _STORE


def reset_skill_table() -> None:
    global _STORE
    _STORE = None


def main(argv: list[str] | None = None) -> int:
    import argparse

    import config

    parser = argparse.ArgumentParser(description="从 Atlas 缓存生成技能效果表")
    parser.add_argument("--atlas", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    payload = build_skill_table(args.atlas)
    target = Path(args.out or Path(config.GAME_ASSISTANT_COMBAT_DIR) / SKILLS_FILENAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {target}：{payload['source']['entries']} 条从者技能表", flush=True)
    top = list(payload["unmodeled_counts"].items())[:8]
    print("未建模/未映射统计（前 8）:", top, flush=True)
    return 0


if __name__ == "__main__":
    import sys

    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
