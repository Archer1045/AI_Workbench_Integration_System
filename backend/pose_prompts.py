"""Layered prompt helpers for pose presets."""
from __future__ import annotations

import re
from typing import Any, Iterable

_COUNT_ONLY_TAG = re.compile(
    r"^(?:exactly\s+)?(?:\d+|one|two|three|four|five|six)\s+"
    r"(?:separate\s+)?(?:people|characters?)$",
    re.IGNORECASE,
)
_QUALITY_ONLY_TAGS = {
    "best quality",
    "high quality",
    "masterpiece",
    "uncensored",
    "anime rendering",
}
_POSE_CONTEXT_TAGS = {
    "consensual",
    "same-age adult partners",
    "female receiver",
    "young-looking adult male",
    "young-looking adult female",
}
_PEOPLE_NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
}


def _unique_tags(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _context_rank(tag: str) -> int | None:
    normalized = tag.casefold()
    if normalized == "consensual":
        return 0
    if re.fullmatch(
        r"(?:two|three|four|multiple)\s+adults?|adult characters?",
        normalized,
    ):
        return 1
    if normalized == "same-age adult partners":
        return 2
    if normalized == "female receiver":
        return 3
    if normalized in {"young-looking adult male", "young-looking adult female"}:
        return 4
    return None


def pose_core_tags(preset: dict[str, Any]) -> list[str]:
    """Return a short, stable pose subset while preserving adult/consent context."""
    tags = [
        tag
        for tag in _unique_tags(preset.get("tags") or [])
        if not _COUNT_ONLY_TAG.fullmatch(tag)
        and tag.casefold() not in _QUALITY_ONLY_TAGS
    ]
    signal = [
        tag
        for tag in tags
        if _context_rank(tag) is None
        and tag.casefold() not in _POSE_CONTEXT_TAGS
    ]
    context: list[str] = []
    if any(_context_rank(tag) in {1, 2, 4} for tag in tags):
        context.append("adult characters")
    if any(tag.casefold() == "consensual" for tag in tags):
        context.append("consensual")

    context_length = len(", ".join(context))
    budget = max(0, 76 - context_length - (2 if context else 0))
    selected: list[str] = []
    for tag in signal:
        if len(selected) >= 5:
            break
        candidate = ", ".join([*selected, tag])
        if selected and len(candidate) > budget:
            break
        selected.append(tag)
        if len(candidate) >= budget:
            break
    selected.extend(context)
    if selected:
        return selected

    fallback = str(preset.get("draw_prompt") or "").strip().split(";", 1)[0].strip()
    return [fallback[:180]] if fallback else []


def pose_people_prompt(preset: dict[str, Any]) -> str:
    explicit = str(preset.get("people_prompt") or "").strip()
    if explicit:
        return explicit
    fallback_count = (
        1
        if preset.get("people") == "单人"
        else 2
        if preset.get("people") == "双人"
        else len(preset.get("role_slots") or [])
    )
    count = int(preset.get("people_count") or fallback_count or 0)
    number = _PEOPLE_NUMBER_WORDS.get(count)
    if count == 1:
        return "exactly 1 person"
    if number:
        return f"exactly {number} people, {number} separate bodies"
    return ""


def pose_prompt(preset: dict[str, Any], detail: str = "core") -> str:
    tags = (
        pose_core_tags(preset)
        if detail != "full"
        else [
            tag
            for tag in _unique_tags(preset.get("tags") or [])
            if not _COUNT_ONLY_TAG.fullmatch(tag)
        ]
    )
    body_parts = [", ".join(tags)]
    if detail == "full":
        body_parts.append(str(preset.get("draw_prompt") or "").strip())
    body = ", ".join(part for part in body_parts if part)
    people = pose_people_prompt(preset)
    if not people:
        return body
    if people.casefold() in body.casefold():
        return body
    return f"{people}, {body}" if body else people
