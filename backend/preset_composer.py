"""Resolve preset IDs into a filtered, role-aware final prompt."""
from __future__ import annotations

import re
from typing import Iterable

import body_modification_presets
import clothing_presets
import config
import content_filter
import expansion_presets
import pose_prompts
import preset_registry
import prompt_agent
import prompt_budget
import scene_presets
import toy_presets


class ComposeError(ValueError):
    """Raised when a composition is unknown, conflicting, or over the limit."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


_DEFAULT_ROLES = ("女A", "女B", "男A", "男B")
_SCOPE_PROMPTS = {
    "girlA": "the first girl",
    "girlB": "the second girl",
    "boyA": "the first boy",
    "boyB": "the second boy",
}
_SCOPE_ALIASES = {
    "girla": "girlA",
    "girlb": "girlB",
    "boya": "boyA",
    "boyb": "boyB",
    "女a": "girlA",
    "女b": "girlB",
    "男a": "boyA",
    "男b": "boyB",
    "the first girl": "girlA",
    "the second girl": "girlB",
    "the first boy": "boyA",
    "the second boy": "boyB",
}
_BODY_SEPARATION_SUFFIX = (
    "separate opaque bodies with clear silhouettes, exactly one head and two arms and two legs per person, "
    "no duplicate limbs, no extra limbs, no merged bodies"
)
_COUNT_ONLY_TAG = re.compile(
    r"^(?:exactly\s+)?(?:\d+|one|two|three|four|five|six)"
    r"\s+(?:separate\s+)?(?:people|characters?)$",
    re.IGNORECASE,
)
_FULL_COVER_IDS = {
    "latex_catsuit",
    "leather_high_collar_coat",
    "men_mechanic_jumpsuit",
    "knight_armor",
    "dragon_knight_armor",
}
_OPEN_DISPLAY_IDS = {
    "sheer_clothing",
    "men_sheer_mesh_top",
    "backless_evening_dress",
    "lifted_skirt_layer",
    "harness_cage_top",
}
_EXPLICIT_CONFLICT_PAIRS = {
    frozenset(("mod_chest_chain", "mod_collarbone_bar")),
    frozenset(("mod_spine_ornament", "mod_back_ring_pair")),
    frozenset(("mod_energy_node", "mod_chest_chain")),
}
_COLOR_SLOTS = {"primary", "secondary", "accent"}
_MAX_COLOR_LENGTH = 40
_REGISTRY_KIND = {
    "clothing": "clothing",
    "body_modification": "body",
    "toy": "toy",
    "expansion": "expansion",
}


def _catalog_maps() -> tuple[dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict]]:
    poses = {str(item["id"]): item for item in prompt_agent.POSE_PRESETS}
    clothing = {str(item["id"]): item for item in clothing_presets.CLOTHING_PRESETS}
    scenes = {str(item["id"]): item for item in scene_presets.SCENE_PRESETS}
    modifications = {str(item["id"]): item for item in body_modification_presets.BODY_MODIFICATION_PRESETS}
    toys = {str(item["id"]): item for item in toy_presets.TOY_PRESETS}
    expansions = {str(item["id"]): item for item in expansion_presets.EXPANSION_PRESETS}
    return poses, clothing, scenes, modifications, toys, expansions


def _as_selection(raw: object) -> dict:
    if isinstance(raw, str):
        return {"id": raw, "scope": "all"}
    if not isinstance(raw, dict):
        raise ComposeError("组合项必须是预设 ID 或包含 id/scope 的对象")
    preset_id = str(raw.get("id") or "").strip()
    if not preset_id:
        raise ComposeError("组合项缺少 id")
    colors_raw = raw.get("colors") if isinstance(raw.get("colors"), dict) else {}
    colors: dict[str, str] = {}
    for slot, value in colors_raw.items():
        key = str(slot).strip().lower()
        color = str(value).strip()
        if key not in _COLOR_SLOTS:
            raise ComposeError(f"不支持的颜色槽：{slot}")
        if not color:
            continue
        if len(color) > _MAX_COLOR_LENGTH:
            raise ComposeError(f"颜色值过长：{key}")
        colors[key] = color
    scope = _canonical_scope(raw.get("scope") or "all")
    return {
        "id": preset_id,
        "scope": scope,
        "colors": colors,
    }


def _canonical_scope(raw: object) -> str:
    text = str(raw or "all").strip()
    if not text:
        return "all"
    return _SCOPE_ALIASES.get(text.lower(), text)


def _display_role(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    canonical = _canonical_scope(text)
    return _SCOPE_PROMPTS.get(canonical, text)


def _dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _fragment(preset: dict) -> str:
    draw_prompt = str(
        preset.get("occupied_scene_prompt")
        or preset.get("draw_prompt")
        or ""
    ).strip()
    tags = [
        str(tag).strip()
        for tag in preset.get("tags") or []
        if str(tag).strip() and not _COUNT_ONLY_TAG.match(str(tag).strip())
    ]
    body = draw_prompt or ", ".join(tags)
    people_prompt = str(preset.get("people_prompt") or "").strip()
    if people_prompt and people_prompt.lower() not in body.lower():
        return f"{people_prompt}, {body}"
    return body


def _scoped_fragment(preset: dict, scope: str) -> str:
    fragment = _fragment(preset)
    canonical = _canonical_scope(scope)
    if canonical == "all":
        return fragment
    label = _SCOPE_PROMPTS.get(canonical, canonical)
    return f"for {label}: {fragment}"


def _role_list(payload: dict, pose: dict | None) -> list[str]:
    raw = payload.get("role_order")
    if isinstance(raw, list):
        roles = _dedupe(_display_role(item) for item in raw if str(item).strip())
    elif pose:
        roles = [_display_role(item) for item in pose.get("role_slots") or [] if str(item).strip()]
    else:
        roles = []
    if not roles and str(payload.get("pose_id") or "").strip():
        raise ComposeError("体位缺少角色槽位，无法生成角色顺序")
    return roles


def _validate_scope(scope: str, roles: list[str], *, pose: dict | None) -> None:
    canonical = _canonical_scope(scope)
    if canonical == "all":
        return
    if pose and str(pose.get("people")) == "单人" and canonical not in ("主体", "all"):
        raise ComposeError(f"单人构图中不能使用角色范围：{canonical}")
    if canonical in _SCOPE_PROMPTS:
        return
    if canonical in _DEFAULT_ROLES or scope in _DEFAULT_ROLES or (roles and scope in roles):
        return
    raise ComposeError(f"未知角色范围：{canonical}")


def _validate_compatibility(
    scene_id: str,
    pose: dict | None,
    selected: list[dict],
) -> None:
    """A compatibility list is an allow-list that applies when a scene is selected."""
    if not scene_id:
        return
    for preset in [pose, *[item["preset"] for item in selected]]:
        if not preset:
            continue
        allowed = [str(item).strip() for item in preset.get("compatibility") or [] if str(item).strip()]
        if allowed and scene_id not in allowed:
            raise ComposeError(
                f"预设 {preset['id']} 与场景 {scene_id} 不兼容，允许场景：{', '.join(allowed)}"
            )


def _check_conflicts(selected_ids: list[str]) -> None:
    selected = set(selected_ids)
    if selected & _FULL_COVER_IDS and selected & _OPEN_DISPLAY_IDS:
        full = sorted(selected & _FULL_COVER_IDS)
        opened = sorted(selected & _OPEN_DISPLAY_IDS)
        raise ComposeError(f"封闭全身装与开放展示装冲突：{full} / {opened}")
    for pair in _EXPLICIT_CONFLICT_PAIRS:
        if pair <= selected:
            raise ComposeError(f"预设冲突：{sorted(pair)}")


# ── 标签级冲突检测（M2，2026-11-10） ──
# 与 _check_conflicts 的区别：
# - _check_conflicts 是预设 ID 级，硬阻断（raise ComposeError）
# - _check_tag_conflicts 是标签级，软警告（返回 warnings + 建议）

# 互斥标签对：(A 组, B 组, 说明, 建议)
_TAG_CONFLICT_RULES: tuple[tuple[frozenset[str], frozenset[str], str, str], ...] = (
    (
        frozenset({"lying prone", "prone", "lying face down"}),
        frozenset({"far leg raised", "pelvis toward partner", "raised hips"}),
        "俯卧和抬腿朝向对方在几何上冲突，模型只能二选一",
        "建议改用 lying on side，或去掉 far leg raised",
    ),
    (
        frozenset({"head turned back", "looking back"}),
        frozenset({"looking at partner", "looking at viewer", "eye contact"}),
        "回头和看对方/看镜头是互斥的朝向",
        "建议二选一：要回头就写 looking back，要交流就写 looking at partner",
    ),
    (
        frozenset({"standing", "standing up", "on feet"}),
        frozenset({"lying", "prone", "supine", "lying on back", "lying on side", "on back"}),
        "站立和躺卧互斥",
        "建议只保留一个姿势标签",
    ),
    (
        frozenset({"sitting", "seated", "kneeling"}),
        frozenset({"standing", "standing up", "on feet"}),
        "坐/跪和站立互斥",
        "建议只保留一个姿势标签",
    ),
    (
        frozenset({"from behind", "from back"}),
        frozenset({"facing viewer", "looking at viewer", "face to face"}),
        "背后视角和面向观众/面对面前冲突",
        "建议二选一",
    ),
    (
        frozenset({"eyes closed", "closed eyes"}),
        frozenset({"looking at viewer", "looking at partner", "eye contact"}),
        "闭眼和视线交互互斥",
        "如果强调表情交流，去掉 eyes closed",
    ),
    (
        frozenset({"spread legs"}),
        frozenset({"legs together", "closed legs"}),
        "腿分开和并拢互斥",
        "建议只保留一个",
    ),
)


def _normalize_tags_for_conflict(prompt: str) -> str:
    """把提示词转成小写、去标点的字符串，便于子串匹配。"""
    import re

    return re.sub(r"[^a-z0-9,\- ]", " ", prompt.lower())


def _check_tag_conflicts(prompt: str) -> list[str]:
    """检测标签级冲突，返回警告列表（带修正建议）。

    只做警告，不修改提示词（用户 2026-11-10 确认「警告 + 建议」）。
    """
    norm = _normalize_tags_for_conflict(prompt)
    warnings: list[str] = []
    for group_a, group_b, reason, suggestion in _TAG_CONFLICT_RULES:
        hit_a = [t for t in group_a if t in norm]
        hit_b = [t for t in group_b if t in norm]
        if hit_a and hit_b:
            warnings.append(
                f"检测到冲突：{', '.join(hit_a)} 与 {', '.join(hit_b)} —— {reason}。{suggestion}"
            )
    return warnings


def compose_presets(payload: dict, *, restriction_enabled: bool = False) -> dict:
    """Validate and compose a preset-only prompt.

    ``payload`` accepts only preset IDs and short role/scope metadata. The
    client cannot inject arbitrary long prompts into the final result.
    """
    pose_id = str(payload.get("pose_id") or "").strip()
    scene_id = str(payload.get("scene_id") or "").strip()
    clothing_raw = payload.get("clothing") or []
    modifications_raw = payload.get("body_modifications") or []
    toys_raw = payload.get("toys") or []
    expansions_raw = payload.get("expansions") or []
    if (
        not isinstance(clothing_raw, list)
        or not isinstance(modifications_raw, list)
        or not isinstance(toys_raw, list)
        or not isinstance(expansions_raw, list)
    ):
        raise ComposeError("clothing、body_modifications、toys 与 expansions 必须是数组")

    clothing = [_as_selection(item) for item in clothing_raw]
    modifications = [_as_selection(item) for item in modifications_raw]
    toys = [_as_selection(item) for item in toys_raw]
    expansions = [_as_selection(item) for item in expansions_raw]
    max_items = config.PRESET_COMPOSITION_MAX_ITEMS
    if (
        len(clothing)
        + len(modifications)
        + len(toys)
        + len(expansions)
        + int(bool(pose_id))
        + int(bool(scene_id))
        > max_items
    ):
        raise ComposeError(f"单个组合最多包含 {max_items} 个预设")

    poses, clothing_map, scenes, modifications_map, toys_map, expansions_map = _catalog_maps()
    pose = None
    if pose_id:
        pose = poses.get(pose_id)
        if not pose:
            raise ComposeError(f"不存在的体位 ID：{pose_id}")
    scene = None
    if scene_id:
        scene = scenes.get(scene_id)
        if not scene:
            raise ComposeError(f"不存在的场景 ID：{scene_id}")

    selected: list[dict] = []
    for item in clothing:
        preset = clothing_map.get(item["id"])
        if not preset:
            raise ComposeError(f"不存在的服装 ID：{item['id']}")
        selected.append({**item, "preset": preset, "kind": "clothing"})
    for item in modifications:
        preset = modifications_map.get(item["id"])
        if not preset:
            raise ComposeError(f"不存在的身体改造 ID：{item['id']}")
        selected.append({**item, "preset": preset, "kind": "body_modification"})
    for item in toys:
        preset = toys_map.get(item["id"])
        if not preset:
            raise ComposeError(f"不存在的性玩具 ID：{item['id']}")
        selected.append({**item, "preset": preset, "kind": "toy"})
    for item in expansions:
        preset = expansions_map.get(item["id"])
        if not preset:
            raise ComposeError(f"不存在的扩张 ID：{item['id']}")
        selected.append({**item, "preset": preset, "kind": "expansion"})

    roles = _role_list(payload, pose)
    if pose and pose.get("people") in {"双人", "多人"} and roles:
        expected = int(pose.get("people_count") or len(pose.get("role_slots") or []))
        if expected and len(roles) != expected:
            label = "多人" if pose.get("people") == "多人" else "双人"
            raise ComposeError(f"{label}体位需要 {expected} 个角色，当前为 {len(roles)} 个")
    if scene and scene.get("people") == "单人":
        scoped = [
            item["scope"]
            for item in [*clothing, *modifications, *toys, *expansions]
            if _canonical_scope(item["scope"]) != "all"
        ]
        if scoped:
            raise ComposeError("单人场景不能使用角色范围")

    seen_per_role: dict[tuple[str, str], int] = {}
    for item in selected:
        scope = item["scope"]
        _validate_scope(scope, roles, pose=pose)
        key = (item["kind"], scope)
        seen_per_role[key] = seen_per_role.get(key, 0) + 1
        definition = preset_registry.PRESET_KIND_BY_KEY[_REGISTRY_KIND[item["kind"]]]
        limit = definition.max_per_scope or max_items
        if seen_per_role[key] > limit:
            raise ComposeError(
                f"角色 {scope} 的{definition.label}超过上限 {limit}"
            )

    selected_ids = _dedupe(
        [pose_id, scene_id]
        + [item["id"] for item in clothing]
        + [item["id"] for item in modifications]
        + [item["id"] for item in toys]
        + [item["id"] for item in expansions]
    )
    _validate_compatibility(scene_id, pose, selected)
    _check_conflicts(selected_ids)

    rating = "普通"
    for preset in [pose, scene, *[item["preset"] for item in selected]]:
        if not preset:
            continue
        if str(preset.get("rating") or ("R18" if preset.get("nsfw") else "普通")) == "R18":
            rating = "R18"
        if preset.get("conflicts"):
            conflicts = set(str(item) for item in preset["conflicts"])
            overlap = conflicts & set(selected_ids)
            if overlap:
                raise ComposeError(f"{preset['id']} 与以下预设冲突：{sorted(overlap)}")

    # 按优先级收集片段：P0 必留，P1 尽量留，P2 可丢
    tagged_fragments: list[tuple[int, str]] = []
    if roles:
        tagged_fragments.append(
            (prompt_budget.P0, "character roles from left to right: " + ", ".join(roles))
        )
    if pose:
        tagged_fragments.append((prompt_budget.P0, pose_prompts.pose_prompt(pose, "core")))
    if pose and pose.get("body_separation"):
        tagged_fragments.append((prompt_budget.P0, _BODY_SEPARATION_SUFFIX))
    if scene:
        tagged_fragments.append((prompt_budget.P1, _fragment(scene)))
        # 按场景的路人密度追加人群描述（2026-11-09）
        density = str(scene.get("pc_density") or "optional")
        if density == "required":
            tagged_fragments.append(
                (prompt_budget.P2, "background characters, crowd in the distance, depth of field")
            )
        elif density == "none":
            # 私人场景：明确不要路人
            tagged_fragments.append((prompt_budget.P2, "empty surroundings, no other people"))

    # 每个角色的第一件服装算 P1（保证每个角色都有衣着描述），其余算 P2
    # 2026-11-10：默认按 scope 分组合并（compact），把「每部位一条」改成「每角色一句」
    compact = payload.get("compact_prompt")
    if compact is None:
        compact = True

    if compact:
        # 按 scope 分组，每组内 fragment 用逗号拼接
        grouped: dict[str, list[str]] = {}
        scope_order: list[str] = []
        for item in selected:
            fragment = _fragment(item["preset"])
            color_terms = [
                f"{slot} color {value}"
                for slot, value in item["colors"].items()
                if value
            ]
            if color_terms:
                fragment = f"{fragment}, {', '.join(color_terms)}"
            scope_key = str(item["scope"]).strip().lower()
            if scope_key not in grouped:
                grouped[scope_key] = []
                scope_order.append(scope_key)
            grouped[scope_key].append(fragment)

        for idx, scope_key in enumerate(scope_order):
            fragments = grouped[scope_key]
            # 合并时去掉重复的 "wearing " 前缀（只保留第一个）
            cleaned: list[str] = []
            has_wearing = False
            for frag in fragments:
                if has_wearing and frag.startswith("wearing "):
                    cleaned.append(frag[len("wearing "):])
                else:
                    if frag.startswith("wearing "):
                        has_wearing = True
                    cleaned.append(frag)
            merged = ", ".join(cleaned)
            # 用原始 scope 的显示形式（保留大小写）
            scope_display = scope_key
            for item in selected:
                if str(item["scope"]).strip().lower() == scope_key:
                    scope_display = str(item["scope"]).strip()
                    break
            canonical = _canonical_scope(scope_key)
            if canonical == "all":
                final = merged
            else:
                final = f"for {scope_display}: {merged}"
            # 每个 scope 的第一组算 P1
            priority = prompt_budget.P1 if idx == 0 else prompt_budget.P2
            tagged_fragments.append((priority, final))
    else:
        # 旧格式：每个 preset 单独一条
        seen_scope: set[str] = set()
        for item in selected:
            fragment = _scoped_fragment(item["preset"], item["scope"])
            color_terms = [
                f"{slot} color {value}"
                for slot, value in item["colors"].items()
                if value
            ]
            if color_terms:
                fragment = f"{fragment}, {', '.join(color_terms)}"
            # 用原始 scope 字符串做 key（canonical 会把 角色A/角色B 都归一成 all）
            scope_key = str(item["scope"]).strip().lower()
            if scope_key not in seen_scope:
                priority = prompt_budget.P1
                seen_scope.add(scope_key)
            else:
                priority = prompt_budget.P2
            tagged_fragments.append((priority, fragment))

    prompt, dropped_tags = prompt_budget.trim_fragments(tagged_fragments)
    blocked_text = content_filter.is_hard_blocked(prompt)
    if blocked_text:
        raise ComposeError("组合内容命中永久禁止规则", status_code=403)
    if restriction_enabled and rating == "R18":
        raise ComposeError("内容限制已开启，组合包含 R18 预设", status_code=403)

    warnings: list[str] = []
    if rating == "R18":
        warnings.append("组合包含 R18 预设")
    if dropped_tags:
        warnings.append(f"提示词超出 CLIP 预算，已裁剪 {len(dropped_tags)} 个 tag")
    # 标签级冲突检测（M2，2026-11-10）
    warnings.extend(_check_tag_conflicts(prompt))

    return {
        "prompt": prompt,
        "rating": rating,
        "warnings": warnings,
        "blocked": False,
        "used_ids": selected_ids,
        "roles": roles,
        "budget": {
            "estimated_tokens": prompt_budget.estimate_tokens(prompt),
            "limit": prompt_budget.DEFAULT_BUDGET,
            "dropped_tags": dropped_tags[:10],
        },
        "items": {
            "pose_id": pose_id or None,
            "scene_id": scene_id or None,
            "clothing": clothing,
            "body_modifications": modifications,
            "toys": toys,
            "expansions": expansions,
        },
    }
