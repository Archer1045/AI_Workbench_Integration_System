"""Keep character identity tags separate from the default outfit preset."""
from __future__ import annotations

import re
from collections.abc import Iterable


_ATTIRE_PATTERN = re.compile(
    r"\b(?:"
    r"armband|armor(?:ed)?|apron|backpack|bangle|belt|bikini|bodysuit|boots?|"
    r"bracelet|cape|choker|cloak|clothes|clothing|"
    r"coat|costume|crown|dress|earring|fan|glasses|gloves?|goggles|gown|"
    r"hairband|hat|headdress|headband|heels?|hood|"
    r"jacket|jewelry|kimono|lance|leotard|mask|necklace|ornaments?|outfit|ribbon|ring|"
    r"robe|sash|scarf|shields?|shirt|shoes?|skirt|socks?|spear|staff|stockings?|"
    r"swimsuit|sword|thighhighs?|uniform|veil|vest|weapon"
    r")s?\b",
    re.IGNORECASE,
)
_EXTRA_ATTIRE_TAGS = {
    "hair flower",
    "summer halo",
    "single bare shoulder",
}
_IDENTITY_ONLY_TAGS = {
    "dragon wings",
    "black dragon wings",
    "black and purple dragon wings",
    "dragon horns",
    "black horns",
    "fox ears",
    "animal ears",
    "halo",
}


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _is_attire(tag: str) -> bool:
    normalized = re.sub(r"[_-]+", " ", tag)
    return tag.lower() in _EXTRA_ATTIRE_TAGS or bool(_ATTIRE_PATTERN.search(normalized))


def separate_character_outfit(
    appearance_tags: Iterable[str],
    outfit_tags: Iterable[str],
    *,
    work: str,
) -> tuple[list[str], list[str]]:
    """Split a combined character/outfit tag list into identity and attire."""
    appearance = _dedupe(appearance_tags)
    identity_tag = appearance[0] if appearance else ""
    appearance_keys = {tag.lower() for tag in appearance}
    identity_exclusions = {
        identity_tag.lower(),
        str(work or "").strip().lower(),
        "official_default_outfit",
    }
    clothing = [
        tag
        for tag in _dedupe(outfit_tags)
        if tag.lower() not in identity_exclusions
        and (tag.lower() not in appearance_keys or _is_attire(tag))
    ]
    clothing_keys = {tag.lower() for tag in clothing}
    moved: list[str] = []
    identity: list[str] = []
    for tag in appearance:
        key = tag.lower()
        is_attire = (
            key not in _IDENTITY_ONLY_TAGS
            and (key in clothing_keys or _is_attire(tag))
        )
        if is_attire:
            moved.append(tag)
        else:
            identity.append(tag)
    return identity, _dedupe([*clothing, *moved])
