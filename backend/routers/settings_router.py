"""内容限制开关接口。"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

import database
import config
import services
from web_tools import WebToolsSettings, get_web_tools_service

router = APIRouter()

CONTENT_RESTRICTION_KEY = "content_restriction"
VISUAL_REVIEW_KEY = "visual_review_enabled"
VLM_MODEL_KEY = "vlm_model"
DATA_RETENTION_KEY = "data_retention_days"
PROMPT_SEMANTIC_CHECK_KEY = "prompt_semantic_check"


@router.get("/api/settings/web-tools")
def get_web_tools_settings() -> dict:
    return get_web_tools_service().view().model_dump(mode="json")


@router.put("/api/settings/web-tools")
def put_web_tools_settings(payload: WebToolsSettings) -> dict:
    return get_web_tools_service().save_settings(payload).model_dump(mode="json")


@router.put("/api/settings/web-tools/api-key")
def put_web_tools_api_key(payload: dict = Body(...)) -> dict:
    provider = str(payload.get("provider") or "").strip()
    if provider not in {"deepseek", "tavily", "serper", "duckduckgo"}:
        raise HTTPException(status_code=400, detail="不支持的搜索 Provider")
    return get_web_tools_service().set_api_key(
        provider,  # type: ignore[arg-type]
        api_key=str(payload.get("api_key") or ""),
        clear=bool(payload.get("clear")),
    ).model_dump(mode="json")


@router.post("/api/settings/web-tools/test")
def test_web_tools() -> dict:
    return get_web_tools_service().test_connection()


@router.post("/api/settings/web-tools/cache/clear")
def clear_web_tools_cache() -> dict:
    return {"deleted": get_web_tools_service().clear_cache()}


def content_restriction_enabled() -> bool:
    """读取内容限制开关状态。"""
    return database.get_setting(CONTENT_RESTRICTION_KEY, "false") == "true"


@router.get("/api/settings/content-restriction")
def get_content_restriction() -> dict:
    """返回当前内容限制状态。"""
    return {"enabled": content_restriction_enabled()}


@router.post("/api/settings/content-restriction")
def set_content_restriction(payload: dict = Body(...)) -> dict:
    """开启或关闭内容限制。"""
    enabled = bool(payload.get("enabled", False))
    database.set_setting(CONTENT_RESTRICTION_KEY, "true" if enabled else "false")
    return {"enabled": enabled}


def visual_review_enabled() -> bool:
    """生成后视觉复核开关，默认开启。"""
    return database.get_setting(VISUAL_REVIEW_KEY, "true") == "true"


@router.get("/api/settings/visual-review")
def get_visual_review() -> dict:
    """返回生成后视觉复核状态。"""
    return {"enabled": visual_review_enabled()}


@router.post("/api/settings/visual-review")
def set_visual_review(payload: dict = Body(...)) -> dict:
    """开启或关闭生成后视觉复核。"""
    enabled = bool(payload.get("enabled", True))
    database.set_setting(VISUAL_REVIEW_KEY, "true" if enabled else "false")
    return {"enabled": enabled}


@router.get("/api/settings/vlm-model")
def get_vlm_model() -> dict:
    """返回当前视觉模型名称。"""
    model = database.get_setting(VLM_MODEL_KEY, "")
    if not model:
        from prompt_agent import vlm_model as resolve

        model = resolve()
    return {"model": model}


@router.post("/api/settings/vlm-model")
def set_vlm_model(payload: dict = Body(...)) -> dict:
    """切换视觉模型（默认 abliterated，可切回官方 qwen2.5vl 系列）。"""
    model = str(payload.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    database.set_setting(VLM_MODEL_KEY, model)
    return {"model": model}


@router.get("/api/settings/service-supervision")
def get_service_supervision() -> dict:
    """返回服务自启与健康探活配置。"""
    return services.supervision_status()


@router.post("/api/settings/service-supervision")
def set_service_supervision(payload: dict = Body(...)) -> dict:
    """保存服务自启与健康探活配置。"""
    try:
        services.update_supervision_settings(payload)
        return services.supervision_status()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/settings/auto-shutdown")
def get_auto_shutdown() -> dict:
    """返回任务完成后自动关机配置与当前状态。"""
    import auto_shutdown

    return auto_shutdown.status()


@router.post("/api/settings/auto-shutdown")
def set_auto_shutdown(payload: dict = Body(...)) -> dict:
    """保存任务完成后自动关机配置；关闭或改延迟会取消当前倒计时。"""
    import auto_shutdown

    try:
        return auto_shutdown.update_settings(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/settings/data-retention")
def get_data_retention() -> dict:
    """返回数据保留天数（0 表示永久保留）。"""
    try:
        days = max(
            config.SETTINGS_DATA_RETENTION_MIN,
            min(
                config.SETTINGS_DATA_RETENTION_MAX,
                int(
                    database.get_setting(
                        DATA_RETENTION_KEY,
                        str(config.SETTINGS_DATA_RETENTION_DEFAULT),
                    )
                    or config.SETTINGS_DATA_RETENTION_DEFAULT
                ),
            ),
        )
    except (TypeError, ValueError):
        days = config.SETTINGS_DATA_RETENTION_DEFAULT
    return {"days": days}


@router.post("/api/settings/data-retention")
def set_data_retention(payload: dict = Body(...)) -> dict:
    """保存数据保留天数（0 表示永久保留）。"""
    try:
        days = max(
            config.SETTINGS_DATA_RETENTION_MIN,
            min(
                config.SETTINGS_DATA_RETENTION_MAX,
                int(payload.get("days", config.SETTINGS_DATA_RETENTION_DEFAULT)),
            ),
        )
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="保留天数必须是整数") from None
    database.set_setting(DATA_RETENTION_KEY, str(days))
    return {"days": days}


def prompt_semantic_check_enabled() -> bool:
    """AI 语义校验开关，默认关闭（规则引擎不受影响）。"""
    return database.get_setting(PROMPT_SEMANTIC_CHECK_KEY, "false") == "true"


@router.get("/api/settings/prompt-semantic-check")
def get_prompt_semantic_check() -> dict:
    """返回提示词 AI 语义校验开关状态。"""
    return {"enabled": prompt_semantic_check_enabled()}


@router.post("/api/settings/prompt-semantic-check")
def set_prompt_semantic_check(payload: dict = Body(...)) -> dict:
    """开启或关闭提示词 AI 语义校验（默认关闭）。"""
    enabled = bool(payload.get("enabled", False))
    database.set_setting(PROMPT_SEMANTIC_CHECK_KEY, "true" if enabled else "false")
    return {"enabled": enabled}
