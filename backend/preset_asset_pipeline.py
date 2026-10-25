"""Preset thumbnail workshop generation queue and prompt snapshots."""
from __future__ import annotations

import base64
import hashlib
import json
import random
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import comfy_worker
import config
import content_filter
import database
import preset_asset_service as asset_service
import requests
import task_registry
import task_resources
from PIL import Image, ImageDraw, ImageFilter

JOB_KIND = "preset_asset"
JOB_REQUEST_VERSION = 1
ACTIVE_AI_STATUSES = {"queued", "preparing", "running", "cancel_requested"}
PENDING_ITEM_STATUSES = {"queued", "preparing"}
RETRYABLE_FAILURE_CODES = {
    "generation_timeout",
    "generation_service_unavailable",
    "gpu_busy",
}
RECOVERABLE_ITEM_STATUSES = {"failed", "interrupted", "cancelled"}
FAILURE_RETRY_CONTRACT: dict[str, tuple[bool, str]] = {
    "generation_timeout": (True, "wait_and_retry"),
    "generation_service_unavailable": (True, "start_service"),
    "gpu_busy": (True, "free_gpu"),
    "generation_failed": (True, "retry"),
    "invalid_parameters": (False, "fix_parameters"),
    "invalid_preset": (False, "review_preset"),
    "cancelled": (True, "retry"),
}
RETRY_BACKOFF_BASE_SECONDS = 30
RETRY_BACKOFF_MAX_SECONDS = 3600
IDEMPOTENCY_KEY_MAX_LENGTH = 200
RESTART_INTERRUPTED_REASON = "后端重启中断，运行中的生成不会自动重提"

_GPU_CONDITION = threading.Condition()
_AI_ACTIVE = False
_CPU_SEMAPHORE = threading.BoundedSemaphore(max(1, config.PRESET_ASSET_CPU_CONCURRENCY))
_JOB_THREADS: dict[str, threading.Thread] = {}
_JOB_THREADS_LOCK = threading.RLock()

_COMMON_NEGATIVE = (
    "text, watermark, logo, signature, frame, border, collage, multiple panels, "
    "duplicate subject, cropped, low quality, worst quality, blurry"
)

_POSE_NUDE_POSITIVE = "completely nude, full nudity, bare skin, no clothing"
_POSE_NUDE_NEGATIVE = (
    "clothing, clothes, outfit, underwear, lingerie, partially dressed"
)
_POSE_EXPLICIT_CLOTHING_MARKERS = (
    "open shirt",
    "half undressed",
    "removing stockings",
    "unclasping bra",
    "one hand under skirt",
    "skirt lift",
    "dress shoulder slip",
    "front clasp bra",
    "open bra",
    "panties aside",
    "latex outfit",
    "zipper partially open",
    "fully clothed",
    "soft robe open",
)
_POSE_GENERIC_CLOTHING_REPLACEMENTS = (
    ("opaque natural skin and clothing", "opaque natural skin"),
    ("distinct outfits and faces", "distinct character designs and faces"),
    ("distinct everyday outfits", "distinct character designs"),
    ("distinct clothing for each person", "distinct character designs"),
    ("distinct outfits", "distinct character designs"),
)
_POSE_GENERIC_CLOTHING_REMOVALS = (
    "both wear simple fitted clothing",
    "both wear simple loungewear",
    "simple fitted loungewear",
    "simple sleeveless loungewear",
    "soft loungewear around the shoulders",
    "simple everyday clothing",
    "simple fitted clothing",
    "simple loose clothing",
    "comfortable loungewear",
    "loose camisole lowered at the back",
    "wearing a loose nursing camisole",
    "wearing a loose camisole",
    "simple loungewear",
    "loose loungewear",
    "soft open loungewear",
    "soft loungewear",
    "loose camisole",
)

_FULL_BODY_FRAMING_POSITIVE = (
    "zoomed out full-body shot, wide balanced framing, entire person inside frame, "
    "complete head and both feet visible, generous headroom above the head, "
    "clear space below the feet"
)
_FULL_BODY_FRAMING_NEGATIVE = (
    "close-up framing, portrait crop, upper-body crop, waist-up shot, "
    "cropped legs, feet out of frame"
)
_VISIBLE_FACE_POSITIVE = (
    "face fully inside frame, both eyes and facial features visible and unobstructed"
)
_VISIBLE_FACE_NEGATIVE = (
    "cropped head, top of head cut off, head out of frame, face out of frame, "
    "eyes out of frame, obscured face, covered eyes, headless, faceless"
)
_FRONT_LIGHT_POSITIVE = (
    "soft even frontal fill lighting, face and front of the subject "
    "evenly illuminated and clearly visible"
)
_FRONT_LIGHT_NEGATIVE = (
    "shadow on face, shadow on chest, shadow across body, side shadow, "
    "backlit silhouette, underexposed front, harsh shadow across subject"
)
_SINGLE_PERSON_POSITIVE = (
    "exactly one adult anime woman, solo, completely alone, no other person"
)
_SINGLE_PERSON_NEGATIVE = (
    "1boy, male, man, 2girls, 2boys, multiple girls, multiple boys, couple, second person, "
    "extra person, additional character, duplicate subject"
)
_UPPER_BODY_FRAMING_POSITIVE = (
    "upper-body clothing presentation, complete head and face visible, "
    "shoulders and chest fully inside frame, complete featured upper garment visible"
)
_UPPER_BODY_FRAMING_NEGATIVE = (
    "chest close-up only, collar-only crop, cropped shoulders, cropped featured garment"
)
_PARTIAL_BODY_FRAMING_POSITIVE = (
    "partial-body clothing presentation with complete head and face visible, "
    "framed low enough to show the complete featured garment, feet may be outside "
    "frame only when they are not part of the featured item"
)
_PARTIAL_BODY_FRAMING_NEGATIVE = (
    "featured garment cropped, underwear out of frame, swim bottoms out of frame, "
    "sleepwear hem out of frame, extreme close-up, chest-only crop"
)
_LEG_FOCUS_POSITIVE = (
    f"{_FULL_BODY_FRAMING_POSITIVE}, both legs and feet visible, "
    "complete legwear silhouette visible"
)
_LEG_FOCUS_NEGATIVE = (
    f"{_FULL_BODY_FRAMING_NEGATIVE}, cropped legs, cropped knees, cropped ankles, "
    "feet out of frame"
)
_FRONT_FACING_POSITIVE = (
    "primary front view, face and front of the character visible to the viewer"
)
_FRONT_FACING_NEGATIVE = (
    "back-facing only, rear-only view, face turned away from viewer"
)
_FRONT_BACK_VIEW_POSITIVE = (
    "coordinated front and back clothing reference views of the same single "
    "adult woman, identity and outfit consistent between views, front view "
    "shows the face, back view clearly shows the required back detail"
)
_FRONT_BACK_VIEW_NEGATIVE = (
    "different women in the two views, inconsistent identity, different outfit "
    "between views, front view missing face"
)
_ACTION_FLEX_POSITIVE = (
    "pose and action may vary freely, natural coherent posture, anatomically "
    "consistent body and visually balanced composition"
)
_ACTION_FLEX_NEGATIVE = (
    "awkward pose, broken anatomy, disconnected limbs, incoherent composition"
)
_TOY_CHARACTER_CONTEXT_POSITIVE = (
    "featured visual toy presented with exactly one adult woman, the character "
    "holding or positioning the featured toy beside her body, toy fully visible "
    "and unobstructed, readable toy silhouette and material, character and toy "
    "clearly connected in one private interior scene"
)
_TOY_CHARACTER_CONTEXT_NEGATIVE = (
    "isolated product shot only, toy-only image, disembodied object, no person, "
    "multiple different toys, duplicate toy, toy obscured by hands, cropped toy, "
    "cluttered background, extra people"
)
_EXPANSION_INTERNAL_FACE_POSITIVE = (
    "face fully inside frame, both eyes visible and unobstructed, face turned "
    "toward the viewer"
)
_EXPANSION_SINGLE_SUBJECT_POSITIVE = (
    "same single adult woman, one consistent identity, no additional people"
)
_EXPANSION_SINGLE_SUBJECT_NEGATIVE = (
    "two different women, two different identities, duplicate character, "
    "extra person, extra people"
)
_EXPANSION_TRANSPARENT_STYLE_POSITIVE = (
    "styled transparent internal visualization, layered anatomical illustration "
    "integrated into the character composition, limited only to the applicable "
    "uterus, vaginal canal, anal opening, or anal canal, readable internal cavity, "
    "clean anime rendering, no labels or text annotations"
)
_EXPANSION_SIMPLE_STYLE_POSITIVE = (
    "subtle visible expansion silhouette in the central pelvic area, normal "
    "opaque skin, opaque arms, legs, abdomen, and torso, clean anime rendering, "
    "no detailed anatomy, no see-through body"
)
_EXPANSION_INTERNAL_NEGATIVE = (
    "medical labels, clinical chart, text annotations, surgical instrument, "
    "real-world procedure, real material recommendation, clinical photograph, "
    "ovaries, fallopian tubes, bladder, intestines, colon, pelvic bones, skeleton, "
    "unrelated internal organs, extra anatomy, "
    "transparent arms, transparent legs, transparent torso, translucent body, "
    "transparent skin, see-through skin, x-ray body, "
    "face out of frame, eyes hidden, target region cropped, featureless inner "
    "walls, fluid obscuring internal structure, extra people, awkward pose"
)
_EXPANSION_CUTAWAY_FRAGMENTS = (
    "artistic cutaway outline",
    "artistic cutaway",
    "cutaway structure",
    "fictional internal outline",
)
_EXPANSION_DUAL_REGION_POSITIVE = (
    "two coordinated regions in one vertical image, upper region showing the "
    "same single adult woman's face and upper body, lower region showing a large "
    "transparent internal visualization limited to the applicable uterus, vaginal "
    "canal, anal opening, or anal canal, with readable cavity, folds, cervix when "
    "applicable, and fluid"
)
_EXPANSION_STATE_POSITIVE = {
    "仅展示": "visible expansion state only",
    "填充液体": "subtle fluid-state color variation",
    "填充固体": "subtle crystalline color variation",
    "玩弄": "simple abstract contact prop",
}
_EXPANSION_THUMBNAIL_PROFILES: dict[str, dict[str, str]] = {
    "阴道扩张": {
        "pose": (
            "fixed supine open pose, upper body slightly raised, knees raised and "
            "apart, pelvis angled toward the viewer, low front camera angle"
        ),
        "view": (
            "simple visible vaginal expansion state centered in the pelvic area, "
            "soft surface shading, subtle opening and shallow depth, no detailed "
            "internal anatomy"
        ),
        "required_detail_negative": "",
    },
    "肛门扩张": {
        "pose": (
            "fixed side-lying raised-hip pose, torso turned enough to keep the "
            "face toward the viewer, hip lifted toward the camera"
        ),
        "view": (
            "simple visible anal expansion state centered in the pelvic area, "
            "soft surface shading, subtle opening and shallow depth, no detailed "
            "internal anatomy"
        ),
        "required_detail_negative": "",
    },
}
_EXPANSION_PELVIS_MASK_POLYGONS: dict[str, tuple[tuple[float, float], ...]] = {
    "阴道扩张": (
        (0.30, 0.48),
        (0.70, 0.48),
        (0.75, 0.60),
        (0.67, 0.76),
        (0.58, 0.84),
        (0.42, 0.84),
        (0.33, 0.76),
        (0.25, 0.60),
    ),
    "肛门扩张": (
        (0.30, 0.50),
        (0.70, 0.50),
        (0.76, 0.63),
        (0.69, 0.80),
        (0.58, 0.86),
        (0.42, 0.86),
        (0.31, 0.80),
        (0.24, 0.63),
    ),
}
_EXPANSION_MINIMAL_STYLE_POSITIVE = (
    "uncensored, anime illustration, 2d anime style, cel shading"
)
_EXPANSION_MINIMAL_STYLE_NEGATIVE = (
    "photorealistic, realistic photo, 3d render, live-action, photographic skin, "
    "censor bar, black bar, white bar, horizontal censorship bar, censorship, "
    "mosaic censorship, bar censor, frame, border"
)
_EXPANSION_LIQUID_NEGATIVE = (
    "fluid from elsewhere, fluid flowing upward, impossible flow direction, fluid "
    "passing through body, whole body wet gloss, circular lens frame, geometric border, "
    "separate container, cup, bottle, vessel, pipe, transparent cutaway, internal "
    "cavity view, enlarged internal anatomy, cross-section"
)
_EXPANSION_SOLID_NEGATIVE = (
    "empty opening, missing insert, insert hidden inside body, insert too small, "
    "insertion action, hand holding insert, tool, medical instrument, procedure, "
    "object merged into body, material covering body, liquid fill, dripping, melting, "
    "flowing, soft gel, deformation, fragmentation, separate container, cup, bottle, "
    "vessel, pipe, transparent cutaway, internal cavity view, enlarged internal "
    "anatomy, cross-section"
)

