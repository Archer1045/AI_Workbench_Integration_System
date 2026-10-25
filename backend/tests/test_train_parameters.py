from __future__ import annotations

import time
from pathlib import Path

from routers import train
from routers.train import _output_name_conflicts, _plain_decimal, _suggest_output_name


def _touch(directory: Path, *names: str) -> None:
    for name in names:
        (directory / name).write_bytes(b"")


def test_plain_decimal_never_uses_scientific_notation() -> None:
    assert _plain_decimal(0.0001) == "0.0001"
    assert _plain_decimal(0.00005) == "0.00005"
    assert _plain_decimal(0.0000001) == "0.0000001"
    assert _plain_decimal(1.0) == "1"
    assert "e" not in _plain_decimal(0.0000001).lower()
    assert "e" not in _plain_decimal(0.00005).lower()


def test_output_name_conflicts_covers_same_name_family(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(train, "OUTPUT_DIR", tmp_path)
    _touch(
        tmp_path,
        "my_dania_v1.safetensors",
        "my_dania_v1-000001.safetensors",
        "my_dania_v1_comfy.safetensors",
        "my_dania_v1-000001_comfy.safetensors",
        "my_dania_v10.safetensors",
        "my_dania_v1_backup.safetensors",
        "other_lora.safetensors",
    )
    assert _output_name_conflicts("my_dania_v1") == [
        "my_dania_v1-000001.safetensors",
        "my_dania_v1-000001_comfy.safetensors",
        "my_dania_v1.safetensors",
        "my_dania_v1_comfy.safetensors",
    ]
    # 仅前缀相同的其他 LoRA 不应算冲突。
    assert _output_name_conflicts("my_dania_v10") == ["my_dania_v10.safetensors"]
    assert _output_name_conflicts("my_dania_v1_backup") == ["my_dania_v1_backup.safetensors"]
    assert _output_name_conflicts("unused_name") == []
    assert _output_name_conflicts("") == []


def test_suggest_output_name_skips_existing_suggestions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(train, "OUTPUT_DIR", tmp_path)
    stamp = time.strftime("%Y%m%d")
    _touch(
        tmp_path,
        "my_style_v1.safetensors",
        f"my_style_v1_{stamp}.safetensors",
        f"my_style_v1_{stamp}_comfy.safetensors",
    )
    suggested = _suggest_output_name("my_style_v1")
    assert suggested == f"my_style_v1_{stamp}_2"
    assert _output_name_conflicts(suggested) == []


def test_check_output_name_endpoint_reports_conflicts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(train, "OUTPUT_DIR", tmp_path)
    _touch(tmp_path, "my_dania_v1.safetensors", "my_dania_v1-000002_comfy.safetensors")
    result = train.check_output_name("my_dania_v1")
    assert result["output_name"] == "my_dania_v1"
    assert result["conflicts"] == ["my_dania_v1-000002_comfy.safetensors", "my_dania_v1.safetensors"]
    assert result["suggested_name"].startswith("my_dania_v1_")
    assert _output_name_conflicts(result["suggested_name"]) == []
    # 无冲突时不给出建议名称。
    assert train.check_output_name("brand_new_lora") == {
        "output_name": "brand_new_lora",
        "conflicts": [],
        "suggested_name": "",
    }
