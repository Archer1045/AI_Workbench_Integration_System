"""Parse Mooncell quest-config sections into real 3T CombatProfiles.

The parser is deliberately narrow. It reads the standard FGO Wiki「关卡配置」
battle table for one free quest and extracts the three battle rows (class,
level, HP). It never guesses a value it cannot see: anything unreadable or
missing is reported instead of being filled in.

Parsed data is public reference material, not in-game verification. Profiles
built here are written with ``mock=False`` and ``verified=False`` so that the
execution preflight still refuses to run them until a human confirms the
numbers in game.
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .combat_domain import CombatProfile, EnemyUnit, EnemyWave

_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = r'<span class="mw-headline" id="{heading}">'
_BATTLE_RE = re.compile(r"BATTLE\s*(\d)\s*/\s*3")
_LEVEL_RE = re.compile(r"Lv\.(\d+)")
_HP_RE = re.compile(r"HP\s*([\d,]+)")
_CLASS_RE = re.compile(r'<a href="/w/([A-Za-z_]+)" title="[^"]*">[^<]*</a>\)HP')
_ANCHOR_TITLE_RE = re.compile(r'<a[^>]*title="([^"]+)"')


class QuestParseError(ValueError):
    pass


@dataclass
class ParsedEnemy:
    name: str
    class_name: str
    level: int
    hp: int
    source_name: str = ""


@dataclass
class ParsedWave:
    wave_index: int
    label: str
    enemies: list[ParsedEnemy]


@dataclass
class ParsedQuest:
    recommended_level: str
    ap_cost: int
    bond: str
    exp: str
    qp: str
    waves: list[ParsedWave]
    warnings: list[str] = field(default_factory=list)

    @property
    def total_enemy_hp(self) -> int:
        return sum(enemy.hp for wave in self.waves for enemy in wave.enemies)


def _table_end(page_html: str, start: int) -> int:
    """从 `<table` 开始数嵌套，返回**这个** table 的闭合位置（每日任务页里表是层层嵌套的）。"""
    depth = 0
    for match in re.finditer(r"</?table\b", page_html[start:], re.IGNORECASE):
        if match.group(0).lower().startswith("</"):
            depth -= 1
            if depth == 0:
                close = page_html.find(">", start + match.end())
                return (close + 1) if close != -1 else len(page_html)
        else:
            depth += 1
    return len(page_html)


def find_quest_section(page_html: str, heading_id: str) -> str:
    """切出一关的 HTML 段落。两种页面结构都要认（2026-10-15 补第二种）：

    * **活动关卡页**：`<span class="mw-headline" id="关卡名">` ⇒ 切到下一个 `h2`/`h3`（走原逻辑）；
    * **每日任务页（迦勒底之门）**：每个难度是 `<table class="wikitable logo" id="打开宝物库之门&#95;极级">`
      ⇒ 切到**这个表**的闭合标签为止。注意表是嵌套的（单元格里还有敌人表），所以要数嵌套深度；
      不这么切就会把初/中/上/超级/极级 5 个难度全吃进来，解析出 15 面。
    """
    match = re.search(_HEADING_RE.format(heading=re.escape(heading_id)), page_html)
    if match is not None:
        start = match.start()
        candidates = [pos for pos in (page_html.find("<h3", start), page_html.find("<h2", start)) if pos > 0]
        end = min(candidates) if candidates else len(page_html)
        return page_html[start:end]
    generic = re.search(r'id="' + re.escape(heading_id) + r'"', page_html)
    if generic is None:
        raise QuestParseError(f"没有找到关卡标题：{heading_id}")
    tag_start = page_html.rfind("<", 0, generic.start())
    open_end = page_html.find(">", tag_start)
    open_tag = page_html[tag_start : open_end + 1].lower()
    if open_tag.startswith("<table"):
        return page_html[tag_start : _table_end(page_html, tag_start)]
    candidates = [pos for pos in (page_html.find("<h3", tag_start), page_html.find("<h2", tag_start)) if pos > 0]
    return page_html[tag_start : (min(candidates) if candidates else len(page_html))]


def _visible_text(fragment: str) -> str:
    return html_lib.unescape(_TAG_RE.sub("", fragment)).strip()


def _parse_enemy_cell(cell: str) -> ParsedEnemy | None:
    hp_match = _HP_RE.search(cell)
    level_match = _LEVEL_RE.search(cell)
    class_match = _CLASS_RE.search(cell)
    if hp_match is None or level_match is None or class_match is None:
        return None
    # 敌人名字取自 <br /> 之前的可见文字；链接的 title 是敌人类型或真实从者名。
    head = cell.split("<br", 1)[0]
    name = _visible_text(head)
    anchor = _ANCHOR_TITLE_RE.search(cell)
    source_name = html_lib.unescape(anchor.group(1)) if anchor else ""
    if source_name.startswith("敌人一览"):
        source_name = source_name.split("#")[-1]
    return ParsedEnemy(
        name=name or source_name,
        class_name=class_match.group(1),
        level=int(level_match.group(1)),
        hp=int(hp_match.group(1).replace(",", "")),
        source_name=source_name,
    )


def parse_quest_section(section_html: str) -> ParsedQuest:
    level_match = re.search(r"推荐Lv\.\s*([^<\n]+)", section_html)
    ap_match = re.search(r"AP(\d+)", section_html)
    if ap_match is None:
        raise QuestParseError("没有找到 AP 消耗")

    waves: list[ParsedWave] = []
    warnings: list[str] = []
    for row in re.findall(r"<tr>(.*?)</tr>", section_html, re.S):
        header_match = re.search(r"<th[^>]*>(.*?)</th>", row, re.S)
        if header_match is None:
            continue
        label = _visible_text(header_match.group(1)).replace("\n", " ")
        battle_match = _BATTLE_RE.search(label)
        if battle_match is None:
            continue
        wave_index = int(battle_match.group(1))
        enemies: list[ParsedEnemy] = []
        for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S):
            parsed = _parse_enemy_cell(cell)
            if parsed is not None:
                enemies.append(parsed)
        if not enemies:
            warnings.append(f"第 {wave_index} 面没有解析到任何敌人")
        waves.append(ParsedWave(wave_index=wave_index, label=label, enemies=enemies))

    waves.sort(key=lambda item: item.wave_index)
    if [wave.wave_index for wave in waves] != [1, 2, 3]:
        warnings.append(f"解析到的波次索引为 {[wave.wave_index for wave in waves]}，不是 1/2/3")

    def _meta(pattern: str) -> str:
        match = re.search(pattern, section_html)
        return match.group(1) if match else ""

    return ParsedQuest(
        recommended_level=(level_match.group(1).strip() if level_match else ""),
        ap_cost=int(ap_match.group(1)),
        bond=_meta(r"牵绊:([\d,]+)"),
        exp=_meta(r"经验:([\d,]+)"),
        qp=_meta(r"QP:([\d,]+)"),
        waves=waves,
        warnings=warnings,
    )


def build_profile(
    parsed: ParsedQuest,
    *,
    quest_id: str,
    event_id: str,
    quest_name: str,
    source_ids: list[str] | None = None,
    source_url: str = "",
    extra_notes: list[str] | None = None,
) -> CombatProfile:
    waves: list[EnemyWave] = []
    for wave in parsed.waves:
        units = [
            EnemyUnit(
                enemy_id=f"w{wave.wave_index}_{index:02d}",
                name=enemy.name,
                class_name=enemy.class_name,
                level=enemy.level,
                hp=enemy.hp,
                count=1,
                notes=(
                    [f"出处敌人：{enemy.source_name}"]
                    if enemy.source_name and enemy.source_name != enemy.name
                    else []
                ),
            )
            for index, enemy in enumerate(wave.enemies, start=1)
        ]
        waves.append(
            EnemyWave(
                wave_id=f"w{wave.wave_index}",
                wave_index=wave.wave_index,
                units=units,
                notes=[f"来源标签：{wave.label}"],
            )
        )

    notes = [
        f"来源：Mooncell FGO Wiki 关卡配置表 {source_url}".strip(),
        "敌方职阶与血量来自公开 wiki，属于参考数据；需游戏内实测确认后才能标记 verified。",
        "敌人属性（天/地/人）未从该表取得，统一按默认 man 记录。",
        "阵营克制关系由推荐器按我方从者职阶逐场计算，不使用本档案的 class_relation。",
    ]
    notes.extend(parsed.warnings)
    notes.extend(extra_notes or [])

    return CombatProfile(
        quest_id=quest_id,
        event_id=event_id,
        quest_name=quest_name,
        ap_cost=parsed.ap_cost,
        waves=waves,
        verified=False,
        mock=False,
        source_ids=list(source_ids or []),
        notes=notes,
    )


def load_page(url: str = "", html_file: str = "", timeout: int = 30) -> str:
    if html_file:
        return Path(html_file).read_text(encoding="utf-8")
    if not url:
        raise QuestParseError("需要提供 --url 或 --html-file")
    import requests

    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 Mooncell 关卡配置表解析成 3T CombatProfile")
    parser.add_argument("--url", default="")
    parser.add_argument("--html-file", default="")
    parser.add_argument("--heading-id", required=True)
    parser.add_argument("--quest-id", required=True)
    parser.add_argument("--event-id", default="")
    parser.add_argument("--quest-name", required=True)
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--out", required=True, help="输出 profile JSON 路径")
    args = parser.parse_args(argv)

    page = load_page(args.url, args.html_file)
    section = find_quest_section(page, args.heading_id)
    parsed = parse_quest_section(section)
    profile = build_profile(
        parsed,
        quest_id=args.quest_id,
        event_id=args.event_id,
        quest_name=args.quest_name,
        source_ids=args.source_id,
        source_url=args.url,
    )
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"已写入 {target}：推荐Lv.{parsed.recommended_level} AP{parsed.ap_cost} "
        f"三面敌人 {sum(len(wave.enemies) for wave in parsed.waves)} 个，总血量 {parsed.total_enemy_hp}",
        flush=True,
    )
    for warning in parsed.warnings:
        print(f"WARNING: {warning}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