_MULTI_SUBJECT_RE = re.compile(
    r"\b(?:exactly\s+[2-9]\d*|two adults?|two (?:women|men|characters?)|"
    r"[2-9]\s*(?:girls?|boys?|women|men|characters?)|multiple\s+"
    r"(?:girls?|boys?|women|men|characters?|people)|couple|partners?|"
    r"threesome|group sex|orgy|gangbang)\b",
    re.IGNORECASE,
)
_LOWER_BODY_FOCUS_MARKERS = (
    "stocking",
    "thighhigh",
    "thigh-high",
    "pantyhose",
    "bodystocking",
    "garter",
    "legwear",
    "leg ring",
    "knee-high",
    "sock",
    "shoe",
    "boot",
    "barefoot",
    "footjob",
    "ankle",
    "trouser",
    "pants",
    "long skirt",
    "floor-length",
    "长裙",
    "长裤",
    "裤装",
    "丝袜",
    "连裤袜",
    "连身袜",
    "吊袜",
    "腿环",
    "鞋",
    "靴",
    "脚部",
)
_UPPER_BODY_MARKERS = (
    "blouse",
    "shirt",
    "t-shirt",
    "tshirt",
    "corset",
    "bustier",
    "bralette",
    "bra ",
    "bra,",
    "bikini top",
    "halter",
    "tank top",
    "camisole",
    "crop top",
    "jacket",
    "coat",
    "胸衣",
    "文胸",
    "束腰",
    "上衣",
    "比基尼上装",
)
_BACK_FOCUS_MARKERS = (
    "backless",
    "open back",
    "low back",
    "back bow",
    "back lace",
    "back zipper",
    "back panel",
    "back detail",
    "back design",
    "spine",
    "rear",
    "露背",
    "开背",
    "低背",
    "背链",
    "背饰",
    "背部",
    "后腰",
    "后拉链",
)
_CLOTHING_SCENE_MAP: dict[str, tuple[str, ...]] = {
    "泳装/运动": (
        "sunlit sandy beach with ocean water",
        "clean outdoor swimming pool",
        "private indoor pool with clear water",
        "shallow water at a quiet beach",
    ),
    "居家日常": (
        "warm home living room",
        "quiet bedroom interior",
        "clean residential bathroom",
    ),
    "内衣/睡衣": (
        "private bedroom interior",
        "softly lit home bathroom",
        "boutique hotel bedroom",
    ),
    "情趣内衣": (
        "private boutique hotel room",
        "softly lit bedroom interior",
        "private bathroom with a bathtub",
    ),
    "礼服/正式": (
        "elegant banquet hall",
        "grand ballroom interior",
        "luxury hotel event corridor",
    ),
    "校服/制服": (
        "school classroom interior",
        "quiet school corridor",
        "school club room",
    ),
    "职业装": (
        "modern office interior",
        "professional studio workplace",
    ),
    "民族/主题": (
        "themed courtyard with matching architecture",
        "ornate themed hall",
    ),
    "乳胶/皮革": (
        "private modern lounge",
        "clean photographic studio",
    ),
    "SM/束缚": (
        "private themed studio room",
        "softly lit lounge interior",
    ),
    "配饰": (
        "elegant dressing room",
        "clean vanity area",
    ),
    "配饰/鞋袜/材质": (
        "elegant dressing room",
        "clean studio interior",
    ),
    "角色服装": (
        "clean character reference studio",
        "simple indoor character space",
    ),
}


def _preset_thumbnail_text(preset: dict[str, Any]) -> str:
    values: list[str] = [
        str(preset.get("id") or ""),
        str(preset.get("label") or ""),
        str(preset.get("translation") or ""),
        str(preset.get("category") or ""),
        str(preset.get("part") or ""),
        *(str(item) for item in (preset.get("tags") or [])),
        *(str(item) for item in (preset.get("accessories") or [])),
        *(str(item) for item in (preset.get("materials") or [])),
    ]
    return " ".join(values).lower()


def _strip_multi_subject_text(value: str) -> str:
    text = _MULTI_SUBJECT_RE.sub(" ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip(" ,;")


def _strip_prompt_fragments(value: str, fragments: tuple[str, ...]) -> str:
    text = str(value or "")
    for fragment in fragments:
        text = re.sub(
            rf"(?<![a-z0-9_]){re.escape(fragment)}(?![a-z0-9_])",
            " ",
            text,
            flags=re.IGNORECASE,
        )
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r",\s*(?:,\s*)+", ", ", text)
    return text.strip(" ,;")


def resolve_thumbnail_framing(
    preset_type: str,
    preset: dict[str, Any],
) -> dict[str, str]:
    """Choose the minimum framing that fully presents the preset subject."""
    if preset_type == "scene":
        return {"mode": "scene", "reason": "environment_only"}
    if preset_type == "toy":
        return {"mode": "toy_character_context", "reason": "toy_character_context"}
    if preset_type == "expansion":
        return {"mode": "expansion_internal", "reason": "internal_depth_focus"}
    if preset_type != "clothing":
        return {"mode": "full_body", "reason": "person_reference"}

    text = _preset_thumbnail_text(preset)
    if any(marker in text for marker in _LOWER_BODY_FOCUS_MARKERS):
        return {"mode": "full_body", "reason": "lower_body_focus"}
    if str(preset.get("part") or "") == "上装":
        return {"mode": "upper_body", "reason": "upper_garment_part"}
    if any(marker in text for marker in _UPPER_BODY_MARKERS):
        return {"mode": "upper_body", "reason": "upper_body_marker"}
    return {"mode": "partial_body", "reason": "show_complete_featured_garment"}


def resolve_thumbnail_scene(preset: dict[str, Any]) -> str:
    scenes = _CLOTHING_SCENE_MAP.get(str(preset.get("category") or ""))
    if not scenes:
        return "clean neutral studio background"
    digest = hashlib.sha256(str(preset.get("id") or "").encode("utf-8")).hexdigest()
    return scenes[int(digest[:8], 16) % len(scenes)]


def _preset_requires_front_back(preset: dict[str, Any]) -> bool:
    text = _preset_thumbnail_text(preset)
    return any(marker in text for marker in _BACK_FOCUS_MARKERS)


def _thumbnail_prompt_constraints(
    preset_type: str,
    preset: dict[str, Any],
) -> tuple[str, str, str, str, bool]:
    framing = resolve_thumbnail_framing(preset_type, preset)
    mode = framing["mode"]
    scene = ""
    front_back_required = (
        preset_type != "scene" and _preset_requires_front_back(preset)
    )
    if mode == "toy_character_context":
        positive_parts = [
            _SINGLE_PERSON_POSITIVE,
            _VISIBLE_FACE_POSITIVE,
            _FRONT_FACING_POSITIVE,
            _ACTION_FLEX_POSITIVE,
            _TOY_CHARACTER_CONTEXT_POSITIVE,
            "single private bedroom or lounge interior",
        ]
        negative_parts = [
            _SINGLE_PERSON_NEGATIVE,
            _VISIBLE_FACE_NEGATIVE,
            _FRONT_FACING_NEGATIVE,
            _ACTION_FLEX_NEGATIVE,
            _TOY_CHARACTER_CONTEXT_NEGATIVE,
        ]
        return (
            ", ".join(_dedupe_parts(positive_parts)),
            ", ".join(_dedupe_parts(negative_parts)),
            mode,
            scene,
            front_back_required,
        )
    if mode == "expansion_internal":
        target = str(preset.get("category") or "")
        profile = _EXPANSION_THUMBNAIL_PROFILES.get(
            target, _EXPANSION_THUMBNAIL_PROFILES["阴道扩张"]
        )
        state = str(preset.get("state") or "")
        state_positive = _EXPANSION_STATE_POSITIVE.get(
            state, "readable fictional internal expansion state"
        )
        positive_parts = [
            _EXPANSION_SINGLE_SUBJECT_POSITIVE,
            _EXPANSION_INTERNAL_FACE_POSITIVE,
            profile["pose"],
            profile["view"],
            state_positive,
            _EXPANSION_SIMPLE_STYLE_POSITIVE,
            "opaque legs and body outside the central pelvic area",
            "soft even lighting across the face and internal target region",
            "single private indoor setting",
        ]
        negative_parts = [
            _EXPANSION_SINGLE_SUBJECT_NEGATIVE,
            _EXPANSION_INTERNAL_NEGATIVE,
        ]
        if profile["required_detail_negative"]:
            negative_parts.append(profile["required_detail_negative"])
        return (
            ", ".join(_dedupe_parts(positive_parts)),
            ", ".join(_dedupe_parts(negative_parts)),
            mode,
            scene,
            front_back_required,
        )
    positive_parts: list[str] = [
        _SINGLE_PERSON_POSITIVE,
        _FRONT_LIGHT_POSITIVE,
        _ACTION_FLEX_POSITIVE,
    ]
    negative_parts: list[str] = [
        _SINGLE_PERSON_NEGATIVE,
        _FRONT_LIGHT_NEGATIVE,
        _ACTION_FLEX_NEGATIVE,
    ]
    if front_back_required:
        positive_parts.append(_FRONT_BACK_VIEW_POSITIVE)
        negative_parts.append(_FRONT_BACK_VIEW_NEGATIVE)
    else:
        positive_parts.append(_FRONT_FACING_POSITIVE)
        negative_parts.append(_FRONT_FACING_NEGATIVE)
    if mode == "upper_body":
        positive_parts.extend((_UPPER_BODY_FRAMING_POSITIVE, _VISIBLE_FACE_POSITIVE))
        negative_parts.extend((_UPPER_BODY_FRAMING_NEGATIVE, _VISIBLE_FACE_NEGATIVE))
    elif mode == "partial_body":
        positive_parts.extend((_PARTIAL_BODY_FRAMING_POSITIVE, _VISIBLE_FACE_POSITIVE))
        negative_parts.extend((_PARTIAL_BODY_FRAMING_NEGATIVE, _VISIBLE_FACE_NEGATIVE))
    elif mode == "full_body":
        positive_parts.extend((_FULL_BODY_FRAMING_POSITIVE, _VISIBLE_FACE_POSITIVE))
        negative_parts.extend((_FULL_BODY_FRAMING_NEGATIVE, _VISIBLE_FACE_NEGATIVE))
        if framing.get("reason") == "lower_body_focus":
            positive_parts.append(_LEG_FOCUS_POSITIVE)
            negative_parts.append(_LEG_FOCUS_NEGATIVE)
    elif mode == "scene":
        positive_parts = []
        negative_parts = ["unrelated people", "random human subjects"]
    elif mode == "object":
        positive_parts = [
            "single toy reference, complete object visible, centered clean product composition"
        ]
        negative_parts = [
            "multiple toys, human body, hands covering the object, cropped object, clutter"
        ]

    if preset_type == "clothing":
        scene = resolve_thumbnail_scene(preset)
        positive_parts.append(
            f"single clothing location appropriate for the outfit: {scene}"
        )
        negative_parts.append(
            "wrong clothing scene, multiple locations, conflicting environments"
        )
    return (
        ", ".join(_dedupe_parts(positive_parts)),
        ", ".join(_dedupe_parts(negative_parts)),
        mode,
        scene,
        front_back_required,
    )


