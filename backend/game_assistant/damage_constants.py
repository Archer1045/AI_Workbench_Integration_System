"""Atlas-derived class/attribute damage constants.

Source files (exported 2026-10-18):
- NiceClassAttackRate.json
- NiceClassRelation.json
- NiceAttributeRelation.json

Atlas stores these as integer per-mille values. The previous planner only knew
the six base-class triangle and treated every extra class as neutral, which
missed Beast's 1.5x attack relation against standard classes.
"""
from __future__ import annotations

import json
from pathlib import Path

import config

_CLASS_ATTACK_FILE = "class_attack_rates.json"
_CLASS_RELATION_FILE = "class_relations.json"
_ATTRIBUTE_RELATION_FILE = "attribute_relations.json"

ATLAS_CLASS_KEYS = {
    "Saber": "saber",
    "Archer": "archer",
    "Lancer": "lancer",
    "Rider": "rider",
    "Caster": "caster",
    "Assassin": "assassin",
    "Berserker": "berserker",
    "Shielder": "shielder",
    "Ruler": "ruler",
    "Alterego": "alterEgo",
    "AlterEgo": "alterEgo",
    "Avenger": "avenger",
    "MoonCancer": "moonCancer",
    "Foreigner": "foreigner",
    "Pretender": "pretender",
    "Beast": "beast",
    "UnBeastOlgaMarie": "unBeastOlgaMarie",
    "DemonGodPillar": "demonGodPillar",
}

_CACHE: dict[str, dict] = {}


def _load(filename: str) -> dict:
    if filename not in _CACHE:
        path = Path(config.GAME_ASSISTANT_COMBAT_DIR) / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        _CACHE[filename] = payload if isinstance(payload, dict) else {}
    return _CACHE[filename]


def reset_damage_constants() -> None:
    _CACHE.clear()


def _class_key(class_name: str) -> str:
    return ATLAS_CLASS_KEYS.get(str(class_name or ""), str(class_name or ""))


def _attribute_key(attribute: str) -> str:
    value = str(attribute or "").lower()
    return "human" if value == "man" else value


def class_attack_rate(class_name: str) -> float:
    value = _load(_CLASS_ATTACK_FILE).get(_class_key(class_name), 1000)
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return 1.0


def class_relation_multiplier(attacker_class: str, defender_class: str) -> float:
    row = _load(_CLASS_RELATION_FILE).get(_class_key(attacker_class), {})
    value = row.get(_class_key(defender_class), 1000) if isinstance(row, dict) else 1000
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return 1.0


def attribute_relation_multiplier(attacker_attribute: str, defender_attribute: str) -> float:
    row = _load(_ATTRIBUTE_RELATION_FILE).get(_attribute_key(attacker_attribute), {})
    value = row.get(_attribute_key(defender_attribute), 1000) if isinstance(row, dict) else 1000
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return 1.0


def combined_class_multiplier(attacker_class: str, defender_class: str) -> float:
    return class_attack_rate(attacker_class) * class_relation_multiplier(
        attacker_class, defender_class
    )
