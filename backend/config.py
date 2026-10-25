"""集中化路径与运行环境配置：所有硬编码路径在此定义，支持环境变量覆盖。"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


def _env(key: str, default: str) -> str:
    value = os.environ.get(key, "").strip()
    return value or default


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


def _endpoint_parts(url: str, default_host: str, default_port: int) -> tuple[str, int]:
    parsed = urlparse(url if "://" in url else f"http://{url}")
    return parsed.hostname or default_host, parsed.port or default_port


PROJECT_ROOT = Path(_env("AI_WORKBENCH_ROOT", r"D:\workSpace\code\ai-workbench"))
AI_PRODUCT_DIR = Path(_env("AI_PRODUCT_DIR", str(PROJECT_ROOT / "AIproduct")))
DB_PATH = Path(_env("RIDER_STUDIO_DB", str(AI_PRODUCT_DIR / "rider_studio.db")))
GAME_ASSISTANT_DB_PATH = Path(_env("GAME_ASSISTANT_DB", str(AI_PRODUCT_DIR / "game_assistant.db")))
GAME_ASSISTANT_PRIVATE_DB_PATH = Path(_env("GAME_ASSISTANT_PRIVATE_DB", str(AI_PRODUCT_DIR / "game_assistant_private.db")))

GAME_ASSISTANT_CONFIG_DIR = Path(_env("GAME_ASSISTANT_CONFIG_DIR", str(AI_PRODUCT_DIR / "game_assistant_config")))
GAME_ASSISTANT_SOURCE_DIR = Path(_env("GAME_ASSISTANT_SOURCE_DIR", str(AI_PRODUCT_DIR / "game_assistant_sources")))
GAME_ASSISTANT_COMBAT_DIR = Path(_env("GAME_ASSISTANT_COMBAT_DIR", str(AI_PRODUCT_DIR / "game_assistant_combat")))
GAME_ASSISTANT_KB_DIR = Path(_env("GAME_ASSISTANT_KB_DIR", str(AI_PRODUCT_DIR / "game_assistant_kb")))
GAME_ASSISTANT_SECRETS_PATH = Path(_env("GAME_ASSISTANT_SECRETS", str(GAME_ASSISTANT_CONFIG_DIR / "secrets.json")))
WEB_TOOLS_CONFIG_DIR = Path(_env("WEB_TOOLS_CONFIG_DIR", str(AI_PRODUCT_DIR / "app_config")))
WEB_TOOLS_CACHE_DIR = Path(_env("WEB_TOOLS_CACHE_DIR", str(WEB_TOOLS_CONFIG_DIR / "web_tools_cache")))
WEB_TOOLS_EVENTS_PATH = Path(_env("WEB_TOOLS_EVENTS", str(WEB_TOOLS_CONFIG_DIR / "web_tools_events.jsonl")))
WEB_TOOLS_SECRETS_PATH = Path(_env("WEB_TOOLS_SECRETS", str(WEB_TOOLS_CONFIG_DIR / "secrets.json")))
GAME_ASSISTANT_SOURCE_MAX_BYTES = _env_int("GAME_ASSISTANT_SOURCE_MAX_BYTES", 5_000_000)

# FGO 自动执行：执行层是 FGO-py（绑定规则 2026-10-10/10-12），这里的路径指向
# FGO-py 本地副本与它的专用解释器；后端只通过 fgoAgent.py 的 JSON 协议驱动它。
GAME_ASSISTANT_EXECUTION_DIR = Path(
    _env("GAME_ASSISTANT_EXECUTION_DIR", str(AI_PRODUCT_DIR / "game_assistant_execution"))
)
FGO_PY_DIR = Path(_env("FGO_PY_DIR", r"D:\workSpace\code\_research\fgo-py\FGO-py"))
FGO_PY_PYTHON = Path(_env("FGO_PY_PYTHON", r"D:\workSpace\code\_research\fgo-py\.venv\Scripts\python.exe"))
FGO_PY_AGENT = _env("FGO_PY_AGENT", "fgoAgent.py")
FGO_PY_DEVICE = _env("FGO_PY_DEVICE", "emulator-5554")
GAME_ASSISTANT_SOURCE_TIMEOUT = _env_int("GAME_ASSISTANT_SOURCE_TIMEOUT", 20)

BACKEND_HOST = _env("AI_WORKBENCH_HOST", "127.0.0.1")
BACKEND_PORT = _env_int("AI_WORKBENCH_PORT", 8500)

OLLAMA_HOST = _env("OLLAMA_SERVICE_HOST", "127.0.0.1")
OLLAMA_PORT = _env_int("OLLAMA_SERVICE_PORT", 11434)
OLLAMA_BASE = _env("OLLAMA_BASE", f"http://{OLLAMA_HOST}:{OLLAMA_PORT}").rstrip("/")
OLLAMA_HOST, OLLAMA_PORT = _endpoint_parts(OLLAMA_BASE, OLLAMA_HOST, OLLAMA_PORT)
LOCAL_CHAT_MODEL = _env("LOCAL_CHAT_MODEL", "qwen3:8b")
GAME_ASSISTANT_LOCAL_MODEL = _env("GAME_ASSISTANT_LOCAL_MODEL", LOCAL_CHAT_MODEL)
DEEPSEEK_BASE_URL = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = _env("DEEPSEEK_MODEL", "deepseek-chat")
GAME_ASSISTANT_LLM_TIMEOUT = _env_int("GAME_ASSISTANT_LLM_TIMEOUT", 180)
R18_MODEL = _env("R18_MODEL", "dolphin-llama3:8b")
VLM_MODEL = _env("VLM_MODEL", "huihui_ai/qwen2.5-vl-abliterated:7b")
VLM_COUNT_MODEL = _env("VLM_COUNT_MODEL", "qwen2.5vl:3b")

COMFY_HOST = _env("COMFY_SERVICE_HOST", "127.0.0.1")
COMFY_PORT = _env_int("COMFY_SERVICE_PORT", 8188)
COMFY_URL = _env("COMFY_URL", f"http://{COMFY_HOST}:{COMFY_PORT}").rstrip("/")
COMFY_HOST, COMFY_PORT = _endpoint_parts(COMFY_URL, COMFY_HOST, COMFY_PORT)
COMFY_GENERATE_TIMEOUT = int(_env("COMFY_GENERATE_TIMEOUT", "600"))
LORAS_DIR = Path(_env("COMFY_LORAS_DIR", r"D:\AI\ComfyUI\models\loras"))
MODELS_DIR = Path(_env("COMFY_DIFFUSION_MODELS_DIR", r"D:\AI\ComfyUI\models\diffusion_models"))
CLIP_NAME = _env("ANIMA_CLIP_NAME", "qwen_3_06b_base.safetensors")
VAE_NAME = _env("ANIMA_VAE_NAME", "qwen_image_vae.safetensors")
QWEN3_PATH = Path(_env("ANIMA_QWEN3_PATH", r"D:\AI\ComfyUI\models\text_encoders\qwen_3_06b_base.safetensors"))
VAE_PATH = Path(_env("ANIMA_VAE_PATH", r"D:\AI\ComfyUI\models\vae\qwen_image_vae.safetensors"))

KOYA_ROOT = Path(_env("KOYA_ROOT", r"D:\AI\kohya_ss"))
KOYA_PY = Path(_env("KOYA_PYTHON", str(KOYA_ROOT / "venv" / "Scripts" / "python.exe")))
KOYA_SD_SCRIPTS = Path(_env("KOYA_SD_SCRIPTS", str(KOYA_ROOT / "sd-scripts")))
ACCELERATE_EXE = KOYA_PY.parent / "accelerate.exe"
WD14_SCRIPT = KOYA_SD_SCRIPTS / "finetune" / "tag_images_by_wd14_tagger.py"
TRAIN_SCRIPT = KOYA_SD_SCRIPTS / "anima_train_network.py"
CONVERT_SCRIPT = KOYA_SD_SCRIPTS / "networks" / "convert_anima_lora_to_comfy.py"
WD14_MODEL_DIR = Path(_env("WD14_MODEL_DIR", str(KOYA_ROOT / "wd14_tagger_model")))
WD14_DEFAULT_REPO = _env("WD14_MODEL_REPO", "SmilingWolf/wd-v1-4-convnext-tagger-v2")

LORA_TRAINING_ROOT = Path(_env("LORA_TRAINING_ROOT", r"D:\AI\lora-training"))
DATASET_DIR = Path(_env("LORA_DATASET_DIR", str(LORA_TRAINING_ROOT / "dataset" / "images")))
TAG_BACKUP_DIR = Path(_env("LORA_TAG_BACKUP_DIR", str(LORA_TRAINING_ROOT / "tag_backups")))
OUTPUT_DIR = Path(_env("LORA_OUTPUT_DIR", str(LORA_TRAINING_ROOT / "output")))
LOG_DIR = Path(_env("LORA_LOG_DIR", str(LORA_TRAINING_ROOT / "logs")))
TRAIN_DATASET_CONFIG = Path(_env("LORA_DATASET_CONFIG", str(LORA_TRAINING_ROOT / "dataset_config.toml")))
EXCLUDED_DIR = DATASET_DIR.parent / "excluded"
AI_IMPORT_MARKER = DATASET_DIR / "ai_imported.json"

SCAN_SCRIPT = PROJECT_ROOT / "lora-training" / "scan_dataset.py"
MERGE_SCRIPT = PROJECT_ROOT / "lora-training" / "merge_anima_loras.py"
EMBED_CACHE_DIR = Path(_env("EMBED_CACHE_DIR", str(PROJECT_ROOT / "rag_knowledge_base" / "models")))
TAG_EMBED_MODEL = _env("TAG_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
TAG_EMBED_CACHE_DIR = Path(_env("TAG_EMBED_CACHE_DIR", str(PROJECT_ROOT / "rag_knowledge_base" / "models")))
COMPARE_OUTPUT_DIR = Path(_env("COMPARE_OUTPUT_DIR", r"D:\workSpace\code\ab_test_20260830"))

OLLAMA_EXE = Path(_env("OLLAMA_EXE", r"D:\AI\Ollama\ollama.exe"))
OLLAMA_MODELS = Path(_env("OLLAMA_MODELS", r"D:\AI\Ollama\models"))
COMFY_PY = Path(_env("COMFY_PY", r"D:\AI\ComfyUI\venv\Scripts\python.exe"))
COMFY_DIR = Path(_env("COMFY_DIR", r"D:\AI\ComfyUI"))
COMFY_LOG = Path(_env("COMFY_LOG", r"D:\AI\ComfyUI\comfyui-service.log"))
COMFY_INPUT_DIR = Path(_env("COMFY_INPUT_DIR", str(COMFY_DIR / "input")))
VIDEO_OUTPUT_DIR = Path(_env("VIDEO_OUTPUT_DIR", str(AI_PRODUCT_DIR / "videos")))
VIDEO_KEYFRAME_DIR = Path(_env("VIDEO_KEYFRAME_DIR", str(AI_PRODUCT_DIR / "video_keyframes")))
VIDEO_WORKFLOW_PATH = Path(
    _env("VIDEO_WORKFLOW_PATH", str(PROJECT_ROOT.parent / "Workflow" / "wan_nsfw_lora_i2v_poc_api.json"))
)
VIDEO_MODEL = _env("VIDEO_MODEL", "wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors")
VIDEO_LORA = _env("VIDEO_LORA", "wan21_general_nsfw_e14_fixed.safetensors")
VIDEO_CLIP = _env("VIDEO_CLIP", "umt5_xxl_fp8_e4m3fn_scaled.safetensors")
VIDEO_VAE = _env("VIDEO_VAE", "wan_2.1_vae.safetensors")
VIDEO_CLIP_VISION = _env("VIDEO_CLIP_VISION", "clip_vision_h.safetensors")
VIDEO_COMFY_SUBDIR = _env("VIDEO_COMFY_SUBDIR", "workbench_video")

BACKUP_ROOT = Path(_env("WORKBENCH_BACKUP_DIR", str(PROJECT_ROOT.parent / "backups" / "workbench")))

DRAW_DEFAULT_MODEL = _env("DRAW_DEFAULT_MODEL", "chosenIrisesMix_v20Anima.safetensors")
DRAW_DEFAULT_PROMPT = _env(
    "DRAW_DEFAULT_PROMPT",
    (
        "uncensored, masterpiece, score 7, highres, absurdres, best quality, "
        "very aesthetic, anime coloring, 1girl, solo, long hair, blue eyes, "
        "school uniform, sailor collar, white shirt, pleated skirt, looking at viewer, "
        "smile, upper body, simple background, cherry blossoms"
    ),
)
PRESET_ASSET_DEFAULT_STYLE_POSITIVE = _env(
    "PRESET_ASSET_DEFAULT_STYLE_POSITIVE",
    (
        "uncensored, masterpiece, score 7, highres, absurdres, best quality, "
        "very aesthetic, anime coloring"
    ),
)
DRAW_DEFAULT_NEGATIVE_PROMPT = _env(
    "DRAW_DEFAULT_NEGATIVE_PROMPT",
    (
        "worst quality, low quality, score_1, score_2, score_3, artist name, blurry, "
        "jpeg artifacts, lowres, signature, mosaic_censored, bar_censor, text_censor, "
        "censored, censor, censor_bar, blur_censor, pixelated, mosaic, censorship"
    ),
)
DRAW_DEFAULT_WIDTH = _env_int("DRAW_DEFAULT_WIDTH", 1080)
DRAW_DEFAULT_HEIGHT = _env_int("DRAW_DEFAULT_HEIGHT", 1920)
DRAW_DEFAULT_STEPS = _env_int("DRAW_DEFAULT_STEPS", 18)
DRAW_DEFAULT_CFG = _env_float("DRAW_DEFAULT_CFG", 1.0)
DRAW_DEFAULT_LORA_STRENGTH_MODEL = _env_float("DRAW_DEFAULT_LORA_STRENGTH_MODEL", 0.8)
DRAW_DEFAULT_LORA_STRENGTH_CLIP = _env_float("DRAW_DEFAULT_LORA_STRENGTH_CLIP", 0.8)
DRAW_GROUP_COUNT_MIN = _env_int("DRAW_GROUP_COUNT_MIN", 1)
DRAW_MAX_GROUP_COUNT = _env_int("DRAW_MAX_GROUP_COUNT", 20)
DRAW_MAX_TOTAL_COUNT = _env_int("DRAW_MAX_TOTAL_COUNT", 100)
DRAW_WIDTH_MIN = _env_int("DRAW_WIDTH_MIN", 256)
DRAW_WIDTH_MAX = _env_int("DRAW_WIDTH_MAX", 4096)
DRAW_HEIGHT_MIN = _env_int("DRAW_HEIGHT_MIN", 256)
DRAW_HEIGHT_MAX = _env_int("DRAW_HEIGHT_MAX", 4096)
DRAW_STEPS_MIN = _env_int("DRAW_STEPS_MIN", 1)
DRAW_STEPS_MAX = _env_int("DRAW_STEPS_MAX", 80)
DRAW_SEED_MIN = _env_int("DRAW_SEED_MIN", 0)
DRAW_SEED_MAX = _env_int("DRAW_SEED_MAX", 9_007_199_254_740_991)
DRAW_CFG_MIN = _env_float("DRAW_CFG_MIN", 0.5)
DRAW_CFG_MAX = _env_float("DRAW_CFG_MAX", 20.0)
DRAW_CFG_STEP = _env_float("DRAW_CFG_STEP", 0.5)
DRAW_LORA_STRENGTH_MIN = _env_float("DRAW_LORA_STRENGTH_MIN", 0.0)
DRAW_LORA_STRENGTH_MAX = _env_float("DRAW_LORA_STRENGTH_MAX", 1.5)
DRAW_LORA_STRENGTH_STEP = _env_float("DRAW_LORA_STRENGTH_STEP", 0.05)
DRAW_ALLOWED_SIZES = ((1080, 1920), (1920, 1080), (1024, 1024))

VIDEO_DEFAULT_FRAMES = _env_int("VIDEO_DEFAULT_FRAMES", 121)
VIDEO_DEFAULT_FPS = _env_int("VIDEO_DEFAULT_FPS", 24)
VIDEO_DEFAULT_WIDTH = _env_int("VIDEO_DEFAULT_WIDTH", 512)
VIDEO_DEFAULT_HEIGHT = _env_int("VIDEO_DEFAULT_HEIGHT", 512)
VIDEO_DEFAULT_STEPS = _env_int("VIDEO_DEFAULT_STEPS", 20)
VIDEO_DEFAULT_CFG = _env_float("VIDEO_DEFAULT_CFG", 6.0)
VIDEO_DEFAULT_DENOISE = _env_float("VIDEO_DEFAULT_DENOISE", 1.0)
VIDEO_DEFAULT_LORA_STRENGTH = _env_float("VIDEO_DEFAULT_LORA_STRENGTH", 1.0)
VIDEO_SEED_MIN = _env_int("VIDEO_SEED_MIN", 0)
VIDEO_TIMEOUT_SECONDS = _env_int("VIDEO_TIMEOUT_SECONDS", 7200)
VIDEO_KEYFRAME_MAX_BYTES = _env_int("VIDEO_KEYFRAME_MAX_BYTES", 20 * 1024 * 1024)
VIDEO_SCRIPT_MAX_LENGTH = _env_int("VIDEO_SCRIPT_MAX_LENGTH", 4000)
VIDEO_STEPS_MIN = _env_int("VIDEO_STEPS_MIN", 1)
VIDEO_STEPS_MAX = _env_int("VIDEO_STEPS_MAX", 100)
VIDEO_CFG_MIN = _env_float("VIDEO_CFG_MIN", 0.5)
VIDEO_CFG_MAX = _env_float("VIDEO_CFG_MAX", 20.0)
VIDEO_CFG_STEP = _env_float("VIDEO_CFG_STEP", 0.5)
VIDEO_DENOISE_MIN = _env_float("VIDEO_DENOISE_MIN", 0.0)
VIDEO_DENOISE_MAX = _env_float("VIDEO_DENOISE_MAX", 1.0)
VIDEO_DENOISE_STEP = _env_float("VIDEO_DENOISE_STEP", 0.05)
VIDEO_LORA_STRENGTH_MIN = _env_float("VIDEO_LORA_STRENGTH_MIN", 0.0)
VIDEO_LORA_STRENGTH_MAX = _env_float("VIDEO_LORA_STRENGTH_MAX", 1.5)
VIDEO_LORA_STRENGTH_STEP = _env_float("VIDEO_LORA_STRENGTH_STEP", 0.05)
VIDEO_ALLOWED_FRAMES = (33, 81, 121)
VIDEO_ALLOWED_SIZES = ((512, 512), (832, 480), (480, 832))

TRAIN_DEFAULT_CAPTION_THRESHOLD = _env_float("TRAIN_DEFAULT_CAPTION_THRESHOLD", 0.35)
TRAIN_DEFAULT_CAPTION_BATCH_SIZE = _env_int("TRAIN_DEFAULT_CAPTION_BATCH_SIZE", 4)
TRAIN_DEFAULT_SKIP_EXISTING = _env("TRAIN_DEFAULT_SKIP_EXISTING", "1") != "0"
TRAIN_DEFAULT_REMOVE_UNDERSCORE = _env("TRAIN_DEFAULT_REMOVE_UNDERSCORE", "1") != "0"
TRAIN_DEFAULT_AUTO_CONVERT = _env("TRAIN_DEFAULT_AUTO_CONVERT", "1") != "0"
TRAIN_CAPTION_THRESHOLD_MIN = _env_float("TRAIN_CAPTION_THRESHOLD_MIN", 0.1)
TRAIN_CAPTION_THRESHOLD_MAX = _env_float("TRAIN_CAPTION_THRESHOLD_MAX", 0.9)
TRAIN_CAPTION_THRESHOLD_STEP = _env_float("TRAIN_CAPTION_THRESHOLD_STEP", 0.05)
TRAIN_CAPTION_BATCH_MIN = _env_int("TRAIN_CAPTION_BATCH_MIN", 1)
TRAIN_CAPTION_BATCH_MAX = _env_int("TRAIN_CAPTION_BATCH_MAX", 16)
TRAIN_DEFAULT_RESOLUTION = _env_int("TRAIN_DEFAULT_RESOLUTION", 1024)
TRAIN_DEFAULT_REPEATS = _env_int("TRAIN_DEFAULT_REPEATS", 5)
TRAIN_DEFAULT_BATCH_SIZE = _env_int("TRAIN_DEFAULT_BATCH_SIZE", 1)
TRAIN_DEFAULT_NETWORK_DIM = _env_int("TRAIN_DEFAULT_NETWORK_DIM", 32)
TRAIN_DEFAULT_NETWORK_ALPHA = _env_int("TRAIN_DEFAULT_NETWORK_ALPHA", 16)
TRAIN_DEFAULT_LEARNING_RATE = _env_float("TRAIN_DEFAULT_LEARNING_RATE", 0.0001)
TRAIN_DEFAULT_EPOCHS = _env_int("TRAIN_DEFAULT_EPOCHS", 4)
TRAIN_DEFAULT_SAVE_EVERY = _env_int("TRAIN_DEFAULT_SAVE_EVERY", 1)
TRAIN_DEFAULT_MAX_STEPS = _env_int("TRAIN_DEFAULT_MAX_STEPS", 0)
TRAIN_RESOLUTION_MIN = _env_int("TRAIN_RESOLUTION_MIN", 512)
TRAIN_RESOLUTION_MAX = _env_int("TRAIN_RESOLUTION_MAX", 2048)
TRAIN_RESOLUTION_STEP = _env_int("TRAIN_RESOLUTION_STEP", 64)
TRAIN_REPEATS_MIN = _env_int("TRAIN_REPEATS_MIN", 1)
TRAIN_REPEATS_MAX = _env_int("TRAIN_REPEATS_MAX", 50)
TRAIN_BATCH_SIZE_MIN = _env_int("TRAIN_BATCH_SIZE_MIN", 1)
TRAIN_BATCH_SIZE_MAX = _env_int("TRAIN_BATCH_SIZE_MAX", 8)
TRAIN_NETWORK_DIM_MIN = _env_int("TRAIN_NETWORK_DIM_MIN", 4)
TRAIN_NETWORK_DIM_MAX = _env_int("TRAIN_NETWORK_DIM_MAX", 128)
TRAIN_NETWORK_ALPHA_MIN = _env_int("TRAIN_NETWORK_ALPHA_MIN", 4)
TRAIN_NETWORK_ALPHA_MAX = _env_int("TRAIN_NETWORK_ALPHA_MAX", 128)
TRAIN_LEARNING_RATE_MIN = _env_float("TRAIN_LEARNING_RATE_MIN", 0.0000001)
TRAIN_LEARNING_RATE_MAX = _env_float("TRAIN_LEARNING_RATE_MAX", 0.01)
TRAIN_LEARNING_RATE_STEP = _env_float("TRAIN_LEARNING_RATE_STEP", 0.00005)
TRAIN_EPOCHS_MIN = _env_int("TRAIN_EPOCHS_MIN", 1)
TRAIN_EPOCHS_MAX = _env_int("TRAIN_EPOCHS_MAX", 200)
TRAIN_SAVE_EVERY_MIN = _env_int("TRAIN_SAVE_EVERY_MIN", 1)
TRAIN_SAVE_EVERY_MAX = _env_int("TRAIN_SAVE_EVERY_MAX", 50)
TRAIN_MAX_STEPS_MIN = _env_int("TRAIN_MAX_STEPS_MIN", 0)
TRAIN_MAX_STEPS_MAX = _env_int("TRAIN_MAX_STEPS_MAX", 100000)
TRAIN_MERGE_RATIO_DEFAULT = _env_float("TRAIN_MERGE_RATIO_DEFAULT", 1.0)
TRAIN_MERGE_RATIO_MIN = _env_float("TRAIN_MERGE_RATIO_MIN", 0.1)
TRAIN_MERGE_RATIO_MAX = _env_float("TRAIN_MERGE_RATIO_MAX", 2.0)
TRAIN_MERGE_RATIO_STEP = _env_float("TRAIN_MERGE_RATIO_STEP", 0.1)
COMPARE_DEFAULT_WIDTH = _env_int("COMPARE_DEFAULT_WIDTH", DRAW_DEFAULT_WIDTH)
COMPARE_DEFAULT_HEIGHT = _env_int("COMPARE_DEFAULT_HEIGHT", DRAW_DEFAULT_HEIGHT)
COMPARE_DEFAULT_STEPS = _env_int("COMPARE_DEFAULT_STEPS", DRAW_DEFAULT_STEPS)
COMPARE_DEFAULT_CFG = _env_float("COMPARE_DEFAULT_CFG", DRAW_DEFAULT_CFG)
COMPARE_WIDTH_MIN = _env_int("COMPARE_WIDTH_MIN", DRAW_WIDTH_MIN)
COMPARE_WIDTH_MAX = _env_int("COMPARE_WIDTH_MAX", DRAW_WIDTH_MAX)
COMPARE_HEIGHT_MIN = _env_int("COMPARE_HEIGHT_MIN", DRAW_HEIGHT_MIN)
COMPARE_HEIGHT_MAX = _env_int("COMPARE_HEIGHT_MAX", DRAW_HEIGHT_MAX)
COMPARE_STEPS_MIN = _env_int("COMPARE_STEPS_MIN", DRAW_STEPS_MIN)
COMPARE_STEPS_MAX = _env_int("COMPARE_STEPS_MAX", DRAW_STEPS_MAX)
COMPARE_CFG_MIN = _env_float("COMPARE_CFG_MIN", DRAW_CFG_MIN)
COMPARE_CFG_MAX = _env_float("COMPARE_CFG_MAX", DRAW_CFG_MAX)
COMPARE_CFG_STEP = _env_float("COMPARE_CFG_STEP", DRAW_CFG_STEP)
PRESET_COMPOSITION_MAX_ITEMS = _env_int("PRESET_COMPOSITION_MAX_ITEMS", 12)

PRESET_ASSET_ROOT = Path(
    _env("PRESET_ASSET_ROOT", str(AI_PRODUCT_DIR / "preset_assets"))
)
PRESET_ASSET_TEMPLATE_VERSION = _env(
    "PRESET_ASSET_TEMPLATE_VERSION", "thumbnail_template_v25"
)
PRESET_ASSET_SEMANTIC_VALIDATION = _env(
    "PRESET_ASSET_SEMANTIC_VALIDATION", "advisory"
).strip().lower()
PRESET_ASSET_UPLOAD_MAX_BYTES = _env_int(
    "PRESET_ASSET_UPLOAD_MAX_BYTES", 20 * 1024 * 1024
)
PRESET_ASSET_UPLOAD_MAX_PIXELS = _env_int(
    "PRESET_ASSET_UPLOAD_MAX_PIXELS", 20_000_000
)
PRESET_ASSET_CANDIDATE_MIN = _env_int("PRESET_ASSET_CANDIDATE_MIN", 1)
PRESET_ASSET_CANDIDATE_MAX = _env_int("PRESET_ASSET_CANDIDATE_MAX", 4)
PRESET_ASSET_CANDIDATE_DEFAULT = _env_int("PRESET_ASSET_CANDIDATE_DEFAULT", 2)
PRESET_ASSET_BATCH_MAX_ITEMS = _env_int("PRESET_ASSET_BATCH_MAX_ITEMS", 50)
PRESET_ASSET_FOCUS_MIN = _env_float("PRESET_ASSET_FOCUS_MIN", 0.0)
PRESET_ASSET_FOCUS_MAX = _env_float("PRESET_ASSET_FOCUS_MAX", 1.0)
PRESET_ASSET_FOCUS_STEP = _env_float("PRESET_ASSET_FOCUS_STEP", 0.01)
PRESET_ASSET_ZOOM_MIN = _env_float("PRESET_ASSET_ZOOM_MIN", 0.05)
PRESET_ASSET_ZOOM_MAX = _env_float("PRESET_ASSET_ZOOM_MAX", 10.0)
PRESET_ASSET_ZOOM_STEP = _env_float("PRESET_ASSET_ZOOM_STEP", 0.05)
PRESET_ASSET_CPU_CONCURRENCY = _env_int("PRESET_ASSET_CPU_CONCURRENCY", 2)
PRESET_ASSET_AI_CONCURRENCY = _env_int("PRESET_ASSET_AI_CONCURRENCY", 1)
PRESET_ASSET_PREVIEW_FORMAT = _env("PRESET_ASSET_PREVIEW_FORMAT", "WEBP").upper()
PRESET_ASSET_PREVIEW_QUALITY = _env_int("PRESET_ASSET_PREVIEW_QUALITY", 90)
PRESET_ASSET_TARGETS = {
    "pose": {
        "generation_size": (832, 1216),
        "output_size": (512, 768),
        "format": "PNG",
        "quality": 95,
    },
    "clothing": {
        "generation_size": (540, 960),
        "output_size": (270, 480),
        "format": "WEBP",
        "quality": 90,
    },
    "scene": {
        "generation_size": (1024, 576),
        "output_size": (480, 270),
        "format": "WEBP",
        "quality": 90,
    },
    "body": {
        "generation_size": (540, 960),
        "output_size": (270, 480),
        "format": "WEBP",
        "quality": 90,
    },
    "toy": {
        "generation_size": (768, 768),
        "output_size": (384, 384),
        "format": "WEBP",
        "quality": 90,
    },
    "expansion": {
        "generation_size": (768, 768),
        "output_size": (384, 384),
        "format": "WEBP",
        "quality": 90,
    },
    "character": {
        "generation_size": (540, 960),
        "output_size": (270, 480),
        "format": "WEBP",
        "quality": 90,
    },
}
PRESET_ASSET_DEFAULT_SETTINGS = {
    "version": 1,
    "model": DRAW_DEFAULT_MODEL,
    "loras": [],
    "lora_strengths": {},
    "lora_strength_model": DRAW_DEFAULT_LORA_STRENGTH_MODEL,
    "lora_strength_clip": DRAW_DEFAULT_LORA_STRENGTH_CLIP,
    "steps": DRAW_DEFAULT_STEPS,
    "cfg": DRAW_DEFAULT_CFG,
    "seed_strategy": "random",
    "seed": None,
    "crop_mode": "cover",
    "focus_x": 0.5,
    "focus_y": 0.5,
    "zoom": 1.0,
    "candidate_count": PRESET_ASSET_CANDIDATE_DEFAULT,
    "style_positive": PRESET_ASSET_DEFAULT_STYLE_POSITIVE,
    "style_negative": DRAW_DEFAULT_NEGATIVE_PROMPT,
    "user_positive": "",
    "user_negative": "",
}

SETTINGS_HEALTH_INTERVAL_DEFAULT = _env_int("SETTINGS_HEALTH_INTERVAL_DEFAULT", 15)
SETTINGS_HEALTH_INTERVAL_MIN = _env_int("SETTINGS_HEALTH_INTERVAL_MIN", 5)
SETTINGS_HEALTH_INTERVAL_MAX = _env_int("SETTINGS_HEALTH_INTERVAL_MAX", 3600)
SETTINGS_MAX_FAILURES_DEFAULT = _env_int("SETTINGS_MAX_FAILURES_DEFAULT", 3)
SETTINGS_MAX_FAILURES_MIN = _env_int("SETTINGS_MAX_FAILURES_MIN", 1)
SETTINGS_MAX_FAILURES_MAX = _env_int("SETTINGS_MAX_FAILURES_MAX", 20)
SETTINGS_AUTO_SHUTDOWN_DELAY_DEFAULT = _env_int("SETTINGS_AUTO_SHUTDOWN_DELAY_DEFAULT", 60)
SETTINGS_AUTO_SHUTDOWN_DELAY_MIN = _env_int("SETTINGS_AUTO_SHUTDOWN_DELAY_MIN", 10)
SETTINGS_AUTO_SHUTDOWN_DELAY_MAX = _env_int("SETTINGS_AUTO_SHUTDOWN_DELAY_MAX", 600)
SETTINGS_DATA_RETENTION_DEFAULT = _env_int("SETTINGS_DATA_RETENTION_DEFAULT", 0)
SETTINGS_DATA_RETENTION_MIN = _env_int("SETTINGS_DATA_RETENTION_MIN", 0)
SETTINGS_DATA_RETENTION_MAX = _env_int("SETTINGS_DATA_RETENTION_MAX", 3650)

QUERY_PAGE_MIN = _env_int("QUERY_PAGE_MIN", 1)
QUERY_RECORDS_PAGE_DEFAULT = _env_int("QUERY_RECORDS_PAGE_DEFAULT", 1)
QUERY_RECORDS_PAGE_SIZE_DEFAULT = _env_int("QUERY_RECORDS_PAGE_SIZE_DEFAULT", 10)
QUERY_RECORDS_PAGE_SIZE_MAX = _env_int("QUERY_RECORDS_PAGE_SIZE_MAX", 100)
QUERY_PROMPT_STATS_TOP_DEFAULT = _env_int("QUERY_PROMPT_STATS_TOP_DEFAULT", 20)
QUERY_PROMPT_STATS_TOP_MAX = _env_int("QUERY_PROMPT_STATS_TOP_MAX", 500)
QUERY_IMAGE_LIBRARY_PAGE_DEFAULT = _env_int("QUERY_IMAGE_LIBRARY_PAGE_DEFAULT", 1)
QUERY_IMAGE_LIBRARY_PAGE_SIZE_DEFAULT = _env_int("QUERY_IMAGE_LIBRARY_PAGE_SIZE_DEFAULT", 20)
QUERY_IMAGE_LIBRARY_PAGE_SIZE_MAX = _env_int("QUERY_IMAGE_LIBRARY_PAGE_SIZE_MAX", 100)
QUERY_PROMPT_SET_PAGE_DEFAULT = _env_int("QUERY_PROMPT_SET_PAGE_DEFAULT", 1)
QUERY_PROMPT_SET_PAGE_SIZE_DEFAULT = _env_int("QUERY_PROMPT_SET_PAGE_SIZE_DEFAULT", 10)
QUERY_PROMPT_SET_PAGE_SIZE_MAX = _env_int("QUERY_PROMPT_SET_PAGE_SIZE_MAX", 100)
QUERY_VIDEO_KEYFRAMES_LIMIT_DEFAULT = _env_int("QUERY_VIDEO_KEYFRAMES_LIMIT_DEFAULT", 200)
QUERY_VIDEO_KEYFRAMES_LIMIT_MAX = _env_int("QUERY_VIDEO_KEYFRAMES_LIMIT_MAX", 1000)
QUERY_VIDEO_SCRIPTS_LIMIT_DEFAULT = _env_int("QUERY_VIDEO_SCRIPTS_LIMIT_DEFAULT", 30)
QUERY_VIDEO_SCRIPTS_LIMIT_MAX = _env_int("QUERY_VIDEO_SCRIPTS_LIMIT_MAX", 200)
QUERY_VIDEO_LIBRARY_LIMIT_DEFAULT = _env_int("QUERY_VIDEO_LIBRARY_LIMIT_DEFAULT", 100)
QUERY_VIDEO_LIBRARY_LIMIT_MAX = _env_int("QUERY_VIDEO_LIBRARY_LIMIT_MAX", 500)
QUERY_TRAIN_HISTORY_LIMIT_DEFAULT = _env_int("QUERY_TRAIN_HISTORY_LIMIT_DEFAULT", 100)
QUERY_TRAIN_HISTORY_LIMIT_MAX = _env_int("QUERY_TRAIN_HISTORY_LIMIT_MAX", 500)
QUERY_SYSTEM_TASKS_LIMIT_DEFAULT = _env_int("QUERY_SYSTEM_TASKS_LIMIT_DEFAULT", 50)
QUERY_SYSTEM_TASKS_LIMIT_MAX = _env_int("QUERY_SYSTEM_TASKS_LIMIT_MAX", 200)
QUERY_RECORD_EXPORT_LIMIT_DEFAULT = _env_int("QUERY_RECORD_EXPORT_LIMIT_DEFAULT", 100000)
QUERY_OVERVIEW_TAG_CHUNK = _env_int("QUERY_OVERVIEW_TAG_CHUNK", 50)
QUERY_MODULE_TOP_LIMIT = _env_int("QUERY_MODULE_TOP_LIMIT", 10)
QUERY_MODULE_TOP_LIMIT_V2 = _env_int("QUERY_MODULE_TOP_LIMIT_V2", 5)
QUERY_RECENT_ERROR_LIMIT = _env_int("QUERY_RECENT_ERROR_LIMIT", 3)
QUERY_DAILY_TREND_DAYS = _env_int("QUERY_DAILY_TREND_DAYS", 7)
BACKUP_KEEP_COUNT = _env_int("BACKUP_KEEP_COUNT", 10)


def runtime_config() -> dict:
    """Return runtime defaults shared by backend and frontend."""
    return {
        "backend": {
            "host": BACKEND_HOST,
            "port": BACKEND_PORT,
            "api_base": "/api",
        },
        "services": {
            "ollama": {"base_url": OLLAMA_BASE},
            "comfyui": {"base_url": COMFY_URL},
        },
        "draw": {
            "default_model": DRAW_DEFAULT_MODEL,
            "default_prompt": DRAW_DEFAULT_PROMPT,
            "default_negative_prompt": DRAW_DEFAULT_NEGATIVE_PROMPT,
            "default_width": DRAW_DEFAULT_WIDTH,
            "default_height": DRAW_DEFAULT_HEIGHT,
            "default_steps": DRAW_DEFAULT_STEPS,
            "default_cfg": DRAW_DEFAULT_CFG,
            "default_lora_strength_model": DRAW_DEFAULT_LORA_STRENGTH_MODEL,
            "default_lora_strength_clip": DRAW_DEFAULT_LORA_STRENGTH_CLIP,
            "group_count_min": DRAW_GROUP_COUNT_MIN,
            "max_group_count": DRAW_MAX_GROUP_COUNT,
            "max_total_count": DRAW_MAX_TOTAL_COUNT,
            "width_min": DRAW_WIDTH_MIN,
            "width_max": DRAW_WIDTH_MAX,
            "height_min": DRAW_HEIGHT_MIN,
            "height_max": DRAW_HEIGHT_MAX,
            "steps_min": DRAW_STEPS_MIN,
            "steps_max": DRAW_STEPS_MAX,
            "cfg_min": DRAW_CFG_MIN,
            "cfg_max": DRAW_CFG_MAX,
            "cfg_step": DRAW_CFG_STEP,
            "lora_strength_min": DRAW_LORA_STRENGTH_MIN,
            "lora_strength_max": DRAW_LORA_STRENGTH_MAX,
            "lora_strength_step": DRAW_LORA_STRENGTH_STEP,
            "allowed_sizes": [list(size) for size in DRAW_ALLOWED_SIZES],
        },
        "video": {
            "default_frames": VIDEO_DEFAULT_FRAMES,
            "default_fps": VIDEO_DEFAULT_FPS,
            "default_width": VIDEO_DEFAULT_WIDTH,
            "default_height": VIDEO_DEFAULT_HEIGHT,
            "default_steps": VIDEO_DEFAULT_STEPS,
            "default_cfg": VIDEO_DEFAULT_CFG,
            "default_denoise": VIDEO_DEFAULT_DENOISE,
            "default_lora_strength": VIDEO_DEFAULT_LORA_STRENGTH,
            "seed_min": VIDEO_SEED_MIN,
            "timeout_seconds": VIDEO_TIMEOUT_SECONDS,
            "keyframe_max_bytes": VIDEO_KEYFRAME_MAX_BYTES,
            "script_max_length": VIDEO_SCRIPT_MAX_LENGTH,
            "steps_min": VIDEO_STEPS_MIN,
            "steps_max": VIDEO_STEPS_MAX,
            "cfg_min": VIDEO_CFG_MIN,
            "cfg_max": VIDEO_CFG_MAX,
            "cfg_step": VIDEO_CFG_STEP,
            "denoise_min": VIDEO_DENOISE_MIN,
            "denoise_max": VIDEO_DENOISE_MAX,
            "denoise_step": VIDEO_DENOISE_STEP,
            "lora_strength_min": VIDEO_LORA_STRENGTH_MIN,
            "lora_strength_max": VIDEO_LORA_STRENGTH_MAX,
            "lora_strength_step": VIDEO_LORA_STRENGTH_STEP,
            "allowed_frames": list(VIDEO_ALLOWED_FRAMES),
            "allowed_sizes": [list(size) for size in VIDEO_ALLOWED_SIZES],
        },
        "train": {
            "default_caption_threshold": TRAIN_DEFAULT_CAPTION_THRESHOLD,
            "default_caption_batch_size": TRAIN_DEFAULT_CAPTION_BATCH_SIZE,
            "default_skip_existing": TRAIN_DEFAULT_SKIP_EXISTING,
            "default_remove_underscore": TRAIN_DEFAULT_REMOVE_UNDERSCORE,
            "default_auto_convert": TRAIN_DEFAULT_AUTO_CONVERT,
            "default_resolution": TRAIN_DEFAULT_RESOLUTION,
            "default_repeats": TRAIN_DEFAULT_REPEATS,
            "default_batch_size": TRAIN_DEFAULT_BATCH_SIZE,
            "default_network_dim": TRAIN_DEFAULT_NETWORK_DIM,
            "default_network_alpha": TRAIN_DEFAULT_NETWORK_ALPHA,
            "default_learning_rate": TRAIN_DEFAULT_LEARNING_RATE,
            "default_epochs": TRAIN_DEFAULT_EPOCHS,
            "default_save_every": TRAIN_DEFAULT_SAVE_EVERY,
            "default_max_steps": TRAIN_DEFAULT_MAX_STEPS,
            "caption_threshold_min": TRAIN_CAPTION_THRESHOLD_MIN,
            "caption_threshold_max": TRAIN_CAPTION_THRESHOLD_MAX,
            "caption_threshold_step": TRAIN_CAPTION_THRESHOLD_STEP,
            "caption_batch_min": TRAIN_CAPTION_BATCH_MIN,
            "caption_batch_max": TRAIN_CAPTION_BATCH_MAX,
            "resolution_min": TRAIN_RESOLUTION_MIN,
            "resolution_max": TRAIN_RESOLUTION_MAX,
            "resolution_step": TRAIN_RESOLUTION_STEP,
            "repeats_min": TRAIN_REPEATS_MIN,
            "repeats_max": TRAIN_REPEATS_MAX,
            "batch_size_min": TRAIN_BATCH_SIZE_MIN,
            "batch_size_max": TRAIN_BATCH_SIZE_MAX,
            "network_dim_min": TRAIN_NETWORK_DIM_MIN,
            "network_dim_max": TRAIN_NETWORK_DIM_MAX,
            "network_alpha_min": TRAIN_NETWORK_ALPHA_MIN,
            "network_alpha_max": TRAIN_NETWORK_ALPHA_MAX,
            "learning_rate_min": TRAIN_LEARNING_RATE_MIN,
            "learning_rate_max": TRAIN_LEARNING_RATE_MAX,
            "learning_rate_step": TRAIN_LEARNING_RATE_STEP,
            "epochs_min": TRAIN_EPOCHS_MIN,
            "epochs_max": TRAIN_EPOCHS_MAX,
            "save_every_min": TRAIN_SAVE_EVERY_MIN,
            "save_every_max": TRAIN_SAVE_EVERY_MAX,
            "max_steps_min": TRAIN_MAX_STEPS_MIN,
            "max_steps_max": TRAIN_MAX_STEPS_MAX,
            "merge_ratio_default": TRAIN_MERGE_RATIO_DEFAULT,
            "merge_ratio_min": TRAIN_MERGE_RATIO_MIN,
            "merge_ratio_max": TRAIN_MERGE_RATIO_MAX,
            "merge_ratio_step": TRAIN_MERGE_RATIO_STEP,
        },
        "compare": {
            "default_width": COMPARE_DEFAULT_WIDTH,
            "default_height": COMPARE_DEFAULT_HEIGHT,
            "default_steps": COMPARE_DEFAULT_STEPS,
            "default_cfg": COMPARE_DEFAULT_CFG,
            "width_min": COMPARE_WIDTH_MIN,
            "width_max": COMPARE_WIDTH_MAX,
            "height_min": COMPARE_HEIGHT_MIN,
            "height_max": COMPARE_HEIGHT_MAX,
            "steps_min": COMPARE_STEPS_MIN,
            "steps_max": COMPARE_STEPS_MAX,
            "cfg_min": COMPARE_CFG_MIN,
            "cfg_max": COMPARE_CFG_MAX,
            "cfg_step": COMPARE_CFG_STEP,
        },
        "preset_composition": {
            "max_items": PRESET_COMPOSITION_MAX_ITEMS,
        },
        "preset_assets": {
            "root": str(PRESET_ASSET_ROOT),
            "template_version": PRESET_ASSET_TEMPLATE_VERSION,
            "upload_max_bytes": PRESET_ASSET_UPLOAD_MAX_BYTES,
            "upload_max_pixels": PRESET_ASSET_UPLOAD_MAX_PIXELS,
            "candidate_min": PRESET_ASSET_CANDIDATE_MIN,
            "candidate_max": PRESET_ASSET_CANDIDATE_MAX,
            "candidate_default": PRESET_ASSET_CANDIDATE_DEFAULT,
            "batch_max_items": PRESET_ASSET_BATCH_MAX_ITEMS,
            "cpu_concurrency": PRESET_ASSET_CPU_CONCURRENCY,
            "ai_concurrency": PRESET_ASSET_AI_CONCURRENCY,
            "preview_format": PRESET_ASSET_PREVIEW_FORMAT,
            "preview_quality": PRESET_ASSET_PREVIEW_QUALITY,
            "targets": {
                kind: {
                    "generation_size": list(target["generation_size"]),
                    "output_size": list(target["output_size"]),
                    "format": target["format"],
                    "quality": target["quality"],
                }
                for kind, target in PRESET_ASSET_TARGETS.items()
            },
            "defaults": PRESET_ASSET_DEFAULT_SETTINGS,
        },
        "settings": {
            "health_interval_default": SETTINGS_HEALTH_INTERVAL_DEFAULT,
            "health_interval_min": SETTINGS_HEALTH_INTERVAL_MIN,
            "health_interval_max": SETTINGS_HEALTH_INTERVAL_MAX,
            "max_failures_default": SETTINGS_MAX_FAILURES_DEFAULT,
            "max_failures_min": SETTINGS_MAX_FAILURES_MIN,
            "max_failures_max": SETTINGS_MAX_FAILURES_MAX,
            "auto_shutdown_delay_default": SETTINGS_AUTO_SHUTDOWN_DELAY_DEFAULT,
            "auto_shutdown_delay_min": SETTINGS_AUTO_SHUTDOWN_DELAY_MIN,
            "auto_shutdown_delay_max": SETTINGS_AUTO_SHUTDOWN_DELAY_MAX,
            "data_retention_default": SETTINGS_DATA_RETENTION_DEFAULT,
            "data_retention_min": SETTINGS_DATA_RETENTION_MIN,
            "data_retention_max": SETTINGS_DATA_RETENTION_MAX,
        },
        "query": {
            "page_min": QUERY_PAGE_MIN,
            "records_page_default": QUERY_RECORDS_PAGE_DEFAULT,
            "records_page_size_default": QUERY_RECORDS_PAGE_SIZE_DEFAULT,
            "records_page_size_max": QUERY_RECORDS_PAGE_SIZE_MAX,
            "prompt_stats_top_default": QUERY_PROMPT_STATS_TOP_DEFAULT,
            "prompt_stats_top_max": QUERY_PROMPT_STATS_TOP_MAX,
            "image_library_page_default": QUERY_IMAGE_LIBRARY_PAGE_DEFAULT,
            "image_library_page_size_default": QUERY_IMAGE_LIBRARY_PAGE_SIZE_DEFAULT,
            "image_library_page_size_max": QUERY_IMAGE_LIBRARY_PAGE_SIZE_MAX,
            "prompt_set_page_default": QUERY_PROMPT_SET_PAGE_DEFAULT,
            "prompt_set_page_size_default": QUERY_PROMPT_SET_PAGE_SIZE_DEFAULT,
            "prompt_set_page_size_max": QUERY_PROMPT_SET_PAGE_SIZE_MAX,
            "video_keyframes_limit_default": QUERY_VIDEO_KEYFRAMES_LIMIT_DEFAULT,
            "video_keyframes_limit_max": QUERY_VIDEO_KEYFRAMES_LIMIT_MAX,
            "video_scripts_limit_default": QUERY_VIDEO_SCRIPTS_LIMIT_DEFAULT,
            "video_scripts_limit_max": QUERY_VIDEO_SCRIPTS_LIMIT_MAX,
            "video_library_limit_default": QUERY_VIDEO_LIBRARY_LIMIT_DEFAULT,
            "video_library_limit_max": QUERY_VIDEO_LIBRARY_LIMIT_MAX,
            "train_history_limit_default": QUERY_TRAIN_HISTORY_LIMIT_DEFAULT,
            "train_history_limit_max": QUERY_TRAIN_HISTORY_LIMIT_MAX,
            "system_tasks_limit_default": QUERY_SYSTEM_TASKS_LIMIT_DEFAULT,
            "system_tasks_limit_max": QUERY_SYSTEM_TASKS_LIMIT_MAX,
        },
        "backup": {
            "keep_count": BACKUP_KEEP_COUNT,
        },
    }
