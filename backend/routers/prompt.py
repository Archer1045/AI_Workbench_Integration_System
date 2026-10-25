"""提示词 Agent 接口：图片反推与自然语言转提示词。"""
from __future__ import annotations

import base64
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from fastapi import APIRouter, Body, HTTPException, Query

import action_composer
import database
import content_filter
import config
import clothing_presets
import body_modification_presets
import expression_presets
import expansion_presets
import llm
import preset_asset_service
import preset_composer
import preset_registry
import preset_taxonomy
import pose_accuracy
import pose_prompts
import prompt_agent
import prompt_checker
import prompt_document
import scene_presets
import tag_category
import task_state
import toy_presets
import water_presets
from routers.chat import translate_text
from routers.settings_router import content_restriction_enabled, prompt_semantic_check_enabled
from web_tools import WebToolsError, get_web_tools_service

router = APIRouter()

AI_PRODUCT_DIR = config.AI_PRODUCT_DIR
_CLOTHING_PRESETS_BY_ID = {
    str(item["id"]): item for item in clothing_presets.CLOTHING_PRESETS
}


def _appearance_with_outfit(item: dict) -> dict:
    result = dict(item)
    outfit = _CLOTHING_PRESETS_BY_ID.get(str(result.get("outfit_id") or ""))
    result["outfit_name"] = str(outfit["label"]) if outfit else ""
    return result

_TRACKING_QUERY_KEYS = {
    "bst",
    "frommodule",
    "lemmafrom",
    "lemmaidfrom",
    "spm",
    "utm_campaign",
    "utm_medium",
    "utm_source",
    "utm_term",
}


def _setting_result_key(url: str) -> str:
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_QUERY_KEYS
    ]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            "",
            urlencode(sorted(query)),
            "",
        )
    )

SEMANTIC_SYSTEM = (
    "你是绘画提示词语义一致性检查器。"
    "只检查本地规则难以发现的隐性语义冲突（例如环境/视角/情绪互相矛盾、人物关系暗示与人数不一致、明显自相矛盾的描述）。"
    "不要审查内容尺度或拒绝任何主题，不要提供修改建议以外的道德评价。"
    '只输出 JSON 数组，每项 {"type":"warning|error","message":"简短中文说明"}，没有则输出 []。'
)


def _ensure_llm_resource_free() -> None:
    """重任务运行时直接阻止提示词/LLM 类同步操作（不做排队）。"""
    tasks = task_state.running_tasks()
    if not tasks:
        return
    labels = "、".join(task["label"] for task in tasks)
    raise HTTPException(
        status_code=409,
        detail=f"检测到资源占用（{labels}），绘画/训练运行期间已直接阻止提示词与 LLM 类操作，请等待任务结束再试",
    )


def _llm_http_error(exc: Exception, operation: str) -> HTTPException:
    """把 LLM 调用异常映射成可读 HTTP 错误。"""
    if isinstance(exc, requests.exceptions.Timeout):
        return HTTPException(status_code=504, detail=f"{operation}超时：模型响应时间过长，请稍后重试或减少输入内容")
    if isinstance(exc, requests.exceptions.ConnectionError):
        return HTTPException(status_code=503, detail=f"{operation}失败：Ollama 未连接，请先启动 Ollama 服务")
    text = str(exc)
    if "JSON" in text or "解析失败" in text or "不是有效 JSON" in text or "分组" in text:
        return HTTPException(
            status_code=422,
            detail=(
                f"{operation}失败：模型输出不是有效 JSON 或内容被截断。"
                "请减少标签/描述数量后重试；仍失败可重启 Ollama 或切换模型"
            ),
        )
    return HTTPException(status_code=500, detail=f"{operation}失败：{text}")


def parse_semantic_items(text: str) -> list[dict]:
    """把 LLM 返回文本解析为规范化的语义问题列表（容错、最多 5 条）。"""
    try:
        data = prompt_agent.extract_json_payload(text, "array")
    except Exception:
        return []
    issues = []
    for item in data[:5]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").lower()
        message = str(item.get("message") or "").strip()
        if kind in ("error", "warning") and message:
            issues.append({"type": kind, "message": message})
    return issues


@router.post("/api/prompt/validate")
def validate_prompt(payload: dict = Body(...)):
    """校验绘画提示词：重复、冲突、语法与人数一致性。"""
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    result = prompt_checker.validate_prompt(prompt, str(payload.get("negative_prompt") or ""))
    if prompt_semantic_check_enabled():
        for item in _semantic_issues(prompt):
            kind = item.get("type")
            if kind in ("error", "warning") and item.get("message"):
                result.setdefault(f"{kind}s", []).append({**item, "source": "ai"})
    return result


def _semantic_issues(prompt: str) -> list[dict]:
    """调用本地大模型做隐性语义冲突检查；解析失败返回空。"""
    if not llm.is_available():
        return []
    try:
        result = llm.chat(
            [
                {"role": "system", "content": SEMANTIC_SYSTEM},
                {"role": "user", "content": f"提示词：{prompt}"},
            ],
            max_tokens=400,
            temperature=0.1,
            think=False,
            model=config.R18_MODEL if content_filter.is_nsfw(prompt) else None,
        )
    except Exception:
        return []
    return parse_semantic_items(result)

SPLIT_CATEGORIES = list(tag_category.CATEGORIES)
SPLIT_SYSTEM = (
    "你是绘图提示词分类助手。把英文标签按类别分组，只输出 JSON，不要解释。"
    '格式：{"character":[],"action":[],"background":[],"style":[],"other":[]}。'
)


def _split_tags_with_llm(tags: list[str]) -> dict[str, list[str]]:
    """调用大模型分类，解析失败时返回空字典触发降级。"""
    if not llm.is_available():
        return {}
    for _ in range(2):
        try:
            result = llm.chat(
                [
                    {"role": "system", "content": SPLIT_SYSTEM},
                    {"role": "user", "content": "标签列表：\n" + "\n".join(tags)},
                ],
                max_tokens=800,
                temperature=0.1,
                think=False,
            )
            data = prompt_agent.extract_json_payload(result, "object")
            return {
                category: [str(item) for item in data.get(category, []) if str(item).strip()]
                for category in SPLIT_CATEGORIES
            }
        except Exception:
            continue
    return {}


