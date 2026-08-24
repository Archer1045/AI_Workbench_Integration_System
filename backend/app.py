"""FastAPI 后端入口：装配路由、CORS 和数据库初始化。"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 把知识库和 Agent 目录加入模块搜索路径
ROOT = Path(__file__).resolve().parents[2]
for path in (str(ROOT / "rag_knowledge_base"), str(ROOT / "agent")):
    if path not in sys.path:
        sys.path.insert(0, path)

import database  # noqa: E402
import llm  # noqa: E402
import services  # noqa: E402
from routers import chat, draw, prompt, records, services_router, settings_router  # noqa: E402

app = FastAPI(title="骑手招聘助手 AI 工作台 API", version="1.0.0")

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
