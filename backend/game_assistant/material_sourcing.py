"""素材获取查询：缺素材 X → 优先刷哪个自由关卡 / 哪个活动能换。

两条来源：
- **掉落（效率优先）**：Mooncell「道具一览」top3 关卡库（`mooncell_drops`）。Atlas 侧没有掉落数据，
  所以这是唯一来源；它是 top3 而非全量，且随游戏版本变化。
- **活动**：`events_cn` / `events_jp` 的奖励对象（`reward_items`，活动直接发放）与商店
  （`shop_items`，含全量兑换项与消耗）。国服可执行、日服仅作参考（排期不同）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

from . import mooncell_drops

STALE_AFTER_DAYS = 30
WIKI_CAVEAT = (
    "掉落率是 wiki 口径，可以超过 100%（一次战斗可能掉多个；数值随游戏版本变化）；"
    "活动排期以国服公告为准，日服条目仅供参考。"
)


def _load(kb_dir: Path, filename: str) -> dict[str, Any]:
    target = kb_dir / filename
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _age_days(payload: dict[str, Any]) -> float | None:
    stamp = str((payload.get("source") or {}).get("generated_at") or "").strip()
    if not stamp:
        return None
    try:
        generated = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - generated).total_seconds() / 86400, 1)


def _wanted_names(material: str) -> set[str]:
    """查询用的名字集合：原写法 + 掉落库的别名归一（Atlas「祸骨」/ Mooncell「凶骨」）。"""
    base = str(material or "").strip()
    names = {base} if base else set()
    alias = mooncell_drops.NAME_ALIASES.get(base)
    if alias:
        names.add(alias)
    for source, target in mooncell_drops.NAME_ALIASES.items():
        if target == base:
            names.add(source)
    names.discard("")
    return names


def events_granting(
    material: str,
    payload: dict[str, Any] | None,
    region: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """活动侧：该素材作为「奖励对象」或「商店兑换项」出现的活动（最近的在前）。"""
    wanted = _wanted_names(material)
    if not wanted:
        return []
    rows: list[dict[str, Any]] = []
    for item in (payload or {}).get("items") or []:
        grants: list[dict[str, Any]] = []
        for entry in item.get("reward_items") or []:
            name = entry[1] if isinstance(entry, (list, tuple)) and len(entry) > 1 else ""
            if str(name).strip() in wanted:
                grants.append({"source": "point_reward", "name": str(name)})
        for slot in item.get("shop_items") or []:
            if str(slot.get("name") or "").strip() in wanted:
                grants.append(
                    {
                        "source": "shop",
                        "name": str(slot.get("name")),
                        "costs": [
                            str(cost.get("name") or "")
                            for cost in (slot.get("costs") or [])[:4]
                        ],
                    }
                )
        if grants:
            rows.append(
                {
                    "region": region,
                    "name": str(item.get("name") or ""),
                    "type": str(item.get("type") or ""),
                    "started_at": item.get("started_at"),
                    "grants": grants,
                }
            )
    rows.sort(key=lambda row: row.get("started_at") or 0, reverse=True)
    return rows[:limit]


def material_sourcing(
    material: str,
    *,
    kb_dir: Path | str | None = None,
    limit: int = 3,
    event_limit: int = 5,
) -> dict[str, Any]:
    """合成回答：优先自由关卡（top3）+ 能换到/发放该素材的活动。"""
    base = str(material or "").strip()
    if not base:
        raise ValueError("material 不能为空")
    directory = Path(kb_dir or config.GAME_ASSISTANT_KB_DIR)
    drops_payload = _load(directory, mooncell_drops.OUTPUT_FILENAME)
    cn_payload = _load(directory, "events_cn.json")
    jp_payload = _load(directory, "events_jp.json")

    quests = mooncell_drops.drops_for_material(drops_payload, base, limit=limit)
    cn_events = events_granting(base, cn_payload, "cn", event_limit)
    jp_events = events_granting(base, jp_payload, "jp", event_limit)

    age = _age_days(drops_payload)
    notes: list[str] = []
    if not quests:
        notes.append(
            "掉落库里没有该素材：它只覆盖可刷素材的 top3（技能石 / 职阶棋子 / 铜银金素材 / 一般道具，共 108 项）"
        )
    if age is None:
        notes.append("掉落库尚未生成，先跑 python -m game_assistant.mooncell_drops")
    elif age > STALE_AFTER_DAYS:
        notes.append(
            f"掉落库已生成 {age} 天，建议重跑 python -m game_assistant.mooncell_drops 刷新（版本更新会影响掉落）"
        )
    if not cn_events and not jp_events:
        notes.append("已导入的活动库中没有任何活动直接发放或商店兑换该素材（活动路线给不了它）")
    notes.append(WIKI_CAVEAT)

    return {
        "material": base,
        "queried_names": sorted(_wanted_names(base)),
        "free_quests": quests,
        "events": {"cn": cn_events, "jp": jp_events},
        "sources": {
            "free_quests": {
                "library": mooncell_drops.LIBRARY,
                "file": mooncell_drops.OUTPUT_FILENAME,
                "generated_at": (drops_payload.get("source") or {}).get("generated_at"),
                "age_days": age,
                "coverage": "每素材 top3 关卡（章节 / 关卡 / 消耗 AP / 掉落率）",
            },
            "events_cn": {"file": "events_cn.json", "entries": len(cn_payload.get("items") or [])},
            "events_jp": {"file": "events_jp.json", "entries": len(jp_payload.get("items") or [])},
        },
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="查询：缺素材 X → 刷哪个自由关卡 / 哪个活动能换")
    parser.add_argument("--material", required=True)
    parser.add_argument("--limit", type=int, default=3, help="掉落关卡条数（默认 top3）")
    parser.add_argument("--event-limit", type=int, default=5)
    parser.add_argument("--kb-dir", default="")
    args = parser.parse_args(argv)
    result = material_sourcing(
        args.material,
        kb_dir=args.kb_dir or None,
        limit=args.limit,
        event_limit=args.event_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
