"""Guide generation and candidate planning for the FGO public knowledge slice."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import config
import llm

from .domain import (
    EventBundle,
    EventPhase,
    GuideDraft,
    GuideGenerationRequest,
    GuideGenerationResult,
    GuideSection,
    PlanCandidate,
    PlanStep,
    ProviderName,
    ProviderStatus,
    Quest,
)
from .provider_settings import get_provider_settings_service
from .providers import deepseek_json_chat, local_json_chat, openai_json_chat
from . import schedule
from .store import GameAssistantStore

SHANGHAI = ZoneInfo("Asia/Shanghai")
PROMPT_VERSION = "fgo-guide-v1"
_SERVICE: "GameAssistantService | None" = None


def now_shanghai() -> datetime:
    return datetime.now(SHANGHAI)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="minutes") if value else None


def _current_phase(bundle: EventBundle, now: datetime) -> EventPhase | None:
    opened = [phase for phase in bundle.phases if phase.opens_at and phase.opens_at <= now]
    return max(opened, key=lambda phase: phase.opens_at or bundle.starts_at, default=None)


# 活动生命周期（2026-10-15 定，前后端同用；起因：2026-10-15 13:59 幕末武斗神话结束后，
# 页面仍把它当"本期活动"完整展示 —— 视图里从来没有"已结束"这个概念）。
STATUS_RUNNING = "running"
STATUS_ENDED_SHOP_OPEN = "ended_shop_open"
STATUS_CLOSED = "closed"


def event_status(bundle: EventBundle, now: datetime | None = None) -> str:
    """活动处于哪一档：进行中 / 已结束但交换所还开 / 已完全关闭。

    口径：
      * `running`：`now < ends_at`；
      * `ended_shop_open`：`ends_at ≤ now < exchange_ends_at` —— 副本关了、**交换所还开着**
        （这一周里活动加成从者与交换清单还能用来换素材），所以不删，只折叠 + 标注；
      * `closed`：`now ≥ exchange_ends_at`，或活动本来就没有交换所。
    `ends_at` 当刻即算结束（与游戏里 13:59 截止一致）。
    """
    moment = now or now_shanghai()
    if moment < bundle.ends_at:
        return STATUS_RUNNING
    exchange = bundle.exchange_ends_at
    if exchange is not None and moment < exchange:
        return STATUS_ENDED_SHOP_OPEN
    return STATUS_CLOSED


def shop_state(bundle: EventBundle, now: datetime | None = None) -> dict[str, Any]:
    """交换所倒计时：结束时刻、剩余天数、是否当天截止、还开着没有。

    天数 = **向下取整**的整天数（`max(1, floor(剩余 / 24h))`）——对截止日来说保守一点更安全
    （写「剩余 6 天（截止 10-22 13:59）」而不是 7 天，不会让人以为还有一整周），且因为同时给出
    精确截止时刻，读数不会有歧义；截止日在**当天**时给 `ends_today=True`，界面写
    「今天 HH:MM 截止」——这样永远不会出现「剩余 0 天」。
    """
    moment = now or now_shanghai()
    exchange = bundle.exchange_ends_at
    if exchange is None:
        return {"ends_at": None, "state": "none", "days_left": None, "ends_today": False}
    remaining = (exchange - moment).total_seconds()
    if remaining <= 0:
        return {"ends_at": _iso(exchange), "state": "closed", "days_left": None, "ends_today": False}
    return {
        "ends_at": _iso(exchange),
        "state": "open",
        "days_left": max(1, int(remaining // 86400)),
        "ends_today": exchange.date() == moment.date(),
    }


def _next_phase(bundle: EventBundle, now: datetime) -> EventPhase | None:
    upcoming = [phase for phase in bundle.phases if phase.opens_at and phase.opens_at > now]
    return min(upcoming, key=lambda phase: phase.opens_at or bundle.ends_at, default=None)


def _available_quests(bundle: EventBundle, now: datetime) -> list[Quest]:
    return [
        quest
        for quest in bundle.quests
        if quest.available_from is not None and quest.available_from <= now
    ]


def _upcoming_quests(bundle: EventBundle, now: datetime) -> list[Quest]:
    return sorted(
        [
            quest
            for quest in bundle.quests
            if quest.available_from is not None and quest.available_from > now
        ],
        key=lambda quest: quest.available_from or bundle.ends_at,
    )


def _quest_summary(quest: Quest) -> dict[str, Any]:
    return {
        "quest_id": quest.quest_id,
        "name": quest.name,
        "type": quest.quest_type,
        "location": quest.location,
        "ap": quest.ap_cost,
        "level": quest.recommended_level,
        "unlock": quest.unlock_condition,
        "available_from": _iso(quest.available_from),
        "repeatable": quest.repeatable,
        "tags": quest.tags,
    }


def build_event_view(bundle: EventBundle, now: datetime | None = None) -> dict[str, Any]:
    current_now = now or now_shanghai()
    current = _current_phase(bundle, current_now)
    upcoming = _next_phase(bundle, current_now)
    return {
        "event": bundle.model_dump(mode="json"),
        "event_status": event_status(bundle, current_now),
        "quests_closed_at": _iso(bundle.ends_at),
        "shop": shop_state(bundle, current_now),
        "current_phase": current.model_dump(mode="json") if current else None,
        "next_phase": upcoming.model_dump(mode="json") if upcoming else None,
        "available_quests": [_quest_summary(quest) for quest in _available_quests(bundle, current_now)],
        "upcoming_quests": [
            _quest_summary(quest) for quest in _upcoming_quests(bundle, current_now)
        ],
        "server_time": current_now.isoformat(timespec="seconds"),
    }
def _guide_intent(goal: str) -> str:
    normalized = goal.lower()
    team_terms = ("组队", "队伍", "阵容", "配队", "team")
    if "90++" in normalized and any(term in normalized for term in team_terms):
        return "team_recommendation"
    next_event_terms = (
        "下一个活动", "下个活动", "下一期活动", "下一期", "后续活动", "未来活动",
        "活动日程", "活动安排", "接下来有什么活动", "接下来什么活动",
        "next event", "upcoming event", "next_event",
    )
    if any(term in normalized for term in next_event_terms):
        return "next_event"
    return "general"


def _template_draft(bundle: EventBundle, goal: str, intent: str, now: datetime) -> GuideDraft:
    """按意图选确定性模板（完全不经过模型）。"""
    if intent == "team_recommendation":
        return _template_team_guide(bundle, goal, now)
    if intent == "next_event":
        return _template_next_event(bundle, goal, now)
    return _template_guide(bundle, goal, now)


def _template_next_event(bundle: EventBundle, goal: str, now: datetime) -> GuideDraft:
    """回答"下一个活动是什么"：**只用 KB 里已确认的日程**，没有就明确说没有。

    这是 backlog 的硬要求：不许用日服进度、版本号或模型记忆推国服排期，所以这个意图在
    生成器里固定走确定性回答、不经过任何模型（见 generate() 里的分支）。
    """
    current = [
        f"当前活动：{bundle.title}，{_iso(bundle.starts_at)} 至 {_iso(bundle.ends_at)}"
        + (f"（交换所到 {_iso(bundle.exchange_ends_at)}）" if bundle.exchange_ends_at else "")
    ]
    upcoming = schedule.confirmed_events(now)
    bundle_sources = [source.source_id for source in bundle.sources][:2]
    if upcoming:
        bullets = [
            f"{item.title}：{_iso(item.starts_at) or '开始时间待定'} 至 {_iso(item.ends_at) or '结束时间待定'}"
            + (f"（{item.note}）" if item.note else "")
            + (
                f"｜来源：{item.source_title or item.source_url}"
                if (item.source_title or item.source_url)
                else ""
            )
            for item in upcoming[:5]
        ]
        summary = f"已确认 {len(upcoming)} 个后续活动日程。"
        warnings: list[str] = []
    else:
        bullets = ["暂无已确认的后续活动日程。"]
        summary = "只有当前在办活动有确认来源；下一个活动的官方日程尚未确认。"
        warnings = ["没有已确认日程：不要用日服进度、版本号或模型记忆推断国服排期，等官方公告。"]
    return GuideDraft(
        title="接下来的活动日程",
        summary=summary,
        current_phase="活动排期",
        sections=[
            GuideSection(heading="当前活动", bullets=current, citation_ids=bundle_sources),
            GuideSection(heading="后续活动", bullets=bullets, citation_ids=[]),
        ],
        warnings=warnings,
        citation_ids=bundle_sources,
    )


def _template_team_guide(bundle: EventBundle, goal: str, now: datetime) -> GuideDraft:
    target = next(
        (quest for quest in bundle.quests if quest.recommended_level == "90++"),
        None,
    )
    if target is None:
        return _template_guide(bundle, goal, now)
    bonus_servants = sorted(
        bundle.bonus_servants,
        key=lambda servant: (
            -servant.attack_bonus_percent,
            servant.class_name,
            servant.name,
        ),
    )
    assassin_bonus = [
        servant
        for servant in bonus_servants
        if servant.class_name == "Assassin"
    ]
    enemy_lines = target.enemy_waves or target.notes or ["敌方波次尚未结构化。"]
    target_available = target.available_from is None or target.available_from <= now
    trace_sources = target.source_ids or [source.source_id for source in bundle.sources]
    class_tags = "、".join(tag for tag in target.tags if tag not in {"自由本", "90++"})
    bonus_lines = [
        f"{servant.name}：{servant.class_name}，攻击威力 +{servant.attack_bonus_percent}%，牵绊 +{servant.bond_bonus_percent}%"
        for servant in bonus_servants[:10]
    ]
    return GuideDraft(
        title=f"{target.name} 90++ 推荐组队（候选）",
        summary="基于公开敌方波次和活动加成生成通用组队模板；尚未读取个人从者、宝具、技能和礼装库存。",
        current_phase=target.name,
        sections=[
            GuideSection(
                heading="目标与限制",
                summary=f"{target.name}，AP{target.ap_cost}，{target.unlock_condition}。",
                bullets=[
                    "当前未接入账号从者与礼装库存，因此只能生成角色定位模板，不能保证可直接照抄。",
                    "90++ 首次通关与奖励领取仍由人工处理。",
                ],
                citation_ids=trace_sources,
            ),
            GuideSection(
                heading="敌方结构",
                summary="以下敌方结构来自已发布的公开活动资料。",
                bullets=enemy_lines,
                citation_ids=trace_sources,
            ),
            GuideSection(
                heading="组队思路",
                summary=(
                    f"已知职阶标签：{class_tags}。请按敌方职阶克制关系选择输出。"
                    if class_tags
                    else "按当前敌方职阶选择克制输出，并兼顾多面清场。"
                ),
                bullets=[
                    "前两面优先准备稳定清场；最终面按公开 HP 选择单体或高宝具输出。",
                    "活动加成优先考虑 100% 加成从者；没有时可使用 50%/30% 加成或泛用输出。",
                    "若 90++ 尚未开放，本页只能作为预备方案，不能据此执行。",
                ],
                citation_ids=trace_sources,
            ),
            GuideSection(
                heading="候选阵容模板",
                summary="以下仅是从者定位模板，实际配置需要个人账号信息。",
                bullets=[
                    "模板A：克制职阶单体主输出 + 两名充能/宝具辅助 + 光炮补刀处理前两面。",
                    "模板B：自备光炮清前两面 + 借高配克制职阶单体输出处理最终面。",
                    "活动加成 Assassin 候选：" + ("、".join(servant.name for servant in assassin_bonus) if assassin_bonus else "当前没有结构化活动加成 Assassin。"),
                ],
                citation_ids=trace_sources,
            ),
            GuideSection(
                heading="缺失信息",
                summary="要生成可直接执行的最终组队，还需要账号侧数据。",
                bullets=[
                    "需要个人拥有的 Assassin、Berserker、辅助从者，以及宝具等级、技能、追加技能。",
                    "需要可用概念礼装、魔术礼装和助战列表。",
                    "在补齐这些信息前，不输出“必定三回合”或固定从者组合。",
                ],
                citation_ids=trace_sources,
            ),
            GuideSection(
                heading="活动加成参考",
                summary="公开公告列出的高倍率活动加成从者如下。",
                bullets=bonus_lines or ["活动加成从者尚未结构化。"],
                citation_ids=trace_sources,
            ),
        ],
        warnings=[
            "当前攻略没有个人账号从者、宝具、技能和礼装库存，无法给出可保证执行的最终组队。",
            (
                "90++ 已开放；仍请在游戏内确认敌方结构和实际配置。"
                if target_available
                else "90++ 尚未开放；当前时间只能生成候选模板，不能在游戏内验证。"
            ),
        ],
        citation_ids=trace_sources,
    )

def _template_guide(bundle: EventBundle, goal: str, now: datetime) -> GuideDraft:
    current = _current_phase(bundle, now)
    upcoming = _next_phase(bundle, now)
    available = _available_quests(bundle, now)
    free_quests = [quest for quest in available if quest.quest_type == "free"]
    old_90pp = next((quest for quest in bundle.quests if quest.recommended_level == "90++"), None)
    high_priority_shop = [item for item in bundle.shop_items if item.priority == "high"]
    source_ids = [source.source_id for source in bundle.sources]
    current_name = current.name if current else "活动尚未开始或已结束"
    next_text = (
        f"{upcoming.name}，开放时间 {_iso(upcoming.opens_at)}；条件：{upcoming.unlock_condition or '按公告'}"
        if upcoming
        else "当前没有已登记的后继阶段"
    )
    actions = [
        f"先完成当前阶段「{current_name}」已经开放的主线。",
        "首通已开放自由本，优先低成本节点，再考虑 AP40 节点。",
        "以当前阶段门槛和已领取主线奖励为停止条件，不为短期素材无目标连续周回。",
    ]
    if current and current.unlock_condition:
        actions.append(f"当前阶段开放条件：{current.unlock_condition}")
    future = [next_text]
    if upcoming:
        future.append(
            f"下一阶段目标：{upcoming.name}；开放前保留至少一次主线与首通所需 AP。"
        )
    future.append(
        "活动商店在关卡结束后仍开放至交换截止时间，但素材获取应在本体关卡关闭前完成。"
    )
    if old_90pp:
        future.append(
            f"90++ 暂不可提前刷取：{old_90pp.name}，AP{old_90pp.ap_cost}，{old_90pp.unlock_condition}。"
        )
    sections = [
        GuideSection(
            heading="活动机制",
            summary="本期活动按公开阶段逐日开放，并通过活动点数与商店兑换推进。",
            bullets=[f"{item.title}：{item.detail}" for item in bundle.mechanics],
            citation_ids=source_ids,
        ),
        GuideSection(
            heading="当前阶段",
            summary=f"当前阶段：{current_name}。目标：{goal}",
            bullets=actions,
            citation_ids=source_ids,
        ),
        GuideSection(
            heading="当前可刷关卡",
            summary=f"公共资料显示当前已开放 {len(available)} 个关卡入口，其中自由本 {len(free_quests)} 个。",
            bullets=[
                f"{quest.name}：AP{quest.ap_cost}，推荐等级 {quest.recommended_level or '未标注'}，{quest.location}"
                for quest in free_quests
            ]
            or ["当前没有可按公共时间表确认的自由本。"],
            citation_ids=source_ids,
        ),
        GuideSection(
            heading="后续解锁",
            summary="按阶段推进，不在未开放节点上提前规划重复执行。",
            bullets=future,
            citation_ids=source_ids,
        ),
        GuideSection(
            heading="商店优先级",
            summary="默认目标是有限库存优先；QP 等无限项不计入搬空条件。",
            bullets=[
                f"{item.name}：{item.currency}，库存 {item.stock if item.stock is not None else '无限'}，优先级 {item.priority}"
                for item in high_priority_shop
            ]
            or ["商店数据尚未结构化。"],
            citation_ids=source_ids,
        ),
    ]
    return GuideDraft(
        title=bundle.title,
        summary="这是一份只读公共资料生成的当前阶段攻略候选。",
        current_phase=current_name,
        sections=sections,
        warnings=[
            "尚未接入账号进度、AP、苹果和素材库存；计划只按公共事实生成条件步骤。",
            "首通奖励、任务奖励、商店兑换和高难关卡仍需人工确认。",
        ],
        citation_ids=source_ids,
    )


def _bundle_context(bundle: EventBundle, now: datetime) -> dict[str, Any]:
    """Return a compact fact view for generation.

    The complete bundle remains in SQLite and is exposed by the API. Sending
    every quest and shop row to a smaller local model causes truncated JSON, so
    generation receives only facts needed to explain the current phase.
    """
    generation_quests = [
        {
            "quest_id": quest.quest_id,
            "name": quest.name,
            "type": quest.quest_type,
            "ap": quest.ap_cost,
            "level": quest.recommended_level,
            "unlock": quest.unlock_condition,
            "available_from": _iso(quest.available_from),
            "enemy_waves": quest.enemy_waves,
            "notes": quest.notes,
        }
        for quest in bundle.quests
        if quest.quest_type == "free" or quest.recommended_level == "90++"
    ]
    gating_missions = [
        {
            "mission_no": mission.mission_no,
            "name": mission.name,
            "condition": mission.condition,
            "opens_at": _iso(mission.opens_at),
            "gates_phase_id": mission.gates_phase_id,
        }
        for mission in bundle.missions
        if mission.gates_phase_id
    ]
    priority_shop = [
        {
            "name": item.name,
            "currency": item.currency,
            "stock": item.stock,
            "priority": item.priority,
        }
        for item in bundle.shop_items
        if item.priority in {"high", "infinite"}
    ]
    current = _current_phase(bundle, now)
    upcoming = _next_phase(bundle, now)
    return {
        "current_state": {
            "server_time": _iso(now),
            "current_phase_id": current.phase_id if current else None,
            "current_phase_name": current.name if current else None,
            "next_phase_id": upcoming.phase_id if upcoming else None,
            "next_phase_name": upcoming.name if upcoming else None,
            "next_phase_opens_at": _iso(upcoming.opens_at) if upcoming else None,
        },
        "event": {
            "event_id": bundle.event_id,
            "revision": bundle.revision,
            "title": bundle.title,
            "server": bundle.server,
            "starts_at": _iso(bundle.starts_at),
            "ends_at": _iso(bundle.ends_at),
            "exchange_ends_at": _iso(bundle.exchange_ends_at),
            "tags": bundle.tags,
            "participation_requirement": bundle.participation_requirement,
        },
        "mechanics": [
            {"title": item.title, "detail": item.detail, "kind": item.kind}
            for item in bundle.mechanics
        ],
        "bonus_servants": [
            {
                "name": servant.name,
                "class_name": servant.class_name,
                "rarity": servant.rarity,
                "attack_bonus_percent": servant.attack_bonus_percent,
                "bond_bonus_percent": servant.bond_bonus_percent,
            }
            for servant in bundle.bonus_servants
        ],
        "phases": [
            {
                "phase_id": phase.phase_id,
                "name": phase.name,
                "opens_at": _iso(phase.opens_at),
                "unlock_condition": phase.unlock_condition,
                "summary": phase.summary,
            }
            for phase in bundle.phases
        ],
        "quests": generation_quests,
        "gating_missions": gating_missions,
        "priority_shop": priority_shop,
        "sources": [
            {"source_id": source.source_id, "title": source.title, "type": source.source_type}
            for source in bundle.sources
        ],
    }

def _guide_messages(bundle: EventBundle, goal: str, now: datetime) -> list[dict[str, str]]:
    context = json.dumps(_bundle_context(bundle, now), ensure_ascii=False, indent=2)
    intent = _guide_intent(goal)
    required_sections = (
        "目标与限制、敌方结构、组队思路、候选阵容模板、缺失信息、活动加成参考"
        if intent == "team_recommendation"
        else "活动机制、当前阶段、当前可刷关卡、后续解锁、商店优先级"
    )
    intent_rule = (
        "这是90++组队请求。必须明确个人账号数据缺失，只输出角色定位和候选模板，禁止声称固定阵容必定三回合。"
        if intent == "team_recommendation"
        else "这是当前活动综合攻略请求，按事实包总结当前阶段和候选行动。"
    )
    system = (
        "你是 Fate/Grand Order 国服公开活动攻略生成器。"
        "只能使用用户提供的事实包，不得补写活动时间、AP、关卡、商店或开放条件。"
        "所有事实性结论必须引用事实包中的 source_id。"
        "不能把攻略建议写成官方事实，不能计算事实包中不存在的数据。"
        "输出必须是严格 JSON，不要使用 Markdown 代码围栏。"
    )
    user = f"""
