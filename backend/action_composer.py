"""Deterministic catalog and compiler for Action Composition."""
from __future__ import annotations

from typing import Any


def _options(mapping: dict[str, tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"id": option_id, "label": label, "tag": tag}
        for option_id, (label, tag) in mapping.items()
    ]


BASE_STATES = {
    "side_lying": ("侧卧", "side lying"),
    "sitting": ("坐姿", "sitting"),
    "kneeling": ("跪姿", "kneeling"),
    "standing": ("站姿", "standing"),
    "lying_back": ("仰卧", "lying on back"),
    "prone": ("俯卧", "lying prone"),
}
PELVIS_STATES = {
    "toward_partner": ("朝向对方", "pelvis toward partner"),
    "toward_viewer": ("朝向镜头", "pelvis toward viewer"),
    "away": ("背向", "pelvis away"),
    "side": ("侧向", "side-facing pelvis"),
    "raised": ("抬髋", "raised pelvis"),
}
NEAR_LEG_STATES = {
    "extended": ("伸展", "near leg extended"),
    "bent": ("弯曲", "near leg bent"),
    "raised": ("抬起", "near leg raised"),
    "supported": ("被支撑", "near leg supported"),
}
FAR_LEG_STATES = {
    "extended": ("伸展", "far leg extended"),
    "bent": ("弯曲", "far leg bent"),
    "raised": ("抬起", "far leg raised"),
    "supported": ("被支撑", "far leg supported"),
}
ARM_STATES = {
    "natural": ("自然放置", "arms resting naturally"),
    "support": ("支撑身体", "arms supporting body"),
    "hold_partner_leg": ("抱住对方腿", "holding partner's leg"),
    "hold_partner": ("环抱对方", "holding partner"),
    "fixed": ("被固定", "arms restrained"),
}
HEAD_STATES = {
    "facing": ("面向对方", "facing partner"),
    "profile": ("侧脸", "profile view"),
    "look_back": ("回眸", "head turned back"),
    "raised": ("仰头", "head raised"),
    "lowered": ("低头", "head lowered"),
    "tilted": ("偏头", "head tilted"),
}
EXPRESSIONS = {
    "calm": ("平静", "calm expression"),
    "smile": ("轻笑", "light smile"),
    "focused": ("专注", "focused expression"),
    "tense": ("紧张", "tense expression"),
    "enduring": ("忍耐", "enduring expression"),
    "dazed": ("失神", "dazed expression"),
    "satisfied": ("满足", "satisfied expression"),
    "afterglow": ("余韵", "afterglow expression"),
}
GAZES = {
    "look_partner": ("看向对方", "looking at partner"),
    "look_viewer": ("看向镜头", "looking at viewer"),
    "look_away": ("移开视线", "averted gaze"),
    "closed_eyes": ("闭眼", "eyes closed"),
    "look_down": ("向下看", "looking down"),
    "look_up": ("向上看", "looking up"),
}
SOURCE_PARTS = {
    "hands": ("双手", "hands"),
    "mouth": ("口部", "mouth"),
    "arms": ("手臂", "arms"),
    "legs": ("腿部", "legs"),
    "pelvis": ("骨盆", "pelvis"),
}
ACTIONS = {
    "contact": ("接触", "contact"),
    "support": ("托住", "supporting"),
    "grab": ("抓住", "grabbing"),
    "pull": ("拉扯", "pulling"),
    "kiss": ("亲吻", "kissing"),
    "lick": ("舔", "licking"),
    "suck": ("吮吸", "sucking"),
    "nibble": ("轻咬", "nibbling"),
    "rub": ("抚摸", "rubbing"),
    "press": ("按压", "pressing"),
    "lift": ("抬起", "lifting"),
    "fix": ("固定", "restraining"),
    "release": ("释放", "releasing"),
}
TARGET_PARTS = {
    "head": ("头部", "head", None),
    "shoulder": ("肩部", "shoulder", None),
    "chest": ("胸部", "chest", None),
    "waist": ("腰部", "waist", None),
    "pelvis": ("骨盆", "pelvis", None),
    "hands": ("双手", "hands", None),
    "near_leg": ("近侧腿", "near leg", None),
    "far_leg": ("远侧腿", "far leg", None),
    "feet": ("双脚", "feet", None),
    "breast": ("女性胸部", "female breast", "female"),
    "nipple_jewelry": ("乳头饰品", "nipple jewelry", "female"),
    "hair": ("头发", "hair", "female"),
    "intimate_area": ("阴部区域", "intimate area", "female"),
}
PRIMARY_ACTIONS = {
    "vaginal_insertion": ("插入", "vaginal sex"),
    "anal_insertion": ("肛交插入", "anal sex"),
    "hand_play": ("手部互动", "handjob"),
    "oral_play": ("口部互动", "fellatio"),
    "toy_play": ("玩具互动", "toy stimulation"),
    "support_hold": ("抱住 / 支撑肢体", "holding partner's leg"),
}
PHASES = {
    "ready": ("准备", "about to begin"),
    "contact": ("接触", "initial contact"),
    "ongoing": ("进行中", "ongoing action"),
    "hold": ("保持", "holding position"),
    "aftercare": ("余韵", "aftercare"),
}
DIRECTION_PROFILES = {
    "male_dominant": ("男性主导 → 女性接收", "male dominant, female receiving"),
    "female_dominant": ("女性主导 → 男性接收", "female dominant, male receiving"),
    "same_sex_custom": ("同性组合主导配置", "same-sex role direction"),
}