def _parse_thumbnail_validation(raw: str) -> dict[str, Any]:
    cleaned = str(raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("视觉校验未返回 JSON")
    data, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    if not isinstance(data, dict):
        raise ValueError("视觉校验输出不是 JSON 对象")
    return data


def _record_candidate_validation(
    candidate_id: int,
    validation: dict[str, Any],
) -> None:
    candidate = database.get_preset_asset_candidate(candidate_id) or {}
    params = candidate.get("params")
    if isinstance(params, dict):
        params = dict(params)
    else:
        try:
            params = json.loads(str(candidate.get("params_json") or "{}"))
        except Exception:
            params = {}
        if not isinstance(params, dict):
            params = {}
    params["thumbnail_validation"] = validation
    database.update_preset_asset_candidate(
        candidate_id,
        params_json=json.dumps(params, ensure_ascii=False),
    )


def _thumbnail_validation_outcome(
    preset_type: str,
    preset: dict[str, Any],
    expected_mode: str,
    front_back_required: bool,
    data: dict[str, Any],
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    people_total = int(data.get("people_total") or 0)
    if expected_mode == "expansion_internal":
        if people_total != 1:
            warnings.append("people_count_manual_review_required")
    elif people_total != 1:
        failures.append("single_person_required")
    if expected_mode != "expansion_internal" and not bool(data.get("head_visible")):
        failures.append("full_head_required")
    if not bool(data.get("face_visible")):
        failures.append("face_visibility_required")
    if expected_mode == "full_body" and not bool(data.get("feet_visible")):
        failures.append("full_body_required")
    if (
        preset_type == "clothing"
        and expected_mode in {"upper_body", "partial_body"}
        and not bool(data.get("target_garment_visible"))
    ):
        failures.append("featured_garment_required")
    if preset_type == "toy":
        if not bool(data.get("target_subject_visible")):
            failures.append("featured_toy_required")
        if bool(data.get("isolated_product_only")):
            failures.append("toy_character_context_required")
    if expected_mode == "expansion_internal":
        target = str(preset.get("category") or "")
        if not bool(data.get("target_subject_visible")):
            failures.append("target_region_required")
        if not bool(data.get("direct_internal_view")):
            failures.append("direct_internal_view_required")
        if not bool(data.get("inner_wall_folds_visible")):
            failures.append("inner_wall_folds_required")
        if target == "阴道扩张" and not bool(data.get("cervix_visible")):
            warnings.append("cervix_manual_review_required")
        if bool(data.get("unrelated_organs_visible")):
            warnings.append("unrelated_organs_manual_review_required")
        if not bool(data.get("fluid_visual_visible")):
            failures.append("fluid_visual_required")
        if not bool(data.get("pose_matches")):
            failures.append("thumbnail_pose_mismatch")
    if (
        expected_mode == "expansion_minimal"
        and str(preset.get("state") or "") == "填充液体"
    ):
        if not bool(data.get("liquid_visible")):
            failures.append("liquid_visual_required")
        if not bool(data.get("liquid_origin_at_opening")):
            failures.append("liquid_origin_mismatch")
        if not bool(data.get("flow_direction_consistent")):
            failures.append("liquid_direction_inconsistent")
        if not bool(data.get("wet_area_localized")):
            failures.append("liquid_not_localized")
        if bool(data.get("whole_body_wetness")):
            failures.append("whole_body_wetness_detected")
        if bool(data.get("circular_frame_detected")):
            failures.append("circular_frame_detected")
        if bool(data.get("physical_container_visible")):
            failures.append("physical_container_detected")
        if bool(data.get("cutaway_detected")):
            failures.append("liquid_cutaway_detected")
    if (
        expected_mode == "expansion_minimal"
        and str(preset.get("state") or "") == "填充固体"
    ):
        if not bool(data.get("insert_visible")):
            failures.append("insert_required")
        if not bool(data.get("insert_contact_opening")):
            failures.append("insert_opening_contact_required")
        if not bool(data.get("insert_size_readable")):
            failures.append("insert_size_unreadable")
        if bool(data.get("insertion_motion_visible")) or bool(data.get("hand_holding_insert")):
            failures.append("insertion_action_detected")
        if (
            not bool(data.get("solid_material_confined_to_opening"))
            or not bool(data.get("normal_skin_visible"))
            or bool(data.get("body_material_transformed"))
            or bool(data.get("object_merged_into_body"))
        ):
            failures.append("solid_material_leak")
        if (
            not bool(data.get("solid_form_static"))
            or bool(data.get("solid_melting_visible"))
            or bool(data.get("solid_fragmentation_visible"))
        ):
            failures.append("solid_form_unstable")
        if bool(data.get("cutaway_detected")):
            failures.append("solid_cutaway_detected")
    if bool(data.get("front_shadow")):
        failures.append("front_shadow_detected")
    if front_back_required:
        if not bool(data.get("front_back_views")):
            failures.append("front_back_views_required")
        if not bool(data.get("identity_consistent")):
            failures.append("front_back_identity_mismatch")
        if not bool(data.get("front_view_visible")):
            failures.append("front_view_required")
    elif expected_mode != "expansion_internal" and not bool(data.get("front_facing")):
        failures.append("front_facing_required")
    if preset_type == "clothing" and not bool(data.get("scene_matches")):
        failures.append("clothing_scene_mismatch")
    return failures, warnings


def _validate_thumbnail_candidate(
    candidate_id: int,
    image_path: Path,
    preset_type: str,
    preset: dict[str, Any],
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode = str(config.PRESET_ASSET_SEMANTIC_VALIDATION or "advisory").lower()
    if mode == "off" or preset_type == "scene":
        validation = {"status": "skipped", "reason": "disabled_or_scene"}
        _record_candidate_validation(candidate_id, validation)
        return validation

    framing = resolve_thumbnail_framing(preset_type, preset)
    expected_mode = str(
        (snapshot or {}).get("thumbnail_mode") or framing.get("mode") or "full_body"
    )
    expected_style = str((snapshot or {}).get("thumbnail_style") or "")
    expected_scene = (
        resolve_thumbnail_scene(preset) if preset_type == "clothing" else ""
    )
    front_back_required = bool(
        (snapshot or {}).get("thumbnail_front_back")
        or _preset_requires_front_back(preset)
    )
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    model = database.get_setting("vlm_model", config.VLM_MODEL) or config.VLM_MODEL
    prompt = (
        "你是本地虚构缩略图质检器。只根据画面可见事实输出 JSON，不要解释。\n"
        f"要求的构图模式：{expected_mode}\n"
        f"要求的视觉风格：{expected_style or '不适用'}\n"
        f"要求的服装场景：{expected_scene or '不适用'}\n"
        f"是否要求正面和背面双视图：{'是' if front_back_required else '否'}\n"
        "输出字段："
        '{"people_total":0,"head_visible":true,"face_visible":true,'
        '"target_garment_visible":true,"target_subject_visible":true,'
        '"feet_visible":true,"direct_internal_view":true,'
        '"liquid_visible":true,"liquid_origin_at_opening":true,'
        '"flow_direction_consistent":true,"overflow_visible":true,'
        '"wet_area_localized":true,"whole_body_wetness":false,'
        '"circular_frame_detected":false,"physical_container_visible":false,'
        '"solid_object_visible":true,"solid_material_confined_to_opening":true,'
        '"insert_visible":true,"insert_contact_opening":true,'
        '"insert_size_readable":true,"insertion_motion_visible":false,'
        '"hand_holding_insert":false,'
        '"normal_skin_visible":true,"body_material_transformed":false,'
        '"object_merged_into_body":false,'
        '"solid_form_static":true,'
        '"solid_melting_visible":false,"solid_fragmentation_visible":false,'
        '"cutaway_detected":false,"inner_wall_folds_visible":true,'
        '"cervix_visible":false,"fluid_visual_visible":true,'
        '"visualized_organs":[],"unrelated_organs_visible":false,'
        '"pose_matches":true,"isolated_product_only":false,'
        '"front_shadow":false,"front_facing":true,'
        '"front_back_views":false,"identity_consistent":true,'
        '"front_view_visible":true,"scene_matches":true,'
        '"scene_observed":"","issues":[]}。\n'
        "people_total 只统计可辨认的独立人物身份；同一个角色的正面和背面双视图，"
        "或 expansion_internal 上区面部、下区身体所形成的协调双区域，仍计为一人。"
        "head_visible 表示头顶和完整头部在框内；"
        "face_visible 表示双眼和面部无遮挡；front_shadow 表示脸、胸口、腰腹或服装正面"
        "明显被阴影覆盖。full_body 模式要求双脚可见；upper_body 和 partial_body 不要求脚。"
        "clothing 类型必须判断 target_garment_visible 和 scene_matches；"
        "toy 类型必须判断 target_subject_visible，并确认不是 isolated_product_only。"
        "expansion_internal 必须同时判断面部、target_subject_visible、"
        "direct_internal_view、cutaway_detected、inner_wall_folds_visible、"
        "cervix_visible、fluid_visual_visible 和 pose_matches。"
        "expansion_minimal 的填充液体状态必须判断 liquid_visible、"
        "liquid_origin_at_opening、flow_direction_consistent、overflow_visible、"
        "wet_area_localized、whole_body_wetness、circular_frame_detected、"
        "physical_container_visible 和 cutaway_detected。液体需要从目标开口产生，"
        "允许在重力作用下外溢、滴落、浸湿相邻组织并在近处形成浅层积液；"
        "液体来源不明、逆重力、穿透身体、覆盖全身、圆形镜头框或独立实体容器"
        "才是问题。"
        "expansion_minimal 的填充固体状态必须判断 solid_object_visible、"
        "solid_material_confined_to_opening、normal_skin_visible、"
        "body_material_transformed、object_merged_into_body、solid_form_static、"
        "solid_melting_visible、"
        "solid_fragmentation_visible 和 cutaway_detected；固体必须是开口处的"
        "insert_visible、insert_contact_opening、insert_size_readable、"
        "insertion_motion_visible、hand_holding_insert、solid_material_confined_to_opening、"
        "normal_skin_visible、body_material_transformed、object_merged_into_body、"
        "solid_form_static、solid_melting_visible、solid_fragmentation_visible "
        "和 cutaway_detected；固体应当是已经插入并留在开口处的独立物体，尺寸和"
        "形状可读，不出现插入动作或手持物，不与皮肤融合或改变身体材质。"
        "当视觉风格为 transparent_internal_visual 时，透明内部可视化是预期风格；"
        "当视觉风格为 simplified_expansion_visual 时，皮肤、四肢和躯干应保持不透明，"
        "只允许骨盆区域出现简单的扩张轮廓。cutaway_detected 仅作为风格观察字段，"
        "不计为失败。"
        "visualized_organs 必须列出画面中清楚可见的内部结构名称；"
        "阴道扩张只允许 uterus、cervix、vaginal canal 及其内壁褶皱；"
        "肛门扩张只允许 anal opening、anal canal 及其内壁褶皱。"
        "出现 ovaries、fallopian tubes、bladder、intestines、colon、pelvic bones "
        "或其他无关器官时，unrelated_organs_visible 必须为 true。"
        "cutaway_detected 表示出现透明躯干、透明腹部、身体轮廓外的内部器官、"
        "双侧解剖剖面、图解线或医学插图式分层。"
        "front_back_views 表示同一角色正面和背面都得到清楚展示；"
        "identity_consistent 表示双视图中的身份和服装一致。"
    )
    try:
        response = requests.post(
            config.OLLAMA_BASE + "/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "images": [encoded],
                "stream": False,
                "format": "json",
                "options": {"num_predict": 500, "temperature": 0.0, "num_ctx": 6144},
            },
            timeout=180,
        )
        response.raise_for_status()
        data = _parse_thumbnail_validation(
            str(response.json().get("response") or "")
        )
    except Exception as exc:
        validation = {
            "status": "unavailable",
            "reason": str(exc)[-500:],
            "mode": expected_mode,
            "scene": expected_scene,
        }
        _record_candidate_validation(candidate_id, validation)
        if mode == "enforce":
            raise RuntimeError(
                f"thumbnail_semantic_validation_unavailable: {exc}"
            ) from exc
        return validation

    failures, warnings = _thumbnail_validation_outcome(
        preset_type,
        preset,
        expected_mode,
        front_back_required,
        data,
    )

    validation = {
        **data,
        "status": (
            "blocked"
            if failures and mode == "enforce"
            else "advisory_failed"
            if failures
            else "passed"
        ),
        "failures": failures,
        "advisory_failures": failures if mode != "enforce" else [],
        "blocking": bool(failures) and mode == "enforce",
        "warnings": warnings,
        "mode": expected_mode,
        "scene": expected_scene,
        "front_back_required": front_back_required,
        "model": model,
    }
    _record_candidate_validation(candidate_id, validation)
    if failures and mode == "enforce":
        raise RuntimeError(
            "thumbnail_semantic_validation_failed: " + ", ".join(failures)
        )
    return validation

_TYPE_TEMPLATES: dict[str, dict[str, str]] = {
    "pose": {
        "positive": (
            f"clear single-character reference, complete character, {_FULL_BODY_FRAMING_POSITIVE}, "
            f"{_VISIBLE_FACE_POSITIVE}, all limbs visible, natural coherent posture, "
            "balanced card-friendly composition"
        ),
        "negative": (
            "extra characters, missing characters, merged bodies, missing limbs, "
            f"incorrect anatomy, split pose, multiple views, {_FULL_BODY_FRAMING_NEGATIVE}, "
            f"{_VISIBLE_FACE_NEGATIVE}"
        ),
    },
    "clothing": {
        "positive": (
            f"single outfit reference, full-body fashion presentation, "
            f"{_FULL_BODY_FRAMING_POSITIVE}, {_VISIBLE_FACE_POSITIVE}, "
            "complete outfit visible, clear materials, clear layers, "
            "focused clothing presentation, target outfit replaces any base outfit, "
            "no unrelated garments"
        ),
        "negative": (
            "outfit collage, repeated character, obscured garment, missing garment parts, "
            f"wardrobe grid, unrelated clothing, extra layered outfit, "
            f"{_FULL_BODY_FRAMING_NEGATIVE}, {_VISIBLE_FACE_NEGATIVE}"
        ),
    },
    "scene": {
        "positive": (
            "clear environment reference, stable composition, readable setting, coherent lighting, "
            "background-focused presentation"
        ),
        "negative": (
            "unrelated people, cluttered subject, inconsistent perspective, broken architecture, "
            "random props"
        ),
    },
    "body": {
        "positive": (
            "adult fictional character, static decorative result, "
            f"{_FULL_BODY_FRAMING_POSITIVE}, {_VISIBLE_FACE_POSITIVE}, "
            "clean presentation, coherent anatomy"
        ),
        "negative": (
            "procedure, operation process, wound, blood, medical instrument, permanent injury, "
            f"open injury, {_FULL_BODY_FRAMING_NEGATIVE}, {_VISIBLE_FACE_NEGATIVE}"
        ),
    },
    "toy": {
        "positive": (
            "single toy character-context reference, exactly one adult woman "
            "interacting with the featured visual toy, complete toy inside frame, "
            "readable toy silhouette and material, character and toy clearly connected"
        ),
        "negative": (
            "isolated product shot only, toy-only image, disembodied object, "
            "multiple different toys, duplicate object, cropped toy, toy hidden by "
            "hands, extra people, text, watermark, logo, collage, multiple panels"
        ),
    },
    "expansion": {
        "positive": (
            "single adult woman, body-focused fictional expansion state, "
            "subtle expansion silhouette in the central pelvic area, minimal detail, "
            "clean visual presentation, coherent anatomy, normal opaque skin, opaque "
            "arms, legs, abdomen, and torso"
        ),
        "negative": (
            "real-world procedure, real material recommendation, medical instruction, "
            "medical labels, clinical chart, text annotations, surgical instrument, "
            "ovaries, fallopian tubes, bladder, intestines, colon, pelvic bones, "
            "skeleton, unrelated internal organs, extra anatomy, "
            "transparent arms, transparent legs, transparent torso, translucent body, "
            "see-through skin, x-ray body, "
            "extra people, cropped internal target, text, watermark"
        ),
    },
    "character": {
        "positive": (
            "single adult fictional character, complete full-body character reference, "
            f"{_FULL_BODY_FRAMING_POSITIVE}, {_VISIBLE_FACE_POSITIVE}, "
            "consistent identity, clean neutral presentation, coherent anatomy, "
            "card-friendly character composition"
        ),
        "negative": (
            "multiple characters, duplicate character, inconsistent identity, "
            "text, watermark, logo, collage, split view, multiple views, "
            f"{_FULL_BODY_FRAMING_NEGATIVE}, {_VISIBLE_FACE_NEGATIVE}"
        ),
    },
}


class PresetAssetCancelled(RuntimeError):
    """Raised internally when a queued workshop job has been cancelled."""


def _dedupe_parts(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in parts:
        value = str(raw or "").strip()
        normalized = " ".join(value.lower().split())
        if not value or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _safe_resource_name(value: str, label: str) -> str:
    name = str(value or "").strip()
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or "\x00" in name
    ):
        raise asset_service.PresetAssetError(f"{label}名称非法", status_code=400)
    return name


def _normalize_seed(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        seed = int(value)
    except (TypeError, ValueError) as exc:
        raise asset_service.PresetAssetError("seed 必须是整数", status_code=400) from exc
    return max(0, min(2**63 - 1, seed))


def _pose_has_explicit_clothing(preset: dict[str, Any]) -> bool:
    """Keep clothing-focused pose and play presets on their original styling."""
    text = " ".join(
        [
            str(preset.get("draw_prompt") or ""),
            *(str(tag) for tag in (preset.get("tags") or [])),
        ]
    ).lower()
    return any(marker in text for marker in _POSE_EXPLICIT_CLOTHING_MARKERS)


def _strip_generic_pose_clothing(prompt: str) -> str:
    """Remove generic outfit cues so default-nude pose prompts stay coherent."""
    result = str(prompt or "")
    for marker, replacement in _POSE_GENERIC_CLOTHING_REPLACEMENTS:
        result = re.sub(
            rf"\b{re.escape(marker)}\b",
            replacement,
            result,
            flags=re.IGNORECASE,
        )
    for marker in _POSE_GENERIC_CLOTHING_REMOVALS:
        result = re.sub(
            rf"\b{re.escape(marker)}\b",
            "",
            result,
            flags=re.IGNORECASE,
        )
    result = re.sub(r"\s*,\s*", ", ", result)
    result = re.sub(r"\s*;\s*", "; ", result)
    result = re.sub(r";\s*,+", "; ", result)
    result = re.sub(r",\s*(?:,\s*)+", ", ", result)
    result = re.sub(r"\s+", " ", result)
    return result.strip(" ,;")


def _minimal_expansion_prompt(preset: dict[str, Any]) -> str:
    style = f"{_EXPANSION_MINIMAL_STYLE_POSITIVE}, "
    state = str(preset.get("state") or "")
    target = "anal opening" if str(preset.get("category") or "") == "肛门扩张" else "vaginal opening"
    state_detail = {
        "仅展示": ", visible expansion state only, no additional internal detail",
        "填充液体": (
            f", fluid originates at the {target}, natural gravity-driven flow, "
            "visible overflow allowed, localized wetness around the opening and "
            "adjacent tissue, nearby shallow pooling allowed"
        ),
        "填充固体": (
            f", one clearly visible smooth solid insert already positioned inside "
            f"the {target}, insert occupies and is partially visible at the opening, "
            "readable solid object shape and size, static insertion state, no insertion "
            "motion, normal human skin texture on the face, torso, arms, legs, and "
            "buttocks, opaque skin, normal skin shading, body unchanged except at "
            "the opening"
        ),
    }.get(state, "")
    if str(preset.get("category") or "") == "肛门扩张":
        return (
            f"{style}one adult woman, solo, visible face, clearly visible anal dilation, "
            "visibly widened opening, obvious expansion state, side-lying pose "
            "with hips raised, hips raised toward the camera, rear pelvic area "
            "clearly visible, torso adjusted for face visibility, rear pelvic area "
            "oriented toward the viewer, stable body silhouette, target pelvic area "
            f"unobstructed by hands, thighs, or hair{state_detail}"
        )
    return (
        f"{style}one adult woman, solo, visible face, clearly visible vaginal dilation, "
        "visibly widened opening, obvious expansion state, supine pose with "
        "knees raised and apart, pelvic area centered and clearly visible from "
        "the camera, pelvis tilted toward the viewer, stable body silhouette, "
        f"target pelvic area unobstructed by hands, thighs, or hair{state_detail}"
    )


def _minimal_expansion_negative(preset: dict[str, Any]) -> str:
    negative_parts = [_EXPANSION_MINIMAL_STYLE_NEGATIVE]
    state = str(preset.get("state") or "")
    if state == "填充液体":
        negative_parts.append(_EXPANSION_LIQUID_NEGATIVE)
    elif state == "填充固体":
        negative_parts.append(_EXPANSION_SOLID_NEGATIVE)
    return ", ".join(_dedupe_parts(negative_parts))


def _build_minimal_expansion_snapshot(
    preset_id: str,
    preset: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    target = asset_service.target_for("expansion")
    output_width, output_height = (int(item) for item in target["output_size"])
    if settings.get("generate_at_output_size"):
        generation_width, generation_height = output_width, output_height
    else:
        generation_width, generation_height = (
            int(item) for item in target["generation_size"]
        )
    positive = _minimal_expansion_prompt(preset)
    negative = _minimal_expansion_negative(preset)
    return {
        "version": 1,
        "settings": settings,
        "preset_type": "expansion",
        "preset_id": preset_id,
        "template_version": config.PRESET_ASSET_TEMPLATE_VERSION,
        "prompt_mode": "minimal_expansion",
        "prompt_layers": {
            "style_positive": "",
            "preset_draw_prompt": "",
            "generation_prompt": positive,
            "preset_tags": "",
            "type_positive": "",
            "user_positive": "",
            "thumbnail_positive": positive,
            "style_negative": _EXPANSION_MINIMAL_STYLE_NEGATIVE,
            "common_negative": "",
            "type_negative": "",
            "user_negative": "",
            "thumbnail_negative": negative,
        },
        "thumbnail_mode": "expansion_minimal",
        "thumbnail_style": "minimal_expansion",
        "thumbnail_scene": "",
        "thumbnail_front_back": False,
        "prompt_positive": positive,
        "base_prompt_positive": positive,
        "masked_prompt_positive": "",
        "prompt_negative": negative,
        "generation_width": generation_width,
        "generation_height": generation_height,
        "output_width": output_width,
        "output_height": output_height,
        "candidate_count": int(settings["candidate_count"]),
    }


def build_prompt_snapshot(
    preset_type: str,
    preset_id: str,
    values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the immutable candidate parameter and four-layer prompt snapshot."""
    preset = asset_service.resolve_preset(preset_type, preset_id)
    target = asset_service.target_for(preset_type)
    defaults = asset_service.settings_payload()["defaults"]
    raw = values if isinstance(values, dict) else {}
    if isinstance(raw.get("settings"), dict):
        raw = dict(raw["settings"])
    settings = asset_service.normalize_settings({**defaults, **raw})
    settings["model"] = _safe_resource_name(settings.get("model"), "模型")
    settings["loras"] = [
        _safe_resource_name(name, "LoRA")
        for name in settings.get("loras", [])
    ][:24]
    settings["seed"] = _normalize_seed(settings.get("seed"))
    if preset_type == "expansion":
        return _build_minimal_expansion_snapshot(
            preset_id,
            preset,
            settings,
        )

    template = _TYPE_TEMPLATES[preset_type]
    core_tags = ", ".join(
        _strip_multi_subject_text(str(tag))
        for tag in (preset.get("tags") or [])
        if _strip_multi_subject_text(str(tag))
    )
    core_prompt = str(preset.get("draw_prompt") or "")
    generation_prompt = _strip_multi_subject_text(core_prompt)
    if preset_type == "expansion":
        generation_prompt = "adult woman in a fictional visual expansion state"
        core_tags = _strip_prompt_fragments(
            core_tags,
            _EXPANSION_CUTAWAY_FRAGMENTS,
        )
    type_positive = template["positive"]
    type_negative = template["negative"]
    if preset_type == "pose":
        generation_prompt = core_prompt
    (
        thumbnail_positive,
        thumbnail_negative,
        thumbnail_mode,
        thumbnail_scene,
        thumbnail_front_back,
    ) = _thumbnail_prompt_constraints(preset_type, preset)
    common_negative = _COMMON_NEGATIVE
    if preset_type == "expansion":
        dual_region_conflicts = ("collage", "multiple panels")
        common_negative = _strip_prompt_fragments(
            common_negative,
            dual_region_conflicts,
        )
        type_negative = _strip_prompt_fragments(
            type_negative,
            dual_region_conflicts,
        )
    if thumbnail_front_back:
        view_conflicts = (
            "collage",
            "multiple panels",
            "split view",
            "multiple views",
            "outfit collage",
            "wardrobe grid",
            "duplicate character",
            "duplicate subject",
        )
        common_negative = _strip_prompt_fragments(common_negative, view_conflicts)
        type_negative = _strip_prompt_fragments(type_negative, view_conflicts)
    positive = ", ".join(
        _dedupe_parts(
            [
                settings["style_positive"],
                generation_prompt,
                core_tags,
                type_positive,
                settings["user_positive"],
                thumbnail_positive,
            ]
        )
    )
    negative = ", ".join(
        _dedupe_parts(
            [
                settings["style_negative"],
                common_negative,
                type_negative,
                settings["user_negative"],
                thumbnail_negative,
            ]
        )
    )
    base_prompt_positive = positive
    masked_prompt_positive = ""
    if content_filter.is_hard_blocked(positive):
        raise asset_service.PresetAssetError("提示词包含禁止内容", status_code=400)

    output_width, output_height = (int(item) for item in target["output_size"])
    if settings.get("generate_at_output_size"):
        generation_width, generation_height = output_width, output_height
    else:
        generation_width, generation_height = (
            int(item) for item in target["generation_size"]
        )
    for width, height in (
        (generation_width, generation_height),
        (output_width, output_height),
    ):
        if not (
            config.DRAW_WIDTH_MIN <= width <= config.DRAW_WIDTH_MAX
            and config.DRAW_HEIGHT_MIN <= height <= config.DRAW_HEIGHT_MAX
        ):
            raise asset_service.PresetAssetError("生成尺寸超出允许范围", status_code=400)

    snapshot = {
        "version": 1,
        "settings": settings,
        "preset_type": preset_type,
        "preset_id": preset_id,
        "template_version": config.PRESET_ASSET_TEMPLATE_VERSION,
        "prompt_layers": {
            "style_positive": settings["style_positive"],
            "preset_draw_prompt": core_prompt,
            "generation_prompt": generation_prompt,
            "preset_tags": core_tags,
            "type_positive": type_positive,
            "user_positive": settings["user_positive"],
            "thumbnail_positive": thumbnail_positive,
            "style_negative": settings["style_negative"],
            "common_negative": common_negative,
            "type_negative": type_negative,
            "user_negative": settings["user_negative"],
            "thumbnail_negative": thumbnail_negative,
        },
        "thumbnail_mode": thumbnail_mode,
        "thumbnail_style": (
            "simplified_expansion_visual"
            if preset_type == "expansion"
            else ""
        ),
        "thumbnail_scene": thumbnail_scene,
        "thumbnail_front_back": thumbnail_front_back,
        "prompt_positive": positive,
        "base_prompt_positive": base_prompt_positive,
        "masked_prompt_positive": masked_prompt_positive,
        "prompt_negative": negative,
        "generation_width": generation_width,
        "generation_height": generation_height,
        "output_width": output_width,
        "output_height": output_height,
        "candidate_count": int(settings["candidate_count"]),
    }
    if preset_type == "character":
        snapshot["preset_version"] = int(preset.get("version") or 1)
    return snapshot


def _seed_for(snapshot: dict[str, Any], index: int) -> int:
    settings = snapshot["settings"]
    strategy = settings.get("seed_strategy") or "random"
    base_seed = _normalize_seed(settings.get("seed"))
    if strategy == "fixed":
        if base_seed is None:
            digest = hashlib.sha256(
                (
                    snapshot["preset_type"]
                    + ":"
                    + snapshot["preset_id"]
                    + ":"
                    + snapshot["prompt_positive"]
                ).encode("utf-8")
            ).digest()
            base_seed = int.from_bytes(digest[:8], "big") % (2**63 - 1)
        return max(0, min(2**63 - 1, base_seed + index))
    if strategy == "derive":
        if base_seed is None:
            base_seed = 0
        return max(0, min(2**63 - 1, base_seed + index))
    return random.SystemRandom().randrange(0, 2**63 - 1)


def _normalize_create_items(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    if not items:
        raise asset_service.PresetAssetError("批量任务不能为空", status_code=400)
    if len(items) > config.PRESET_ASSET_BATCH_MAX_ITEMS:
        raise asset_service.PresetAssetError(
            f"批量任务最多 {config.PRESET_ASSET_BATCH_MAX_ITEMS} 项",
            status_code=400,
        )

    normalized_items: list[dict[str, Any]] = []
    total = 0
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise asset_service.PresetAssetError("任务项格式错误", status_code=400)
        preset_type = str(raw_item.get("preset_type") or "")
        preset_id = str(raw_item.get("preset_id") or "")
        preset = asset_service.resolve_preset(preset_type, preset_id)
        mode = str(raw_item.get("mode") or "ai")
        if mode == "ai":
            snapshot = build_prompt_snapshot(
                preset_type,
                preset_id,
                raw_item.get("params") or raw_item,
            )
            params = snapshot
            total += int(snapshot["candidate_count"])
        elif mode == "crop":
            source_id = raw_item.get("source_id")
            if source_id in (None, ""):
                source = database.get_active_preset_asset_source(
                    preset_type, preset_id
                )
                if not source:
                    raise asset_service.PresetAssetError(
                        "没有可用的源图", status_code=409
                    )
                source_id = source["id"]
            source = database.get_preset_asset_source(int(source_id))
            if (
                not source
                or source.get("preset_type") != preset_type
                or source.get("preset_id") != preset_id
            ):
                raise asset_service.PresetAssetError(
                    "源图不属于当前预设", status_code=400
                )
            crop_params = dict(raw_item.get("params") or {})
            if preset_type == "character":
                crop_params["preset_version"] = int(preset.get("version") or 1)
            params = {
                "source_id": int(source_id),
                "crop": dict(raw_item.get("crop") or {}),
                "params": crop_params,
                "candidate_count": 1,
            }
            total += 1
        else:
            raise asset_service.PresetAssetError("未知的生成方式", status_code=400)
        normalized_items.append(
            {
                "preset_type": preset_type,
                "preset_id": preset_id,
                "mode": mode,
                "params": params,
            }
        )
    return normalized_items, total


def _request_hash(normalized_items: list[dict[str, Any]]) -> str:
    payload = {
        "version": JOB_REQUEST_VERSION,
        "items": normalized_items,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_idempotency_key(value: str | None) -> str:
    key = str(value or "").strip()
    if not key:
        return f"internal-{uuid.uuid4().hex}"
    if len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise asset_service.PresetAssetError(
            f"Idempotency-Key 最多 {IDEMPOTENCY_KEY_MAX_LENGTH} 个字符",
            status_code=400,
        )
    if any(ord(char) < 32 for char in key):
        raise asset_service.PresetAssetError(
            "Idempotency-Key 不能包含控制字符",
            status_code=400,
        )
    return key


def _classify_failure(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, TimeoutError) or "timeout" in text or "超时" in text:
        return "generation_timeout"
    if any(
        marker in text
        for marker in (
            "connection",
            "refused",
            "unreachable",
            "service unavailable",
            "bad gateway",
            "503",
        )
    ):
        return "generation_service_unavailable"
    if any(
        marker in text
        for marker in (
            "out of memory",
            "cuda",
            "vram",
            "gpu",
            "显存",
            "忙碌",
            "busy",
        )
    ):
        return "gpu_busy"
    if isinstance(exc, asset_service.PresetAssetError):
        if "预设" in text:
            return "invalid_preset"
        return "invalid_parameters"
    return "generation_failed"


def _retry_metadata(
    failure_code: str,
    attempt_count: int,
) -> tuple[str | None, int]:
    if failure_code not in RETRYABLE_FAILURE_CODES:
        return None, 0
    exponent = min(max(1, int(attempt_count)) - 1, 7)
    backoff_seconds = min(
        RETRY_BACKOFF_MAX_SECONDS,
        RETRY_BACKOFF_BASE_SECONDS * (2**exponent),
    )
    next_retry_at = (
        datetime.now().astimezone() + timedelta(seconds=backoff_seconds)
    ).isoformat(timespec="seconds")
    return next_retry_at, backoff_seconds


def _item_retry_contract(item: dict[str, Any]) -> tuple[bool, str]:
    status = str(item.get("status") or "")
    if status not in RECOVERABLE_ITEM_STATUSES:
        return False, "none"

    failure_code = str(item.get("last_error_code") or "").strip()
    if failure_code in FAILURE_RETRY_CONTRACT:
        return FAILURE_RETRY_CONTRACT[failure_code]

    # Older failed/interrupted/cancelled rows may not have a structured code.
    return True, "retry"


def _register_created_job(
    job_id: str,
    total: int,
    normalized_items: list[dict[str, Any]],
) -> None:
    task_registry.register(
        JOB_KIND,
        job_id,
        payload={
            "items": len(normalized_items),
            "request_version": JOB_REQUEST_VERSION,
        },
        total=total,
        status="queued",
        resources=task_resources.for_kind(JOB_KIND),
    )


def create_job(
    items: list[dict[str, Any]],
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Create or reuse a queued batch job using a stable request fingerprint."""
    normalized_items, total = _normalize_create_items(items)
    request_hash = _request_hash(normalized_items)
    resolved_key = _normalize_idempotency_key(idempotency_key)

    job_id = uuid.uuid4().hex
    created = database.create_preset_asset_job(
        job_id,
        total,
        normalized_items,
        idempotency_key=resolved_key,
        request_hash=request_hash,
        payload={
            "items": len(normalized_items),
            "request_version": JOB_REQUEST_VERSION,
        },
    )
    if created["conflict"]:
        raise asset_service.PresetAssetError(
            "Idempotency-Key 已用于不同的任务请求",
            status_code=409,
        )
    resolved_job_id = str(created["job_id"])
    if created["created"]:
        _register_created_job(resolved_job_id, total, normalized_items)
    elif not task_registry.get(JOB_KIND, resolved_job_id):
        raise asset_service.PresetAssetError(
            "幂等任务记录缺少对应后台任务",
            status_code=409,
        )

    current = task_registry.get(JOB_KIND, resolved_job_id) or {}
    if current.get("status") not in task_registry.TERMINAL_STATUSES:
        _start_job_thread(resolved_job_id)
    return job_status(resolved_job_id)


def _start_job_thread(job_id: str, only_indexes: set[int] | None = None) -> None:
    with _JOB_THREADS_LOCK:
        existing = _JOB_THREADS.get(job_id)
        if existing and existing.is_alive():
            return
        thread = threading.Thread(
            target=_run_job,
            args=(job_id, only_indexes),
            name=f"preset-asset-{job_id[:8]}",
            daemon=True,
        )
        _JOB_THREADS[job_id] = thread
        thread.start()


def restore_pending_jobs() -> int:
    """Recover queued workshop items after restart without replaying GPU work."""
    jobs: list[dict[str, Any]] = []
    for status in (
        "queued",
        "preparing",
        "running",
        "cancel_requested",
        # The shared task registry may have marked the outer job interrupted
        # before this workshop-specific recovery runs.
        "interrupted",
    ):
        jobs.extend(
            database.list_background_jobs(
                kind=JOB_KIND,
                status=status,
            )
        )

    recovered = 0
    for job in jobs:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            continue
        items = database.list_preset_asset_job_items(job_id)
        candidates = database.list_preset_asset_candidates_by_job(job_id)
        if (
            str(job.get("status") or "") == "interrupted"
            and not any(
                item.get("status") in ACTIVE_AI_STATUSES for item in items
            )
            and not any(
                candidate.get("status") in ACTIVE_AI_STATUSES
                for candidate in candidates
            )
        ):
            continue
        cancel_requested = (
            str(job.get("status") or "") == "cancel_requested"
            or bool(job.get("stop_requested"))
        )
        interrupted_indexes = {
            int(item["item_index"])
            for item in items
            if cancel_requested
            or item.get("status") in {"running", "cancel_requested"}
        }
        if interrupted_indexes:
            database.mark_preset_asset_job_items_interrupted(
                job_id,
                interrupted_indexes,
                RESTART_INTERRUPTED_REASON,
            )
        database.mark_preset_asset_job_active_candidates_interrupted(
            job_id,
            RESTART_INTERRUPTED_REASON,
        )

        refreshed_items = database.list_preset_asset_job_items(job_id)
        pending_indexes = {
            int(item["item_index"])
            for item in refreshed_items
            if not cancel_requested
            and item.get("status") in PENDING_ITEM_STATUSES
        }
        if pending_indexes:
            task_registry.update(
                JOB_KIND,
                job_id,
                status="queued",
                current="启动恢复待执行项",
                error=None,
                stop_requested=False,
                finished_at=None,
            )
            _start_job_thread(job_id, pending_indexes)
        elif refreshed_items and all(
            item.get("status") == "done" for item in refreshed_items
        ):
            task_registry.update(
                JOB_KIND,
                job_id,
                status="done",
                current="已完成",
                error=None,
                finished_at=database.now_iso(),
            )
        else:
            failed_count = sum(
                1 for item in refreshed_items if item.get("status") == "failed"
            )
            task_registry.update(
                JOB_KIND,
                job_id,
                status="error" if failed_count else "interrupted",
                current="已中断" if not failed_count else "部分任务项失败",
                error=(
                    f"{failed_count} 个任务项失败"
                    if failed_count
                    else RESTART_INTERRUPTED_REASON
                ),
                finished_at=database.now_iso(),
            )
        recovered += 1
    return recovered


def _run_job(job_id: str, only_indexes: set[int] | None = None) -> None:
    try:
        task_registry.update(
            JOB_KIND,
            job_id,
            status="preparing",
            current="准备参数快照",
            error=None,
            finished_at=None,
        )
        items = database.list_preset_asset_job_items(job_id)
        for item in items:
            item_index = int(item["item_index"])
            if only_indexes is not None and item_index not in only_indexes:
                continue
            if _job_cancelled(job_id):
                _mark_job_cancelled(job_id, item)
                break
            mode = str(item["params"].get("mode") or "ai")
            started_item = database.start_preset_asset_job_item_attempt(
                job_id,
                item_index,
            )
            if not started_item:
                continue
            task_registry.update(
                JOB_KIND,
                job_id,
                status="preparing",
                current=f"{item['preset_type']}/{item['preset_id']}",
            )
            try:
                if mode == "crop":
                    produced, item_status = _process_crop_item(job_id, item)
                else:
                    produced, item_status = _process_ai_item(job_id, item)
            except PresetAssetCancelled:
                produced, item_status = 0, "cancelled"
                database.update_preset_asset_job_item(
                    job_id,
                    item_index,
                    status=item_status,
                    error="已取消",
                    last_error_code="cancelled",
                    next_retry_at=None,
                    retry_backoff_seconds=0,
                )
            except Exception as exc:
                produced, item_status = 0, "failed"
                failure_code = _classify_failure(exc)
                next_retry_at, backoff_seconds = _retry_metadata(
                    failure_code,
                    int(started_item.get("attempt_count") or 1),
                )
                database.update_preset_asset_job_item(
                    job_id,
                    item_index,
                    status="failed",
                    error=str(exc)[-2000:],
                    last_error_code=failure_code,
                    next_retry_at=next_retry_at,
                    retry_backoff_seconds=backoff_seconds,
                )
                database.add_preset_asset_audit(
                    "job_item_failed",
                    str(item["preset_type"]),
                    str(item["preset_id"]),
                    job_id=job_id,
                    detail={
                        "item_index": item_index,
                        "error": str(exc)[-1000:],
                        "failure_code": failure_code,
                        "attempt_count": int(
                            started_item.get("attempt_count") or 1
                        ),
                        "next_retry_at": next_retry_at,
                        "retry_backoff_seconds": backoff_seconds,
                    },
                )
            else:
                database.update_preset_asset_job_item(
                    job_id,
                    item_index,
                    status=item_status,
                    error=None if item_status == "done" else "已取消",
                )
            if produced:
                current = task_registry.get(JOB_KIND, job_id) or {}
                task_registry.update(
                    JOB_KIND,
                    job_id,
                    done=int(current.get("done") or 0) + produced,
                )
            if item_status == "cancelled" or _job_cancelled(job_id):
                _mark_job_cancelled(job_id, item, clear_pending=True)
                break
        _finish_job_from_items(job_id)
    except Exception as exc:
        task_registry.finish(JOB_KIND, job_id, "error", str(exc)[-2000:])
        database.add_preset_asset_audit(
            "job_failed",
            job_id=job_id,
            detail={"error": str(exc)[-1000:]},
        )
    finally:
        with _JOB_THREADS_LOCK:
            _JOB_THREADS.pop(job_id, None)


def _process_ai_item(
    job_id: str,
    item: dict[str, Any],
) -> tuple[int, str]:
    snapshot = item["params"]
    preset = asset_service.resolve_preset(
        str(item["preset_type"]),
        str(item["preset_id"]),
    )
    candidate_params = {
        **snapshot,
        asset_service.CANDIDATE_JOB_ITEM_INDEX_PARAM: int(item["item_index"]),
    }
    count = int(snapshot.get("candidate_count") or 1)
    generated = 0
    for index in range(count):
        if _job_cancelled(job_id):
            raise PresetAssetCancelled()
        seed = _seed_for(snapshot, index)
        candidate_id = database.insert_preset_asset_candidate(
            str(item["preset_type"]),
            str(item["preset_id"]),
            "ai",
            "queued",
            candidate_params,
            job_id=job_id,
            source_revision_id=None,
            prompt_positive=str(snapshot["prompt_positive"]),
            prompt_negative=str(snapshot["prompt_negative"]),
            template_version=str(snapshot["template_version"]),
            model=str(snapshot["settings"]["model"]),
            loras=list(snapshot["settings"].get("loras") or []),
            seed=seed,
            generation_width=int(snapshot["generation_width"]),
            generation_height=int(snapshot["generation_height"]),
            output_width=int(snapshot["output_width"]),
            output_height=int(snapshot["output_height"]),
        )
        database.update_preset_asset_job_item(
            job_id,
            int(item["item_index"]),
            candidate_id=candidate_id,
        )
        gpu_acquired = False
        try:
            while True:
                acquired = _wait_for_gpu_slot(job_id, candidate_id)
                if not acquired:
                    database.update_preset_asset_candidate(
                        candidate_id,
                        status="cancelled",
                        error="已取消",
                    )
                    raise PresetAssetCancelled()
                try:
                    task_registry.update(
                        JOB_KIND,
                        job_id,
                        status="running",
                        current=f"{item['preset_type']}/{item['preset_id']}",
                    )
                    break
                except task_resources.ResourceConflictError:
                    _release_gpu_slot()
                    time.sleep(0.5)
            gpu_acquired = True
            database.update_preset_asset_candidate(
                candidate_id,
                status="running",
                error=None,
            )
            candidate_dir = _candidate_dir(
                str(item["preset_type"]),
                str(item["preset_id"]),
                candidate_id,
            )
            masked_prompt = None
            mask_image = None
            if snapshot.get("masked_prompt_positive"):
                mask_image = _expansion_inpaint_mask(
                    preset,
                    int(snapshot["generation_width"]),
                    int(snapshot["generation_height"]),
                )
                masked_prompt = str(
                    snapshot.get("masked_prompt_positive")
                    or snapshot["prompt_positive"]
                )
            result = comfy_worker.generate(
                prompt=str(
                    snapshot.get("base_prompt_positive")
                    or snapshot["prompt_positive"]
                ),
                negative_prompt=str(snapshot["prompt_negative"]),
                width=int(snapshot["generation_width"]),
                height=int(snapshot["generation_height"]),
                steps=int(snapshot["settings"]["steps"]),
                cfg=float(snapshot["settings"]["cfg"]),
                loras=list(snapshot["settings"].get("loras") or []),
                timeout=config.COMFY_GENERATE_TIMEOUT,
                model_name=str(snapshot["settings"]["model"]),
                lora_strength_model=float(
                    snapshot["settings"].get("lora_strength_model")
                    or config.DRAW_DEFAULT_LORA_STRENGTH_MODEL
                ),
                lora_strength_clip=float(
                    snapshot["settings"].get("lora_strength_clip")
                    or config.DRAW_DEFAULT_LORA_STRENGTH_CLIP
                ),
                seed=seed,
                lora_strengths=snapshot["settings"].get("lora_strengths"),
                output_dir=str(candidate_dir),
                masked_prompt=masked_prompt,
                mask_image=mask_image,
            )
            if _job_cancelled(job_id):
                database.update_preset_asset_candidate(
                    candidate_id,
                    status="cancelled",
                    error="已取消",
                )
                raise PresetAssetCancelled()
            saved_path = result.get("saved_path")
            if not saved_path or not Path(str(saved_path)).is_file():
                raise RuntimeError("ComfyUI 未返回可用的生成图片")
            _validate_thumbnail_candidate(
                candidate_id,
                Path(str(saved_path)),
                str(item["preset_type"]),
                preset,
                snapshot,
            )
            asset_service.finalize_ai_candidate(
                candidate_id,
                Path(str(saved_path)),
                crop={
                    "mode": snapshot["settings"]["crop_mode"],
                    "focus_x": snapshot["settings"]["focus_x"],
                    "focus_y": snapshot["settings"]["focus_y"],
                    "zoom": snapshot["settings"]["zoom"],
                },
            )
            database.update_preset_asset_candidate(
                candidate_id,
                seed=int(result.get("seed") or seed),
            )
            generated += 1
        except PresetAssetCancelled:
            raise
        except Exception as exc:
            if _job_cancelled(job_id):
                database.update_preset_asset_candidate(
                    candidate_id,
                    status="cancelled",
                    error="已取消",
                )
                raise PresetAssetCancelled() from exc
            database.update_preset_asset_candidate(
                candidate_id,
                status="failed",
                error=str(exc)[-2000:],
            )
            raise
        finally:
            if gpu_acquired:
                _release_gpu_slot()
    return generated, "done"


def _process_crop_item(
    job_id: str,
    item: dict[str, Any],
) -> tuple[int, str]:
    if _job_cancelled(job_id):
        raise PresetAssetCancelled()
    params = item["params"]
    preset = asset_service.resolve_preset(
        str(item["preset_type"]),
        str(item["preset_id"]),
    )
    with _CPU_SEMAPHORE:
        candidate = asset_service.create_crop_candidate(
            str(item["preset_type"]),
            str(item["preset_id"]),
            source_id=int(params["source_id"]),
            crop=dict(params.get("crop") or {}),
            params=dict(params.get("params") or {}),
            job_item_index=int(item["item_index"]),
        )
    try:
        _validate_thumbnail_candidate(
            int(candidate["id"]),
            Path(str(candidate["thumbnail_path"])),
            str(item["preset_type"]),
            preset,
        )
    except Exception as exc:
        database.update_preset_asset_candidate(
            int(candidate["id"]),
            status="failed",
            error=str(exc)[-2000:],
        )
        raise
    database.update_preset_asset_candidate(
        int(candidate["id"]),
        job_id=job_id,
    )
    database.update_preset_asset_job_item(
        job_id,
        int(item["item_index"]),
        candidate_id=int(candidate["id"]),
    )
    return 1, "done"


def _wait_for_gpu_slot(job_id: str, candidate_id: int) -> bool:
    global _AI_ACTIVE
    while True:
        if _job_cancelled(job_id):
            return False
        with _GPU_CONDITION:
            external = [
                task
                for task in task_registry.running_tasks()
                if task.get("type") != JOB_KIND
            ]
            if not external and not _AI_ACTIVE:
                _AI_ACTIVE = True
                return True
        reason = (
            "等待其他重任务释放 GPU"
            if external
            else "等待前一个预设生成任务"
        )
        task_registry.update(JOB_KIND, job_id, status="queued", current=reason)
        database.update_preset_asset_candidate(
            candidate_id,
            status="queued",
            error=reason,
        )
        time.sleep(1)


def _release_gpu_slot() -> None:
    global _AI_ACTIVE
    with _GPU_CONDITION:
        _AI_ACTIVE = False
        _GPU_CONDITION.notify_all()


def _candidate_dir(preset_type: str, preset_id: str, candidate_id: int) -> Path:
    path = (
        Path(config.PRESET_ASSET_ROOT)
        / "candidates"
        / preset_type
        / preset_id
        / str(candidate_id)
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _expansion_inpaint_mask(
    preset: dict[str, Any],
    width: int,
    height: int,
) -> str:
    target = str(preset.get("category") or "")
    target_key = "vaginal" if target == "阴道扩张" else "anal"
    polygon = _EXPANSION_PELVIS_MASK_POLYGONS.get(
        target, _EXPANSION_PELVIS_MASK_POLYGONS["阴道扩张"]
    )
    mask_dir = Path(config.PRESET_ASSET_ROOT) / "masks" / "expansion"
    mask_dir.mkdir(parents=True, exist_ok=True)
    mask_path = mask_dir / f"{target_key}_{width}x{height}.png"
    if not mask_path.is_file():
        mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask)
        draw.polygon(
            [
                (round(x * width), round(y * height))
                for x, y in polygon
            ],
            fill=255,
        )
        mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2, width // 64)))
        mask.convert("RGB").save(mask_path, format="PNG")
    input_dir = Path(config.COMFY_INPUT_DIR)
    input_dir.mkdir(parents=True, exist_ok=True)
    target_path = input_dir / f"preset_asset_{target_key}_mask_{width}x{height}.png"
    if (
        not target_path.is_file()
        or target_path.stat().st_size != mask_path.stat().st_size
    ):
        shutil.copyfile(mask_path, target_path)
    return target_path.name


def _job_cancelled(job_id: str) -> bool:
    job = task_registry.get(JOB_KIND, job_id)
    return bool(
        job
        and (
            job.get("stop_requested")
            or job.get("status") in {"cancel_requested", "cancelled", "stopped"}
        )
    )


def _mark_job_cancelled(
    job_id: str,
    current_item: dict[str, Any] | None = None,
    *,
    clear_pending: bool = False,
) -> None:
    for item in database.list_preset_asset_job_items(job_id):
        if item.get("status") not in ACTIVE_AI_STATUSES:
            continue
        database.update_preset_asset_job_item(
            job_id,
            int(item["item_index"]),
            status=(
                "cancel_requested"
                if item.get("status") == "running"
                else "cancelled"
            ),
            error="已取消",
        )
    for candidate in database.list_preset_asset_candidates_by_job(job_id):
        if candidate.get("status") in ACTIVE_AI_STATUSES:
            database.update_preset_asset_candidate(
                int(candidate["id"]),
                status=(
                    "cancel_requested"
                    if candidate.get("status") == "running"
                    else "cancelled"
                ),
                error="已取消",
            )
    task_registry.update(
        JOB_KIND,
        job_id,
        status="cancel_requested",
        current="正在停止",
    )
    if clear_pending:
        task_registry.finish(JOB_KIND, job_id, "cancelled", "用户取消")
    if current_item:
        database.add_preset_asset_audit(
            "job_item_cancelled",
            str(current_item["preset_type"]),
            str(current_item["preset_id"]),
            job_id=job_id,
            detail={"item_index": int(current_item["item_index"])},
        )


def _finish_job_from_items(job_id: str) -> None:
    job = task_registry.get(JOB_KIND, job_id)
    if job and job.get("status") in {"cancelled", "stopped"}:
        return
    items = database.list_preset_asset_job_items(job_id)
    if any(item.get("status") == "cancelled" for item in items):
        task_registry.finish(JOB_KIND, job_id, "cancelled", "用户取消")
        return
    failed = [item for item in items if item.get("status") == "failed"]
    if failed:
        task_registry.finish(
            JOB_KIND,
            job_id,
            "error",
            f"{len(failed)} 个任务项失败",
        )
        return
    interrupted = [
        item for item in items if item.get("status") == "interrupted"
    ]
    if interrupted:
        task_registry.finish(
            JOB_KIND,
            job_id,
            "interrupted",
            f"{len(interrupted)} 个任务项因重启中断，可手动重试",
        )
        return
    if items and all(item.get("status") == "done" for item in items):
        task_registry.finish(JOB_KIND, job_id, "done")
        return
    task_registry.finish(JOB_KIND, job_id, "error", "任务未完成")


def cancel_job(job_id: str) -> dict[str, Any]:
    """Request cancellation and interrupt the active local ComfyUI prompt."""
    job = task_registry.get(JOB_KIND, job_id)
    if not job:
        raise asset_service.PresetAssetError("任务不存在", status_code=404)
    if job.get("status") in task_registry.TERMINAL_STATUSES:
        return job_status(job_id)
    task_registry.update(
        JOB_KIND,
        job_id,
        stop_requested=True,
        status="cancel_requested",
        current="正在停止",
    )
    _mark_job_cancelled(job_id)
    with _GPU_CONDITION:
        active = _AI_ACTIVE
    if active:
        _interrupt_comfy()
    database.add_preset_asset_audit(
        "job_cancel_requested",
        job_id=job_id,
    )
    return job_status(job_id)


def _interrupt_comfy() -> None:
    try:
        import requests

        requests.post(
            config.COMFY_URL + "/interrupt",
            json={"client_id": ""},
            timeout=5,
        )
    except Exception:
        pass


def retry_failed_job(
    job_id: str,
    item_indexes: set[int] | None = None,
) -> dict[str, Any]:
    """Retry recoverable items from their saved parameter snapshots."""
    job = task_registry.get(JOB_KIND, job_id)
    if not job:
        raise asset_service.PresetAssetError("任务不存在", status_code=404)
    items = database.list_preset_asset_job_items(job_id)
    with _JOB_THREADS_LOCK:
        thread = _JOB_THREADS.get(job_id)
        if (
            job.get("status") in ACTIVE_AI_STATUSES
            or (thread and thread.is_alive())
            or any(
                item.get("status") in ACTIVE_AI_STATUSES for item in items
            )
        ):
            raise asset_service.PresetAssetError(
                "任务仍在运行，暂时不能重试失败项",
                status_code=409,
            )
    if item_indexes is None:
        retry_items = [
            item
            for item in items
            if _item_retry_contract(item)[0]
        ]
        missing_indexes: set[int] = set()
        invalid_items: list[dict[str, Any]] = []
    else:
        requested_indexes = {int(index) for index in item_indexes}
        items_by_index = {
            int(item["item_index"]): item
            for item in items
        }
        missing_indexes = requested_indexes - set(items_by_index)
        if missing_indexes:
            raise asset_service.PresetAssetError(
                "任务项不存在",
                status_code=404,
            )
        retry_items = [
            items_by_index[index]
            for index in sorted(requested_indexes)
        ]
        invalid_items = [
            item
            for item in retry_items
            if not _item_retry_contract(item)[0]
        ]
        if invalid_items:
            raise asset_service.PresetAssetError(
                "任务项当前不可重试",
                status_code=409,
            )
    if not retry_items:
        raise asset_service.PresetAssetError("没有可重试的失败项", status_code=409)
    retry_indexes = {int(item["item_index"]) for item in retry_items}
    done = sum(
        int(item.get("params", {}).get("candidate_count") or 1)
        for item in items
        if item.get("status") == "done"
    )
    total = sum(
        int(item.get("params", {}).get("candidate_count") or 1)
        for item in items
    )
    for item in retry_items:
        database.update_preset_asset_job_item(
            job_id,
            int(item["item_index"]),
            status="queued",
            candidate_id=None,
            error=None,
            last_error_code=None,
            next_retry_at=None,
            retry_backoff_seconds=0,
        )
    task_registry.update(
        JOB_KIND,
        job_id,
        status="queued",
        total=total,
        done=done,
        current="等待重试",
        error=None,
        stop_requested=False,
        finished_at=None,
    )
    _start_job_thread(job_id, retry_indexes)
    return job_status(job_id)


def _candidate_job_item_index(candidate: dict[str, Any]) -> int | None:
    params = candidate.get("params")
    if not isinstance(params, dict):
        return None
    raw_index = params.get(asset_service.CANDIDATE_JOB_ITEM_INDEX_PARAM)
    if isinstance(raw_index, bool) or raw_index is None:
        return None
    try:
        item_index = int(raw_index)
    except (TypeError, ValueError):
        return None
    return item_index if item_index >= 0 else None


def _candidate_breakdown(candidates: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "candidate_count": len(candidates),
        "ready_count": sum(
            1 for candidate in candidates if candidate.get("status") == "ready"
        ),
        "adopted_count": sum(
            1 for candidate in candidates if candidate.get("status") == "adopted"
        ),
        "active_count": sum(
            1
            for candidate in candidates
            if candidate.get("status")
            in {"queued", "preparing", "running", "cancel_requested"}
        ),
        "failed_count": sum(
            1
            for candidate in candidates
            if candidate.get("status") in {"failed", "interrupted"}
        ),
        "cancelled_count": sum(
            1
            for candidate in candidates
            if candidate.get("status") in {"cancelled", "stopped"}
        ),
    }


def _summarize_job_item_candidates(
    items: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> tuple[dict[int, dict[str, int]], bool]:
    """Assign candidates to items without merging duplicate preset entries."""
    item_indexes = {int(item["item_index"]) for item in items}
    assignments: dict[int, list[dict[str, Any]]] = {
        item_index: [] for item_index in item_indexes
    }
    assigned_candidate_ids: set[int] = set()
    reliable = True

    def assign(candidate: dict[str, Any], item_index: int) -> None:
        candidate_id = int(candidate["id"])
        if candidate_id in assigned_candidate_ids:
            return
        assignments[item_index].append(candidate)
        assigned_candidate_ids.add(candidate_id)

    # New candidates carry their exact task-item index in params_json.
    for candidate in candidates:
        item_index = _candidate_job_item_index(candidate)
        if item_index is None:
            continue
        if item_index not in assignments:
            reliable = False
            continue
        assign(candidate, item_index)

    # Historical jobs can still use the item's last candidate as a unique anchor.
    anchors: dict[int, list[int]] = {}
    for item in items:
        raw_candidate_id = item.get("candidate_id")
        if raw_candidate_id is None:
            continue
        try:
            candidate_id = int(raw_candidate_id)
        except (TypeError, ValueError):
            continue
        anchors.setdefault(candidate_id, []).append(int(item["item_index"]))
    for candidate in candidates:
        candidate_id = int(candidate["id"])
        if candidate_id in assigned_candidate_ids:
            continue
        matched_indexes = anchors.get(candidate_id, [])
        if len(matched_indexes) == 1:
            assign(candidate, matched_indexes[0])
        elif len(matched_indexes) > 1:
            reliable = False

    items_by_preset: dict[tuple[str, str], list[int]] = {}
    for item in items:
        key = (str(item.get("preset_type") or ""), str(item.get("preset_id") or ""))
        items_by_preset.setdefault(key, []).append(int(item["item_index"]))

    for candidate in candidates:
        candidate_id = int(candidate["id"])
        if candidate_id in assigned_candidate_ids:
            continue
        key = (
            str(candidate.get("preset_type") or ""),
            str(candidate.get("preset_id") or ""),
        )
        matched_indexes = items_by_preset.get(key, [])
        if len(matched_indexes) == 1:
            assign(candidate, matched_indexes[0])

    # Duplicate legacy presets cannot be attributed exactly. Keep the old
    # preset-level fallback for display, but flag that the summary is ambiguous.
    for candidate in candidates:
        if int(candidate["id"]) in assigned_candidate_ids:
            continue
        reliable = False
        key = (
            str(candidate.get("preset_type") or ""),
            str(candidate.get("preset_id") or ""),
        )
        for item_index in items_by_preset.get(key, []):
            assignments[item_index].append(candidate)

    return (
        {
            item_index: _candidate_breakdown(item_candidates)
            for item_index, item_candidates in assignments.items()
        },
        reliable,
    )


def job_status(job_id: str) -> dict[str, Any]:
    """Return a stable workshop job payload with per-item state."""
    job = task_registry.get(JOB_KIND, job_id) or database.get_background_job(job_id)
    if not job or job.get("kind") != JOB_KIND:
        raise asset_service.PresetAssetError("任务不存在", status_code=404)
    items = database.list_preset_asset_job_items(job_id)
    raw_candidates = database.list_preset_asset_candidates_by_job(job_id)
    item_candidate_summaries, summary_reliable = _summarize_job_item_candidates(
        items,
        raw_candidates,
    )
    active_versions: dict[tuple[str, str], dict[str, Any]] = {}
    for version in database.list_active_preset_asset_versions(
        sorted(
            {
                str(item.get("preset_type") or "")
                for item in items
                if item.get("preset_type")
            }
        )
    ):
        key = (str(version["preset_type"]), str(version["preset_id"]))
        active_versions.setdefault(key, version)
    for item in items:
        item["preset_label"] = asset_service.preset_label(
            str(item.get("preset_type") or ""),
            str(item.get("preset_id") or ""),
        )
        item.update(
            item_candidate_summaries.get(
                int(item["item_index"]),
                _candidate_breakdown([]),
            )
        )
        active_version = active_versions.get(
            (
                str(item.get("preset_type") or ""),
                str(item.get("preset_id") or ""),
            )
        )
        item["active_version"] = (
            asset_service.version_payload(active_version)
            if active_version
            else None
        )
        item["candidate_summary_reliable"] = summary_reliable
        item["candidate_summary_source"] = (
            "job_item" if summary_reliable else "legacy_preset_fallback"
        )
        retryable, user_action = _item_retry_contract(item)
        item["retryable"] = retryable
        item["user_action"] = user_action
    candidates = [
        asset_service.candidate_payload(item)
        for item in raw_candidates
    ]
    return {
        **job,
        "items": items,
        "candidates": candidates,
    }
