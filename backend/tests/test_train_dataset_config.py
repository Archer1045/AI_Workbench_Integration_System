"""dataset_config.toml 生成逻辑回归测试。

背景（2026-10-11 BUG-1）：写配置文件时 bucket/keep_tokens/shuffle_caption 曾被写成字面量，
面板上的 Keep Tokens、Bucket 最小/最大分辨率、Bucket 步长、Shuffle Caption 因此静默失效。
"""
from __future__ import annotations

from pathlib import Path

from routers.train import _dataset_config_text


def test_dataset_config_uses_payload_values(tmp_path: Path) -> None:
    text = _dataset_config_text(
        resolution=1024,
        batch_size=1,
        repeats=10,
        shuffle_caption=True,
        keep_tokens=3,
        bucket_min_reso=768,
        bucket_max_reso=1280,
        bucket_reso_steps=32,
        image_dir=tmp_path,
    )
    assert "shuffle_caption = true" in text
    assert "keep_tokens = 3" in text
    assert "min_bucket_reso = 768" in text
    assert "max_bucket_reso = 1280" in text
    assert "bucket_reso_steps = 32" in text
    assert "resolution = 1024" in text
    assert "batch_size = 1" in text
    assert "num_repeats = 10" in text
    # 旧的写死值不应残留
    assert "min_bucket_reso = 512" not in text
    assert "bucket_reso_steps = 64" not in text


def test_dataset_config_defaults_and_path_separator(tmp_path: Path) -> None:
    text = _dataset_config_text(
        resolution=768,
        batch_size=2,
        repeats=5,
        shuffle_caption=False,
        keep_tokens=1,
        bucket_min_reso=512,
        bucket_max_reso=1536,
        bucket_reso_steps=64,
        image_dir=tmp_path,
    )
    assert "shuffle_caption = false" in text
    assert "keep_tokens = 1" in text
    assert "min_bucket_reso = 512" in text
    assert "max_bucket_reso = 1536" in text
    assert "bucket_reso_steps = 64" in text
    # 图片目录必须转成正斜杠，避免 kohya 解析 TOML 时出问题
    assert "\\" not in text
