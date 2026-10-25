"""内容限制：未成年相关内容始终拦截，其他敏感内容按开关控制。"""
from __future__ import annotations

import re

# 无论开关状态都必须拦截的内容（涉及未成年人）
ALWAYS_BLOCKED = [
    "儿童色情",
    "儿童性",
    "儿童",
    "幼女",
    "幼児",
    "幼态",
    "未成年",
    "未成年者",
    "18歳未満",
    "小学生",
    "中学生",
    "高校生",
    "萝莉",
    "ロリ",
    "loli",
    "jailbait",
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

# 无论内容限制开关状态都必须拦截的非虚构动物互动内容
HARD_BLOCKED_KEYWORDS = [
    "兽交",
    "兽类性",
    "bestiality",
    "beastiality",
    "zoophilia",
    "animal sex",
    "animal intercourse",
]


def _contains_keyword(text: str, keyword: str) -> bool:
    """Match English tokens/phrases as words, not as substrings of fashion terms."""
    if not keyword.isascii():
        return keyword in text
    normalized = re.sub(r"[_-]+", " ", text.lower())
    pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
    return re.search(pattern, normalized) is not None


def is_always_blocked(text: str) -> bool:
    """检测是否包含必须拦截的未成年相关内容。"""
    lower = text.lower()
    return any(_contains_keyword(lower, keyword) for keyword in ALWAYS_BLOCKED)


def is_hard_blocked(text: str) -> bool:
    """检测必须始终拦截的内容：未成年人及非虚构动物互动。"""
    lower = text.lower()
    return is_always_blocked(text) or any(
        _contains_keyword(lower, keyword) for keyword in HARD_BLOCKED_KEYWORDS
    )


def is_nsfw(text: str) -> bool:
    """检测是否包含成人向敏感内容。"""
    lower = text.lower()
    return any(keyword in lower for keyword in NSFW_KEYWORDS)
