"""AI 绘画提示词校验：重复、冲突、语法与人数一致性检查。"""
from __future__ import annotations

import re

COUNT_PATTERN = re.compile(r"^(\d+)(girls?|boys?)$")
MULTI_HINT_KEYWORDS = [
    "clone",
    "duplicate",
    "doppelganger",
    "reflection",
    "mirror image",
    "identical twins",
    "same person twice",
    "two of the same",
    "multiple girls",
    "multiple boys",
    "pair",
    "group",
]
QUALITY_KEYWORDS = ["masterpiece", "best quality", "high quality", "highres", "score_7", "score_8", "very aesthetic"]
CONFLICT_RULES = [
    (
        ("nude", "naked", "topless", "no clothes"),
        ("dress", "clothes", "clothed", "uniform", "school uniform", "shirt", "pants", "skirt", "swimsuit", "lingerie"),
    ),
    (("long hair",), ("short hair", "bob cut")),
    (("standing",), ("lying", "sitting", "kneeling")),
    (("closed eyes",), ("looking at viewer", "open eyes")),
    (("day", "daylight"), ("night", "nighttime")),
    (("indoor", "indoors"), ("outdoor", "outdoors")),
    (("smile", "smiling"), ("frown", "frowning", "angry expression")),
    (("white dress",), ("black dress", "red dress", "blue dress")),
]


def _normalize(tag: str) -> str:
    """归一化标签：去空格/下划线/权重，用于重复与规则匹配。"""
    text = tag.strip().lower().replace("_", " ")
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    text = re.sub(r":\d+(\.\d+)?$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _split_tags(prompt: str) -> list[str]:
    return [tag for tag in (part.strip() for part in prompt.split(",")) if tag]


def _count_info(tag: str) -> tuple[int | None, str | None]:
    match = COUNT_PATTERN.fullmatch(tag.replace(" ", ""))
    if match:
        return int(match.group(1)), match.group(2)
    if tag == "solo":
        return 1, "solo"
    return None, None


def _originals_for(normalized_list: list[str], original_list: list[str], targets: list[str]) -> list[str]:
    """返回匹配归一化目标的原始标签（保留权重写法）。"""
    found: list[str] = []
    for norm, original in zip(normalized_list, original_list):
        if norm in targets and original not in found:
            found.append(original)
    return found


def validate_prompt(prompt: str, negative_prompt: str = "") -> dict:
    """返回 errors / warnings / suggestions 三个列表。"""
    errors: list[dict] = []
    warnings: list[dict] = []
    suggestions: list[dict] = []

    tags = _split_tags(prompt)
    if not tags:
        return {"errors": [], "warnings": [], "suggestions": []}

    normalized = [_normalize(tag) for tag in tags]
    full_text = " ".join(normalized)

    # 重复检测
    seen: dict[str, str] = {}
    for original, norm in zip(tags, normalized):
        if norm in seen:
            warnings.append(
                {
                    "type": "warning",
                    "message": f"标签重复：{norm}（保留第一个，建议删除后面的）",
                    "action": "dedupe",
                    "tags": [seen[norm], original],
                }
            )
        else:
            seen[norm] = original

    # 人数一致性
    girl_values: list[int] = []
    boy_values: list[int] = []
    solo = False
    count_originals: list[str] = []
    for original, norm in zip(tags, normalized):
        value, kind = _count_info(norm)
        if value is None:
            continue
        count_originals.append(original)
        if kind == "solo":
            solo = True
        elif kind in ("girls", "girl"):
            girl_values.append(value)
        else:
            boy_values.append(value)
    total_count = (max(girl_values) if girl_values else 0) + (max(boy_values) if boy_values else 0)
    if solo and total_count > 1:
        errors.append(
            {
                "type": "error",
                "message": f"solo 与多人标签冲突：{', '.join(count_originals)}，请统一人数",
                "action": "remove-tag",
                "tags": count_originals,
            }
        )
    elif len(set(girl_values)) > 1 or len(set(boy_values)) > 1:
        errors.append(
            {
                "type": "error",
                "message": f"同一性别人数标签冲突：{', '.join(count_originals)}，请统一人数",
                "action": "remove-tag",
                "tags": count_originals,
            }
        )
    elif total_count == 1:
        lowered = " ".join(normalized)
        for keyword in MULTI_HINT_KEYWORDS:
            if keyword in lowered:
                matched = _originals_for(normalized, tags, [norm for norm in normalized if keyword in norm])
                errors.append(
                    {
                        "type": "error",
                        "message": f"提示词包含多角色暗示（{keyword}），与 1girl/1boy/solo 冲突，可能生成多名角色",
                        "action": "remove-tag",
                        "tags": matched or [tag for tag in tags if keyword in _normalize(tag)],
                    }
                )
                break

    # 冲突规则
    for group_a, group_b in CONFLICT_RULES:
        hit_a = next((word for word in group_a if word in full_text), None)
        hit_b = next((word for word in group_b if word in full_text), None)
        if hit_a and hit_b:
            matched_a = _originals_for(normalized, tags, [norm for norm in normalized if hit_a in norm])
            matched_b = _originals_for(normalized, tags, [norm for norm in normalized if hit_b in norm])
            warnings.append(
                {
                    "type": "warning",
                    "message": f"提示词冲突：{hit_a} 与 {hit_b} 同时出现，可能互相抵消",
                    "action": "remove-tag",
                    "tags": (matched_a or [hit_a]) + (matched_b or [hit_b]),
                }
            )

    # 语法
    if prompt.count("(") != prompt.count(")"):
        errors.append({"type": "error", "message": "括号不匹配，请检查权重写法"})
    if re.search(r"\(\s*\)", prompt):
        warnings.append({"type": "warning", "message": "存在空括号 ()"})
    if re.search(r"(^|,)\s*[^,(]+:\d", prompt):
        warnings.append({"type": "warning", "message": "检测到未加括号的权重语法，建议写成 (tag:1.2)"})

    # 建议
    if not any(keyword in full_text for keyword in QUALITY_KEYWORDS):
        suggestions.append({"type": "suggestion", "message": "缺少质量词（如 masterpiece、best quality），可补充提高稳定性"})
    if len(prompt) > 1000:
        suggestions.append({"type": "suggestion", "message": "提示词过长，建议精简到 1000 字符以内"})

    return {"errors": errors, "warnings": warnings, "suggestions": suggestions}
