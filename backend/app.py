"""FastAPI 后端入口：装配路由、CORS 和数据库初始化。"""
from __future__ import annotations

import sys

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config

# 把知识库和 Agent 目录加入模块搜索路径
ROOT = config.PROJECT_ROOT
for path in (str(ROOT / "rag_knowledge_base"), str(ROOT / "agent")):
    if path not in sys.path:
        sys.path.insert(0, path)

import database  # noqa: E402
import llm  # noqa: E402
import preset_asset_pipeline  # noqa: E402
import preset_asset_service  # noqa: E402
import services  # noqa: E402
import task_registry  # noqa: E402
import task_resources  # noqa: E402
from routers import chat, companion, draw, preset_assets, prompt, prompt_sets, records, resources, services_router, settings_router, train, video  # noqa: E402
from game_assistant import account_router as game_assistant_account_router  # noqa: E402
from game_assistant import combat_router as game_assistant_combat_router  # noqa: E402
from game_assistant import execution_router as game_assistant_execution_router  # noqa: E402
from game_assistant import router as game_assistant_router  # noqa: E402

app = FastAPI(title="AI工作台 API", version="1.0.0")


@app.exception_handler(task_resources.ResourceConflictError)
async def task_resource_conflict_handler(
    _request: Request,
    exc: task_resources.ResourceConflictError,
) -> JSONResponse:
    """Return a stable 409 response when requested task resources are busy."""
    return JSONResponse(
        status_code=409,
        content={"detail": task_resources.conflict_message(exc), "conflicts": exc.conflicts},
    )


@app.exception_handler(preset_asset_service.PresetAssetError)
async def preset_asset_error_handler(
    _request: Request,
    exc: preset_asset_service.PresetAssetError,
) -> JSONResponse:
    """Map workshop domain errors to stable HTTP responses."""
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

# 允许前端开发服务器跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    """启动时创建数据库表和索引。"""
    database.init_db()
    preset_asset_service.recover_pending_write_journals()
    draw.restore_batch_jobs()
    task_registry.restore_interrupted()
    preset_asset_pipeline.restore_pending_jobs()
    video.restore_video_jobs()
    companion.seed_presets()
    import auto_shutdown

    auto_shutdown.start_watcher()
    services.start_supervisor()
    services.auto_start_services()


@app.get("/health")
def health() -> dict:
    """健康检查：返回服务状态和当前大模型。"""
    return {
        "ok": True,
        "services": services.status(),
        "model": llm.MODEL,
    }


# 注册各业务模块路由
app.include_router(chat.router)
app.include_router(draw.router)
app.include_router(prompt.router)
app.include_router(records.router)
app.include_router(services_router.router)
app.include_router(settings_router.router)
app.include_router(train.router)
app.include_router(prompt_sets.router)
app.include_router(companion.router)
app.include_router(resources.router)
app.include_router(video.router)
app.include_router(preset_assets.router)
app.include_router(game_assistant_router.router)
app.include_router(game_assistant_account_router.router)
app.include_router(game_assistant_combat_router.router)
app.include_router(game_assistant_execution_router.router)
