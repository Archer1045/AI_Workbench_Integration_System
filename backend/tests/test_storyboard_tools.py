"""Storyboard grid slicing and video merge preflight contracts."""
from __future__ import annotations

import base64
import io
import json
import subprocess
import zipfile
from pathlib import Path

from PIL import Image

import config
import storyboard_tools


def _png_bytes(size=(600, 400), color=(240, 240, 240)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _report(response) -> dict:
    value = response.headers["x-image-tool-report"]
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def test_storyboard_slice_routes_create_metadata_for_4_6_9(
    client,
) -> None:
    for grid, expected in ((4, (2, 2)), (6, (2, 3)), (9, (3, 3))):
        response = client.post(
            "/api/storyboard/slice",
            files={"file": ("source-storyboard.png", _png_bytes(), "image/png")},
            params={"grid": grid, "crop_margin": 4},
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/zip")
        report = _report(response)
        assert report["grid"] == grid
        assert report["rows"] == expected[0]
        assert report["columns"] == expected[1]
        assert report["cell_count"] == grid
        assert report["cells"][-1]["x"] + report["cells"][-1]["width"] == 596
        assert report["cells"][-1]["y"] + report["cells"][-1]["height"] == 396
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = set(archive.namelist())
            assert "manifest.json" in names
            assert f"cells/r{expected[0]}c{expected[1]}.png" in names
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["source_name"] == "source-storyboard.png"
            assert manifest["source_sha256"] == report["source_sha256"]


def test_storyboard_slice_rejects_invalid_grid_and_crop(client) -> None:
    bad_grid = client.post(
        "/api/storyboard/slice",
        files={"file": ("source.png", _png_bytes(), "image/png")},
        params={"grid": 8},
    )
    assert bad_grid.status_code == 400
    assert "4、6 或 9" in bad_grid.json()["detail"]

    bad_crop = client.post(
        "/api/storyboard/slice",
        files={"file": ("source.png", _png_bytes((100, 100)), "image/png")},
        params={"grid": 9, "crop_margin": 40},
    )
    assert bad_crop.status_code == 400
    assert "裁剪边距" in bad_crop.json()["detail"]


def _make_video(
    path: Path,
    color: str,
    audio_frequency: int,
    size: str = "64x64",
) -> None:
    command = [
        str(storyboard_tools.ffmpeg_path()),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={size}:r=10:d=0.6",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={audio_frequency}:sample_rate=44100:duration=0.6",
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(path),
    ]
    process = subprocess.run(command, capture_output=True, check=False)
    assert process.returncode == 0, process.stderr.decode(errors="replace")


def test_video_merge_preflight_and_lossless_concat(
    client, tmp_path, monkeypatch
) -> None:
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    _make_video(first, "red", 440)
    _make_video(second, "blue", 660)
    monkeypatch.setattr(config, "VIDEO_MERGE_OUTPUT_DIR", tmp_path / "output")

    files = [
        ("files", ("first.mp4", first.read_bytes(), "video/mp4")),
        ("files", ("second.mp4", second.read_bytes(), "video/mp4")),
    ]
    preflight = client.post("/api/storyboard/merge/preflight", files=files)

    assert preflight.status_code == 200, preflight.text
    body = preflight.json()
    assert body["compatible"] is True
    assert body["output_format"] == "mp4"
    assert [item["name"] for item in body["files"]] == [
        "first.mp4",
        "second.mp4",
    ]
    assert body["files"][0]["video"] == body["files"][1]["video"]
    assert body["files"][0]["audio"]["codec"] == "aac"

    mismatch = tmp_path / "mismatch.mp4"
    _make_video(mismatch, "green", 880, size="96x64")
    rejected = client.post(
        "/api/storyboard/merge/preflight",
        files=[
            ("files", ("first.mp4", first.read_bytes(), "video/mp4")),
            ("files", ("mismatch.mp4", mismatch.read_bytes(), "video/mp4")),
        ],
    )
    assert rejected.status_code == 200
    assert rejected.json()["compatible"] is False
    assert rejected.json()["issues"]

    merged = client.post("/api/storyboard/merge", files=files)
    assert merged.status_code == 200, merged.text
    result = merged.json()
    assert result["format"] == "mp4"
    output = tmp_path / "output" / result["filename"]
    assert output.is_file()
    assert output.stat().st_size > 0
    probe = storyboard_tools.probe_video(output, output.name)
    assert (probe["video"]["width"], probe["video"]["height"]) == (64, 64)
    assert probe["audio"]["codec"] == "aac"
    assert probe["duration"] >= 1.0
    served = client.get(result["url"])
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("video/mp4")
