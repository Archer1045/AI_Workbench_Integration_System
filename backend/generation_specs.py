"""Canonical model families and legal image-generation dimensions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any


class GenerationSpecError(ValueError):
    """Raised when a model cannot be used by the implemented workflow."""


@dataclass(frozen=True)
class GenerationProfile:
    id: str
    label: str
    latent_node: str
    channels: int
    height_divisor: int
    width_divisor: int
    resolution_step: int
    min_size: int
    max_size: int
    batch_max: int
    downscale_ratio: int
    workflow_supported: bool
    workflow_support_reason: str = ""


PROFILES: dict[str, GenerationProfile] = {
    "anima": GenerationProfile(
        id="anima",
        label="Anima",
        latent_node="EmptyLatentImage",
        channels=16,
        height_divisor=8,
        width_divisor=8,
        resolution_step=8,
        min_size=256,
        max_size=4096,
        batch_max=4096,
        downscale_ratio=8,
        workflow_supported=True,
    ),
    "flux2": GenerationProfile(
        id="flux2",
        label="FLUX.2 / FLUX.3",
        latent_node="EmptyFlux2LatentImage",
        channels=128,
        height_divisor=16,
        width_divisor=16,
        resolution_step=16,
        min_size=256,
        max_size=4096,
        batch_max=4096,
        downscale_ratio=16,
        workflow_supported=False,
        workflow_support_reason="尚未接入 FLUX 专用加载与空 latent 工作流",
    ),
    "qwen_image": GenerationProfile(
        id="qwen_image",
        label="Qwen Image",
        latent_node="EmptyLatentImage",
        channels=16,
        height_divisor=8,
        width_divisor=8,
        resolution_step=32,
        min_size=256,
        max_size=4096,
        batch_max=4096,
        downscale_ratio=8,
        workflow_supported=False,
        workflow_support_reason="尚未接入 Qwen Image 专用加载与采样工作流",
    ),
    "sdxl": GenerationProfile(
        id="sdxl",
        label="SDXL / Illustrious / Pony",
        latent_node="EmptyLatentImage",
        channels=4,
        height_divisor=8,
        width_divisor=8,
        resolution_step=8,
        min_size=256,
        max_size=4096,
        batch_max=4096,
        downscale_ratio=8,
        workflow_supported=False,
        workflow_support_reason="当前工作台尚未对 SDXL 系列建立独立参数模板",
    ),
    "sd3": GenerationProfile(
        id="sd3",
        label="Stable Diffusion 3",
        latent_node="EmptySD3LatentImage",
        channels=16,
        height_divisor=8,
        width_divisor=8,
        resolution_step=16,
        min_size=256,
        max_size=4096,
        batch_max=4096,
        downscale_ratio=8,
        workflow_supported=False,
        workflow_support_reason="尚未接入 SD3 专用文本编码器和空 latent 工作流",
    ),
    "hunyuan": GenerationProfile(
        id="hunyuan",
        label="Hunyuan Image",
        latent_node="EmptyHunyuanImageLatent",
        channels=64,
        height_divisor=32,
        width_divisor=32,
        resolution_step=32,
        min_size=64,
        max_size=4096,
        batch_max=4096,
        downscale_ratio=32,
        workflow_supported=False,
        workflow_support_reason="尚未接入 Hunyuan Image 专用加载与采样工作流",
    ),
    "krea2": GenerationProfile(
        id="krea2",
        label="Krea 2",
        latent_node="EmptyLatentImage",
        channels=16,
        height_divisor=8,
        width_divisor=8,
        resolution_step=16,
        min_size=256,
        max_size=4096,
        batch_max=4096,
        downscale_ratio=8,
        workflow_supported=False,
        workflow_support_reason="尚未接入 Krea 2 专用工作流",
    ),
    "z_image": GenerationProfile(
        id="z_image",
        label="Z-Image",
        latent_node="EmptyLatentImage",
        channels=16,
        height_divisor=8,
        width_divisor=8,
        resolution_step=16,
        min_size=256,
        max_size=4096,
        batch_max=4096,
        downscale_ratio=8,
        workflow_supported=False,
        workflow_support_reason="尚未接入 Z-Image 专用工作流",
    ),
    "boogu": GenerationProfile(
        id="boogu",
        label="Boogu",
        latent_node="EmptyLatentImage",
        channels=16,
        height_divisor=8,
        width_divisor=8,
        resolution_step=8,
        min_size=256,
        max_size=4096,
        batch_max=4096,
        downscale_ratio=8,
        workflow_supported=False,
        workflow_support_reason="尚未接入 Boogu 专用工作流",
    ),
    "unknown": GenerationProfile(
        id="unknown",
        label="未识别模型",
        latent_node="EmptyLatentImage",
        channels=16,
        height_divisor=8,
        width_divisor=8,
        resolution_step=8,
        min_size=256,
        max_size=4096,
        batch_max=4096,
        downscale_ratio=8,
        workflow_supported=False,
        workflow_support_reason="无法识别模型家族，请先补充生成规格",
    ),
}

_MODEL_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("flux2", ("flux2", "flux.2", "flux3", "flux.3")),
    ("qwen_image", ("qwen_image", "qwen-image", "qwenimage")),
    ("hunyuan", ("hunyuan",)),
    ("sdxl", ("sdxl", "illustrious", "noobai", "pony")),
    ("sd3", ("sd3", "stable_diffusion_3", "stable-diffusion-3")),
    ("krea2", ("krea2", "krea_2", "krea-2")),
    ("z_image", ("z_image", "z-image", "zimage")),
    ("boogu", ("boogu",)),
    ("anima", ("anima",)),
)

ASPECT_RATIOS: tuple[dict[str, Any], ...] = (
    {"id": "1:1", "label": "1:1 方形", "ratio": 1.0, "width": 1024, "height": 1024},
    {"id": "4:3", "label": "4:3 横向", "ratio": 4 / 3, "width": 1440, "height": 1080},
    {"id": "3:4", "label": "3:4 竖向", "ratio": 3 / 4, "width": 1080, "height": 1440},
    {"id": "16:9", "label": "16:9 宽屏", "ratio": 16 / 9, "width": 1920, "height": 1080},
    {"id": "9:16", "label": "9:16 竖屏", "ratio": 9 / 16, "width": 1080, "height": 1920},
    {"id": "21:9", "label": "21:9 超宽", "ratio": 21 / 9, "width": 2520, "height": 1080},
    {"id": "2:3", "label": "2:3 海报", "ratio": 2 / 3, "width": 1080, "height": 1620},
    {"id": "3:2", "label": "3:2 横向", "ratio": 3 / 2, "width": 1620, "height": 1080},
)


def resolve_profile(model_name: str | None) -> GenerationProfile:
    normalized = str(model_name or "").strip().casefold().replace("\\", "/")
    for profile_id, markers in _MODEL_MARKERS:
        if any(marker in normalized for marker in markers):
            return PROFILES[profile_id]
    return PROFILES["unknown"]


def normalize_dimension(
    value: int | float,
    profile: GenerationProfile,
    *,
    min_size: int | None = None,
    max_size: int | None = None,
) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(profile.resolution_step)
    if not math.isfinite(numeric):
        numeric = float(profile.resolution_step)
    lower = max(int(min_size or profile.min_size), profile.min_size)
    upper = min(int(max_size or profile.max_size), profile.max_size)
    step = profile.resolution_step
    snapped = int(math.floor(numeric / step + 0.5)) * step
    return max(lower, min(upper, snapped))


def normalize_size(
    model_name: str | None,
    width: int | float,
    height: int | float,
    aspect_ratio: str = "",
    *,
    min_size: int | None = None,
    max_size: int | None = None,
    min_width: int | None = None,
    max_width: int | None = None,
    min_height: int | None = None,
    max_height: int | None = None,
) -> tuple[int, int, GenerationProfile]:
    profile = resolve_profile(model_name)
    lower_width = min_width if min_width is not None else min_size
    upper_width = max_width if max_width is not None else max_size
    lower_height = min_height if min_height is not None else min_size
    upper_height = max_height if max_height is not None else max_size
    normalized_width = normalize_dimension(
        width, profile, min_size=lower_width, max_size=upper_width
    )
    normalized_height = normalize_dimension(
        height, profile, min_size=lower_height, max_size=upper_height
    )
    ratio_def = next(
        (item for item in ASPECT_RATIOS if item["id"] == str(aspect_ratio or "")),
        None,
    )
    if ratio_def is None:
        return normalized_width, normalized_height, profile
    ratio = float(ratio_def["ratio"])
    if ratio == 1.0:
        side = max(normalized_width, normalized_height)
        return (
            normalize_dimension(
                side, profile, min_size=lower_width, max_size=upper_width
            ),
            normalize_dimension(
                side, profile, min_size=lower_height, max_size=upper_height
            ),
            profile,
        )
    if ratio > 1:
        base = max(normalized_width, normalized_height)
        normalized_width = normalize_dimension(
            base, profile, min_size=lower_width, max_size=upper_width
        )
        normalized_height = normalize_dimension(
            normalized_width / ratio,
            profile,
            min_size=lower_height,
            max_size=upper_height,
        )
    else:
        base = max(normalized_width, normalized_height)
        normalized_height = normalize_dimension(
            base, profile, min_size=lower_height, max_size=upper_height
        )
        normalized_width = normalize_dimension(
            normalized_height * ratio,
            profile,
            min_size=lower_width,
            max_size=upper_width,
        )
    return normalized_width, normalized_height, profile


def canvas_presets(
    profile: GenerationProfile,
    *,
    min_size: int | None = None,
    max_size: int | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for item in ASPECT_RATIOS:
        width, height, _ = normalize_size(
            profile.id,
            int(item["width"]),
            int(item["height"]),
            str(item["id"]),
            min_size=min_size,
            max_size=max_size,
        )
        key = (width, height)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "id": item["id"],
                "label": item["label"],
                "width": width,
                "height": height,
            }
        )
    if not result:
        side = normalize_dimension(1024, profile, min_size=min_size, max_size=max_size)
        result.append({"id": "1:1", "label": "1:1 方形", "width": side, "height": side})
    return result


def describe_profile(
    profile: GenerationProfile,
    *,
    min_size: int | None = None,
    max_size: int | None = None,
) -> dict[str, Any]:
    result = asdict(profile)
    result["canvas_presets"] = canvas_presets(
        profile, min_size=min_size, max_size=max_size
    )
    return result


def describe_model(
    model_name: str,
    *,
    min_size: int | None = None,
    max_size: int | None = None,
) -> dict[str, Any]:
    profile = resolve_profile(model_name)
    return {
        "generation_profile": profile.id,
        "generation_profile_label": profile.label,
        "workflow_supported": profile.workflow_supported,
        "workflow_support_reason": profile.workflow_support_reason,
        "spec": describe_profile(profile, min_size=min_size, max_size=max_size),
    }


def require_workflow_supported(model_name: str | None) -> GenerationProfile:
    profile = resolve_profile(model_name)
    if not profile.workflow_supported:
        model = str(model_name or "未选择模型")
        reason = profile.workflow_support_reason or "模型工作流尚未实现"
        raise GenerationSpecError(f"{model}：{reason}")
    return profile
