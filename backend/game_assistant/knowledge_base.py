"""目录侧知识库：指令纹章 / 概念礼装 / 魔术礼装。

与账号侧（`game_assistant_private.db` 与手抄快照）分工：这里回答「某件东西是什么、
有什么效果」，账号侧回答「我有没有、练到什么程度」。

数据来源：Atlas Academy CN 导出（`nice_command_code.json` / `nice_equip.json` /
`nice_mystic_code.json`）。效果解析复用 `skill_effects.parse_skill`，
因此卡色限制、条件、逐级数值的口径与从者技能完全一致。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .skill_effects import parse_skill

LIBRARIES = (
    "command_codes",
    "craft_essences",
    "mystic_codes",
    "materials",
    "events_cn",
    "events_jp",
    "class_boards",
)
SOURCES = {
    "command_codes": "nice_command_code_cn.json",
    "craft_essences": "nice_equip_cn.json",
    "mystic_codes": "nice_mystic_code_cn.json",
    "materials": "nice_item_cn.json",
    "events_jp": "nice_event_jp.json",
    "events_cn": "nice_event_cn.json",
    "class_boards": "nice_class_board_cn.json",
}
OUTPUT = {
    "command_codes": "command_codes_cn.json",
    "craft_essences": "craft_essences_cn.json",
    "mystic_codes": "mystic_codes_cn.json",
    "materials": "materials_cn.json",
    "events_jp": "events_jp.json",
    "events_cn": "events_cn.json",
    "class_boards": "class_boards_cn.json",
}
LEVEL = 10


def _effects(skill: dict[str, Any]) -> list[dict[str, Any]]:
    """把一个技能解析成效果列表（与其他模块同口径）。"""
    parsed = parse_skill(skill, level=LEVEL)
    return [
        {
            "kind": effect.kind,
            "value": effect.value,
            "values": [round(item, 4) for item in effect.values],
            "target": effect.target,
            "duration": effect.duration,
            "card": effect.card,
            "condition": effect.condition,
            "condition_label": effect.condition_label,
            "source": effect.source,
        }
        for effect in parsed.effects
    ]


def _skills(entry: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for index, skill in enumerate(entry.get("skills") or [], start=1):
        if not isinstance(skill, dict):
            continue
        result.append(
            {
                "slot": int(skill.get("num") or index),
                "name": str(skill.get("name") or ""),
                "detail": str(skill.get("detail") or ""),
                "cooldowns": [int(v) for v in (skill.get("coolDown") or []) if isinstance(v, (int, float))],
                "effects": _effects(skill),
            }
        )
    return result


def build_command_codes(entries: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for entry in entries:
        skills = _skills(entry)
        rows.append(
            {
                "id": entry.get("id"),
                "collection_no": entry.get("collectionNo"),
                "name": str(entry.get("name") or ""),
                "rarity": entry.get("rarity"),
                "illustrator": str(entry.get("illustrator") or ""),
                "comment": str(entry.get("comment") or ""),
                # 纹章的机制常常只写在技能文案里（例：花之魔术师「攻击时宝具值 +10%，
                # 使用后需等待 3 回合」），所以文案必须一起入库。
                "detail": " / ".join(skill["detail"] for skill in skills if skill["detail"]),
                "effects": [effect for skill in skills for effect in skill["effects"]],
            }
        )
    rows.sort(key=lambda item: (int(item["rarity"] or 0), str(item["name"])))
    return _payload("command_codes", rows, len(entries))


def build_craft_essences(entries: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for entry in entries:
        if not entry.get("name"):
            continue
        rows.append(
            {
                "id": entry.get("id"),
                "collection_no": entry.get("collectionNo"),
                "name": str(entry.get("name") or ""),
                "rarity": entry.get("rarity"),
                "cost": entry.get("cost"),
                "lv_max": entry.get("lvMax"),
                "atk_max": entry.get("atkMax"),
                "hp_max": entry.get("hpMax"),
                "bond_equip_owner": entry.get("bondEquipOwner"),
                "detail": " / ".join(skill["detail"] for skill in _skills(entry) if skill["detail"]),
                "effects": [effect for skill in _skills(entry) for effect in skill["effects"]],
            }
        )
    rows.sort(key=lambda item: (-(int(item["rarity"] or 0)), str(item["name"])))
    return _payload("craft_essences", rows, len(entries))


def build_mystic_codes(entries: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for entry in entries:
        rows.append(
            {
                "id": entry.get("id"),
                "name": str(entry.get("name") or ""),
                "short_name": str(entry.get("shortName") or ""),
                "detail": str(entry.get("detail") or ""),
                "max_lv": entry.get("maxLv"),
                "exp_required": entry.get("expRequired"),
                "skills": _skills(entry),
            }
        )
    rows.sort(key=lambda item: str(item["name"]))
    return _payload("mystic_codes", rows, len(entries))


def build_materials(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """素材 / 道具名库。

    注意：**掉落关卡信息不在 Atlas 里**（`nice_war.json` 的 15,284 个关卡
    `dropInfos` 全为空），所以这里只有「素材是什么」，没有「哪里掉」。
    """
    rows = []
    seen: set[tuple[str, Any]] = set()
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        key = (name, entry.get("type"))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "id": entry.get("id"),
                "name": name,
                "type": str(entry.get("type") or ""),
                "rarity": entry.get("rarity"),
                "background": str(entry.get("background") or ""),
                "detail": str(entry.get("detail") or ""),
                "drop_priority": entry.get("dropPriority"),
                "event_id": entry.get("eventId"),
            }
        )
    rows.sort(key=lambda item: (-(int(item["rarity"] or 0)), str(item["name"])))
    return _payload("materials", rows, len(entries))


def war_name_map(war_entries: list[dict[str, Any]]) -> dict[int, str]:
    """warId → 关卡/地图名称（用于把活动的关联关卡翻译成人看得懂的名字）。"""
    mapping: dict[int, str] = {}
    for war in war_entries:
        if not isinstance(war, dict) or war.get("id") is None:
            continue
        mapping[int(war["id"])] = str(war.get("longName") or war.get("name") or "")
    return mapping


def item_lookup(item_entries: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """itemId → {name, type}：把奖励/商店里的对象 id 解析成人看得懂的名字。

    两服共用同一套道具 id，所以日服活动也可以用国服道具表解析（名字会是中文，反而更好读）。
    """
    mapping: dict[int, dict[str, Any]] = {}
    for entry in item_entries:
        if not isinstance(entry, dict) or entry.get("id") is None:
            continue
        mapping[int(entry["id"])] = {
            "name": str(entry.get("name") or ""),
            "type": str(entry.get("type") or ""),
        }
    return mapping


def build_events(
    entries: list[dict[str, Any]],
    wars: dict[int, str] | None = None,
    items: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """未来活动库（**日服**侧）。

    日服版本领先国服，所以可以用它提前知道后面有什么活动与它们的结构；
    但**国服排期不能按日服进度线性推断**，因此这里只记录事实（名称/类型/起止时间/
    关联关卡），并在查询时标注来源为日服。
    """
    rows = []
    for entry in entries:
        rows.append(
            {
                "id": entry.get("id"),
                "name": str(entry.get("name") or ""),
                "short_name": str(entry.get("shortName") or ""),
                "type": str(entry.get("type") or ""),
                "started_at": entry.get("startedAt"),
                "ended_at": entry.get("endedAt"),
                "war_ids": list(entry.get("warIds") or []),
                "war_names": [wars.get(int(wid), "") for wid in (entry.get("warIds") or [])]
                if wars
                else [],
                "shop_count": len(entry.get("shop") or []),
                "reward_count": len(entry.get("rewards") or []),
                # 商店**全量**存储（此前只取前 40 项，导致素材兑换项常被截断），
                # 并把消耗素材解析成名字，于是「这个活动能换到 X 吗」可以直接查。
                "shop_items": [
                    {
                        "name": str(slot.get("name") or ""),
                        "shop_type": str(slot.get("shopType") or ""),
                        "costs": [
                            {
                                "item_id": (cost.get("item") or {}).get("id"),
                                "name": str((cost.get("item") or {}).get("name") or ""),
                                "amount": cost.get("amount") or cost.get("num"),
                            }
                            for cost in (slot.get("consumes") or [])
                            if isinstance(cost, dict)
                        ][:4],
                    }
                    for slot in (entry.get("shop") or [])
                    if isinstance(slot, dict) and slot.get("name")
                ],
                # 点位奖励：把对象 id 解析成素材名（此前只存 id，等于查不了）
                "reward_items": sorted(
                    {
                        (
                            gift.get("objectId"),
                            str((items or {}).get(int(gift.get("objectId") or 0), {}).get("name") or ""),
                            str((items or {}).get(int(gift.get("objectId") or 0), {}).get("type") or ""),
                        )
                        for reward in (entry.get("rewards") or [])
                        for gift in (reward.get("gifts") or [])
                        if isinstance(gift, dict) and str(gift.get("type")) == "item" and gift.get("objectId")
                    }
                ),
                "reward_object_ids": sorted(
                    {
                        gift.get("objectId")
                        for reward in (entry.get("rewards") or [])
                        for gift in (reward.get("gifts") or [])
                        if isinstance(gift, dict) and gift.get("objectId") is not None
                    }
                )[:30],
                "has_lottery": bool(entry.get("lotteries")),
                "has_tower": bool(entry.get("towers")),
            }
        )
    rows.sort(key=lambda item: int(item["started_at"] or 0))
    return _payload("events_jp", rows, len(entries))


def build_events_cn(
    entries: list[dict[str, Any]],
    wars: dict[int, str] | None = None,
    items: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = build_events(entries, wars, items)
    payload["library"] = "events_cn"
    payload["source"]["file"] = SOURCES["events_cn"]
    return payload


def cn_future_candidates(
    cn_payload: dict[str, Any],
    jp_payload: dict[str, Any],
    limit: int = 10,
    since: int = 0,
    require_war: bool = True,
) -> list[dict[str, Any]]:
    """国服「还没开」的活动候选 = 日服有、国服没有（按 id 做差集）。

    日服数据里没有“未来条目”，只有已经开始的；但日服领先国服若干版本，
    所以这个差集就是国服后面可能出的活动**候选**。国服排期与顺序可能与日服不同，
    必须如实标注，不能当成国服已确认的日程。
    """
    # 按“名称”比对而不是 id：两服的 id 集合并不一致（国服 2073 条 / 日服 1491 条），
    # 只按 id 做差集会翻出一堆 2016-2017 年的陈年活动，没有参考价值。
    cn_keys = {
        (str(item.get("name") or ""), str(item.get("short_name") or ""))
        for item in cn_payload.get("items") or []
    }
    rows = [
        item
        for item in jp_payload.get("items") or []
        if (str(item.get("name") or ""), str(item.get("short_name") or "")) not in cn_keys
        and int(item.get("started_at") or 0) >= since
        # 只要“有实际关卡”的正式活动：否则列表会被 AP/经验加倍之类的 campaign 灌满。
        and (bool(item.get("war_ids")) or not require_war)
    ]
    # 最近的排前面：国服接下来最可能出的就是日服最近这些。
    rows.sort(key=lambda item: -int(item["started_at"] or 0))
    return rows[:limit]


def _material_costs(entries: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """把 `[{item: {...}, amount: n}]` 形态的消耗解析成 id/名称/数量。"""
    costs = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        item = entry.get("item") or {}
        costs.append(
            {
                "item_id": item.get("id"),
                "name": str(item.get("name") or ""),
                "amount": entry.get("amount"),
            }
        )
    return costs


def _class_board_effect(square: dict[str, Any]) -> dict[str, Any]:
    """职阶天赋树节点的效果。

    实测（2026-10-11，Atlas CN 导出）：节点效果**不在 `functions`/`buffs` 里**，而是内联在
    `targetSkill` 中（一个完整的被动技能对象）。`skillType` 只有三类：
    - `passive`（609 个）：被动强化 —— `targetSkill` 带 name/detail，`upSkillLv` 是强化到的等级；
    - `commandSpell`（45 个）：令咒强化 —— 导出里**没有效果表**（Atlas CN 无 skill / commandSpell
      导出，均 404），只保留图标线索（形如 `cs_03861.png`）；
    - `none`（205 个）：**解锁闸门** —— 靠 `lock` 里的道具（例如「新星火炬」）开放后续节点，
      本身不授予效果。
    """
    target = square.get("targetSkill")
    if isinstance(target, dict):
        level = square.get("upSkillLv")
        return {
            "kind": "passive",
            "skill_id": target.get("id"),
            "name": str(target.get("name") or ""),
            "detail": str(target.get("detail") or target.get("unmodifiedDetail") or ""),
            "up_skill_lv": int(level) if isinstance(level, (int, float)) else 0,
        }
    skill_type = str(square.get("skillType") or "")
    if skill_type == "commandSpell":
        return {"kind": "commandSpell", "icon": str(square.get("icon") or ""), "name": ""}
    if skill_type == "none":
        return {"kind": "gate", "name": "解锁闸门"}
    return {"kind": skill_type or "unknown", "name": ""}


def build_class_boards(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """职阶天赋树（Class Score）目录数据。

    每职阶一张树。树级记录解锁素材（`dispItems`，例如「星光之砂」【星座开放道具】）；
    节点（square）记录：节点 id、消耗素材（id/名称/数量）、闸门需求（`lock_items`）、
    以及效果（`effect` / `effect_kind`，三类见 `_class_board_effect`）。
    **注意**：实际可用性取决于账号解锁了哪些节点，那部分数据在账号侧（尚未采集）；
    `commandSpell` 节点的具体效果表 Atlas CN 未提供，只给到图标线索。
    """
    rows = []
    for board in entries:
        squares = []
        for square in board.get("squares") or []:
            if not isinstance(square, dict):
                continue
            effect = _class_board_effect(square)
            squares.append(
                {
                    "square_id": square.get("id"),
                    "icon": str(square.get("icon") or ""),
                    "skill_type": str(square.get("skillType") or ""),
                    "costs": _material_costs(square.get("items")),
                    "lock_items": _material_costs((square.get("lock") or {}).get("items")),
                    "effect": effect,
                    "effect_kind": effect["kind"],
                    # 兼容旧字段：只有真正授予效果的节点才进 effects
                    "effects": [effect] if effect["kind"] == "passive" else [],
                }
            )
        rows.append(
            {
                "board_id": board.get("id"),
                "name": str(board.get("name") or ""),
                "classes": list(board.get("classes") or []),
                "board_materials": [
                    {
                        "item_id": item.get("id"),
                        "name": str(item.get("name") or ""),
                        "detail": str(item.get("detail") or ""),
                    }
                    for item in (board.get("dispItems") or [])
                    if isinstance(item, dict)
                ],
                "square_count": len(squares),
                "squares": squares,
            }
        )
    rows.sort(key=lambda item: int(item["board_id"] or 0))
    return _payload("class_boards", rows, len(entries))


def upcoming_events(payload: dict[str, Any], after: int, limit: int = 10) -> list[dict[str, Any]]:
    """给定 unix 时间戳，返回**日服**在此之后开始的正式活动（过滤掉 campaign 类）。"""
    campaign_types = {"campaign", "loginBonuses", "interludeCampaign", "combineCampaign"}
    rows = [
        item
        for item in payload.get("items") or []
        if int(item.get("started_at") or 0) > after
        and str(item.get("type") or "") not in campaign_types
        and not str(item.get("name") or "").startswith("[")
    ]
    rows.sort(key=lambda item: int(item["started_at"] or 0))
    return rows[:limit]


def _payload(library: str, rows: list[dict[str, Any]], source_entries: int) -> dict[str, Any]:
    return {
        "library": library,
        "source": {
            "name": "Atlas Academy CN export",
            "file": SOURCES[library],
            "entries": source_entries,
            "kept": len(rows),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "items": rows,
    }


BUILDERS = {
    "command_codes": build_command_codes,
    "craft_essences": build_craft_essences,
    "mystic_codes": build_mystic_codes,
    "materials": build_materials,
    "events_jp": build_events,
    "events_cn": build_events_cn,
    "class_boards": build_class_boards,
}


def build_library(library: str, source_dir: Path | str, out_dir: Path | str) -> Path:
    source_path = Path(source_dir) / SOURCES[library]
    entries = json.loads(source_path.read_text(encoding="utf-8"))
    if library in {"events_jp", "events_cn"}:
        war_file = "nice_war_jp.json" if library == "events_jp" else "nice_war_cn.json"
        war_path = Path(source_dir) / war_file
        wars = war_name_map(json.loads(war_path.read_text(encoding="utf-8"))) if war_path.exists() else None
        item_path = Path(source_dir) / SOURCES["materials"]
        items = item_lookup(json.loads(item_path.read_text(encoding="utf-8"))) if item_path.exists() else None
        payload = (
            build_events(entries, wars or {}, items or {})
            if library == "events_jp"
            else build_events_cn(entries, wars or {}, items or {})
        )
    else:
        payload = BUILDERS[library](entries)
    target = Path(out_dir) / OUTPUT[library]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    import config

    parser = argparse.ArgumentParser(description="从 Atlas 导出构建目录侧知识库")
    parser.add_argument("--source-dir", required=True, help="存放 nice_*.json 的目录")
    parser.add_argument("--out-dir", default="", help="默认写入 config.GAME_ASSISTANT_KB_DIR")
    parser.add_argument("--library", default="all", choices=("all", *LIBRARIES))
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir or config.GAME_ASSISTANT_KB_DIR)
    targets = LIBRARIES if args.library == "all" else (args.library,)
    for library in targets:
        target = build_library(library, args.source_dir, out_dir)
        payload = json.loads(target.read_text(encoding="utf-8"))
        print(f"已写入 {target}：{payload['source']['kept']} 条（{library}）", flush=True)
    return 0


if __name__ == "__main__":
    import sys

    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
