"""提示词校验纯逻辑单元测试，不依赖外部服务。"""
from __future__ import annotations

import prompt_checker


def _kinds(payload: dict) -> dict:
    return {key: [item["type"] for item in value] for key, value in payload.items()}


def test_duplicate_tag_warns():
    result = prompt_checker.validate_prompt("1girl, 1girl")
    assert "warning" in _kinds(result)["warnings"]


def test_same_gender_count_conflict_errors():
    result = prompt_checker.validate_prompt("1girl, 2girls")
    assert "error" in _kinds(result)["errors"]


def test_solo_with_multi_errors():
    result = prompt_checker.validate_prompt("solo, 1girl, 1boy")
    assert "error" in _kinds(result)["errors"]


def test_multi_hint_conflicts_with_one():
    result = prompt_checker.validate_prompt("1girl, clone")
    assert "error" in _kinds(result)["errors"]


def test_conflict_rule_warns():
    result = prompt_checker.validate_prompt("white dress, black dress")
    assert "warning" in _kinds(result)["warnings"]


def test_unbalanced_parentheses_errors():
    result = prompt_checker.validate_prompt("(masterpiece")
    assert "error" in _kinds(result)["errors"]


def test_clean_prompt_no_errors():
    result = prompt_checker.validate_prompt("1girl, masterpiece, best quality")
    assert result["errors"] == []
    assert result["warnings"] == []


def test_mixed_gender_counts_no_conflict():
    result = prompt_checker.validate_prompt("1girl, 1boy, masterpiece")
    assert result["errors"] == []


def test_weighted_parentheses_ok():
    result = prompt_checker.validate_prompt("(masterpiece:1.2), 1girl, best quality")
    assert result["errors"] == []
    assert result["warnings"] == []


def test_negative_prompt_does_not_break_local_checks():
    result = prompt_checker.validate_prompt("1girl, masterpiece", "")
    assert result["errors"] == []


def test_multi_hint_with_multiple_people_allowed():
    result = prompt_checker.validate_prompt("1girl, 1boy, clone, masterpiece")
    assert result["errors"] == []