目标：{goal}

只返回一个完整、可解析的 JSON 对象，不要 Markdown、不要解释、不要思考过程。
输出结构必须为：
{{
  "title": "攻略标题",
  "summary": "一句话总结",
  "current_phase": "当前阶段名称",
  "sections": [
    {{"heading": "章节名", "summary": "一句话总结", "bullets": ["短结论"], "citation_ids": ["S1"]}}
  ],
  "warnings": ["不确定项"],
  "citation_ids": ["S1"]
}}

硬性要求：
1. sections 必须正好覆盖：{required_sections}。
2. 每个 section 最多 3 个 bullets；每条 bullet 不超过 80 个汉字。{intent_rule}
3. current_state 是规则引擎计算的权威状态；不得把 next_phase 写成 current_phase。所有时间和 AP 必须来自事实包；没有把握就写入 warnings，不要推测。
4. 所有事实性 section 至少引用一个存在的 source_id。
5. JSON 必须在最后一个 }} 完整结束，不能截断。

事实包：
{context}
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model response did not contain a JSON object")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("model response JSON must be an object")
    return payload


def _sanitize_guide(draft: GuideDraft, bundle: EventBundle) -> tuple[GuideDraft, list[str]]:
    valid = bundle.source_id_set()
    warnings: list[str] = []
    invalid_seen: set[str] = set()
    sections: list[GuideSection] = []
    for section in draft.sections:
        citations: list[str] = []
        for source_id in section.citation_ids:
            if source_id in valid:
                if source_id not in citations:
                    citations.append(source_id)
            else:
                invalid_seen.add(source_id)
        bullets = [item.strip() for item in section.bullets if item.strip()]
        sections.append(
            GuideSection(
                heading=section.heading.strip() or "未命名章节",
                summary=section.summary.strip(),
                bullets=bullets,
                citation_ids=citations,
            )
        )
    top_citations: list[str] = []
    for source_id in draft.citation_ids:
        if source_id in valid and source_id not in top_citations:
            top_citations.append(source_id)
        elif source_id not in valid:
            invalid_seen.add(source_id)
    if not sections:
        raise ValueError("guide must contain at least one section")
    if invalid_seen:
        warnings.append("已移除模型返回的未知来源：" + ", ".join(sorted(invalid_seen)))
    return (
        GuideDraft(
            title=draft.title.strip() or bundle.title,
            summary=draft.summary.strip(),
            current_phase=draft.current_phase.strip(),
            sections=sections,
            warnings=[*draft.warnings, *warnings],
            citation_ids=top_citations or sorted(valid),
        ),
        warnings,
    )


