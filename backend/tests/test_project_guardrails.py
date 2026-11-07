"""项目护栏测试：防止"已明确降级的自研控制层"被悄悄重建。

背景（2026-10-10 事故）：decisions.md 明确写着「执行层优先 FGO-py，自研仅在 POC
失败且用户同意后才考虑」，但当时的会话没查 decisions.md，直接手搓了一套控制脚本
（手量坐标 + adb 点击），随后连续出错。因此用**测试**把这条规则钉死：
控制层原语只允许出现在白名单文件里，且白名单文件必须带 `# LAYER: control` 标记。
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
GAME_ASSISTANT = BACKEND / "game_assistant"

# 允许出现控制层原语的文件（冻结名单；新增/删除都要显式改这里并写进 decisions）
CONTROL_LAYER_ALLOWLIST = {
    "battle_executor.py",  # 冻结中的自研执行器，待 FGO-py 接管
}

# 控制层原语：直接驱动设备/输入的关键字
CONTROL_PATTERNS = (
    re.compile(r"\badb\b", re.IGNORECASE),
    re.compile(r"input\s+-d\s"),
    re.compile(r"\bscreencap\b", re.IGNORECASE),
)
# 只有"真的在驱动设备"才算：文件里同时出现外部进程调用。
# 纯文字提到 adb（例如执行前检查清单 execution_preflight.py）不算违规。
DRIVER_PATTERNS = (
    re.compile(r"\bsubprocess\b"),
    re.compile(r"\bPopen\b"),
    re.compile(r"os\.system"),
)


def _control_hits(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not any(pattern.search(text) for pattern in DRIVER_PATTERNS):
        return []
    return [pattern.pattern for pattern in CONTROL_PATTERNS if pattern.search(text)]


def test_control_primitives_only_in_allowlisted_files() -> None:
    offenders: dict[str, list[str]] = {}
    for path in GAME_ASSISTANT.rglob("*.py"):
        if path.name in CONTROL_LAYER_ALLOWLIST:
            continue
        hits = _control_hits(path)
        if hits:
            offenders[path.name] = hits
    assert not offenders, (
        "以下文件出现了控制层原语（adb/input/screencap），但不在白名单里："
        f"{offenders}。按 decisions.md，执行层必须走 FGO-py；"
        "如确需自研，请先取得用户同意并更新白名单与 decisions。"
    )


def test_allowlisted_control_files_are_labelled_and_frozen() -> None:
    for name in CONTROL_LAYER_ALLOWLIST:
        path = GAME_ASSISTANT / name
        assert path.exists(), f"白名单文件不存在：{name}（清理白名单）"
        head = path.read_text(encoding="utf-8", errors="ignore")[:600]
        assert "# LAYER: control" in head, f"{name} 缺少 `# LAYER: control` 标记"
        assert "冻结" in head, f"{name} 必须写明「已冻结」及原因（待 FGO-py 接管）"


def test_binding_rules_are_recorded_in_decisions() -> None:
    decisions = BACKEND.parent.parent / ".agent-handoff" / "decisions.md"
    if not decisions.exists():
        return  # 非本仓库布局时跳过
    text = decisions.read_text(encoding="utf-8", errors="ignore")
    assert "FGO-py first" in text or "执行层必须走 FGO-py" in text, (
        "decisions.md 必须记录「执行层走 FGO-py」这条绑定规则"
    )
