"""Deterministic comic dialogue parsing and Pillow text rendering."""
from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

import config


SYSTEM_FONT_FILES = (
    "msyh.ttc",
    "msyhbd.ttc",
    "simhei.ttf",
    "simsun.ttc",
    "NotoSansSC-VF.ttf",
    "NotoSerifSC-VF.ttf",
)
FONT_SUFFIXES = {".ttf", ".ttc", ".otf"}
IMAGE_FORMATS = {"PNG", "JPEG", "WEBP"}
ALIGNMENTS = {"left", "center", "right"}
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
DIALOGUE_TAG = re.compile(r"\[([^\[\]]*)\]", re.DOTALL)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+(?:['-][A-Za-z0-9_]+)*|\s+|.", re.DOTALL)


class ComicTextError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _system_font_dir() -> Path:
    return Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def _custom_font_entries() -> list[dict[str, str]]:
    root = config.COMIC_FONT_DIR
    if not root.is_dir():
        return []
    entries: list[dict[str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.suffix.lower() not in FONT_SUFFIXES:
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        entries.append(
            {
                "id": "custom:" + resolved.relative_to(root.resolve()).as_posix(),
                "label": path.stem,
                "source": "自定义字体目录",
            }
        )
    return entries


def font_catalog() -> dict[str, Any]:
    system_dir = _system_font_dir()
    system: list[dict[str, str]] = []
    for name in SYSTEM_FONT_FILES:
        path = system_dir / name
        if path.is_file():
            system.append(
                {
                    "id": f"system:{name}",
                    "label": path.stem,
                    "source": "系统白名单",
                }
            )
    custom = _custom_font_entries()
    default = (system + custom)[0]["id"] if system or custom else ""
    return {"default": default, "fonts": system + custom}


def _font_path(font_id: str) -> Path:
    catalog = font_catalog()
    selected = next(
        (font for font in catalog["fonts"] if font["id"] == font_id),
        None,
    )
    if selected is None:
        raise ComicTextError("字体不在系统白名单或受控字体目录中。")
    if font_id.startswith("system:"):
        return _system_font_dir() / font_id.split(":", 1)[1]
    relative = font_id.split(":", 1)[1]
    root = config.COMIC_FONT_DIR.resolve()
    path = (root / Path(relative)).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ComicTextError("字体路径越界。") from None
    return path


def _size_hint(length: int) -> dict[str, str]:
    if length <= 3:
        return {"name": "微小", "description": "一个微小紧凑的"}
    if length <= 8:
        return {"name": "标准", "description": "一个标准大小的"}
    if length <= 18:
        return {"name": "宽大", "description": "一个宽大的"}
    return {"name": "超大长条", "description": "一个占据极大面积的超大长条形"}


def parse_script(
    raw_prompt: str,
    base_bubble_description: str,
) -> dict[str, Any]:
    raw = str(raw_prompt or "")
    base = str(base_bubble_description or "").strip() or "纯白干净的空白对话框"
    dialogues: list[dict[str, Any]] = []

    def replace(match: re.Match[str]) -> str:
        text = match.group(1).strip()
        if not text:
            return ""
        hint = _size_hint(len(text))
        dialogues.append(
            {
                "index": len(dialogues) + 1,
                "text": text,
                "length": len(text),
                "bubble_size": hint["name"],
            }
        )
        return hint["description"] + base

    cleaned = DIALOGUE_TAG.sub(replace, raw)
    return {
        "cleaned_prompt": cleaned.strip(),
        "dialogues": dialogues,
        "dialogue_count": len(dialogues),
        "warning": "" if dialogues else "未发现方括号 [台词] 标记。",
    }


def _parse_color(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not HEX_COLOR.fullmatch(text):
        raise ComicTextError(f"{field} 必须是 #RRGGBB。")
    return text


def _parse_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ComicTextError(f"{field} 必须是整数。") from None
    if result < minimum or result > maximum:
        raise ComicTextError(f"{field} 必须在 {minimum}-{maximum} 之间。")
    return result


def _load_image(data: bytes) -> Image.Image:
    if len(data) > config.COMIC_TEXT_MAX_BYTES:
        raise ComicTextError(
            f"图片不能超过 {config.COMIC_TEXT_MAX_BYTES / 1024 / 1024:g} MB。",
            413,
        )
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if (opened.format or "").upper() not in IMAGE_FORMATS:
                raise ComicTextError("漫画图只支持 PNG/JPEG/WebP。")
            opened.load()
            image = ImageOps.exif_transpose(opened).copy()
    except ComicTextError:
        raise
    except (UnidentifiedImageError, OSError):
        raise ComicTextError("图片格式无法识别。") from None
    width, height = image.size
    if width < 32 or height < 32:
        raise ComicTextError("图片宽高不能小于 32 px。")
    if width * height > config.COMIC_TEXT_MAX_PIXELS:
        raise ComicTextError(
            f"图片像素数不能超过 {config.COMIC_TEXT_MAX_PIXELS:,}。",
            413,
        )
    return image.convert("RGBA")


def _tokens(paragraph: str) -> list[str]:
    return TOKEN_PATTERN.findall(paragraph)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: Any, stroke: int) -> float:
    return float(draw.textlength(text, font=font)) + stroke * 2


def _wrap_paragraph(
    draw: ImageDraw.ImageDraw,
    paragraph: str,
    font: Any,
    max_width: int,
    stroke: int,
) -> list[str]:
    if not paragraph:
        return [""]
    lines: list[str] = []
    current = ""
    for token in _tokens(paragraph):
        if token.isspace() and not current:
            continue
        candidate = current + token
        if _text_width(draw, candidate, font, stroke) <= max_width:
            current = candidate
            continue
        if current.strip():
            lines.append(current.rstrip())
            current = "" if token.isspace() else token.lstrip()
        else:
            current = token
        if _text_width(draw, current, font, stroke) <= max_width:
            continue
        # A long Latin token still has to fit without crossing the box boundary.
        chunk = ""
        for character in current:
            candidate = chunk + character
            if chunk and _text_width(draw, candidate, font, stroke) <= max_width:
                chunk = candidate
            elif _text_width(draw, character, font, stroke) <= max_width:
                if chunk:
                    lines.append(chunk)
                chunk = character
            else:
                raise ComicTextError("文本框宽度不足，无法容纳单个字符。")
        if chunk:
            lines.append(chunk)
        current = ""
    if current or not lines:
        lines.append(current.rstrip())
    return lines


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: Any,
    max_width: int,
    stroke: int,
) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        lines.extend(
            _wrap_paragraph(draw, paragraph, font, max_width, stroke)
        )
    return lines


def _layout_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: Any,
    max_width: int,
    max_height: int,
    stroke: int,
) -> tuple[list[str], int]:
    lines = _wrap_text(draw, text, font, max_width, stroke)
    line_height = max(1, int(round(font.size * 1.28)))
    total_height = line_height * len(lines) + stroke * 2
    if total_height > max_height:
        raise ComicTextError(
            f"文字高度 {total_height}px 超出文本框 {max_height}px。"
        )
    return lines, line_height


def _normalize_box(
    raw: dict[str, Any],
    index: int,
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    text = str(raw.get("text") or "").strip()
    if not text:
        raise ComicTextError(f"第 {index} 个文字框内容为空。")
    if len(text) > 2000:
        raise ComicTextError(f"第 {index} 个文字框不能超过 2000 个字符。")
    x = _parse_int(raw.get("x", 0), f"第 {index} 个文字框 X", 0, image_width - 1)
    y = _parse_int(raw.get("y", 0), f"第 {index} 个文字框 Y", 0, image_height - 1)
    available_width = image_width - x
    available_height = image_height - y
    width_default = min(available_width, max(1, int(image_width * 0.42)))
    height_default = min(available_height, max(1, int(image_height * 0.25)))
    max_width = _parse_int(
        raw.get("max_width", width_default),
        f"第 {index} 个文字框最大宽度",
        1,
        available_width,
    )
    max_height = _parse_int(
        raw.get("max_height", height_default),
        f"第 {index} 个文字框最大高度",
        1,
        available_height,
    )
    font_size = _parse_int(
        raw.get("font_size", 36),
        f"第 {index} 个文字框字号",
        8,
        500,
    )
    outline_width = _parse_int(
        raw.get("outline_width", 0),
        f"第 {index} 个文字框描边",
        0,
        20,
    )
    alignment = str(raw.get("alignment") or "center")
    if alignment not in ALIGNMENTS:
        raise ComicTextError(f"第 {index} 个文字框对齐方式不合法。")
    return {
        "text": text,
        "x": x,
        "y": y,
        "max_width": max_width,
        "max_height": max_height,
        "font_size": font_size,
        "alignment": alignment,
        "text_color": _parse_color(raw.get("text_color", "#000000"), "文字颜色"),
        "outline_width": outline_width,
        "outline_color": _parse_color(raw.get("outline_color", "#FFFFFF"), "描边颜色"),
    }


def _fit_box(
    draw: ImageDraw.ImageDraw,
    box: dict[str, Any],
    font_path: Path,
    image_width: int,
    image_height: int,
) -> tuple[Any, list[str], int, list[tuple[int, int, int, int]]]:
    stroke = int(box["outline_width"])
    inner_width = int(box["max_width"]) - stroke * 2
    if inner_width < 1:
        raise ComicTextError("文本框宽度不足，无法容纳描边和文字。")
    last_error: ComicTextError | None = None
    for size in range(int(box["font_size"]), 7, -1):
        try:
            font = ImageFont.truetype(str(font_path), size)
        except OSError:
            raise ComicTextError(f"字体无法读取：{font_path.name}") from None
        try:
            lines, line_height = _layout_lines(
                draw,
                box["text"],
                font,
                inner_width,
                int(box["max_height"]),
                stroke,
            )
        except ComicTextError as exc:
            last_error = exc
            continue
        measurements: list[tuple[int, int, int, int]] = []
        for line in lines:
            left, top, right, bottom = draw.textbbox(
                (0, 0),
                line,
                font=font,
                stroke_width=stroke,
            )
            measurements.append((left, top, right - left, bottom - top))
        return font, lines, line_height, measurements
    raise last_error or ComicTextError("无法在文本框中排版文字。")


def render_text(
    image_bytes: bytes,
    boxes_raw: list[dict[str, Any]],
    font_id: str,
) -> tuple[bytes, dict[str, Any]]:
    if not boxes_raw:
        raise ComicTextError("至少需要一个文字框。")
    if len(boxes_raw) > config.COMIC_TEXT_MAX_BOXES:
        raise ComicTextError(f"文字框数量不能超过 {config.COMIC_TEXT_MAX_BOXES}。")
    image = _load_image(image_bytes)
    font_path = _font_path(font_id)
    draw = ImageDraw.Draw(image)
    reports: list[dict[str, Any]] = []
    for index, raw in enumerate(boxes_raw, start=1):
        if not isinstance(raw, dict):
            raise ComicTextError(f"第 {index} 个文字框格式不正确。")
        box = _normalize_box(raw, index, image.width, image.height)
        font, lines, line_height, measurements = _fit_box(
            draw,
            box,
            font_path,
            image.width,
            image.height,
        )
        stroke = box["outline_width"]
        content_height = line_height * len(lines) + stroke * 2
        cursor_y = box["y"] + max(0, (box["max_height"] - content_height) // 2)
        for line, (_left, top, text_width, _height) in zip(
            lines,
            measurements,
            strict=True,
        ):
            inner_width = box["max_width"] - stroke * 2
            if box["alignment"] == "center":
                line_x = box["x"] + stroke + max(0, (inner_width - text_width) // 2)
            elif box["alignment"] == "right":
                line_x = box["x"] + stroke + max(0, inner_width - text_width)
            else:
                line_x = box["x"] + stroke
            draw.text(
                (line_x, cursor_y - top),
                line,
                font=font,
                fill=box["text_color"],
                stroke_width=stroke,
                stroke_fill=box["outline_color"],
            )
            cursor_y += line_height
        reports.append(
            {
                "index": index,
                "text": box["text"],
                "x": box["x"],
                "y": box["y"],
                "max_width": box["max_width"],
                "max_height": box["max_height"],
                "font_size": font.size,
                "lines": lines,
                "line_count": len(lines),
                "alignment": box["alignment"],
                "fits": True,
            }
        )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue(), {
        "width": image.width,
        "height": image.height,
        "font_id": font_id,
        "box_count": len(reports),
        "boxes": reports,
    }


def opencv_available() -> bool:
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return True


def capabilities() -> dict[str, Any]:
    catalog = font_catalog()
    return {
        "fonts": catalog["fonts"],
        "default_font": catalog["default"],
        "opencv": opencv_available(),
        "auto_bubble_requires": "opencv-python",
    }


def detect_bubbles(
    image_bytes: bytes,
    white_threshold: int = 220,
    min_area: int = 5000,
    invert: bool = False,
) -> dict[str, Any]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        raise ComicTextError(
            "自动气泡检测需要单独授权安装 opencv-python；当前可使用手动坐标排版。",
            501,
        ) from None
    image = _load_image(image_bytes).convert("RGB")
    array = np.asarray(image)
    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    if invert:
        gray = cv2.bitwise_not(gray)
    gray = cv2.morphologyEx(
        gray,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)),
    )
    _, binary = cv2.threshold(
        gray,
        max(1, min(255, int(white_threshold))),
        255,
        cv2.THRESH_BINARY,
    )
    binary = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)),
        iterations=1,
    )
    contours, _ = cv2.findContours(
        binary,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    bubbles: list[dict[str, int]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < max(1, int(min_area)):
            continue
        x, y, width, height = cv2.boundingRect(contour)
        box_area = float(width * height)
        extent = area / box_area if box_area else 0.0
        aspect = max(width, height) / max(1, min(width, height))
        if extent < 0.4 or aspect > 3.5:
            continue
        bubbles.append(
            {
                "x": int(x),
                "y": int(y),
                "width": int(width),
                "height": int(height),
                "area": int(area),
                "center_x": int(x + width / 2),
                "center_y": int(y + height / 2),
            }
        )
    bubbles.sort(key=lambda item: (item["center_y"], item["center_x"]))
    return {
        "width": image.width,
        "height": image.height,
        "count": len(bubbles),
        "bubbles": bubbles,
    }