def _enforce_runtime_facts(
    draft: GuideDraft,
    bundle: EventBundle,
    now: datetime,
    intent: str,
) -> tuple[GuideDraft, list[str]]:
    """Keep time-sensitive facts under deterministic control."""
    if intent == "team_recommendation":
        target = next(
            (quest for quest in bundle.quests if quest.recommended_level == "90++"),
            None,
        )
        label = f"{target.name}（90++，尚未开放）" if target else "90++（尚未开放）"
        return draft.model_copy(update={"current_phase": label}), []
    current = _current_phase(bundle, now)
    if current is None:
        return draft, []
    template = _template_guide(bundle, "当前阶段规则修正", now)
    template_current = next(
        (section for section in template.sections if section.heading == "当前阶段"),
        None,
    )
    sections: list[GuideSection] = []
    for section in draft.sections:
        if "当前阶段" in section.heading and template_current is not None:
            sections.append(template_current)
        else:
            sections.append(section)
    warnings: list[str] = []
    if draft.current_phase.strip() != current.name:
        warnings.append("模型返回的阶段名称与规则引擎不一致，已按服务端事实修正。")
    return (
        draft.model_copy(
            update={
                "current_phase": current.name,
                "sections": sections,
                "warnings": [*draft.warnings, *warnings],
            }
        ),
        warnings,
    )

