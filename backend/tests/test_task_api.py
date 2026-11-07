"""统一任务列表/忙碌接口测试（review/merge 纳入注册表后）。"""
from __future__ import annotations

import task_registry


def test_system_tasks_lists_and_filters_review_merge(client):
    task_registry.register("review", "review-api-1")
    task_registry.register("merge", "merge-api-1")
    try:
        response = client.get("/api/system/tasks")
        assert response.status_code == 200
        items = response.json()["items"]
        ids = {item["job_id"] for item in items}
        assert {"review-api-1", "merge-api-1"} <= ids
        by_id = {item["job_id"]: item for item in items}
        assert by_id["review-api-1"]["label"] == "数据集 AI 审查"
        assert by_id["merge-api-1"]["label"] == "LoRA 合并"

        merge_only = client.get("/api/system/tasks", params={"kind": "merge"}).json()["items"]
        assert [item["job_id"] for item in merge_only] == ["merge-api-1"]
    finally:
        task_registry.finish("review", "review-api-1", "done")
        task_registry.finish("merge", "merge-api-1", "done")


def test_system_busy_returns_review_and_merge_labels(client):
    task_registry.register("review", "review-busy-1")
    task_registry.register("merge", "merge-busy-1")
    try:
        response = client.get("/api/system/busy")
        assert response.status_code == 200
        payload = response.json()
        assert payload["busy"] is True
        labels = {item["label"] for item in payload["tasks"]}
        assert {"数据集 AI 审查", "LoRA 合并"} <= labels
    finally:
        task_registry.finish("review", "review-busy-1", "done")
        task_registry.finish("merge", "merge-busy-1", "done")


def test_system_tasks_includes_done_history_after_finish(client):
    task_registry.register("merge", "merge-history-1")
    task_registry.finish("merge", "merge-history-1", "done", None)
    response = client.get("/api/system/tasks", params={"status": "done"})
    assert response.status_code == 200
    done_ids = [item["job_id"] for item in response.json()["items"]]
    assert "merge-history-1" in done_ids