def _split_unresolved_with_llm(unresolved: list[str]) -> dict[str, list[str]]:
    """LLM fallback for the small set of tags dictionary/vector cannot decide."""
    groups = _split_tags_with_llm(unresolved)
    if not any(groups.values()):
        return {}
    result = {category: [] for category in SPLIT_CATEGORIES}
    remaining = list(unresolved)
    for category in SPLIT_CATEGORIES:
        for item in groups.get(category, []):
            item_key = tag_category.normalize_tag(item)
            if not item_key:
                continue
            for index, original in enumerate(remaining):
                if tag_category.normalize_tag(original) == item_key:
                    result[category].append(original)
                    remaining.pop(index)
                    break
    return result


def _split_tags(tags: list[str]) -> dict[str, list[str]]:
    groups = {category: [] for category in SPLIT_CATEGORIES}
    unresolved: list[str] = []
    for tag in tags:
        category = tag_category.dictionary_category(tag) or tag_category.vector_category(tag)
        if category in groups:
            groups[category].append(tag)
        else:
            unresolved.append(tag)
    if unresolved:
        llm_groups = _split_unresolved_with_llm(unresolved)
        if any(llm_groups.values()):
            assignments = {
                tag_category.normalize_tag(original): category
                for category in SPLIT_CATEGORIES
                for original in llm_groups.get(category, [])
            }
            for tag in unresolved:
                category = assignments.get(tag_category.normalize_tag(tag))
                if category in groups:
                    groups[category].append(tag)
                else:
                    groups["other"].append(tag)
        else:
            groups["other"].extend(unresolved)
    return groups


@router.post("/api/prompt/from-text")
def from_text(payload: dict = Body(...)):
    """自然语言转英文绘画提示词，并记录行为。"""
    text = prompt_agent.clean_prompt_text(str(payload.get("text") or ""))
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    if not prompt_agent.is_available():
        raise HTTPException(status_code=503, detail="Ollama 未启动")
    if content_filter.is_hard_blocked(text):
        raise HTTPException(status_code=403, detail="该内容被禁止生成")
    if content_restriction_enabled() and content_filter.is_nsfw(text):
        raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
    _ensure_llm_resource_free()
    started_at = database.now_iso()
    started_ts = time.time()
    try:
        prompt = prompt_agent.text_to_prompt(text)
        if content_filter.is_hard_blocked(prompt):
            raise HTTPException(status_code=403, detail="该内容被禁止生成")
        if content_restriction_enabled() and content_filter.is_nsfw(prompt):
            raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
        database.insert_prompt_record(
            "text", text, None, None, prompt, prompt_agent.TEXT_MODEL, "success",
            started_at, database.now_iso(), round(time.time() - started_ts, 2),
        )
        return {"prompt": prompt, "prompt_translation": translate_text(prompt), "source_text": text}
    except Exception as exc:  # noqa: BLE001
        database.insert_prompt_record(
            "text", text, None, None, None, prompt_agent.TEXT_MODEL, "error",
            started_at, database.now_iso(), round(time.time() - started_ts, 2),
        )
        raise _llm_http_error(exc, "提示词生成")


@router.post("/api/prompt/from-image")
def from_image(payload: dict = Body(...)):
    """图片反推提示词：保存原图、识别描述、生成英文提示词，并记录行为。"""
    data = str(payload.get("image_base64") or "")
    filename = str(payload.get("filename") or "image.png")
    if "," in data:
        data = data.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"图片编码无效: {exc}") from exc
    if not image_bytes:
        raise HTTPException(status_code=400, detail="图片为空")
    # 默认仍是 vlm：不传 mode 的既有调用方行为不变；前端反推面板会显式传 hybrid（默认档）。
    mode = str(payload.get("mode") or "vlm").strip().lower()
    if mode not in ("vlm", "wd14", "hybrid"):
        raise HTTPException(status_code=400, detail="mode 必须是 vlm、wd14 或 hybrid")
    try:
        wd14_threshold = float(
            payload.get("threshold", config.TRAIN_DEFAULT_CAPTION_THRESHOLD)
        )
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="WD14 阈值格式不正确") from None
    if not config.TRAIN_CAPTION_THRESHOLD_MIN <= wd14_threshold <= config.TRAIN_CAPTION_THRESHOLD_MAX:
        raise HTTPException(
            status_code=400,
            detail=(
                f"WD14 阈值必须在 {config.TRAIN_CAPTION_THRESHOLD_MIN:g}-"
                f"{config.TRAIN_CAPTION_THRESHOLD_MAX:g} 之间"
            ),
        )
    # wd14 模式只跑本地 onnx 分类器：不需要 Ollama，也不受重任务占用的限制。
    if mode == "wd14":
        if not prompt_agent.wd14_available():
            raise HTTPException(status_code=503, detail="WD14 模型文件缺失，请检查 WD14_MODEL_DIR")
    else:
        if not prompt_agent.is_available():
            raise HTTPException(status_code=503, detail="Ollama 未启动")
        _ensure_llm_resource_free()

    # 上传图片保存到 prompt_inputs，方便后续追溯
    prompt_inputs = AI_PRODUCT_DIR / "prompt_inputs"
    prompt_inputs.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    saved_image = prompt_inputs / f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    saved_image.write_bytes(image_bytes)

    started_at = database.now_iso()
    started_ts = time.time()
    model_name = prompt_agent.vlm_model()
    try:
        result = prompt_agent.image_to_prompt(
            image_bytes, filename, mode=mode, wd14_threshold=wd14_threshold
        )
        description = result.get("description") or ""
        prompt = result.get("prompt") or ""
        analysis = result.get("analysis") or {}
        model_name = str(analysis.get("model_label") or model_name)
        if content_filter.is_hard_blocked(description) or content_filter.is_hard_blocked(prompt):
            raise HTTPException(status_code=403, detail="该内容被禁止生成")
        if content_restriction_enabled() and (content_filter.is_nsfw(description) or content_filter.is_nsfw(prompt)):
            raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
        database.insert_prompt_record(
            "image", None, str(saved_image), result.get("description"),
            result.get("prompt"), model_name, "success",
            started_at, database.now_iso(), round(time.time() - started_ts, 2),
        )
        result["prompt_translation"] = translate_text(prompt)
        return result
    except Exception as exc:  # noqa: BLE001
        database.insert_prompt_record(
            "image", None, str(saved_image), None, None, model_name, "error",
            started_at, database.now_iso(), round(time.time() - started_ts, 2),
        )
        raise _llm_http_error(exc, "图片反推") from exc


