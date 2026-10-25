"""指令纹章的效果解析。

背景（2026-10-10 的发现，依然成立）：图鉴里纹章的机制**不在结构化 buff 字段**里
（`effects` 基本为空），真正的效果写在 `detail` 文本里，例如
「当使用被刻印的指令卡进行攻击时,自身的宝具值增加10%(使用后需等待3回合才可再次使用)」。
所以这里按文本模式解析出**能建模的几类效果**，其余一律不猜：

- `charge`       使用该卡攻击时宝具值 +N%（花之魔术师）
- `critical_up`  被刻印的指令卡暴击威力 +N%（只在暴击卡上生效，与模拟器的 critical_up 对齐）
- `stars`        使用该卡攻击时获得 N 个暴击星
- `crit_focus`   暴击星集中度 +N%（影响谁是暴击星的主要携带者）

`card` 表示卡色限制（`仅当被刻印在技/力/迅指令卡上时`），空表示不限卡色。
"""
from __future__ import annotations

import re
from typing import Any

_CARD_WORDS = {"力": "buster", "技": "arts", "迅": "quick"}

_PATTERNS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    ("charge", re.compile(r"自身的宝具值增加\s*([0-9.]+)\s*%"), 1.0),
    ("critical_up", re.compile(r"暴击威力提升\s*([0-9.]+)\s*%"), 1.0),
    ("stars", re.compile(r"获得\s*([0-9.]+)\s*个?暴击星"), 1.0),
    ("crit_focus", re.compile(r"暴击星集中度提升\s*([0-9.]+)\s*%"), 1.0),
)

_CARD_RESTRICTION = re.compile(r"仅当被刻印在([力技迅])指令卡上")


def parse_command_code(detail: str) -> dict[str, Any]:
    """把一条纹章的说明文本解析成可建模的效果集合（解析不到就返回空）。"""
    text = str(detail or "")
    effects: dict[str, float] = {}
    for name, pattern, scale in _PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            effects[name] = effects.get(name, 0.0) + float(match.group(1)) * scale
        except ValueError:
            continue
    restriction = _CARD_RESTRICTION.search(text)
    return {
        "effects": effects,
        "card": _CARD_WORDS.get(restriction.group(1), "") if restriction else "",
        "unmodelled_only": not effects,
    }


def find_code(payload: dict[str, Any], name: str) -> dict[str, Any] | None:
    wanted = str(name or "").strip()
    for item in payload.get("items") or []:
        if str(item.get("name") or "").strip() == wanted:
            return item
    return None


def code_effects(payload: dict[str, Any], name: str) -> dict[str, Any]:
    """按名字取效果；纹章不在库里时返回空结果（调用方据此说明"数据缺失"）。"""
    item = find_code(payload, name)
    if item is None:
        return {"effects": {}, "card": "", "unmodelled_only": True, "found": False}
    parsed = parse_command_code(str(item.get("detail") or ""))
    parsed["found"] = True
    return parsed


def best_critical_code(
    payload: dict[str, Any], names: list[str], card_type: str
) -> dict[str, Any] | None:
    """在用户指定的纹章里挑一个适合该卡色、暴击威力最高的（卡色限制不满足就跳过）。"""
    best: dict[str, Any] | None = None
    for name in names or []:
        parsed = code_effects(payload, name)
        if not parsed.get("found"):
            continue
        effects = parsed.get("effects") or {}
        critical = float(effects.get("critical_up") or 0.0)
        if critical <= 0:
            continue
        restriction = str(parsed.get("card") or "")
        if restriction and restriction != card_type:
            continue
        candidate = {
            "name": str(name),
            "critical_up": critical,
            "stars": float(effects.get("stars") or 0.0),
        }
        if best is None or candidate["critical_up"] > best["critical_up"]:
            best = candidate
    return best


def assumed_command_code_effects(
    payload: dict[str, Any], names: list[str], card_type: str
) -> dict[str, Any]:
    """Summarize user-confirmed command codes usable on the chosen card type.

    The constraints list only code names, not which physical card carries
    which code. We therefore count each named code at most once and never
    invent a card mapping. Star generation is attributed to earlier cards;
    concentration/critical damage are attributed to the critical card.
    """
    stars: list[dict[str, Any]] = []
    critical: dict[str, Any] | None = None
    focus: dict[str, Any] | None = None
    seen: set[str] = set()
    for name in names or []:
        key = str(name).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        parsed = code_effects(payload, key)
        if not parsed.get("found"):
            continue
        restriction = str(parsed.get("card") or "")
        if restriction and card_type and restriction != card_type:
            continue
        effects = parsed.get("effects") or {}
        star_value = float(effects.get("stars") or 0.0)
        critical_value = float(effects.get("critical_up") or 0.0)
        focus_value = float(effects.get("crit_focus") or 0.0)
        if star_value > 0:
            stars.append({"name": key, "value": star_value})
        if critical_value > 0 and (
            critical is None or critical_value > float(critical["value"])
        ):
            critical = {"name": key, "value": critical_value}
        if focus_value > 0 and (
            focus is None or focus_value > float(focus["value"])
        ):
            focus = {"name": key, "value": focus_value}
    return {
        "stars": stars,
        "critical": critical,
        "focus": focus,
    }


def load_codes(path) -> dict[str, Any]:
    import json
    from pathlib import Path

    target = Path(path)
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
