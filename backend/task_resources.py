"""统一任务资源定义与租约管理。"""
from __future__ import annotations

import time
import uuid

import database
import task_activity

PROCESS_OWNER_TOKEN = uuid.uuid4().hex
LEASE_TTL_SECONDS = 120.0

RESOURCE_DEFINITIONS = {
    "gpu": {"label": "GPU", "mode": "exclusive", "description": "GPU/显存独占资源"},
    "comfyui": {"label": "ComfyUI", "mode": "exclusive", "description": "ComfyUI 工作流执行资源"},
    "ollama": {"label": "Ollama", "mode": "shared", "description": "Ollama 推理服务"},
    "vlm": {"label": "本地 VLM", "mode": "exclusive", "description": "本地视觉模型"},
    "emulator": {"label": "模拟器", "mode": "exclusive", "description": "游戏模拟器实例"},
    "adb": {"label": "ADB", "mode": "exclusive", "description": "ADB 设备控制通道"},
}

TASK_RESOURCE_POLICIES = {
    "draw": (("gpu", "exclusive"), ("comfyui", "exclusive")),
    "train": (("gpu", "exclusive"),),
    "caption": (("gpu", "exclusive"), ("ollama", "shared")),
    "compare": (("gpu", "exclusive"), ("comfyui", "exclusive")),
    "review": (("gpu", "exclusive"), ("ollama", "shared"), ("vlm", "exclusive")),
    "merge": (),
    "video": (("gpu", "exclusive"), ("comfyui", "exclusive")),
    "preset_asset": (("gpu", "exclusive"), ("comfyui", "exclusive")),
    "game_assistant_run": (("emulator", "exclusive"), ("adb", "exclusive")),
    "game_assistant_crawl": (),
    "game_assistant_plan": (("ollama", "shared"),),
    "game_assistant_vlm": (("gpu", "exclusive"), ("vlm", "exclusive")),
}

ResourceConflictError = database.ResourceConflictError


def normalize_resources(resources: list[dict | str] | None) -> list[dict]:
    """规范化资源声明并按资源键排序。"""
    normalized: dict[str, dict] = {}
    for raw in resources or []:
        if isinstance(raw, str):
            key = raw
            mode = ""
        elif isinstance(raw, dict):
            key = str(raw.get("key") or "")
            mode = str(raw.get("mode") or "")
        else:
            raise ValueError(f"无效资源声明：{raw!r}")
        if key not in RESOURCE_DEFINITIONS:
            raise ValueError(f"未知资源：{key}")
        definition = RESOURCE_DEFINITIONS[key]
        resolved_mode = mode or str(definition["mode"])
        if resolved_mode not in {"exclusive", "shared"}:
            raise ValueError(f"无效资源模式：{resolved_mode}")
        normalized[key] = {"key": key, "mode": resolved_mode}
    return [normalized[key] for key in sorted(normalized)]


def for_kind(kind: str) -> list[dict]:
    """返回任务类型的默认资源声明。"""
    return normalize_resources(
        [{"key": key, "mode": mode} for key, mode in TASK_RESOURCE_POLICIES.get(kind, ())]
    )


def claim_resources(
    job_id: str,
    kind: str,
    resources: list[dict | str] | None,
    *,
    owner_token: str = PROCESS_OWNER_TOKEN,
    ttl_seconds: float = LEASE_TTL_SECONDS,
) -> list[dict]:
    """原子获取任务资源；冲突时抛出 ResourceConflictError。"""
    normalized = normalize_resources(resources)
    if not normalized:
        return []
    try:
        claims = database.acquire_task_resource_claims(
            job_id,
            kind,
            normalized,
            owner_token=owner_token,
            ttl_seconds=ttl_seconds,
        )
    except database.ResourceConflictError as exc:
        task_activity.record(
            "resource.conflict",
            module="system",
            job_id=job_id,
            kind=kind,
            severity="warning",
            summary="任务资源冲突",
            payload={"resources": normalized, "conflicts": exc.conflicts},
        )
        raise
    task_activity.record(
        "resource.acquired",
        module="system",
        job_id=job_id,
        kind=kind,
        summary="任务资源已获取",
        payload={"resources": [{"key": item["resource_key"], "mode": item["mode"]} for item in claims]},
    )
    return claims


def renew_resources(
    job_id: str,
    *,
    owner_token: str = PROCESS_OWNER_TOKEN,
    ttl_seconds: float = LEASE_TTL_SECONDS,
) -> int:
    return database.renew_task_resource_claims(
        job_id,
        owner_token=owner_token,
        ttl_seconds=ttl_seconds,
    )


def release_resources(
    job_id: str,
    *,
    owner_token: str | None = None,
    reason: str = "task_finished",
) -> int:
    released = database.release_task_resource_claims(
        job_id,
        owner_token=owner_token,
        reason=reason,
    )
    if released:
        task_activity.record(
            "resource.released",
            module="system",
            job_id=job_id,
            summary="任务资源已释放",
            payload={"count": released, "reason": reason},
        )
    return released


def list_job_claims(job_id: str, *, active_only: bool = True) -> list[dict]:
    return database.list_task_resource_claims(job_id=job_id, active_only=active_only)


def snapshot() -> dict:
    """返回资源定义、当前活动租约和可用性快照。"""
    active = database.list_active_task_resource_claims()
    by_key: dict[str, list[dict]] = {key: [] for key in RESOURCE_DEFINITIONS}
    for claim in active:
        by_key.setdefault(str(claim["resource_key"]), []).append(claim)
    resources = []
    for key, definition in RESOURCE_DEFINITIONS.items():
        claims = by_key.get(key, [])
        exclusive_claim = any(item.get("mode") == "exclusive" for item in claims)
        default_exclusive = definition["mode"] == "exclusive"
        available = not exclusive_claim if not default_exclusive else not claims
        resources.append(
            {
                "key": key,
                "label": definition["label"],
                "description": definition["description"],
                "mode": definition["mode"],
                "available": available,
                "busy": bool(claims),
                "claims": claims,
            }
        )
    return {"resources": resources, "claims": active}


def conflict_message(exc: ResourceConflictError) -> str:
    keys = []
    holders: list[tuple[str, int | None]] = []
    for item in exc.conflicts:
        key = str(item.get("resource_key") or "")
        keys.append(RESOURCE_DEFINITIONS.get(key, {}).get("label", key or "未知资源"))
        for claim in item.get("claims") or []:
            job_id = str(claim.get("job_id") or "").strip()
            expires_at = claim.get("expires_at")
            remaining = None
            if isinstance(expires_at, (int, float)):
                remaining = max(0, int(float(expires_at) - time.time()))
            if job_id:
                holders.append((job_id, remaining))
    joined = "、".join(dict.fromkeys(keys)) or "未知资源"
    detail = ""
    if holders:
        job_id, remaining = holders[0]
        detail = f"：当前被 {job_id} 占用"
        if remaining is not None:
            detail += f"，租约最迟约 {remaining} 秒后过期"
        detail += "。若那是已停止的旧运行，请稍等租约过期后再试"
    else:
        detail = "，请等待当前任务释放资源后再试"
    return f"资源冲突（{joined}）{detail}"
