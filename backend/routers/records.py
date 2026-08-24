"""数据看板查询与 Excel 导出接口。"""
from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, HTTPException, Query, Response
from openpyxl import Workbook

import database

router = APIRouter()

# 导出 Excel 时的中文字段名
HEADER_MAP = {
    "agent": {
        "id": "ID",
        "session_id": "会话ID",
        "created_at": "对话时间",
        "sender": "发送人",
        "content": "对话内容",
        "retrieval_score": "检索匹配度",
        "source": "来源",
    },
    "draw": {
        "id": "ID",
        "batch_id": "批次ID",
        "group_index": "组号",
        "started_at": "任务开始时间",
        "finished_at": "任务结束时间",
        "duration_seconds": "任务耗时(秒)",
        "prompt": "提示词",
        "prompt_translation": "提示词翻译",
        "negative_prompt": "负面提示词",
        "negative_translation": "负面提示词翻译",
        "width": "宽度",
        "height": "高度",
        "steps": "步数",
        "cfg": "CFG",
        "model": "模型",
        "lora_anima_turbo": "anima-turbo-lora-v0.2",
        "lora_high_contrast": "high-contrast aesthetic",
        "image_path": "图片路径",
        "image_url": "图片地址",
        "seed": "随机种子",
        "status": "状态",
        "error": "错误信息",
    },
    "prompt": {
        "id": "ID",
        "started_at": "任务开始时间",
        "finished_at": "任务结束时间",
        "duration_seconds": "任务耗时(秒)",
        "mode": "模式",
        "user_input": "用户输入",
        "image_path": "图片路径",
        "description": "原始描述",
        "prompt_result": "生成提示词",
        "model": "模型",
        "status": "状态",
    },
}


def build_excel(kind: str, rows: list[dict]) -> bytes:
    """把记录行写入 Excel 工作簿并返回字节。"""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = kind
    if rows:
        keys = list(rows[0].keys())
        headers = [HEADER_MAP.get(kind, {}).get(key, key) for key in keys]
        worksheet.append(headers)
        for row in rows:
            worksheet.append([row.get(key, "") for key in keys])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@router.get("/api/records")
def records(
    kind: str = Query("agent"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    page: int = Query(1),
    page_size: int = Query(10),
) -> dict:
    """按类型、日期范围分页查询记录。"""
    if kind not in database.available_kinds():
        raise HTTPException(status_code=404, detail="unknown kind")
    return database.query_records(kind, date_from, date_to, page, page_size)


@router.get("/api/export/{kind}")
def export(kind: str, date_from: str | None = None, date_to: str | None = None) -> Response:
    """导出 Excel 文件。"""
    if kind not in database.available_kinds():
        raise HTTPException(status_code=404, detail="unknown kind")
    data = build_excel(kind, database.export_records(kind, date_from, date_to))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{kind}_records.xlsx"'},
    )
