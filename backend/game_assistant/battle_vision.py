"""战斗画面识别（只读像素判据，不做 OCR、不驱动设备）。

定位：感知层。给执行器提供两类东西——
1. 判据：这一屏还是上一屏吗？某个区域变了吗？（region_delta / RegionSignature）
2. 结构读数：手牌 5 张的卡心与卡色、右下「攻击」按钮的位置、技能图标像不像。

来源与口径（都是 2026-10-12 实机校准过的，不是猜的）：
- 卡心横坐标基准 147 / 401 / 656 / 913 / 1163（y≈565），等差约 254；量法见
  work-log.md 同日条目（对 y 440-660 做饱和色分割 + 列直方图取双峰中点）。
- 卡色掩膜与当时现场脚本一致（力击=红、技击=蓝、迅击=绿）；卡面自身的「100%」
  暴击徽标与背景不会命中（阈值已按当日帧验证）。
- 卡色判别是相对判据：换关卡背景会变，所以只按"该卡槽内的主导饱和色"归类，
  不设绝对亮度门槛；判不出就返回 None，绝不猜。

设计原则（与 decisions.md 的绑定规则一致）：点击前必须能自证。任何判据失败都
返回 verified=False，由执行器 fail-stop，而不是继续点。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image

import config

SCREEN = (1280, 720)

HAND_BAND = (440, 660)
HAND_CARD_CENTERS = (147, 401, 656, 913, 1163)
HAND_CARD_Y = 565
HAND_SLOT_HALF_WIDTH = 120

ATTACK_SEARCH = (1080, 500, 1280, 700)
ATTACK_CORE_MIN_AREA = 400  # 腐蚀 6 次后残余像素；真圆盘约 2-3 千，细色带会归零
# 核心面积的**上限**（2026-10-14 实测）：宝具演出里那片大蓝光腐蚀后仍有 11420 px，
# 比真按钮（4470-4621 px）大一倍多，于是被误判成"可用的攻击按钮"，回合等待就误以为
# "下一回合已就绪"、自动收尾不触发。超过上限说明那根本不是按钮圆盘 ⇒ 当作没找到按钮
# 返回 None（不能只标成"不可用"：那样这一帧会被判成 overlay，等待里永远看不到
# battle_over）。真按钮在固定 UI 上尺寸稳定，7000 对 4621 留了五成余量。
ATTACK_CORE_MAX_AREA = 7000
# "按钮真的可点"的两条线（2026-10-12 实测：主战斗 4470-4621 px / 亮度 142-144；
#  「请选择对象」浮层下 3222 px / 亮度 122；选牌界面的「返回」按钮只有 ~460 px）
ATTACK_USABLE_MIN_CORE = 3500
ATTACK_USABLE_MIN_LUMA = 132.0

DIFF_THRESHOLD = 25

# 手牌判定门槛（2026-10-12 实机帧实测：真卡片的色爆 3400-7500 px，主战斗界面的
# 场景色块（红灯笼 / 蓝按钮）最多 ~2100 px，所以 2000 这条线把两者分开了）
CARD_BURST_MIN_PIXELS = 2000
CARD_BURST_MIN_RUN = 30
CARD_GRID_MIN_GAP = 150
# 卡槽几何（2026-10-16 加）：真指令卡的色带是**接近正方形的竖块**——663 帧历史真机帧里
# 实测宽 152-217、宽高比 0.91-1.18。为什么要加：冠位戴冠战的「关卡选择屏」左下有巨大
# 从者卡面 + 队伍头像，正好在手牌带 (y440-660) 里凑出 5 条红带 ⇒ 被判成 card_select
# （收尾把设备送回那一屏时撞到的）。那些假色带的形状是 69×138 / 240×128 / 41×149
# （太窄或太扁），这条几何判据把它们挡掉；同一批 663 帧回归里真卡一帧没误伤，被改判的
# 只有 2 帧"宝具演出"过场帧（本来就是误判）。
CARD_MIN_BAND_WIDTH = 110
CARD_BAND_ASPECT = (0.6, 1.5)

CARD_COLORS = {
    "buster": "力击",
    "arts": "技击",
    "quick": "迅击",
}

# 指令卡的**卡主**识别（2026-10-16）：卡面画的就是这张卡属于哪位从者，所以拿卡面窗口的
# 指纹比对就能认出卡主。窗口取"脸区"（避开上面的「暴击星 xx%」文字与下面的卡色圆环）。
# 实测同一从者的两张卡（不同卡色）NCC 0.746、不同从者 0.015 ⇒ 门槛 0.55 判别力充足。
HAND_CARD_OWNER_BOX = {"left": 70, "right": 70, "top": 405, "bottom": 500}
HAND_CARD_OWNER_MIN_SCORE = 0.55


def card_owner_box(center_x: int) -> tuple[int, int, int, int]:
    """某张卡的「从者卡面」范围（相对卡心 ±left/right，纵向给绝对 y）。"""
    return (
        int(center_x) - HAND_CARD_OWNER_BOX["left"],
        HAND_CARD_OWNER_BOX["top"],
        int(center_x) + HAND_CARD_OWNER_BOX["right"],
        HAND_CARD_OWNER_BOX["bottom"],
    )


def match_card_owner(
    image: np.ndarray,
    center_x: int,
    library: dict[str, np.ndarray],
    min_score: float = HAND_CARD_OWNER_MIN_SCORE,
) -> tuple[str, float]:
    """这张卡属于谁：返回 (名字, 分数)。库里没有达标的就是 ("", 最高分)。

    名字认不出时**不猜**（调用方要么停在原地，要么退到"任意卡"那条偏好）。
    """
    if not library:
        return "", -2.0
    box = card_owner_box(center_x)
    if box[0] < 0 or box[2] >= image.shape[1] or box[3] >= image.shape[0]:
        return "", -2.0
    best_name, best_score = "", -2.0
    for name, reference in library.items():
        score = best_shifted_ncc(image, box, reference, SUPPORT_SHIFT)
        if score > best_score:
            best_name, best_score = name, score
    return (best_name, round(best_score, 3)) if best_score >= min_score else ("", round(best_score, 3))


def load(path: str) -> np.ndarray:
    with Image.open(path) as handle:
        image = handle.convert("RGB")
        if image.size != SCREEN:
            raise ValueError(f"画面尺寸不是 {SCREEN}：{path} -> {image.size}")
        return np.asarray(image).astype(np.int16)


def _crop(image: np.ndarray, box: tuple[int, int, int, int] | None) -> np.ndarray:
    if box is None:
        return image
    x0, y0, x1, y1 = box
    return image[y0:y1, x0:x1]


def luma(image: np.ndarray, box: tuple[int, int, int, int] | None = None) -> float:
    return round(float(_crop(image, box).mean()), 4)


def region_delta(before: np.ndarray, after: np.ndarray, box: tuple[int, int, int, int] | None = None) -> float:
    """区域里"变了"的像素占比（0-1）。相对判据：不依赖绝对亮度。"""
    diff = np.abs(_crop(after, box) - _crop(before, box)).max(axis=2)
    return round(float((diff > DIFF_THRESHOLD).mean()), 4)


@dataclass(frozen=True)
class RegionSignature:
    """区域灰度指纹：判断"还是同一屏吗"（容差比对，不做绝对判断）。"""

    grid: tuple[int, int]
    values: tuple[float, ...]

    def distance(self, other: "RegionSignature") -> float:
        if self.grid != other.grid:
            raise ValueError("指纹网格不一致")
        return float(np.abs(np.array(self.values) - np.array(other.values)).mean())


def signature(image: np.ndarray, box: tuple[int, int, int, int], grid: tuple[int, int] = (6, 4)) -> RegionSignature:
    region = _crop(image, box).mean(axis=2)
    rows, cols = grid
    height, width = region.shape
    cells = []
    for row in range(rows):
        for col in range(cols):
            y0, y1 = height * row // rows, height * (row + 1) // rows
            x0, x1 = width * col // cols, width * (col + 1) // cols
            cells.append(float(region[y0:y1, x0:x1].mean()))
    return RegionSignature(grid=grid, values=tuple(round(value, 3) for value in cells))


def _color_masks(image: np.ndarray) -> dict[str, np.ndarray]:
    red, green, blue = image[:, :, 0], image[:, :, 1], image[:, :, 2]
    return {
        "buster": (red > 140) & (green < 80) & (blue < 80),
        "arts": (blue > 140) & (green < 110) & (red < 110),
        "quick": (green > 140) & (red < 110) & (blue < 110),
    }


@dataclass
class HandCard:
    index: int
    center_x: int
    color: str | None
    label: str
    burst_pixels: int
    # 色带外接框（像素）——用来核"这一条到底像不像一张卡面"，见 CARD_MIN_BAND_WIDTH
    band_width: int = 0
    band_height: int = 0


@dataclass
class HandReading:
    cards: list[HandCard] = field(default_factory=list)
    verified: bool = False
    notes: list[str] = field(default_factory=list)

    def center_of(self, index: int) -> int | None:
        card = self.card_at(index)
        return card.center_x if card else None

    def card_at(self, index: int) -> HandCard | None:
        return next((card for card in self.cards if card.index == index), None)

    def indices_with_color(self, color: str) -> list[int]:
        return [card.index for card in self.cards if card.color == color]

    def report(self) -> str:
        parts = [f"{card.index}:{card.label}({card.center_x})" for card in self.cards]
        return "手牌 " + " ".join(parts) + (" [已核验]" if self.verified else " [未核验]")


def read_hand(image: np.ndarray) -> HandReading:
    """量出 5 张指令卡的卡心与卡色。

    做法：在卡槽窗口内找该槽的主导饱和色爆（力击红 / 技击蓝 / 迅击绿）。只认**成条**的
    色带（列直方图里宽度 ≥ 30 px 的连续段），并且总面积要 ≥ CARD_BURST_MIN_PIXELS，
    这样主战斗界面的红灯笼 / 蓝按钮等零星色块不会冒充卡片。少于 3 个卡槽成立即
    `verified=False`，由调用方 fail-stop（2026-10-12 实测：主战斗界面与
    「请选择对象」浮层都会被这条规则正确拒掉）。

    2026-10-16 再加一条**几何**判据：色带还得是个"接近正方形的竖块"（宽 ≥ 110、
    宽高比 0.6-1.5，见 CARD_MIN_BAND_WIDTH）。只数"有几条色带"是挡不住冠位戴冠战
    「关卡选择屏」的——那一屏左下的巨大从者卡面 + 队伍头像会凑出 5 条红带（形状
    69×138 / 240×128 / 41×149），于是被误判成在选牌。加这条之后同一批 663 帧历史
    真机帧里真卡一帧没误伤，被改判的 15 帧全是本来就不该算的（弹窗屏、关卡选择屏、
    宝具演出的过场帧）。
    """
    y0, y1 = HAND_BAND
    masks = _color_masks(image)
    reading = HandReading()
    odd_shapes: list[str] = []
    for slot, base_x in enumerate(HAND_CARD_CENTERS, start=1):
        x0 = max(0, base_x - HAND_SLOT_HALF_WIDTH)
        x1 = min(image.shape[1], base_x + HAND_SLOT_HALF_WIDTH)
        best_color, best_count, best_center = None, 0, base_x
        best_shape = (0, 0)
        for color, mask in masks.items():
            columns = mask[y0:y1, x0:x1].sum(axis=0)
            runs = _runs(columns, CARD_BURST_MIN_RUN)
            if not runs:
                continue
            covered = np.zeros_like(columns, dtype=bool)
            for start, end in runs:
                covered[start : end + 1] = True
            count = int(columns[covered].sum())
            if count < CARD_BURST_MIN_PIXELS or count <= best_count:
                continue
            # 几何判据：色带得是个"接近正方形的竖块"才当卡面（见 CARD_MIN_BAND_WIDTH）
            columns_at = np.where(covered)[0]
            band = mask[y0:y1, x0 + int(columns_at.min()) : x0 + int(columns_at.max()) + 1]
            rows = np.where(band.any(axis=1))[0]
            width = int(columns_at.max() - columns_at.min() + 1)
            height = int(rows.max() - rows.min() + 1) if rows.size else 0
            aspect = (width / height) if height else 0.0
            if width < CARD_MIN_BAND_WIDTH or not CARD_BAND_ASPECT[0] <= aspect <= CARD_BAND_ASPECT[1]:
                odd_shapes.append(f"{slot}:{color} {width}×{height}")
                continue
            weights = np.arange(columns.shape[0])[covered]
            values = columns[covered]
            best_center = int(round(float((weights * values).sum() / max(1, values.sum())) + x0))
            best_color, best_count = color, count
            best_shape = (width, height)
        reading.cards.append(
            HandCard(
                index=slot,
                center_x=best_center,
                color=best_color,
                label=CARD_COLORS.get(best_color or "", "未知"),
                burst_pixels=best_count,
                band_width=best_shape[0],
                band_height=best_shape[1],
            )
        )
    colored = [card for card in reading.cards if card.color]
    reading.verified = len(colored) >= 3
    if not reading.verified:
        reading.notes.append(f"只有 {len(colored)} 个卡槽成立样色带，判定为没到选牌界面")
    if odd_shapes and not reading.verified:
        # 只当**辅助**说明：形状不像卡面的那些色带是被这条几何判据挡掉的
        reading.notes.append("色带形状不像卡面（太窄/太扁）：" + "、".join(odd_shapes))
    centers = sorted(card.center_x for card in colored)
    if len(centers) >= 3:
        gaps = [b - a for a, b in zip(centers, centers[1:])]
        if min(gaps) < CARD_GRID_MIN_GAP:
            reading.verified = False
            reading.notes.append(f"卡心间距异常（{gaps}），可能把同一张卡量成了两张")
    return reading


def _runs(columns: np.ndarray, min_width: int) -> list[tuple[int, int]]:
    """列直方图里宽度 ≥ min_width 的连续段（阈值取峰值的 12%，与当日现场脚本一致）。"""
    if columns.size == 0 or int(columns.max()) <= 0:
        return []
    threshold = max(8, int(columns.max() * 0.12))
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(columns):
        if value >= threshold and start is None:
            start = index
        elif value < threshold and start is not None:
            if index - start >= min_width:
                runs.append((start, index - 1))
            start = None
    if start is not None and len(columns) - start >= min_width:
        runs.append((start, len(columns) - 1))
    return runs


@dataclass
class AttackButton:
    center: tuple[int, int]
    area: int
    luma: float
    brightness_ratio: float
    usable: bool
    notes: list[str] = field(default_factory=list)


def find_attack_button(image: np.ndarray) -> AttackButton | None:
    """在右下角找那块高饱和蓝圆盘（主战斗界面的「攻击」按钮）。

    用"腐蚀后还剩多大"来等价于"最大内切圆"，从而挑出真正的圆盘而不是细长色带；
    再要求候选斑块的**外接框接近正方形**——活动地图右下那个浅蓝「菜单」按钮
    是细长圆角矩形（宽高比 ≈ 2.4），实测会被这一步干净地拒掉。
    同时回报圆盘亮度与「圆盘亮度 / 整屏亮度」：被浮层压暗的按钮这两个值都低。
    """
    x0, y0, x1, y1 = ATTACK_SEARCH
    region = image[y0:y1, x0:x1]
    red, green, blue = region[:, :, 0], region[:, :, 1], region[:, :, 2]
    mask = (blue > 150) & (blue - red > 40) & (blue - green > 10)
    core = _erode(mask, 6)
    area = int(core.sum())
    if area < ATTACK_CORE_MIN_AREA or area > ATTACK_CORE_MAX_AREA:
        return None
    rows = np.where(core.any(axis=1))[0]
    center_y = int(y0 + rows.mean())
    center_x = int(x0 + (np.arange(core.shape[1])[None, :] * core).sum() / area)
    # 形状判据：看圆心附近 ±90 px 窗口内掩膜的外接框是否接近正方形
    top = max(0, center_y - y0 - 90)
    left = max(0, center_x - x0 - 90)
    window = mask[top : center_y - y0 + 90, left : center_x - x0 + 90]
    window_rows = np.where(window.any(axis=1))[0]
    window_cols = np.where(window.any(axis=0))[0]
    if window_rows.size == 0 or window_cols.size == 0:
        return None
    width = int(window_cols.max() - window_cols.min() + 1)
    height = int(window_rows.max() - window_rows.min() + 1)
    aspect = width / max(1, height)
    patch = image[max(0, center_y - 24) : center_y + 24, max(0, center_x - 24) : center_x + 24].mean(axis=2)
    patch_luma = round(float(patch.mean()), 2)
    screen_luma = luma(image)
    notes: list[str] = []
    usable = True
    if not 0.7 <= aspect <= 1.4:
        usable = False
        notes.append(f"候选斑块宽高比 {aspect:.2f} 不像圆盘（真按钮 ≈1.0）")
    if area < ATTACK_USABLE_MIN_CORE:
        usable = False
        notes.append(f"蓝色核心只有 {area} px（真按钮约 4500），像是别的东西")
    if patch_luma < ATTACK_USABLE_MIN_LUMA:
        usable = False
        notes.append(f"按钮亮度 {patch_luma} 偏低（真按钮约 142），说明被浮层压暗了")
    return AttackButton(
        center=(center_x, center_y),
        area=area,
        luma=patch_luma,
        brightness_ratio=round(patch_luma / screen_luma, 4) if screen_luma else 0.0,
        usable=usable,
        notes=notes,
    )


def _erode(mask: np.ndarray, iterations: int) -> np.ndarray:
    """4 邻域腐蚀（numpy only）。等价于最内切圆筛选，不需要 scipy。"""
    out = mask.copy()
    for _ in range(iterations):
        out = out & np.roll(out, 1, axis=0) & np.roll(out, -1, axis=0)
        out = out & np.roll(out, 1, axis=1) & np.roll(out, -1, axis=1)
    return out


def icon_like_score(image: np.ndarray, point: tuple[int, int], size: int = 46) -> float:
    """技能图标像不像：外圈偏暗、内部有高对比内容。

    只作为点击前的一道保险（真正的判据是点击前后的区域变化），不是识别器。
    """
    cx, cy = point
    half = size // 2
    y0, y1 = max(0, cy - half), min(image.shape[0], cy + half)
    x0, x1 = max(0, cx - half), min(image.shape[1], cx + half)
    patch = image[y0:y1, x0:x1].mean(axis=2)
    if patch.size == 0:
        return 0.0
    inner = patch[4:-4, 4:-4] if patch.shape[0] > 8 and patch.shape[1] > 8 else patch
    border = np.concatenate(
        [patch[0:2, :].ravel(), patch[-2:, :].ravel(), patch[:, 0:2].ravel(), patch[:, -2:].ravel()]
    )
    contrast = float(border.mean()) - float(inner.mean())
    vividness = float(inner.std())
    return round(max(0.0, contrast) / 60.0 + min(vividness, 90.0) / 90.0, 4)


def resolve_cards(
    reading: HandReading,
    color: str,
    count: int = 1,
    position: str = "any",
    exclude: Iterable[int] = (),
    allowed: Iterable[int] | None = None,
) -> list[int]:
    """按卡色 + 位置偏好挑卡位。挑不出就抛错，由调用方决定停不停（不猜）。

    color="any" 表示任意一张还没用掉的指令卡（用在"补位卡是谁无所谓"的回合）。
    `allowed` 给定时只在这些卡位里挑（卡主识别用它把范围收成"某位从者自己的卡"）。
    """
    used = set(exclude)
    permitted = None if allowed is None else set(allowed)
    candidates: list[int] = []
    for card in reading.cards:
        if card.index in used:
            continue
        if permitted is not None and card.index not in permitted:
            continue
        if color == "any":
            # 读数"未知"的卡槽不能当成可用的 any：多半是**已经点过**的那张——选中后
            # 卡片抬起、色带被盖住，手牌读数就变成未知（2026-10-14 实测：第 3 回合点掉
            # 第 5 张后它读成未知）。把它算进来等于再点一次同一张卡 = 把它取消掉。
            if card.color is None:
                continue
        elif card.color != color:
            continue
        candidates.append(card.index)
    if position in ("any", "", None):
        chosen = candidates
    elif position == "leftmost":
        chosen = sorted(candidates)
    elif position == "rightmost":
        chosen = sorted(candidates, reverse=True)
    else:
        index = int(position)
        if index not in candidates:
            raise ValueError(f"第 {index} 张不是 {CARD_COLORS.get(color, color)}（或已被占用）")
        chosen = [index]
    if len(chosen) < count:
        raise ValueError(
            f"手牌里能用的 {CARD_COLORS.get(color, color)} 只有 {len(chosen)} 张，需要 {count} 张"
            f"（{reading.report()}）"
        )
    return chosen[:count]


def describe_hand(reading: HandReading) -> str:
    return reading.report()


SCENE_BATTLE_MAIN = "battle_main"
SCENE_CARD_SELECT = "card_select"
SCENE_OVERLAY = "overlay"
SCENE_OTHER = "other"


# ---------------------------------------------------------------------------
# 指令纹章识别：找出刻了指定纹章的那张指令卡
#
# 判据来源（2026-10-13，用户圈注 + 实机多帧回归，见 .tmp\code_icon\template_meta.json）：
#   * 锚点 = 每张卡右上角的「兽之足迹 / 指令卡强化」金徽——金色实心块，真机实测
#     约 30x35 px，同一帧 5/5 稳定可测，且它是**纯色实心**（掩膜填充率 0.9 左右），
#     和卡面上的金色美术（100% 暴击星爆、发饰）能靠"实心度"分开；
#   * 纹章图样就在金徽**正上方**：窗口中心 = 金徽中心 + (-5, -48)，窗口约 58x69 px；
#   * 同一帧内只有刻了该纹章的那张卡会明显命中（实测 NCC 0.95 左右，其余 <= 0.5）。
#
# 设计原则（与 decisions.md 的绑定规则一致）：**没把握就不给结论**。分数不够高、
# 领先优势不够大、锚点数量不对，都返回 accepted=False，由执行器 fail-stop，绝不猜卡位。
#
# 注意：前一版「卡面看不出纹章」的结论是取样错误（只框了金徽本身），已作废。
# ---------------------------------------------------------------------------

COMMAND_CODE_DIR = Path(config.GAME_ASSISTANT_EXECUTION_DIR) / "templates" / "command_codes"

# 金徽检测：用"实心块"判据（滑动窗口内的金色像素数 + 填充率），不需要连通域库
BADGE_KERNEL = (25, 30)          # (高, 宽) 的滑动窗口，略小于真徽标 30x35
BADGE_MIN_PIXELS = 450           # 窗口内金色像素下限（真徽标约 700）
BADGE_MIN_FILL = 0.60            # 填充率下限：卡面金色美术是散点，达不到
BADGE_BAND = (320, 540)          # 只在手牌区找锚点（抬起的卡最多上移 ~100 px）
BADGE_SLOT_HALF_WIDTH = 118

CODE_SCALE_FACTORS = (0.85, 0.92, 1.00, 1.08, 1.15)
CODE_SHIFT_SEARCH = 6            # 允许 ±6 px 位移（锚点定位误差 + 卡面绘制抖动）
CODE_MIN_SCORE = 0.75            # 命中下限
CODE_MIN_MARGIN = 0.20           # 与次高的差距下限


def _gray(image: np.ndarray) -> np.ndarray:
    return image[:, :, :3].astype(np.float32).mean(axis=2)


def _resize_gray(gray: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """(宽, 高) 缩放，走 PIL 的双线性（避免给后端引入 cv2 依赖）。"""
    height, width = size[1], size[0]
    return np.asarray(
        Image.fromarray(gray.astype(np.uint8)).resize((width, height), Image.BILINEAR)
    ).astype(np.float32)


def _ncc(patch: np.ndarray, template: np.ndarray) -> float:
    """归一化互相关（去均值 + 单位化）：对整体亮度/对比度变化不敏感。"""
    if patch.shape != template.shape:
        return -1.0
    a = patch - patch.mean()
    b = template - template.mean()
    denominator = float(np.sqrt(float((a * a).sum())) * np.sqrt(float((b * b).sum())))
    if denominator <= 1e-6:
        return 0.0
    return float((a * b).sum() / denominator)


def _box_sum(mask: np.ndarray, kernel: tuple[int, int]) -> np.ndarray:
    """积分图算窗口内像素数（等价于用全 1 核做相关，纯 numpy）。"""
    kh, kw = kernel
    integral = np.zeros((mask.shape[0] + 1, mask.shape[1] + 1), dtype=np.float32)
    np.cumsum(np.cumsum(mask.astype(np.float32), axis=0), axis=1, out=integral[1:, 1:])
    height = mask.shape[0] - kh + 1
    width = mask.shape[1] - kw + 1
    if height <= 0 or width <= 0:
        return np.zeros((0, 0), dtype=np.float32)
    return (
        integral[kh:, kw:]
        - integral[:-kh, kw:]
        - integral[kh:, :-kw]
        + integral[:-kh, :-kw]
    )


@dataclass
class BadgeAnchor:
    """一张指令卡的锚点：兽之足迹金徽的中心与尺寸。"""

    slot: int
    center_x: int
    center_y: int
    width: int
    height: int


def find_badges(image: np.ndarray) -> list[BadgeAnchor]:
    """按卡槽找「兽之足迹」金徽（每格最多一个）。找不到的卡槽不返回。"""
    red, green, blue = image[:, :, 0], image[:, :, 1], image[:, :, 2]
    gold = (red > 140) & (green > 100) & (blue < 130) & ((red - blue) > 55) & ((green - blue) > 25)
    y0, y1 = BADGE_BAND
    anchors: list[BadgeAnchor] = []
    for slot, base_x in enumerate(HAND_CARD_CENTERS, start=1):
        x0 = max(0, base_x - BADGE_SLOT_HALF_WIDTH)
        x1 = min(image.shape[1], base_x + BADGE_SLOT_HALF_WIDTH)
        window = gold[y0:y1, x0:x1]
        if not window.any():
            continue
        sums = _box_sum(window, BADGE_KERNEL)
        if sums.size == 0:
            continue
        flat = int(np.argmax(sums))
        rows, cols = sums.shape
        best = float(sums.reshape(-1)[flat])
        kernel_area = BADGE_KERNEL[0] * BADGE_KERNEL[1]
        if best < BADGE_MIN_PIXELS or best / kernel_area < BADGE_MIN_FILL:
            continue
        row, col = divmod(flat, cols)
        box = window[row : row + BADGE_KERNEL[0], col : col + BADGE_KERNEL[1]]
        ys, xs = np.nonzero(box)
        anchors.append(
            BadgeAnchor(
                slot=slot,
                center_x=int(round(x0 + col + float(xs.mean()))),
                center_y=int(round(y0 + row + float(ys.mean()))),
                width=BADGE_KERNEL[1],
                height=BADGE_KERNEL[0],
            )
        )
    return anchors


@dataclass
class CodeCardMatch:
    """「哪张卡刻了这个纹章」的判定结果（含证据，便于写进执行日志）。"""

    name: str
    index: int | None = None
    score: float = 0.0
    runner_up: float = 0.0
    margin: float = 0.0
    scores: list[tuple[int, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    accepted: bool = False

    def report(self) -> str:
        detail = " ".join(f"卡{i}={score:.3f}" for i, score in self.scores) or "无锚点"
        verdict = f"第 {self.index} 张" if self.accepted else "未命中"
        return f"纹章「{self.name}」→ {verdict}（{detail}；差距 {self.margin:.3f}）"


_TEMPLATE_CACHE: dict[str, tuple[np.ndarray, dict]] = {}


def load_command_code(name: str, directory: Path | None = None) -> tuple[np.ndarray, dict]:
    """读出「纹章名 -> (灰度模板, 几何参数)」。参数表在 templates/command_codes/。"""
    if name in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[name]
    base = Path(directory or COMMAND_CODE_DIR)
    registry_path = base / "command_codes.json"
    if not registry_path.exists():
        raise FileNotFoundError(f"缺少纹章模板登记表：{registry_path}")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = next((item for item in registry.get("codes") or [] if str(item.get("name")) == name), None)
    if entry is None:
        known = "、".join(str(item.get("name")) for item in registry.get("codes") or [])
        raise KeyError(f"模板登记表里没有纹章「{name}」（现有：{known}）")
    template_path = base / str(entry.get("template") or "")
    if not template_path.exists():
        raise FileNotFoundError(f"缺少纹章模板图：{template_path}")
    with Image.open(template_path) as handle:
        template = _gray(np.asarray(handle.convert("RGB")).astype(np.int16))
    _TEMPLATE_CACHE[name] = (template, entry)
    return template, entry


def find_command_code_card(
    image: np.ndarray,
    name: str,
    directory: Path | None = None,
) -> CodeCardMatch:
    """在选牌界面上找出刻了指定纹章的那张卡。

    调用前提：**未选牌的选卡界面**。已选中的卡会抬起并盖上「行动N」徽标，金徽本身
    就检不出来（2026-10-12 的 t2f_sel35 帧实测如此），所以那种画面下会返回未命中。
    """
    template, entry = load_command_code(name, directory)
    offset = tuple(entry.get("offset") or (-5, -48))
    badge_ref_width = float(entry.get("badge_ref_width") or 30)
    min_score = float(entry.get("min_score") or CODE_MIN_SCORE)
    min_margin = float(entry.get("min_margin") or CODE_MIN_MARGIN)

    match = CodeCardMatch(name=name)
    anchors = find_badges(image)
    if not anchors:
        match.notes.append("没找到任何兽之足迹金徽（不是选牌界面？或该从者的卡没做过指令卡强化）")
        return match
    if len(anchors) < 3:
        match.notes.append(f"只找到 {len(anchors)} 个金徽锚点，不足以判定")
        return match

    gray = _gray(image)
    base_scale = float(anchors[0].width) / badge_ref_width
    for anchor in anchors:
        scale = float(anchor.width) / badge_ref_width
        center_x = anchor.center_x + offset[0] * scale
        center_y = anchor.center_y + offset[1] * scale
        best = -2.0
        for factor in CODE_SCALE_FACTORS:
            target_w = int(round(template.shape[1] * scale * factor))
            target_h = int(round(template.shape[0] * scale * factor))
            if target_w < 8 or target_h < 8:
                continue
            resized = _resize_gray(template, (target_w, target_h))
            left = int(round(center_x - target_w / 2)) - CODE_SHIFT_SEARCH
            top = int(round(center_y - target_h / 2)) - CODE_SHIFT_SEARCH
            width = target_w + 2 * CODE_SHIFT_SEARCH + 1
            height = target_h + 2 * CODE_SHIFT_SEARCH + 1
            if left < 0 or top < 0 or left + width > gray.shape[1] or top + height > gray.shape[0]:
                continue
            window = gray[top : top + height, left : left + width]
            for dy in range(2 * CODE_SHIFT_SEARCH + 1):
                for dx in range(2 * CODE_SHIFT_SEARCH + 1):
                    score = _ncc(window[dy : dy + target_h, dx : dx + target_w], resized)
                    if score > best:
                        best = score
        match.scores.append((anchor.slot, round(best, 3)))

    match.scores.sort(key=lambda item: -item[1])
    top_slot, top_score = match.scores[0]
    match.index = top_slot
    match.score = float(top_score)
    match.runner_up = float(match.scores[1][1]) if len(match.scores) > 1 else 0.0
    match.margin = round(match.score - match.runner_up, 3)
    match.notes.append(f"锚点 {len(anchors)} 个，模板尺度基准 {base_scale:.2f}")
    if match.score < min_score:
        match.accepted = False
        match.notes.append(f"最高分 {match.score:.3f} < 命中门槛 {min_score}")
    elif match.margin < min_margin:
        match.accepted = False
        match.notes.append(f"最高分与次高只差 {match.margin:.3f} < 门槛 {min_margin}（分不清是哪张）")
    else:
        match.accepted = True
    return match


@dataclass
class SceneReading:
    name: str
    hand: HandReading
    attack: AttackButton | None
    notes: list[str] = field(default_factory=list)

    def report(self) -> str:
        detail = f"攻击按钮={self.attack.center if self.attack else None}"
        if self.attack:
            detail += f"(核心{self.attack.area}px/亮度{self.attack.luma})"
        text = f"画面判定：{self.name}｜{detail}｜{self.hand.report()}"
        if self.notes:
            text += "｜" + "；".join(self.notes)
        return text


def read_scene(image: np.ndarray) -> SceneReading:
    """当前是哪个界面。只区分执行器真正需要的四种：

    - card_select：手牌被判成立（选牌界面）；
    - battle_main：主战斗界面且「攻击」按钮**可用**（没被浮层压暗）；
    - overlay：有浮层（按钮还在但被压暗）——「请选择对象」/ 御主技能菜单都归这里；
    - other：两个信号都没有（结算页 / 活动地图 / 过场等）。
    """
    hand = read_hand(image)
    attack = find_attack_button(image)
    notes = list(hand.notes)
    if hand.verified:
        name = SCENE_CARD_SELECT
    elif attack is not None and attack.usable:
        name = SCENE_BATTLE_MAIN
    elif attack is not None:
        name = SCENE_OVERLAY
        notes.extend(attack.notes)
    else:
        name = SCENE_OTHER
    return SceneReading(name=name, hand=hand, attack=attack, notes=notes)


# ---------------------------------------------------------------------------
# 助战选择屏：「行结构」+「身份块」指纹
#
# 判据来源（2026-10-14，用户圈注 + 本机实测）：
#   * 用户口径：挑助战只看画面**左边**的身份块（从者名 / 宝具 / 等级 / 玩家名）；右侧那列
#     （礼装图标、技能等级、指令纹章）不作挑选判据——需要卡那些属性时用户会自己出从者。
#   * 为什么指纹必须是"整块"而不是只认从者名：同一帧里第 1、2 行都叫「阿尔托莉雅·卡斯特」
#     （不同职阶变体），只比从者名那一行 NCC = 0.974（认不出来）；比整个身份块 NCC = 0.432
#     （一眼分开）。⇒ 指纹范围 = 名字带 + 「从者 / 宝具」面板整块。
#   * 点击落点 = 那块青色面板的中心（用户圈注的框里那一块，每帧都能重新检出；不手量坐标）。
# 判不出来就返回空列表 / accepted=False，由执行器 fail-stop，绝不猜行。
# ---------------------------------------------------------------------------

SUPPORT_PANEL_COLOR = (90, 117, 168)
SUPPORT_PANEL_TOLERANCE = 28
SUPPORT_PANEL_SEARCH = (200, 120, 900, 720)
# 面板整高 90 px，但它下半有渐变——纯色部分只有上半 42-55 px，所以分两步：先用"强色带"
# 定位每一行的上沿，再按固定高度补出整个面板。阈值取 300 是因为实测：助战屏每行强色带
# 441-473 px，而地图 / 战斗 / 选牌帧在同一掩膜下最多 184 px。
SUPPORT_PANEL_MIN_COUNT = 300     # 每行命中面板色的像素数下限
SUPPORT_PANEL_BAND_COUNT = 100    # 判"这是面板色带"的行像素下限（比上面低：新版面板更窄、
                                  # 色带还会被文字切碎，旧阈值 300 会把整屏判成 0 行）
SUPPORT_PANEL_MIN_BAND = 30       # 强色带最小高度（实测 42-55）
SUPPORT_PANEL_HEIGHT = 90         # 面板整体高度（实测；固定布局）
SUPPORT_PANEL_MIN_WIDTH = 400     # 面板横向像素数下限（实测 ≈578）
SUPPORT_PANEL_MIN_WIDTH_WIDE = 320  # 宽块布局（冠位从者）的面板更窄：实测 427
# 指纹取面板里「宝具 名称 等级N」那一行（相对面板的 左/上/右/下 偏移，2026-10-14 实测）。
# 为什么是这一行而不是整块或从者名行（同一帧实测 NCC）：
#   * 从者名行两两 = 0.973 —— 两行都叫「阿尔托莉雅·卡斯特」，认不出职阶变体；
#   * 整块身份块两两 = 0.53 —— 能分但有相当一部分是玩家留言/等级等会变的内容；
#   * 宝具行两两 = 0.20 / -0.04 —— 又稳（纯文本、不随留言/登录时间变）又分得开。
# 从者名行不进门槛，只作为诊断分数一起记进日志。
SUPPORT_IDENTITY_LINE = {"left": 93, "top": 44, "right": 107, "bottom": 68}
# 「等级N」要**排除在指纹之外**（2026-10-17 实测）：窄块布局里那行是
# 「宝具 | 灵袈重光・…大社 等级1」，`等级N` 落在 x≈620-680、正好在旧的框内 ⇒ 好友把宝具
# 从等级1 升到等级2/4，同一只从者的分数就掉到 0.15（今天列表里两行真冠位杀狐因此被判"不是"）。
# 窄块把右边收紧到"名字结束处"（面板右 -190）；宽块布局的文字更靠左、框本来就不含 `等级N`
# （实测宽块文字 ≈476-720、`等级N` 在 731 之后），保持原值。
SUPPORT_IDENTITY_RIGHT = {"narrow": 190, "wide": 107}
SUPPORT_REFERENCE_VERSION = 2
SUPPORT_MIN_ROWS = 2              # 少于两条就不算「助战选择」屏
SUPPORT_ROW_PITCH = (100, 300)    # 相邻两行的纵向间距合理区间（实测 186）
# 行外框：横贯整行的亮线。**两版布局都有**（2026-10-16 实测）：新版（冠位从者，左边块更宽）
# 在 y≈187/387/587、行距 200；旧版（普通助战，单个礼装）在 y≈220/407/607、行距 187。
# 用它当行锚点比"找青色面板色带"稳（新版面板只有 81 px 高、色带还会被文字切碎 ⇒ 旧检测器
# 直接报 0 行，把助战屏错判成 overlay）。面板仍按颜色在**行内**找，用来定身份块与落点。
SUPPORT_SEPARATOR_LUMA = 210      # 外框亮线的亮度门槛（max 通道）
SUPPORT_SEPARATOR_COUNT = 700     # 一条外框至少要有这么多亮像素（实测 ≥1000）
# 两版布局的左边块（金框方块）相对**面板**的偏移：新版左边块要宽得多（肖像 + 3 件礼装）。
SUPPORT_CELL_VARIANTS = (
    # wide：冠位从者（左边块 = 肖像 + 最多 3 件礼装），面板宽 ≈427
    {"name": "wide", "max_width": 480, "cell": {"left": 340, "top": 88, "right": 7, "bottom": 6},
     "ce_split": None},   # 礼装区是 3 张并排、不是单条 ⇒ 这版**不提供礼装指纹框**
    # narrow：普通助战（左边块 = 肖像 + 1 件礼装），面板宽 ≈570
    {"name": "narrow", "max_width": 10_000, "cell": {"left": 191, "top": 88, "right": 7, "bottom": 6},
     "ce_split": 28},
)
# 「冠位从者」标签（在肖像底部的蓝色小条上）相对**面板**的偏移。实测 2026-10-16：
# 面板 (386,265)..(813,345) → 标签 ≈ (100,336)-(157,352)，即 left-286 / right-229 / top+71..+88。
SUPPORT_GRAND_LABEL_FRAME = {"left": 286, "right": 229, "top": 71, "bottom": 88}
SUPPORT_GRAND_MIN_SCORE = 0.80
SUPPORT_MIN_SCORE = 0.85          # 指纹命中门槛（同一行 1.000 / 不同职阶变体 0.20 与 −0.04）
# **不看与次高的差距**：2026-10-14 实机遇到两行"宝具行完全相同"的合法情形（两个好友都
# 借 C呆 Caster、宝具 环抱着你的希望之星 等级1），只有玩家名/等级/留言不同。按用户口径
# 那两行**都是能用的那只**，取最上面那行即可 ⇒ 只要绝对分达标就算命中，差距只记进日志。
SUPPORT_MIN_MARGIN = 0.0
# 位移搜索半径（**逐像素**搜，不是只试 0/±shift 三个格点）：2026-10-15 实测「连续出击」
# 那条路上同一行的指纹块相对登记位置偏 (1, 0) 像素，旧的 9 格点网格探不到 ⇒ 0.794 被判
# 找不到而停手；逐像素搜 ±6 后同一帧 0.883 正常命中。
SUPPORT_SHIFT = 6
# 左侧方块（金框方格：上=从者立绘、下=礼装条）相对**文字面板**的偏移。
# 2026-10-15 在真机帧 `run-20261015-095000/104_support_before_r2.png` 上量出来：
# 行 1 面板 (237,281,807,370) → 方块 (46,193)-(230,376)，从者/礼装分界线在 y≈309。
# 即：方块右边界 = 面板左边 -7、宽 184（正方形）；上 = 面板上沿 -88、下 = 面板下沿 +6；
# 礼装条从「面板上沿 +28」到方块底。
SUPPORT_CELL_FRAME = {"left": 191, "top": 88, "right": 7, "bottom": 6}
SUPPORT_CE_SPLIT = 28

def support_dir() -> Path:
    """指纹目录。**每次现读 config**，这样测试 monkeypatch 执行目录就能隔离。"""
    return Path(config.GAME_ASSISTANT_EXECUTION_DIR) / "templates" / "support"


@dataclass
class SupportRow:
    """一条助战：面板范围、指纹行范围、点击落点，以及**左侧方块**（上=从者、下=礼装）。"""

    index: int
    panel: tuple[int, int, int, int]
    identity: tuple[int, int, int, int]
    center: tuple[int, int]
    cell: tuple[int, int, int, int] = (0, 0, 0, 0)
    """左侧那个带金框的方块（从者立绘 + 下方的礼装条）。"""
    ce: tuple[int, int, int, int] = (0, 0, 0, 0)
    """方块下半部分 —— 借来的**概念礼装**卡面（挑助战要按它过滤时用）。

    宽块布局（冠位从者行，带最多 3 件礼装）没有"单条礼装" ⇒ 这里是空框，
    `match_support_criteria` 会跳过它。
    """
    variant: str = "narrow"
    """布局变体：`narrow`（普通助战）/ `wide`（冠位从者）。"""

    def report(self) -> str:
        return f"第{self.index}行 面板{self.panel} 落点{self.center}"


def support_cell_box(panel: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """面板 -> 左侧方块（金框方格）。2026-10-15 在真机帧上量出来的相对偏移。"""
    return _support_cell_box_with(panel, SUPPORT_CELL_VARIANTS[0]["cell"])


def _support_cell_box_with(
    panel: tuple[int, int, int, int], frame: dict[str, int]
) -> tuple[int, int, int, int]:
    left, top, _right, bottom = panel
    return (
        max(0, left - frame["left"]),
        max(0, top - frame["top"]),
        max(0, left - frame["right"]),
        min(719, bottom + frame["bottom"]),
    )


def support_ce_box(panel: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """面板 -> 方块里**礼装那一条**（从者立绘与礼装的分界线在面板上沿下 SUPPORT_CE_SPLIT）。"""
    return _support_ce_box_with(panel, SUPPORT_CELL_VARIANTS[0])


def _support_ce_box_with(
    panel: tuple[int, int, int, int], variant: dict[str, Any]
) -> tuple[int, int, int, int]:
    """礼装条的范围。**宽块布局（冠位从者）返回空框**：那种行里礼装区是 3 张并排，
    不是"单条礼装"，按条挑会挑到无意义的东西 ⇒ 用空框表示"这版不能按礼装挑"。"""
    split = variant.get("ce_split")
    if not split:
        return (0, 0, 0, 0)
    cell = _support_cell_box_with(panel, variant["cell"])
    return (cell[0], min(719, panel[1] + int(split)), cell[2], cell[3])


SUPPORT_LIBRARY_MIN_SCORE = 0.85
# 「宝具行」横向位移搜索范围：窄块 / 宽块两版布局里那段文字的相对位置差约 40 px
# （2026-10-16 实测），所以从者指纹匹配要搜 ±60。
SUPPORT_IDENTITY_SHIFT_X = 60
# 助战指纹库的门槛与位移搜索：2026-10-15 真机回算（模板从第 1 行登记）——
# 命中的行 从者 0.957~1.000 / 礼装 1.000；不匹配的行 礼装 0.245~0.263 ⇒ 判别力足够。
# 从者指纹用密集 ±6（换好友时只有宝具等级数字不同，仍要能命中）；礼装条更大，用 ±4。
SUPPORT_CE_SHIFT = 4


def support_library_dir(kind: str) -> Path:
    """助战指纹库：`servant/`（认从者，存那一行的「宝具行」）与 `ce/`（认礼装，存左块下半的礼装条）。

    **每次现读 config**，这样测试 monkeypatch 执行目录就能隔离。
    """
    return support_dir() / kind


def support_library_paths(kind: str, name: str) -> tuple[Path, Path]:
    stem = _support_key_name(name)
    directory = support_library_dir(kind)
    return directory / f"{stem}.json", directory / f"{stem}.png"


def save_support_library_entry(
    kind: str, name: str, image: np.ndarray, box: tuple[int, int, int, int], note: str = "",
) -> Path:
    """把 image 上 box 处的图案登记成一条助战指纹（kind = "servant" / "ce"）。"""
    left, top, right, bottom = box
    patch = block_gray(image, box, (bottom - top + 1, right - left + 1))
    meta_path, image_path = support_library_paths(kind, name)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(patch.astype(np.uint8)).save(image_path)
    meta_path.write_text(
        json.dumps(
            {
                "name": name,
                "kind": kind,
                "image": image_path.name,
                "box": [int(value) for value in box],
                "min_score": SUPPORT_LIBRARY_MIN_SCORE,
                "captured_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                "note": note,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return meta_path


def load_support_library(kind: str) -> dict[str, np.ndarray]:
    """读整个助战指纹库（名字 -> 灰度图）。缺图/读不出的条目跳过，不抛异常。"""
    directory = support_library_dir(kind)
    library: dict[str, np.ndarray] = {}
    if not directory.is_dir():
        return library
    for meta_path in sorted(directory.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            image_path = meta_path.parent / str(meta.get("image") or f"{meta_path.stem}.png")
            with Image.open(image_path) as handle:
                library[str(meta.get("name") or meta_path.stem)] = _gray(
                    np.asarray(handle.convert("RGB")).astype(np.int16)
                )
        except (OSError, json.JSONDecodeError):
            continue
    return library


def best_shifted_ncc(
    image: np.ndarray,
    box: tuple[int, int, int, int],
    reference: np.ndarray,
    shift: int,
    shift_x: int | None = None,
) -> float:
    """box 处在 ±shift（纵向）/ ±shift_x（横向）像素内逐个位置试，取与 reference 的最高 NCC。

    `shift_x` 单独给（默认同 shift）是为了「宝具行」跨布局匹配：窄块布局（普通助战）的
    「宝具」图标 + 文字比宽块布局（冠位从者）整体**右移约 40 px**，不搜横向位移就永远对不上
    （2026-10-16 实测：同一个杀狐在两版之间 0.032，搜到位移后正常命中）。
    """
    best = -2.0
    span_x = shift if shift_x is None else int(shift_x)
    for dy in range(-shift, shift + 1):
        for dx in range(-span_x, span_x + 1):
            moved = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
            if moved[0] < 0 or moved[1] < 0 or moved[2] >= image.shape[1] or moved[3] >= image.shape[0]:
                continue
            best = max(best, _ncc(block_gray(image, moved, reference.shape), reference))
    return best


def match_support_criteria(
    image: np.ndarray,
    servant_reference: np.ndarray,
    ce_references: dict[str, np.ndarray],
    rows: Sequence[SupportRow] | None = None,
    min_score: float = SUPPORT_LIBRARY_MIN_SCORE,
    shift: int = SUPPORT_SHIFT,
    ce_shift: int = SUPPORT_CE_SHIFT,
    prefer_grand: bool = False,
    extra_servant_references: dict[str, np.ndarray] | None = None,
) -> SupportMatch:
    """按「从者 + 礼装」挑行：从上往下第一个「从者指纹命中 **且** 礼装命中白名单」的行。

    从者看那一行的「宝具行」（与灵基再临无关；换好友导致宝具等级不同也仍应命中）；
    礼装看左块下半的「礼装条」。挑不出就 ``accepted=False``（**不猜行**，交给人工）。

    `prefer_grand=True`（2026-10-16）：**只认冠位从者**——本函数只在**这一帧的可见行**里
    干活，所以"优先"这件事它不替调用方做主：这一帧里"满足规则但不是冠位"的第一行会记进
    `match.plain`（不 accepted），调用方要**先把整张列表翻到底**，一路都没有冠位才用它
    （用户 2026-10-16 澄清："首屏没有的话就往下翻，一直到底部都没有的话就选个普通杀狐"）。

    `extra_servant_references`：同一只从者**另一版布局**的指纹。窄块（普通助战）与宽块
    （冠位从者）的「宝具行」字距/字号都不同，2026-10-17 实测同一个模板在另一版上只有 0.15、
    跨版横移搜索 ±60 也补不回来 ⇒ 每行取"所有参考里最高的那个分"。
    """
    match = SupportMatch()
    candidates = list(rows) if rows is not None else find_support_rows(image)
    if not candidates:
        match.notes.append("这帧里找不到助战行（不是助战选择屏？）")
        return match
    # 礼装白名单可以为空 ⇒ **只按从者挑行**（2026-10-16 用户口径：冠位战里助战可以是"冠位从者"，
    # 冠位从者能戴最多 3 件礼装、礼装区几何跟普通行不一样，所以那种场合本来就不该按礼装挑）。
    # 空白名单不是错误，是"这次只看从者"。
    servant_only = not ce_references
    detail: list[str] = []
    grand_reference = load_support_library("grand").get("冠位从者") if prefer_grand else None
    references = [servant_reference, *(extra_servant_references or {}).values()]
    for row in candidates:
        servant_score = max(
            best_shifted_ncc(image, row.identity, reference, shift, shift_x=SUPPORT_IDENTITY_SHIFT_X)
            for reference in references
        )
        ce_name, ce_score = "", -2.0
        if not servant_only:
            ce_box = row.ce if row.ce[2] > row.ce[0] else support_ce_box(row.panel)
            if ce_box[2] <= ce_box[0] or ce_box[3] <= ce_box[1]:
                continue
            for name, reference in ce_references.items():
                score = best_shifted_ncc(image, ce_box, reference, ce_shift)
                if score > ce_score:
                    ce_name, ce_score = name, score
        match.scores.append((row.index, round(servant_score, 3)))
        detail.append(
            f"第{row.index}行 从者{servant_score:.3f}"
            if servant_only
            else f"第{row.index}行 从者{servant_score:.3f}/礼装{ce_score:.3f}({ce_name})"
        )
        if servant_only:
            if servant_score >= min_score:
                if prefer_grand and not support_row_is_grand(image, row, grand_reference):
                    if match.plain is None:
                        match.plain = (row.index, round(servant_score, 3))
                    continue
                match.index = row.index
                match.score = round(servant_score, 3)
                match.runner_up = 0.0
                match.accepted = True
                match.notes.append(
                    f"第 {row.index} 行命中：只按从者 {servant_score:.3f}（未指定礼装）"
                    + ("｜冠位从者 ✓" if prefer_grand else "")
                )
                return match
            continue
        if servant_score >= min_score and ce_score >= min_score:
            if prefer_grand and not support_row_is_grand(image, row, grand_reference):
                if match.plain is None:
                    match.plain = (row.index, round(servant_score, 3))
                continue
            match.index = row.index
            match.score = round(servant_score, 3)
            match.runner_up = round(ce_score, 3)
            match.accepted = True
            match.notes.append(
                f"第 {row.index} 行命中：从者 {servant_score:.3f}｜礼装「{ce_name}」{ce_score:.3f}"
                + ("｜冠位从者 ✓" if prefer_grand else "")
            )
            return match
    if prefer_grand and match.plain is not None:
        # 这一帧里有"满足规则但不是冠位"的行：**不替调用方兜底**（要先把整张列表翻到底）。
        plain_index, plain_score = match.plain
        match.notes.append(
            f"第 {plain_index} 行满足规则但**不是冠位从者**（从者 {plain_score:.3f}）："
            "这一屏不能就这么定了，继续往下翻；整张列表都没有冠位才用它"
        )
    match.index = 0
    match.score = -2.0
    match.runner_up = 0.0
    match.accepted = False
    match.notes.append(
        ("没有一行的从者指纹命中：" if servant_only else "没有一行同时满足「从者 + 礼装白名单」：")
        + "；".join(detail)
    )
    return match


def support_identity_box(
    panel: tuple[int, int, int, int], variant: str = "narrow"
) -> tuple[int, int, int, int]:
    """面板 -> 「宝具 名称」那一行的范围（指纹范围，**不含「等级N」**）。"""
    left, top, right, _bottom = panel
    return (
        left + SUPPORT_IDENTITY_LINE["left"],
        top + SUPPORT_IDENTITY_LINE["top"],
        right - SUPPORT_IDENTITY_RIGHT.get(variant, SUPPORT_IDENTITY_LINE["right"]),
        top + SUPPORT_IDENTITY_LINE["bottom"],
    )


def support_grand_label_box(panel: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """面板 -> 肖像底部那条「冠位从者」标签的位置（只有宽块布局才有）。"""
    left, top, _right, _bottom = panel
    frame = SUPPORT_GRAND_LABEL_FRAME
    return (left - frame["left"], top + frame["top"], left - frame["right"], top + frame["bottom"])


def support_row_is_grand(
    image: np.ndarray,
    row: SupportRow,
    reference: np.ndarray | None = None,
    min_score: float = SUPPORT_GRAND_MIN_SCORE,
    shift: int = 16,
) -> bool:
    """这一行是不是**冠位从者**：宽块布局（肖像 + 3 件礼装）且标签指纹命中。

    2026-10-16 用户口径：冠位战里助战可以借冠位从者，**要优先挑这种**。
    判据是"结构 + 标签"两道：窄块布局直接否掉（普通助战），宽块再看肖像底部那
    条「冠位从者」标签跟登记模板的 NCC（模板由用户在真机助战屏上指过的位置裁出）。

    `shift=16`（2026-10-17 实测）：不同帧里面板高度会差 ~9 px（90 vs 81），固定偏移的
    标签框会整体错位，±4 只有 0.14；搜到 ±16 才命中（今天三行 0.965/0.965/1.000，
    登记帧仍是 1.0）。所以这里故意用比礼装/宝具行更大的纵向搜索半径。
    """
    if row.variant != "wide":
        return False
    if reference is None:
        reference = load_support_library("grand").get("冠位从者")
    if reference is None:
        return False
    box = support_grand_label_box(row.panel)
    if box[0] < 0 or box[1] < 0 or box[2] >= image.shape[1] or box[3] >= image.shape[0]:
        return False
    return best_shifted_ncc(image, box, reference, shift) >= min_score


def find_support_rows(image: np.ndarray) -> list[SupportRow]:
    """找出「助战选择」屏里的每一条助战（从上到下）。

    **行锚点是横贯整行的外框亮线**（2026-10-16 改）：两版布局都有它，行距稳定（新版 200、
    旧版 187）；而"找青色面板色带"在新版（冠位从者行）会碎成小块、直接报 0 行 —— 那次把
    助战屏错判成了 overlay。面板仍在**行内**按颜色找，用来定身份块（宝具行）与点击落点。

    检出不足两条（或间距不一致）就返回空列表——说明这不是助战选择屏，调用方必须 fail-stop。
    """
    x0, y0, x1, y1 = SUPPORT_PANEL_SEARCH
    sub = image[y0:y1, x0:x1]
    mask = np.abs(sub - np.array(SUPPORT_PANEL_COLOR)).max(axis=2) <= SUPPORT_PANEL_TOLERANCE
    counts = mask.sum(axis=1)
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for offset, count in enumerate(counts):
        if count >= SUPPORT_PANEL_BAND_COUNT and start is None:
            start = offset
        elif count < SUPPORT_PANEL_BAND_COUNT and start is not None:
            if offset - start >= SUPPORT_PANEL_MIN_BAND:
                bands.append((start, offset - 1))
            start = None
    if start is not None and len(counts) - start >= SUPPORT_PANEL_MIN_BAND:
        bands.append((start, len(counts) - 1))
    rows: list[SupportRow] = []
    panels: list[tuple[int, int, int]] = []   # (left, right, panel_top)
    for top, band_bottom in bands:
        band = mask[top : band_bottom + 1]
        column_hits = band.sum(axis=0)
        columns = np.nonzero(column_hits >= max(3, band.shape[0] * 0.25))[0]
        if columns.size == 0:
            continue
        # 取**最长连续段**当面板：礼装缩略图里也有相近颜色，用 min/max 会把面板左边界
        # 拉到礼装区去（2026-10-16 实测：新版第 1 行因此被算成 225..813）
        best_start = best_end = columns[0]
        run_start = columns[0]
        for index in range(1, columns.size):
            if columns[index] - columns[index - 1] > 6:
                if columns[index - 1] - run_start > best_end - best_start:
                    best_start, best_end = run_start, columns[index - 1]
                run_start = columns[index]
        if columns[-1] - run_start > best_end - best_start:
            best_start, best_end = run_start, columns[-1]
        left, right = x0 + int(best_start), x0 + int(best_end)
        width = right - left
        # 窄块布局（普通助战）面板 ≈570；宽块布局（冠位从者）≈427 ⇒ 下限取 320，
        # 真正的"不是面板"由颜色命中本身挡掉
        if width < SUPPORT_PANEL_MIN_WIDTH_WIDE:
            continue
        panel_top = y0 + top
        panels.append((left, right, panel_top, width))
    if len(panels) < SUPPORT_MIN_ROWS:
        return []
    # 行距一致性 + **按行距吸附**：最下面一行被屏幕下沿裁切时，色带起点会偏早
    # （2026-10-16 实测：新版第 3 行检到 651，等距应是 665）。吸附后身份块越界会被
    # 打分环节自然跳过（拿不到指纹范围 ⇒ 记 −2，不算命中）。
    gaps = [later[2] - earlier[2] for earlier, later in zip(panels, panels[1:])]
    if any(gap < SUPPORT_ROW_PITCH[0] or gap > SUPPORT_ROW_PITCH[1] for gap in gaps):
        return []
    # 行距一致性：容差 ±60（2026-10-17 放宽，原 ±20）。列表被滑到中间、或某一行被"悬浮详情"
    # 挡住时，那一条色带的起点会偏（实测 160 vs 200）；旧规则会整屏报 0 行 ⇒ "翻着找行"直接
    # 进行不下去。偏掉的行由指纹打分自然淘汰（认不出就不点），比"整屏判死"安全得多。
    if len(gaps) > 1 and max(gaps) - min(gaps) > 60:
        return []
    # 行距取**最大**的那个间距：被裁的那一行色带起点会偏早（间距变小），所以最大间距才可信。
    pitch = max(gaps)
    snapped_top = panels[0][2]
    for index, (left, right, panel_top, width) in enumerate(panels):
        expected = snapped_top + pitch * index
        if abs(panel_top - expected) > 8:
            panel_top = expected
        panel_bottom = min(image.shape[0] - 1, panel_top + SUPPORT_PANEL_HEIGHT - 1)
        panel = (left, panel_top, right, panel_bottom)
        variant = _support_variant(width)
        rows.append(
            SupportRow(
                index=index + 1,
                panel=panel,
                identity=support_identity_box(panel, str(variant["name"])),
                center=((left + right) // 2, (panel[1] + panel[3]) // 2),
                cell=_support_cell_box_with(panel, variant["cell"]),
                ce=_support_ce_box_with(panel, variant),
                variant=str(variant["name"]),
            )
        )
    return rows


def _support_variant(panel_width: int) -> dict[str, Any]:
    """按面板宽度选布局变体（窄块 = 普通助战；宽块 = 冠位从者，左边块带 3 件礼装）。"""
    for variant in SUPPORT_CELL_VARIANTS:
        if panel_width < int(variant["max_width"]):
            return variant
    return SUPPORT_CELL_VARIANTS[-1]


def block_gray(image: np.ndarray, box: tuple[int, int, int, int], shape: tuple[int, int]) -> np.ndarray:
    """取一块区域的灰度图，并缩放到参照指纹的尺寸（面板检出有 ±1-3 px 抖动）。"""
    left, top, right, bottom = box
    crop = _gray(image[top : bottom + 1, left : right + 1])
    return crop if crop.shape == shape else _resize_gray(crop, (shape[1], shape[0]))


@dataclass
class SupportMatch:
    index: int | None = None
    score: float = 0.0
    runner_up: float = 0.0
    margin: float = 0.0
    scores: list[tuple[int, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    accepted: bool = False
    # `prefer_grand=True`（只认冠位）时，把这一帧里"满足规则但不是冠位从者"的第一个候选
    # 记在这——**交给调用方决定**要不要兜底（调用方要先把整张列表翻到底，见 battle_runner）。
    plain: tuple[int, float] | None = None

    def report(self) -> str:
        # 分数 -2 表示那一行的指纹范围取不出来（例如最后一行被屏幕下沿截断）
        detail = " ".join(
            f"第{i}行={'—' if s < -1 else format(s, '.3f')}" for i, s in self.scores
        ) or "无候选行"
        verdict = f"第 {self.index} 行" if self.accepted else "未命中"
        return f"助战身份块：{verdict}（{detail}；差距 {self.margin:.3f}）"


def match_support_row(
    image: np.ndarray,
    reference: np.ndarray,
    rows: Sequence[SupportRow] | None = None,
    min_score: float = SUPPORT_MIN_SCORE,
    min_margin: float = SUPPORT_MIN_MARGIN,
    shift: int = SUPPORT_SHIFT,
) -> SupportMatch:
    """按登记过的身份块指纹挑一行。挑不出就 accepted=False（不猜行）。

    位移搜索必须是**密集**的：2026-10-15 实测「连续出击」那条路上，同一行的指纹块
    相对登记位置只偏 (1, 0) 像素，但旧实现只试 0/±3 这 9 个格点，最大值 0.794（<0.85
    门槛）被判成"找不到"，于是停手；改成逐个像素搜到 ±6 后，同一帧升到 0.883 正常命中。
    """
    match = SupportMatch()
    candidates = list(rows) if rows is not None else find_support_rows(image)
    if not candidates:
        match.notes.append("这帧里找不到助战行（不是助战选择屏？）")
        return match
    for row in candidates:
        best = -2.0
        for dy in range(-shift, shift + 1):
            for dx in range(-shift, shift + 1):
                box = (row.identity[0] + dx, row.identity[1] + dy, row.identity[2] + dx, row.identity[3] + dy)
                if box[0] < 0 or box[1] < 0 or box[2] >= image.shape[1] or box[3] >= image.shape[0]:
                    continue
                best = max(best, _ncc(block_gray(image, box, reference.shape), reference))
        match.scores.append((row.index, round(best, 3)))
    match.scores.sort(key=lambda item: -item[1])
    match.index = match.scores[0][0]
    match.score = match.scores[0][1]
    match.runner_up = match.scores[1][1] if len(match.scores) > 1 else 0.0
    match.margin = round(match.score - match.runner_up, 3)
    if match.score < -1:
        match.accepted = False
        match.notes.append(
            "第 %d 行的指纹范围取不出来（那一行可能被屏幕下沿截断）：停手" % match.index
        )
    elif match.score < min_score:
        match.accepted = False
        match.notes.append(f"最高分 {match.score:.3f} < 门槛 {min_score}（那一行可能不在列表里了）")
    elif match.margin < min_margin:
        match.accepted = False
        match.notes.append(f"最高分与次高只差 {match.margin:.3f} < 门槛 {min_margin}（两行难分，不猜）")
    else:
        match.accepted = True
    return match


def _support_key_name(key: str) -> str:
    safe = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in str(key or ""))
    return safe or "default"


def support_reference_paths(key: str, directory: Path | None = None) -> tuple[Path, Path]:
    base = Path(directory) if directory is not None else support_dir()
    name = _support_key_name(key)
    return base / f"{name}.json", base / f"{name}.block.png"


def save_support_reference(
    key: str,
    image: np.ndarray,
    row: SupportRow,
    directory: Path | None = None,
    note: str = "",
) -> Path:
    """把某一行的身份块存成指纹（首次登记 / 人工指行时调用）。"""
    meta_path, image_path = support_reference_paths(key, directory)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    block = image[row.identity[1] : row.identity[3] + 1, row.identity[0] : row.identity[2] + 1]
    Image.fromarray(block.astype(np.uint8)).save(image_path)
    meta_path.write_text(
        json.dumps(
            {
                "key": _support_key_name(key),
                "version": SUPPORT_REFERENCE_VERSION,
                "region": "np_line",
                "offsets": SUPPORT_IDENTITY_LINE,
                "block_image": image_path.name,
                "captured_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                "row_index": row.index,
                "panel": list(row.panel),
                "identity": list(row.identity),
                "min_score": SUPPORT_MIN_SCORE,
                "note": note,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return meta_path


def load_support_reference(key: str, directory: Path | None = None) -> tuple[np.ndarray, dict]:
    """读出「key -> (身份块灰度指纹, 元数据)」。没登记过就抛 FileNotFoundError。"""
    meta_path, image_path = support_reference_paths(key, directory)
    if not meta_path.exists():
        raise FileNotFoundError(f"没有登记过助战行指纹：{meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if int(meta.get("version") or 0) != SUPPORT_REFERENCE_VERSION:
        raise FileNotFoundError(
            f"助战行指纹是旧格式（version={meta.get('version')}，当前 {SUPPORT_REFERENCE_VERSION}）："
            "请用 --pick-support-only --support-row N 重新登记一次"
        )
    image_path = meta_path.parent / str(meta.get("block_image") or image_path.name)
    if not image_path.exists():
        raise FileNotFoundError(f"助战行指纹图丢了：{image_path}")
    with Image.open(image_path) as handle:
        gray = _gray(np.asarray(handle.convert("RGB")).astype(np.int16))
    return gray, meta


# ---------------------------------------------------------------------------
# 固定按钮模板（局部匹配）
#
# 用途：那些"就只有这一处、位置固定、但手量坐标点真机不合规"的按钮——例如「队伍确认」
# 屏右下角的「开始任务」。取法：把按钮连一点背景整块裁下来存成模板（登记时人工确认），
# 运行时在**限定搜索框**内滑窗做归一化互相关，取最高分；分数达标才认为按钮在、并且
# 落点由匹配位置给出（不是手量的）。
# ---------------------------------------------------------------------------

SUPPORT_BUTTON_MIN_SCORE = 0.90


def button_dir() -> Path:
    return Path(config.GAME_ASSISTANT_EXECUTION_DIR) / "templates" / "buttons"


@dataclass
class ButtonMatch:
    name: str
    score: float = 0.0
    center: tuple[int, int] | None = None
    box: tuple[int, int, int, int] | None = None
    accepted: bool = False
    notes: list[str] = field(default_factory=list)

    def report(self) -> str:
        detail = f"分数 {self.score:.3f}" if self.center else "未命中"
        if not self.accepted and self.score:
            detail += f"（< 门槛）"
        return f"按钮「{self.name}」：{detail}" + ("，落点 " + str(self.center) if self.accepted else "")


def save_button_template(
    name: str, image: np.ndarray, box: tuple[int, int, int, int],
    search_box: tuple[int, int, int, int] | None = None,
    min_score: float = SUPPORT_BUTTON_MIN_SCORE, note: str = "",
) -> Path:
    """把按钮处裁下来登记成模板（人工确认过位置再用）。"""
    meta_path, image_path = button_reference_paths(name)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    left, top, right, bottom = box
    template = image[top : bottom + 1, left : right + 1]
    Image.fromarray(template.astype(np.uint8)).save(image_path)
    if search_box is None:
        margin = 60
        search_box = (
            max(0, left - margin), max(0, top - margin),
            min(image.shape[1] - 1, right + margin), min(image.shape[0] - 1, bottom + margin),
        )
    meta_path.write_text(
        json.dumps(
            {
                "name": name,
                "template": image_path.name,
                "captured_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                "box": list(box),
                "search_box": list(search_box),
                "min_score": min_score,
                "note": note,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return meta_path


def button_reference_paths(name: str, directory: Path | None = None) -> tuple[Path, Path]:
    base = Path(directory) if directory is not None else button_dir()
    safe = _support_key_name(name)
    return base / f"{safe}.json", base / f"{safe}.png"


def load_button_template(name: str, directory: Path | None = None) -> tuple[np.ndarray, dict]:
    meta_path, image_path = button_reference_paths(name, directory)
    if not meta_path.exists():
        raise FileNotFoundError(f"没有登记过按钮模板：{meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    image_path = meta_path.parent / str(meta.get("template") or image_path.name)
    if not image_path.exists():
        raise FileNotFoundError(f"按钮模板图丢了：{image_path}")
    with Image.open(image_path) as handle:
        gray = _gray(np.asarray(handle.convert("RGB")).astype(np.int16))
    return gray, meta


def match_button(
    image: np.ndarray, name: str, directory: Path | None = None,
    min_score: float | None = None, step: int = 3, refine: int = 3,
) -> ButtonMatch:
    """在登记过的搜索框里找这个按钮。找不到 / 没登记 / 分数不够都返回 accepted=False。"""
    match = ButtonMatch(name=name)
    try:
        template, meta = load_button_template(name, directory)
    except FileNotFoundError as exc:
        match.notes.append(str(exc))
        return match
    threshold = float(meta.get("min_score") if min_score is None else min_score)
    x0, y0, x1, y1 = [int(v) for v in meta.get("search_box") or (0, 0, image.shape[1] - 1, image.shape[0] - 1)]
    height, width = template.shape
    best_score, best_left, best_top = -2.0, x0, y0
    for top in range(max(0, y0), max(0, min(image.shape[0] - height, y1 - height)) + 1, max(1, step)):
        for left in range(max(0, x0), max(0, min(image.shape[1] - width, x1 - width)) + 1, max(1, step)):
            score = _ncc(block_gray(image, (left, top, left + width - 1, top + height - 1), template.shape), template)
            if score > best_score:
                best_score, best_left, best_top = score, left, top
    # 粗搜之后再在原地 ±refine 细搜一次
    for top in range(best_top - refine, best_top + refine + 1):
        for left in range(best_left - refine, best_left + refine + 1):
            if left < 0 or top < 0 or left + width > image.shape[1] or top + height > image.shape[0]:
                continue
            score = _ncc(block_gray(image, (left, top, left + width - 1, top + height - 1), template.shape), template)
            if score > best_score:
                best_score, best_left, best_top = score, left, top
    match.score = round(best_score, 3)
    match.box = (best_left, best_top, best_left + width - 1, best_top + height - 1)
    match.center = (best_left + width // 2, best_top + height // 2)
    if best_score < threshold:
        match.notes.append(f"最高分 {best_score:.3f} < 门槛 {threshold}：这个屏上没有该按钮")
        return match
    match.accepted = True
    return match


# ---------------------------------------------------------------------------
# 行动力读数（地图屏左下「行动力 xx/148」下面那根条）
#
# 为什么不直接认数字：那行白字压在御主立绘上（立绘大片是亮的、还有高对比边缘），
# 白阈值 / 暗描边 / 两帧相减三种分割都分不干净（2026-10-14 实测，证据见 work-log）。
# 改为**读条**：条的位置固定（x 185..322、y 695），填充从左侧开始、空槽是纯黑；
# 注意 AP 低时填充是**深绿**（实测 (2,89,6)），亮度门槛设高会把低 AP 全读成 0。
#
# 校准（5 帧真实截图，填充端 x 与已知 AP）：199↔23 / 206↔30 / 240↔62 / 309↔127 /
# 315↔133；线性拟合得 px/AP ≈ 1.055、零点 174.7，残差 ±2 AP。条装满时报"≥148"。
# ⚠️ 换分辨率 / UI 改版后要重新校准这几个常数。
# ---------------------------------------------------------------------------

AP_BAR_Y = 695
AP_BAR_LEFT = 185
AP_BAR_RIGHT = 322
AP_BAR_ZERO_X = 174.7
AP_BAR_PX_PER_AP = 1.055
AP_BAR_MAX_AP = 148


@dataclass
class ApReading:
    estimate: int | None
    fill_end_x: int | None
    saturated: bool = False
    readable: bool = True
    notes: list[str] = field(default_factory=list)

    def report(self) -> str:
        if not self.readable or self.estimate is None:
            return "行动力读数：读不出（" + "；".join(self.notes) + "）"
        suffix = "，条已满（只能保证 ≥148）" if self.saturated else ""
        return f"行动力 ≈ {self.estimate}{suffix}"


def read_ap(image: np.ndarray) -> ApReading:
    """按行动力条的填充端估算当前 AP（±2；条装满时报"≥148"）。"""
    reading = ApReading(estimate=None, fill_end_x=None)
    if image.shape[0] <= AP_BAR_Y or image.shape[1] <= AP_BAR_RIGHT:
        reading.readable = False
        reading.notes.append("画面尺寸不匹配")
        return reading
    row = image[AP_BAR_Y, AP_BAR_LEFT : AP_BAR_RIGHT + 1]
    red, green, blue = row[:, 0], row[:, 1], row[:, 2]
    green_fill = (green > red + 30) & (green > blue + 30) & (green > 55)
    yellow_fill = (red > 190) & (green > 165) & (blue < 130) & (red - blue > 70) & (green - blue > 60)
    fill = green_fill | yellow_fill
    columns = [AP_BAR_LEFT + index for index, hit in enumerate(fill) if hit]
    if not columns:
        reading.readable = False
        reading.notes.append("这一行没找到填充（不是地图屏？或者条被遮住了）")
        return reading
    reading.fill_end_x = int(columns[-1])
    if reading.fill_end_x >= AP_BAR_RIGHT - 2:
        reading.estimate = AP_BAR_MAX_AP
        reading.saturated = True
        return reading
    reading.estimate = max(0, int(round((reading.fill_end_x - AP_BAR_ZERO_X) / AP_BAR_PX_PER_AP)))
    return reading
