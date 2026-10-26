"""Focused coverage for the local Xiaofanqie/Gilbert image transform."""
from __future__ import annotations

import base64
import io
import json

import numpy as np
import pytest
from PIL import Image

import config
import image_deobfuscation as image_tool
from routers import image_tools


def _smooth_array(width: int, height: int, *, alpha: bool = False) -> np.ndarray:
    y, x = np.indices((height, width))
    channels = [
        (x * 2 + y) % 256,
        (x + y * 2) % 256,
        (x * 3 + y * 5) % 256,
    ]
    if alpha:
        channels.append((x + y * 7) % 256)
    return np.stack(channels, axis=2).astype(np.uint8)


def _png_bytes(image: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="PNG")
    return buffer.getvalue()


def _decode_bytes(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return np.asarray(image)


def _report_from_response(response) -> dict:
    encoded = response.headers["x-image-tool-report"]
    padded = encoded + "=" * (-len(encoded) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def test_curve_golden_sequences_and_offsets() -> None:
    assert image_tool.curve_indices(3, 3).tolist() == [0, 3, 6, 7, 8, 5, 4, 1, 2]
    assert image_tool.curve_indices(4, 5).tolist() == [
        0,
        4,
        5,
        1,
        2,
        3,
        7,
        6,
        10,
        11,
        15,
        19,
        18,
        14,
        17,
        13,
        9,
        8,
        12,
        16,
    ]
    assert image_tool.curve_offset(12) == 7
    assert image_tool.curve_offset(720 * 1145) == 509507


@pytest.mark.parametrize(
    ("width", "height"),
    [(1, 1), (2, 2), (3, 2), (2, 3), (31, 3), (3, 31), (97, 61), (61, 97)],
)
def test_curve_is_a_complete_permutation(width: int, height: int) -> None:
    indices = image_tool.curve_indices(width, height)
    assert sorted(indices.tolist()) == list(range(width * height))


@pytest.mark.parametrize(
    ("width", "height"),
    [(1, 1), (2, 2), (127, 64), (64, 127), (31, 3), (3, 31)],
)
@pytest.mark.parametrize("alpha", [False, True])
def test_array_encode_decode_is_lossless(width: int, height: int, alpha: bool) -> None:
    source = _smooth_array(width, height, alpha=alpha)
    encoded = image_tool.transform_array(source, "encode")
    decoded = image_tool.transform_array(encoded, "decode")
    np.testing.assert_array_equal(decoded, source)
    if width * height > 1:
        assert not np.array_equal(encoded, source)


def test_synthetic_scrambled_png_is_decoded_and_accepted() -> None:
    source = _smooth_array(128, 96, alpha=True)
    scrambled = image_tool.transform_array(source, "encode")
    result = image_tool.decode_image(_png_bytes(scrambled))

    assert result.accepted is True
    assert result.roughness_after < result.roughness_before
    np.testing.assert_array_equal(_decode_bytes(result.image_bytes), source)
    assert result.report["mode"] == "RGBA"
    assert result.report["source_format"] == "PNG"


def test_jpeg_input_is_supported_and_reported() -> None:
    source = _smooth_array(128, 96)
    scrambled = image_tool.transform_array(source, "encode")
    buffer = io.BytesIO()
    Image.fromarray(scrambled).save(buffer, format="JPEG", quality=95)

    result = image_tool.decode_image(buffer.getvalue())

    assert result.report["source_format"] == "JPEG"
    assert result.report["mode"] == "RGB"
    assert result.image_bytes.startswith(b"\x89PNG\r\n\x1a\n")


def test_untouched_image_is_rejected_unless_forced() -> None:
    source = _png_bytes(_smooth_array(128, 96))
    with pytest.raises(image_tool.ImageDeobfuscationError) as error:
        image_tool.decode_image(source)
    assert error.value.status_code == 422
    assert "可能不是小番茄混淆图" in str(error.value)

    forced = image_tool.decode_image(source, force=True)
    assert forced.accepted is False
    assert forced.report["forced"] is True
    assert forced.image_bytes.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("data", [b"", b"definitely not an image"])
def test_invalid_image_is_rejected(data: bytes) -> None:
    with pytest.raises(image_tool.ImageDeobfuscationError) as error:
        image_tool.decode_image(data)
    assert error.value.status_code in {400, 422}


def test_file_size_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _png_bytes(_smooth_array(8, 8))
    monkeypatch.setattr(config, "IMAGE_DEOBFUSCATION_MAX_BYTES", len(data) - 1)
    with pytest.raises(image_tool.ImageDeobfuscationError) as error:
        image_tool.decode_image(data)
    assert error.value.status_code == 413


def test_pixel_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _png_bytes(_smooth_array(32, 24))
    monkeypatch.setattr(config, "IMAGE_DEOBFUSCATION_MAX_PIXELS", 32 * 24 - 1)
    with pytest.raises(image_tool.ImageDeobfuscationError) as error:
        image_tool.decode_image(data)
    assert error.value.status_code == 413


def test_api_returns_png_with_metadata_header(client) -> None:
    source = _smooth_array(128, 96, alpha=True)
    scrambled = _png_bytes(image_tool.transform_array(source, "encode"))
    response = client.post(
        "/api/image-tools/deobfuscate",
        files={"file": ("scrambled.png", scrambled, "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["cache-control"] == "no-store"
    report = _report_from_response(response)
    assert report["accepted"] is True
    assert report["width"] == 128
    assert report["height"] == 96
    np.testing.assert_array_equal(_decode_bytes(response.content), source)


def test_api_rejects_untouched_image_and_supports_forced_view(client) -> None:
    original = _png_bytes(_smooth_array(96, 64))
    rejected = client.post(
        "/api/image-tools/deobfuscate",
        files={"file": ("normal.png", original, "image/png")},
    )
    assert rejected.status_code == 422
    assert "可能不是小番茄混淆图" in rejected.json()["detail"]

    forced = client.post(
        "/api/image-tools/deobfuscate?force=true",
        files={"file": ("normal.png", original, "image/png")},
    )
    assert forced.status_code == 200
    report = _report_from_response(forced)
    assert report["accepted"] is False
    assert report["forced"] is True


def test_api_maps_corrupt_image_to_bad_request(client) -> None:
    response = client.post(
        "/api/image-tools/deobfuscate",
        files={"file": ("broken.png", b"not an image", "image/png")},
    )
    assert response.status_code == 400
    assert "无法解码" in response.json()["detail"]


def test_api_rejects_a_second_concurrent_request(client) -> None:
    original = _png_bytes(_smooth_array(32, 24))
    assert image_tools._PROCESSING_SLOTS.acquire(blocking=False)
    try:
        response = client.post(
            "/api/image-tools/deobfuscate",
            files={"file": ("normal.png", original, "image/png")},
        )
    finally:
        image_tools._PROCESSING_SLOTS.release()
    assert response.status_code == 429
