"""Target-model prompt rules kept separate to avoid cross-model instruction drift."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PromptProfile:
    id: str
    label: str
    description: str
    instruction: str


PROFILES: dict[str, PromptProfile] = {
    "general": PromptProfile(
        id="general",
        label="通用绘图",
        description="适合当前 Anima 等标签式出图工作流。",
        instruction=(
            "目标工作流使用英文 Danbooru 风格提示词。保留用户要求与已有角色身份，"
            "只输出可直接用于出图的最终提示词和分组 JSON。"
        ),
    ),
    "qwen_image_edit": PromptProfile(
        id="qwen_image_edit",
        label="Qwen Image Edit",
        description="偏向精确图像编辑，明确保留区域与最终画面。",
        instruction=(
            "目标模型是 Qwen Image Edit。只描述本次需要的修改和最终画面，明确受保护主体"
            "应保持不变；不得输出对比式语句，如“原来/改成/替换为”。输出应具体、自然且"
            "可以直接用于图像编辑。"
        ),
    ),
    "flux2_edit": PromptProfile(
        id="flux2_edit",
        label="FLUX.2 图像编辑",
        description="使用更简洁的编辑指令，避免重复强调无关对象。",
        instruction=(
            "目标模型是 FLUX.2 图像编辑。只描述需要变化的区域和最终可见结果，"
            "避免复述与修改无关的现有元素，避免权重语法和解释性文字。"
        ),
    ),
    "storyboard": PromptProfile(
        id="storyboard",
        label="影视分镜",
        description="按独立镜头输出视觉上可拍摄的具体信息。",
        instruction=(
            "目标用途是影视分镜。每个镜头必须独立、自洽，明确主体动作、环境、景别、"
            "镜头角度、光线和空间层次；只写摄影机可拍到的物理视觉信息，不写抽象情绪总结，"
            "不引用前后镜头。"
        ),
    ),
}

DEFAULT_PROFILE_ID = "general"


def resolve_prompt_profile(profile_id: str | None) -> PromptProfile:
    key = str(profile_id or "").strip()
    return PROFILES.get(key, PROFILES[DEFAULT_PROFILE_ID])


def list_prompt_profiles() -> list[dict[str, str]]:
    return [asdict(profile) for profile in PROFILES.values()]


def get_prompt_profile(profile_id: str | None) -> dict[str, str]:
    return asdict(resolve_prompt_profile(profile_id))