@router.post("/api/prompt-agent/split")
def split_prompt_set(payload: dict = Body(...)):
    """把提示词集智能拆分为人物/动作/背景/画风/其他。"""
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    tags = [tag.strip() for tag in re.split(r"[,\n]", text) if tag.strip()]
    if not tags:
        raise HTTPException(status_code=400, detail="没有可拆分的标签")
    _ensure_llm_resource_free()
    if bool(payload.get("role_aware")) and payload.get("description"):
        try:
            groups = prompt_agent.split_prompt_role_aware(str(payload.get("description")), tags)
        except Exception as exc:  # noqa: BLE001
            raise _llm_http_error(exc, "角色感知拆分") from exc
        return {"groups": groups}
    return {"groups": _split_tags(tags)}


def _preset_rating(preset: dict) -> str:
    return str(preset.get("rating") or ("R18" if preset.get("nsfw") else "普通"))


def _hidden_by_restriction(preset: dict, restriction: bool) -> bool:
    return restriction and (_preset_rating(preset) == "R18" or bool(preset.get("nsfw")))


def _preset_image_url(preset: dict, directory: str, extension: str) -> str | None:
    image_path = (
        config.PROJECT_ROOT
        / "studio"
        / "frontend"
        / "public"
        / directory
        / f"{preset['id']}.{extension}"
    )
    if not image_path.is_file():
        return None
    return f"/{directory}/{preset['id']}.{extension}"


def _registry_items(kind: str, restriction: bool) -> list[dict]:
    """Load one preset family from the central registry and apply hidden rules."""
    definition = preset_registry.PRESET_KIND_BY_KEY[kind]
    return [
        preset
        for preset in preset_taxonomy.enrich_presets(
            definition.taxonomy_key,
            definition.list_loader(),
        )
        if not _hidden_by_restriction(preset, restriction)
    ]


def _registry_image_url(preset: dict, kind: str) -> str | None:
    definition = preset_registry.PRESET_KIND_BY_KEY[kind]
    return _preset_image_url(
        preset,
        definition.image_directory,
        definition.image_extension,
    )


def _pose_items(restriction: bool) -> list[dict]:
    """Return normalized pose items with derived people/orientation fields."""
    solo_ids = {"lying_back", "lying_side", "kneeling", "standing"}
    items: list[dict] = []
    for preset in _registry_items("pose", restriction):
        text = " ".join(str(tag) for tag in preset.get("tags") or []).lower()
        category = str(preset.get("category") or "")
        lesbian = category == "女同" or "lesbian" in text
        group = (
            category in ("3P", "群交")
            or "group sex" in text
            or "threesome" in text
            or "orgy" in text
            or "gangbang" in text
        )
        people = str(preset.get("people") or "")
        if people not in ("单人", "双人", "多人"):
            people = "多人" if group else ("单人" if str(preset.get("id") or "") in solo_ids or "solo" in text else "双人")
        orientation = str(preset.get("orientation") or "")
        if not orientation:
            if people == "单人":
                orientation = "单人"
            elif lesbian:
                orientation = "女女"
            elif people == "多人":
                orientation = "多人"
            else:
                orientation = "男女"
        image = _registry_image_url(preset, "pose")
        audit = pose_accuracy.audit_for(
            str(preset.get("id") or ""),
            has_image=bool(image),
        )
        items.append(
            {
                **preset,
                "orientation": orientation,
                "people": people,
                "core_tags": pose_prompts.pose_core_tags(preset),
                "core_prompt": pose_prompts.pose_prompt(preset, "core"),
                "full_prompt": pose_prompts.pose_prompt(preset, "full"),
                "accuracy_status": audit["accuracy_status"],
                "accuracy_notes": audit["accuracy_notes"],
                "accuracy_audit_version": pose_accuracy.AUDIT_VERSION,
                "has_image": bool(image),
                "image": image,
            }
        )
    return items


def _clothing_image_url(preset: dict) -> str | None:
    return _preset_image_url(preset, "clothing-presets", "webp")


def _clothing_items(restriction: bool) -> list[dict]:
    items = []
    for preset in _registry_items("clothing", restriction):
        image = _clothing_image_url(preset)
        items.append(
            {
                **preset,
                "has_image": bool(image),
                "image": image,
                "rating": _preset_rating(preset),
                "tag_count": len(preset.get("tags") or []),
            }
        )
    return items


def _scene_items(restriction: bool) -> list[dict]:
    return [
        {
            **preset,
            "rating": _preset_rating(preset),
            "has_image": bool(image := _registry_image_url(preset, "scene")),
            "image": image,
        }
        for preset in _registry_items("scene", restriction)
    ]


def _body_modification_items(restriction: bool) -> list[dict]:
    return [
        {
            **preset,
            "rating": _preset_rating(preset),
            "has_image": bool(
                image := _registry_image_url(preset, "body")
            ),
            "image": image,
        }
        for preset in _registry_items("body", restriction)
    ]


def _toy_items(restriction: bool) -> list[dict]:
    return [
        {
            **preset,
            "rating": _preset_rating(preset),
            "has_image": bool(image := _registry_image_url(preset, "toy")),
            "image": image,
        }
        for preset in _registry_items("toy", restriction)
    ]


def _expansion_items(restriction: bool) -> list[dict]:
    return [
        {
            **preset,
            "rating": _preset_rating(preset),
            "has_image": bool(image := _registry_image_url(preset, "expansion")),
            "image": image,
        }
        for preset in _registry_items("expansion", restriction)
    ]


def _expression_items(restriction: bool) -> list[dict]:
    return [
        {
            **preset,
            "rating": _preset_rating(preset),
        }
        for preset in expression_presets.EXPRESSION_PRESETS
        if not _hidden_by_restriction(preset, restriction)
    ]


def _water_items(restriction: bool) -> list[dict]:
    return [
        {
            **preset,
            "rating": _preset_rating(preset),
        }
        for preset in water_presets.WATER_PRESETS
        if not _hidden_by_restriction(preset, restriction)
    ]


@router.get("/api/preset-types")
def preset_types() -> dict:
    """Return frontend metadata for every built-in preset family."""
    return {
        "items": preset_registry.list_metadata(),
        "composition": {
            "max_items": config.PRESET_COMPOSITION_MAX_ITEMS,
        },
    }