def _render_markdown(guide: GuideDraft, bundle: EventBundle) -> str:
    source_map = {source.source_id: source for source in bundle.sources}
    lines = [f"# {guide.title}", "", guide.summary, ""]
    if guide.current_phase:
        lines.extend([f"当前阶段：{guide.current_phase}", ""])
    for section in guide.sections:
        lines.extend([f"## {section.heading}", ""])
        if section.summary:
            lines.extend([section.summary, ""])
        for bullet in section.bullets:
            lines.append(f"- {bullet}")
        if section.citation_ids:
            links = []
            for source_id in section.citation_ids:
                source = source_map.get(source_id)
                links.append(f"[{source_id}]" + (f"({source.url})" if source else ""))
            lines.extend(["", "来源：" + " ".join(links)])
        lines.append("")
    if guide.warnings:
        lines.append("## 不确定项")
        lines.append("")
        lines.extend(f"- {warning}" for warning in guide.warnings)
    return "\n".join(lines).strip() + "\n"


def _build_team_plan(bundle: EventBundle, goal: str, now: datetime) -> PlanCandidate:
    target = next(
        (quest for quest in bundle.quests if quest.recommended_level == "90++"),
        None,
    )
    if target is None:
        return _build_plan(bundle, goal, now)
    current = _current_phase(bundle, now)
    return PlanCandidate(
        title=f"{target.name} 90++ 组队验证计划",
        objective=goal,
        current_phase=current.name if current else "未开始",
        steps=[
            PlanStep(
                step_id="team-unlock",
                phase_id="day5",
                title="确认 90++ 解锁状态",
                action="先推进第十一话至第十二话，并确认活动任务前置已经完成。",
                availability="upcoming",
                condition=target.unlock_condition,
                expected_cost=f"AP{target.ap_cost}/次（开放后）",
                stop_condition="90++ 未开放时只输出候选模板，不进入游戏。",
                citation_ids=["S3", "S4"],
            ),
            PlanStep(
                step_id="team-roster",
                phase_id="day5",
                title="确认个人输出与辅助",
                action="盘点可用 Assassin 单体、光炮、充能辅助、宝具等级、追加技能和礼装。",
                availability="conditional",
                condition="需要个人账号资源快照；当前未接入。",
                expected_cost="无游戏资源消耗",
                stop_condition="缺少从者或礼装信息时，不输出可直接执行的固定阵容。",
                citation_ids=["S5"],
            ),
            PlanStep(
                step_id="team-template",
                phase_id="day5",
                title="选择组队模板",
                action="按“单体主输出处理最终大怪 + 前两面光炮/补刀”的路线选择模板。",
                availability="conditional",
                condition="根据个人从者库存选择模板A或模板B。",
                expected_cost="仅候选，不消耗 AP",
                stop_condition="没有明确模板或助战要求时保持候选状态。",
                citation_ids=["S1", "S3"],
            ),
            PlanStep(
                step_id="team-manual-check",
                phase_id="day5",
                title="人工验证首局",
                action="在 90++ 开放后由用户手动进入副本并验证队伍稳定性。",
                availability="final",
                condition="第十二话通关且副本已开放。",
                expected_cost="首局按实际 AP 消耗",
                stop_condition="首通奖励、战斗失败或界面异常时暂停人工处理。",
                citation_ids=["S3"],
            ),
        ],
        stop_conditions=[
            "当前未接入账号从者、宝具、技能和礼装库存，计划不能直接执行。",
            "90++ 尚未开放，不能用当前公共事实验证固定阵容。",
            "不自动消耗 AP、苹果、圣晶石、呼符或令咒。",
        ],
        warnings=["该计划只用于组队信息补齐和人工验证，不是自动刷本计划。"],
        citation_ids=["S1", "S3", "S4", "S5"],
    )

