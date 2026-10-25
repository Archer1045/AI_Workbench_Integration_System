"""Built-in adult fictional expansion-state presets."""
from __future__ import annotations

CATEGORIES = ("阴道扩张", "肛门扩张")
STATES = ("仅展示", "填充液体", "填充固体", "玩弄")
RATINGS = ("R18",)
INTENSITIES = ("标准", "强化", "极限")

_FLUID_VISUAL = {
    "id": "clear_fluid_visual",
    "label": "澄澈流体",
    "appearance_reference": "清水",
    "visual_prompt": "clear translucent fluid-like material, smooth wet surface, slow flowing visual",
}
_SOLID_VISUAL = {
    "id": "cold_crystal_visual",
    "label": "冷晶块",
    "appearance_reference": "冰块",
    "visual_prompt": "transparent crystalline block-like visual material, frosted edges, static shape",
}


def _expansion(
    preset_id: str,
    target: str,
    state: str,
    label: str,
    translation: str,
    tags: list[str],
    *,
    intensity: str,
    draw_prompt: str,
    visual_material: dict | None = None,
    compatibility: list[str] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "id": preset_id,
        "category": target,
        "state": state,
        "label": label,
        "translation": translation,
        "tags": tags,
        "rating": "R18",
        "intensity": intensity,
        "source": "builtin",
        "visual_only": True,
        "execution_allowed": False,
        "visual_material": visual_material,
        "compatibility": compatibility or [],
        "conflicts": [],
        "draw_prompt": draw_prompt,
        "has_image": False,
        "image": None,
    }


EXPANSION_PRESETS = [
    _expansion(
        "expansion_vaginal_display",
        "阴道扩张",
        "仅展示",
        "阴道扩张展示",
        "成年女性阴道扩张状态的外部展示与艺术化内部轮廓",
        ["vaginal dilation", "display state", "fictional internal outline", "visual only"],
        intensity="强化",
        draw_prompt="an adult woman in a visual vaginal-dilation display state, with an artistic cutaway outline and no real-world material or procedural detail",
    ),
    _expansion(
        "expansion_vaginal_liquid_fill",
        "阴道扩张",
        "填充液体",
        "阴道扩张液体填充",
        "阴道扩张状态下呈现澄澈流体的虚构填充视觉",
        ["vaginal dilation", "clear fluid visual", "internal fill visual", "fictional"],
        intensity="极限",
        visual_material=_FLUID_VISUAL,
        draw_prompt="an adult woman in a fictional vaginal-dilation state with a clear fluid-like internal visual and artistic cutaway, no real substance or operational detail",
    ),
    _expansion(
        "expansion_vaginal_solid_fill",
        "阴道扩张",
        "填充固体",
        "阴道扩张固体填充",
        "阴道扩张状态下呈现冷晶块状材质的虚构填充视觉",
        ["vaginal dilation", "crystal block visual", "internal fill visual", "fictional"],
        intensity="极限",
        visual_material=_SOLID_VISUAL,
        draw_prompt="an adult woman in a fictional vaginal-dilation state with a transparent crystalline block-like internal visual and artistic cutaway, no real object",
    ),
    _expansion(
        "expansion_vaginal_play",
        "阴道扩张",
        "玩弄",
        "阴道扩张玩弄",
        "在扩张状态下进行视觉化的内部接触或视觉工具玩弄",
        ["vaginal dilation", "play state", "visual contact tool", "fictional internal view"],
        intensity="极限",
        compatibility=["toy_graduated_dilator_set", "toy_open_visual_expander", "toy_blunt_contact_visual"],
        draw_prompt="an adult woman in a fictional vaginal-dilation play state with an abstract visual contact tool and cutaway structure, no procedural instructions",
    ),
    _expansion(
        "expansion_anal_display",
        "肛门扩张",
        "仅展示",
        "肛门扩张展示",
        "成年女性肛门扩张状态的外部展示与艺术化内部轮廓",
        ["anal dilation", "display state", "fictional internal outline", "visual only"],
        intensity="强化",
        draw_prompt="an adult woman in a visual anal-dilation display state, with an artistic cutaway outline and no real-world material or procedural detail",
    ),
    _expansion(
        "expansion_anal_liquid_fill",
        "肛门扩张",
        "填充液体",
        "肛门扩张液体填充",
        "肛门扩张状态下呈现澄澈流体的虚构填充视觉",
        ["anal dilation", "clear fluid visual", "internal fill visual", "fictional"],
        intensity="极限",
        visual_material=_FLUID_VISUAL,
        draw_prompt="an adult woman in a fictional anal-dilation state with a clear fluid-like internal visual and artistic cutaway, no real substance or operational detail",
    ),
    _expansion(
        "expansion_anal_solid_fill",
        "肛门扩张",
        "填充固体",
        "肛门扩张固体填充",
        "肛门扩张状态下呈现冷晶块状材质的虚构填充视觉",
        ["anal dilation", "crystal block visual", "internal fill visual", "fictional"],
        intensity="极限",
        visual_material=_SOLID_VISUAL,
        draw_prompt="an adult woman in a fictional anal-dilation state with a transparent crystalline block-like internal visual and artistic cutaway, no real object",
    ),
    _expansion(
        "expansion_anal_play",
        "肛门扩张",
        "玩弄",
        "肛门扩张玩弄",
        "在扩张状态下进行视觉化的内部接触或视觉工具玩弄",
        ["anal dilation", "play state", "visual contact tool", "fictional internal view"],
        intensity="极限",
        compatibility=["toy_graduated_dilator_set", "toy_open_visual_expander", "toy_blunt_contact_visual"],
        draw_prompt="an adult woman in a fictional anal-dilation play state with an abstract visual contact tool and cutaway structure, no procedural instructions",
    ),
]