@router.get("/api/prompt-agent/expression-presets")
def expression_presets_api(
    keyword: str = "",
    category: str = "",
    intensity: str = "",
    character_scope: str = "",
) -> dict:
    """Return the built-in expression library with lightweight filters."""
    query = keyword.strip().lower()
    items: list[dict] = []
    for preset in _expression_items(content_restriction_enabled()):
        scope_values = [
            str(value) for value in preset.get("character_scope") or []
        ]
        if category and preset.get("category") != category:
            continue
        if intensity and preset.get("intensity") != intensity:
            continue
        if character_scope and character_scope not in scope_values:
            continue
        haystack = " ".join(
            [
                str(preset.get("id") or ""),
                str(preset.get("label") or ""),
                str(preset.get("translation") or ""),
                str(preset.get("category") or ""),
                str(preset.get("intensity") or ""),
                *scope_values,
                *[str(value) for value in preset.get("aliases") or []],
                *[str(value) for value in preset.get("tags") or []],
            ]
        ).lower()
        if query and query not in haystack:
            continue
        items.append(preset)
    return {
        "items": items,
        "total": len(items),
        "schema_version": expression_presets.SCHEMA_VERSION,
        "categories": list(expression_presets.CATEGORIES),
        "intensities": list(expression_presets.INTENSITIES),
        "character_scopes": list(expression_presets.CHARACTER_SCOPES),
        "restricted": content_restriction_enabled(),
    }


@router.get("/api/prompt-agent/water-presets")
def water_presets_api(
    keyword: str = "",
    category: str = "",
    water_level: str = "",
    target: str = "",
) -> dict:
    """Return reusable water modifiers for existing pose/scene presets."""
    query = keyword.strip().lower()
    items: list[dict] = []
    for preset in _water_items(content_restriction_enabled()):
        if category and preset.get("category") != category:
            continue
        if water_level and preset.get("water_level") != water_level:
            continue
        if target and preset.get("target") != target:
            continue
        haystack = " ".join(
            [
                str(preset.get("id") or ""),
                str(preset.get("label") or ""),
                str(preset.get("translation") or ""),
                str(preset.get("category") or ""),
                str(preset.get("water_level") or ""),
                str(preset.get("target") or ""),
                *[str(value) for value in preset.get("tags") or []],
            ]
        ).lower()
        if query and query not in haystack:
            continue
        items.append(preset)
    return {
        "items": items,
        "total": len(items),
        "schema_version": water_presets.SCHEMA_VERSION,
        "categories": list(water_presets.CATEGORIES),
        "water_levels": list(water_presets.WATER_LEVELS),
        "targets": list(water_presets.TARGETS),
        "restricted": content_restriction_enabled(),
    }


@router.get("/api/runtime-config")
def get_runtime_config() -> dict:
    """Return centralized runtime defaults and service endpoints."""
    return config.runtime_config()


def _matches_keyword(preset: dict, keyword: str, extra: list[str] | None = None) -> bool:
    query = keyword.strip().lower()
    if not query:
        return True
    values = [
        str(preset.get("id") or ""),
        str(preset.get("label") or ""),
        str(preset.get("translation") or ""),
        str(preset.get("category") or ""),
        str(preset.get("category_group") or ""),
        str(preset.get("subcategory") or ""),
        str(preset.get("description") or ""),
        *[str(item) for item in preset.get("aliases") or []],
        *[str(item) for item in preset.get("tags") or []],
        *[str(item) for item in extra or []],
    ]
    return query in " ".join(values).lower()


@router.get("/api/prompt-agent/pose-presets")
def pose_presets(
    keyword: str = Query(""),
    category: str = Query(""),
    category_group: str = Query(""),
    subcategory: str = Query(""),
    rating: str = Query(""),
    people: str = Query(""),
    orientation: str = Query(""),
) -> dict:
    """返回体位/姿势预设，并附带取向/人数派生字段供前端筛选。"""
    restriction = content_restriction_enabled()
    items = []
    for preset in _pose_items(restriction):
        if rating and preset.get("rating") != rating:
            continue
        if people and preset.get("people") != people:
            continue
        if orientation and preset.get("orientation") != orientation:
            continue
        if not preset_taxonomy.matches_category(
            preset, category, category_group, subcategory
        ):
            continue
        if not _matches_keyword(preset, keyword):
            continue
        items.append(preset)
    return {
        "items": items,
        "total": len(items),
        "restricted": restriction,
        "categories": sorted(
            {str(item.get("category") or "") for item in _pose_items(restriction)}
        ),
        **preset_taxonomy.taxonomy_payload("pose"),
    }


@router.get("/api/prompt-agent/clothing-presets")
def clothing_presets_api(
    keyword: str = Query(""),
    category: str = Query(""),
    category_group: str = Query(""),
    subcategory: str = Query(""),
    gender: str = Query(""),
    part: str = Query(""),
    rating: str = Query(""),
    material: str = Query(""),
    layer_state: str = Query(""),
    intensity: str = Query(""),
) -> dict:
    """返回内置服装预设；内容限制开启时强制隐藏 R18 条目。"""
    restriction = content_restriction_enabled()
    items = _clothing_items(restriction)
    filtered = []
    for preset in items:
        if rating and preset.get("rating") != rating:
            continue
        if not preset_taxonomy.matches_category(
            preset, category, category_group, subcategory
        ):
            continue
        if gender and preset.get("gender") != gender:
            continue
        if part and preset.get("part") != part:
            continue
        if material and material not in (preset.get("materials") or []):
            continue
        if layer_state and preset.get("layer_state") != layer_state:
            continue
        if intensity and preset.get("intensity") != intensity:
            continue
        if not _matches_keyword(
            preset,
            keyword,
            [
                str(preset.get("gender") or ""),
                str(preset.get("part") or ""),
                *[str(item) for item in preset.get("materials") or []],
            ],
        ):
            continue
        filtered.append(preset)
    return {
        "items": filtered,
        "total": len(filtered),
        "restricted": restriction,
        "categories": list(clothing_presets.CATEGORIES),
        **preset_taxonomy.taxonomy_payload("clothing"),
        "genders": list(clothing_presets.GENDERS),
        "parts": list(clothing_presets.PARTS),
        "materials": list(clothing_presets.MATERIALS),
        "layer_states": list(clothing_presets.LAYER_STATES),
        "intensities": list(clothing_presets.INTENSITIES),
    }