def _build_plan(bundle: EventBundle, goal: str, now: datetime) -> PlanCandidate:
    intent = _guide_intent(goal)
    if intent == "next_event":
        return _build_next_event_plan(now)
    if intent == "team_recommendation":
        return _build_team_plan(bundle, goal, now)
    phases = sorted(
        [phase for phase in bundle.phases if phase.opens_at is not None],
        key=lambda phase: phase.opens_at or bundle.ends_at,
    )
    steps: list[PlanStep] = []
    for index, phase in enumerate(phases, start=1):
        if phase.opens_at and phase.opens_at <= now:
            availability = "current"
            condition = phase.unlock_condition or "当前已开放"
        else:
            availability = "upcoming"
            condition = (
                f"{_iso(phase.opens_at)} 开放；{phase.unlock_condition or '按公告'}"
                if phase.opens_at
                else phase.unlock_condition
            )
        steps.append(
            PlanStep(
                step_id=f"phase-{index}",
                phase_id=phase.phase_id,
                title=phase.name,
                action=phase.summary or "完成该阶段主线、NEW新选组关卡和已开放自由本。",
                availability=availability,  # type: ignore[arg-type]
                condition=condition,
                expected_cost="按实际关卡 AP 消耗",
                stop_condition="完成阶段解锁条件；遇到首通奖励、任务奖励或未知界面时暂停人工处理。",
                citation_ids=phase.source_ids or ["S1", "S3"],
            )
        )
    ninety_pp = next((quest for quest in bundle.quests if quest.recommended_level == "90++"), None)
    if ninety_pp:
        steps.append(
            PlanStep(
                step_id="final-90pp",
                phase_id="day5",
                title=f"90++ 候选周回：{ninety_pp.name}",
                action="第十二话开放后再评估是否周回；先满足有限商店和任务目标。",
                availability="final",
                condition=ninety_pp.unlock_condition,
                expected_cost=f"AP{ninety_pp.ap_cost}/次",
                stop_condition="达到用户指定目标或商店有限库存目标后立即停止；不在未确认目标时无限刷取。",
                citation_ids=ninety_pp.source_ids or ["S3"],
            )
        )
    return PlanCandidate(
        title=f"{bundle.title} 候选执行计划",
        objective=goal,
        current_phase=(_current_phase(bundle, now).name if _current_phase(bundle, now) else "未开始"),
        steps=steps,
        stop_conditions=[
            "未接入账号资源，不自动使用 AP、苹果、圣晶石、呼符或令咒。",
            "首通奖励、任务奖励、商店兑换和高难关卡保持人工处理。",
            "关卡阶段变化或活动 revision 更新后，旧计划自动失效。",
        ],
        warnings=["当前计划没有个人账号进度和库存，条件步骤不能直接执行。"],
        citation_ids=["S1", "S3", "S4"],
    )


