from __future__ import annotations

from routers.companion import _search_error_message, _should_search, _wants_details
from web_tools import WebToolsError


def test_realtime_hint_triggers_search_without_model() -> None:
    need_search, query = _should_search("今天北京的天气怎么样？")
    assert need_search is True
    assert query == "今天北京的天气怎么样？"


def test_casual_chat_does_not_use_realtime_hint() -> None:
    assert "天气" not in "今天有点累，陪我聊两句吧。"
    assert _wants_details("今天有点累，陪我聊两句吧。") is False


def test_detail_hint_detects_sources() -> None:
    assert _wants_details("请详细说明并给出来源链接") is True


def test_search_error_messages_are_actionable() -> None:
    assert "Key" in _search_error_message(WebToolsError("x", status_code=401))
    assert "余额" in _search_error_message(WebToolsError("x", status_code=402))
    assert "限流" in _search_error_message(WebToolsError("x", status_code=429))