@router.get("/api/prompt-agent/scene-presets")
def scene_presets_api(
    keyword: str = Query(""),
    category: str = Query(""),
    category_group: str = Query(""),
    subcategory: str = Query(""),
    rating: str = Query(""),
    intensity: str = Query(""),
    setting: str = Query(""),
    equipment: str = Query(""),
    orientation: str = Query(""),
    people: str = Query(""),
) -> dict:
    """返回静态场景预设；内容限制开启时隐藏 R18 条目。"""
    restriction = content_restriction_enabled()
    items = []
    for preset in _scene_items(restriction):
        if rating and preset.get("rating") != rating:
            continue
        if not preset_taxonomy.matches_category(
            preset, category, category_group, subcategory
        ):
            continue
        if intensity and preset.get("intensity") != intensity:
            continue
        if setting and preset.get("setting") != setting:
            continue
        if equipment and equipment not in (preset.get("equipment") or []):
            continue
        if orientation and preset.get("orientation") != orientation:
            continue
        if people and preset.get("people") != people:
            continue
        if not _matches_keyword(preset, keyword, list(preset.get("equipment") or [])):
            continue
        items.append(preset)
    return {
        "items": items,
        "total": len(items),
        "restricted": restriction,
        "categories": list(scene_presets.CATEGORIES),
        **preset_taxonomy.taxonomy_payload("scene"),
        "settings": list(scene_presets.SETTINGS),
        "equipment": list(scene_presets.EQUIPMENT),
        "orientations": list(scene_presets.ORIENTATIONS),
        "intensities": list(scene_presets.INTENSITIES),
    }


@router.get("/api/prompt-agent/body-modification-presets")
def body_modification_presets_api(
    keyword: str = Query(""),
    category: str = Query(""),
    category_group: str = Query(""),
    subcategory: str = Query(""),
    rating: str = Query(""),
    intensity: str = Query(""),
    modification_type: str = Query(""),
    location: str = Query(""),
) -> dict:
    """返回静态、装饰性身体改造预设。"""
    restriction = content_restriction_enabled()
    items = []
    for preset in _body_modification_items(restriction):
        if rating and preset.get("rating") != rating:
            continue
        if not preset_taxonomy.matches_category(
            preset, category, category_group, subcategory
        ):
            continue
        if intensity and preset.get("intensity") != intensity:
            continue
        if modification_type and preset.get("modification_type") != modification_type:
            continue
        if location and preset.get("location") != location:
            continue
        if not _matches_keyword(preset, keyword, [str(preset.get("location") or "")]):
            continue
        items.append(preset)
    return {
        "items": items,
        "total": len(items),
        "restricted": restriction,
        "categories": list(body_modification_presets.CATEGORIES),
        **preset_taxonomy.taxonomy_payload("body"),
        "modification_types": list(body_modification_presets.MODIFICATION_TYPES),
        "locations": list(body_modification_presets.LOCATIONS),
        "intensities": list(body_modification_presets.INTENSITIES),
    }


@router.get("/api/prompt-agent/toy-presets")
def toy_presets_api(
    keyword: str = Query(""),
    category: str = Query(""),
    category_group: str = Query(""),
    subcategory: str = Query(""),
    rating: str = Query(""),
    intensity: str = Query(""),
    form_factor: str = Query(""),
    material_appearance: str = Query(""),
) -> dict:
    """返回用于虚构组合的性玩具视觉预设。"""
    restriction = content_restriction_enabled()
    items = []
    for preset in _toy_items(restriction):
        if rating and preset.get("rating") != rating:
            continue
        if not preset_taxonomy.matches_category(
            preset, category, category_group, subcategory
        ):
            continue
        if intensity and preset.get("intensity") != intensity:
            continue
        if form_factor and preset.get("form_factor") != form_factor:
            continue
        if (
            material_appearance
            and preset.get("material_appearance") != material_appearance
        ):
            continue
        if not _matches_keyword(
            preset,
            keyword,
            [
                str(preset.get("form_factor") or ""),
                str(preset.get("material_appearance") or ""),
            ],
        ):
            continue
        items.append(preset)
    return {
        "items": items,
        "total": len(items),
        "restricted": restriction,
        "categories": list(toy_presets.CATEGORIES),
        **preset_taxonomy.taxonomy_payload("toy"),
        "form_factors": list(toy_presets.FORM_FACTORS),
        "material_appearances": list(toy_presets.MATERIAL_APPEARANCES),
        "intensities": list(toy_presets.INTENSITIES),
    }


@router.get("/api/prompt-agent/expansion-presets")
def expansion_presets_api(
    keyword: str = Query(""),
    category: str = Query(""),
    category_group: str = Query(""),
    subcategory: str = Query(""),
    rating: str = Query(""),
    intensity: str = Query(""),
    state: str = Query(""),
) -> dict:
    """返回非执行性的虚构扩张状态预设。"""
    restriction = content_restriction_enabled()
    items = []
    for preset in _expansion_items(restriction):
        if rating and preset.get("rating") != rating:
            continue
        if not preset_taxonomy.matches_category(
            preset, category, category_group, subcategory
        ):
            continue
        if intensity and preset.get("intensity") != intensity:
            continue
        if state and preset.get("state") != state:
            continue
        if not _matches_keyword(
            preset,
            keyword,
            [
                str(preset.get("state") or ""),
                str((preset.get("visual_material") or {}).get("label") or ""),
            ],
        ):
            continue
        items.append(preset)
    return {
        "items": items,
        "total": len(items),
        "restricted": restriction,
        "categories": list(expansion_presets.CATEGORIES),
        **preset_taxonomy.taxonomy_payload("expansion"),
        "states": list(expansion_presets.STATES),
        "intensities": list(expansion_presets.INTENSITIES),
    }


@router.get("/api/prompt-agent/preset-catalog")
def preset_catalog() -> dict:
    """返回组合器需要的完整可见预设目录。"""
    restriction = content_restriction_enabled()
    return {
        "restricted": restriction,
        "poses": _pose_items(restriction),
        "clothing": _clothing_items(restriction),
        "scenes": _scene_items(restriction),
        "expressions": _expression_items(restriction),
        "water": _water_items(restriction),
        "body_modifications": _body_modification_items(restriction),
        "expansions": _expansion_items(restriction),
        "toys": _toy_items(restriction),
    }


@router.post("/api/prompt-agent/compose-presets")
def compose_presets_api(payload: dict = Body(...)) -> dict:
    """仅按预设 ID、角色范围和颜色槽生成最终提示词。"""
    try:
        return preset_composer.compose_presets(
            payload,
            restriction_enabled=content_restriction_enabled(),
        )
    except preset_composer.ComposeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/api/prompt-agent/resolve-prompt-document")
def resolve_prompt_document(payload: dict = Body(...)) -> dict:
    """把结构化文档解析为最终正负提示词，并在后端复核内容限制。"""
    document = payload.get("document") if "document" in payload else payload
    try:
        return prompt_document.resolve_document(
            document,
            restriction_enabled=content_restriction_enabled(),
        )
    except prompt_document.PromptDocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/api/prompt-agent/normalize-prompt-document")
