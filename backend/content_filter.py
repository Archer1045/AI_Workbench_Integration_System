"""内容限制：未成年相关内容始终拦截，其他敏感内容按开关控制。"""
from __future__ import annotations

# 无论开关状态都必须拦截的内容（涉及未成年人）
ALWAYS_BLOCKED = [
    "儿童色情",
    "儿童性",
    "幼女",
    "幼男",
    "未成年",
    "萝莉",
    "正太",
    "loli",
    "shotacon",
    "underage",
    "minor",
]

# 内容限制开关开启时需要拦截的成人向关键词
NSFW_KEYWORDS = [
    "nsfw",
    "explicit",
    "hentai",
    "r18",
    "18禁",
    "nude",
    "naked",
    "nipples",
    "areola",
    "breasts",
    "penis",
    "vagina",
    "pussy",
    "sex",
    "sexual",
    "intercourse",
    "masturbat",
    "orgasm",
    "porn",
    "裸体",
    "乳头",
    "乳晕",
    "乳房",
    "生殖器",
    "性交",
    "口交",
    "肛交",
    "自慰",
    "高潮",
    "勃起",
    "阴道",
    "阴茎",
    "射精",
    "色情",
]


def is_always_blocked(text: str) -> bool:
    """检测是否包含必须拦截的未成年相关内容。"""
    lower = text.lower()
    return any(keyword in lower for keyword in ALWAYS_BLOCKED)


def is_nsfw(text: str) -> bool:
    """检测是否包含成人向敏感内容。"""
    lower = text.lower()
    return any(keyword in lower for keyword in NSFW_KEYWORDS)
