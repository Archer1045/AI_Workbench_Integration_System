"""统一 GPU/重任务忙碌状态判断（基于 task_registry）。"""
from __future__ import annotations

TASK_LABELS = {
    "draw": "AI 绘画",
    "train": "LoRA 训练",
    "caption": "批量打标",
    "compare": "检查点对比出图",
    "review": "数据集 AI 审查",
    "merge": "LoRA 合并",
    "video": "AI 视频",
    "video_long": "长视频分段",
    "dataset_write": "数据集标签写入",
    "prompt_llm": "提示词 LLM",
    "prompt_vlm": "提示词视觉反推",
    "prompt_wd14": "提示词 WD14 反推",
    "companion_text": "陪伴聊天",
    "companion_vision": "陪伴图片识别",
    "preset_asset": "预设缩略图",
    "game_assistant_run": "游戏助手任务",
    "game_assistant_crawl": "游戏资料抓取",
    "game_assistant_plan": "游戏计划",
    "game_assistant_vlm": "游戏视觉识别",
}


def running_tasks() -> list[dict]:
    """返回当前运行中的重任务列表（统一注册表）。"""
    import task_registry  # noqa: PLC0415

    tasks = []
    seen: set[str] = set()
    for task in task_registry.running_tasks():
        kind = str(task.get("type") or "")
        if kind in seen:
            continue
        seen.add(kind)
        tasks.append({"type": kind, "label": TASK_LABELS.get(kind, kind), "job_id": task.get("job_id"), "resources": task.get("resources") or []})
    return tasks