def catalog() -> dict[str, Any]:
    return {
        "base_states": _options(BASE_STATES),
        "pelvis_states": _options(PELVIS_STATES),
        "near_leg_states": _options(NEAR_LEG_STATES),
        "far_leg_states": _options(FAR_LEG_STATES),
        "arm_states": _options(ARM_STATES),
        "head_states": _options(HEAD_STATES),
        "expressions": _options(EXPRESSIONS),
        "gazes": _options(GAZES),
        "source_parts": _options(SOURCE_PARTS),
        "actions": _options(ACTIONS),
        "target_parts": [
            {"id": key, "label": label, "tag": tag, "owner_gender": owner}
            for key, (label, tag, owner) in TARGET_PARTS.items()
        ],
        "primary_actions": _options(PRIMARY_ACTIONS),
        "phases": _options(PHASES),
        "direction_profiles": _options(DIRECTION_PROFILES),
    }


def _item(options: dict[str, tuple[str, str]], key: object) -> tuple[str, str] | None:
    return options.get(str(key or ""))


def _default_state(key: str) -> str:
    options = {
        "base": BASE_STATES,
        "pelvis": PELVIS_STATES,
        "near_leg": NEAR_LEG_STATES,
        "far_leg": FAR_LEG_STATES,
        "arms": ARM_STATES,
        "head": HEAD_STATES,
    }[key]
    return next(iter(options))


def _default_expression(key: str) -> str:
    return next(iter(EXPRESSIONS if key == "expression" else GAZES))


