"""Enemy-trait helpers shared by planning, runbook compilation, and simulation."""
from __future__ import annotations

from .combat_domain import CombatProfile, EnemyUnit

# 档案里的属性写法 → 图鉴标签
ATLAS_ATTRIBUTE_TAGS = {
    "man": "attributeHuman",
    "human": "attributeHuman",
    "sky": "attributeSky",
    "earth": "attributeEarth",
    "star": "attributeStar",
    "beast": "attributeBeast",
}

# 图鉴对这些职阶使用驼峰写法，而档案里的名字来自 normalize_class。
ATLAS_CLASS_TAGS = {
    "Alterego": "AlterEgo",
    "AlterEgo": "AlterEgo",
    "MoonCancer": "MoonCancer",
    "DemonGodPillar": "DemonGodPillar",
    "UnBeastOlgaMarie": "UnBeastOlgaMarie",
    "Beast": "Beast",
}


def enemy_trait_set(unit: EnemyUnit) -> set[str]:
    """All trait names that can satisfy a conditional effect for one enemy."""
    tags = {f"class{unit.class_name}", f"attribute{str(unit.attribute).title()}"}
    atlas_class = ATLAS_CLASS_TAGS.get(str(unit.class_name))
    if atlas_class:
        tags.add(f"class{atlas_class}")
    atlas_attribute = ATLAS_ATTRIBUTE_TAGS.get(str(unit.attribute).lower())
    if atlas_attribute:
        tags.add(atlas_attribute)
    tags |= {str(trait) for trait in (unit.traits or [])}
    return tags


def common_enemy_traits(profile: CombatProfile) -> set[str]:
    """Traits shared by every enemy, used for conservative recommendation scoring."""
    per_unit = [
        enemy_trait_set(unit)
        for wave in profile.waves
        for unit in wave.units
    ]
    if not per_unit:
        return set()
    common = set(per_unit[0])
    for tags in per_unit[1:]:
        common &= tags
    return common


def condition_tags(condition: str) -> set[str]:
    return {tag.strip() for tag in str(condition or "").split(",") if tag.strip()}


def condition_is_resolvable(condition: str) -> bool:
    """False for text-only conditions (field/HP threshold/stack count)."""
    tags = condition_tags(condition)
    return bool(tags) and "textCondition" not in tags


def condition_satisfied(condition: str, traits: set[str] | None) -> bool:
    tags = condition_tags(condition)
    if not tags or "textCondition" in tags or not traits:
        return False
    return bool(tags & traits)
