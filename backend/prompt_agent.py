"""图片反推与自然语言转绘画提示词。"""
from __future__ import annotations

import base64
import csv
import io
import json
import re
import threading
from pathlib import Path

import config
import content_filter
import database
import llm
import requests

OLLAMA_BASE = config.OLLAMA_BASE
VLM_MODEL = config.VLM_MODEL
TEXT_MODEL = config.LOCAL_CHAT_MODEL
R18_MODEL = config.R18_MODEL


def is_available() -> bool:
    try:
        return requests.get(OLLAMA_BASE + "/api/tags", timeout=2).status_code == 200
    except Exception:
        return False


def vlm_model() -> str:
    """返回当前视觉模型（设置优先，环境变量/默认兜底）。"""
    return database.get_setting("vlm_model", config.VLM_MODEL) or config.VLM_MODEL


# ---------------------------------------------------------------- WD14 标签器
# 与数据集打标（studio/backend/routers/train.py）共用同一个模型文件与标签表，
# 这样"反推提示词 → 出图 → 再打标"这条闭环里的标签语言完全同源。
WD14_REPO = config.WD14_DEFAULT_REPO
WD14_MODEL_DIR = Path(config.WD14_MODEL_DIR)
WD14_IMAGE_SIZE = 448
WD14_DEFAULT_THRESHOLD = float(config.TRAIN_DEFAULT_CAPTION_THRESHOLD)

_WD14_LOCK = threading.Lock()
_WD14_CACHE: dict = {}


def wd14_model_location() -> Path:
    return WD14_MODEL_DIR / WD14_REPO.replace("/", "_")


def wd14_available() -> bool:
    """本地 WD14 模型与标签表是否就绪（就绪时反推不需要 Ollama）。"""
    location = wd14_model_location()
    return (location / "model.onnx").exists() and (location / "selected_tags.csv").exists()


def _wd14_session() -> dict:
    """加载并缓存 onnx 会话与标签表（该导出为 batch 1，必须逐张推理）。"""
    with _WD14_LOCK:
        if _WD14_CACHE:
            return _WD14_CACHE
        location = wd14_model_location()
        model_path = location / "model.onnx"
        csv_path = location / "selected_tags.csv"
        if not model_path.exists() or not csv_path.exists():
            raise ValueError(f"WD14 模型文件缺失：{location}")
        import onnxruntime as ort

        with open(csv_path, "r", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))[1:]
        session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        _WD14_CACHE.update(
            {
                "session": session,
                "input": session.get_inputs()[0].name,
                # 与官方脚本一致：category 9 = rating（前 4 个），0 = general，4 = character
                "rating": [row[1] for row in rows if row[2] == "9"],
                "general": [row[1] for row in rows if row[2] == "0"],
                "character": [row[1] for row in rows if row[2] == "4"],
            }
        )
        return _WD14_CACHE