def compile_recipe(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    raw_roles = payload.get("roles")
    if not isinstance(raw_roles, list) or not raw_roles:
        return {"ok": False, "errors": ["至少需要一个角色"], "warnings": [], "tags": {}}
    if len(raw_roles) > 2:
        errors.append("第一版最多支持两个角色")

    roles: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_roles[:2]):
        data = raw if isinstance(raw, dict) else {}
        slot = str(data.get("slot") or ("A" if index == 0 else "B")).upper()
        gender = str(data.get("gender") or ("female" if index == 0 else "male"))
        if gender not in {"female", "male"}:
            errors.append(f"角色{slot} 性别无效")
            gender = "female"
        roles.append(
            {
                "slot": slot,
                "gender": gender,
                "base": str(data.get("base") or _default_state("base")),
                "pelvis": str(data.get("pelvis") or _default_state("pelvis")),
                "near_leg": str(data.get("near_leg") or _default_state("near_leg")),
                "far_leg": str(data.get("far_leg") or _default_state("far_leg")),
                "arms": str(data.get("arms") or _default_state("arms")),
                "head": str(data.get("head") or _default_state("head")),
                "expression": str(data.get("expression") or _default_expression("expression")),
                "gaze": str(data.get("gaze") or _default_expression("gaze")),
            }
        )

    role_by_slot = {role["slot"]: role for role in roles}
    if len(roles) == 2 and all(role["gender"] == "male" for role in roles):
        errors.append("第一版不开放男男组合")

    direction = str(payload.get("direction_profile") or "male_dominant")
    dominant = str(payload.get("dominant_role") or "B").upper()
    receiving = str(payload.get("receiving_role") or "A").upper()
    if direction not in DIRECTION_PROFILES:
        errors.append("未知的交互方向配置")
    if dominant not in role_by_slot or receiving not in role_by_slot:
        errors.append("主导角色或接收角色槽位无效")
    elif dominant == receiving:
        errors.append("主导角色和接收角色不能相同")

    if len(roles) == 2 and dominant in role_by_slot and receiving in role_by_slot:
        genders = {role["slot"]: role["gender"] for role in roles}
        if set(genders.values()) == {"female", "male"} and direction != "male_dominant":
            errors.append("第一版男女组合仅支持男性主导、女性接收")
        if set(genders.values()) == {"female"} and direction != "same_sex_custom":
            errors.append("女女组合需要使用同性主导配置")

    state_options = {
        "base": BASE_STATES,
        "pelvis": PELVIS_STATES,
        "near_leg": NEAR_LEG_STATES,
        "far_leg": FAR_LEG_STATES,
        "arms": ARM_STATES,
        "head": HEAD_STATES,
    }
    role_tags: dict[str, list[str]] = {}
    expression_tags: dict[str, list[str]] = {}
    for role in roles:
        tags: list[str] = []
        for field, options in state_options.items():
            selected = _item(options, role[field])
            if not selected:
                errors.append(f"角色{role['slot']} 的{field}选项无效")
                continue
            tags.append(selected[1])
        expression_tags[role["slot"]] = []
        if role["gender"] == "female":
            expression = _item(EXPRESSIONS, role["expression"])
            gaze = _item(GAZES, role["gaze"])
            if not expression:
                errors.append(f"角色{role['slot']} 表情无效")
            if not gaze:
                errors.append(f"角色{role['slot']} 视线无效")
            if expression:
                expression_tags[role["slot"]].append(expression[1])
            if gaze:
                expression_tags[role["slot"]].append(gaze[1])
            if role["gaze"] == "closed_eyes" and role["head"] == "facing":
                warnings.append(f"角色{role['slot']} 同时闭眼并面向对方，请确认视线表现")
        role_tags[role["slot"]] = list(dict.fromkeys(tags))

    interactions = payload.get("interactions")
    if not isinstance(interactions, list):
        interactions = []
    if len(interactions) > 4:
        errors.append("动作交互最多 4 行")
    action_tags: list[str] = []
    contact_tags: list[str] = []
    seen_rows: set[tuple[str, ...]] = set()
    for index, raw in enumerate(interactions[:4]):
        data = raw if isinstance(raw, dict) else {}
        source_role = str(data.get("source_role") or "").upper()
        target_role = str(data.get("target_role") or "").upper()
        source_part = str(data.get("source_part") or "")
        action_id = str(data.get("action") or "")
        target_part = str(data.get("target_part") or "")
        if source_role not in role_by_slot or target_role not in role_by_slot:
            errors.append(f"动作行 {index + 1} 的角色槽位无效")
            continue
        source = _item(SOURCE_PARTS, source_part)
        action = _item(ACTIONS, action_id)
        target = TARGET_PARTS.get(target_part)
        if not source:
            errors.append(f"动作行 {index + 1} 的来源部位无效")
            continue
        if not action:
            errors.append(f"动作行 {index + 1} 的动作无效")
            continue
        if not target:
            errors.append(f"动作行 {index + 1} 的目标部位无效")
            continue
        target_gender = role_by_slot[target_role]["gender"]
        owner_gender = target[2]
        if owner_gender and target_gender != owner_gender:
            errors.append(f"动作行 {index + 1} 的目标部位不适用于角色{target_role}")
            continue
        row_key = (source_role, source_part, action_id, target_role, target_part)
        if row_key in seen_rows:
            warnings.append(f"动作行 {index + 1} 与前面的交互重复")
        seen_rows.add(row_key)
        action_tags.append(action[1])
        contact_tags.append(f"{action[1]} role {target_role} {target[1]}")

    primary = _item(PRIMARY_ACTIONS, payload.get("primary_action") or "vaginal_insertion")
    phase = _item(PHASES, payload.get("phase") or "ongoing")
    if not primary:
        errors.append("主动作无效")
    if not phase:
        errors.append("动作阶段无效")

    direction_tag = DIRECTION_PROFILES.get(direction, DIRECTION_PROFILES["male_dominant"])[1]
    interaction_tags = {
        "action_tags": list(dict.fromkeys(action_tags + ([primary[1]] if primary else []))),
        "contact_tags": list(dict.fromkeys(contact_tags)),
        "relationship_tags": [direction_tag],
        "composition_constraints": [
            "exactly 2 separate adult anime characters" if len(roles) == 2 else "exactly 1 adult anime character"
        ],
    }
    all_tags = list(
        dict.fromkeys(
            [tag for slot_tags in role_tags.values() for tag in slot_tags]
            + interaction_tags["action_tags"]
            + interaction_tags["contact_tags"]
            + interaction_tags["relationship_tags"]
            + interaction_tags["composition_constraints"]
            + ([phase[1]] if phase else [])
        )
    )
    return {
        "ok": not errors,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "direction_profile": direction,
        "dominant_role": dominant,
        "receiving_role": receiving,
        "role_tags": role_tags,
        "expression_tags": expression_tags,
        "interaction_tags": interaction_tags,
        "preview_tags": all_tags,
    }