def normalize_prompt_document(payload: dict = Body(...)) -> dict:
    """把结构化文档补全，或把自由文本转换为可继续编辑的草稿。"""
    if isinstance(payload.get("document"), dict):
        return {"document": prompt_document.normalize_document(payload["document"])}
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 或 document 不能为空")
    document = prompt_document.normalize_legacy_prompt(
        text,
        str(payload.get("negative_prompt") or ""),
    )
    return {"document": document}


@router.get("/api/prompt-agent/action-composer")
def action_composer_catalog() -> dict:
    """Return options for the first-version Action Composition workspace."""
    return action_composer.catalog()


@router.post("/api/prompt-agent/compile-action-recipe")
def compile_action_recipe(payload: dict = Body(...)) -> dict:
    """Validate an action recipe and compile deterministic prompt tags."""
    return action_composer.compile_recipe(payload)


def _validate_appearance_preset_payload(payload: dict, *, partial: bool = False) -> dict:
    name = str(payload.get("name") or "").strip()
    work = str(payload.get("work") or "").strip()
    category = str(payload.get("category") or "自由备注").strip()
    if not partial or "name" in payload:
        if not name:
            raise HTTPException(status_code=400, detail="预设名称不能为空")
    if len(name) > 120 or len(work) > 200:
        raise HTTPException(status_code=400, detail="预设名称或作品名过长")
    if category not in prompt_document.APPEARANCE_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的分类：{category}",
        )

    def clean_tags(field: str) -> list[str]:
        raw = payload.get(field) or []
        if not isinstance(raw, list):
            raise HTTPException(status_code=400, detail=f"{field} 必须是数组")
        if len(raw) > 80:
            raise HTTPException(status_code=400, detail=f"{field} 最多 80 个标签")
        result: list[str] = []
        seen: set[str] = set()
        for value in raw:
            tag = str(value or "").strip()
            if not tag:
                continue
            if len(tag) > 120:
                raise HTTPException(status_code=400, detail="单个外观标签不能超过 120 字")
            if not tag.isascii():
                raise HTTPException(status_code=400, detail="角色外观标签必须使用英文")
            if content_filter.is_hard_blocked(tag):
                raise HTTPException(status_code=403, detail="该外观标签命中禁止规则")
            if content_restriction_enabled() and content_filter.is_nsfw(tag):
                raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该外观标签")
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                result.append(tag)
        return result

    note = str(payload.get("note") or "").strip()
    if len(note) > 1000:
        raise HTTPException(status_code=400, detail="备注不能超过 1000 字")
    outfit_id = str(payload.get("outfit_id") or "").strip()
    if len(outfit_id) > 160:
        raise HTTPException(status_code=400, detail="outfit_id 过长")
    return {
        "name": name,
        "work": work,
        "category": category,
        "appearance_tags": clean_tags("appearance_tags"),
        "clothing_tags": clean_tags("clothing_tags"),
        "expression_tags": clean_tags("expression_tags"),
        "outfit_id": outfit_id,
        "note": note,
        "enabled": payload.get("enabled", True) is not False,
    }


@router.get("/api/prompt-agent/appearance-presets")
def appearance_presets(
    keyword: str = Query("", max_length=200),
    category: str = Query("", max_length=40),
    source: str = Query("", max_length=40),
    work: str = Query("", max_length=80),
    enabled: bool | None = Query(None),
) -> dict:
    """本地外观预设目录；不依赖 Ollama 或网络。"""
    items = database.list_character_appearance_presets(
        keyword=keyword,
        category=category,
        source=source,
        work=work,
        enabled=enabled,
    )
    thumbnail_statuses = preset_asset_service.character_thumbnail_statuses(
        [str(item["preset_id"]) for item in items]
    )
    for item in items:
        item.update(thumbnail_statuses[str(item["preset_id"])])
    items = [_appearance_with_outfit(item) for item in items]
    return {
        "items": items,
        "total": len(items),
        "categories": list(prompt_document.APPEARANCE_CATEGORIES),
        "sources": ["builtin", "user", "llm_draft", "legacy_cache"],
        "works": database.list_character_appearance_works(),
    }


@router.get("/api/prompt-agent/appearance-presets/{preset_id}")
def appearance_preset_detail(
    preset_id: str,
    version: int | None = Query(None, ge=1),
) -> dict:
    item = database.get_character_appearance_preset(preset_id, version)
    if not item:
        raise HTTPException(status_code=404, detail="外观预设不存在")
    return {"item": _appearance_with_outfit(item)}


@router.post("/api/prompt-agent/appearance-presets")
def create_appearance_preset(payload: dict = Body(...)) -> dict:
    values = _validate_appearance_preset_payload(payload)
    preset_id = str(payload.get("preset_id") or "").strip()
    if preset_id:
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", preset_id):
            raise HTTPException(status_code=400, detail="preset_id 格式不合法")
        if database.get_character_appearance_preset(preset_id):
            raise HTTPException(status_code=409, detail="preset_id 已存在")
    else:
        preset_id = f"appearance_{uuid.uuid4().hex}"
    item = database.create_character_appearance_preset(
        preset_id=preset_id,
        source="user",
        **values,
    )
    return {"ok": True, "item": _appearance_with_outfit(item)}


@router.put("/api/prompt-agent/appearance-presets/{preset_id}")
def edit_appearance_preset(preset_id: str, payload: dict = Body(...)) -> dict:
    current = database.get_character_appearance_preset(preset_id)
    if not current:
        raise HTTPException(status_code=404, detail="外观预设不存在")
    values = _validate_appearance_preset_payload(payload, partial=True)
    merged = {
        "name": values["name"] or current["name"],
        "work": values["work"] if "work" in payload else current["work"],
        "category": values["category"] if "category" in payload else current["category"],
        "appearance_tags": (
            values["appearance_tags"] if "appearance_tags" in payload else current["appearance_tags"]
        ),
        "clothing_tags": (
            values["clothing_tags"] if "clothing_tags" in payload else current["clothing_tags"]
        ),
        "expression_tags": (
            values["expression_tags"] if "expression_tags" in payload else current["expression_tags"]
        ),
        "outfit_id": values["outfit_id"] if "outfit_id" in payload else current["outfit_id"],
        "note": values["note"] if "note" in payload else current["note"],
        "enabled": values["enabled"] if "enabled" in payload else current["enabled"],
    }
    if current["source"] == "builtin":
        item = database.create_character_appearance_preset(
            preset_id=f"appearance_{uuid.uuid4().hex}",
            source="user",
            **merged,
        )
        return {"ok": True, "item": _appearance_with_outfit(item), "created_copy": True}
    item = database.update_character_appearance_preset(
        preset_id,
        source=current["source"],
        **merged,
    )
    return {"ok": True, "item": _appearance_with_outfit(item), "created_copy": False}