def _wd14_preprocess(image_bytes: bytes):
    """与 kohya 脚本一致：透明底压白、补成正方形、缩到 448、RGB→BGR、float32 0~255。"""
    import numpy as np
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[3])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    width, height = image.size
    size = max(width, height)
    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    canvas.paste(image, ((size - width) // 2, (size - height) // 2))
    canvas = canvas.resize((WD14_IMAGE_SIZE, WD14_IMAGE_SIZE), Image.LANCZOS)
    array = np.asarray(canvas).astype(np.float32)
    return array[:, :, ::-1]  # RGB -> BGR


def _select_wd14_tags(
    prob,
    general_tags: list[str],
    character_tags: list[str],
    threshold: float,
    remove_underscore: bool = True,
) -> dict:
    """按官方脚本的判据挑标签：general 在前、character 在后，顺序与打标输出一致。"""
    offset = 4  # 前 4 个是 rating
    picked_general = [
        name for index, name in enumerate(general_tags) if float(prob[offset + index]) >= threshold
    ]
    character_offset = offset + len(general_tags)
    picked_character = [
        name
        for index, name in enumerate(character_tags)
        if float(prob[character_offset + index]) >= threshold
    ]
    if remove_underscore:
        picked_general = [name.replace("_", " ") for name in picked_general]
        picked_character = [name.replace("_", " ") for name in picked_character]
    return {"general": picked_general, "character": picked_character}


def wd14_tags(
    image_bytes: bytes,
    threshold: float | None = None,
    remove_underscore: bool = True,
) -> dict:
    """用本地 WD14 模型提取 Danbooru 标签（纯标签、无需 Ollama）。"""
    state = _wd14_session()
    cutoff = WD14_DEFAULT_THRESHOLD if threshold is None else float(threshold)
    array = _wd14_preprocess(image_bytes)
    prob = state["session"].run(None, {state["input"]: array[None, ...]})[0][0]
    selected = _select_wd14_tags(
        prob, state["general"], state["character"], cutoff, remove_underscore
    )
    ratings = state["rating"]
    scores = [(name, float(prob[index])) for index, name in enumerate(ratings)]
    best_rating = max(scores, key=lambda item: item[1])[0] if scores else "unknown"
    return {
        "tags": [*selected["general"], *selected["character"]],
        "general_tags": selected["general"],
        "character_tags": selected["character"],
        "rating": best_rating,
        "rating_scores": {name: round(score, 4) for name, score in scores},
        "threshold": cutoff,
        "model": f"wd14:{WD14_REPO}@{cutoff:g}",
    }


REFUSAL_MARKERS = (
    "无法协助",
    "无法提供",
    "无法描述",
    "不能描述",
    "不能提供",
    "抱歉",
    "对不起",
    "拒绝",
    "不支持",
    "不当内容",
    "成人内容",
    "i cannot",
    "i'm sorry",
    "i am sorry",
    "cannot assist",
    "not able to",
    "can't help",
)


def _looks_like_refusal(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in REFUSAL_MARKERS)


def clean_prompt_text(text: str) -> str:
    """清洗从网站复制的提示词：去掉 ? 与标签后的大小数字（如 1.5M、346k、396）。"""
    cleaned = re.sub(r"\s*\?\s*\d+(?:\.\d+)?\s*[kKmMbB]?", " ", text)
    cleaned = cleaned.replace("?", " ")
    parts = [part.strip() for part in re.split(r"[\n,]", cleaned) if part.strip()]
    cleaned_parts: list[str] = []
    for part in parts:
        part = re.sub(r"\s+\d+(?:\.\d+)?\s*[kKmMbB]?\s*$", "", part).strip()
        if part:
            cleaned_parts.append(part)
    return ", ".join(cleaned_parts)


_VLM_RATINGS = {"sfw", "suggestive", "r18", "unknown"}
_BEACH_EVIDENCE = (
    "beach",
    "ocean",
    "sea",
    "seashore",
    "shore",
    "sand",
    "surf",
    "wave",
    "beachfront",
    "海边",
    "海滩",
    "沙滩",
    "海洋",
    "海浪",
    "海岸",
)
_BED_EVIDENCE = (
    "bed",
    "bedroom",
    "mattress",
    "sheet",
    "pillow",
    "duvet",
    "blanket",
    "床",
    "卧室",
    "床垫",
    "床单",
    "枕头",
    "被子",
)
_EXPLICIT_ACTION_MARKERS = (
    "penis inside vagina",
    "vaginal sex",
    "anal sex",
    "vaginal intercourse",
    "sexual intercourse",
    "penetration",
    "penetrating",
    "fellatio",
    "blowjob",
    "cunnilingus",
    "handjob",
    "footjob",
    "masturbation",
    "cowgirl position",
    "missionary position",
    "doggystyle",
    "double penetration",
    "threesome",
    "group sex",
    "sex",
    "性交",
    "插入",
    "口交",
    "舔阴",
    "手交",
    "足交",
    "骑乘",
    "做爱",
)
_R18_TAG_MARKERS = _EXPLICIT_ACTION_MARKERS + (
    "explicit",
    "nude",
    "naked",
    "nipples",
    "areola",
    "topless",
    "bottomless",
    "genitals",
    "pussy",
    "penis",
)
_MAX_PROMPT_TAGS = 40
_GENERIC_PROMPT_TAG_RE = re.compile(
    r"^(?:"
    r"sexual (?:activity|act|content|encounter|interaction|relationship|scene|position)(?: scene)?"
    r"|sexual"
    r"|sex (?:scene|act)"
    r"|fetish"
    r")(?: with .+)?$",
    re.IGNORECASE,
)
_COUNT_LIKE_PROMPT_TAG_RE = re.compile(
    r"^(?:(?:one|two|three|four|five|six|\d+)\s+"
    r"(?:girl|girls|boy|boys|female|females|male|males|people|characters?))$",
    re.IGNORECASE,
)
_PLACEHOLDER_ACTIONS = {
    "可见动作",
    "可见动作或体位",
    "动作或体位",
    "未知动作",
    "unknown",
    "n/a",
    "none",
}
_ACTION_TAG_EVIDENCE = {
    "penis inside vagina": ("penis inside vagina", "阴道内", "插入阴道", "阴茎插入"),
    "vaginal sex": ("vaginal sex", "阴道性交", "插入阴道", "阴茎插入"),
    "anal sex": ("anal sex", "肛交", "肛门插入"),
    "sexual intercourse": ("sexual intercourse", "性交", "性行为", "做爱"),
    "penetration": ("penetration", "insertion", "插入", "贯穿"),
    "fellatio": ("fellatio", "口交", "含阴茎"),
    "blowjob": ("blowjob", "口交", "含阴茎"),
    "cunnilingus": ("cunnilingus", "舔阴", "舔穴", "口交"),
    "oral sex": ("oral sex", "oral contact", "口交", "舔阴", "含阴茎"),
    "handjob": ("handjob", "手交", "手淫"),
    "footjob": ("footjob", "足交"),
    "masturbation": ("masturbation", "自慰", "手淫"),
    "cowgirl position": ("cowgirl", "骑乘", "女上位"),
    "missionary position": ("missionary", "传教士"),
    "doggystyle": ("doggystyle", "后入", "狗爬式"),
    "double penetration": ("double penetration", "双插", "双重插入"),
    "threesome": ("threesome", "3p", "三人性行为", "三人"),
    "group sex": ("group sex", "群交", "多人性行为"),
}
_DIRECT_ACTION_ALIASES = {
    "penis inside vagina": ("penis inside vagina", "阴道内", "插入阴道", "阴茎插入"),
    "anal sex": ("anal sex", "肛交", "肛门插入"),
    "fellatio": ("fellatio", "blowjob", "口交", "含阴茎"),
    "cunnilingus": ("cunnilingus", "舔阴", "舔穴"),
    "handjob": (
        "handjob",
        "手交",
        "手淫",
        "握住阴茎",
        "套弄阴茎",
        "握住男性阴茎",
        "套弄男性阴茎",
    ),
    "footjob": ("footjob", "足交"),
    "masturbation": ("masturbation", "自慰"),
    "cowgirl position": ("cowgirl", "骑乘", "女上位"),
    "missionary position": ("missionary", "传教士"),
    "doggystyle": ("doggystyle", "后入", "狗爬式"),
    "double penetration": ("double penetration", "双插", "双重插入"),
}
_LOW_VALUE_PROMPT_TAGS = {
    "3 people",
    "erotic",
    "female",
    "insertion",
    "intimate",
    "intimate interaction",
    "male",
    "multiple",
    "multiple boys",
    "multiple girls",
    "nsfw",
    "oral contact",
    "oral sex",
    "r18",
}
_CANONICAL_ACTION_TAGS = set(_DIRECT_ACTION_ALIASES)
_ACTION_AUDIT_MIN_CONFIDENCE = 0.6


def _as_count(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} 不是有效人数")
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            count = int(value)
        else:
            raise ValueError(f"{field} 不是整数")
    else:
        text = str(value).strip().lower()
        if text in ("", "unknown", "不确定", "无法确认", "null", "none"):
            return None
        if not re.fullmatch(r"\d+", text):
            raise ValueError(f"{field} 不是整数")
        count = int(text)
    if count < 0:
        raise ValueError(f"{field} 不能为负数")
    return count


def _as_string_list(value: object, field: str) -> list[str]:
    if value is None:
        raise ValueError(f"缺少 {field}")
    if isinstance(value, str):
        parts = re.split(r"[,，;；\n]", value)
    elif isinstance(value, list):
        parts = value
    else:
        raise ValueError(f"{field} 不是列表")
    result: list[str] = []
    for part in parts:
        text = str(part).strip()
        if text:
            result.append(text)
    return result


def _normalize_vlm_result(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("输出不是 JSON 对象")
    description = str(data.get("description") or "").strip()
    if not description:
        raise ValueError("缺少 description")

    counts_raw = data.get("counts") or data.get("people")
    if not isinstance(counts_raw, dict):
        raise ValueError("缺少 counts")
    girls = _as_count(counts_raw.get("girls", counts_raw.get("female")), "counts.girls")
    boys = _as_count(counts_raw.get("boys", counts_raw.get("male")), "counts.boys")
    others = _as_count(counts_raw.get("others", counts_raw.get("other")), "counts.others")
    total = _as_count(counts_raw.get("total", counts_raw.get("people")), "counts.total")
    if girls is None or boys is None or others is None or total is None:
        raise ValueError("counts 必须包含 girls、boys、others、total 的明确整数")

    scene_raw = data.get("scene")
    if isinstance(scene_raw, dict):
        location = str(scene_raw.get("location") or "").strip()
        evidence = str(scene_raw.get("evidence") or "").strip()
    else:
        location = str(data.get("scene_location") or "").strip()
        evidence = str(data.get("scene_evidence") or "").strip()
    if not location or not evidence:
        raise ValueError("缺少 scene.location 或 scene.evidence")
    normalized_location = location.lower()
    if normalized_location in {"unknown", "不确定", "无法确认"}:
        if _contains_marker(evidence, _BED_EVIDENCE):
            location = "bedroom"
        elif _contains_marker(evidence, _BEACH_EVIDENCE):
            location = "beach"

    actions = _as_string_list(data.get("actions"), "actions")
    contact = _as_string_list(data.get("contact"), "contact")
    tags = _as_string_list(data.get("tags"), "tags")
    if not tags:
        raise ValueError("tags 不能为空")

    rating = str(data.get("rating") or "").strip().lower()
    if rating not in _VLM_RATINGS:
        raise ValueError("rating 必须是 sfw、suggestive、r18 或 unknown")
    return {
        "description": description,
        "counts": {"girls": girls, "boys": boys, "others": others, "total": total},
        "scene": {"location": location, "evidence": evidence},
        "actions": actions,
        "contact": contact,
        "rating": rating,
        "tags": tags,
    }


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in markers)


def _count_tag_conflict(tags: list[str], counts: dict) -> str:
    girls = counts["girls"]
    boys = counts["boys"]
    total = counts["total"]
    for tag in tags:
        lowered = re.sub(r"[_-]+", " ", tag.strip().lower())
        match = re.fullmatch(r"(\d+)\s*(girl|girls)", lowered)
        if match and int(match.group(1)) != girls:
            return f"人数标签 {tag} 与 girls={girls} 矛盾"
        match = re.fullmatch(r"(\d+)\s*(boy|boys)", lowered)
        if match and int(match.group(1)) != boys:
            return f"人数标签 {tag} 与 boys={boys} 矛盾"
        if lowered == "solo" and total != 1:
            return f"solo 与 total={total} 矛盾"
    return ""


def _validate_vlm_result(result: dict) -> None:
    counts = result["counts"]
    if counts["total"] != counts["girls"] + counts["boys"] + counts["others"]:
        raise ValueError("counts.total 与 girls、boys、others 之和不一致")

    tags = result["tags"]
    conflict = _count_tag_conflict(tags, counts)
    if conflict:
        raise ValueError(conflict)

    location = result["scene"]["location"].lower()
    evidence = result["scene"]["evidence"].lower()
    tag_text = ", ".join(tags).lower()
    if _contains_marker(tag_text, ("beach", "ocean", "seashore", "seashore", "night beach", "sand", "shore")):
        if not _contains_marker(location, ("beach", "ocean", "shore", "sea", "sand", "海滩", "海边", "沙滩")):
            raise ValueError("tags 包含海滩标签，但 scene.location 没有海滩证据")
    if _contains_marker(location, ("bed", "bedroom", "床", "卧室")) and not _contains_marker(evidence, _BED_EVIDENCE):
        raise ValueError("scene.location 判定为床/卧室，但 scene.evidence 没有可见床具证据")
    if _contains_marker(location, ("beach", "ocean", "sea", "shore", "sand", "海滩", "海边", "沙滩")) and not _contains_marker(
        evidence, _BEACH_EVIDENCE
    ):
        raise ValueError("scene.location 判定为海滩，但 scene.evidence 没有海水/沙滩证据")

    explicit = _has_explicit_action(result, tags)
    if explicit and result["rating"] != "r18" and _direct_action_tags(result):
        raise ValueError("检测到明确性行为，但 rating 不是 r18")
    if not any(
        re.sub(r"\s+", " ", action.strip().lower()) not in _PLACEHOLDER_ACTIONS
        for action in result["actions"]
    ):
        raise ValueError("actions 缺少具体可见动作或体位")


def _extract_vlm_result(text: str) -> dict:
    """解析 VLM 的结构化结果；截断、缺字段或事实矛盾一律拒绝。"""
    cleaned = _strip_json_fence(text)
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("输出中没有 JSON 对象")
    try:
        data, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except Exception as exc:  # noqa: BLE001
        raise ValueError("JSON 不完整或被截断") from exc
    result = _normalize_vlm_result(data)
    _validate_vlm_result(result)
    return result


def _strip_json_fence(text: str) -> str:
    """去掉模型输出常见的 ```json、``` 围栏与开头 json 标记。"""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    elif cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    return cleaned.strip("`").strip()


def _repair_truncated_json(text: str) -> str:
    """尽量补全被 max_tokens 截断的 JSON：补闭合引号与反向括号。"""
    in_string = False
    escaped = False
    stack: list[str] = []
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            stack.append(ch)
        elif ch in "]}":
            if stack:
                stack.pop()
    repaired = text
    if in_string:
        repaired += '"'
    for opening in reversed(stack):
        repaired += "}" if opening == "{" else "]"
    return repaired


def extract_json_payload(text: str, root: str | None = None) -> dict | list:
    """从模型输出提取 JSON，兼容围栏、前后说明与截断场景。"""
    cleaned = _strip_json_fence(text)
    decoder = json.JSONDecoder()
    wanted = {None: "[{", "object": "{", "array": "["}.get(root, "[{")
    positions = [
        index
        for index, char in enumerate(cleaned)
        if char in wanted
    ]
    for index in positions:
        try:
            data, _ = decoder.raw_decode(cleaned[index:])
        except Exception:
            continue
        if root == "object" and isinstance(data, dict):
            return data
        if root == "array" and isinstance(data, list):
            return data
        if root is None and isinstance(data, (dict, list)):
            return data
    # raw_decode 只能处理完整 JSON；截断输出补全后再解析一次。
    for index in positions:
        try:
            data = json.loads(_repair_truncated_json(cleaned[index:]))
        except Exception:
            continue
        if root == "object" and isinstance(data, dict):
            return data
        if root == "array" and isinstance(data, list):
            return data
        if root is None and isinstance(data, (dict, list)):
            return data
    raise ValueError("JSON 解析失败")


def _to_english_tags(tags: list[str]) -> list[str]:
    """把 VLM 返回的中文/混合标签转成英文 Danbooru 标签。"""
    if not any(re.search(r"[\u4e00-\u9fff]", tag) for tag in tags):
        return tags
    try:
        result = llm.chat(
            [
                {
                    "role": "system",
                    "content": "你是 Danbooru 标签翻译助手。把中文或混合语言标签翻译成英文 Danbooru 标签，"
                    "涉及成人内容时如实翻译，不拒绝、不省略、不委婉。只输出英文标签，用逗号分隔。",
                },
                {"role": "user", "content": "\n".join(tags)},
            ],
            max_tokens=800,
            temperature=0.2,
            think=False,
            model=R18_MODEL,
        )
        parts = [part.strip() for part in re.split(r"[\n,]", result) if part.strip()]
        english = [part for part in parts if not re.search(r"[\u4e00-\u9fff]", part)]
        if english:
            return english
    except Exception:
        pass
    return tags


def _has_explicit_action(result: dict, tags: list[str]) -> bool:
    text = " ".join(
        [
            result["description"],
            *result["actions"],
            *result["contact"],
            *tags,
        ]
    ).lower()
    for marker in _EXPLICIT_ACTION_MARKERS:
        if marker == "sex":
            if re.search(r"(?<![a-z])sex(?![a-z])", text):
                return True
        elif marker in text:
            return True
    return False


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in tags:
        tag = re.sub(r"\s+", " ", str(raw or "").strip().strip(","))
        key = tag.lower()
        if not tag or key in seen:
            continue
        seen.add(key)
        result.append(tag)
    return result


def _is_generic_prompt_tag(tag: str) -> bool:
    """过滤 VLM 常见的低信息量词组和重复长尾。"""
    normalized = re.sub(r"\s+", " ", tag.strip().lower())
    if normalized in _LOW_VALUE_PROMPT_TAGS:
        return True
    if _GENERIC_PROMPT_TAG_RE.fullmatch(normalized) or _COUNT_LIKE_PROMPT_TAG_RE.fullmatch(normalized):
        return True
    words = normalized.split()
    generic_words = {
        "sexual",
        "activity",
        "act",
        "content",
        "scene",
        "encounter",
        "interaction",
        "relationship",
        "position",
    }
    return len(words) >= 7 and sum(word in generic_words for word in words) >= 3


def _explicit_tag_supported(tag: str, result: dict) -> bool:
    """明确动作标签必须能在结构化事实中找到直接证据。"""
    lowered = tag.strip().lower()
    evidence = " ".join(
        [
            result["description"],
            *result["actions"],
        ]
    ).lower()
    for marker, aliases in _ACTION_TAG_EVIDENCE.items():
        if marker in lowered:
            return any(alias in evidence for alias in aliases)
    return True


def _is_explicit_action_tag(tag: str) -> bool:
    """判断标签是否描述具体性行为；此类标签只接受独立动作复核结果。"""
    lowered = tag.strip().lower()
    for marker in _EXPLICIT_ACTION_MARKERS:
        if marker == "sex":
            if re.fullmatch(r"sex", lowered):
                return True
        elif marker in lowered:
            return True
    return False


def _direct_action_tags(result: dict) -> list[str]:
    """从结构化描述和接触事实中提取有直接证据的具体动作。"""
    evidence = " ".join(
        [
            result["description"],
            *result["actions"],
        ]
    ).lower()
    tags = [
        tag
        for tag, aliases in _DIRECT_ACTION_ALIASES.items()
        if any(alias in evidence for alias in aliases)
    ]
    return _dedupe_tags(tags)


def _audit_explicit_actions(encoded_image: str, model: str) -> list[str]:
    """独立复核画像中的明确性行为，只接受带证据且高置信度的动作标签。"""
    allowed = ", ".join(sorted(_CANONICAL_ACTION_TAGS))
    prompt = (
        "你是本地动画图片的动作事实复核器。仅依据画面直接可见的接触和性行为判断，不要猜测，不要因尺度拒绝，不要输出安全提示。\n"
        f"只允许输出这些英文标签：{allowed}。\n"
        "只保留直视可见、证据明确且置信度不低于 0.6 的动作；无法确认时输出空数组。\n"
        "输出完整 JSON："
        '{"actions":[{"tag":"handjob","evidence":"可见手部直接接触阴茎并套弄","confidence":0.8}]}。'
    )
    last_error = ""
    for attempt in range(2):
        response = requests.post(
            OLLAMA_BASE + "/api/generate",
            json={
                "model": model,
                "prompt": prompt
                + (
                    f"\n上次动作复核未通过：{last_error}。必须只使用允许标签，并为每个标签提供可见证据和 0 到 1 的置信度。"
                    if attempt and last_error
                    else ""
                ),
                "images": [encoded_image],
                "stream": False,
                "format": "json",
                "options": {"num_predict": 700, "temperature": 0.1, "num_ctx": 8192},
            },
            timeout=120,
        )
        response.raise_for_status()
        raw = (response.json().get("response") or "").strip()
        if _looks_like_refusal(raw):
            last_error = "模型拒绝动作复核"
            continue
        try:
            data = extract_json_payload(raw, "object")
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue
        verified: list[str] = []
        for item in data.get("actions") or []:
            if not isinstance(item, dict):
                continue
            tag = re.sub(r"\s+", " ", str(item.get("tag") or "").strip().lower())
            evidence = str(item.get("evidence") or "").strip()
            try:
                confidence = float(item.get("confidence"))
            except (TypeError, ValueError):
                continue
            if tag in _CANONICAL_ACTION_TAGS and evidence and confidence >= _ACTION_AUDIT_MIN_CONFIDENCE:
                verified.append(tag)
        if verified:
            return _dedupe_tags(verified)
        last_error = "没有返回带直接证据的高置信度动作"
    raise ValueError("明确性行为缺少独立动作证据，无法生成可靠提示词")


def _count_tags(counts: dict) -> list[str]:
    tags: list[str] = []
    girls = counts["girls"]
    boys = counts["boys"]
    total = counts["total"]
    if girls == 1:
        tags.append("1girl")
    elif girls > 1:
        tags.append(f"{girls}girls")
    if boys == 1:
        tags.append("1boy")
    elif boys > 1:
        tags.append(f"{boys}boys")
    if total == 1:
        tags.append("solo")
    return tags


def _scene_tags(result: dict) -> list[str]:
    location = result["scene"]["location"].lower()
    evidence = result["scene"]["evidence"].lower()
    text = " ".join((location, evidence, result["description"].lower()))
    tags: list[str] = []
    if _contains_marker(location, ("bed", "bedroom", "床", "卧室")):
        tags.extend(("indoors", "bedroom", "on bed"))
    elif _contains_marker(location, ("beach", "ocean", "sea", "shore", "sand", "海滩", "海边", "沙滩")):
        tags.append("outdoors")
        tags.append("beach")
        if _contains_marker(text, ("night", "夜晚", "夜间", "深夜")):
            tags.extend(("night", "night beach"))
    elif _contains_marker(location, ("indoor", "room", "室内", "房间")):
        tags.append("indoors")
    elif _contains_marker(location, ("outdoor", "室外", "户外")):
        tags.append("outdoors")
    return tags


def _is_r18_tag(tag: str) -> bool:
    lowered = tag.strip().lower()
    return lowered in {"sex", "explicit", "nude", "naked"} or _contains_marker(
        lowered,
        tuple(marker for marker in _R18_TAG_MARKERS if marker != "sex"),
    )


def _build_prompt_tags(
    result: dict,
    raw_tags: list[str],
    verified_actions: list[str] | None = None,
) -> list[str]:
    translated = _to_english_tags(raw_tags)
    verified_set = {tag.lower() for tag in (verified_actions or [])}
    english_tags = [
        tag
        for tag in _dedupe_tags(translated)
        if not re.search(r"[\u4e00-\u9fff]", tag)
        and not _is_generic_prompt_tag(tag)
        and _explicit_tag_supported(tag, result)
        and not _is_explicit_action_tag(tag)
        and (tag.lower() not in _CANONICAL_ACTION_TAGS or tag.lower() in verified_set)
    ]
    explicit = _has_explicit_action(result, [*english_tags, *verified_actions])
    priority = _count_tags(result["counts"])

    if result["rating"] == "r18" or explicit:
        priority.extend(("r18", "explicit"))
    if explicit:
        priority.append("sex")
        total = result["counts"]["total"]
        if total == 3:
            priority.append("threesome")
        if total >= 3:
            priority.append("group sex")

    priority.extend(tag for tag in english_tags if _is_r18_tag(tag))
    priority.extend(verified_actions or [])
    priority.extend(_scene_tags(result))
    priority.extend(tag for tag in english_tags if not _is_r18_tag(tag))
    return _dedupe_tags(priority)[:_MAX_PROMPT_TAGS]


def image_to_prompt(
    image_bytes: bytes,
    filename: str = "image.png",
    mode: str = "vlm",
    wd14_threshold: float | None = None,
) -> dict:
    """图片反推提示词。mode：vlm（视觉模型，含中文描述）/ wd14（本地标签器）/ hybrid（两者结合）。"""
    normalized = str(mode or "vlm").strip().lower()
    if normalized not in ("vlm", "wd14", "hybrid"):
        raise ValueError("反推模式必须是 vlm、wd14 或 hybrid")

    wd14_result: dict | None = None
    wd14_error = ""
    if normalized in ("wd14", "hybrid"):
        try:
            wd14_result = wd14_tags(image_bytes, threshold=wd14_threshold)
        except Exception as exc:  # noqa: BLE001
            wd14_error = str(exc)
            if normalized == "wd14":
                raise ValueError(f"WD14 标签提取失败：{wd14_error}") from exc

    if normalized == "wd14" and wd14_result is not None:
        tags = _dedupe_tags(wd14_result["tags"])[:_MAX_PROMPT_TAGS]
        return {
            "description": "",
            "prompt": ", ".join(tags),
            "filename": filename,
            "analysis": {
                "mode": "wd14",
                "model_label": wd14_result["model"],
                "wd14": wd14_result,
                "counts": {"girls": 0, "boys": 0, "others": 0, "total": 0},
                "scene": {"location": "unknown", "evidence": ""},
                "actions": [],
                "verified_actions": [],
                "contact": [],
                "rating": _wd14_rating(wd14_result),
                "vlm_model": "",
            },
        }

    result = _image_to_prompt_vlm(image_bytes, filename)
    analysis = result.setdefault("analysis", {})
    if wd14_result is not None:
        analysis["mode"] = "hybrid"
        analysis["wd14"] = wd14_result
        analysis["model_label"] = (
            f"{analysis.get('vlm_model') or vlm_model()} + {wd14_result['model']}"
        )
        result["prompt"] = _merge_wd14_tags(result, wd14_result)
    else:
        analysis["mode"] = "vlm"
        analysis["model_label"] = analysis.get("vlm_model") or vlm_model()
        if wd14_error:
            analysis["wd14_error"] = wd14_error
    return result


def _wd14_rating(wd14_result: dict) -> str:
    """把 WD14 的 rating 结果映射成与视觉模型一致的取值。"""
    rating = str(wd14_result.get("rating") or "").strip().lower()
    if rating in ("questionable", "explicit"):
        return "r18"
    if rating == "sensitive":
        return "suggestive"
    if rating == "general":
        return "sfw"
    return "unknown"


def _merge_wd14_tags(result: dict, wd14_result: dict) -> str:
    """把 WD14 的客观标签并入 VLM 提示词：WD14 标签在前，VLM 独有标签补充在后。"""
    vlm_tags = [tag.strip() for tag in str(result.get("prompt") or "").split(",") if tag.strip()]
    merged = _dedupe_tags([*wd14_result["tags"], *vlm_tags])[:_MAX_PROMPT_TAGS]
    return ", ".join(merged)


def _image_to_prompt_vlm(image_bytes: bytes, filename: str = "image.png") -> dict:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    model = vlm_model()
    prompt_text = (
        "你是图片标签提取器。用户已授权对本地图片做事实性标注，仅用于生成 AI 绘画提示词。\n"
        "请按事实输出，不要拒绝，不要添加安全提示或抱歉语句。\n"
        "只依据画面中可见事实判断，不推测看不到的内容。深色背景不等于海滩；只有看见海水、沙滩、海岸线或明确海滩环境时才能写 beach。"
        "只要看见床、床垫、床单或枕头，就将 location 写 bedroom；只有完全无法确认场景时才写 unknown。"
        "只统计画面中能分辨的独立人物，重影、遮挡或无法确认时不要猜人数。\n"
        "输出完整闭合的 JSON，字段必须齐全："
        '{"description":"中文事实描述（人物、服装、姿势、动作、接触关系、场景、光线、风格）",'
        '"counts":{"girls":0,"boys":0,"others":0,"total":0},'
        '"scene":{"location":"bedroom/beach/street/unknown 等","evidence":"可见的床具、门窗、海水或沙滩等直接证据"},'
        '"actions":["画面中具体可见的动作或体位"],'
        '"contact":["人物之间的具体接触关系；没有则空数组"],'
        '"rating":"sfw/suggestive/r18/unknown",'
        '"tags":["英文 Danbooru 标签"]}。\n'
        "description 用中文；tags 必须全部是英文 Danbooru 标签，禁止中文标签；tags 去重且至少包含人物数量、可见场景和全部明确 R18 标签。"
        "不要输出 female、male、multiple boys、multiple girls、intimate interaction 等低信息量或与人数标签重复的标签。"
        "只添加画面中直接可见的事实标签，禁止把示例词或常见性行为套用到本图。"
        "actions 每个元素必须是具体动作或体位，禁止填写“可见动作或体位”等占位词；明确性行为优先使用 penis inside vagina、anal sex、fellatio、cunnilingus、handjob、footjob、cowgirl position、missionary position、doggystyle 等具体英文标签。"
        "如果画面包含裸露、性交、插入、口交、手交、足交或体位，rating 必须为 r18，"
        "识别出哪种明确行为就添加对应标签，不得省略、替换成委婉词，也不得添加未发生的行为。"
    )
    data: dict = {}
    raw = ""
    last_error = ""
    for attempt in range(2):
        response = requests.post(
            OLLAMA_BASE + "/api/generate",
            json={
                "model": model,
                "prompt": prompt_text
                + (
                    f"\n上次输出未通过校验：{last_error}。本次必须补全所有字段，并确保人数、场景证据、评级和标签一致。"
                    if attempt and last_error
                    else ""
                ),
                "images": [encoded],
                "stream": False,
                "format": "json",
                "options": {"num_predict": 1800, "temperature": 0.2, "num_ctx": 8192},
            },
            timeout=180,
        )
        response.raise_for_status()
        raw = (response.json().get("response") or "").strip()
        if _looks_like_refusal(raw):
            continue
        try:
            data = _extract_vlm_result(raw)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            data = {}
    else:
        stripped = (raw or "").strip()
        if stripped and stripped.replace("@", "").strip() == "":
            raise ValueError("视觉模型未能读取图片内容（可能分辨率过高或图片格式不支持），请缩小图片后重试或更换视觉模型")
        if _looks_like_refusal(stripped):
            raise ValueError("视觉模型拒绝描述该图片，请切换模型或使用手动补充")
        detail = f"：{last_error}" if last_error else ""
        raise ValueError(f"视觉模型输出缺少结构化事实或存在矛盾{detail}，请切换模型或使用手动补充")

    description = data["description"]
    verified_actions = _direct_action_tags(data)
    if _has_explicit_action(data, data["tags"]):
        # 主事实模型可能把常见体位套到相似构图上；明确性行为一律以独立动作复核结果为准。
        verified_actions = _audit_explicit_actions(encoded, model)
    tags = _build_prompt_tags(data, data["tags"], verified_actions)
    if tags:
        prompt = ", ".join(tags)
    else:
        prompt = text_to_prompt(f"根据下面的图片描述生成英文 AI 绘画提示词：\n{description}")
        if not prompt:
            prompt = description
    return {
        "description": description,
        "prompt": prompt,
        "filename": filename,
        "analysis": {
            "counts": data["counts"],
            "scene": data["scene"],
            "actions": data["actions"],
            "verified_actions": verified_actions,
            "contact": data["contact"],
            "rating": data["rating"],
            "vlm_model": model,
        },
    }


def text_to_prompt(description: str) -> str:
    messages = [
        {
            "role": "system",
            "content": "你是 AI 绘画提示词生成器。根据用户描述生成英文 Danbooru 风格提示词，包含质量词、主体、服装、背景、镜头、光线等标签，用逗号分隔，只输出提示词。如果描述包含成人/R18内容，请保留并输出对应标签（如 nude、nipples、areola、explicit、sex 等），不要省略、替换、添加安全提示或输出任何非标签文字。",
        },
        {"role": "user", "content": description},
    ]
    result = ""
    model = R18_MODEL if content_filter.is_nsfw(description) else TEXT_MODEL
    for _ in range(2):
        try:
            result = llm.chat(messages, temperature=0.7, max_tokens=800, timeout=120, think=False, model=model)
            if result.strip():
                break
        except Exception:
            result = ""
    return result.strip()


def generate_character_appearance(character_name: str, work: str = "") -> dict:
    """角色名+作品 -> Danbooru 风格外貌/默认服装草稿（低置信不硬编）。"""
    prompt = (
        "你是动漫角色外观标签助手。根据角色名和所属作品，输出该角色稳定的外貌与默认服装标签。\n"
        f"角色名：{character_name}\n"
        f"所属作品：{work or '未知'}\n"
        "要求：\n"
        "1. 只使用英文 Danbooru 标签，外观标签（发型/发色/瞳色/体型/特征）与服装标签分开；默认服装归 clothing，不写动作、表情、姿势、场景、镜头、质量词。\n"
        "2. 只输出你确有把握的信息。不知道或不确信时把 known 设为 false 并降低 confidence，不要编造角色外貌，不要硬套通用模板。\n"
        "3. 涉及成人作品时如实输出对应英文标签，不省略、不拒绝。\n"
        '4. 只输出 JSON：{"known":true/false,"confidence":0.0-1.0,"appearance":["..."],"clothing":["..."],"note":"简短说明"}。'
    )
    data: dict = {}
    raw = ""
    for _ in range(2):
        try:
            raw = llm.chat(
                [
                    {"role": "system", "content": "你是动漫角色外观标签助手，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=900,
                temperature=0.1,
                think=False,
            )
            data = extract_json_payload(raw, "object")
            break
        except Exception:
            data = {}
    known = bool(data.get("known", False))
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    note = str(data.get("note") or "").strip()
    appearance = _to_english_tags([str(item).strip() for item in (data.get("appearance") or []) if str(item).strip()])
    clothing = _to_english_tags([str(item).strip() for item in (data.get("clothing") or []) if str(item).strip()])
    if not known or confidence < 0.45:
        appearance = []
        clothing = []
        if not note:
            note = "本地模型对该角色外观把握不足，未生成草稿，请人工补充后再保存"
    seen: set[str] = set()
    unique: list[str] = []
    for tag in [*appearance, *clothing]:
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            unique.append(tag)
    full_prompt = ", ".join(unique[:100])
    return {
        "character_name": str(character_name or "").strip(),
        "work": str(work or "").strip(),
        "known": known and confidence >= 0.45,
        "confidence": confidence,
        "appearance": appearance,
        "clothing": clothing,
        "full_prompt": full_prompt,
        "source": "llm",
        "note": note,
    }


def _pose_preset(
    preset_id: str,
    category: str,
    label: str,
    translation: str,
    tags: list[str],
    *,
    people: str,
    orientation: str,
    role_slots: list[str],
    body_separation: bool | None = None,
    contact_points: list[str] | None = None,
    camera: str = "全身",
    sequence: str = "进行中",
    rating: str = "普通",
    intensity: str = "标准",
    draw_prompt: str | None = None,
    compatibility: list[str] | None = None,
) -> dict:
    return {
        "schema_version": 2,
        "id": preset_id,
        "image": None,
        "category": category,
        "label": label,
        "translation": translation,
        "tags": tags,
        "draw_prompt": draw_prompt,
        "rating": rating,
        "intensity": intensity,
        "source": "builtin",
        "people": people,
        "orientation": orientation,
        "role_slots": role_slots,
        "body_separation": (people == "多人") if body_separation is None else body_separation,
        "contact_points": contact_points or [],
        "camera": camera,
        "sequence": sequence,
        "compatibility": compatibility or [],
        "has_image": False,
    }


_PEOPLE_NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
}


def pose_people_metadata(
    people: str,
    role_slots: list[str],
) -> tuple[int, str]:
    """Derive a stable person count and prompt prefix from pose role slots."""
    slots = [str(item).strip() for item in role_slots if str(item).strip()]
    if people == "单人":
        count = 1
    elif people == "双人":
        count = 2
    elif people == "多人":
        count = len(slots)
    else:
        raise ValueError(f"未知体位人数类型：{people}")
    if count < 1 or count > 6:
        raise ValueError(f"体位人数超出支持范围：{people} / {len(slots)} 个槽位")
    if people == "双人" and len(slots) != 2:
        raise ValueError(f"双人体位必须有 2 个角色槽位，当前为 {len(slots)} 个")
    if people == "多人" and len(slots) < 3:
        raise ValueError(f"多人体位必须有至少 3 个角色槽位，当前为 {len(slots)} 个")
    number = _PEOPLE_NUMBER_WORDS[count]
    if count == 1:
        people_prompt = "exactly 1 person"
    else:
        people_prompt = f"exactly {number} people, {number} separate bodies"
    return count, people_prompt


def _solo_r18_pose(
    preset_id: str,
    category: str,
    label: str,
    translation: str,
    tags: list[str],
    contact_points: list[str],
    *,
    camera: str = "全身",
    sequence: str = "进行中",
    intensity: str = "强化",
    compatibility: list[str] | None = None,
) -> dict:
    camera_en = {
        "全景": "wide",
        "全身": "full-body",
        "中景": "medium",
        "特写": "close detail",
        "俯视": "top-down",
        "仰视": "low-angle",
    }.get(camera, "full-body")
    draw_prompt = (
        f"exactly 1 anime woman in one {camera_en} shot, {', '.join(tags)}, "
        "one complete body, exactly one head, two arms and two legs, "
        "clear hands and feet, coherent stylized anatomy, uncensored anatomy, "
        "no second person, no extra limbs, no missing limbs, no merged body, "
        "no cropped body"
    )
    return _pose_preset(
        preset_id,
        category,
        label,
        translation,
        tags,
        people="单人",
        orientation="单人",
        role_slots=["主体"],
        body_separation=False,
        contact_points=contact_points,
        camera=camera,
        sequence=sequence,
        rating="R18",
        intensity=intensity,
        draw_prompt=draw_prompt,
        compatibility=compatibility,
    )


def _duo_r18_pose(
    preset_id: str,
    category: str,
    label: str,
    translation: str,
    tags: list[str],
    *,
    orientation: str,
    role_slots: list[str],
    contact_points: list[str],
    action_prompt: str,
    camera: str = "全身",
    sequence: str = "进行中",
    intensity: str = "强化",
    compatibility: list[str] | None = None,
) -> dict:
    subject = {
        "男女": "exactly 2 separate adult anime characters, one adult woman and one adult man",
        "女女": "exactly 2 separate adult anime women",
        "中性": "exactly 2 separate adult anime characters",
    }.get(orientation, "exactly 2 separate adult anime characters")
    draw_prompt = (
        f"{subject} in one continuous scene; {action_prompt}; "
        "both complete bodies visible, exactly one head, two arms and two legs per character, "
        "clear separate silhouettes, coherent stylized anatomy, uncensored anatomy, "
        "no extra people, no collage"
    )
    return _pose_preset(
        preset_id,
        category,
        label,
        translation,
        tags,
        people="双人",
        orientation=orientation,
        role_slots=role_slots,
        body_separation=False,
        contact_points=contact_points,
        camera=camera,
        sequence=sequence,
        rating="R18",
        intensity=intensity,
        draw_prompt=draw_prompt,
        compatibility=compatibility,
    )


POSE_PRESETS = [
    {
        "id": "lying_back",
        "image": "/pose-presets/lying_back.png",
        "category": "躺姿",
        "label": "仰躺",
        "translation": "人物仰面平躺，视线看向镜头",
        "tags": ["lying", "on back", "looking at viewer"],
    },
    {
        "id": "lying_side",
        "image": "/pose-presets/lying_side.png",
        "category": "躺姿",
        "label": "侧躺",
        "translation": "人物侧卧，身体自然弯曲",
        "tags": ["lying", "side lying"],
    },
    {
        "id": "kneeling",
        "image": "/pose-presets/kneeling.png",
        "category": "跪姿",
        "label": "跪姿",
        "translation": "人物跪在地上，膝部着地",
        "tags": ["kneeling"],
    },
    {
        "id": "doggy",
        "image": "/pose-presets/doggy.png",
        "category": "背后位",
        "label": "后入式",
        "translation": "女方四肢着地，男方从后方进入",
        "tags": ["from behind", "doggystyle"],
    },
    {
        "id": "doggy_standing",
        "image": "/pose-presets/doggy_standing.png",
        "category": "背后位",
        "label": "站姿后入",
        "translation": "女方站立弯腰，男方从后方进入",
        "tags": ["standing", "bent over", "from behind", "doggystyle"],
    },
    {
        "id": "prone_bone",
        "image": "/pose-presets/prone_bone.png",
        "category": "背后位",
        "label": "俯卧后入",
        "translation": "女方俯卧，男方压覆并从后方进入",
        "tags": ["prone bone", "lying", "from behind"],
    },
    {
        "id": "cowgirl",
        "image": "/pose-presets/cowgirl.png",
        "category": "骑乘位",
        "label": "骑乘位",
        "translation": "女方坐在男方身上面向对方",
        "tags": ["cowgirl position"],
    },
    {
        "id": "reverse_cowgirl",
        "image": "/pose-presets/reverse_cowgirl.png",
        "category": "骑乘位",
        "label": "反向骑乘位",
        "translation": "女方背对男方坐在身上",
        "tags": ["reverse cowgirl position"],
    },
    {
        "id": "missionary",
        "image": "/pose-presets/missionary.png",
        "category": "常规",
        "label": "传教士",
        "translation": "女方仰躺，男方在上方相对进入",
        "tags": ["missionary position"],
    },
    {
        "id": "lotus",
        "image": "/pose-presets/lotus.png",
        "category": "常规",
        "label": "莲花坐抱",
        "translation": "面对面坐着交合，腿部交叉环绕",
        "tags": ["lotus position", "sitting", "intercourse"],
    },
    {
        "id": "spooning",
        "image": "/pose-presets/spooning.png",
        "category": "侧位",
        "label": "侧卧拥抱",
        "translation": "两人同向侧卧，身体贴合拥抱",
        "tags": ["spooning"],
    },
    {
        "id": "side_sex",
        "image": "/pose-presets/side_sex.png",
        "category": "侧位",
        "label": "侧卧性交",
        "translation": "侧卧位交合，适合展示身体线条",
        "tags": ["sideways intercourse", "lying", "side lying"],
    },
    {
        "id": "standing",
        "image": "/pose-presets/standing.png",
        "category": "站姿",
        "label": "站立",
        "translation": "人物站立，适合全身展示",
        "tags": ["standing"],
    },
    {
        "id": "sitting_lap",
        "image": "/pose-presets/sitting_lap.png",
        "category": "坐姿",
        "label": "坐腿",
        "translation": "人物坐在另一人腿上，面向对方",
        "tags": ["sitting on lap"],
    },
    {
        "id": "mating_press",
        "image": "/pose-presets/mating_press.png",
        "category": "站立",
        "label": "抵墙式",
        "translation": "女方背靠墙面，男方从前方进入",
        "tags": ["mating press", "against wall"],
    },
    {
        "id": "kneeling_blowjob",
        "image": "/pose-presets/kneeling_blowjob.png",
        "category": "口交位",
        "label": "跪姿口交",
        "translation": "女方跪姿进行口交",
        "tags": ["kneeling", "fellatio", "blowjob"],
    },
    {
        "id": "sixty_nine",
        "image": "/pose-presets/sixty_nine.png",
        "category": "口交位",
        "label": "69 式",
        "translation": "双方倒转方向同时口交",
        "tags": ["69", "fellatio", "cunnilingus"],
    },
    {
        "id": "handjob",
        "image": "/pose-presets/handjob.png",
        "category": "手交",
        "label": "手交",
        "translation": "用手对男性器官进行刺激",
        "tags": ["handjob", "hand on penis"],
    },
    {
        "id": "footjob",
        "image": "/pose-presets/footjob.png",
        "category": "足交",
        "label": "足交",
        "translation": "用足部对男性器官进行刺激",
        "tags": ["footjob"],
    },
    {
        "id": "bent_over_desk",
        "image": "/pose-presets/bent_over_desk.png",
        "category": "背后位",
        "label": "桌边后入",
        "translation": "女方俯身撑在桌边，男方从后方进入",
        "tags": ["bent over", "desk", "from behind", "doggystyle"],
    },
    {
        "id": "squatting_cowgirl",
        "image": "/pose-presets/squatting_cowgirl.png",
        "category": "骑乘位",
        "label": "蹲坐骑乘",
        "translation": "女方下蹲跨坐于男方身上，骑乘位",
        "tags": ["squatting", "cowgirl position", "riding"],
    },
    {
        "id": "folded_missionary",
        "image": "/pose-presets/folded_missionary.png",
        "category": "常规",
        "label": "折腿位",
        "translation": "女方双腿折向胸口，男方在上方进入",
        "tags": ["folded legs", "missionary position", "knees to chest"],
    },
    {
        "id": "legs_over_shoulder",
        "image": "/pose-presets/legs_over_shoulder.png",
        "category": "常规",
        "label": "扛腿位",
        "translation": "女方双腿搭在男方肩上，面对面交合",
        "tags": ["legs over shoulder", "missionary position"],
    },
    {
        "id": "scissors",
        "image": "/pose-presets/scissors.png",
        "category": "侧位",
        "label": "剪刀式",
        "translation": "双方侧卧双腿交叉交合",
        "tags": ["scissors position", "intercourse"],
    },
    {
        "id": "lifted_standing",
        "image": "/pose-presets/lifted_standing.png",
        "category": "站姿",
        "label": "站立抱举",
        "translation": "男方站立抱举女方，女方面向男方交合",
        "tags": ["standing", "lifted", "carried sex"],
    },
    {
        "id": "standing_blowjob",
        "image": "/pose-presets/standing_blowjob.png",
        "category": "口交位",
        "label": "站姿口交",
        "translation": "女方站立或半蹲为站姿男方口交",
        "tags": ["standing", "fellatio", "blowjob"],
    },
    {
        "id": "side_leg_up",
        "image": "/pose-presets/side_leg_up.png",
        "category": "侧位",
        "label": "侧卧抬腿",
        "translation": "侧卧姿势中抬起一条腿便于进入",
        "tags": ["side lying", "leg up", "intercourse"],
    },
    {
        "id": "anal_doggy",
        "image": "/pose-presets/anal_doggy.png",
        "category": "背后位",
        "label": "后入肛交",
        "translation": "以背后位进行肛交",
        "tags": ["doggystyle", "from behind", "anal sex"],
    },
    {
        "id": "anal_side",
        "image": "/pose-presets/anal_side.png",
        "category": "侧位",
        "label": "侧卧肛交",
        "translation": "侧卧拥抱姿势下进行肛交",
        "tags": ["spooning", "anal sex", "sideways intercourse"],
    },
    {
        "id": "face_sitting",
        "image": "/pose-presets/face_sitting.png",
        "category": "口交位",
        "label": "骑脸",
        "translation": "女方坐于男方脸上接受口交",
        "tags": ["face sitting", "cunnilingus", "oral"],
    },
    {
        "id": "piledriver",
        "image": "/pose-presets/piledriver.png",
        "category": "常规",
        "label": "倒立位",
        "translation": "女方头肩着地、双腿高抬，男方进入",
        "tags": ["piledriver position", "legs up", "vaginal sex"],
    },
    {
        "id": "reverse_lap",
        "image": "/pose-presets/reverse_lap.png",
        "category": "坐姿",
        "label": "反向坐腿",
        "translation": "女方背对男方坐在腿上，男方从后方进入",
        "tags": ["sitting on lap", "facing away", "from behind", "intercourse"],
    },
    {
        "id": "bed_edge",
        "image": "/pose-presets/bed_edge.png",
        "category": "常规",
        "label": "床边腿垂",
        "translation": "女方躺在床边、双腿垂下，男方站立进入",
        "tags": ["edge of bed", "legs hanging", "missionary position", "intercourse"],
    },
    {
        "id": "standing_reverse",
        "image": "/pose-presets/standing_reverse.png",
        "category": "站姿",
        "label": "背向站立",
        "translation": "女方背对男方站立，男方从后方进入",
        "tags": ["standing", "facing away", "from behind", "intercourse"],
    },
    {
        "id": "anal_cowgirl",
        "image": "/pose-presets/anal_cowgirl.png",
        "category": "骑乘位",
        "label": "骑乘肛交",
        "translation": "女方骑坐在男方身上进行肛交",
        "tags": ["cowgirl position", "anal sex", "facing each other"],
    },
    {
        "id": "missionary_anal",
        "image": "/pose-presets/missionary_anal.png",
        "category": "常规",
        "label": "传教士肛交",
        "translation": "女方面上仰躺，男方在上方进行肛交",
        "tags": ["missionary position", "anal sex"],
    },
    {
        "id": "cunnilingus_kneeling",
        "image": "/pose-presets/cunnilingus_kneeling.png",
        "category": "口交位",
        "label": "跪姿舔阴",
        "translation": "男方跪姿为站立/跪坐的女方舔阴",
        "tags": ["kneeling", "cunnilingus", "oral"],
    },
    {
        "id": "oral_lying",
        "image": "/pose-presets/oral_lying.png",
        "category": "口交位",
        "label": "躺卧口交",
        "translation": "女方俯身为躺卧的男方口交",
        "tags": ["lying", "fellatio", "oral"],
    },
    {
        "id": "wheelbarrow",
        "image": "/pose-presets/wheelbarrow.png",
        "category": "背后位",
        "label": "手推车式",
        "translation": "女方双手撑地/床，男方从后方握住髋部进入",
        "tags": ["wheelbarrow position", "standing", "from behind"],
    },
    {
        "id": "threesome_2f1m",
        "image": "/pose-presets/threesome_2f1m.png",
        "category": "3P",
        "label": "一男两女",
        "translation": "两名女性同时服务/骑乘一名男性",
        "tags": ["threesome", "2girls 1boy", "group sex"],
        "draw_prompt": "exactly 3 separate people in one wide shot: 1 male lying on his back and 2 females; female A straddles his hips in cowgirl position facing him while he penetrates her pussy, female B kneels beside his head and kisses female A while caressing his chest; all three faces and torsos visible, clear contact mapping, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "threesome_2m1f",
        "image": "/pose-presets/threesome_2m1f.png",
        "category": "3P",
        "label": "两男一女",
        "translation": "一名女性与两名男性进行双插/夹心",
        "tags": ["threesome", "2boys 1girl", "group sex"],
        "draw_prompt": "exactly 3 separate people in one wide shot: 1 female on all fours and 2 males; male A kneels behind her and penetrates her pussy, male B kneels in front of her face and she performs fellatio on him; side view shows all three bodies, faces, and contact points clearly, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "threesome_oral",
        "image": "/pose-presets/threesome_oral.png",
        "category": "3P",
        "label": "双人口交",
        "translation": "两名女性同时为一名男性口交/手交",
        "tags": ["threesome", "2girls 1boy", "fellatio", "handjob", "group sex"],
        "draw_prompt": "exactly 3 separate people in one wide shot: 1 male standing and 2 females kneeling; female A kneels directly in front of the male and performs fellatio on him, female B kneels beside female A and strokes the base of his penis with one hand; clear contact mapping between female A's mouth, female B's hand, and the male's penis, both women face his body, three faces and upper bodies visible, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "dp_doggy",
        "image": "/pose-presets/dp_doggy.png",
        "category": "群交",
        "label": "双插后入",
        "translation": "女方四肢着地，两男分别进行阴道与肛交",
        "tags": ["2boys 1girl", "double penetration", "doggystyle", "group sex"],
        "draw_prompt": "exactly 3 separate people in one wide shot: 1 female on all fours and 2 males kneeling close behind her; male A enters her pussy from below while male B enters her anus from above, both penises visibly meeting her hips in double penetration doggystyle; side rear view shows three separate heads and bodies, clear contact points, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "dp_missionary",
        "image": "/pose-presets/dp_missionary.png",
        "category": "群交",
        "label": "双插传教士",
        "translation": "女方仰躺，两男分别进行阴道与肛交",
        "tags": ["2boys 1girl", "double penetration", "missionary position", "group sex"],
        "draw_prompt": "exactly 3 separate people in one wide shot: 1 female lying on her back with raised hips and knees pulled back, and 2 males; male A kneels between her spread thighs and penetrates her pussy, male B kneels behind her raised hips and penetrates her anus; side angle clearly shows both insertion angles, all three faces and torsos unobstructed, double penetration missionary, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "spitroast_standing",
        "image": "/pose-presets/spitroast_standing.png",
        "category": "群交",
        "label": "站姿夹心",
        "translation": "女方位于两男之间，前后同时进入/口交",
        "tags": ["2boys 1girl", "spitroast", "standing", "group sex"],
        "draw_prompt": "exactly 3 separate people in one wide shot: 1 female bending forward between 2 standing males; male A stands in front and she performs fellatio on him, male B stands directly behind her and penetrates her pussy while holding her hips; side view shows both contact points and all three bodies, standing spitroast, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "orgy_four",
        "image": "/pose-presets/orgy_four.png",
        "category": "群交",
        "label": "四人混战",
        "translation": "四名角色同床进行群交",
        "tags": ["four people", "orgy", "group sex"],
        "draw_prompt": "exactly 4 separate people in one wide shot on a bed: 2 females and 2 males; female A rides male A in cowgirl as he penetrates her pussy, female B lies beside them and performs fellatio on male B while male B kneels over her; four distinct heads and bodies, both pairs clearly separated, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "train_line",
        "image": "/pose-presets/train_line.png",
        "category": "群交",
        "label": "火车式",
        "translation": "多名角色排队式从后连续交合",
        "tags": ["gangbang", "train", "group sex"],
        "draw_prompt": "exactly 4 separate people in one wide shot, side view: 1 female and 3 males in a single-file gangbang queue; the female kneels on all fours, male A kneels directly behind her and penetrates her pussy, male B kneels directly behind male A and waits with both hands on male A's hips, male C stands in front of the female and she performs fellatio on him; each male occupies a different depth plane so all four full bodies, heads, and limbs remain separately visible, clear contact points at the female's mouth and hand on male C, male A's penis in her pussy, and male B's hands on male A's hips, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "lesbian_embrace",
        "image": "/pose-presets/lesbian_embrace.png",
        "category": "女同",
        "label": "接吻爱抚",
        "translation": "两名女性面对面接吻并互相爱抚身体",
        "tags": ["lesbian", "kissing", "groping", "fondling"],
    },
    {
        "id": "lesbian_69",
        "image": "/pose-presets/lesbian_69.png",
        "category": "女同",
        "label": "女同 69",
        "translation": "两名女性头脚相对同时舔阴",
        "tags": ["lesbian", "69", "cunnilingus", "mutual oral"],
    },
    {
        "id": "lesbian_face_sitting",
        "image": "/pose-presets/lesbian_face_sitting.png",
        "category": "女同",
        "label": "骑脸舔阴",
        "translation": "一名女性坐在另一名女性脸上接受舔阴",
        "tags": ["face sitting", "cunnilingus", "lesbian"],
    },
    {
        "id": "tribadism_riding",
        "image": "/pose-presets/tribadism_riding.png",
        "category": "女同",
        "label": "骑乘磨镜",
        "translation": "一名女性骑在另一名女性身上用阴部摩擦",
        "tags": ["tribadism", "grinding", "lesbian"],
    },
    {
        "id": "scissoring",
        "image": "/pose-presets/scissoring.png",
        "category": "女同",
        "label": "剪刀磨阴",
        "translation": "两名女性面对面侧卧交叉双腿用阴部摩擦",
        "tags": ["scissoring", "tribadism", "lesbian"],
    },
    {
        "id": "fingering",
        "image": "/pose-presets/fingering.png",
        "category": "女同",
        "label": "指交",
        "translation": "一名女性用手指插入另一名女性阴道并爱抚",
        "tags": ["fingering", "lesbian", "sex"],
    },
    {
        "id": "strap_doggy",
        "image": "/pose-presets/strap_doggy.png",
        "category": "女同",
        "label": "穿戴后入",
        "translation": "一名女性佩戴假阳具从后方插入另一名女性",
        "tags": ["strap-on", "doggystyle", "lesbian"],
    },
    {
        "id": "strap_missionary",
        "image": "/pose-presets/strap_missionary.png",
        "category": "女同",
        "label": "穿戴传教士",
        "translation": "一名女性佩戴假阳具在另一名女性上方插入",
        "tags": ["strap-on", "missionary position", "lesbian"],
    },
    {
        "id": "side_saddle",
        "image": "/pose-presets/side_saddle.png",
        "category": "骑乘位",
        "label": "侧骑位",
        "translation": "女方侧坐于男方身上骑乘",
        "tags": ["side saddle", "cowgirl position", "riding"],
    },
    {
        "id": "reverse_lying_top",
        "image": "/pose-presets/reverse_lying_top.png",
        "category": "骑乘位",
        "label": "反向躺骑",
        "translation": "女方躺卧叠于男方身上、背向交合",
        "tags": ["lying", "reverse cowgirl", "riding"],
    },
    {
        "id": "kneeling_face_to_face",
        "image": "/pose-presets/kneeling_face_to_face.png",
        "category": "跪姿",
        "label": "对跪位",
        "translation": "双方相对跪立，男方进入",
        "tags": ["kneeling", "facing each other", "intercourse"],
    },
    {
        "id": "carried_reverse",
        "image": "/pose-presets/carried_reverse.png",
        "category": "站姿",
        "label": "背后抱举",
        "translation": "男方从背后抱起女方，女方双腿环绕",
        "tags": ["standing", "lifted", "from behind", "intercourse"],
    },
    {
        "id": "prone_anal",
        "image": "/pose-presets/prone_anal.png",
        "category": "背后位",
        "label": "俯卧肛交",
        "translation": "女方俯卧，男方从后方进行肛交",
        "tags": ["prone bone", "anal sex", "lying"],
    },
    {
        "id": "frog_style",
        "image": "/pose-presets/frog_style.png",
        "category": "骑乘位",
        "label": "青蛙式",
        "translation": "女方蹲坐沉跨于男方身上，由下方进入",
        "tags": ["froggy style", "squatting", "cowgirl position"],
    },
    {
        "id": "bridge",
        "image": "/pose-presets/bridge.png",
        "category": "常规",
        "label": "拱桥式",
        "translation": "女方以肩头与脚撑地拱起腰臀，男方进入",
        "tags": ["bridge position", "arched", "intercourse"],
    },
    {
        "id": "pretzel",
        "image": "/pose-presets/pretzel.png",
        "category": "侧位",
        "label": "麻花式",
        "translation": "双方侧卧身体交错，腿部缠绕交合",
        "tags": ["pretzel position", "side lying", "intercourse"],
    },
    {
        "id": "amazon",
        "image": "/pose-presets/amazon.png",
        "category": "骑乘位",
        "label": "亚马逊位",
        "translation": "女方仰躺叠于男方身上、背向交合",
        "tags": ["amazon position", "reverse", "riding"],
    },
    {
        "id": "anal_reverse_cowgirl",
        "image": "/pose-presets/anal_reverse_cowgirl.png",
        "category": "骑乘位",
        "label": "反向骑乘肛交",
        "translation": "女方背对男方骑坐进行肛交",
        "tags": ["reverse cowgirl position", "anal sex"],
    },
    {
        "id": "reverse_squat_cowgirl",
        "image": "/pose-presets/reverse_squat_cowgirl.png",
        "category": "骑乘位",
        "label": "反向蹲骑",
        "translation": "女方背对男方下蹲骑乘",
        "tags": ["reverse cowgirl", "squatting", "riding"],
    },
    {
        "id": "cowgirl_leaning_back",
        "image": "/pose-presets/cowgirl_leaning_back.png",
        "category": "骑乘位",
        "label": "后仰骑乘",
        "translation": "女方骑乘时向后仰靠，男方支撑",
        "tags": ["cowgirl position", "leaning back", "riding"],
    },
    {
        "id": "cowgirl_leaning_forward",
        "image": "/pose-presets/cowgirl_leaning_forward.png",
        "category": "骑乘位",
        "label": "前俯骑乘",
        "translation": "女方骑乘时向前俯身贴近男方",
        "tags": ["cowgirl position", "leaning forward", "riding"],
    },
    {
        "id": "missionary_legs_waist",
        "image": "/pose-presets/missionary_legs_waist.png",
        "category": "常规",
        "label": "缠腰位",
        "translation": "女方双腿环绕男方腰际的传教士位",
        "tags": ["missionary position", "legs wrapped around waist"],
    },
    {
        "id": "missionary_pillow",
        "image": "/pose-presets/missionary_pillow.png",
        "category": "常规",
        "label": "垫腰位",
        "translation": "女方腰臀垫高、男方在上方进入",
        "tags": ["missionary position", "pillow under hips", "hips elevated"],
    },
    {
        "id": "standing_side_entry",
        "image": "/pose-presets/standing_side_entry.png",
        "category": "站姿",
        "label": "侧入站立",
        "translation": "双方站立，男方从侧方进入",
        "tags": ["standing", "side entry", "intercourse"],
    },
    {
        "id": "anal_reverse_lap",
        "image": "/pose-presets/anal_reverse_lap.png",
        "category": "坐姿",
        "label": "反向坐肛",
        "translation": "女方背对男方坐在腿上肛交",
        "tags": ["sitting on lap", "reverse", "anal sex"],
    },
    {
        "id": "anal_side_saddle",
        "image": "/pose-presets/anal_side_saddle.png",
        "category": "骑乘位",
        "label": "侧骑肛交",
        "translation": "女方侧坐骑乘进行肛交",
        "tags": ["side saddle", "anal sex", "riding"],
    },
    {
        "id": "wheelbarrow_anal",
        "image": "/pose-presets/wheelbarrow_anal.png",
        "category": "背后位",
        "label": "手推车肛交",
        "translation": "女方双手撑地、男方自后方肛交",
        "tags": ["wheelbarrow position", "anal sex"],
    },
    {
        "id": "lesbian_mutual_fingering",
        "image": "/pose-presets/lesbian_mutual_fingering.png",
        "category": "女同",
        "label": "相互指交",
        "translation": "两名女性同时为对方指交",
        "tags": ["lesbian", "mutual fingering", "fingering"],
    },
    {
        "id": "lesbian_spoon_fingering",
        "image": "/pose-presets/lesbian_spoon_fingering.png",
        "category": "女同",
        "label": "侧卧指交",
        "translation": "一名女性从身后搂抱并为另一名女性指交",
        "tags": ["lesbian", "spooning", "fingering"],
    },
    {
        "id": "lesbian_standing_grinding",
        "image": "/pose-presets/lesbian_standing_grinding.png",
        "category": "女同",
        "label": "站立磨阴",
        "translation": "两名女性站立相拥并磨擦阴部",
        "tags": ["lesbian", "standing", "tribadism", "grinding"],
    },
    {
        "id": "lesbian_face_to_face_grinding",
        "image": "/pose-presets/lesbian_face_to_face_grinding.png",
        "category": "女同",
        "label": "面对面磨阴",
        "translation": "两名女性面对面贴合摩擦阴部",
        "tags": ["lesbian", "face to face", "tribadism"],
    },
    {
        "id": "anal_standing_reverse",
        "image": "/pose-presets/anal_standing_reverse.png",
        "category": "站姿",
        "label": "背向肛交",
        "translation": "女方背对男方站立，男方自后方肛交",
        "tags": ["standing", "reverse", "anal sex"],
    },
    {
        "id": "handjob_lying",
        "image": "/pose-presets/handjob_lying.png",
        "category": "手交",
        "label": "卧姿手交",
        "translation": "女方为躺卧的男方手交",
        "tags": ["handjob", "lying"],
    },
    {
        "id": "footjob_lap",
        "image": "/pose-presets/footjob_lap.png",
        "category": "足交",
        "label": "坐姿足交",
        "translation": "女方坐在椅上用脚为男方足交",
        "tags": ["footjob", "sitting"],
    },
    {
        "id": "cunnilingus_lying",
        "image": "/pose-presets/cunnilingus_lying.png",
        "category": "口交位",
        "label": "仰躺舔阴",
        "translation": "女方仰躺，男方跪于腿间舔阴",
        "tags": ["cunnilingus", "lying", "oral"],
    },
    {
        "id": "fellatio_handjob_dual",
        "image": "/pose-presets/fellatio_handjob_dual.png",
        "category": "手交",
        "label": "手口并用",
        "translation": "女方同时用口与手刺激男方",
        "tags": ["handjob", "fellatio", "hand on penis"],
    },
    {
        "id": "lesbian_orgy",
        "image": "/pose-presets/lesbian_orgy.png",
        "category": "群交",
        "label": "女同群交",
        "translation": "三名以上女性互相舔阴与指交",
        "tags": ["lesbian", "orgy", "group sex"],
        "draw_prompt": "exactly 4 separate women in one wide shot: woman A lies on her back while woman B kneels above her face and receives cunnilingus, woman C kisses woman D and fingers her thigh and pussy; clear contact mapping between woman A's mouth and woman B's vulva, and between woman C's hand, mouth, and woman D's body, two clearly paired couples on one bed, four distinct heads and bodies, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "dp_spoon",
        "image": "/pose-presets/dp_spoon.png",
        "category": "群交",
        "label": "侧卧双插",
        "translation": "女方侧卧，两名男性分别进行阴道与肛交",
        "tags": ["2boys 1girl", "double penetration", "spooning", "group sex"],
        "draw_prompt": "exactly 3 separate people in one wide shot: 1 female lying on her side and 2 males; male A kneels in front of her facing her and penetrates her pussy, male B spoons her from behind and penetrates her anus; side view clearly shows both insertions and three separate bodies, double penetration spooning, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "dp_standing",
        "image": "/pose-presets/dp_standing.png",
        "category": "群交",
        "label": "站姿双插",
        "translation": "女方站立/悬空，两名男性分别前后进入",
        "tags": ["2boys 1girl", "double penetration", "standing", "group sex"],
        "draw_prompt": "exactly 3 separate people in one wide shot: 1 female lifted and held between 2 standing males; male A supports her thighs from the front and penetrates her pussy, male B stands behind her and penetrates her anus while holding her waist; side view shows both penetration contact points, the female suspended between them with three separate bodies, double penetration standing, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "mmf_double_vaginal",
        "image": "/pose-presets/mmf_double_vaginal.png",
        "category": "群交",
        "label": "双龙入洞",
        "translation": "两名男性同时进入同一名女性的阴道",
        "tags": ["2boys 1girl", "double vaginal", "threesome", "group sex"],
        "draw_prompt": "exactly 3 separate people in one wide shot: 1 female lying on her back at the edge of a bed with legs raised, and 2 males kneeling side by side between her thighs; both male penises enter the same vaginal opening at the same time, their hips forming a visible V shape, double vaginal, side angle shows three separate bodies and both insertions, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "ffm_face_and_cowgirl",
        "image": "/pose-presets/ffm_face_and_cowgirl.png",
        "category": "3P",
        "label": "女上骑脸",
        "translation": "一名女性骑乘男方，另一名女性坐脸舔阴",
        "tags": ["2girls 1boy", "threesome", "cowgirl", "face sitting", "group sex"],
        "draw_prompt": "exactly 3 separate people in one wide shot: 1 male lying on his back and 2 females; female A straddles his hips in cowgirl as he penetrates her pussy, female B kneels over his face and receives cunnilingus while leaning forward and holding his chest; clear contact mapping between the male's penis and female A's pussy, and between the male's mouth and female B's vulva, side view keeps the male face and both female bodies visible, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "mmf_cowgirl_anal",
        "image": "/pose-presets/mmf_cowgirl_anal.png",
        "category": "3P",
        "label": "双人骑乘肛交",
        "translation": "女方骑乘一名男性肛交，同时为另一名男性口交",
        "tags": ["threesome", "2boys 1girl", "cowgirl", "anal sex", "fellatio"],
        "draw_prompt": "exactly 3 separate people in one wide shot: 1 female and 2 males; male A lies on his back while the female straddles him in reverse cowgirl with his penis inside her anus, male B kneels in front of her face and she performs fellatio on him; side view shows both contact points and three separate bodies, no extra people, no missing people, no merged bodies",
    },
    {
        "id": "ffm_spitroast",
        "image": "/pose-presets/ffm_spitroast.png",
        "category": "3P",
        "label": "两女一男夹心",
        "translation": "男性位于两名女性之间，同时接受前后服务",
        "tags": ["threesome", "2girls 1boy", "spitroast", "group sex"],
        "draw_prompt": "exactly 3 separate people in one wide shot: 1 male standing between 2 kneeling females; female A kneels directly in front of him and performs fellatio, female B kneels behind him and reaches around to stroke the base of his penis and testicles; clear contact points at female A's mouth and the tip of his penis, and at female B's hands, his penis base, and testicles, side view shows the male between two distinct women, all faces and bodies visible, no extra people, no missing people, no merged bodies",
    },
    # 单人构图（5）
    _pose_preset("solo_supported_sit", "单人构图", "支撑坐姿", "角色以单手或双手支撑身体坐在地面，重心明确", ["solo", "sitting", "hand support", "weight shift"], people="单人", orientation="单人", role_slots=["主体"], camera="全身", sequence="进行中", contact_points=["手部与支撑面", "臀部与地面"], rating="普通"),
    _pose_preset("solo_kneeling_twist", "单人构图", "跪姿转体", "角色双膝跪地并向侧后方转体，脊柱线条清晰", ["solo", "kneeling", "twist", "looking back"], people="单人", orientation="单人", role_slots=["主体"], camera="全身", sequence="进行中", contact_points=["膝部与地面"], rating="普通"),
    _pose_preset("solo_side_recline", "单人构图", "侧卧支撑", "角色侧卧并用前臂支撑上身，腿部自然交叠", ["solo", "side reclining", "forearm support", "legs crossed"], people="单人", orientation="单人", role_slots=["主体"], camera="中景", sequence="进行中", contact_points=["前臂与支撑面", "髋部与地面"], rating="普通"),
    _pose_preset("solo_prone_arch", "单人构图", "俯卧回望", "角色俯卧并抬起上身回望镜头，肩背形成弧线", ["solo", "prone", "back arch", "looking back"], people="单人", orientation="单人", role_slots=["主体"], camera="中景", sequence="进行中", contact_points=["胸腹与地面"], rating="普通"),
    _pose_preset("solo_mirror_stance", "单人构图", "镜前站姿", "角色在落地镜前站立，肢体左右各一且镜像关系明确", ["solo", "standing", "mirror", "full body reflection"], people="单人", orientation="单人", role_slots=["主体"], camera="全身", sequence="进行中", contact_points=["双脚与地面"], rating="普通", compatibility=["scene_mirror_studio"]),

    # 双人接触（10）
    _pose_preset("duo_face_to_face_seated", "双人接触", "面对面坐姿", "两名角色相对而坐，膝盖交错并保持独立身体轮廓", ["2 people", "face to face", "sitting", "knees touching"], people="双人", orientation="男女", role_slots=["角色A", "角色B"], contact_points=["双膝", "手部"], camera="全身", sequence="进行中"),
    _pose_preset("duo_reverse_sitting_lap", "双人接触", "反向坐腿", "角色B背对角色A坐在其腿上，两人身体分离且接触点清楚", ["2 people", "reverse sitting on lap", "back to chest"], people="双人", orientation="男女", role_slots=["角色A", "角色B"], contact_points=["臀部与大腿", "背部与胸口"], camera="中景", sequence="进行中"),
    _pose_preset("duo_standing_front_carry", "双人接触", "正面站立抱举", "角色A站立抱举角色B，角色B面向角色A并环绕腿部", ["2 people", "standing carry", "front hug", "legs wrapped"], people="双人", orientation="男女", role_slots=["支撑者", "被抱者"], contact_points=["手臂", "腰腿"], camera="全身", sequence="进行中"),
    _pose_preset("duo_kneeling_hug", "双人接触", "跪姿相拥", "两名角色相对跪坐并近距离相拥，双人头部和四肢分别可见", ["2 people", "kneeling hug", "face to face", "close embrace"], people="双人", orientation="男女", role_slots=["角色A", "角色B"], contact_points=["胸口", "手臂"], camera="中景", sequence="前戏"),
    _pose_preset("duo_side_by_side_contact", "双人接触", "并侧身体接触", "两名角色并侧坐，肩膀、腰部和手部形成单一接触链", ["2 people", "side by side", "shoulder contact", "waist touch"], people="双人", orientation="中性", role_slots=["角色A", "角色B"], contact_points=["肩部", "腰部", "手部"], camera="全身", sequence="进行中"),
    _pose_preset("duo_back_to_back_seated", "双人接触", "背靠背坐姿", "两名角色背靠背坐地，背部和肩部接触但四肢完全分离", ["2 people", "back to back", "sitting", "shoulder contact"], people="双人", orientation="中性", role_slots=["角色A", "角色B"], contact_points=["背部", "肩部"], camera="全身", sequence="结束"),
    _pose_preset("duo_head_to_toe", "双人接触", "反向卧姿", "两名角色反向平躺，头部靠近彼此髋部且身体不重叠", ["2 people", "lying head to toe", "opposite directions", "separate bodies"], people="双人", orientation="男女", role_slots=["角色A", "角色B"], contact_points=["腰髋区域"], camera="俯视", sequence="进行中"),
    _pose_preset("duo_suspended_embrace", "双人接触", "悬浮相拥", "两名角色在悬浮环境中相拥，四肢与身体轮廓分别清楚", ["2 people", "suspended embrace", "floating", "separate silhouettes"], people="双人", orientation="男女", role_slots=["角色A", "角色B"], contact_points=["手臂", "腰部"], camera="全身", sequence="进行中", intensity="强化", compatibility=["scene_suspension_rig"]),
    _pose_preset("duo_wall_press_side", "双人接触", "侧向压墙", "角色A从侧面靠近角色B并单手撑墙，双方重心与接触点清楚", ["2 people", "wall press", "side view", "one hand on wall"], people="双人", orientation="男女", role_slots=["主动角色", "被靠近角色"], contact_points=["手与墙", "肩部"], camera="中景", sequence="前戏"),
    _pose_preset("duo_table_edge_seated", "双人接触", "桌边对坐", "两名角色分别在桌边对坐，手部与腿部接触清楚", ["2 people", "table edge", "sitting opposite", "knee contact"], people="双人", orientation="男女", role_slots=["角色A", "角色B"], contact_points=["桌面", "膝部", "手部"], camera="中景", sequence="进行中"),

    # 多人组合（8）
    _pose_preset("group_triangle_three", "多人组合", "三人三角构图", "三名角色呈三角位置，所有身体轮廓分离且无重叠粘连", ["exactly 3 people", "triangular formation", "group pose", "separate bodies"], people="多人", orientation="多人", role_slots=["角色A", "角色B", "角色C"], body_separation=True, contact_points=["手部", "肩部"], camera="全身", sequence="进行中", intensity="强化", draw_prompt="anime group photo of exactly 3 separate anime characters in a clean triangular formation: one at back center and two at front left and front right; full body head to toe, all faces and complete bodies visible, distinct everyday outfits, clear spacing between silhouettes"),
    _pose_preset("group_front_back_three", "多人组合", "三人前后错位", "三名角色呈前后错位队列，左右半区各至少一人且身体不重叠", ["exactly 3 people", "front and back formation", "staggered group", "separate bodies"], people="多人", orientation="多人", role_slots=["前景角色", "中景角色", "后景角色"], body_separation=True, contact_points=["手部", "腰部"], camera="全身", sequence="进行中", intensity="强化", draw_prompt="anime group photo of exactly 3 separate anime characters staggered in depth: one foreground left, one middle ground right, one background center; full body head to toe, every face and complete body visible, distinct outfits, strong depth separation"),
    _pose_preset("group_quad_center", "多人组合", "四人中心构图", "四名角色围绕中心站位，四点分布清楚且没有身体融合", ["exactly 4 people", "central group composition", "four distinct bodies", "group pose"], people="多人", orientation="多人", role_slots=["中心角色", "左侧角色", "右侧角色", "后方角色"], body_separation=True, contact_points=["手部"], camera="俯视", sequence="进行中", intensity="极限", draw_prompt="directly overhead 90-degree top-down anime scene of exactly 4 separate anime characters standing around one round central table, two on the left and two on the right; all four complete bodies visible on the floor plane, distinct outfits and faces, clear gaps between bodies"),
    _pose_preset("group_quad_balanced", "多人组合", "四人均衡分布", "四名角色左右各两人均衡分布，身体轮毂与肢体不交叠", ["exactly 4 people", "balanced left and right", "four separate bodies", "wide group shot"], people="多人", orientation="多人", role_slots=["左一", "左二", "右一", "右二"], body_separation=True, contact_points=["手部", "肩部"], camera="全景", sequence="进行中", intensity="极限", draw_prompt="wide anime group photo of exactly 4 separate anime characters standing two on the left and two on the right, full body head to toe, all four faces and complete bodies visible, distinct everyday outfits, generous spacing between every silhouette"),
    _pose_preset("group_mff_side_by_side", "多人组合", "两女一男并排", "两女一男并侧展开，三人身体轮廓与角色槽位互不混淆", ["exactly 3 people", "2 girls 1 boy", "side by side", "separate bodies"], people="多人", orientation="多人", role_slots=["女A", "女B", "男A"], body_separation=True, contact_points=["手部", "肩部"], camera="全身", sequence="进行中", intensity="强化", draw_prompt="wide anime group photo of exactly 3 separate anime characters standing side by side: 2 women and 1 man, full body head to toe, three faces and complete bodies visible, distinct clothing for each person, clear spacing and no overlapping silhouettes"),
    _pose_preset("group_mmf_side_by_side", "多人组合", "两男一女并排", "两名男性与一名女性并侧展开，三人四肢与头部数量完整", ["exactly 3 people", "2 boys 1 girl", "side by side", "separate bodies"], people="多人", orientation="多人", role_slots=["男A", "男B", "女A"], body_separation=True, contact_points=["手部", "肩部"], camera="全身", sequence="进行中", intensity="强化", draw_prompt="wide anime group photo of exactly 3 separate anime characters standing side by side: 2 men and 1 woman, full body head to toe, three faces and complete bodies visible, distinct clothing for each person, clear spacing and no overlapping silhouettes"),
    _pose_preset("group_observer_pair", "多人组合", "主体与观察者", "一名主体角色与两名观察者分区站立，左右半区关系清楚", ["exactly 3 people", "one central figure", "two observers", "left and right zones"], people="多人", orientation="多人", role_slots=["主体", "左观察者", "右观察者"], body_separation=True, contact_points=["无直接接触"], camera="全景", sequence="前戏", intensity="强化", draw_prompt="wide anime group photo of exactly 3 separate anime characters: one central woman in the foreground and two observers positioned left and right slightly behind her; all three faces, hands and full bodies visible, distinct outfits, clear depth separation"),
    _pose_preset("group_four_contact_chain", "多人组合", "四人接触链", "四名角色形成手部接触链，接触只发生在相邻角色之间", ["exactly 4 people", "contact chain", "four separate bodies", "group composition"], people="多人", orientation="多人", role_slots=["角色A", "角色B", "角色C", "角色D"], body_separation=True, contact_points=["手部"], camera="全景", sequence="进行中", intensity="极限", draw_prompt="wide anime group photo of exactly 4 separate anime characters standing in one straight line and holding hands with only the adjacent person, two characters on the left and two on the right; full body head to toe, all four faces and complete bodies visible, distinct outfits, clear gaps between torsos"),

    # 动作阶段（4）
    _pose_preset("stage_foreplay_kneeling", "动作阶段", "前戏跪姿阶段", "两名角色保持跪姿近距离互动，动作停留在前戏阶段且身体轮廓清楚", ["2 people", "foreplay", "kneeling", "close interaction"], people="双人", orientation="男女", role_slots=["主动角色", "回应角色"], contact_points=["手部", "肩部"], camera="中景", sequence="前戏"),
    _pose_preset("stage_restraint_kneeling", "动作阶段", "约束跪姿阶段", "一名角色跪姿，另一名角色手持约束道具保持示意性控制", ["2 people", "restraint pose", "kneeling", "symbolic control"], people="双人", orientation="男女", role_slots=["支配角色", "臣服角色"], contact_points=["手腕道具", "肩部"], camera="中景", sequence="约束", intensity="强化", compatibility=["scene_rope_bed", "scene_leather_harness_room"]),
    _pose_preset("stage_ongoing_side_sequence", "动作阶段", "进行中侧视阶段", "两名角色以侧视构图保持进行中的动作阶段，接触点明确且无双人融合", ["2 people", "ongoing action", "side view", "clear contact point"], people="双人", orientation="男女", role_slots=["角色A", "角色B"], contact_points=["腰髋区域", "手部"], camera="中景", sequence="进行中"),
    _pose_preset("stage_aftercare_embrace", "动作阶段", "事后照护相拥", "两名角色结束动作后相拥休息，面部放松并保留完整身体轮廓", ["2 people", "aftercare", "embrace", "resting"], people="双人", orientation="男女", role_slots=["角色A", "角色B"], contact_points=["胸口", "手臂"], camera="中景", sequence="结束"),

    # 镜头变体（3）
    _pose_preset("camera_close_contact", "镜头变体", "接触点近景", "以近景突出双手或肩部接触点，同时不裁掉关键身份特征", ["2 people", "close-up", "contact point", "hands and shoulders"], people="双人", orientation="中性", role_slots=["角色A", "角色B"], contact_points=["手部", "肩部"], camera="近景", sequence="进行中"),
    _pose_preset("camera_full_body_wide", "镜头变体", "双人全身远景", "以全身远景展示两名角色的完整轮廓、间距与重心", ["2 people", "full body", "wide shot", "clear spacing"], people="双人", orientation="中性", role_slots=["角色A", "角色B"], camera="全景", sequence="进行中", draw_prompt="zoomed out wide anime shot of exactly 2 separate anime characters standing one body width apart in a spacious room; full body from head to toe, feet and heads fully inside frame, both faces visible, no waist-up crop, no close-up, clear negative space around both bodies"),
    _pose_preset("camera_topdown_pair", "镜头变体", "俯视双人构图", "从正上方拍摄两名角色，左右半区、四肢和接触点分别清楚", ["2 people", "top down", "overhead view", "left and right zones"], people="双人", orientation="中性", role_slots=["左侧角色", "右侧角色"], contact_points=["手部", "腰髋区域"], camera="俯视", sequence="进行中", draw_prompt="directly overhead 90-degree top-down anime camera looking straight down at exactly 2 separate anime characters lying side by side on a large bed, one on the left and one on the right; both complete bodies visible on the same floor plane, heads at the top and feet at the bottom, faces and hands visible, no tilted perspective"),

    # SM/束缚（10）
    _pose_preset("sm_wrist_raise_restraint", "SM/束缚", "举腕约束姿态", "角色B双手腕由软质腕带固定在头顶横杆，角色A站在侧后方调整装饰扣件，两人轮廓清楚", ["2 people", "raised wrists", "soft wrist restraint pose", "decorative frame", "symbolic restraint", "clear body separation"], people="双人", orientation="中性", role_slots=["引导角色", "约束角色"], body_separation=True, contact_points=["手腕与软带", "横杆", "肩部"], camera="全身", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate anime characters in one wide shot: character B stands upright with both wrists raised inside soft decorative cuffs attached to an overhead padded frame, character A stands beside the frame adjusting a shoulder strap; both full bodies and faces visible, natural skin, clear gaps between bodies, static fashion pose", compatibility=["scene_wall_brace", "scene_rope_workshop"]),
    _pose_preset("sm_kneeling_collar_display", "SM/束缚", "跪姿项圈展示", "角色B端坐跪姿展示装饰性项圈，角色A在其侧方观察，项圈与软带保持静态可分离", ["2 people", "kneeling collar display", "decorative collar", "soft display strap", "static fashion pose", "separated silhouettes"], people="双人", orientation="中性", role_slots=["展示角色", "观察角色"], body_separation=True, contact_points=["项圈装饰", "手部"], camera="中景", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate anime characters in one medium shot: character B kneels upright in a calm display pose wearing a decorative collar and a short soft display strap, character A stands beside them observing; both faces and upper bodies visible, static fashion accessories, clear silhouettes", compatibility=["scene_collar_display", "scene_gothic_leather_lounge"]),
    _pose_preset("sm_wrist_cuffs_back", "SM/束缚", "背腕扣具站姿", "角色B站立并将双手置于背后，佩戴装饰性腕扣，角色A从侧面检查肩背线条", ["2 people", "wrist cuffs behind back", "standing display", "decorative cuffs", "symbolic restraint", "clear posture"], people="双人", orientation="中性", role_slots=["检查角色", "展示角色"], body_separation=True, contact_points=["手腕扣具", "肩部"], camera="全身", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate anime characters in one full-body anime shot: character B stands with both hands behind their back wearing decorative wrist cuffs, character A stands to the side examining the posture; full bodies visible, arms and hands remain anatomically distinct, static fashion pose", compatibility=["scene_leather_harness_room", "scene_open_restraint_gallery"]),
    _pose_preset("sm_side_restraint_recline", "SM/束缚", "侧卧约束依靠", "角色B侧卧在软垫上，装饰性软带沿腰部与大腿固定，角色A坐在近旁保持接触清楚", ["2 people", "side recline", "soft decorative straps", "restraint pose", "padded support", "separated bodies"], people="双人", orientation="中性", role_slots=["陪伴角色", "倚卧角色"], body_separation=True, contact_points=["腰部软带", "大腿软带", "软垫"], camera="中景", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate anime characters in one medium side-view shot: character B reclines comfortably on a padded surface with soft decorative straps around the waist and thighs, character A sits nearby with one hand resting on the cushion; clear contact points and separate body silhouettes, static fashion pose", compatibility=["scene_rope_bed", "scene_gothic_leather_lounge"]),
    _pose_preset("sm_wall_strap_pose", "SM/束缚", "墙面软带姿态", "角色B面对软垫墙站立，手腕放入装饰性软带，角色A从侧方调整肩部束带", ["2 people", "padded wall", "soft wrist straps", "wall restraint pose", "decorative harness", "clear spacing"], people="双人", orientation="中性", role_slots=["调整角色", "墙面角色"], body_separation=True, contact_points=["手腕软带", "肩部束带", "软垫墙"], camera="全身", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate anime characters in one full-body side-view shot: character B stands facing a padded wall with soft decorative wrist straps, character A stands beside them adjusting a shoulder harness; both bodies and limbs separately visible, static display pose", compatibility=["scene_wall_brace", "scene_latex_showroom"]),
    _pose_preset("sm_floor_chain_kneel", "SM/束缚", "地面链饰跪姿", "角色B跪坐在软垫上，佩戴宽松装饰链与腕扣，角色A站在侧方保持示意性主导姿态", ["2 people", "floor kneeling", "decorative chain accessory", "loose wrist cuffs", "symbolic power exchange", "separated bodies"], people="双人", orientation="中性", role_slots=["主导角色", "跪姿角色"], body_separation=True, contact_points=["腕扣", "软垫", "肩部"], camera="全身", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate anime characters in one full-body anime shot: character B kneels upright on a padded floor with a loose decorative chain accessory and wrist cuffs, character A stands beside them in a calm dominant pose; loose accessories remain static and non-tensioned, both bodies clearly separated", compatibility=["scene_dungeon_showcase", "scene_rope_workshop"]),
    _pose_preset("sm_suspension_harness_pose", "SM/束缚", "软吊带悬浮姿态", "角色B由宽软质吊带稳定支撑，角色A在侧方确认重心，支架与身体轮廓清楚", ["2 people", "soft suspension harness pose", "padded support straps", "floating support", "stable center of gravity", "separated silhouettes"], people="双人", orientation="中性", role_slots=["辅助角色", "悬浮角色"], body_separation=True, contact_points=["腰部软带", "腿部支撑", "支架"], camera="全身", sequence="约束", rating="R18", intensity="极限", draw_prompt="exactly 2 separate anime characters in one full-body wide shot: character B is supported by broad padded harness straps from a stable support rig with a clear center of gravity, character A stands to the side guiding the pose; both complete bodies and faces visible, soft straps remain decorative", compatibility=["scene_suspension_rig", "scene_device_display_stage"]),
    _pose_preset("sm_dominant_respondent_standoff", "SM/束缚", "主从对峙站姿", "两名角色面对面站立形成主从构图，服装与姿态对比明确但不发生身体融合", ["2 people", "dominant and respondent standoff", "face to face", "power exchange pose", "clear posture contrast", "separated silhouettes"], people="双人", orientation="中性", role_slots=["主导角色", "回应角色"], body_separation=True, contact_points=["视线", "衣领装饰", "手部"], camera="全身", sequence="前戏", rating="R18", intensity="强化", draw_prompt="exactly 2 separate anime characters standing face to face in one full-body anime shot: fashion outfit with decorative collar and harness details creates a clear dominant-and-respondent composition; both silhouettes fully separated, expressions and posture contrast visible", compatibility=["scene_throne_command", "scene_neon_underground_hall"]),
    _pose_preset("sm_sensory_blindfold_kneel", "SM/束缚", "眼罩跪姿引导", "角色B佩戴静态眼罩跪坐，角色A将单手轻放在其肩部进行示意性引导", ["2 people", "blindfold pose", "kneeling", "symbolic guidance", "static sensory accessory", "separated bodies"], people="双人", orientation="中性", role_slots=["引导角色", "感官角色"], body_separation=True, contact_points=["眼罩", "肩部", "手部"], camera="中景", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate anime characters in one medium shot: character B kneels upright wearing a static decorative blindfold, character A stands beside them with one hand resting lightly on the shoulder in a calm guiding gesture; both faces and upper bodies visible", compatibility=["scene_blindfold_chamber", "scene_sensory_pod"]),
    _pose_preset("sm_rope_frame_standing", "SM/束缚", "绳架站姿", "两名角色站在开放式绳架两侧，装饰性绳纹沿服装固定，绳线不打结且身体轮廓分离", ["2 people", "open rope frame", "decorative rope pattern", "standing pose", "loose static ropes", "separated silhouettes"], people="双人", orientation="中性", role_slots=["前方角色", "侧方角色"], body_separation=True, contact_points=["手与框架", "腰部装饰绳", "肩部"], camera="全身", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate anime characters in one full-body wide shot inside an open decorative rope frame: both stand with clear posture, loose static rope patterns follow the clothing without tension, one character in front and one at the side; all limbs and faces visible", compatibility=["scene_rope_workshop", "scene_open_restraint_gallery"]),

    # 补充单人（5）
    _pose_preset("solo_crouch_side_glance", "单人构图", "低蹲侧望", "角色低蹲并转头从侧面看向镜头，膝盖与重心位置清楚", ["solo", "low crouch", "side glance", "weight on toes"], people="单人", orientation="单人", role_slots=["主体"], contact_points=["双脚与地面"], camera="全身", sequence="进行中", rating="普通", intensity="标准"),
    _pose_preset("solo_kneel_back_arch", "单人构图", "跪立后仰", "角色双膝跪地并向后伸展上身，腰背形成柔和弧线", ["solo", "kneeling", "back arch", "arms relaxed"], people="单人", orientation="单人", role_slots=["主体"], contact_points=["膝部与地面"], camera="全身", sequence="进行中", rating="普通", intensity="标准"),
    _pose_preset("solo_floor_side_lean", "单人构图", "席地侧靠", "角色坐在地面并向侧方倾斜，用一只手支撑身体", ["solo", "sitting on floor", "side lean", "one hand support"], people="单人", orientation="单人", role_slots=["主体"], contact_points=["手部与地面", "臀部与地面"], camera="全身", sequence="进行中", rating="普通", intensity="标准"),
    _pose_preset("solo_leg_extended_stretch", "单人构图", "单腿伸展", "角色坐姿向前伸出一腿，另一腿屈膝收拢，肢体比例清楚", ["solo", "sitting", "one leg extended", "one knee bent"], people="单人", orientation="单人", role_slots=["主体"], contact_points=["臀部与地面"], camera="全身", sequence="进行中", rating="普通", intensity="标准"),
    _pose_preset("solo_shoulder_turn_lookback", "单人构图", "肩部回望", "角色保持正面站姿并扭转肩部回望，头部与身体形成自然转角", ["solo", "standing", "shoulder turn", "looking back"], people="单人", orientation="单人", role_slots=["主体"], contact_points=["双脚与地面"], camera="中景", sequence="进行中", rating="普通", intensity="标准"),

    # 补充常规位（5）
    _pose_preset("missionary_one_leg_raised", "常规", "单腿抬起传教士", "女方仰躺，一条腿抬高由男方扶住，男方在上方进入", ["missionary position", "one leg raised", "holding leg", "vaginal sex"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手与腿部", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("missionary_edge_lean", "常规", "床沿前倾传教士", "女方躺在床沿并抬高髋部，男方站在床边前倾进入", ["missionary position", "bed edge", "hips raised", "standing partner"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手与床沿", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("side_fold_missionary", "侧位", "侧折传教士", "女方侧身仰卧并屈膝折腿，男方从上方侧向进入", ["side missionary", "folded leg", "side view", "intercourse"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["腿部", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("tabletop_missionary", "常规", "桌面传教士", "女方仰躺在桌面，男方站在桌边面对进入", ["missionary position", "on table", "standing partner", "legs apart"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["背部与桌面", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("sofa_missionary_deep", "常规", "沙发深陷传教士", "女方仰躺在沙发坐垫上，男方压低重心在上方进入", ["missionary position", "sofa", "low angle", "close contact"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["背部与沙发", "髋部"], camera="中景", sequence="进行中", rating="R18", intensity="强化"),

    # 补充背后位（5）
    _pose_preset("doggy_arch_deep", "背后位", "塌腰后入", "女方四肢着地并压低肩部、抬高髋部，男方从后方进入", ["doggystyle", "arched back", "hips raised", "from behind"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手膝与支撑面", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="强化"),
    _pose_preset("doggy_head_down", "背后位", "低头后入", "女方俯身低头，双手撑住前方，男方跪在后方进入", ["doggystyle", "head down", "kneeling partner", "from behind"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手部与支撑面", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("sofa_arm_doggy", "背后位", "沙发扶手后入", "女方扶住沙发扶手弯腰，男方站在后方进入", ["doggystyle", "sofa arm", "bent over", "standing partner"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手与沙发扶手", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("prone_raised_hip", "背后位", "俯卧抬髋", "女方俯卧并抬高髋部，男方从上后方进入", ["prone bone", "raised hips", "lying face down", "from behind"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["胸腹与支撑面", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="强化"),
    _pose_preset("standing_bent_knee_doggy", "背后位", "屈膝站姿后入", "女方站立屈膝并向前俯身，男方从后方贴近进入", ["standing doggystyle", "bent knees", "bent over", "from behind"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手部与腿部", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="标准"),

    # 补充骑乘位（5）
    _pose_preset("cowgirl_embrace", "骑乘位", "相拥骑乘", "女方骑坐在男方身上，双方贴近相拥并保持正面接触", ["cowgirl position", "embracing", "face to face", "riding"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["胸口", "手臂", "髋部"], camera="中景", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("reverse_cowgirl_forward", "骑乘位", "前俯反骑", "女方背对男方骑乘并向前俯身支撑，男方托住髋部", ["reverse cowgirl", "leaning forward", "hands support", "riding"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手部与支撑面", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("side_saddle_hug", "骑乘位", "侧骑相拥", "女方侧坐在男方腿上，双方双臂环抱并保持侧向接触", ["side saddle", "cowgirl position", "embracing", "side view"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手臂", "腿与大腿"], camera="中景", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("reverse_squat_embrace", "骑乘位", "反向蹲骑相拥", "女方背对男方下蹲骑乘，男方从后方环抱腰部", ["reverse cowgirl", "squatting", "rear embrace", "riding"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["腰部", "髋部"], camera="中景", sequence="进行中", rating="R18", intensity="强化"),
    _pose_preset("chair_reverse_straddle", "骑乘位", "椅上反向骑坐", "男方坐在椅上，女方背对他跨坐在腿上并向后俯身", ["reverse cowgirl", "on chair", "straddling lap", "facing away"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["腿与椅面", "髋部"], camera="中景", sequence="进行中", rating="R18", intensity="标准", draw_prompt="exactly 2 separate anime characters in one medium shot: the male sits upright on a sturdy chair while the female straddles his lap facing away from him, both full torsos visible and contact points at her hips and his thighs clearly defined; side view, no merged bodies, no extra limbs"),

    # 补充站坐位（5）
    _pose_preset("standing_one_leg_hold", "站姿", "单腿站立抱持", "女方单腿站立，另一腿由男方扶住，双方保持重心稳定", ["standing", "one leg lifted", "partner holding leg", "intercourse"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手与腿部", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="强化"),
    _pose_preset("wall_rear_lift", "站姿", "贴墙后抱举", "女方面向墙面，男方从后方抱起腰部进入，墙面支撑明确", ["standing", "against wall", "rear carry", "from behind"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手与墙面", "腰部", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate anime characters in one full-body side-view shot: the female faces a wall with both hands supporting herself while the male stands behind her and supports her raised hips; both bodies and all limbs separately visible, stable center of gravity, no merged bodies"),
    _pose_preset("seated_side_entry", "坐姿", "坐姿侧入", "女方坐在男方腿上并向侧面转身，男方从侧向进入", ["sitting", "side entry", "on lap", "side view"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["腿与大腿", "髋部"], camera="中景", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("chair_side_saddle", "坐姿", "椅上侧骑", "男方坐在椅上，女方侧坐在其腿上并保持身体平衡", ["side saddle", "on chair", "sitting on lap", "side view"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["腿与椅面", "手臂"], camera="中景", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("standing_leg_cradle", "站姿", "站立托腿", "男方站立托住女方双腿，女方面向男方并由其承担重心", ["standing carry", "leg cradle", "face to face", "supported"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手臂与腿部", "腰部"], camera="全身", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate anime characters in one full-body shot: the male stands upright and supports the female by cradling both of her legs, the female faces him with her arms around his shoulders; both complete bodies and all four limbs visible, stable center of gravity, no merged silhouettes"),

    # 补充口交手交与女同（5）
    _pose_preset("kneeling_face_to_face_oral", "口交位", "对跪口交", "两名角色相对跪坐，一方前倾为另一方口交，双方上肢清楚", ["kneeling", "face to face", "fellatio", "oral"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["口部", "手部"], camera="中景", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("seated_deep_oral", "口交位", "坐姿深口", "男方坐在椅上，女方跪在腿间进行深度口交，头部与肩部轮廓清楚", ["sitting", "kneeling", "fellatio", "deep oral"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["口部", "手部与大腿"], camera="中景", sequence="进行中", rating="R18", intensity="强化"),
    _pose_preset("handjob_rear_reach", "手交", "背后手交", "女方从后方贴近男方，伸手绕过腰部进行手交，双方身体分离", ["handjob", "from behind", "rear reach", "hand on penis"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手部", "腰背"], camera="中景", sequence="进行中", rating="R18", intensity="标准"),
    _pose_preset("lesbian_standing_rear_embrace", "女同", "站立背后爱抚", "一名女性从背后拥抱另一名女性，双手停留在腰腹外侧", ["lesbian", "standing rear embrace", "waist touch", "from behind"], people="双人", orientation="女女", role_slots=["女A", "女B"], contact_points=["手臂", "腰腹"], camera="中景", sequence="前戏", rating="R18", intensity="标准"),
    _pose_preset("lesbian_reverse_riding_grind", "女同", "反向骑乘磨镜", "一名女性背对另一名女性骑坐于其髋部上方，双方保持独立轮廓", ["lesbian", "reverse riding", "tribadism", "grinding"], people="双人", orientation="女女", role_slots=["女A", "女B"], contact_points=["大腿内侧", "髋部"], camera="中景", sequence="进行中", rating="R18", intensity="强化"),

    # 补充乳交、授乳与合意痛感玩法（7）
    _pose_preset("breast_sex_kneeling", "乳交", "跪姿乳交", "女方跪坐在男方身前，双手托住胸部包裹阴茎，双方表情与身体轮廓清楚", ["breast sex", "titjob", "penis between breasts", "kneeling", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["胸部", "双手", "阴茎"], camera="中景", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one wide side-view scene: a seated adult man and an adult woman kneel close together; the woman keeps both hands on her own breasts and leans toward his chest, with his penis visible between her breasts; both are fully visible from head to toe, one continuous scene, clear separate silhouettes, no inset portrait, no duplicate faces, no cropped limbs"),
    _pose_preset("nursing_intimate_side", "授乳玩法", "侧卧授乳互动", "两名成年女性侧卧贴近，一名女性托住胸部向另一名角色提供哺乳互动，姿态温和", ["adult nursing", "lactation", "side lying", "breast feeding play", "gentle eye contact", "consensual adult intimacy"], people="双人", orientation="女女", role_slots=["授乳角色", "回应角色"], contact_points=["胸部", "口部", "手臂"], camera="中景", sequence="前戏", rating="R18", intensity="标准", draw_prompt="exactly 2 separate adult anime women in one continuous side-view scene on a still bed: one woman lies on her side wearing a loose nursing camisole and cradles the other woman close to her chest in a calm nursing interaction; both are full body, exactly two heads, clear separate silhouettes, no extra people, no collage"),
    _pose_preset("consensual_spanking_over_knee", "痛感玩法", "合意膝上打屁股", "接受方成年角色俯卧在主动方腿上，主动方抬起手掌进行合意打屁股，双方表情自然", ["consensual adult spanking", "over the knee", "open hand spanking", "pain play", "adult partners", "established consent"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["手掌", "臀部", "大腿"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous side-view living room scene: a seated adult partner safely supports the other adult across the lap with one open hand raised; both wear simple loungewear, both complete bodies are visible, calm consensual expressions, no impact marks, no extra people, no collage"),
    _pose_preset("leather_paddle_short_flogger_play", "痛感玩法", "皮拍短鞭体验", "一名成年角色手持皮拍或短鞭贴近另一名接受者的背部，动作停留在合意感官体验的起势", ["consensual adult impact play", "leather paddle", "short suede flogger", "hand-held toy", "pain play", "adult partners"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["皮拍或短鞭", "手部", "肩背"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women standing side by side in a calm indoor room; one woman holds a small leather paddle by its handle near her own waist while the other faces her calmly at a short distance; simple fitted loungewear, both complete bodies visible, no contact impact, no latex, no harness, no cage, no machinery, no collage"),
    _pose_preset("suede_flogger_sensation_play", "痛感玩法", "软鞭抚触体验", "主动方手持绒面软鞭将鞭梢轻放在接受方肩背，强调材质触感与双方合意互动", ["consensual adult sensory play", "suede flogger", "soft leather strands", "shoulder sensation play", "hand-held toy", "pain play"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["软鞭", "肩背", "手部"], camera="中景", sequence="进行中", rating="R18", intensity="标准", draw_prompt="exactly 2 separate adult anime women standing in a calm indoor room; one woman holds a soft suede flogger with many flexible fringe strands by its handle and rests the fringe lightly on the other woman's shoulder; simple sleeveless loungewear, both complete bodies visible, gentle expression, no hard rod, no latex, no cage, no machinery, no collage"),
    _pose_preset("rattan_sensation_experience", "痛感玩法", "藤条轻触体验", "主动方手持细藤条在接受方身侧保持轻触起势，接受方以稳定站姿回应，双方保持成人合意氛围", ["consensual adult sensation play", "flexible rattan rod", "hand-held toy", "light touch", "adult partners", "pain play"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["藤条", "手部", "侧腰"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters standing apart in a calm bright room; one adult holds a thin flexible rattan rod down at their side, the other stands relaxed facing them; simple everyday clothing, both complete bodies visible, no impact, no weapon pose, no extra people, no collage"),
    _pose_preset("wax_play_low_temperature", "痛感玩法", "低温滴蜡体验", "主动方使用低温按摩蜡烛在对方上背部上方悬停，少量温热蜡滴落在肩背，强调合意感官体验", ["consensual adult wax play", "low temperature massage candle", "warm wax drops", "upper back", "sensory play", "adult partners"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["蜡烛", "蜡滴", "肩背"], camera="中景", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women in one continuous indoor scene; one woman reclines on a towel wearing a loose camisole while the other holds a small unlit low-temperature massage candle above her upper back; no open flame, both complete bodies visible, exactly two heads, natural neck and shoulders, no machinery, no collage"),

    # 新增痛感/性虐玩法（16）
    _pose_preset("impact_spanking_over_knee_consensual", "痛感玩法", "膝上拍打", "接受方成年角色俯卧在主动方腿上，主动方抬起手掌保持合意拍打起势，双方穿着日常家居服", ["spanking", "impact play", "over knee", "adult", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["手掌", "臀部", "大腿"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous side-view living room scene; a seated adult on a low sofa supports the other adult safely across the lap with one open hand raised above the hip line; both wear simple loungewear, both complete bodies are visible, calm expressions, intact unmarked skin, no extra people, no collage"),
    _pose_preset("impact_spanking_bent_over_consensual", "痛感玩法", "俯身拍打", "接受方成年角色俯身扶住软垫凳，主动方站在侧后方抬起手掌保持合意拍打起势", ["spanking", "bent over", "impact play", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["手掌", "臀部", "软垫凳"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous room scene; the receiving adult bends forward with both hands resting on a padded bench while the giving adult stands to the side behind them with one open hand raised; simple fitted clothing, both complete bodies visible, intact unmarked skin, no restraints, no extra people, no collage"),
    _pose_preset("impact_paddle_pose_consensual", "痛感玩法", "拍板玩法", "接受方成年角色在软垫上跪伏，主动方在侧边持小型皮拍保持控制力度的合意起势", ["paddle", "impact play", "controlled intensity", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["皮拍", "手部", "肩背"], camera="全身", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime characters in one calm indoor scene; the receiving adult kneels on a padded mat with shoulders lowered and the giving adult kneels beside them holding a small leather paddle at a controlled distance; simple loungewear, both complete bodies visible, no contact at this moment, intact skin, no cage, no machinery, no extra people, no collage"),
    _pose_preset("impact_riding_crop_pose_consensual", "痛感玩法", "短鞭玩法", "接受方成年角色面向墙面站立，主动方在安全距离手持短鞭保持合意起势，双方轮廓完整", ["riding crop", "impact play", "consensual", "controlled intensity"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["短鞭", "手部", "肩背"], camera="全身", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime characters in one bright indoor room; one adult stands facing a plain wall with both palms resting on it while the other stands behind and to the side holding a riding crop down at a controlled distance; simple fitted clothing, both complete bodies visible, no contact at this moment, intact skin, no extra people, no collage"),
    _pose_preset("impact_soft_flogger_back_consensual", "痛感玩法", "软鞭背部", "接受方成年角色向前坐稳露出上背，主动方从后方持软鞭保持合意起势，强调完整独立身体", ["soft flogger", "back", "impact play", "consensual"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["软鞭", "手部", "上背"], camera="全身", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime women in one continuous calm indoor scene; one woman sits facing away on a floor cushion with her upper back visible while the other kneels behind and holds a soft suede flogger above at a controlled distance; loose loungewear, both complete bodies visible, intact unmarked skin, no contact at this moment, no machinery, no collage"),
    _pose_preset("wax_drip_back_consensual", "痛感玩法", "背部滴蜡", "接受方成年角色坐姿背向镜头，主动方在其上背上方持低温蜡烛，少量蜡滴形成感官体验", ["wax play", "candle wax", "back", "temperature play"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["蜡烛", "蜡滴", "上背"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women in one continuous indoor scene; one seated woman faces away with her upper back visible while the other kneels beside her holding a small unlit low-temperature massage candle above the shoulder blades; loose camisole lowered at the back, both complete bodies visible, intact skin, only a few warm wax drops, no open flame, no machinery, no collage"),
    _pose_preset("wax_drip_chest_consensual", "痛感玩法", "胸前滴蜡", "接受方成年角色坐姿面向侧方，主动方在肩侧持低温蜡烛，少量蜡滴落在胸前皮肤", ["wax play", "candle wax", "chest", "temperature play"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["蜡烛", "蜡滴", "胸前"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women in one continuous indoor scene; one seated woman turns slightly to the side with her upper chest and collarbone visible while the other kneels beside her holding a small unlit low-temperature massage candle above the chest; simple loose clothing, both complete bodies visible, intact skin, only a few warm wax drops, no open flame, no machinery, no collage"),
    _pose_preset("wax_remove_aftercare_consensual", "痛感玩法", "蜡层处理与照护", "接受方成年角色裹着毛巾安静坐好，主动方用柔软布料轻柔清理冷却蜡层并检查皮肤", ["wax removal", "aftercare", "skin check", "calm"], people="双人", orientation="女女", role_slots=["照护角色", "接受角色"], contact_points=["软布", "冷却蜡层", "肩背"], camera="全身", sequence="结束", rating="R18", intensity="标准", draw_prompt="exactly 2 separate adult anime women in one calm indoor aftercare scene; one woman sits wrapped in a soft towel while the other kneels beside her and gently removes cooled wax from the shoulder with a clean soft cloth; both complete bodies visible, relaxed expressions, intact skin, no heated tools, no open flame, no medical equipment, no extra people, no collage"),
    _pose_preset("nipple_clamp_chain_consensual", "痛感玩法", "乳夹链玩法", "两名成年女性保持坐姿，接受方佩戴装饰性乳夹并由细链连接，主动方轻扶链条保持合意感官互动", ["nipple clamps", "chain", "sensation play", "consensual"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["乳夹", "细链", "手部"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women seated side by side in one calm indoor scene; the receiving woman wears decorative nipple clamps connected by a thin loose chain while the other gently supports the center of the chain with one hand; soft loungewear around the shoulders, both complete bodies visible, intact skin, relaxed expressions, no weights, no machinery, no extra people, no collage"),
    _pose_preset("nipple_clamp_weight_consensual", "痛感玩法", "乳夹配重", "接受方成年角色坐直并佩戴小型装饰乳夹配重，主动方站在侧边扶稳肩部观察状态", ["nipple clamps", "weights", "sensation play", "consensual"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["乳夹配重", "肩部", "手部"], camera="全身", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime women in one calm indoor scene; one woman sits upright wearing small decorative weighted nipple clamps while the other stands beside her with one hand gently steadying her shoulder; soft open loungewear, both complete bodies visible, intact skin, controlled expression, no machinery, no suspension, no extra people, no collage"),
    _pose_preset("clothespin_application_consensual", "痛感玩法", "衣夹排列", "接受方成年角色背向坐好，主动方将木质衣夹整齐排列在上背皮肤并保持合意感官互动", ["clothespins", "sensation play", "arranged", "consensual"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["衣夹", "上背", "手指"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women in one calm indoor scene; one woman sits facing away with her upper back visible while the other kneels behind and carefully arranges a short row of wooden clothespins on the skin; soft loungewear, both complete bodies visible, intact skin, relaxed expressions, no machinery, no restraints, no extra people, no collage"),
    _pose_preset("hair_pull_arch_consensual", "痛感玩法", "拉发弓身", "接受方成年角色站立并轻微弓背，主动方从后方轻握一束头发控制力度，双方保持合意互动", ["hair pulling", "back arch", "controlled intensity", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["头发", "手部", "背部"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous side-view room scene; the receiving adult stands with a gentle back arch while the giving adult stands behind and lightly holds one lock of hair near the back of the head; both wear simple fitted clothing, both complete bodies visible, calm controlled expressions, no extra people, no collage"),
    _pose_preset("nail_scratch_back_consensual", "痛感玩法", "背部抓痕", "接受方成年角色向前坐好露出上背，主动方以指尖沿背部形成浅淡表面痕迹", ["nail scratches", "back", "skin marks", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["指尖", "上背", "浅表痕迹"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one calm indoor scene; one adult sits facing away with the upper back visible while the other stands beside and lightly draws a few shallow temporary surface lines with the fingertips; both wear simple loungewear, both complete bodies visible, skin remains intact, no wounds, no bleeding, no extra people, no collage"),
    _pose_preset("love_bite_neck_consensual", "痛感玩法", "颈侧咬痕", "两名成年角色站立相拥，主动方轻咬接受方颈侧并形成浅淡吻痕，双方表情放松", ["biting", "neck", "love bite", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["口部", "颈侧", "手臂"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters standing in one continuous indoor scene; the giving adult gently kisses and lightly bites the side of the other adult's neck while both remain in a relaxed consensual embrace; simple fitted clothing, both complete bodies visible, only a soft temporary mark, intact skin, no bleeding, no extra people, no collage"),
    _pose_preset("impact_mark_inspection_consensual", "痛感玩法", "痕迹检查", "接受方成年角色披着浴袍坐好，主动方跪在一侧检查上背浅淡表面痕迹并确认状态", ["mark inspection", "aftercare", "skin check", "consent"], people="双人", orientation="女女", role_slots=["照护角色", "接受角色"], contact_points=["手指", "上背", "浅表痕迹"], camera="全身", sequence="结束", rating="R18", intensity="标准", draw_prompt="exactly 2 separate adult anime women in one calm aftercare scene; the receiving woman sits with a soft robe open at the back while the caring woman kneels beside her and gently inspects shallow temporary surface marks on the upper back; both complete bodies visible, intact skin, no wounds, no medical equipment, no extra people, no collage"),
    _pose_preset("pain_aftercare_hydration_consensual", "痛感玩法", "痛感后补水照护", "接受方成年角色裹毯坐好，主动方递上清水并轻扶肩部确认状态，氛围安静温和", ["aftercare", "hydration", "blanket", "check-in"], people="双人", orientation="女女", role_slots=["照护角色", "接受角色"], contact_points=["水杯", "手部", "肩部"], camera="全身", sequence="结束", rating="R18", intensity="标准", draw_prompt="exactly 2 separate adult anime women in one calm indoor aftercare scene; one woman sits wrapped in a soft blanket while the other kneels beside her offering a glass of water and gently resting a hand near her shoulder; both complete bodies visible, relaxed check-in expressions, no medical equipment, no extra people, no collage"),
    _pose_preset("standing_front_carry_cowgirl", "双人玩法", "站姿面对面托举骑乘", "男方站立托起女方，女方面向男方并以腿部环绕腰侧，双方保持清晰的身体接触和完整轮廓", ["standing carry", "cowgirl position", "face to face", "penis inside vagina", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手臂", "腰腿", "胯部"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous indoor scene; an adult man stands and supports an adult woman facing him with her legs wrapped around his waist in a consensual cowgirl carry; both complete bodies visible, clear separate silhouettes, uncensored, no extra people, no collage"),
    _pose_preset("standing_reverse_carry_wall", "双人玩法", "站姿反向托举贴墙", "男方从后方托举女方，女方背对男方并靠近墙面，双腿分开并由男方支撑", ["standing carry", "reverse cowgirl position", "against wall", "penis inside vagina", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["背部与胸口", "手臂", "腰腿"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous indoor scene; an adult man lifts an adult woman from behind while she faces a plain wall in a consensual reverse standing carry; both complete bodies visible, clear separate silhouettes, uncensored, no extra people, no collage"),
    _pose_preset("side_scissor_rear_entry", "双人玩法", "侧卧交叉剪刀后入", "两名角色侧卧并将双腿交叉，男方从后方进入，接触点集中在髋腿区域", ["side lying", "scissors position", "from behind", "anal sex", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["腰髋区域", "腿部交叉"], camera="中景", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters lying on their sides in one continuous indoor scene with crossed legs; the adult man enters the adult woman from behind in a consensual side scissor position; both complete bodies visible, clear separate silhouettes, uncensored, no extra people, no collage"),
    _pose_preset("x_position_side_by_side", "双人玩法", "X 位交叉侧卧", "两名角色侧卧并相互交叉双腿，形成稳定 X 形接触，髋部与腿部保持清楚", ["x position", "side lying", "crossed legs", "vaginal sex", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["髋部", "大腿", "膝部"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters lying side by side with their legs crossed in an X-shaped consensual intercourse pose; both complete bodies visible, clear separate heads and limbs, uncensored, no extra people, no collage"),
    _pose_preset("seashell_missionary", "双人玩法", "贝壳位仰卧抱腿", "女方仰卧并将双腿向胸前收拢，男方从上方俯身进入，身体支撑点和骨盆角度清楚", ["seashell position", "lying on back", "legs pulled back", "missionary position", "penis inside vagina", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["腿弯", "髋部", "肩背"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous indoor scene; an adult woman lies on her back with both legs pulled back toward her chest while an adult man leans over her in a consensual seashell missionary pose; both complete bodies visible, clear separate silhouettes, uncensored, no extra people, no collage"),
    _pose_preset("corkscrew_position", "双人玩法", "螺旋位侧卧交叠", "两名角色侧卧并形成腿部螺旋交叠，一方从侧向进入，身体接触点清楚且不重叠", ["corkscrew position", "side lying", "legs interlocked", "vaginal sex", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["髋部", "大腿内侧"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters lying on their sides with their legs interlocked in a consensual corkscrew sex position; both complete bodies visible, clear separate heads and limbs, uncensored, no extra people, no collage"),
    _pose_preset("rocking_chair_cowgirl", "双人玩法", "摇椅式面对面骑乘", "女方坐在男方身上并面向对方，双方共同利用坐姿节奏保持骑乘接触，身体轮廓完整", ["rocking chair", "cowgirl position", "face to face", "penis inside vagina", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["胯部", "腰背", "腿部"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous indoor scene; an adult woman sits facing an adult man on a wide chair in a consensual rocking cowgirl position; both complete bodies visible, clear separate silhouettes, uncensored, no extra people, no collage"),
    _pose_preset("sex_swing_suspended", "双人玩法", "吊椅秋千位", "两名角色在软质吊椅支撑下面对面互动，支撑带保持松软，双方身体轮廓和接触点清楚", ["sex swing", "soft support sling", "face to face", "penis inside vagina", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["软质吊椅", "腰背", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime characters in one continuous indoor scene seated closely in a soft padded support sling while facing each other in a consensual swing pose; both complete bodies visible, clear separate silhouettes, soft fabric support only, no hard machinery, no extra people, no collage"),
    _pose_preset("standing_one_leg_lock", "双人玩法", "站姿单腿锁腰", "男方站立并抬起女方一条腿，女方以另一条腿保持稳定，双方正面接触清楚", ["standing", "one leg raised", "partner holding leg", "penis inside vagina", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["手与腿", "腰髋区域", "支撑脚"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters standing in one continuous indoor scene; an adult man supports one raised leg of an adult woman while they remain face to face in a consensual standing intercourse pose; both complete bodies visible, clear separate silhouettes, uncensored, no extra people, no collage"),
    _pose_preset("reverse_bridge_cowgirl", "双人玩法", "反向桥式骑乘", "男方仰卧，女方背对男方呈桥式后仰骑乘，双手支撑身体，接触点与四肢位置完整", ["reverse bridge", "arched back", "cowgirl position", "vaginal sex", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["双手与支撑面", "腰髋区域"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous indoor scene; an adult woman arches backward over an adult man while riding him in a consensual reverse bridge cowgirl pose; both complete bodies visible, clear separate silhouettes, uncensored, no extra people, no collage"),
    _pose_preset("bed_edge_reverse_doggy", "双人玩法", "床边反向后入", "女方俯卧在床边并将臀部抬向床沿，男方站在地面从后方进入，双方接触点清楚", ["bed edge", "bent over", "standing partner", "anal sex", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["床沿", "髋部", "手部"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous indoor scene; an adult woman bends over the edge of a bed while an adult man stands behind her in a consensual reverse doggy pose; both complete bodies visible, clear separate silhouettes, uncensored, no extra people, no collage"),
    _pose_preset("reverse_cowgirl_lying_back", "双人玩法", "女上反向后仰骑乘", "女方背对男方坐在其髋部并向后仰靠，男方托住女方腰背，双方重心稳定且接触清楚", ["reverse cowgirl position", "leaning back", "penis inside vagina", "two adult partners", "consensual"], people="双人", orientation="男女", role_slots=["女A", "男A"], contact_points=["腰背", "手部", "髋部"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous indoor scene; an adult woman leans backward while sitting on an adult man in a consensual reverse cowgirl pose with his hands supporting her lower back; both complete bodies visible, clear separate silhouettes, uncensored, no extra people, no collage"),
    _pose_preset("mouth_gag_kneeling", "痛感玩法", "口球跪姿调教", "接受方成年角色跪坐并佩戴宽松装饰口球，主动方站在侧后方轻扶肩部，姿态静态合意", ["ball gag", "kneeling", "bdsm", "sensation play", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["口球", "肩部", "膝部"], camera="全身", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one calm indoor scene; one adult kneels wearing a loose decorative ball gag while the other stands beside them gently touching one shoulder; both complete bodies visible, intact skin, static consensual pose, no machinery, no extra people, no collage"),
    _pose_preset("sensory_deprivation_blindfold_earplugs", "痛感玩法", "眼罩耳塞感官剥夺", "接受方成年角色跪坐并佩戴柔软眼罩与耳塞，主动方在侧边以手势保持安全距离", ["blindfold", "earplugs", "sensory deprivation", "kneeling", "bdsm", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["眼罩", "耳塞", "肩部"], camera="全身", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one calm indoor scene; one adult kneels wearing a soft blindfold and earplugs while the other stands nearby without touching, both complete bodies visible, clear separate silhouettes, intact skin, no machinery, no extra people, no collage"),
    _pose_preset("collar_leash_standing", "痛感玩法", "皮革项圈牵引站立", "接受方成年角色站立并佩戴宽松装饰项圈与短牵引带，主动方在侧前方持带保持松垂", ["collar", "leash", "standing", "bdsm", "power exchange", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["项圈", "牵引带", "手部"], camera="全身", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters standing in one calm indoor scene; one adult wears a loose decorative collar with a short leash while the other holds the leash end without tension; both complete bodies visible, clear separate silhouettes, intact skin, no extra people, no collage"),
    _pose_preset("wrist_bed_restraint_supine", "痛感玩法", "手腕床柱束缚仰卧", "接受方成年角色仰卧并将手腕放在松软装饰束带中，主动方在床边检查束带位置", ["wrist restraints", "bed frame", "lying on back", "bdsm", "restraint play", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["手腕束带", "床柱", "肩部"], camera="全身", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one calm bedroom scene; one adult lies on their back with both wrists resting inside loose soft decorative restraints attached to the bed frame while the other stands beside the bed checking the straps; both complete bodies visible, clear separate silhouettes, intact skin, no machinery, no extra people, no collage"),
    _pose_preset("ankle_cuffs_spread", "痛感玩法", "脚踝束带双腿张开", "接受方成年角色仰卧并屈膝，双脚佩戴宽松装饰脚踝束带，主动方在侧边观察姿态", ["ankle cuffs", "legs spread", "bdsm", "restraint play", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["脚踝束带", "膝盖", "软垫"], camera="全身", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one calm indoor scene; one adult lies on a padded surface with knees bent and ankles resting in loose decorative cuffs while the other sits beside them observing; both complete bodies visible, clear separate silhouettes, intact skin, no hard spreader bar, no machinery, no extra people, no collage"),
    _pose_preset("partial_suspension_harness", "痛感玩法", "半悬空吊缚展示", "接受方成年角色由宽软吊带支撑并保持一只脚触地，主动方在侧后方调整肩带，姿态静态", ["partial suspension", "soft harness", "bondage", "bdsm", "consensual", "static pose"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["软吊带", "肩部", "支撑脚"], camera="全身", sequence="约束", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime characters in one calm indoor scene; one adult is partially supported by wide soft padded straps with one foot still touching the floor while the other stands behind adjusting a shoulder strap; both complete bodies visible, clear separate silhouettes, soft fabric support only, no hard machinery, no extra people, no collage"),
    _pose_preset("ice_cube_back_sensation", "痛感玩法", "冰块低温刺激背部", "接受方成年角色坐姿背向主动方，主动方手持冰块沿上背缓慢移动，保持合意感官体验", ["ice cube", "temperature play", "back", "sensation play", "consensual", "adult partners"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["冰块", "上背", "手部"], camera="中景", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one calm indoor scene; one adult sits facing away while the other gently moves an ice cube across the upper back in a consensual temperature-play pose; both complete bodies visible, intact skin, no wounds, no medical equipment, no extra people, no collage"),
    _pose_preset("feather_tease_sensation", "痛感玩法", "羽毛敏感点撩拨", "接受方成年角色坐姿放松，主动方用柔软羽毛沿肩颈和上背轻扫，保持合意挑逗氛围", ["feather", "sensitive skin", "teasing", "sensation play", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["羽毛", "肩颈", "上背"], camera="中景", sequence="进行中", rating="R18", intensity="标准", draw_prompt="exactly 2 separate adult anime characters in one calm indoor scene; one adult sits relaxed while the other lightly sweeps a soft feather over their neck and upper back in a consensual teasing pose; both complete bodies visible, intact skin, no machinery, no extra people, no collage"),
    _pose_preset("external_vibrator_control", "痛感玩法", "外部震动玩具控制", "接受方成年角色坐姿放松，主动方手持小型外部震动玩具保持在腰腹上方，双方距离清楚", ["vibrator", "external stimulation", "remote control toy", "bdsm", "consensual", "sensation play"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["震动玩具", "手部", "腰腹"], camera="全身", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one calm indoor scene; one adult sits relaxed while the other holds a small external vibrator above the lower abdomen in a consensual controlled pose; both complete bodies visible, clear separate silhouettes, no internal insertion, no machinery, no extra people, no collage"),
    _pose_preset("collar_chain_kneeling_display", "痛感玩法", "锁链项圈跪坐展示", "接受方成年角色跪坐并佩戴装饰项圈与松垂锁链，主动方站在侧边轻扶链条，姿态静态展示", ["collar", "chain leash", "kneeling", "display pose", "bdsm", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["项圈", "锁链", "手部"], camera="全身", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one calm indoor scene; one adult kneels wearing a decorative collar with a loose chain while the other stands beside them holding the chain gently; both complete bodies visible, clear separate silhouettes, intact skin, no hard restraints, no machinery, no extra people, no collage"),
    _pose_preset("restraint_straps_side_lying_entry", "痛感玩法", "束缚带侧卧后入", "接受方成年角色侧卧并佩戴宽松装饰束带，主动方从后方保持进入，双方接触点与轮廓完整", ["restraint straps", "side lying", "rear entry", "intercourse", "bdsm", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["装饰束带", "腰髋区域", "腿部"], camera="全身", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime characters lying on their sides in one calm indoor scene with loose decorative restraint straps around the receiving adult's thighs; the giving adult enters from behind in a consensual side-lying pose; both complete bodies visible, clear separate silhouettes, intact skin, no hard restraints, no machinery, no extra people, no collage"),
    _pose_preset("leather_glove_pose_guidance", "痛感玩法", "皮革手套姿势引导", "主动方佩戴柔软皮革手套轻触接受方下颌与肩部，引导对方调整站姿，动作克制合意", ["leather gloves", "neck touch", "posture guidance", "bdsm", "consensual", "power exchange"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["手套", "下颌", "肩部"], camera="全身", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters standing in one calm indoor scene; the giving adult wears soft leather gloves and lightly touches the other adult's jaw and shoulder while guiding their posture; both complete bodies visible, clear separate silhouettes, intact skin, no impact, no machinery, no extra people, no collage"),

    # 双人亲密扩充（12）
    _pose_preset("duo_countertop_front_lift", "双人接触", "台面正面抱举", "一名成年角色坐在厨房台面边缘，另一名角色站在其身前托住腰侧拥抱，双方面向彼此", ["two adults", "countertop", "front lift", "face to face", "intimate embrace", "consensual"], people="双人", orientation="男女", role_slots=["坐姿角色", "支撑角色"], contact_points=["双手与腰侧", "腿部与台面", "胸口靠近"], camera="全身", sequence="前戏", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous modern kitchen scene; one seated adult rests on the countertop edge while the other stands close in front and supports their waist in a consensual intimate embrace; both complete bodies visible, clear faces, separate silhouettes, natural hands and legs, no sexual content, no extra people, no collage"),
    _pose_preset("duo_shower_wall_embrace", "双人接触", "淋浴间贴墙相拥", "一名成年角色双手扶住淋浴墙，另一名角色从身后靠近并环抱腰侧，水汽与身体轮廓清楚", ["two adults", "shower", "against wall", "back embrace", "wet skin", "consensual"], people="双人", orientation="女女", role_slots=["靠墙角色", "环抱角色"], contact_points=["手掌与墙面", "手臂与腰侧", "背部靠近"], camera="中景", sequence="前戏", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women in one continuous shower scene; one woman rests both palms on the tiled wall while the other stands close behind and embraces her waist in a consensual intimate pose; both complete bodies visible, clear separate heads and limbs, wet skin, no extra people, no merged bodies, no collage"),
    _pose_preset("duo_bathtub_spooning", "双人接触", "浴缸前后贴卧", "两名成年角色在同一浴缸内前后贴卧，后侧角色环抱前侧角色腰腹，水面与身体轮廓完整", ["two adults", "bathtub", "spooning", "back embrace", "wet skin", "consensual"], people="双人", orientation="女女", role_slots=["前侧角色", "后侧角色"], contact_points=["手臂与腰腹", "背部靠近", "腿部与浴缸"], camera="中景", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women in one continuous bathtub scene; one reclines in front while the other lies close behind and gently embraces her waist in a consensual spooning pose; both complete bodies visible above the waterline, distinct heads, shoulders, arms and legs, no extra people, no collage"),
    _pose_preset("duo_bathtub_face_to_face", "双人接触", "浴缸面对面相拥", "两名成年角色在浴缸内面对面坐稳，双腿自然交错并相互扶住手臂，水面保持稳定", ["two adults", "bathtub", "face to face", "close embrace", "wet skin", "consensual"], people="双人", orientation="女女", role_slots=["角色A", "角色B"], contact_points=["手臂", "腿部交错", "浴缸边缘"], camera="中景", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women seated face to face in one continuous bathtub scene; their knees gently overlap while each rests a hand on the other's upper arm in a consensual intimate embrace; both complete bodies and faces visible above the waterline, clear separate silhouettes, no extra people, no collage"),
    _pose_preset("duo_mirror_front_back_embrace", "双人接触", "镜前后背环抱", "两名成年角色面对高镜站立，后侧角色从背后环抱腰侧，镜中仅重复相同的两个人", ["two adults", "mirror", "front back embrace", "standing", "waist touch", "consensual"], people="双人", orientation="女女", role_slots=["前侧角色", "后侧角色"], contact_points=["手臂与腰侧", "背部靠近", "双脚与地面"], camera="全身", sequence="前戏", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women standing in one continuous dressing room scene; one stands in front while the other embraces her waist from behind as both face a tall mirror; the reflection repeats only the same two women, no third person, both complete bodies visible, clear heads and limbs, no extra people, no collage"),
    _pose_preset("duo_chair_face_to_face_embrace", "双人接触", "椅上面对面相拥", "一名成年角色坐在椅子上，另一名角色面向其靠近膝上，双方额头相贴并轻扶肩背", ["two adults", "chair", "face to face", "lap embrace", "forehead touch", "consensual"], people="双人", orientation="男女", role_slots=["坐姿角色", "靠近角色"], contact_points=["腿部与椅面", "双手与肩背", "额头"], camera="全身", sequence="前戏", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous indoor scene; one adult sits on a sturdy chair while the other faces them close above the lap with foreheads gently touching and hands resting on shoulders; both complete bodies visible, clear separate silhouettes, fully clothed, no extra people, no collage"),
    _pose_preset("duo_lap_pillow_soothing", "双人接触", "膝枕安抚", "一名成年角色侧卧在另一名角色的膝上，另一名角色轻抚头发与肩部，氛围安静温和", ["two adults", "lap pillow", "soothing", "hair touch", "aftercare", "calm"], people="双人", orientation="女女", role_slots=["照护角色", "休息角色"], contact_points=["头部与大腿", "手与头发", "手与肩部"], camera="中景", sequence="结束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women in one continuous calm indoor aftercare scene; one reclines across the other's lap while the seated woman gently strokes her hair and shoulder; both complete bodies visible, relaxed expressions, clear separate silhouettes, comfortable loungewear, no extra people, no collage"),
    _pose_preset("duo_sofa_reclining_mutual_touch", "双人玩法", "沙发并卧互抚", "两名成年角色在宽沙发上并侧卧，面向彼此并以手掌轻触脸颊、腰侧与大腿，动作克制", ["two adults", "sofa", "side lying", "mutual touch", "face to face", "consensual"], people="双人", orientation="男女", role_slots=["角色A", "角色B"], contact_points=["手掌与脸颊", "手掌与腰侧", "腿部靠近"], camera="中景", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters lying face to face together on one wide sofa in one continuous indoor scene; each gently touches the other's cheek, waist and thigh in a consensual intimate pose; both complete bodies visible, clear heads and limbs, separate silhouettes, no extra people, no collage"),
    _pose_preset("duo_oil_massage_lying", "双人玩法", "俯卧精油按摩", "一名成年角色俯卧在毛巾上，另一名角色跪在侧边将精油涂抹于上背与肩部，动作稳定温和", ["two adults", "lying prone", "oil massage", "upper back", "shoulders", "consensual"], people="双人", orientation="女女", role_slots=["按摩角色", "接受角色"], contact_points=["手掌与上背", "精油", "膝部与软垫"], camera="中景", sequence="前戏", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women in one continuous calm massage room scene; one lies prone on a fresh towel while the other kneels beside her and applies oil to the upper back and shoulders with both hands; both complete bodies visible, clear separate silhouettes, intact skin, no extra people, no collage"),
    _pose_preset("duo_feather_mutual_tease", "双人玩法", "羽毛互相撩拨", "两名成年角色面对面坐在软垫上，各自用柔软羽毛轻扫对方肩颈与锁骨，表情放松", ["two adults", "feather", "mutual tease", "sitting", "shoulders", "consensual"], people="双人", orientation="女女", role_slots=["角色A", "角色B"], contact_points=["羽毛与肩颈", "手部", "膝部与软垫"], camera="中景", sequence="前戏", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women seated face to face on soft cushions in one continuous indoor scene; each lightly sweeps a soft feather across the other's shoulder and collarbone in a consensual teasing pose; both complete bodies visible, relaxed expressions, clear hands, no extra people, no collage"),
    _pose_preset("duo_ice_cube_body_trail", "双人玩法", "冰块身体滑触", "一名成年角色倚躺并露出肩颈与手臂，另一名角色手持冰块沿锁骨和上臂缓慢滑动", ["two adults", "ice cube", "temperature play", "collarbone", "upper arm", "consensual"], people="双人", orientation="男女", role_slots=["持冰角色", "接受角色"], contact_points=["手与冰块", "锁骨", "上臂"], camera="中景", sequence="进行中", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime characters in one continuous calm indoor scene; one reclines with shoulders and arms visible while the other gently trails a small ice cube along the collarbone and upper arm in a consensual temperature-play pose; both complete bodies visible, intact skin, no medical equipment, no extra people, no collage"),
    _pose_preset("duo_soft_ribbon_wrist_play", "双人玩法", "软带手腕轻绕", "两名成年角色相对跪坐，一名角色用宽软缎带在另一名角色并拢的手腕外轻绕一圈，缎带保持松垂", ["two adults", "soft ribbon", "wrist play", "kneeling", "loose wrap", "consensual"], people="双人", orientation="女女", role_slots=["缠绕角色", "接受角色"], contact_points=["软缎带", "手腕", "膝部与软垫"], camera="中景", sequence="约束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women kneeling face to face on soft cushions in one continuous indoor scene; one carefully wraps a wide soft ribbon once around the other's gently joined wrists while the ribbon remains completely loose; both complete bodies visible, relaxed consensual expressions, clear hands, no tension, no extra people, no collage"),

    # 合意痛感扩充（12）
    _pose_preset("impact_spanking_standing_wall_consensual", "痛感玩法", "墙前站立重拍", "接受方成年角色双手扶墙并主动绷紧臀部，主动方以空手完成有力拍击，掌面刚离开皮肤，接受方因痛感咬唇皱眉", ["spanking", "standing wall", "hard open-hand spanking", "impact play", "red hand marks", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["手掌", "臀部外侧", "墙面与手掌"], camera="全身", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime characters in one continuous room scene; the receiving adult braces both hands against a plain wall with hips slightly extended while the giving adult follows through with a firm open-hand spanking strike across the outer buttock; visible skin compression and fresh red hand marks, the receiver's jaw tightens in a consensual pain reaction; both complete bodies visible, no restraints, no extra people, no collage"),
    _pose_preset("impact_paddle_padded_bench_consensual", "痛感玩法", "软凳皮拍重击", "接受方成年角色俯身扶凳，主动方以硬质皮拍完成有力击打，臀部受压并出现短时红肿与红痕", ["hard leather paddle", "padded bench", "heavy impact play", "visible red welt", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["硬质皮拍", "臀部外侧", "手掌与软凳"], camera="全身", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime characters in one continuous indoor scene; the receiving adult bends forward with both hands gripping a padded bench while the giving adult drives a hard leather paddle into the outer buttock with clear follow-through; the skin compresses under the paddle and shows a fresh raised red welt, the receiver lurches forward with a sharp consensual pain reaction; both complete bodies visible, no machinery, no extra people, no collage"),
    _pose_preset("impact_flogger_outer_thigh_consensual", "痛感玩法", "多尾硬鞭大腿外侧", "接受方成年角色侧身站稳并绷紧腿部，主动方挥动多尾硬鞭让鞭梢集中落在大腿外侧，皮肤出现短时红肿条痕", ["heavy suede flogger", "outer thigh", "hard impact play", "raised red welts", "consensual"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["多尾硬鞭", "大腿外侧", "手部"], camera="中景", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime women in one continuous indoor scene; one braces with her trouser leg raised and thigh muscles taut while the other swings a heavy multi-tail suede flogger so several strands land together across the outer thigh; the leg jerks from the impact and fresh red welt lines appear on the skin, the receiver shows a strained consensual pain reaction; both complete bodies visible, no machinery, no extra people, no collage"),
    _pose_preset("impact_crop_inner_thigh_consensual", "痛感玩法", "短鞭内侧实击", "接受方成年角色坐在高凳上并绷紧大腿，主动方用短鞭鞭梢完成一记锐利击打，大腿弹动并留下清晰红痕", ["riding crop", "inner thigh", "sharp impact play", "raised red line", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["短鞭鞭梢", "大腿内侧", "手部"], camera="中景", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime characters in one continuous indoor scene; the receiving adult sits on a high stool with knees held apart and inner thigh muscles tensed while the giving adult lands a sharp riding-crop strike with the tip against the inner thigh; the leg flinches from the hard impact and a narrow raised red line forms immediately, the receiver's face shows a controlled consensual pain response; both complete bodies visible, no restraints, no extra people, no collage"),
    _pose_preset("wax_drip_thigh_consensual", "痛感玩法", "大腿叠层滴蜡", "接受方成年角色侧坐并绷紧大腿，主动方让低温热蜡连续落在同一区域，皮肤泛红并形成叠层蜡滴，接受方因灼热感吸气", ["wax play", "low temperature massage candle", "outer thigh", "layered hot wax", "sharp heat sensation", "consensual"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["蜡烛", "叠层蜡滴", "大腿外侧"], camera="中景", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime women in one continuous indoor scene; one sits sideways with the outer thigh held taut while the other tilts an unlit low-temperature massage candle and lets several streams of warm wax fall close together onto the same patch of skin, building a layered wax trail; the skin flushes red from the heat and the receiver gasps with a sharp consensual pain reaction; both complete bodies visible, no open flame, no extra people, no collage"),
    _pose_preset("wax_drip_abdomen_consensual", "痛感玩法", "腹部叠层滴蜡", "接受方成年角色仰卧并绷紧腹肌，主动方将低温热蜡连续滴在同一片腹部区域，皮肤泛红且蜡层逐渐叠加", ["wax play", "low temperature massage candle", "abdomen", "layered hot wax", "sharp heat sensation", "consensual"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["蜡烛", "叠层蜡滴", "腹部"], camera="中景", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime women in one continuous indoor scene; one lies on her back with abdominal muscles contracted while the other tilts an unlit low-temperature massage candle and releases a close sequence of warm wax drops onto the same area of the abdomen; the skin reddens from the heat and a layered wax patch forms, the receiver arches slightly with a sharp consensual pain reaction; both complete bodies visible, no open flame, no restraints, no extra people, no collage"),
    _pose_preset("nipple_clamp_light_pull_consensual", "痛感玩法", "乳夹重拉", "接受方成年角色跪坐并挺直上身，主动方握住细链向后上方持续施力，乳夹受力明显并使胸腹绷紧，接受方因刺痛弓背", ["weighted nipple clamps", "hard chain pull", "sensation pain", "visible tension", "consensual"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["乳夹", "绷紧细链", "手指"], camera="中景", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime women in one continuous indoor scene; the receiving woman kneels with her torso lifted while firmly attached decorative nipple clamps are connected by a taut chain that the other woman pulls firmly backward and upward; the chain is visibly under tension, the clamps lift the skin and the receiver arches with a sharp consensual pain reaction; both complete bodies visible, no machinery, no extra people, no collage"),
    _pose_preset("clothespin_removal_aftercare_consensual", "痛感玩法", "衣夹取下余痛", "接受方成年角色披着软毯坐好，大腿上排列多个木质衣夹并留下深压痕，主动方快速取下其中一个，接受方因回血刺痛吸气", ["many clothespins", "removal pain", "deep skin indentations", "aftercare", "consensual"], people="双人", orientation="女女", role_slots=["照护角色", "接受角色"], contact_points=["木质衣夹", "大腿", "软手套"], camera="中景", sequence="结束", rating="R18", intensity="强化", draw_prompt="exactly 2 separate adult anime women in one continuous aftercare scene; one sits draped in a soft blanket with several tightly attached wooden clothespins in a row across the outer thigh, leaving deep red compression marks, while the other kneels beside her wearing soft gloves and snaps one clothespin open to remove it; the receiver inhales sharply from the returning sting; both complete bodies visible, no medical equipment, no extra people, no collage"),
    _pose_preset("hair_pull_kneeling_consensual", "痛感玩法", "跪姿强力后拉", "接受方成年角色跪坐在软垫上，主动方从侧后方抓住整束头发向后上方拉动，颈部和脊柱被迫后弓，接受方闭眼皱眉", ["hair pulling", "kneeling", "firm backward pull", "arched neck", "pain reaction", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["整束头发", "手部", "膝部与软垫"], camera="全身", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime characters in one continuous indoor scene; the receiving adult kneels on a soft cushion while the giving adult grips a thick lock of hair close to the scalp and pulls firmly backward and upward, forcing the neck to stretch and the spine into a sharp arch; the receiver closes their eyes and grimaces in a consensual pain reaction; both complete bodies visible, no restraints, no extra people, no collage"),
    _pose_preset("love_bite_shoulder_consensual", "痛感玩法", "肩头深咬", "两名成年角色紧贴站立，主动方用力咬住接受方肩头并保持压力，牙齿压陷皮肤并留下深红紫咬痕，接受方因疼痛绷紧手臂", ["hard biting", "shoulder", "deep love bite", "teeth indentation", "bruised mark", "consensual"], people="双人", orientation="男女", role_slots=["主动角色", "接受角色"], contact_points=["牙齿", "肩头", "手臂"], camera="中景", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime characters standing close in one continuous indoor scene; the giving adult clamps their teeth hard into the other adult's shoulder with visible skin compression and holds the bite while gripping the receiver tightly; a deep red-purple bite mark forms and the receiver tenses with a consensual pain reaction; both complete bodies visible, no extra people, no collage"),
    _pose_preset("nail_scratch_thigh_consensual", "痛感玩法", "大腿深抓痕", "接受方成年角色抬腿坐在软垫上并绷紧大腿，主动方用指尖持续用力抓过皮肤，留下数道隆起的深红抓痕，接受方腿部弹动", ["hard nail scratching", "outer thigh", "raised red scratches", "skin indentation", "consensual"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["指尖", "大腿外侧", "隆起抓痕"], camera="中景", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime women in one continuous indoor scene; one sits with one leg raised and thigh muscles tense while the other drags her fingernails firmly across the outer thigh, raising a set of parallel deep red scratch trails with visible skin indentation; the receiver's leg jerks and her face shows a consensual pain reaction; both complete bodies visible, no medical equipment, no extra people, no collage"),
    _pose_preset("ice_cube_chest_abdomen_consensual", "痛感玩法", "冰压胸腹", "接受方成年角色仰卧并绷紧胸腹，主动方将冰块用力压在同一点后沿锁骨下方拖向腹部，皮肤留下泛红低温痕，接受方颤抖吸气", ["ice cube", "deep cold pressure", "chest", "abdomen", "red cold flush", "sensation pain", "consensual"], people="双人", orientation="女女", role_slots=["主动角色", "接受角色"], contact_points=["手与冰块", "锁骨下方", "腹部"], camera="中景", sequence="进行中", rating="R18", intensity="极限", draw_prompt="exactly 2 separate adult anime women in one continuous indoor scene; one lies on her back with chest and abdominal muscles contracted while the other presses an ice cube firmly against the skin below the collarbone and drags it slowly toward the abdomen, leaving a wet red cold flush in its path; the receiver shivers and arches with a sharp consensual pain reaction; both complete bodies visible, no medical equipment, no extra people, no collage"),

    # 双人扩张与器具协作扩充（12）
    _duo_r18_pose("partner_dilation_stage_two_guided", "双人玩法", "伴侣辅助二期扩张", "接受方仰卧抬膝，辅助方扶住一侧大腿并缓慢引导大型渐扩器具进入第二阶段，同时观察接受方反应", ["two adults", "partner assisted dilation", "stage two dilation", "large graduated dilator", "knees raised", "consensual", "uncensored"], orientation="女女", role_slots=["辅助角色", "接受角色"], contact_points=["手与渐扩器具", "手与大腿", "外阴"], action_prompt="the receiving adult lies on their back with knees raised while the other adult braces one thigh and guides a large graduated dilator in a slow stage-two dilation, watching for a consensual response", camera="中景", intensity="极限"),
    _duo_r18_pose("partner_dilation_stage_three_guided", "双人玩法", "伴侣辅助三期扩张", "接受方仰卧并保持双腿打开，辅助方托住髋部并引导更大型渐扩器具完成第三阶段扩张", ["two adults", "partner assisted dilation", "stage three dilation", "maximum graduated dilator", "hips supported", "consensual", "uncensored"], orientation="女女", role_slots=["辅助角色", "接受角色"], contact_points=["手与渐扩器具", "手与髋部", "外阴"], action_prompt="the receiving adult lies back with both knees held wide while the other adult supports the hips and guides a larger graduated dilator through a sustained stage-three dilation, the receiver gripping a cushion with a strained consensual expression", camera="中景", intensity="极限"),
    _duo_r18_pose("partner_dilation_hold_control", "双人玩法", "伴侣控制扩张保持", "接受方侧卧抬腿，辅助方维持器具位置并看着计时器继续保持，接受方腰腹因持续受力轻颤", ["two adults", "dilation hold", "side lying", "timer", "sustained stretch", "consensual", "uncensored"], orientation="女女", role_slots=["辅助角色", "接受角色"], contact_points=["手与渐扩器具", "手与抬起的腿部", "计时器"], action_prompt="the receiving adult lies on their side with the upper leg raised while the other adult maintains the dilator position and watches a nearby timer, the receiver's waist trembling as the stretch is held", camera="中景", intensity="极限"),
    _duo_r18_pose("partner_speculum_adjustment_guided", "双人玩法", "伴侣调整窥器观察", "接受方仰卧抬膝，辅助方双手持完全张开的装饰窥器调整角度并靠近观察", ["two adults", "speculum adjustment", "open speculum", "guided examination", "reclining", "consensual", "uncensored"], orientation="女女", role_slots=["辅助角色", "接受角色"], contact_points=["双手与窥器", "外阴", "大腿内侧"], action_prompt="the receiving adult reclines with knees raised while the other adult holds a fully open decorative speculum at a clear close angle, adjusting its position with both hands for observation", camera="中景", intensity="极限"),
    _duo_r18_pose("partner_object_ladder_guided", "双人玩法", "伴侣辅助尺寸阶梯", "接受方跪坐在软垫上方，辅助方从后方引导中型柔性物件，旁边按大小排列三件器具", ["two adults", "object ladder", "graduated objects", "guided insertion", "three objects", "kneeling", "consensual", "uncensored"], orientation="女女", role_slots=["辅助角色", "接受角色"], contact_points=["手与柔性物件", "外阴", "膝部与软垫"], action_prompt="the receiving adult kneels upright over a low cushion while the other adult kneels behind and guides a medium flexible object, three graduated objects arranged in a visible size order nearby, the current insertion shown as one continuous controlled action", camera="中景", intensity="极限"),
    _duo_r18_pose("partner_fisting_assist", "双人玩法", "伴侣辅助部分拳交", "接受方仰卧抬高髋部，辅助方一手稳定髋部，另一只手以缓慢动作进行部分进入并保持", ["two adults", "fisting", "partial insertion", "hand insertion", "hip support", "consensual", "uncensored"], orientation="女女", role_slots=["辅助角色", "接受角色"], contact_points=["手与髋部", "手与身体中心", "大腿内侧"], action_prompt="the receiving adult lies on their back with hips raised and one knee supported by the giving adult, whose hand is partially inserted while the other arm steadies the receiver's hip in a slow fisting hold", camera="中景", intensity="极限"),
    _duo_r18_pose("partner_dual_object_coordinated", "双人玩法", "伴侣协同双物件", "接受方仰卧抬膝，辅助方双手分别控制两件柔性物件进行同步插入和节奏调整", ["two adults", "two objects", "dual insertion", "coordinated insertion", "knees raised", "consensual", "uncensored"], orientation="女女", role_slots=["操作角色", "接受角色"], contact_points=["双手与两件物件", "外阴", "大腿内侧"], action_prompt="the receiving adult reclines with knees raised while the other adult coordinates two flexible objects with both hands in a synchronized insertion sequence, the receiver's hands gripping the cushion", camera="中景", intensity="极限"),
    _duo_r18_pose("partner_labia_clamp_control", "双人玩法", "伴侣安装阴唇夹", "接受方仰卧抬膝，辅助方安装两只软垫阴唇夹并调整连接链条的轻微张力", ["two adults", "labia clamps", "padded clamps", "spreader chain", "knees raised", "consensual", "uncensored"], orientation="女女", role_slots=["辅助角色", "接受角色"], contact_points=["双手与阴唇夹", "外阴", "连接链条"], action_prompt="the receiving adult lies back with knees raised while the other adult fits two padded decorative labia clamps and adjusts a light spreader chain, the receiver keeping both hands on the thighs", camera="中景", intensity="极限"),
    _duo_r18_pose("partner_nipple_jewelry_tension", "双人玩法", "伴侣牵引乳头饰品", "接受方跪坐挺直上身，辅助方握住既有乳头穿刺饰品之间的链条向上持续牵引", ["two adults", "nipple jewelry", "piercing jewelry", "chain tension", "hard chain pull", "consensual", "uncensored"], orientation="女女", role_slots=["牵引角色", "接受角色"], contact_points=["手与链条", "乳头饰品", "肩部"], action_prompt="the receiving adult kneels upright while the other adult pulls a central chain connected to existing decorative nipple jewelry firmly upward, the skin and jewelry showing clear tension as the receiver arches with a consensual pain reaction", camera="中景", intensity="极限"),
    _duo_r18_pose("partner_intimate_jewelry_traction", "双人玩法", "伴侣牵引私密饰品", "接受方仰卧抬膝，辅助方拉住连接私密穿刺饰品的链条向上外侧持续施力", ["two adults", "intimate jewelry", "piercing jewelry", "chain traction", "knees raised", "consensual", "uncensored"], orientation="女女", role_slots=["牵引角色", "接受角色"], contact_points=["手与链条", "私密饰品", "大腿内侧"], action_prompt="the receiving adult lies back with knees open while the other adult draws a chain connected to existing decorative intimate jewelry upward and outward, the receiver gripping the cushion with a tense consensual response", camera="中景", intensity="极限"),
    _duo_r18_pose("partner_body_jewelry_multipoint_traction", "双人玩法", "伴侣多点牵引饰品", "接受方站立，辅助方拉住连接胸饰、脐环和私密饰品的中心链，形成多点同时受力", ["two adults", "body jewelry", "piercing jewelry", "multipoint tension", "standing", "consensual", "uncensored"], orientation="女女", role_slots=["牵引角色", "接受角色"], contact_points=["手与中心链", "多点饰品", "胸腹"], action_prompt="the receiving adult stands upright while the other adult pulls a central ring connected by chains to existing decorative chest, navel and intimate jewelry, creating visible multi-point tension without lifting the receiver", camera="全身", intensity="极限"),
    _duo_r18_pose("partner_restraint_dilation_predicament", "双人玩法", "伴侣限制扩张保持", "接受方仰卧并被宽松软带分开双膝，辅助方控制大型渐扩器具和计时器维持姿势", ["two adults", "soft thigh restraints", "dilation hold", "timer", "predicament", "consensual", "uncensored"], orientation="女女", role_slots=["控制角色", "接受角色"], contact_points=["软质腿带", "手与渐扩器具", "计时器"], action_prompt="the receiving adult lies back with both thighs held open in loose padded floor restraints while the other adult controls a large dilator and a visible timer, the receiver's hands gripping the cushion as the hold continues", camera="中景", intensity="极限"),

    # 高强度痛感与穿刺饰品受力扩充（12）
    _duo_r18_pose("sm_nipple_jewelry_weighted_traction_consensual", "痛感玩法", "乳头饰品悬重牵引", "接受方跪坐挺胸，既有乳头穿刺饰品通过链条悬挂配重并向下牵引皮肤，辅助方稳住肩部", ["nipple jewelry", "piercing jewelry", "weighted chain", "downward traction", "sensation pain", "consensual"], orientation="女女", role_slots=["辅助角色", "接受角色"], contact_points=["乳头饰品", "悬重链条", "肩部"], action_prompt="the receiving adult kneels upright while small weights hang from a chain connected to existing decorative nipple jewelry, pulling the skin and jewelry visibly downward as the other adult steadies the receiver's shoulder", camera="中景", intensity="极限"),
    _duo_r18_pose("sm_intimate_jewelry_chain_tension_consensual", "痛感玩法", "私密饰品强力牵引", "接受方仰卧抬膝，辅助方对连接私密穿刺饰品的链条施加持续强力牵引，接受方腿部紧绷颤抖", ["intimate jewelry", "piercing jewelry", "chain tension", "firm pull", "sensation pain", "consensual"], orientation="女女", role_slots=["牵引角色", "接受角色"], contact_points=["手与链条", "私密饰品", "大腿内侧"], action_prompt="the receiving adult lies on their back with knees raised while the other adult holds a chain connected to existing decorative intimate jewelry under firm but controlled tension, the receiver's thighs trembling", camera="中景", intensity="极限"),
    _duo_r18_pose("sm_navel_chain_weighted_consensual", "痛感玩法", "脐环悬重拉伸", "接受方站立并举高双臂，既有脐环连接链条和小型配重，重量使腹部皮肤明显向下受力", ["navel jewelry", "piercing jewelry", "weighted chain", "downward traction", "skin tension", "consensual"], orientation="女女", role_slots=["观察角色", "接受角色"], contact_points=["脐环", "悬重链条", "腹部"], action_prompt="the receiving adult stands with arms raised overhead while a small weight hangs from a chain connected to existing decorative navel jewelry, visibly drawing the skin downward as the other adult watches the tension", camera="中景", intensity="极限"),
    _duo_r18_pose("sm_body_jewelry_multipoint_tension_consensual", "痛感玩法", "多点穿刺饰品同步受力", "接受方站立，辅助方拉动连接胸饰、脐环和私密饰品的中心链，所有饰品点位同时明显受力", ["body jewelry", "piercing jewelry", "multipoint tension", "central chain pull", "sensation pain", "consensual"], orientation="女女", role_slots=["牵引角色", "接受角色"], contact_points=["中心链", "多点饰品", "胸腹"], action_prompt="the receiving adult stands upright while the other adult pulls a central chain linked to existing decorative chest, navel and intimate jewelry, creating visible multi-point skin tension and a strained consensual pain reaction", camera="全身", intensity="极限"),
    _duo_r18_pose("sm_wartenberg_wheel_thigh_consensual", "痛感玩法", "刺轮重压大腿", "接受方坐在软垫上绷紧大腿，辅助方将多排刺轮沿大腿外侧稳定重压滚动，留下表层红痕", ["wartenberg wheel", "outer thigh", "firm rolling pressure", "red pressure trails", "sensation pain", "consensual"], orientation="女女", role_slots=["操作角色", "接受角色"], contact_points=["多排刺轮", "大腿外侧", "手部"], action_prompt="the receiving adult sits with one thigh taut while the other adult rolls a multi-row Wartenberg wheel firmly along the outer thigh, leaving shallow red pressure trails on intact skin as the receiver flinches", camera="中景", intensity="极限"),
    _duo_r18_pose("sm_wartenberg_wheel_back_consensual", "痛感玩法", "刺轮重压背部", "接受方俯卧并绷紧上背，辅助方将多排刺轮沿肩胛到腰侧反复重压滚动", ["wartenberg wheel", "upper back", "firm rolling pressure", "red pressure trails", "sensation pain", "consensual"], orientation="女女", role_slots=["操作角色", "接受角色"], contact_points=["多排刺轮", "上背", "肩胛"], action_prompt="the receiving adult lies face down with the upper back taut while the other adult rolls a multi-row Wartenberg wheel firmly from the shoulder blades toward the waist, leaving shallow red pressure trails on intact skin and a sharp consensual pain reaction", camera="中景", intensity="极限"),
    _duo_r18_pose("sm_clamp_zipper_chain_pull_consensual", "痛感玩法", "链式衣夹持续拉紧", "接受方跪坐并绷紧上背，两排木质衣夹由细绳串联，辅助方持续拉动细绳使所有夹点同时受力", ["clamp zipper", "clothespins", "cord pull", "sustained pressure", "pain reaction", "consensual"], orientation="女女", role_slots=["牵引角色", "接受角色"], contact_points=["串联细绳", "两排衣夹", "上背"], action_prompt="the receiving adult kneels with many wooden clothespins arranged in two rows across the upper back and connected by a cord; the other adult pulls the cord steadily, tightening the chain of clamps as the receiver arches and gasps", camera="中景", intensity="极限"),
    _duo_r18_pose("sm_clamp_zipper_release_consensual", "痛感玩法", "链式衣夹集中释放", "接受方跪坐并保持背部紧绷，辅助方快速依次打开串联衣夹，所有夹点集中释放形成强烈痛感", ["clamp zipper", "clothespins", "rapid release", "concentrated pain spike", "pain reaction", "consensual"], orientation="女女", role_slots=["释放角色", "接受角色"], contact_points=["两排衣夹", "上背", "手部"], action_prompt="the receiving adult kneels with the same row of clothespins across the upper back while the other adult opens the clamps in a rapid sequence, producing a concentrated consensual pain spike", camera="中景", intensity="极限"),
    _duo_r18_pose("sm_labia_clamp_weighted_tension_consensual", "痛感玩法", "阴唇夹悬重拉伸", "接受方仰卧并保持双腿打开，软垫阴唇夹连接小型配重形成持续下拉，辅助方稳住一侧大腿", ["labia clamps", "weighted clamps", "spreader tension", "sustained stretch", "sensation pain", "consensual"], orientation="女女", role_slots=["辅助角色", "接受角色"], contact_points=["阴唇夹", "悬重链条", "大腿内侧"], action_prompt="the receiving adult lies back with knees held open while padded decorative labia clamps support small hanging weights, stretching the skin clearly as the other adult steadies one thigh", camera="中景", intensity="极限"),
    _duo_r18_pose("sm_clamp_endurance_timer_consensual", "痛感玩法", "双腿夹持耐力计时", "接受方坐稳并将双手放在身后，双腿排列多只衣夹，辅助方观察计时器并阻止其提前取下", ["clamp endurance", "clothespins", "both thighs", "timer", "sustained pressure", "consensual"], orientation="女女", role_slots=["监督角色", "接受角色"], contact_points=["衣夹", "双侧大腿", "计时器"], action_prompt="the receiving adult sits upright with rows of clothespins on both thighs while the other adult watches a visible timer and keeps the receiver's hands away from the clamps, the receiver enduring the sustained pressure with a pained consensual expression", camera="中景", intensity="极限"),
    _duo_r18_pose("sm_rope_harness_tension_floor_consensual", "痛感玩法", "低位绳网张力限制", "接受方贴近软垫俯卧，软绳在躯干和大腿形成张力网，辅助方逐步收紧但保持身体低位不悬空", ["rope harness", "floor restraint", "body tension", "low position", "predicament", "consensual"], orientation="女女", role_slots=["收紧角色", "接受角色"], contact_points=["软绳网", "躯干", "大腿"], action_prompt="the receiving adult lies low on a padded floor with a soft rope harness across the torso and thighs, limbs kept close to the floor while the other adult tensions the rope network without lifting or suspending the receiver", camera="中景", intensity="极限"),
    _duo_r18_pose("sm_predicament_clamp_dilation_hold_consensual", "痛感玩法", "夹持扩张双重保持", "接受方仰卧并被软垫阴唇夹保持轻微张力，辅助方同时维持大型渐扩器具和计时器，形成双重持续压力", ["labia clamps", "dilation hold", "timer", "combined predicament", "sustained stretch", "consensual"], orientation="女女", role_slots=["控制角色", "接受角色"], contact_points=["阴唇夹", "大型渐扩器具", "计时器"], action_prompt="the receiving adult lies back with padded labia clamps under light tension and a large dilator held in place while the other adult controls the position and watches a timer, the receiver gripping the cushion through the combined hold", camera="中景", intensity="极限"),

    # 非机械日常姿势扩充（5，源码完成，图片待生成）
    _pose_preset("pose_window_glance_back", "单人构图", "窗边回眸", "角色侧坐在窗边，身体朝向窗外并回头看向镜头，头部与双脚完整可见", ["solo", "1girl", "seated on window bench", "looking back", "looking at viewer", "full body", "clear face"], people="单人", orientation="单人", role_slots=["主体"], body_separation=False, contact_points=["臀部与窗边座椅", "双脚与地面"], camera="全身", sequence="进行中", rating="普通", intensity="标准", draw_prompt="exactly one adult anime woman in one full-body composition, seated sideways on a window bench and turning her head back toward the viewer, complete head and both feet visible, clear unobstructed face, no crop, no machinery, no collage"),
    _pose_preset("pose_kneeling_with_flowers", "单人展示", "跪坐捧花", "角色正面跪坐并双手捧花，花束位于胸前且不遮挡面部", ["solo", "1girl", "kneeling", "holding bouquet", "flowers in front of chest", "looking at viewer", "full body", "clear face"], people="单人", orientation="单人", role_slots=["主体"], body_separation=False, contact_points=["双手与花束", "膝部与软垫"], camera="全身", sequence="进行中", rating="普通", intensity="标准", draw_prompt="exactly one adult anime woman kneeling upright in one full-body composition, holding a bouquet in front of her chest without covering her face, complete head and both feet visible, clear expression, no machinery, no collage"),
    _pose_preset("pose_shared_reading", "双人接触", "并肩共读", "两名成年角色并肩坐在一起共读一本书，肩部自然相靠", ["two adults", "sitting side by side", "shared reading", "holding one book", "shoulders touching", "full body", "clear faces"], people="双人", orientation="中性", role_slots=["角色A", "角色B"], body_separation=False, contact_points=["肩部", "双手与书本"], camera="全身", sequence="进行中", rating="普通", intensity="标准", draw_prompt="exactly 2 separate adult anime characters seated side by side and reading one open book together, shoulders gently touching, both complete bodies and faces visible, no machinery, no extra people, no collage"),
    _pose_preset("pose_sofa_embrace", "常规", "沙发依偎", "一名角色靠坐在沙发上，另一名角色从侧面自然依偎并环抱肩部", ["two adults", "sofa", "leaning close", "affectionate embrace", "one arm around shoulder", "full body", "clear faces"], people="双人", orientation="中性", role_slots=["角色A", "角色B"], body_separation=False, contact_points=["肩部与手臂", "身体与沙发"], camera="全身", sequence="进行中", rating="普通", intensity="标准", draw_prompt="exactly 2 separate adult anime characters on a sofa, one seated upright while the other leans close from the side with one arm around the shoulders, both complete bodies and faces visible, no machinery, no extra people, no collage"),
    _pose_preset("pose_slow_dance_embrace", "常规", "慢舞相拥", "两名成年角色保持站姿轻握慢舞，一只手搭肩、一只手扶腰，双脚完整可见", ["two adults", "slow dance", "standing embrace", "hand on shoulder", "hand at waist", "full body", "clear faces"], people="双人", orientation="中性", role_slots=["角色A", "角色B"], body_separation=False, contact_points=["手与肩部", "手与腰部", "双脚与地面"], camera="全身", sequence="进行中", rating="普通", intensity="标准", draw_prompt="exactly 2 separate adult anime characters in one continuous slow dance, standing chest to chest with one hand on a shoulder and one hand at the waist, both complete bodies, faces and feet visible, no machinery, no extra people, no collage"),

    # 女性痛感与穿刺饰品玩法扩充（20，源码完成，图片待生成）
    _solo_r18_pose(
        "solo_mirror_nipple_jewelry_tension",
        "单人前戏",
        "镜前胸前饰品牵引",
        "女性角色站在镜前，用手控制既有胸前饰品链的张力，镜中同步呈现吃痛表情、腰背反应和完整身体",
        ["solo", "1girl", "mirror", "nipple jewelry", "chain tension", "controlled pull", "arched back", "pain reaction", "full body", "uncensored"],
        ["手与饰品链", "胸前饰品", "镜面"],
        camera="全身",
        sequence="前戏",
        intensity="强化",
    ),
    _solo_r18_pose(
        "solo_navel_chain_guided_tension",
        "单人前戏",
        "脐环链分级牵引",
        "女性角色用手逐级改变既有脐环链的张力，腹部收紧、身体前倾并呈现持续的疼痛反馈",
        ["solo", "1girl", "navel jewelry", "chain tension", "controlled pull", "hand on chain", "abdomen tension", "pain reaction", "uncensored"],
        ["手与饰品链", "脐环", "腰腹"],
        camera="全身",
        sequence="前戏",
        intensity="强化",
    ),
    _solo_r18_pose(
        "solo_intimate_jewelry_insertion_feedback",
        "单人玩具",
        "私密饰品与插入反馈",
        "女性角色侧卧抬腿，一手控制既有私密饰品链的轻微张力，另一手持玩具进行插入并保持双重受力",
        ["solo", "1girl", "side lying", "intimate jewelry", "chain tension", "toy insertion", "dual stimulation", "pain reaction", "uncensored"],
        ["手与饰品链", "手持玩具", "大腿内侧"],
        camera="全身",
        sequence="进行中",
        intensity="极限",
    ),
    _solo_r18_pose(
        "solo_dual_toy_alternating_rhythm",
        "单人玩具",
        "双玩具交替节奏",
        "女性角色仰卧屈膝，双手分别持前后两件玩具进行交替使用，以腿部和腰腹反应表现节奏差异",
        ["solo", "1girl", "lying on back", "two toys", "alternating rhythm", "vaginal toy", "rear toy", "body reaction", "uncensored"],
        ["双手与玩具", "大腿内侧", "腰腹"],
        camera="全身",
        sequence="进行中",
        intensity="强化",
    ),
    _solo_r18_pose(
        "solo_kneeling_dilation_pain_feedback",
        "单人极限",
        "跪姿扩张痛感反馈",
        "女性角色跪坐在软垫上，手持渐扩器具调整角度并继续扩张，身体紧绷、颤抖和呼吸变化清晰可见",
        ["solo", "1girl", "kneeling", "dilation", "graduated dilator", "pain reaction", "trembling", "uncensored"],
        ["手持渐扩器具", "大腿内侧", "膝部与软垫"],
        camera="全身",
        sequence="进行中",
        intensity="极限",
    ),
    _solo_r18_pose(
        "solo_wall_supported_toy_insertion",
        "单人玩具",
        "靠墙单腿玩具插入",
        "女性角色背部靠墙并抬起单腿，一手稳定身体，一手控制玩具进入深度，保持单脚支撑和完整身体",
        ["solo", "1girl", "against wall", "one leg raised", "toy insertion", "one hand support", "balance", "body reaction", "uncensored"],
        ["背部与墙面", "单脚与地面", "手持玩具"],
        camera="全身",
        sequence="进行中",
        intensity="极限",
    ),
    _solo_r18_pose(
        "solo_piercing_tension_release_afterplay",
        "单人结束",
        "饰品张力解除余韵",
        "女性角色放松身体，逐级释放既有饰品链的张力，表现余痛、呼吸恢复和结束后的安静状态",
        ["solo", "1girl", "body jewelry", "chain release", "afterplay", "afterglow", "relaxed breathing", "uncensored"],
        ["手与饰品链", "胸前与腰腹", "软垫"],
        camera="全身",
        sequence="结束",
        intensity="强化",
    ),
    _duo_r18_pose(
        "duo_face_to_face_hair_pull_feedback",
        "痛感玩法",
        "面对面交合与拉发反馈",
        "女性接受方与伴侣面对面交合，主动方轻握一束头发控制力度，女性角色的表情和呼吸决定下一个节奏",
        ["two adults", "face to face", "vaginal sex", "hair pulling", "controlled force", "pain reaction", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["主动方", "女性接受方"],
        contact_points=["手与头发", "髋部", "腿部"],
        action_prompt="the female receiver and her partner have continuous face-to-face intercourse while the active partner holds one lock of the female receiver's hair under controlled force; her expression and breathing visibly guide the next rhythm",
        camera="全身",
        intensity="强化",
    ),
    _duo_r18_pose(
        "duo_front_rear_jewelry_tension",
        "双人玩法",
        "前后刺激与饰品牵引",
        "女性接受方承受正面交合和后向玩具的双重刺激，主动方同时用手控制既有身体饰品链的张力",
        ["two adults", "vaginal sex", "rear toy", "body jewelry", "chain tension", "dual stimulation", "female receiver", "pain reaction", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["主动方", "女性接受方"],
        contact_points=["正面交合", "后向玩具", "身体饰品链"],
        action_prompt="the active partner performs continuous vaginal sex on the female receiver while also using a rear toy and pulling a short chain connected to her existing body jewelry; the receiver shows clear dual stimulation and pain response",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "duo_cowgirl_piercing_control",
        "双人玩法",
        "女上节奏与饰品受力",
        "女性接受方坐在伴侣身上控制骑乘节奏，伴侣同步控制胸前或私密既有饰品的轻微张力",
        ["two adults", "cowgirl position", "nipple jewelry", "chain tension", "female controls rhythm", "pain reaction", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["女性主动方", "辅助方"],
        contact_points=["胯部", "手与饰品链", "胸腹"],
        action_prompt="the female receiver rides her partner and controls the rhythm while the other adult applies controlled tension to her existing chest or intimate jewelry; her posture and pain response remain clearly visible",
        camera="全身",
        intensity="强化",
    ),
    _duo_r18_pose(
        "duo_side_entry_bite_feedback",
        "痛感玩法",
        "侧位进入与咬痕反馈",
        "女性接受方侧卧抬腿接受进入，主动方在肩颈处形成短时牙印，女性角色出现紧绷和疼痛反应",
        ["two adults", "side entry", "vaginal sex", "biting shoulder", "love bite", "short mark", "pain reaction", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["主动方", "女性接受方"],
        contact_points=["髋部", "肩颈", "牙齿与皮肤"],
        action_prompt="the female receiver lies on her side with one leg raised for continuous vaginal entry while the active partner bites her shoulder and neck, leaving only a shallow temporary mark as she tenses with a pain response",
        camera="全身",
        intensity="强化",
    ),
    _duo_r18_pose(
        "duo_partner_guided_dilation_pain",
        "双人玩法",
        "伴侣引导扩张痛感",
        "女性接受方仰卧抬膝，辅助方控制扩张器具的角度和保持节奏，女性角色的疼痛反馈决定继续或回退",
        ["two adults", "partner guided dilation", "graduated dilator", "pain reaction", "hips supported", "controlled angle", "consensual", "uncensored"],
        orientation="女女",
        role_slots=["引导方", "女性接受方"],
        contact_points=["手与扩张器具", "手与髋部", "大腿内侧"],
        action_prompt="the female receiver lies back with knees raised while her female partner guides a graduated dilator at a controlled angle and holds the position only while the receiver accepts it, with clear pain and breathing feedback",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "duo_oral_nipple_jewelry_tension",
        "痛感玩法",
        "口部刺激与胸前饰品牵引",
        "女性接受方接受口部刺激，伴侣同时分级牵引既有胸前饰品链，疼痛反应与快感反馈同时可见",
        ["two adults", "cunnilingus", "nipple jewelry", "chain tension", "female receiver", "pain reaction", "consensual", "uncensored"],
        orientation="女女",
        role_slots=["刺激方", "女性接受方"],
        contact_points=["口部刺激", "手与饰品链", "胸腹"],
        action_prompt="the female receiver receives continuous oral stimulation while her female partner applies controlled tension to her existing chest jewelry, showing both pleasure and a clear pain reaction",
        camera="全身",
        intensity="强化",
    ),
    _duo_r18_pose(
        "duo_lesbian_reciprocal_jewelry_control",
        "女同",
        "女女互相控制饰品张力",
        "两名成年女性轮流控制对方既有饰品链的张力，双方都承担主动与承受角色并持续反馈疼痛状态",
        ["two adult women", "body jewelry", "chain tension", "reciprocal control", "female receiver", "pain reaction", "consensual", "uncensored"],
        orientation="女女",
        role_slots=["女性主动方", "女性接受方"],
        contact_points=["双手与饰品链", "胸前与腰腹", "相互身体接触"],
        action_prompt="two adult women take turns applying controlled tension to each other's existing body jewelry in a reciprocal sequence, with both women remaining active and visibly reacting to the pain",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "duo_scissor_finger_pain_feedback",
        "女同",
        "磨镜手指同步痛感",
        "两名成年女性进行磨镜接触，其中一方用手指和既有饰品牵引增加疼痛反馈，由接受方反应决定节奏",
        ["two adult women", "scissoring", "fingering", "jewelry tension", "pain reaction", "mutual contact", "consensual", "uncensored"],
        orientation="女女",
        role_slots=["女性主动方", "女性接受方"],
        contact_points=["腿部与胯部", "手指接触", "手与饰品链"],
        action_prompt="two adult women maintain continuous scissoring contact while one partner uses her fingers and controlled jewelry tension to add pain feedback, with the female receiver's reaction guiding each change",
        camera="全身",
        intensity="强化",
    ),
    _duo_r18_pose(
        "duo_mutual_remote_toy_control",
        "双人玩法",
        "互相遥控玩具",
        "两名角色分别控制对方的遥控玩具，根据实时表情、呼吸和腿部反应推进刺激阶段",
        ["two adults", "remote control toy", "mutual control", "toy stimulation", "body reaction", "continuous feedback", "consensual", "uncensored"],
        orientation="女女",
        role_slots=["女性角色A", "女性角色B"],
        contact_points=["各自手持遥控器", "玩具与身体", "腿部接触"],
        action_prompt="two adult women each control the other's remote toy in one continuous scene, watching facial expressions and body reactions as they advance or pause the stimulation",
        camera="全身",
        intensity="强化",
    ),
    _duo_r18_pose(
        "duo_position_shift_with_jewelry_tension",
        "双人玩法",
        "体位转换保持饰品张力",
        "两名角色从坐姿转换到跪撑或侧卧，过程中保持身体接触和既有饰品链张力，不出现拼图或分屏",
        ["two adults", "position change", "body jewelry", "chain tension", "continuous contact", "pain reaction", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["主动方", "女性接受方"],
        contact_points=["手与饰品链", "髋部", "支撑腿"],
        action_prompt="the active partner keeps continuous contact while the female receiver shifts from a seated position into kneeling support or side lying, maintaining controlled tension on her existing jewelry through the transition in one scene",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "duo_bathtub_face_to_face_entry",
        "双人玩法",
        "浴缸面对面进入",
        "两名成年角色在浴缸中面对面进入，保持水面、支撑点和双方完整身体轮廓清晰可见",
        ["two adults", "bathtub", "face to face", "vaginal sex", "wet skin", "water", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["主动方", "女性接受方"],
        contact_points=["胯部", "手臂支撑", "浴缸边缘"],
        action_prompt="two adult anime characters have continuous face-to-face vaginal sex in a bathtub, with the water surface, support points and both complete bodies clearly visible in one scene",
        camera="全身",
        intensity="强化",
    ),
    _duo_r18_pose(
        "duo_multi_point_piercing_guided_release",
        "痛感玩法",
        "多点饰品分级解除",
        "女性接受方的胸前、脐部和私密既有饰品链被伴侣依次放松，表现余痛、呼吸回落和身体状态恢复",
        ["two adults", "multi point body jewelry", "chain release", "graded release", "pain relief", "afterplay", "female receiver", "consensual", "uncensored"],
        orientation="女女",
        role_slots=["照护方", "女性接受方"],
        contact_points=["手与多点饰品链", "胸前与腰腹", "伴侣支撑"],
        action_prompt="the female receiver remains supported while her female partner releases tension from her existing chest, navel and intimate jewelry chains one point at a time, showing gradual pain relief and breathing recovery",
        camera="全身",
        intensity="强化",
        sequence="结束",
    ),
    _duo_r18_pose(
        "duo_slow_withdrawal_pain_afterplay",
        "双人玩法",
        "缓慢退出与痛感余韵",
        "女性接受方在缓慢退出玩具或身体接触后保持依偎，伴侣通过互抚和呼吸观察表现余痛与情绪回落",
        ["two adults", "slow withdrawal", "afterplay", "mutual touch", "pain afterglow", "close embrace", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["照护方", "女性接受方"],
        contact_points=["缓慢退出", "手臂与肩背", "相互依偎"],
        action_prompt="the female receiver remains in a close embrace after slow withdrawal while her partner gently touches her shoulder and waist, showing lingering pain and a calm return to a relaxed state",
        camera="全身",
        intensity="强化",
        sequence="结束",
    ),
    _duo_r18_pose(
        "young_male_forced_wall_pin_consensual",
        "痛感玩法",
        "年轻男性墙边压制",
        "更矮小的年轻成年男性将成年女性接受方压在墙边，女性持续挣扎但在合意角色扮演中承受压制",
        ["two adults", "same-age adult partners", "young-looking adult male", "smaller male", "wall pin", "female receiver", "struggle", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["手与肩部", "身体与墙面", "腰部"],
        action_prompt="a shorter, younger-looking adult man pins the adult woman against a plain wall while she visibly struggles in a mutually consensual CNC roleplay scene",
        camera="全身",
        intensity="强化",
    ),
    _duo_r18_pose(
        "young_male_forced_kneel_control_consensual",
        "痛感玩法",
        "年轻男性强制跪姿控制",
        "女性接受方被年轻成年男性压制为跪姿，男性控制肩膀和腰部并突出体型反差",
        ["two adults", "same-age adult partners", "young-looking adult male", "forced kneeling", "shoulder control", "waist control", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["手与肩膀", "手与腰部", "膝部与软垫"],
        action_prompt="the younger-looking adult male presses the adult woman into a kneeling position on a soft mat while controlling her shoulder and waist in a consensual CNC scene",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "young_male_hair_pull_command_consensual",
        "痛感玩法",
        "年轻男性拉发命令",
        "年轻成年男性从后方控制女性头发和姿态，女性接受方呈现吃痛、紧绷和服从反应",
        ["two adults", "same-age adult partners", "young-looking adult male", "hair pulling", "rear control", "pain reaction", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["手与头发", "肩背", "腰部"],
        action_prompt="the younger-looking adult male stands behind the adult woman and controls her hair and posture with a firm pull, her face showing a pain response within a consensual roleplay",
        camera="全身",
        intensity="强化",
    ),
    _duo_r18_pose(
        "young_male_forced_toy_insertion_consensual",
        "双人玩法",
        "年轻男性强制器具控制",
        "女性接受方被固定姿势，年轻成年男性控制器具角度和节奏，女性出现抵抗与疼痛反应",
        ["two adults", "same-age adult partners", "young-looking adult male", "forced toy control", "tool angle", "struggle", "pain reaction", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["手与器具", "大腿内侧", "腰部"],
        action_prompt="the younger-looking adult male controls a toy angle and rhythm while the adult woman is held in place, showing visible resistance and pain in a consensual CNC scene",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "young_male_intimate_biting_control_consensual",
        "痛感玩法",
        "年轻男性咬性器控制",
        "年轻成年男性在合意角色扮演中咬住女性接受方私密部位，女性出现短时疼痛反应和压制挣扎",
        ["two adults", "same-age adult partners", "young-looking adult male", "intimate biting", "pain reaction", "struggle", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["口部与私密部位", "手与髋部", "腿部"],
        action_prompt="the younger-looking adult male briefly bites the adult woman's intimate area while she reacts with pain and struggle in a mutually consensual CNC roleplay scene",
        camera="中景",
        intensity="极限",
    ),
    _duo_r18_pose(
        "young_male_piercing_tension_control_consensual",
        "痛感玩法",
        "年轻男性穿刺饰品牵引",
        "男性控制女性既有胸饰、脐饰或私密饰品链，女性因受力和强迫感而弓身并挣扎",
        ["two adults", "same-age adult partners", "young-looking adult male", "piercing jewelry", "chain tension", "female receiver", "pain reaction", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["手与饰品链", "胸前或腰腹", "身体支撑点"],
        action_prompt="the younger-looking adult male applies controlled tension to the adult woman's existing piercing jewelry while she arches and struggles in a consensual CNC scene",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "sibling_dynamic_mirror_command_consensual",
        "双人玩法",
        "姐弟感镜前命令",
        "通过体型和年轻外貌形成姐弟感，女性接受方在镜前被命令维持姿势，动作和视角保持自然",
        ["two adults", "same-age adult partners", "sister-brother visual dynamic", "young-looking adult male", "mirror", "commanding posture", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["手与肩膀", "镜前姿态", "腰部"],
        action_prompt="the shorter younger-looking adult male commands the adult woman to hold a mirror-facing pose, creating a sister-brother visual dynamic without implying real kinship or non-adult ages",
        camera="全身",
        intensity="强化",
    ),
    _duo_r18_pose(
        "maternal_dynamic_lap_control_consensual",
        "双人玩法",
        "母子感膝上压制",
        "通过外观年龄差形成母子感，较小男性控制女性姿势，女性出现挣扎和疼痛反馈",
        ["two adults", "same-age adult partners", "mother-son visual dynamic", "young-looking adult male", "lap control", "female receiver", "struggle", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["手与腰部", "大腿与支撑面", "肩部"],
        action_prompt="the younger-looking adult male controls the adult woman across his lap, creating a mother-son visual dynamic through appearance only while she reacts with struggle and pain in a consensual scene",
        camera="全身",
        intensity="强化",
    ),
    _duo_r18_pose(
        "size_contrast_reverse_dominance_consensual",
        "双人玩法",
        "体型反差逆压制",
        "女性体型更大但被较小、更年轻的男性压制，画面强调体型反差和合意控制感",
        ["two adults", "same-age adult partners", "smaller male", "young-looking adult male", "larger adult woman", "size contrast", "reverse dominance", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["手与肩部", "身体压制", "腿部"],
        action_prompt="the smaller younger-looking adult male dominates the taller adult woman through posture and leverage, emphasizing the body-size contrast in a consensual CNC roleplay scene",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "young_pair_pain_aftercare_check_consensual",
        "双人玩法",
        "年轻同龄组合事后检查",
        "强制玩法结束后，男性检查女性浅表痕迹、呼吸和状态，形成余痛与照护收尾",
        ["two adults", "same-age adult partners", "young-looking adult male", "aftercare", "mark inspection", "breathing check", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["照护方", "女性接受方"],
        contact_points=["手与肩背", "浅表痕迹检查", "伴侣支撑"],
        action_prompt="after the consensual scene, the younger-looking adult male checks the adult woman's shallow temporary marks and breathing while she rests, showing pain afterglow and calm aftercare",
        camera="全身",
        intensity="强化",
        sequence="结束",
    ),
    _pose_preset(
        "gentle_lap_rest_younger_male_consensual",
        "双人接触",
        "年轻男性膝上依偎",
        "成年女性坐在更矮小、年轻外貌的成年男性腿上，双方自然依偎，动作轻柔且身体协调",
        ["two adults", "same-age adult partners", "young-looking adult male", "woman sitting on lap", "gentle embrace", "fully clothed", "soft loungewear", "consensual"],
        people="双人",
        orientation="男女",
        role_slots=["女性角色", "年轻男性"],
        contact_points=["腿部支撑", "肩部", "彼此手臂"],
        camera="全身",
        sequence="进行中",
        rating="普通",
        intensity="标准",
        draw_prompt="two same-age adult anime characters in a gentle lap-rest scene, the adult woman comfortably seated on the lap of a shorter younger-looking adult man, wearing soft loungewear, natural balanced posture, both faces and bodies clearly visible, no pain or extreme elements",
    ),
    _pose_preset(
        "gentle_rear_hug_younger_male_consensual",
        "双人接触",
        "年轻男性背后环抱",
        "更矮小的年轻成年男性从身后环抱成年女性，女性自然靠向对方，动作温和协调",
        ["two adults", "same-age adult partners", "young-looking adult male", "rear hug", "gentle embrace", "fully clothed", "soft home clothing", "consensual"],
        people="双人",
        orientation="男女",
        role_slots=["女性角色", "年轻男性"],
        contact_points=["肩部", "腰部", "手臂"],
        camera="全身",
        sequence="进行中",
        rating="普通",
        intensity="标准",
        draw_prompt="two same-age adult anime characters in a gentle rear-hug scene, the shorter younger-looking adult man gently embracing the adult woman from behind while she leans naturally into him, fully clothed, balanced composition, no pain or extreme elements",
    ),
    _pose_preset(
        "gentle_bath_wash_younger_male_consensual",
        "双人接触",
        "年轻男性浴室擦洗",
        "年轻成年男性用柔软浴巾为成年女性擦洗肩背，环境温暖安静，双方动作自然",
        ["two adults", "same-age adult partners", "young-looking adult male", "bath wash", "soft towel", "bathrobe", "wet bathroom", "consensual"],
        people="双人",
        orientation="男女",
        role_slots=["年轻男性", "女性角色"],
        contact_points=["毛巾与肩背", "手臂", "浴室支撑"],
        camera="全身",
        sequence="进行中",
        rating="普通",
        intensity="标准",
        draw_prompt="two same-age adult anime characters in a warm private bathroom, the younger-looking adult man gently washing the adult woman's shoulder and back with a soft towel while both wear bathrobes, calm expressions, no pain or extreme elements",
    ),
    _pose_preset(
        "gentle_bedtime_cuddle_younger_male_consensual",
        "双人接触",
        "年轻男性睡前抱躺",
        "两人穿着睡衣在床边安静抱躺，女性自然靠在年轻男性怀里，动作松弛",
        ["two adults", "same-age adult partners", "young-looking adult male", "bedtime cuddle", "pajamas", "lying close", "gentle embrace", "consensual"],
        people="双人",
        orientation="男女",
        role_slots=["女性角色", "年轻男性"],
        contact_points=["肩部", "手臂", "床铺"],
        camera="全身",
        sequence="进行中",
        rating="普通",
        intensity="标准",
        draw_prompt="two same-age adult anime characters wearing pajamas and resting closely on a bed, the adult woman leaning naturally against the shorter younger-looking adult man, gentle expressions, complete bodies visible, no pain or extreme elements",
    ),
    _pose_preset(
        "gentle_apron_embrace_younger_male_consensual",
        "双人接触",
        "年轻男性厨房围裙环抱",
        "成年女性穿着居家围裙，年轻男性从侧后方轻轻环住腰部，厨房氛围温暖日常",
        ["two adults", "same-age adult partners", "young-looking adult male", "kitchen", "apron outfit", "gentle waist embrace", "fully clothed", "consensual"],
        people="双人",
        orientation="男女",
        role_slots=["女性角色", "年轻男性"],
        contact_points=["腰部", "手臂", "厨房台面"],
        camera="全身",
        sequence="进行中",
        rating="普通",
        intensity="标准",
        draw_prompt="two same-age adult anime characters in a warm home kitchen, the adult woman wearing a simple apron while the shorter younger-looking adult man gently embraces her waist from the side, casual clothing, balanced posture, no pain or extreme elements",
    ),
    _pose_preset(
        "gentle_mirror_dress_help_younger_male_consensual",
        "双人接触",
        "年轻男性镜前换衣协助",
        "年轻成年男性在镜前协助女性整理肩带或外衣，双方动作自然，构图明确",
        ["two adults", "same-age adult partners", "young-looking adult male", "mirror", "helping with clothing", "fully clothed", "gentle interaction", "consensual"],
        people="双人",
        orientation="男女",
        role_slots=["女性角色", "年轻男性"],
        contact_points=["手与肩带", "镜前站位", "手臂"],
        camera="全身",
        sequence="进行中",
        rating="普通",
        intensity="标准",
        draw_prompt="two same-age adult anime characters in front of a mirror, the shorter younger-looking adult man gently helps the adult woman adjust a shoulder strap or outer garment, both fully clothed, natural coordinated poses, no pain or extreme elements",
    ),
    _duo_r18_pose(
        "cnc_smaller_male_forced_penetration_r18",
        "痛感玩法",
        "较小年轻男性强制插入",
        "更矮小的年轻成年男性压制女性接受方并进行强制插入，女性表现挣扎与疼痛反馈",
        ["two adults", "same-age adult partners", "young-looking adult male", "forced penetration", "female receiver", "struggle", "pain reaction", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["手与腰部", "髋部", "腿部"],
        action_prompt="the smaller younger-looking adult man forces continuous penetration while the adult woman struggles with visible pain in a mutually consensual CNC roleplay",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "cnc_smaller_male_forced_oral_r18",
        "痛感玩法",
        "强制口部控制",
        "年轻成年男性按住女性接受方进行强制口部控制，女性出现挣扎、皱眉和疼痛反应",
        ["two adults", "same-age adult partners", "young-looking adult male", "forced oral", "female receiver", "struggle", "pain reaction", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["手与头部", "肩部", "口部接触"],
        action_prompt="the smaller younger-looking adult man holds the adult woman in place for forced oral contact while she struggles and shows pain in a consensual CNC scene",
        camera="中景",
        intensity="极限",
    ),
    _duo_r18_pose(
        "cnc_smaller_male_forced_toy_double_r18",
        "双人玩法",
        "强制双器具控制",
        "女性接受方被固定姿势，年轻男性同时控制两件器具并持续调整节奏",
        ["two adults", "same-age adult partners", "young-looking adult male", "two toys", "forced toy control", "female receiver", "struggle", "pain reaction", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["双手与两件器具", "大腿内侧", "腰部"],
        action_prompt="the smaller younger-looking adult man controls two adult toys at once while the adult woman is held in place, showing struggle and pain in a consensual CNC scene",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "cnc_smaller_male_piercing_penetration_r18",
        "痛感玩法",
        "穿刺饰品与插入双重受力",
        "插入过程中，年轻男性同时牵引女性既有穿刺饰品，形成双重受力与疼痛反馈",
        ["two adults", "same-age adult partners", "young-looking adult male", "penetration", "piercing jewelry", "chain tension", "female receiver", "pain reaction", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["手与饰品链", "髋部", "胸前或腰腹"],
        action_prompt="the smaller younger-looking adult man maintains penetration while pulling a short chain connected to the adult woman's existing piercing jewelry, producing dual tension and pain in a consensual scene",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "cnc_smaller_male_intimate_biting_r18",
        "痛感玩法",
        "咬性器与压制",
        "年轻成年男性在压制女性接受方时咬住私密部位，女性出现短时疼痛和身体颤抖",
        ["two adults", "same-age adult partners", "young-looking adult male", "intimate biting", "body pin", "female receiver", "pain reaction", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["口部与私密部位", "手与髋部", "腿部"],
        action_prompt="the smaller younger-looking adult man bites the adult woman's intimate area while pinning her body, showing a brief pain reaction in a mutually consensual CNC scene",
        camera="中景",
        intensity="极限",
    ),
    _duo_r18_pose(
        "cnc_sister_dynamic_mirror_penetration_r18",
        "双人玩法",
        "姐弟感镜前强制插入",
        "通过体型和年轻外貌形成姐弟感，在镜前进行合意强迫插入并保持完整身体",
        ["two adults", "same-age adult partners", "sister-brother visual dynamic", "young-looking adult male", "mirror", "penetration", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["镜前姿态", "髋部", "腰部"],
        action_prompt="the smaller younger-looking adult man performs continuous penetration with the adult woman in front of a mirror, creating a sister-brother visual dynamic through appearance only in a consensual CNC scene",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "cnc_maternal_dynamic_lap_penetration_r18",
        "双人玩法",
        "母子感膝上控制",
        "通过外观形成母子感，女性接受方被控制为膝上姿势并承受插入节奏",
        ["two adults", "same-age adult partners", "mother-son visual dynamic", "young-looking adult male", "lap position", "penetration", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["腿部支撑", "腰部", "肩部"],
        action_prompt="the smaller younger-looking adult man controls the adult woman in a lap position during continuous penetration, creating a mother-son visual dynamic through appearance only in a consensual CNC scene",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "cnc_size_contrast_reverse_carry_r18",
        "双人玩法",
        "体型反差反向托举",
        "女性体型更大，但被较小年轻男性托举控制，强调体型反差和合意强迫感",
        ["two adults", "same-age adult partners", "smaller male", "young-looking adult male", "larger adult woman", "reverse carry", "penetration", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["手臂托举", "腿弯", "髋部"],
        action_prompt="the smaller younger-looking adult man lifts and controls the larger adult woman in a reverse carry during continuous penetration, emphasizing body-size contrast in a consensual CNC scene",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "cnc_young_pair_restraint_toy_r18",
        "双人玩法",
        "合意限制与器具控制",
        "女性接受方被软质限制保持姿势，年轻男性控制插入与器具节奏",
        ["two adults", "same-age adult partners", "young-looking adult male", "soft restraint", "toy control", "penetration", "female receiver", "pain reaction", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性主动方", "女性接受方"],
        contact_points=["软质限制", "手持器具", "髋部"],
        action_prompt="the smaller younger-looking adult man uses soft restraints to keep the adult woman in position while controlling penetration and toy rhythm in a consensual CNC scene",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "cnc_young_pair_pain_aftercare_r18",
        "双人玩法",
        "强制玩法后的检查与照护",
        "强制玩法结束后，男性检查女性浅表痕迹、呼吸和状态，表现余痛与照护",
        ["two adults", "same-age adult partners", "young-looking adult male", "aftercare", "mark inspection", "breathing check", "female receiver", "pain afterglow", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["照护方", "女性接受方"],
        contact_points=["手与肩背", "浅表痕迹检查", "伴侣支撑"],
        action_prompt="after the consensual scene, the smaller younger-looking adult man checks the adult woman's shallow temporary marks and breathing while she rests, showing pain afterglow and calm aftercare",
        camera="全身",
        intensity="强化",
        sequence="结束",
    ),
    _duo_r18_pose(
        "r18_young_male_guided_tease",
        "双人玩法",
        "年轻男性温柔引导前戏",
        "更矮小的年轻成年男性温柔引导女性进入前戏，节奏缓慢并保持双方舒适",
        ["two adults", "same-age adult partners", "young-looking adult male", "guided foreplay", "gentle touch", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性", "女性接受方"],
        contact_points=["手与肩颈", "腰部", "腿部"],
        action_prompt="the smaller younger-looking adult man gently guides the adult woman through foreplay with slow touch and continuous visual feedback in a consensual scene",
        camera="全身",
        intensity="标准",
    ),
    _duo_r18_pose(
        "r18_young_male_oral_service",
        "双人常规",
        "年轻男性口部服务",
        "年轻成年男性为女性接受方提供持续口部服务，女性动作自然并给予反馈",
        ["two adults", "same-age adult partners", "young-looking adult male", "cunnilingus", "oral service", "female receiver", "pleasure response", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性", "女性接受方"],
        contact_points=["口部接触", "大腿", "腰部"],
        action_prompt="the smaller younger-looking adult man performs continuous oral service for the adult woman while she responds naturally in a gentle consensual scene",
        camera="全身",
        intensity="标准",
    ),
    _duo_r18_pose(
        "r18_young_male_mutual_masturbation",
        "双人玩法",
        "双方互相抚慰",
        "双方以自然姿势互相抚慰并同步节奏，保持完整身体与清楚动作",
        ["two adults", "same-age adult partners", "young-looking adult male", "mutual masturbation", "mutual touch", "shared rhythm", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["女性角色", "年轻男性"],
        contact_points=["手与身体", "腿部", "肩部"],
        action_prompt="two same-age adult partners face each other in a gentle mutual masturbation scene, synchronizing their touch and visible responses without pain or coercion",
        camera="全身",
        intensity="标准",
    ),
    _duo_r18_pose(
        "r18_young_male_cowgirl_control",
        "双人玩法",
        "女性主导骑乘节奏",
        "女性接受方掌握骑乘节奏，年轻男性配合并保持自然视线与身体协调",
        ["two adults", "same-age adult partners", "young-looking adult male", "cowgirl position", "female controls rhythm", "vaginal sex", "pleasure response", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["女性主动方", "年轻男性"],
        contact_points=["髋部", "腿部", "手与肩部"],
        action_prompt="the adult woman controls the rhythm in a gentle cowgirl scene with the smaller younger-looking adult man, both moving naturally with clear pleasure and no extreme elements",
        camera="全身",
        intensity="强化",
    ),
    _duo_r18_pose(
        "r18_young_male_spooning_intimacy",
        "双人玩法",
        "侧卧贴合式亲密互动",
        "双方侧卧贴合，年轻男性从后方进行温和亲密互动，动作自然稳定",
        ["two adults", "same-age adult partners", "young-looking adult male", "spooning", "side-lying sex", "gentle intimacy", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性", "女性接受方"],
        contact_points=["髋部", "腰部", "腿部"],
        action_prompt="two same-age adult partners lie on their sides in a gentle spooning sex scene, the smaller younger-looking adult man moving slowly while both bodies remain naturally aligned",
        camera="全身",
        intensity="标准",
    ),
    _duo_r18_pose(
        "r18_young_male_bathtub_together",
        "双人玩法",
        "浴缸亲密互动",
        "两人共同浸在水中进行温柔亲密互动，突出水面、支撑和身体协调",
        ["two adults", "same-age adult partners", "young-looking adult male", "bathtub", "water", "gentle sex", "wet skin", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["女性角色", "年轻男性"],
        contact_points=["手臂支撑", "腿部", "浴缸边缘"],
        action_prompt="two same-age adult partners share a warm bathtub and engage in gentle intimate sex, with the water, support points and both complete bodies clearly visible",
        camera="全身",
        intensity="标准",
    ),
    _duo_r18_pose(
        "r18_young_male_sofa_lap_sex",
        "双人玩法",
        "沙发膝上式亲密互动",
        "女性坐在年轻男性腿上缓慢互动，沙发提供稳定支撑，动作自然放松",
        ["two adults", "same-age adult partners", "young-looking adult male", "sofa", "lap sex", "gentle rhythm", "female controls pace", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["女性主动方", "年轻男性"],
        contact_points=["腿部", "腰部", "沙发支撑"],
        action_prompt="the adult woman sits on the lap of the smaller younger-looking adult man on a sofa, controlling a gentle intimate rhythm with relaxed balanced posture",
        camera="全身",
        intensity="标准",
    ),
    _duo_r18_pose(
        "r18_young_male_shower_embrace_sex",
        "双人玩法",
        "淋浴间相拥与温和进入",
        "两人在淋浴间相拥并进行温和进入，水雾和支撑点清楚且动作协调",
        ["two adults", "same-age adult partners", "young-looking adult male", "shower", "standing sex", "embrace", "wet skin", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["女性接受方", "年轻男性"],
        contact_points=["墙壁支撑", "腰部", "腿部"],
        action_prompt="two same-age adult partners embrace in a shower during gentle standing sex, using the wall for balance with clear faces, hands and full bodies",
        camera="全身",
        intensity="标准",
    ),
    _duo_r18_pose(
        "r18_young_male_gentle_toy_control",
        "双人玩法",
        "温和控制玩具节奏",
        "年轻男性温柔控制器具节奏，女性接受方通过表情和身体反馈决定推进或暂停",
        ["two adults", "same-age adult partners", "young-looking adult male", "remote toy", "gentle toy control", "female receiver", "pleasure response", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性", "女性接受方"],
        contact_points=["手持遥控器", "腿部", "腰部"],
        action_prompt="the smaller younger-looking adult man gently controls a toy while the adult woman guides the pace through visible reactions in a soft consensual scene",
        camera="全身",
        intensity="标准",
    ),
    _duo_r18_pose(
        "r18_young_male_afterglow_embrace",
        "双人玩法",
        "结束后的拥抱与照护",
        "亲密结束后双方依偎、调整呼吸并相互照护，画面安静松弛",
        ["two adults", "same-age adult partners", "young-looking adult male", "afterglow", "embrace", "breathing", "gentle aftercare", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["年轻男性", "女性角色"],
        contact_points=["手臂与肩背", "腰部", "依偎"],
        action_prompt="after gentle intimacy, two same-age adult partners rest in a close embrace, breathing softly and calmly checking on each other, with no pain or extreme elements",
        camera="全身",
        intensity="标准",
        sequence="结束",
    ),
    _duo_r18_pose(
        "sibling_dynamic_internal_dilation_view_r18",
        "单人极限",
        "虚构内部扩张视图",
        "女性接受方进行扩张，画面以艺术化内部视图展示性器内部与子宫位置的虚构结构，男性协助观察",
        ["two adults", "same-age adult partners", "sibling visual dynamic", "internal dilation view", "fictional anatomy", "decorative expander", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["协助方", "女性接受方"],
        contact_points=["手与扩张器", "大腿内侧", "腹部支撑"],
        action_prompt="a same-age adult pair presents a fictional internal dilation view with an artistic cutaway showing internal anatomy and the uterus position, using only decorative visual props and no real-world instructions",
        camera="中景",
        intensity="极限",
    ),
    _duo_r18_pose(
        "sibling_dynamic_fluid_fill_expansion_r18",
        "单人极限",
        "虚构液体填充扩张",
        "女性接受方在扩张状态下呈现虚构液体填充的视觉特效，内部视图显示填充范围与子宫位置",
        ["two adults", "same-age adult partners", "sibling visual dynamic", "fluid fill visual", "internal cutaway", "dilation", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["协助方", "女性接受方"],
        contact_points=["手与扩张器", "腹部", "大腿内侧"],
        action_prompt="the adult woman appears in an artistic fictional fluid-fill dilation visual with a transparent internal cutaway showing the uterus position, no real material recommendation or procedure instructions",
        camera="中景",
        intensity="极限",
    ),
    _duo_r18_pose(
        "sibling_dynamic_solid_fill_expansion_r18",
        "单人极限",
        "虚构固体填充扩张",
        "女性接受方在扩张状态下呈现虚构固体填充效果，画面只使用抽象材质和内部视图",
        ["two adults", "same-age adult partners", "sibling visual dynamic", "solid fill visual", "internal cutaway", "dilation", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["协助方", "女性接受方"],
        contact_points=["手与视觉道具", "腹部", "大腿内侧"],
        action_prompt="the adult woman appears in an artistic fictional solid-fill dilation visual with an abstract internal cutaway and uterus position, using no real-world material recommendation",
        camera="中景",
        intensity="极限",
    ),
    _duo_r18_pose(
        "sibling_dynamic_uterine_hand_contact_r18",
        "单人极限",
        "虚构子宫手部接触",
        "女性接受方在扩张内部视图中呈现手部接触虚拟子宫结构，男性从旁辅助和观察",
        ["two adults", "same-age adult partners", "sibling visual dynamic", "uterine contact visual", "hand contact", "fictional anatomy", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["协助方", "女性接受方"],
        contact_points=["手与内部视觉结构", "腹部", "腿部"],
        action_prompt="an artistic fictional internal-view scene shows a hand touching the uterus structure of the adult woman, with the same-age adult partner assisting and observing without real-world procedural detail",
        camera="中景",
        intensity="极限",
    ),
    _duo_r18_pose(
        "sibling_dynamic_uterine_tool_contact_r18",
        "单人极限",
        "虚构子宫工具接触",
        "女性接受方在内部视图中呈现钝头视觉工具接触虚拟子宫结构，画面强调艺术结构而非现实操作",
        ["two adults", "same-age adult partners", "sibling visual dynamic", "uterine contact visual", "blunt visual tool", "fictional anatomy", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["协助方", "女性接受方"],
        contact_points=["工具与内部视觉结构", "腹部", "腿部"],
        action_prompt="an artistic fictional internal-view scene shows a blunt visual tool touching the uterus structure of the adult woman, with abstract anatomy and no real-world procedural instructions",
        camera="中景",
        intensity="极限",
    ),
    _duo_r18_pose(
        "sibling_dynamic_internal_urination_visual_r18",
        "单人极限",
        "虚构内部排尿视觉",
        "女性接受方在扩张状态下呈现内部排尿行为的虚构视觉特效，液体路径只作为抽象画面元素",
        ["two adults", "same-age adult partners", "sibling visual dynamic", "urination visual", "internal cutaway", "fluid effect", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["协助方", "女性接受方"],
        contact_points=["腹部", "大腿内侧", "视觉液体路径"],
        action_prompt="an artistic fictional internal urination visual effect is shown in an abstract cutaway, with fluid movement as a picture element only and no real-world recommendation or instruction",
        camera="中景",
        intensity="极限",
    ),
    _duo_r18_pose(
        "sibling_dynamic_mirror_internal_dilation_r18",
        "单人极限",
        "镜前内部扩张双视图",
        "女性接受方在镜前扩张，镜面与内部视图同时展示外部姿势和虚拟内部结构",
        ["two adults", "same-age adult partners", "sibling visual dynamic", "mirror", "internal dilation view", "fictional anatomy", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["协助方", "女性接受方"],
        contact_points=["手与扩张器", "镜前站位", "腹部"],
        action_prompt="the adult woman appears before a mirror during artistic fictional internal dilation, with the mirror and cutaway showing external posture and abstract internal anatomy together",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "sibling_dynamic_bathtub_internal_fill_r18",
        "单人极限",
        "浴缸虚构填充视图",
        "女性接受方在浴缸环境中呈现虚构内部填充效果，水面和内部视图形成柔和画面层次",
        ["two adults", "same-age adult partners", "sibling visual dynamic", "bathtub", "fluid fill visual", "internal cutaway", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["协助方", "女性接受方"],
        contact_points=["浴缸支撑", "腹部", "大腿内侧"],
        action_prompt="the adult woman rests in a bathtub during an artistic fictional internal fill visual, with water and an abstract cutaway showing the uterus position without real-world instructions",
        camera="全身",
        intensity="极限",
    ),
    _duo_r18_pose(
        "sibling_dynamic_speculum_internal_touch_r18",
        "单人极限",
        "开放结构内部接触",
        "女性接受方在开放结构下呈现内部接触，使用装饰化扩张视觉件并展示虚拟内部结构",
        ["two adults", "same-age adult partners", "sibling visual dynamic", "decorative speculum", "internal touch visual", "fictional anatomy", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["协助方", "女性接受方"],
        contact_points=["手与视觉扩张件", "腹部", "大腿内侧"],
        action_prompt="the adult woman appears in an artistic open-structure internal-touch visual with a decorative visual expander and abstract internal anatomy, no real-world procedural guidance",
        camera="中景",
        intensity="极限",
    ),
    _duo_r18_pose(
        "sibling_dynamic_aftercare_internal_check_r18",
        "单人结束",
        "扩张内部状态照护",
        "扩张视觉结束后，男性协助女性调整姿势、观察呼吸和检查浅表状态，形成平稳照护收尾",
        ["two adults", "same-age adult partners", "sibling visual dynamic", "aftercare", "internal dilation aftercare", "breathing check", "female receiver", "consensual", "uncensored"],
        orientation="男女",
        role_slots=["照护方", "女性接受方"],
        contact_points=["手与肩背", "腹部支撑", "伴侣照护"],
        action_prompt="after the artistic internal-dilation scene, the same-age adult partner supports the adult woman, checks her breathing and shallow surface condition, and brings the scene to a calm aftercare ending",
        camera="全身",
        intensity="强化",
        sequence="结束",
    ),
]

_SOLO_R18_DEFINITIONS = (
    ("solo_back_knees_up_touch", "单人自慰", "仰卧屈膝自抚", "角色仰卧屈起双膝，一只手沿大腿内侧缓慢自抚，肩部保持放松", ["solo", "1girl", "lying on back", "knees up", "self touch", "masturbation", "fingering", "thighs apart"], ["手部", "大腿内侧"], "全身", "进行中", "强化"),
    ("solo_side_single_leg_touch", "单人自慰", "侧卧抬腿自抚", "角色侧卧并抬起上侧腿，一只手从腿间向内轻触，身体形成柔和弧线", ["solo", "1girl", "side lying", "one leg raised", "bent knee", "self touch", "fingering"], ["手部", "大腿内侧"], "全身", "进行中", "强化"),
    ("solo_seated_open_touch", "单人自慰", "坐姿开腿自抚", "角色坐在地面并向外打开双膝，一只手靠近身体中心缓慢自抚", ["solo", "1girl", "sitting", "spread legs", "self touch", "masturbation", "fingering"], ["手部", "大腿内侧", "臀部与地面"], "全身", "进行中", "强化"),
    ("solo_prone_hip_raise_touch", "单人自慰", "俯卧抬髋回手", "角色俯卧并抬高髋部，一只手向后伸向身体下方进行自抚", ["solo", "1girl", "prone", "hips raised", "rear reach", "self touch", "fingering"], ["手部", "髋部", "胸腹与支撑面"], "全身", "进行中", "强化"),
    ("solo_kneeling_thigh_touch", "单人自慰", "跪姿扶腿自抚", "角色保持跪姿并轻微后仰，双手沿大腿移动至身体中心附近", ["solo", "1girl", "kneeling", "back arch", "hands on thighs", "self touch", "masturbation"], ["手部", "大腿", "膝部与地面"], "全身", "进行中", "强化"),
    ("solo_mirror_standing_touch", "单人自慰", "镜前站立自抚", "角色面对落地镜站立，单手停留在裙摆下方或腰腹内侧进行自抚", ["solo", "1girl", "standing", "mirror", "one hand under skirt", "self touch", "looking at mirror"], ["手部", "腰腹", "双脚与地面"], "全身", "进行中", "强化",),
    ("solo_bathtub_recline_touch", "单人自慰", "浴缸倚躺自抚", "角色倚靠在浴缸边缘，双腿自然弯曲，一只手在水面上方轻触身体", ["solo", "1girl", "bathtub", "reclining", "wet skin", "self touch", "masturbation"], ["背部与浴缸", "手部", "大腿内侧"], "全身", "进行中", "强化"),
    ("solo_chair_recline_touch", "单人自慰", "椅上后仰自抚", "角色后仰坐在椅上，双膝分开，一只手在身体中心缓慢移动", ["solo", "1girl", "on chair", "reclining", "spread knees", "self touch", "masturbation"], ["背部与椅背", "手部", "腿部与椅面"], "中景", "进行中", "强化"),
    ("solo_wall_lean_touch", "单人自慰", "靠墙单膝自抚", "角色背靠墙面并将一侧膝盖抬起，一只手停留在腰腹下方进行自抚", ["solo", "1girl", "against wall", "standing", "one knee raised", "self touch", "fingering"], ["背部与墙面", "手部", "单脚与地面"], "全身", "进行中", "强化"),
    ("solo_wand_vibrator_back", "单人玩具", "仰卧按摩棒刺激", "角色仰卧屈膝，一只手将圆头按摩棒贴近身体中心进行刺激", ["solo", "1girl", "lying on back", "magic wand vibrator", "toy stimulation", "knees up", "uncensored"], ["手部", "按摩棒", "大腿内侧"], "全身", "进行中", "强化"),
    ("solo_wand_vibrator_seated", "单人玩具", "坐姿按摩棒刺激", "角色坐在软垫上并打开双膝，手持按摩棒贴近身体中心进行刺激", ["solo", "1girl", "sitting", "magic wand vibrator", "toy stimulation", "spread legs", "uncensored"], ["手部", "按摩棒", "臀部与软垫"], "中景", "进行中", "强化"),
    ("solo_suction_toy_side", "单人玩具", "侧卧吸吮玩具", "角色侧卧屈膝，一只手将小型吸吮玩具固定在身体中心附近", ["solo", "1girl", "side lying", "suction toy", "clitoral toy", "toy stimulation", "uncensored"], ["手部", "吸吮玩具", "大腿内侧"], "中景", "进行中", "强化"),
    ("solo_insertable_toy_back", "单人玩具", "仰卧插入玩具", "角色仰卧抬膝，一只手缓慢将可插入玩具贴近并插入身体", ["solo", "1girl", "lying on back", "insertable toy", "dildo", "vaginal insertion", "knees up", "uncensored"], ["手部", "玩具", "大腿内侧"], "全身", "进行中", "极限"),
    ("solo_riding_toy_seated", "单人玩具", "坐姿骑乘玩具", "角色跨坐在固定于地面的玩具上方，双膝分开并保持稳定重心", ["solo", "1girl", "straddling toy", "riding toy", "seated", "vaginal insertion", "uncensored"], ["玩具", "大腿内侧", "双脚与地面"], "全身", "进行中", "极限"),
    ("solo_riding_toy_kneeling", "单人玩具", "跪姿骑乘玩具", "角色跪坐在玩具上方并轻微下沉髋部，双手扶住大腿保持平衡", ["solo", "1girl", "kneeling", "riding toy", "straddling toy", "hips lowered", "uncensored"], ["玩具", "膝部与地面", "手部与大腿"], "全身", "进行中", "极限"),
    ("solo_prone_toy_stimulation", "单人玩具", "俯卧玩具刺激", "角色俯卧并抬高髋部，一只手从后方持玩具向身体下方贴近", ["solo", "1girl", "prone", "hips raised", "toy stimulation", "rear reach", "uncensored"], ["手部", "玩具", "髋部"], "全身", "进行中", "强化"),
    ("solo_dual_stimulation_toy", "单人玩具", "双玩具同步刺激", "角色仰卧抬膝，一只手使用按摩棒，另一只手持小型玩具进行同步刺激", ["solo", "1girl", "lying on back", "dual toy stimulation", "magic wand vibrator", "insertable toy", "knees up", "uncensored"], ["双手", "两件玩具", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_remote_toy_standing", "单人玩具", "站立遥控玩具", "角色站立并轻轻交叉双腿，身体因遥控玩具的刺激而出现紧绷姿态", ["solo", "1girl", "standing", "remote control toy", "toy stimulation", "legs crossed", "uncensored"], ["玩具", "大腿内侧", "双脚与地面"], "全身", "进行中", "强化"),

    ("solo_wrist_cuffs_front_kneel", "单人束缚", "前扣跪姿束缚", "角色跪坐并将双手置于身前，佩戴宽松装饰腕扣，姿态安静且重心稳定", ["solo", "1girl", "kneeling", "wrist cuffs in front", "decorative restraints", "static cuffs"], ["手腕扣具", "膝部与软垫"], "全身", "约束", "强化"),
    ("solo_wrist_cuffs_back_standing", "单人束缚", "背腕站立束缚", "角色站立并将双手交叠在背后，佩戴宽松装饰腕扣，肩背线条清楚", ["solo", "1girl", "standing", "wrist cuffs behind back", "decorative restraints", "back arch"], ["手腕扣具", "双脚与地面"], "全身", "约束", "强化"),
    ("solo_ankle_cuffs_side_recline", "单人束缚", "侧卧踝扣束缚", "角色侧卧屈膝，脚踝处佩戴宽松装饰扣具，双手自然支撑上身", ["solo", "1girl", "side lying", "ankle cuffs", "decorative restraints", "bent knees"], ["脚踝扣具", "前臂与支撑面"], "全身", "约束", "强化"),
    ("solo_rope_harness_standing", "单人束缚", "站立绳纹胸衣", "角色站立并展示贴合身体的装饰性绳纹胸衣，绳线保持静态且不拉紧", ["solo", "1girl", "standing", "decorative rope harness", "rope pattern", "static ropes"], ["装饰绳", "腰腹", "双脚与地面"], "全身", "约束", "强化"),
    ("solo_collar_leash_kneel", "单人束缚", "项圈跪姿展示", "角色跪坐展示装饰项圈与短链饰，一只手轻扶链饰并保持安静姿态", ["solo", "1girl", "kneeling", "decorative collar", "leash accessory", "static chain"], ["项圈", "链饰", "手部"], "中景", "约束", "强化"),
    ("solo_suspension_harness", "单人束缚", "软吊带悬浮", "角色由宽软质吊带稳定支撑，身体保持水平悬浮并展示完整轮廓", ["solo", "1girl", "soft suspension harness", "padded support straps", "floating pose", "stable center of gravity"], ["腰部软带", "腿部支撑", "支架"], "全景", "约束", "极限"),
    ("solo_open_shirt_bed", "单人前戏", "床上敞衫自抚", "角色半躺在床边，衬衫敞开但未完全脱下，单手停留在腰腹进行轻触", ["solo", "1girl", "on bed", "open shirt", "half undressed", "self touch", "teasing"], ["背部与床", "手部", "大腿内侧"], "全身", "前戏", "强化"),
    ("solo_stocking_remove", "单人前戏", "褪下长袜", "角色坐在床边并抬起一腿，双手缓慢褪下长袜，身体线条保持清楚", ["solo", "1girl", "on bed", "removing stockings", "one leg raised", "lingerie", "teasing"], ["手部", "长袜", "臀部与床"], "全身", "前戏", "强化"),
    ("solo_back_bra_unclasp", "单人前戏", "背手解扣", "角色背对镜头站立并反手解开内衣扣，肩背与手臂轮廓保持完整", ["solo", "1girl", "standing", "viewing back", "unclasping bra", "lingerie", "teasing"], ["手部", "内衣扣", "双脚与地面"], "全身", "前戏", "强化"),
    ("solo_seated_skirt_lift", "单人前戏", "坐姿提裙", "角色坐在椅上并轻轻提起裙摆，另一只手自然支撑座椅，姿态含蓄", ["solo", "1girl", "sitting", "skirt lift", "one hand holding hem", "teasing", "lingerie"], ["手部", "裙摆", "腿部与椅面"], "中景", "前戏", "强化"),
    ("solo_back_afterglow", "单人结束", "背向余韵", "角色背对镜头侧卧，肩背随呼吸轻微起伏，身体保持柔软放松", ["solo", "1girl", "viewing back", "lying on side", "afterglow", "relaxed body", "soft breathing"], ["肩背与床", "髋部与床"], "全身", "结束", "强化"),
    ("solo_side_curl_afterglow", "单人结束", "侧蜷余韵", "角色侧身蜷缩，双臂抱住膝盖，表情放松并呈现结束后的余韵", ["solo", "1girl", "lying on side", "curled up", "afterglow", "relaxed expression", "soft lighting"], ["手臂与膝盖", "身体与床"], "全身", "结束", "强化"),

    ("solo_side_top_leg_reach", "单人自慰", "侧卧抬腿回手", "角色侧卧并抬高上侧腿，单手越过腿间向后轻触身体中心", ["solo", "1girl", "side lying", "top leg raised", "rear reach", "self touch", "fingering"], ["手部", "大腿内侧", "髋部"], "全身", "进行中", "强化"),
    ("solo_seated_heel_press", "单人自慰", "坐姿足跟压迫", "角色坐在地面并屈膝，以足跟贴近身体下方轻轻压迫并保持平衡", ["solo", "1girl", "sitting", "bent knees", "heel press", "self stimulation", "thighs apart"], ["足跟", "大腿内侧", "臀部与地面"], "全身", "进行中", "强化"),
    ("solo_kneeling_arch_touch", "单人自慰", "跪姿后仰自抚", "角色跪立后仰，一只手沿腹部向下移动，另一只手支撑身后地面", ["solo", "1girl", "kneeling", "back arch", "one hand support", "self touch", "masturbation"], ["手部", "膝部与地面", "手掌与地面"], "全身", "进行中", "强化"),
    ("solo_standing_one_leg_lift_touch", "单人自慰", "站立抬腿自抚", "角色单腿站立并抬高另一侧膝盖，一只手扶腿，另一只手进行自抚", ["solo", "1girl", "standing", "one leg lifted", "self touch", "fingering", "balancing"], ["手部", "抬起的腿部", "单脚与地面"], "全身", "进行中", "强化"),
    ("solo_lying_side_rear_reach", "单人自慰", "侧卧后向触摸", "角色侧卧屈膝，一只手从腰后伸向身体下方，肩部保持自然打开", ["solo", "1girl", "side lying", "rear reach", "bent knees", "self touch", "fingering"], ["手部", "腰背", "大腿内侧"], "全身", "进行中", "强化"),
    ("solo_wall_squat_touch", "单人自慰", "靠墙半蹲自抚", "角色背部贴墙半蹲，双膝分开，单手停留在大腿之间进行自抚", ["solo", "1girl", "against wall", "wall squat", "knees apart", "self touch", "fingering"], ["背部与墙面", "手部", "双脚与地面"], "全身", "进行中", "强化"),
    ("solo_bed_headboard_support", "单人自慰", "床头支撑自抚", "角色仰卧并以双手抓住床头，抬高髋部，一只手改为向下自抚", ["solo", "1girl", "on bed", "headboard support", "hips raised", "self touch", "masturbation"], ["双手与床头", "手部", "髋部与床"], "全身", "进行中", "强化"),
    ("solo_desk_chair_recline", "单人自慰", "书桌椅后仰自抚", "角色后仰坐在书桌椅中，双腿搭在桌沿，一只手在身体中心进行自抚", ["solo", "1girl", "office chair", "desk", "reclining", "legs on desk", "self touch", "masturbation"], ["背部与椅背", "腿部与桌面", "手部"], "全景", "进行中", "强化"),
    ("solo_sofa_arm_arch", "单人自慰", "沙发扶手弓身", "角色以沙发扶手支撑腰背，髋部抬起，单手向身体下方进行自抚", ["solo", "1girl", "sofa arm support", "back arch", "hips raised", "self touch", "fingering"], ["腰背与沙发扶手", "手部", "双脚与地面"], "中景", "进行中", "强化"),
    ("solo_shower_wall_touch", "单人自慰", "淋浴间扶墙自抚", "角色站在淋浴间内以单手扶墙，另一只手在腰腹下方缓慢自抚", ["solo", "1girl", "shower", "wet skin", "against wall", "self touch", "steam"], ["手掌与墙面", "手部", "双脚与地面"], "全身", "进行中", "强化"),
    ("solo_bathtub_edge_sit", "单人自慰", "浴缸边坐自抚", "角色坐在浴缸边缘并向外打开双膝，单手支撑缸沿，另一只手自抚", ["solo", "1girl", "bathtub edge", "sitting", "knees apart", "self touch", "wet skin"], ["手与浴缸边缘", "臀部与浴缸", "手部"], "全身", "进行中", "强化"),
    ("solo_floor_pillow_kneel", "单人自慰", "软垫跪坐自抚", "角色跪坐在厚软垫上，上身轻微后仰，一只手沿大腿内侧向下移动", ["solo", "1girl", "floor cushion", "kneeling", "back arch", "self touch", "masturbation"], ["膝部与软垫", "手部", "大腿内侧"], "全身", "进行中", "强化"),
    ("solo_large_wand_lying", "单人玩具", "仰卧大型按摩棒", "角色仰卧抬膝，双手握住大型圆头按摩棒贴近身体中心进行刺激", ["solo", "1girl", "lying on back", "large wand vibrator", "toy stimulation", "knees up", "uncensored"], ["双手", "大型按摩棒", "大腿内侧"], "中景", "进行中", "强化"),
    ("solo_anal_toy_side", "单人玩具", "侧卧后庭玩具", "角色侧卧屈膝，一只手从身后将小型玩具贴近后庭区域进行刺激", ["solo", "1girl", "side lying", "anal toy", "rear insertion", "toy stimulation", "uncensored"], ["手部", "玩具", "髋部"], "中景", "进行中", "极限"),
    ("solo_anal_toy_kneeling", "单人玩具", "跪姿后庭玩具", "角色跪趴并抬高髋部，一只手从身后使用小型玩具进行刺激", ["solo", "1girl", "kneeling", "hips raised", "anal toy", "rear insertion", "toy stimulation", "uncensored"], ["手部", "玩具", "膝部与支撑面"], "全身", "进行中", "极限"),
    ("solo_double_ended_toy_solo", "单人玩具", "双头玩具自身使用", "角色仰卧屈膝，一只手握住双头玩具的一端并缓慢调整身体角度", ["solo", "1girl", "lying on back", "double ended dildo", "insertable toy", "knees up", "uncensored"], ["双手", "玩具", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_remote_toy_squat", "单人玩具", "蹲姿遥控玩具", "角色保持低蹲姿态，双膝分开，遥控玩具带来的刺激使身体轻微紧绷", ["solo", "1girl", "squatting", "remote control toy", "toy stimulation", "knees apart", "uncensored"], ["玩具", "大腿内侧", "双脚与地面"], "全身", "进行中", "强化"),
    ("solo_mirror_toy_display", "单人玩具", "镜前玩具展示", "角色面对落地镜跪坐，双手持玩具展示于身前，镜中轮廓完整清楚", ["solo", "1girl", "mirror", "kneeling", "holding toy", "toy display", "uncensored"], ["双手", "玩具", "膝部与软垫"], "中景", "前戏", "强化"),
    ("solo_spreader_bar_standing", "单人束缚", "站立扩张杆束缚", "角色站立并保持双腿分开，脚踝连接一根横向扩张杆，双手自然上举", ["solo", "1girl", "standing", "spreader bar", "ankle restraint", "decorative device", "static pose"], ["脚踝与扩张杆", "双脚与地面"], "全身", "约束", "极限"),
    ("solo_spreader_bar_recline", "单人束缚", "仰卧扩张杆束缚", "角色仰卧并屈膝，脚踝由横向扩张杆保持分开，双手放在腹部附近", ["solo", "1girl", "lying on back", "spreader bar", "ankle restraint", "knees bent", "static pose"], ["脚踝与扩张杆", "背部与支撑面"], "全身", "约束", "极限"),
    ("solo_wrist_chain_overhead", "单人束缚", "举腕链饰束缚", "角色跪坐并举高双手，手腕由宽松链饰连接至头顶支架，身体轮廓完整", ["solo", "1girl", "kneeling", "wrists overhead", "decorative chain", "overhead restraint", "static pose"], ["手腕链饰", "膝部与软垫"], "全身", "约束", "强化"),
    ("solo_rope_legging_recline", "单人束缚", "侧卧绳纹腿饰", "角色侧卧屈膝，装饰性绳纹沿大腿固定，双手自然放在身前软垫上", ["solo", "1girl", "side lying", "decorative rope leggings", "thigh ropes", "static pose"], ["装饰绳", "大腿", "前臂与软垫"], "中景", "约束", "强化"),
    ("solo_cage_kneeling", "单人束缚", "笼中跪姿展示", "角色跪坐在开放式装饰笼内，双手扶住膝部并保持安静展示姿态", ["solo", "1girl", "inside decorative cage", "kneeling", "display pose", "static scene"], ["膝部与笼底", "手部与膝部"], "全景", "约束", "强化"),
    ("solo_suspension_side", "单人束缚", "侧向软吊带悬浮", "角色侧向悬浮于宽软吊带之间，身体保持水平，支撑带与轮廓清楚", ["solo", "1girl", "side suspension", "soft harness", "padded straps", "floating pose"], ["腰部软带", "腿部支撑", "支架"], "全景", "约束", "极限"),
    ("solo_shirt_open_kneel", "单人前戏", "跪姿敞衫", "角色跪坐在床上，衬衫敞开露出内衣，双手自然放在大腿上", ["solo", "1girl", "kneeling", "on bed", "open shirt", "lingerie visible", "teasing"], ["膝部与床", "手部与大腿"], "中景", "前戏", "强化"),
    ("solo_dress_shoulder_slip", "单人前戏", "裙装滑肩", "角色站立并将裙装肩带轻轻滑落一侧，双手自然垂下，姿态含蓄", ["solo", "1girl", "standing", "dress shoulder slip", "one strap down", "teasing", "lingerie visible"], ["衣料与肩部", "双脚与地面"], "全身", "前戏", "强化"),
    ("solo_bra_front_open", "单人前戏", "前开内衣展示", "角色跪坐在软垫上，双手将前开内衣轻轻拉至两侧，身体保持自然舒展", ["solo", "1girl", "kneeling", "front clasp bra", "open bra", "lingerie", "teasing"], ["双手", "内衣", "膝部与软垫"], "中景", "前戏", "极限"),
    ("solo_panties_side_pull", "单人前戏", "侧拉内裤", "角色侧卧屈膝，一只手将内裤侧面轻轻拉开，另一只手放在腰腹上", ["solo", "1girl", "side lying", "panties aside", "lingerie", "teasing", "one hand on hip"], ["手部", "内裤", "髋部"], "中景", "前戏", "极限"),
    ("solo_latex_zip_partial", "单人前戏", "部分拉开乳胶拉链", "角色跪坐于镜前，将乳胶衣正面拉链下拉一段，双手保持自然位置", ["solo", "1girl", "kneeling", "latex outfit", "zipper partially open", "mirror", "teasing"], ["拉链", "双手", "膝部与软垫"], "中景", "前戏", "极限"),
    ("solo_kneeling_tremble_afterglow", "单人结束", "跪姿轻颤余韵", "角色跪坐并微微前倾，双肩轻颤，表情放松并呈现结束后的余韵", ["solo", "1girl", "kneeling", "trembling", "afterglow", "relaxed expression", "soft breathing"], ["膝部与软垫", "手部与大腿"], "中景", "结束", "强化"),

    ("solo_speculum_back_supported", "单人玩具", "仰卧支撑鸭嘴器", "角色仰卧抬膝，由软垫支撑腿部，闭合式鸭嘴器以装饰道具造型贴近身体", ["solo", "1girl", "lying on back", "knees up", "speculum", "open speculum", "decorative device", "uncensored"], ["手部", "鸭嘴器", "腿部支撑"], "中景", "进行中", "极限"),
    ("solo_speculum_side_recline", "单人玩具", "侧卧鸭嘴器", "角色侧卧屈膝，一只手稳定持有装饰化鸭嘴器并保持身体轮廓清楚", ["solo", "1girl", "side lying", "speculum", "decorative device", "one hand holding device", "uncensored"], ["手部", "鸭嘴器", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_speculum_seated_open", "单人玩具", "坐姿开腿鸭嘴器", "角色坐在软垫上打开双膝，手持装饰化鸭嘴器展示于身体前方", ["solo", "1girl", "sitting", "spread legs", "speculum", "open device", "decorative device", "uncensored"], ["双手", "鸭嘴器", "臀部与软垫"], "中景", "进行中", "极限"),
    ("solo_speculum_kneeling_open", "单人玩具", "跪姿鸭嘴器", "角色跪坐并轻微后仰，一只手持装饰化鸭嘴器贴近身体中心", ["solo", "1girl", "kneeling", "back arch", "speculum", "open device", "decorative device", "uncensored"], ["手部", "鸭嘴器", "膝部与软垫"], "中景", "进行中", "极限"),
    ("solo_speculum_mirror_observe", "单人玩具", "镜前鸭嘴器观察", "角色面对落地镜跪坐，双手持装饰化鸭嘴器，镜中倒影完整清楚", ["solo", "1girl", "mirror", "kneeling", "speculum", "holding device", "decorative device", "uncensored"], ["双手", "鸭嘴器", "膝部与软垫"], "中景", "进行中", "极限"),
    ("solo_speculum_self_hold", "单人玩具", "自行持握鸭嘴器", "角色仰卧屈膝，双手稳定握住装饰化鸭嘴器并保持身体自然打开", ["solo", "1girl", "lying on back", "speculum", "self holding device", "knees up", "decorative device", "uncensored"], ["双手", "鸭嘴器", "大腿内侧"], "特写", "进行中", "极限"),
    ("solo_speculum_frame_support", "单人玩具", "仰卧鸭嘴器辅助", "角色仰卧抬高双膝，单手稳定张开的鸭嘴器并展示器具位置，不出现固定支架或机械结构", ["solo", "1girl", "lying on back", "knees up", "speculum", "hand-held device", "open device", "uncensored"], ["单手", "鸭嘴器", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_speculum_close_view", "单人玩具", "鸭嘴器局部特写", "镜头聚焦角色双手与装饰化鸭嘴器，身体下半部以艺术化方式完整构图", ["solo", "1girl", "close-up", "speculum", "open device", "hands holding device", "exaggerated anatomy", "uncensored"], ["双手", "鸭嘴器"], "特写", "进行中", "极限"),
    ("solo_object_insertion_back", "单人极限", "仰卧异物插入", "角色仰卧抬膝，一只手将小型物件缓慢贴近并纳入身体", ["solo", "1girl", "lying on back", "object insertion", "object", "knees up", "uncensored"], ["手部", "插入物件", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_object_insertion_side", "单人极限", "侧卧异物插入", "角色侧卧屈膝，一只手从腿间持小型物件进行插入展示", ["solo", "1girl", "side lying", "object insertion", "object", "one hand holding object", "uncensored"], ["手部", "插入物件", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_object_insertion_seated", "单人极限", "坐姿异物插入", "角色坐在软垫上打开双膝，双手持小型物件贴近身体中心", ["solo", "1girl", "sitting", "spread legs", "object insertion", "object", "uncensored"], ["双手", "插入物件", "臀部与软垫"], "中景", "进行中", "极限"),
    ("solo_object_insertion_kneeling", "单人极限", "跪姿异物插入", "角色跪坐后仰，一只手支撑身后，另一只手持小型物件进行插入", ["solo", "1girl", "kneeling", "object insertion", "object", "back arch", "uncensored"], ["手部", "插入物件", "膝部与软垫"], "中景", "进行中", "极限"),
    ("solo_object_insertion_standing", "单人极限", "站立异物插入", "角色单腿站立并抬高另一侧膝盖，一只手持小型物件贴近身体", ["solo", "1girl", "standing", "one leg lifted", "object insertion", "object", "uncensored"], ["手部", "插入物件", "单脚与地面"], "全身", "进行中", "极限"),
    ("solo_object_partial_insertion", "单人极限", "半插入异物", "角色仰卧抬膝，双手持中型物件并展示部分纳入的状态", ["solo", "1girl", "lying on back", "partial insertion", "medium object", "object", "knees up", "uncensored"], ["双手", "插入物件", "大腿内侧"], "特写", "进行中", "极限"),
    ("solo_object_large_insertion", "单人极限", "大型异物插入", "角色仰卧抬膝，双手稳定持大型物件并保持身体姿态舒展", ["solo", "1girl", "lying on back", "large object insertion", "oversized toy", "knees up", "uncensored"], ["双手", "大型物件", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_object_multi_insertion", "单人极限", "多物件同步插入", "角色仰卧抬膝，双手分别持两件柔性物件进行同步插入展示", ["solo", "1girl", "lying on back", "multiple object insertion", "two objects", "knees up", "uncensored"], ["双手", "两件物件", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_prolapse_back_supported", "单人极限", "仰卧支撑宫脱", "角色仰卧抬膝并由软垫支撑，身体中心呈艺术化夸张生理状态", ["solo", "1girl", "lying on back", "knees up", "uterine prolapse", "exaggerated anatomy", "uncensored"], ["手部", "大腿内侧", "腿部支撑"], "中景", "进行中", "极限"),
    ("solo_prolapse_side_recline", "单人极限", "侧卧宫脱", "角色侧卧屈膝，一只手扶住大腿，身体中心以艺术化夸张生理状态呈现", ["solo", "1girl", "side lying", "prolapse", "exaggerated anatomy", "uncensored"], ["手部", "大腿内侧", "髋部"], "中景", "进行中", "极限"),
    ("solo_prolapse_seated_open", "单人极限", "坐姿开腿宫脱", "角色坐在软垫上打开双膝，身体中心以艺术化夸张生理状态呈现", ["solo", "1girl", "sitting", "spread legs", "prolapse", "exaggerated anatomy", "uncensored"], ["双手", "大腿内侧", "臀部与软垫"], "中景", "进行中", "极限"),
    ("solo_prolapse_kneeling_open", "单人极限", "跪姿开腿宫脱", "角色跪坐并向外打开双膝，身体中心以艺术化夸张生理状态呈现", ["solo", "1girl", "kneeling", "spread legs", "prolapse", "exaggerated anatomy", "uncensored"], ["膝部与软垫", "手部", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_prolapse_standing_open", "单人极限", "站立开腿宫脱", "角色站立并向外打开双腿，一只手扶住大腿，身体中心以艺术化状态呈现", ["solo", "1girl", "standing", "legs apart", "prolapse", "exaggerated anatomy", "uncensored"], ["手部与大腿", "双脚与地面"], "全身", "进行中", "极限"),
    ("solo_prolapse_speculum", "单人玩具", "鸭嘴器宫脱", "角色仰卧抬膝，双手持装饰化鸭嘴器，身体中心以艺术化夸张生理状态呈现", ["solo", "1girl", "lying on back", "speculum", "prolapse", "exaggerated anatomy", "uncensored"], ["双手", "鸭嘴器", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_prolapse_object_insertion", "单人极限", "异物宫脱双重展示", "角色仰卧抬膝，双手持中型物件，身体中心以艺术化夸张生理状态呈现", ["solo", "1girl", "lying on back", "object insertion", "prolapse", "exaggerated anatomy", "uncensored"], ["双手", "插入物件", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_prolapse_afterglow", "单人结束", "宫脱余韵", "角色侧卧蜷缩并轻轻按住腹部，身体中心以艺术化夸张生理状态收束", ["solo", "1girl", "side lying", "curled up", "prolapse afterglow", "exaggerated anatomy", "relaxed expression", "uncensored"], ["手部与腹部", "身体与床"], "中景", "结束", "极限"),
    ("solo_spread_pussy_front", "单人展示", "仰躺掰穴正面", "角色仰躺并抬高双腿，双手向两侧分开外阴，正面完整展示清晰器官结构", ["solo", "1girl", "lying on back", "spread pussy", "labia spread", "legs apart", "uncensored"], ["双手", "大腿内侧", "外阴"], "中景", "进行中", "强化"),
    ("solo_spread_pussy_sitting", "单人展示", "坐姿掰穴", "角色坐在软垫上分开双膝，双手向下分开外阴并保持稳定正面构图", ["solo", "1girl", "sitting", "spread pussy", "two hands spreading", "legs apart", "uncensored"], ["双手", "大腿内侧", "坐垫"], "中景", "进行中", "强化"),
    ("solo_spread_pussy_side", "单人展示", "侧卧掰穴", "角色侧卧抬起上侧腿，用手指向两侧分开外阴并保持侧向器官可见", ["solo", "1girl", "side lying", "one leg raised", "spread pussy", "fingers spreading", "uncensored"], ["手指", "抬起的腿部", "外阴"], "中景", "进行中", "强化"),
    ("solo_spread_pussy_kneeling", "单人展示", "跪姿掰穴", "角色跪坐并向外分开膝盖，一只手支撑身体、另一只手分开外阴", ["solo", "1girl", "kneeling", "spread pussy", "knees apart", "one hand spreading", "uncensored"], ["单手", "膝盖与支撑面", "外阴"], "中景", "进行中", "强化"),
    ("solo_spread_pussy_mirror", "单人展示", "镜前掰穴", "角色站立抬腿并面对落地镜，一只手分开外阴，镜中同步呈现正面细节", ["solo", "1girl", "mirror", "standing", "one leg raised", "spread pussy", "looking at mirror", "uncensored"], ["单手", "抬起的腿部", "镜面"], "全身", "进行中", "强化"),
    ("solo_two_hand_spread", "单人展示", "双手完全掰开", "角色仰躺抬高髋部，双手同时向两侧完全分开外阴并突出清晰轮廓", ["solo", "1girl", "lying on back", "two hands spreading", "labia spread", "knees up", "uncensored"], ["双手", "外阴", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_vaginal_spread_close", "单人展示", "掰穴局部特写", "局部特写聚焦角色双手向外分开的外阴，完整呈现器官轮廓与手指位置", ["solo", "1girl", "close-up", "spread pussy", "labia spread", "detailed anatomy", "uncensored"], ["双手", "外阴"], "特写", "进行中", "极限"),
    ("solo_speculum_front_open", "单人玩具", "正面鸭嘴器扩张", "角色仰躺抬高双膝，鸭嘴器在正面保持完全张开，器官与器械位置清晰", ["solo", "1girl", "lying on back", "speculum", "open device", "vaginal opening", "front view", "uncensored"], ["鸭嘴器", "大腿内侧", "外阴"], "中景", "进行中", "极限"),
    ("solo_speculum_side_open", "单人玩具", "侧位鸭嘴器扩张", "角色侧卧抬起上侧腿，一只手稳定张开的鸭嘴器并展示侧向扩张结构", ["solo", "1girl", "side lying", "speculum", "open device", "side view", "one hand holding device", "uncensored"], ["单手", "鸭嘴器", "抬起的腿部"], "中景", "进行中", "极限"),
    ("solo_speculum_frame_stand", "单人玩具", "站立鸭嘴器扩张", "角色站立抬起一条腿，单手稳定张开的鸭嘴器并面向镜头，不出现固定支架或机械结构", ["solo", "1girl", "standing", "one leg lifted", "speculum", "hand-held device", "open device", "uncensored"], ["单手", "鸭嘴器", "抬起的腿部"], "全身", "进行中", "极限"),
    ("solo_dilation_stage_one", "单人玩具", "扩张初段", "角色仰躺抬高双膝，使用渐扩器具进入初段并清晰展示器具与外阴位置", ["solo", "1girl", "lying on back", "dilation", "vaginal dilation", "graduated dilator", "knees up", "uncensored"], ["单手", "渐扩器具", "外阴"], "中景", "进行中", "极限"),
    ("solo_dilation_afterglow", "单人结束", "扩张余韵", "角色侧卧并放松双腿，一只手按在下腹，保留扩张后的器官状态与余韵表情", ["solo", "1girl", "side lying", "afterglow", "vaginal dilation afterglow", "relaxed body", "one hand on abdomen", "uncensored"], ["手部与腹部", "身体与床"], "中景", "结束", "极限"),
    ("solo_dilation_stage_two_braced", "单人玩具", "二期支撑扩张", "角色单腿踩在软凳上并扶住大腿，身体轻微后倾，使用更大的渐扩器具进入第二段，另一只手稳定器具位置", ["solo", "1girl", "standing on one leg", "foot on stool", "vaginal dilation", "large graduated dilator", "dilation stage two", "uncensored"], ["单手", "大型渐扩器具", "外阴", "支撑腿"], "中景", "进行中", "极限"),
    ("solo_dilation_stage_three_supine", "单人极限", "三期仰卧扩张", "角色仰卧并将双膝抱向身体两侧，使用更大型渐扩器具完成第三阶段深入扩张，腰部离开软垫并保持紧绷", ["solo", "1girl", "lying on back", "knees wide", "vaginal dilation", "maximum graduated dilator", "dilation stage three", "hips lifted", "uncensored"], ["双手", "最大型渐扩器具", "外阴", "髋部"], "中景", "进行中", "极限"),
    ("solo_dilation_hold_timer_side", "单人束缚", "侧卧扩张保持", "角色侧卧抬腿并用一只手维持渐扩器具的位置，旁边计时器显示保持阶段，腰腹因持续受力轻颤", ["solo", "1girl", "side lying", "dilation hold", "graduated dilator", "timer", "sustained stretch", "uncensored"], ["单手", "渐扩器具", "抬起的腿部", "计时器"], "中景", "进行中", "极限"),
    ("solo_dilation_release_aftercare", "单人结束", "缓慢退出照护", "角色仰卧放松双腿，单手缓慢退出大型渐扩器具，另一只手按住下腹，表情疲惫但平稳", ["solo", "1girl", "lying on back", "slow removal", "large graduated dilator", "aftercare", "one hand on abdomen", "uncensored"], ["单手与器具", "手部与腹部", "大腿内侧"], "中景", "结束", "极限"),
    ("solo_speculum_to_dilation_sequence", "单人玩具", "窥器转连续扩张", "角色仰卧抬膝，张开的窥器保持在身体一侧，另一只手持渐扩器具贴近，表现从观察过渡到扩张的连续动作", ["solo", "1girl", "lying on back", "open speculum", "graduated dilator", "guided transition", "knees up", "uncensored"], ["单手与窥器", "单手与渐扩器具", "外阴"], "中景", "进行中", "极限"),
    ("solo_object_ladder_sequence", "单人极限", "尺寸阶梯序列", "角色跪坐在镜前，三件由小到大的柔性物件排成一列，当前物件已纳入并准备更换下一尺寸", ["solo", "1girl", "kneeling", "mirror", "object ladder", "graduated objects", "three flexible objects", "uncensored"], ["手与插入物件", "外阴", "膝部与软垫"], "中景", "进行中", "极限"),
    ("solo_fisting_partial_hold", "单人极限", "单人部分拳交保持", "角色仰卧抬高髋部并将一只手部分纳入身体，手腕保持稳定，另一只手抓住膝弯控制姿态", ["solo", "1girl", "lying on back", "fisting", "partial insertion", "hand insertion", "hips raised", "knees up", "uncensored"], ["手与身体中心", "手与膝弯", "髋部"], "中景", "进行中", "极限"),
    ("solo_labia_clamp_spread", "单人玩具", "阴唇夹固定张开", "角色仰卧抬腿，使用两只软垫阴唇夹固定外阴两侧并由链条维持轻微张力，双手放在大腿上展示固定状态", ["solo", "1girl", "lying on back", "labia clamps", "padded clamps", "spreader chain", "sustained spread", "uncensored"], ["阴唇夹", "连接链条", "大腿内侧"], "中景", "进行中", "极限"),
    ("solo_clamp_chain_dilation_combo", "单人玩具", "夹持链饰同步扩张", "角色仰卧抬膝，乳夹链条连接至腹前配重，另一只手维持渐扩器具，胸腹和下身同时保持受力", ["solo", "1girl", "lying on back", "nipple clamps", "weighted chain", "large graduated dilator", "combined tension", "uncensored"], ["乳夹链条", "渐扩器具", "外阴", "腹部配重"], "中景", "进行中", "极限"),
    ("solo_body_jewelry_weighted_tension", "单人束缚", "身体饰品负重拉伸", "角色跪坐挺直上身，既有胸饰和脐环通过链条连接低垂配重，皮肤被明显向下牵引，双手放在大腿保持稳定", ["solo", "1girl", "kneeling", "body jewelry", "piercing jewelry", "weighted chain", "skin tension", "uncensored"], ["胸饰", "脐环", "悬重链条"], "中景", "进行中", "极限"),
    ("solo_intimate_jewelry_chain_tension", "单人束缚", "私密饰品链条拉伸", "角色坐在地面打开双膝，一只手向侧上方拉住连接私密穿刺饰品的链条，身体因紧张后仰，另一只手支撑身后", ["solo", "1girl", "sitting", "knees apart", "intimate jewelry", "piercing jewelry", "chain traction", "one hand support", "uncensored"], ["手与链条", "私密饰品", "手掌与地面"], "中景", "进行中", "极限"),
    ("solo_predicament_dilation_hold", "单人束缚", "扩张限制保持", "角色仰卧并由宽松软带分开双膝，双手放在计时器旁保持渐扩器具的位置，需要持续维持且不能自行放松", ["solo", "1girl", "lying on back", "soft leg restraints", "dilation hold", "graduated dilator", "timer", "predicament", "uncensored"], ["软质腿带", "手与渐扩器具", "计时器"], "中景", "进行中", "极限"),

    ("solo_ice_cube_collarbone_touch", "单人前戏", "冰块锁骨自触", "角色倚躺并手持冰块沿锁骨缓慢滑动，另一只手轻放在腰腹，姿态放松", ["solo", "1girl", "ice cube", "temperature play", "collarbone", "self touch", "teasing", "uncensored"], ["手持冰块", "锁骨", "手部与腰腹"], "中景", "前戏", "强化"),
    ("solo_ice_cube_thigh_touch", "单人前戏", "冰块大腿自触", "角色坐在地面并抬起一侧膝盖，手持冰块沿大腿外侧缓慢移动", ["solo", "1girl", "ice cube", "temperature play", "outer thigh", "one knee raised", "self touch", "uncensored"], ["手持冰块", "大腿外侧", "抬起的腿部"], "中景", "前戏", "强化"),
    ("solo_feather_waist_self_tease", "单人前戏", "羽毛腰侧自撩", "角色侧卧并让腰线舒展，手持柔软羽毛沿腰侧和腹部缓慢轻扫", ["solo", "1girl", "feather", "waist", "self tease", "side lying", "sensation play", "uncensored"], ["手持羽毛", "腰侧", "腹部"], "中景", "前戏", "强化"),
    ("solo_low_temp_wax_collarbone", "单人前戏", "锁骨低温滴蜡", "角色仰卧并露出锁骨，手持未点燃的低温按摩蜡烛，少量温热蜡滴落在皮肤", ["solo", "1girl", "low temperature massage candle", "wax play", "collarbone", "warm wax drops", "uncensored"], ["手持蜡烛", "蜡滴", "锁骨"], "中景", "前戏", "强化"),
    ("solo_silk_ribbon_wrist_kneel", "单人束缚", "跪姿软缎腕饰", "角色跪坐在软垫上，双手在身前由宽软缎带松散环绕一圈，缎带完全松垂", ["solo", "1girl", "kneeling", "wide silk ribbon", "loose wrist wrap", "decorative restraint", "static pose"], ["软缎带", "手腕", "膝部与软垫"], "全身", "约束", "强化"),
    ("solo_blindfold_self_touch", "单人前戏", "眼罩自抚", "角色坐在地面并佩戴柔软眼罩，一只手沿腹部缓慢移动，另一只手支撑身后", ["solo", "1girl", "soft blindfold", "seated", "self touch", "abdomen", "sensory focus", "uncensored"], ["眼罩", "手部与腹部", "手掌与地面"], "中景", "前戏", "强化"),
    ("solo_remote_toy_seated", "单人玩具", "坐姿遥控玩具", "角色坐在软垫上并轻轻并拢双膝，一只手抓紧大腿，遥控玩具刺激使呼吸变得急促", ["solo", "1girl", "sitting", "remote control toy", "toy stimulation", "knees together", "one hand on thigh", "uncensored"], ["遥控玩具", "大腿内侧", "臀部与软垫"], "中景", "进行中", "强化"),
    ("solo_ice_cube_bathtub", "单人前戏", "浴缸冰块滑触", "角色倚躺在浴缸中，手持冰块沿肩颈与锁骨缓慢滑动，水面和身体轮廓清楚", ["solo", "1girl", "bathtub", "ice cube", "temperature play", "wet skin", "self touch", "uncensored"], ["手持冰块", "肩颈", "背部与浴缸"], "中景", "进行中", "强化"),
    ("solo_mirror_leather_glove_touch", "单人前戏", "镜前皮手套自抚", "角色站在落地镜前并佩戴柔软黑色皮手套，一只手沿锁骨和腰侧缓慢移动", ["solo", "1girl", "mirror", "leather gloves", "self touch", "collarbone", "waist", "uncensored"], ["皮手套", "锁骨", "腰侧", "镜面"], "中景", "前戏", "强化"),
    ("solo_earplug_sensory_seated", "单人束缚", "耳塞感官静坐", "角色坐在软垫上佩戴柔软耳塞并轻闭双眼，双手交叠放在大腿，安静感受环境", ["solo", "1girl", "earplugs", "sensory focus", "seated", "eyes closed", "static pose", "uncensored"], ["耳塞", "双手与大腿", "臀部与软垫"], "中景", "约束", "强化"),
    ("solo_clothespin_thigh_arrangement", "单人束缚", "大腿衣夹排列", "角色坐在软垫上抬起一腿，双手将几只木质衣夹整齐排列在大腿外侧", ["solo", "1girl", "wooden clothespins", "outer thigh", "sensation play", "seated", "arranged", "uncensored"], ["双手", "木质衣夹", "大腿外侧"], "中景", "进行中", "强化"),
    ("solo_warm_towel_aftercare", "单人结束", "暖巾照护余韵", "角色裹着温热软巾坐好，双手捧住巾角，肩颈放松并呈现安静的结束状态", ["solo", "1girl", "warm towel", "aftercare", "seated", "relaxed breathing", "afterglow", "uncensored"], ["暖巾与肩部", "双手", "臀部与软垫"], "中景", "结束", "强化"),
)

POSE_PRESETS.extend(
    _solo_r18_pose(
        preset_id,
        category,
        label,
        translation,
        tags,
        contact_points,
        camera=camera,
        sequence=sequence,
        intensity=intensity,
    )
    for (
        preset_id,
        category,
        label,
        translation,
        tags,
        contact_points,
        camera,
        sequence,
        intensity,
    ) in _SOLO_R18_DEFINITIONS
)
SOLO_R18_POSE_IDS = tuple(
    str(item["id"])
    for item in POSE_PRESETS
    if str(item["id"]).startswith("solo_") and item.get("rating") == "R18"
)

_GROUP_PROMPT_SUFFIX = (
    "single continuous scene with anime rendering, every character has exactly one head, two arms, and two legs, "
    "fully independent anime characters with opaque natural skin and clothing, "
    "visible expressive faces, separate opaque bodies with clear silhouettes, "
    "no mannequin, no transparent body, no plastic suit, no transparent overlays, "
    "no duplicate limbs, no extra limbs, no fused bodies"
)


def _normalize_pose_presets() -> None:
    """Fill v2 fields for legacy poses and enforce multi-person safeguards."""
    solo_ids = {"lying_back", "lying_side", "kneeling", "standing"}
    legacy_role_slots = {
        "threesome_2f1m": ["女A", "女B", "男A"],
        "threesome_2m1f": ["男A", "男B", "女A"],
        "threesome_oral": ["女A", "女B", "男A"],
        "dp_doggy": ["女A", "男A", "男B"],
        "dp_missionary": ["女A", "男A", "男B"],
        "spitroast_standing": ["女A", "男A", "男B"],
        "orgy_four": ["女A", "女B", "男A", "男B"],
        "train_line": ["女A", "男A", "男B", "男C"],
        "lesbian_orgy": ["女A", "女B", "女C", "女D"],
        "dp_spoon": ["女A", "男A", "男B"],
        "dp_standing": ["女A", "男A", "男B"],
        "mmf_double_vaginal": ["女A", "男A", "男B"],
        "ffm_face_and_cowgirl": ["女A", "女B", "男A"],
        "mmf_cowgirl_anal": ["女A", "男A", "男B"],
        "ffm_spitroast": ["女A", "女B", "男A"],
    }
    for preset in POSE_PRESETS:
        text = " ".join(str(tag) for tag in preset.get("tags") or []).lower()
        preset.setdefault("schema_version", 2)
        preset.setdefault("source", "builtin")
        preset.setdefault("rating", "R18" if content_filter.is_nsfw(text) else "普通")
        preset.setdefault("intensity", "强化" if preset["rating"] == "R18" else "标准")
        preset.setdefault("compatibility", [])
        preset.setdefault("has_image", bool(preset.get("image")))
        if not preset.get("people"):
            category = str(preset.get("category") or "")
            group = category in ("3P", "群交") or any(
                marker in text for marker in ("group sex", "threesome", "orgy", "gangbang")
            )
            preset["people"] = "多人" if group else ("单人" if preset.get("id") in solo_ids or "solo" in text else "双人")
        if not preset.get("orientation"):
            category = str(preset.get("category") or "")
            if preset["people"] == "单人":
                preset["orientation"] = "单人"
            elif category == "女同" or "lesbian" in text:
                preset["orientation"] = "女女"
            elif preset["people"] == "多人":
                preset["orientation"] = "多人"
            else:
                preset["orientation"] = "男女"
        if preset.get("id") in legacy_role_slots:
            preset["role_slots"] = legacy_role_slots[str(preset["id"])]
        elif not preset.get("role_slots"):
            preset["role_slots"] = ["主体"] if preset["people"] == "单人" else ["角色A", "角色B"]
        preset.setdefault("body_separation", preset["people"] == "多人")
        (
            preset["people_count"],
            preset["people_prompt"],
        ) = pose_people_metadata(
            str(preset["people"]),
            list(preset.get("role_slots") or []),
        )
        preset.setdefault("contact_points", [])
        preset.setdefault("camera", "全身")
        preset.setdefault("sequence", "进行中")
        if preset.get("body_separation") and preset.get("draw_prompt"):
            prompt_text = str(preset["draw_prompt"]).rstrip(" ,")
            if _GROUP_PROMPT_SUFFIX.lower() not in prompt_text.lower():
                preset["draw_prompt"] = f"{prompt_text}, {_GROUP_PROMPT_SUFFIX}"


_normalize_pose_presets()


def _parse_json(text: str) -> dict:
    """从模型输出中提取 JSON 对象，兼容代码围栏、前后说明与截断。"""
    return extract_json_payload(text, "object")


def normalize_split_groups(raw_groups: object) -> list[dict]:
    """清洗 LLM 返回的分组结构，去掉空组/非法项并保持稳定顺序。"""
    if not isinstance(raw_groups, list):
        return []
    groups: list[dict] = []
    seen_labels: set[str] = set()
    for raw in raw_groups:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "其他").strip() or "其他"
        items_raw = raw.get("items")
        if not isinstance(items_raw, list):
            items: list[str] = []
        else:
            items = [str(item).strip() for item in items_raw if str(item).strip()]
        key = label.lower()
        if key in seen_labels:
            continue
        if not items:
            continue
        seen_labels.add(key)
        groups.append({"label": label, "items": items})
    return groups


def _complete_role_groups(groups: list[dict], tags: list[str]) -> list[dict]:
    """补齐 LLM 分组：确保角色组存在、无标签丢失，并做简单错位兜底。"""
    result = [dict(group) for group in groups]
    assigned: set[str] = set()
    for group in result:
        for item in group["items"]:
            assigned.add(str(item).strip().lower())

    def group_by_label(label_keyword: str):
        return next((group for group in result if label_keyword in str(group["label"]).lower()), None)

    has_role = any(
        any(keyword in str(group["label"]).lower() for keyword in ("男", "女", "角色", "人物", "character"))
        for group in result
    )
    if not has_role:
        appearance_markers = (
            "girl", "boy", "woman", "man", "solo", "hair", "eyes", "eyebrow", "eyelash",
            "blush", "skin", "horn", "tail", "wing", "ear", "mole", "scar", "freckle",
            "breast", "chest", "figure", "legs", "thigh", "marking",
        )
        candidates: list[str] = []
        for group in result:
            label = str(group["label"]).lower()
            if not any(keyword in label for keyword in ("动作", "服装", "场景", "action", "clothing", "background")):
                kept: list[str] = []
                for item in group["items"]:
                    lowered = item.lower()
                    if any(marker in lowered for marker in appearance_markers):
                        candidates.append(item)
                        assigned.discard(lowered)
                    else:
                        kept.append(item)
                group["items"] = kept
        if candidates:
            text = ", ".join(candidates).lower()
            if any(word in text for word in ("1boy", " boy", "male", " man")) and not any(
                word in text for word in ("1girl", " girl", "female", " woman")
            ):
                role_label = "男A"
            elif any(word in text for word in ("1girl", " girl", "female", " woman")):
                role_label = "女A"
            else:
                role_label = "人物A"
            result.append({"label": role_label, "items": candidates})
            assigned.update(item.lower() for item in candidates)

    missing = [tag for tag in tags if tag.strip().lower() not in assigned]
    if missing:
        other = group_by_label("其他")
        if other is None:
            other = group_by_label("other")
        if other is None:
            other = {"label": "其他", "items": []}
            result.append(other)
        existing = {str(item).strip().lower() for item in other["items"]}
        for tag in missing:
            key = tag.strip().lower()
            if key not in existing:
                other["items"].append(tag)
                existing.add(key)
    return normalize_split_groups(result)


def fallback_role_groups(tags: list[str]) -> list[dict]:
    """LLM 分组完全失败时按通用类别兜底，保证拆分操作仍可用。"""
    mapping: list[tuple[str, tuple[str, ...]]] = [
        ("人物", ("1girl", "1boy", "solo", "multiple girls", "multiple boys", "character", "male", "female")),
        ("动作", ("posing", "looking", "sex", "sitting", "standing", "kneeling", "holding", "kissing")),
        ("服装", ("uniform", "dress", "outfit", "jacket", "skirt", "stockings", "gloves", "shoes", "clothes")),
        ("场景", ("background", "indoors", "outdoors", "room", "beach", "bed", "night", "classroom")),
        ("画风", ("masterpiece", "best quality", "anime", "artwork", "coloring", "detailed")),
    ]
    groups = [{"label": label, "items": []} for label, _ in mapping]
    groups.append({"label": "其他", "items": []})
    for tag in tags:
        lowered = tag.lower()
        bucket = len(mapping)
        for index, (_, keywords) in enumerate(mapping):
            if any(keyword in lowered for keyword in keywords):
                bucket = index
                break
        groups[bucket]["items"].append(tag)
    return [group for group in groups if group["items"]]


def refine_prompt(description: str, current_prompt: str, requirements: str, pose_tags: list[str]) -> dict:
    """单轮细化：结合图片描述、现有提示词、预设体位与用户要求重新生成并角色感知拆分。"""
    pose_line = "，".join(pose_tags) if pose_tags else "无"
    prompt = (
        "根据图片描述、现有提示词和用户要求，生成一份完整英文 Danbooru 风格提示词，并做角色感知拆分。\n"
        f"图片描述：{description}\n"
        f"现有提示词：{current_prompt}\n"
        f"预设体位标签：{pose_line}\n"
        f"用户要求：{requirements or '无'}\n"
        "要求：\n"
        "1. 输出完整英文提示词，保留/补充 R18 与体位标签，不要省略。\n"
        "2. 多角色时按 男A、男B、女A 等分别归组；单角色用 角色 或直接归入 人物。\n"
        '3. 输出 JSON 格式：{"prompt":"...","groups":[{"label":"男A","items":["tag",...]},{"label":"动作","items":[...]},{"label":"服装","items":[...]},{"label":"场景","items":[...]},{"label":"画风","items":[...]},{"label":"质量","items":[...]}]}。\n'
        "只输出 JSON，不要输出解释。"
    )
    data: dict | None = None
    last_raw = ""
    result = ""
    for _ in range(3):
        try:
            result = llm.chat(
                [{"role": "system", "content": "你是提示词优化与拆分助手，只输出 JSON。"}, {"role": "user", "content": prompt}],
                max_tokens=1600,
                temperature=0.3,
                think=False,
            )
            data = _parse_json(result)
            if isinstance(data, dict):
                break
        except Exception:
            last_raw = result
            data = None
    if not isinstance(data, dict):
        raise ValueError(f"模型输出不是有效 JSON：{last_raw[:200]}")
    return {
        "prompt": str(data.get("prompt") or current_prompt).strip(),
        "groups": normalize_split_groups(data.get("groups")),
    }


def split_prompt_role_aware(description: str, tags: list[str]) -> list[dict]:
    """角色感知拆分：把标签按角色（男A/女A…）与动作/服装/场景/画风分组。"""
    prompt = (
        "根据图片描述与标签列表，把标签按角色与类别分组。\n"
        "单角色时按性别用 女A/男A，不确定性别用 人物A；多角色时按 男A、男B、女A、女B 区分。\n"
        f"图片描述：{description}\n"
        f"标签：{', '.join(tags)}\n"
        "输出示例："
        '{"groups":[{"label":"女A","items":["1girl","long hair","blue eyes"]},'
        '{"label":"服装","items":["school uniform"]},'
        '{"label":"动作","items":["standing","looking at viewer"]},'
        '{"label":"场景","items":["simple background"]},'
        '{"label":"画风","items":["masterpiece"]}]}\n'
        "要求：\n"
        "1. 发型/发色/瞳色/体型/角色名等外观标签必须放入角色组；画风组只放质量、画风、镜头类标签。\n"
        "2. 输入标签列表里的每个标签都必须出现且只能出现一次；禁止省略、复制到多组、编造新标签。\n"
        "3. 服装类标签放服装组；动作/姿势放动作组；背景放场景组；无法归类的放其他组。\n"
        "只输出 JSON，不要输出解释。"
    )
    data: dict | None = None
    last_raw = ""
    result = ""
    for _ in range(3):
        try:
            result = llm.chat(
                [{"role": "system", "content": "你是提示词拆分助手，只输出 JSON。"}, {"role": "user", "content": prompt}],
                max_tokens=1600,
                temperature=0.15,
                think=False,
            )
            data = _parse_json(result)
            if isinstance(data, dict):
                break
        except Exception:
            last_raw = result
            data = None
    if not isinstance(data, dict):
        raise ValueError(f"模型输出不是有效 JSON：{last_raw[:200]}")
    raw_groups = normalize_split_groups(data.get("groups"))
    groups = _complete_role_groups(raw_groups, tags) if raw_groups else fallback_role_groups(tags)
    if not groups:
        groups = fallback_role_groups(tags)
    if not groups:
        raise ValueError("模型没有返回有效的角色/类别分组")
    return groups