def _build_next_event_plan(now: datetime) -> PlanCandidate:
    """日程意图只输出日程，绝不复用当前活动 bundle 的关卡步骤。"""
    upcoming = schedule.confirmed_events(now)
    if upcoming:
        steps = [
            PlanStep(
                step_id=f"upcoming-{item.event_id}",
                title=item.title,
                action="关注官方开催公告、开放时间与正式关卡资料；活动资料发布后再生成专属攻略和队伍推荐。",
                availability="upcoming",
                condition=(
                    f"{_iso(item.starts_at) or '开始时间待定'} 开放"
                    + (f"；预计到 {_iso(item.ends_at)}" if item.ends_at else "；结束时间待定")
                ),
                expected_cost="不消耗 AP",
                stop_condition="公告或活动开放时间变化时，以新的官方公告重新核对。",
                citation_ids=[],
            )
            for item in upcoming[:5]
        ]
        warnings = ["这里只列日程，不包含当前活动的关卡执行步骤。"]
    else:
        steps = [
            PlanStep(
                step_id="await-confirmed-schedule",
                title="等待已确认日程",
                action="等待官方公告，或在活动日历里核对并确认候选条目。",
                availability="conditional",
                condition="没有已确认且未结束的后续活动。",
                expected_cost="不消耗 AP",
                stop_condition="出现已确认的官方日程后再生成活动攻略。",
                citation_ids=[],
            )
        ]
        warnings = [
            "暂无已确认日程；不要用日服进度、版本号或模型记忆推断国服排期。",
            "这里只列日程，不包含当前活动的关卡执行步骤。",
        ]
    return PlanCandidate(
        title="接下来的活动日程",
        objective="列出已确认的后续活动，不执行旧活动步骤",
        current_phase="活动排期",
        steps=steps,
        stop_conditions=[
            "不根据候选日程或日服进度推断国服开放时间。",
            "活动正式资料未发布前，不生成具体关卡和组队计划。",
        ],
        warnings=warnings,
        citation_ids=[],
    )


