"""B 方案：按优先级裁剪提示词到 token 预算内。

设计：
- 每个 fragment 带优先级（P0 必留 / P1 尽量留 / P2 可丢）
- 按优先级顺序填入，超过预算就停止
- fragment 内部的 tag 也去重

token 估算用 CLIP 的经验值：约 1.3 字符 = 1 token（英文），中文按 1 字 = 1.5 token。
保守起见，用「逗号分隔的 tag 数」作为近似（CLIP 对每个 tag 约 1.5-2 token）。
"""

from __future__ import annotations

import re

# CLIP 名义上限 77 token，但 ComfyUI 的实现支持自动分块（chunking），
# 长文本会被分块编码后拼接，不是硬失败。
# 取 120 作为「合理上限」：
#   - 低于 120：不裁剪（双人 + 两套服装约 79 token，正常）
#   - 高于 120：触发裁剪，因为分块过多会稀释语义
DEFAULT_BUDGET = 120

# 每个 tag 的平均 token 估算（英文短语约 2 token，单词约 1 token）
_TAG_TOKEN_AVG = 2.0

# 优先级常量
P0 = 0   # 必留：角色顺序、核心姿势、身体分离约束
P1 = 1   # 尽量留：场景、 erste 服装
P2 = 2   # 可丢：其他服装、改造、玩具、扩张


def estimate_tokens(text: str) -> int:
    """粗估一段文本的 token 数。

    规则：
    - 英文按空格分词，每词约 1.3 token
    - 中文每字约 1.5 token
    - 标点忽略
    """
    if not text:
        return 0
    # 统计中文字符
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    # 英文单词（去掉中文后的字母序列）
    english_text = re.sub(r"[\u4e00-\u9fff]", " ", text)
    words = len(re.findall(r"[A-Za-z][A-Za-z0-9_-]*", english_text))
    return int(chinese * 1.5 + words * 1.3) + 1


def _split_tags(fragment: str) -> list[str]:
    """把 fragment 按逗号拆成 tag 列表，保留「for xxx:」前缀语义。"""
    parts = [p.strip() for p in fragment.split(",") if p.strip()]
    return parts


def _strip_role_prefix(tag: str) -> tuple[str, str]:
    """拆分「for the first girl (女A): xxx」为 (prefix, body)。"""
    m = re.match(r"^(for [^:]+:\s*)(.*)$", tag)
    if m:
        return m.group(1), m.group(2)
    return "", tag


def trim_fragments(
    fragments: list[tuple[int, str]],
    budget: int = DEFAULT_BUDGET,
) -> tuple[str, list[str]]:
    """按优先级裁剪 fragments，返回 (最终 prompt, 被丢弃的 tag 列表)。

    fragments: [(priority, fragment_text), ...]
    """
    # 1. 按优先级稳定排序（P0 在前，同优先级保持原顺序）
    ordered = sorted(fragments, key=lambda x: x[0])

    kept: list[str] = []
    dropped: list[str] = []
    seen_fragments: set[str] = set()
    used_tokens = 0

    for _priority, fragment in ordered:
        fragment = fragment.strip()
        if not fragment:
            continue

        # fragment 级去重（按小写全文比较）
        key = fragment.lower()
        if key in seen_fragments:
            continue

        fragment_tokens = estimate_tokens(fragment)
        if used_tokens + fragment_tokens > budget:
            dropped.append(fragment)
            continue

        kept.append(fragment)
        seen_fragments.add(key)
        used_tokens += fragment_tokens

    return ", ".join(kept), dropped