@router.post("/api/prompt-agent/appearance-presets/{preset_id}/duplicate")
def duplicate_appearance_preset(preset_id: str, payload: dict = Body(default={})) -> dict:
    current = database.get_character_appearance_preset(preset_id)
    if not current:
        raise HTTPException(status_code=404, detail="外观预设不存在")
    item = database.create_character_appearance_preset(
        preset_id=f"appearance_{uuid.uuid4().hex}",
        name=str(payload.get("name") or f"{current['name']} 副本").strip(),
        work=current["work"],
        category=current["category"],
        appearance_tags=current["appearance_tags"],
        clothing_tags=current["clothing_tags"],
        expression_tags=current["expression_tags"],
        outfit_id=current["outfit_id"],
        note=current["note"],
        source="user",
        enabled=current["enabled"],
    )
    return {"ok": True, "item": _appearance_with_outfit(item)}


@router.delete("/api/prompt-agent/appearance-presets/{preset_id}")
def remove_appearance_preset(preset_id: str) -> dict:
    current = database.get_character_appearance_preset(preset_id)
    if not current:
        raise HTTPException(status_code=404, detail="外观预设不存在")
    if current["source"] == "builtin":
        raise HTTPException(status_code=403, detail="内置模板不能删除，可复制后编辑")
    references = database.count_character_appearance_preset_references(preset_id)
    if references["total"]:
        raise HTTPException(
            status_code=409,
            detail=f"该预设仍被 {references['total']} 处引用，请先解除引用",
        )
    database.delete_character_appearance_preset(preset_id)
    return {"ok": True}


@router.post("/api/prompt-agent/appearance-presets/{preset_id}/apply")
def apply_appearance_preset(preset_id: str, payload: dict = Body(default={})) -> dict:
    current = database.get_character_appearance_preset(
        preset_id,
        int(payload.get("version") or 0) or None,
    )
    if not current:
        raise HTTPException(status_code=404, detail="外观预设不存在")
    current = _appearance_with_outfit(current)
    return {
        "preset_ref": {
            "preset_id": current["preset_id"],
            "version": current["version"],
        },
        "snapshot": {
            "name": current["name"],
            "category": current["category"],
            "appearance_tags": current["appearance_tags"],
            "clothing_tags": current["clothing_tags"],
            "expression_tags": current["expression_tags"],
            "outfit_id": current["outfit_id"],
            "outfit_name": current["outfit_name"],
            "note": current["note"],
        },
        "appearance": current["appearance_tags"],
        "clothing": current["clothing_tags"],
        "expression": current["expression_tags"],
        "default_outfit_id": current["outfit_id"],
        "default_outfit_name": current["outfit_name"],
    }


@router.post("/api/prompt-agent/appearance-presets/import-character-cache")
def import_character_cache(payload: dict = Body(...)) -> dict:
    """用户确认后把一条旧缓存转换为 legacy_cache 外观预设。"""
    name = str(payload.get("character_name") or "").strip()
    work = str(payload.get("work") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="character_name 不能为空")
    cached = database.get_character_appearance(name, work)
    if not cached:
        raise HTTPException(status_code=404, detail="旧缓存不存在")
    category = str(payload.get("category") or "自由备注").strip()
    values = _validate_appearance_preset_payload(
        {
            "name": f"{name}（{work or '旧缓存'}）",
            "work": work,
            "category": category,
            "appearance_tags": cached.get("appearance") or [],
            "clothing_tags": cached.get("clothing") or [],
            "expression_tags": [],
            "note": cached.get("note") or "由旧角色外观缓存显式导入。",
            "enabled": True,
        }
    )
    item = database.create_character_appearance_preset(
        preset_id=f"legacy_{uuid.uuid4().hex}",
        source="legacy_cache",
        **values,
    )
    return {"ok": True, "item": item}


@router.get("/api/prompt-agent/character-appearance")
def character_appearance(
    character_name: str = Query(..., min_length=1, max_length=80),
    work: str = Query("", max_length=200),
) -> dict:
    """角色名+作品 -> 外貌/默认服装：先查本地缓存，未命中再用本地 LLM 草稿。"""
    name = character_name.strip()
    source_work = work.strip()
    if not name:
        raise HTTPException(status_code=400, detail="角色名不能为空")
    if content_filter.is_hard_blocked(name) or content_filter.is_hard_blocked(source_work):
        raise HTTPException(status_code=403, detail="该内容被禁止生成")
    if content_restriction_enabled() and (content_filter.is_nsfw(name) or content_filter.is_nsfw(source_work)):
        raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
    cached = database.get_character_appearance(name, source_work)
    if cached:
        cached["source"] = "cache"
        return cached
    _ensure_llm_resource_free()
    if not prompt_agent.is_available():
        raise HTTPException(status_code=503, detail="Ollama 未启动")
    try:
        result = prompt_agent.generate_character_appearance(name, source_work)
    except Exception as exc:  # noqa: BLE001
        raise _llm_http_error(exc, "角色外观生成") from exc
    saved = database.save_character_appearance(
        name,
        source_work,
        result.get("appearance") or [],
        result.get("clothing") or [],
        note=result.get("note") or "",
        confidence=result.get("confidence") or 0,
        source="llm",
        corrected=False,
    )
    return saved or result


@router.post("/api/prompt-agent/public-setting-lookup")
def public_setting_lookup(payload: dict = Body(...)) -> dict:
    """Search public text settings for a character; never fetch images or apply presets."""
    query = str(payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="查询词不能为空")
    if len(query) > 160:
        raise HTTPException(status_code=400, detail="查询词不能超过 160 字")
    if content_filter.is_hard_blocked(query):
        raise HTTPException(status_code=403, detail="该内容被禁止生成")
    if content_restriction_enabled() and content_filter.is_nsfw(query):
        raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
    try:
        count = max(1, min(int(payload.get("count") or 6), 10))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="count 必须是 1-10 的整数") from None
    try:
        response = get_web_tools_service().search(
            query,
            count=count,
            need_content=False,
            app="prompt-agent-public-setting",
        )
    except WebToolsError as exc:
        status = 429 if exc.status_code == 429 else (502 if exc.retryable or (exc.status_code or 0) >= 500 else 400)
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    results: list[dict] = []
    seen: set[str] = set()
    for item in response.results:
        summary = (item.summary or item.snippet or "").strip()
        key = _setting_result_key(item.url)
        if not item.url or not summary or key in seen:
            continue
        if item.authority is not None and item.authority < 1:
            continue
        seen.add(key)
        results.append(
            {
                "title": item.title,
                "url": item.url,
                "summary": summary,
                "date": item.date,
                "authority": item.authority,
                "site_name": item.site_name,
            }
        )
        if len(results) >= count:
            break
    return {
        "provider": response.provider,
        "cached": response.cached,
        "results": results,
        "note": "仅返回公开文字候选；不下载图片、不自动覆盖角色预设。",
    }