def provider_statuses() -> list[ProviderStatus]:
    return get_provider_settings_service().guide_statuses()


class GameAssistantService:
    def __init__(
        self,
        store: GameAssistantStore | None = None,
        clock: Any = now_shanghai,
        schedule_loader: Callable[[], list[schedule.UpcomingEvent]] | None = None,
    ) -> None:
        self.store = store or GameAssistantStore()
        self.clock = clock
        self.schedule_loader = schedule_loader or schedule.load_schedule

    def _resolve_current(
        self,
        now: datetime,
    ) -> tuple[EventBundle | None, schedule.UpcomingEvent | None, str]:
        """Resolve the active main event first, then fall back to a time-valid bundle."""
        scheduled = schedule.current_main_event(now, items=self.schedule_loader())
        if scheduled is not None:
            bundle = self.store.get_bundle(scheduled.event_id)
            return bundle, scheduled, "ready" if bundle else "missing_bundle"
        current_bundle = next(
            (
                bundle
                for bundle in self.store.list_bundles()
                if bundle.starts_at <= now < bundle.ends_at
            ),
            None,
        )
        return current_bundle, None, "ready" if current_bundle else "no_current_event"

    @staticmethod
    def _schedule_only_view(
        scheduled: schedule.UpcomingEvent,
        now: datetime,
    ) -> dict[str, Any]:
        """Return a non-generatable current-event shell while facts are not imported."""
        event = {
            "event_id": scheduled.event_id,
            "revision": 0,
            "server": scheduled.server,
            "title": scheduled.title,
            "subtitle": "",
            "starts_at": _iso(scheduled.starts_at),
            "ends_at": _iso(scheduled.ends_at),
            "exchange_ends_at": None,
            "participation_requirement": "",
            "location": "",
            "tags": [],
            "mechanics": [],
            "bonus_servants": [],
            "phases": [],
            "quests": [],
            "missions": [],
            "shop_items": [],
            "sources": [],
            "observations": [],
        }
        return {
            "event": event,
            "event_status": STATUS_RUNNING,
            "data_status": "missing_bundle",
            "schedule_event": scheduled.model_dump(mode="json"),
            "quests_closed_at": _iso(scheduled.ends_at),
            "shop": {"ends_at": None, "state": "none", "days_left": None, "ends_today": False},
            "current_phase": None,
            "next_phase": None,
            "available_quests": [],
            "upcoming_quests": [],
            "server_time": now.isoformat(timespec="seconds"),
        }

    def bootstrap(self) -> dict[str, Any]:
        self.store.initialize()
        now = self.clock()
        bundle, scheduled, data_status = self._resolve_current(now)
        event_view = (
            build_event_view(bundle, now)
            if bundle is not None
            else (
                self._schedule_only_view(scheduled, now)
                if scheduled is not None
                else None
            )
        )
        if event_view is not None and bundle is not None:
            event_view["data_status"] = "ready"
            event_view["schedule_event"] = (
                scheduled.model_dump(mode="json") if scheduled is not None else None
            )
        latest = (
            self.store.latest_generation(bundle.event_id, bundle.revision)
            if bundle is not None
            else None
        )
        return {
            "event_view": event_view,
            "event_data_status": data_status,
            "providers": [item.model_dump(mode="json") for item in provider_statuses()],
            "latest_generation": latest.model_dump(mode="json") if latest else None,
            "boundaries": {
                "account_connected": True,
                "executor_connected": False,
                "plan_mode": "candidate_only",
            },
        }

    def list_events(self) -> list[dict[str, Any]]:
        self.store.initialize()
        now = self.clock()
        return [
            {
                "event_id": bundle.event_id,
                "revision": bundle.revision,
                "server": bundle.server,
                "title": bundle.title,
                "starts_at": _iso(bundle.starts_at),
                "ends_at": _iso(bundle.ends_at),
                "event_status": event_status(bundle, now),
                "current_phase": (
                    _current_phase(bundle, now).name if _current_phase(bundle, now) else None
                ),
                "source_count": len(bundle.sources),
            }
            for bundle in self.store.list_bundles()
        ]

    def generate(self, request: GuideGenerationRequest) -> GuideGenerationResult:
        self.store.initialize()
        if request.event_id is not None:
            bundle = self.store.get_bundle(request.event_id, request.revision)
        else:
            bundle, _scheduled, _status = self._resolve_current(self.clock())
        if bundle is None:
            raise LookupError("event revision not found")
        now = self.clock()
        intent = _guide_intent(request.goal)
        provider_used: ProviderName = request.provider
        model = ""
        fallback_reason: str | None = None
        warnings: list[str] = []
        provider_config = get_provider_settings_service().runtime_config(request.provider)
        try:
            if request.provider != "template" and not bool(provider_config.get("available")):
                raise ValueError(f"provider is not configured: {request.provider}")
            if intent == "next_event":
                # 日程类问题**固定确定性回答**：不让模型猜国服排期（backlog 硬要求）。
                draft = _template_draft(bundle, request.goal, intent, now)
                model = "deterministic-template"
                provider_used = "template"
                fallback_reason = "日程类问题固定走确定性回答：不许用模型记忆或日服进度推国服排期"
            elif request.provider == "template":
                draft = _template_draft(bundle, request.goal, intent, now)
                model = "deterministic-template"
            elif request.provider == "local":
                model = str(provider_config.get("model") or "")
                text = local_json_chat(
                    _guide_messages(bundle, request.goal, now),
                    base_url=str(provider_config.get("base_url") or ""),
                    model=model,
                    temperature=request.temperature,
                    max_tokens=4096,
                    timeout=config.GAME_ASSISTANT_LLM_TIMEOUT,
                )
                draft = GuideDraft.model_validate(_extract_json(text))
            elif request.provider == "deepseek":
                model = str(provider_config.get("model") or "")
                text = deepseek_json_chat(
                    _guide_messages(bundle, request.goal, now),
                    base_url=str(provider_config.get("base_url") or ""),
                    api_key=str(provider_config.get("api_key") or ""),
                    model=model,
                    temperature=request.temperature,
                    max_tokens=4096,
                    timeout=config.GAME_ASSISTANT_LLM_TIMEOUT,
                )
                draft = GuideDraft.model_validate(_extract_json(text))
            elif request.provider == "openai_compatible":
                model = str(provider_config.get("model") or "")
                text = openai_json_chat(
                    _guide_messages(bundle, request.goal, now),
                    base_url=str(provider_config.get("base_url") or ""),
                    api_key=str(provider_config.get("api_key") or ""),
                    model=model,
                    temperature=request.temperature,
                    max_tokens=4096,
                    timeout=config.GAME_ASSISTANT_LLM_TIMEOUT,
                    require_key=False,
                )
                draft = GuideDraft.model_validate(_extract_json(text))
            else:
                raise ValueError(f"unsupported provider: {request.provider}")
            draft, warnings = _sanitize_guide(draft, bundle)
        except Exception as exc:
            fallback_reason = f"{type(exc).__name__}: {exc}"
            draft = _template_draft(bundle, request.goal, intent, now)
            draft, warnings = _sanitize_guide(draft, bundle)
            provider_used = "template"
            model = "deterministic-template"
            warnings = [*warnings, "模型调用失败，已回退到确定性模板。"]
        draft, runtime_warnings = _enforce_runtime_facts(draft, bundle, now, intent)
        warnings = [*warnings, *runtime_warnings]
        plan = _build_plan(bundle, request.goal, now)
        guide_warnings = list(dict.fromkeys([*draft.warnings, *warnings, *plan.warnings]))
        draft = draft.model_copy(update={"warnings": guide_warnings})
        return GuideGenerationResult(
            generation_id=uuid.uuid4().hex,
            event_id=bundle.event_id,
            event_revision=bundle.revision,
            provider_requested=request.provider,
            provider_used=provider_used,
            model=model,
            prompt_version=PROMPT_VERSION,
            fallback_reason=fallback_reason,
            guide=draft,
            markdown=_render_markdown(draft, bundle),
            plan=plan,
            warnings=guide_warnings,
            created_at=now,
        )

    def generate_and_save(self, request: GuideGenerationRequest) -> GuideGenerationResult:
        result = self.generate(request)
        self.store.save_generation(result)
        return result

    def get_generation(self, generation_id: str) -> GuideGenerationResult | None:
        self.store.initialize()
        return self.store.get_generation(generation_id)


def get_service() -> GameAssistantService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = GameAssistantService()
    return _SERVICE


def reset_service() -> None:
    global _SERVICE
    _SERVICE = None
