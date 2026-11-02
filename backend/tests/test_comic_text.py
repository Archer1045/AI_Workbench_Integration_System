"""Comic dialogue parsing, font control and deterministic text rendering."""
from __future__ import annotations

import base64
import io
import json

from PIL import Image

import config


def _png_bytes(size=(640, 900), color=(255, 255, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _report(response) -> dict:
    value = response.headers["x-image-tool-report"]
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def test_comic_script_parser_extracts_dialogues_and_cleans_prompt(client) -> None:
    response = client.post(
        "/api/image-tools/comic/parse",
        json={
            "raw_prompt": "两人站在窗边，[你好。] [This is a second line.]",
            "base_bubble_description": "纯白对话框",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dialogue_count"] == 2
    assert [item["text"] for item in body["dialogues"]] == [
        "你好。",
        "This is a second line.",
    ]
    assert "[你好。]" not in body["cleaned_prompt"]
    assert "纯白对话框" in body["cleaned_prompt"]
    assert body["dialogues"][0]["bubble_size"] == "微小"
    assert body["dialogues"][1]["bubble_size"] == "超大长条"


def test_comic_renderer_fits_cjk_and_latin_without_touching_gallery(
    client, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "COMIC_FONT_DIR", tmp_path / "fonts")
    capabilities = client.get("/api/image-tools/comic/capabilities").json()
    assert capabilities["fonts"]
    font_id = capabilities["default_font"]
    boxes = [
        {
            "text": "中文对白需要自动换行，不能越过边界。",
            "x": 40,
            "y": 60,
            "max_width": 230,
            "max_height": 150,
            "font_size": 42,
            "alignment": "center",
            "text_color": "#111111",
            "outline_width": 2,
            "outline_color": "#FFFFFF",
        },
        {
            "text": "Fast English dialogue wraps at words when possible.",
            "x": 300,
            "y": 500,
            "max_width": 260,
            "max_height": 170,
            "font_size": 34,
            "alignment": "left",
            "text_color": "#000000",
            "outline_width": 0,
            "outline_color": "#FFFFFF",
        },
    ]

    response = client.post(
        "/api/image-tools/comic/render",
        files={"file": ("comic.png", _png_bytes(), "image/png")},
        params={
            "boxes_json": json.dumps(boxes, ensure_ascii=False),
            "font_id": font_id,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    report = _report(response)
    assert report["box_count"] == 2
    assert all(box["fits"] for box in report["boxes"])
    assert all(box["line_count"] >= 1 for box in report["boxes"])
    assert report["boxes"][0]["font_size"] <= boxes[0]["font_size"]
    with Image.open(io.BytesIO(response.content)) as output:
        assert output.size == (640, 900)


def test_comic_renderer_rejects_unlisted_font_and_invalid_color(
    client, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(config, "COMIC_FONT_DIR", tmp_path / "fonts")
    invalid_font = client.post(
        "/api/image-tools/comic/render",
        files={"file": ("comic.png", _png_bytes(), "image/png")},
        params={
            "boxes_json": json.dumps(
                [{"text": "test", "x": 1, "y": 1, "max_width": 200}]
            ),
            "font_id": "custom:../../outside.ttf",
        },
    )
    assert invalid_font.status_code == 400
    assert "字体" in invalid_font.json()["detail"]

    capabilities = client.get("/api/image-tools/comic/capabilities").json()
    invalid_color = client.post(
        "/api/image-tools/comic/render",
        files={"file": ("comic.png", _png_bytes(), "image/png")},
        params={
            "boxes_json": json.dumps(
                [
                    {
                        "text": "test",
                        "x": 1,
                        "y": 1,
                        "max_width": 200,
                        "text_color": "red",
                    }
                ]
            ),
            "font_id": capabilities["default_font"],
        },
    )
    assert invalid_color.status_code == 400
    assert "#RRGGBB" in invalid_color.json()["detail"]


def test_comic_renderer_reports_unreadable_image(client) -> None:
    capabilities = client.get("/api/image-tools/comic/capabilities").json()
    response = client.post(
        "/api/image-tools/comic/render",
        files={"file": ("comic.txt", b"not an image", "text/plain")},
        params={
            "boxes_json": json.dumps(
                [{"text": "test", "x": 1, "y": 1, "max_width": 100}]
            ),
            "font_id": capabilities["default_font"],
        },
    )
    assert response.status_code == 400
    assert "图片格式" in response.json()["detail"]