@router.put("/api/prompt-agent/character-appearance")
def save_character_appearance(payload: dict = Body(...)) -> dict:
    """保存/覆盖角色外观缓存，供人工修正后使用。"""
    name = str(payload.get("character_name") or "").strip()
    source_work = str(payload.get("work") or "").strip()
    if not name or len(name) > 80:
        raise HTTPException(status_code=400, detail="角色名不能为空且不超过 80 字")
    if len(source_work) > 200:
        raise HTTPException(status_code=400, detail="作品名称不超过 200 字")
    if content_filter.is_hard_blocked(name) or content_filter.is_hard_blocked(source_work):
        raise HTTPException(status_code=403, detail="该内容被禁止生成")
    if content_restriction_enabled() and (content_filter.is_nsfw(name) or content_filter.is_nsfw(source_work)):
        raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
    appearance = payload.get("appearance") or []
    clothing = payload.get("clothing") or []
    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence") or 0.95)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="confidence 必须是 0-1 的数字") from None
    saved = database.save_character_appearance(
        name,
        source_work,
        appearance,
        clothing,
        note=str(payload.get("note") or "").strip(),
        confidence=confidence,
        source="manual",
        corrected=True,
    )
    return saved


@router.post("/api/prompt-agent/refine")
def refine_prompt(payload: dict = Body(...)):
    """单轮细化：结合图片描述、现有提示词、预设体位与用户要求重新生成并拆分。"""
    description = str(payload.get("description") or "").strip()
    current_prompt = str(payload.get("prompt") or "").strip()
    requirements = str(payload.get("requirements") or "").strip()
    if not current_prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    _ensure_llm_resource_free()
    pose_tags: list[str] = []
    preset_id = str(payload.get("pose_preset_id") or "")
    if preset_id:
        preset = next((item for item in prompt_agent.POSE_PRESETS if item["id"] == preset_id), None)
        if preset:
            people_prompt = str(preset.get("people_prompt") or "").strip()
            pose_tags = [people_prompt, *list(preset.get("tags") or [])] if people_prompt else list(preset.get("tags") or [])
    try:
        refined = prompt_agent.refine_prompt(description, current_prompt, requirements, pose_tags)
    except Exception as exc:  # noqa: BLE001
        raise _llm_http_error(exc, "细化并拆分") from exc
    prompt = refined.get("prompt") or current_prompt
    if content_filter.is_hard_blocked(prompt):
        raise HTTPException(status_code=403, detail="该内容被禁止生成")
    if content_restriction_enabled() and content_filter.is_nsfw(prompt):
        raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
    return {
        "prompt": prompt,
        "prompt_translation": translate_text(prompt),
        "groups": refined.get("groups") or [],
    }


CLARIFY_SESSIONS: dict[str, dict] = {}
CLARIFY_LOCK = threading.Lock()

CLARIFY_SYSTEM = (
    "你是提示词澄清助手，通过多轮问答帮用户生成英文 Danbooru 风格 AI 绘画提示词。\n"
    "每轮先简短确认或追问缺失信息（人物、服装、动作/体位、场景、光线、画风、人数等），最多追问 5 轮。\n"
    "当信息足够时，只输出 JSON："
    '{"done":true,"prompt":"英文逗号分隔标签","groups":[{"label":"人物","items":[]}]}。\n'
    "涉及成人/R18内容时如实保留对应英文标签，不拒绝、不省略、不委婉。"
)


def _cleanup_clarify_sessions() -> None:
    now = time.time()
    for session_id in list(CLARIFY_SESSIONS):
        if now - CLARIFY_SESSIONS[session_id]["updated_at"] > 1800:
            del CLARIFY_SESSIONS[session_id]


@router.post("/api/prompt-agent/clarify")
def clarify_prompt(payload: dict = Body(...)):
    """多轮对话澄清：按 session 保留上下文，信息足够时返回最终提示词。"""
    session_id = str(payload.get("session_id") or "").strip() or uuid.uuid4().hex
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message 不能为空")
    _ensure_llm_resource_free()
    with CLARIFY_LOCK:
        _cleanup_clarify_sessions()
        session = CLARIFY_SESSIONS.setdefault(session_id, {"history": [], "updated_at": time.time()})
        history = session["history"]
        if not history:
            initial = str(payload.get("initial") or "").strip()
            if initial:
                history.append({"role": "user", "content": f"初始描述：{initial}"})
        history.append({"role": "user", "content": message})
        messages = [{"role": "system", "content": CLARIFY_SYSTEM}] + history[-20:]
        try:
            result = llm.chat(
                messages,
                max_tokens=1200,
                temperature=0.3,
                think=False,
                model=config.R18_MODEL if content_filter.is_nsfw(message) else None,
            )
        except Exception as exc:  # noqa: BLE001
            raise _llm_http_error(exc, "多轮澄清") from exc
        history.append({"role": "assistant", "content": result})
        session["updated_at"] = time.time()

    done = False
    prompt = ""
    groups: list[dict] = []
    try:
        data = prompt_agent.extract_json_payload(result, "object")
        if data.get("done"):
            prompt = str(data.get("prompt") or "").strip()
            groups = prompt_agent.normalize_split_groups(data.get("groups"))
            done = True
    except Exception:
        done = False
    if done:
        tags = [tag.strip() for tag in re.split(r"[,\n]", prompt) if tag.strip()]
        tags = [tag for tag in tags if tag.lower() not in ("r18", "nsfw")]
        tags = prompt_agent._to_english_tags(tags)
        prompt = ", ".join(tags)
        for group in groups:
            group["items"] = prompt_agent._to_english_tags([str(item) for item in group["items"]])
        if content_filter.is_hard_blocked(prompt):
            raise HTTPException(status_code=403, detail="该内容被禁止生成")
        if content_restriction_enabled() and content_filter.is_nsfw(prompt):
            raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
        return {
            "session_id": session_id,
            "done": True,
            "reply": "",
            "prompt": prompt,
            "prompt_translation": translate_text(prompt) if prompt else "",
            "groups": groups,
        }
    return {
        "session_id": session_id,
        "done": False,
        "reply": result,
        "prompt": "",
        "prompt_translation": "",
        "groups": [],
    }
