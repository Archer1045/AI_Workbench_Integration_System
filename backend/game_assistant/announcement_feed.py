"""国服官方公告 → 候选日程（**只落 candidate，永不自动确认**）。

来源（2026-10-15 打通，过程值得记下来）：
  * 列表：`https://api.biligame.com/news/list.action?gameExtensionId=45&positionId=2`
  * 正文：`https://api.biligame.com/news/{id}.action`

  怎么找到的：官网 H5 页引的 `static.biligame.com/fgo/js/mc-rhythm-news.js` 里写着
  `gameExtensionId: 45`，真正的请求格式在同站的 `mods_sea/apiUtils_sea.2.3.js`（**`.action`
  后缀 + `positionId`**）。此前试的 `api.biligame.com/news/list`（无后缀）恒回 `totalNum=0`，
  搜索引擎也拿不到新鲜公告，所以这条链路值得写死在注释里。

口径：
  * 只挑**活动类**公告（标题含「举办！」「开幕！」等）；卡池 / 维护 / 说明类不进日程
    （维护窗口要是进了日程，会被"下一个活动"读到、污染回答，将来单独存 `maintenance_cn.json`）；
  * 时间从正文里**保守**抽取：公告常写"2026年10月15日（周四）维护后~"、"13:59为止"，
    能抽到时刻就写时刻，只有日期就写 00:00 并在 `note` 里标明"公告只给到日/维护后"——**不猜**；
  * `event_id = official-{公告id}` ⇒ 幂等：重复拉不会写重复条目；
  * **已经被人确认过的条目不动**（不能把 confirmed 降级回候选）。
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import config

from . import schedule

SHANGHAI = ZoneInfo("Asia/Shanghai")
NEWS_HOST = "https://api.biligame.com/news"
GAME_EXTENSION_ID = 45
POSITION_ID = 2
USER_AGENT = "Mozilla/5.0 (compatible; ai-workbench game assistant)"
DEFAULT_PAGE_SIZE = 30
FETCH_TIMEOUT = 20.0

# 活动类公告的标题特征（2026-10-15 观察到的写法）
EVENT_TITLE_MARKERS = ("举办！", "开幕！", "开放！", "上线！")
# 明确不是活动日程的（卡池 / 维护 / 说明 / 概率公示）：卡池更新不是"活动开放"
SUMMON_MARKERS = ("推荐召唤", "召唤")
NON_EVENT_MARKERS = ("维护公告", "概率公示", "问题的说明", "补偿", "问卷调查", "通知")

_DATE_RE = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
_TAGS = re.compile(r"<[^>]+>")
# 维护公告里的窗口：`【维护时间】2026年10月15日 14:00 ～ 10月15日 19:00（预计）`
_MAINT_RANGE = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})\s*[～~至\-—–]+\s*"
    r"(?:(\d{4})年)?(?:(\d{1,2})月)?(\d{1,2})日\s*(\d{1,2}):(\d{2})"
)
MAINTENANCE_VERSION = 1
MAINTENANCE_KEEP = 20


def _strip_html(raw: str) -> str:
    text = _TAGS.sub("\n", str(raw or ""))
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        text = text.replace(entity, char)
    return re.sub(r"\n{2,}", "\n", text).strip()


def classify(title: str) -> str:
    """公告分类：`event` / `summon` / `maintenance` / `other`。"""
    text = str(title or "")
    if any(marker in text for marker in SUMMON_MARKERS):
        return "summon"
    if any(marker in text for marker in NON_EVENT_MARKERS):
        return "maintenance" if "维护公告" in text else "other"
    if any(marker in text for marker in EVENT_TITLE_MARKERS):
        return "event"
    return "other"


def extract_dates(text: str, reference: datetime | None = None) -> tuple[list[datetime], list[str]]:
    """抽出正文里所有日期/时刻（年份可省），并给每条日期一句"这个时刻是怎么来的"备注。

    公告的写法很杂，实测两种都要认：
      * `2026年10月15日（周四）维护后~`（只有日期，时刻得按 00:00 记并标注）；
      * `2026年9月24日（周四）维护后~10月15日（周四）13:59为止`（**第二个日期不带年份**）。
    年份省略时沿用上一个出现过的年份；月份比上一个小就按跨年 +1 处理（9月→次年10月）。
    """
    reference = reference or datetime.now(SHANGHAI)
    dates: list[datetime] = []
    notes: list[str] = []
    year = reference.year
    previous: datetime | None = None
    for match in _DATE_RE.finditer(text):
        explicit_year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
        if explicit_year:
            year = int(explicit_year)
        elif previous is not None and previous.month == 12 and month == 1:
            year += 1        # 只认"12月 → 次年1月"这一种跨年；别的月份更小一律沿用当前年份
        tail = text[match.end() : match.end() + 16]
        clock = _TIME_RE.search(tail)
        hour = minute = 0
        if clock:
            hour, minute = int(clock.group(1)), int(clock.group(2))
            if hour > 23 or minute > 59:
                hour = minute = 0
        try:
            value = datetime(year, month, day, hour, minute, tzinfo=SHANGHAI)
        except ValueError:
            continue
        if clock:
            notes.append(f"{value:%Y-%m-%d %H:%M}")
        elif "维护后" in tail:
            notes.append(f"{value:%Y-%m-%d} 维护后（按 00:00 记，以游戏内为准）")
        else:
            notes.append(f"{value:%Y-%m-%d}（公告没写时刻，按 00:00 记）")
        dates.append(value)
        previous = value
    return dates, notes


# 只有这些标记段落里的日期才算"活动窗口"。2026-10-15 实测教训：拿"正文里所有日期取跨度"
# 会把卡池、领取期、别的段落里的日期一起算进来，窗口直接飘到 2027 年 ⇒ 只能按段落取。
WINDOW_MARKERS = ("活动时间", "举办时间", "开放时间", "活动期间")


def _window_sections(text: str) -> list[tuple[int, str, str]]:
    """切出「活动时间 / 开放时间」这类段落，按**出现位置**返回 `(位置, 标记, 段落)`。

    段落终止符取"第一个日期之后"的 `◆` / 换行：公告常写成
    `◆ 活动时间（为期3周）◆ 2026年9月24日（周四）维护后~10月15日（周四）13:59为止 ◆ 活动参加条件 ◆`，
    标记和值之间就隔着一个 ◆，切早了整段就废了。
    """
    sections: list[tuple[int, str, str]] = []
    for marker in WINDOW_MARKERS:
        for match in re.finditer(marker, text):
            tail = text[match.end() : match.end() + 200]
            tail = re.sub(r"^[\s◆▶※:：、（）()]+", "", tail)
            first_date = _DATE_RE.search(tail)
            limit = len(tail)
            for separator in ("◆", "\n"):
                start = first_date.end() if first_date else 0
                position = tail.find(separator, start)
                if position != -1:
                    limit = min(limit, position)
            tail = tail[:limit].strip()
            if tail:
                sections.append((match.start(), marker, tail))
    sections.sort(key=lambda item: item[0])
    return sections


def parse_window(
    text: str, reference: datetime | None = None
) -> tuple[datetime | None, datetime | None, list[str]]:
    """从正文的「活动时间」段落里抽 `(开始, 结束, 备注)`；抽不到就返回 None——**不猜**。

    口径（2026-10-15 定）：
      * 只在 `WINDOW_MARKERS` 标出的段落里取日期，且取**第一个有日期的段落**；
      * 段落里只有 1 个日期 ⇒ 视为`常驻 / 公告没写结束`，`ends_at=None` 并写进备注
        （冠位戴冠战就是这种：关卡常驻，只有"免风暴罐期"另说）；
      * 完全标不出段落 ⇒ **不给窗口**，只把抽到的日期列进备注请人工核对。
    """
    reference = reference or datetime.now(SHANGHAI)
    for _position, marker, section in _window_sections(text):
        dates, date_notes = extract_dates(section, reference)
        if not dates:
            continue
        starts_at, ends_at = min(dates), max(dates)
        if len(dates) == 1:
            ends_at = None
            notes = [f"「{marker}」段落只有一个日期（常驻或公告没写结束）：结束时间待人工核对"]
        else:
            notes = [f"时间取自「{marker}」段落"]
        notes.extend(date_notes)
        if starts_at and ends_at and (ends_at - starts_at).days > 200:
            notes.append("跨度超过 200 天：请核对是不是把别的段落算进来了")
        return starts_at, ends_at, notes
    dates, date_notes = extract_dates(text, reference)
    if not dates:
        return None, None, ["正文里没找到可用的日期：时间待人工核对"]
    return None, None, ["正文里没有「活动时间 / 开放时间」这类段落，时间待人工核对"] + date_notes


def _request_json(url: str, timeout: float = FETCH_TIMEOUT) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def list_announcements(page_size: int = DEFAULT_PAGE_SIZE, page_num: int = 1) -> list[dict[str, Any]]:
    """拉官方公告列表（第一条是置顶的概率公示，所以按发布时间自己排一遍）。"""
    query = urllib.parse.urlencode(
        {
            "gameExtensionId": GAME_EXTENSION_ID,
            "positionId": POSITION_ID,
            "pageNum": page_num,
            "pageSize": page_size,
        }
    )
    payload = _request_json(f"{NEWS_HOST}/list.action?{query}")
    rows = payload.get("data") or []
    items = [
        {
            "id": int(row.get("id") or 0),
            "title": str(row.get("title") or ""),
            "create_time": str(row.get("createTime") or ""),
            "modify_time": str(row.get("modifyTime") or ""),
        }
        for row in (rows if isinstance(rows, list) else [])
    ]
    items.sort(key=lambda item: item["create_time"], reverse=True)
    return items


def fetch_announcement(news_id: int) -> dict[str, Any]:
    """拉一条公告正文（去标签后的纯文本）。"""
    payload = _request_json(f"{NEWS_HOST}/{int(news_id)}.action")
    row = payload.get("data") or {}
    return {
        "id": int(row.get("id") or news_id),
        "title": str(row.get("title") or ""),
        "create_time": str(row.get("createTime") or ""),
        "body": _strip_html(row.get("content") or ""),
    }


def _clean_title(title: str) -> str:
    text = re.sub(r"^【[^】]*】", "", str(title or "")).strip()
    for quote in ("「", "」", "『", "』"):
        text = text.replace(quote, "")
    text = text.strip()
    text = re.sub(r"[！!]+$", "", text).strip()
    # 公告标题末尾常带动词（"…举办！" "…开幕！"），日程标题里留着没意义
    text = re.sub(r"(举办|开幕|开放|上线|开启)$", "", text).strip()
    return text or str(title or "").strip()


def maintenance_path() -> Path:
    """维护窗口单独一个文件：它**不能**进 `upcoming_events_cn.json`——那个文件会被
    「下一个活动」读到，混进维护日就污染回答（2026-10-15 口径）。"""
    return Path(config.GAME_ASSISTANT_KB_DIR) / "maintenance_cn.json"


def load_maintenance() -> list[dict[str, Any]]:
    """读维护窗口；文件不存在 / 坏了都当空。"""
    try:
        payload = json.loads(maintenance_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    return [item for item in items or [] if isinstance(item, dict)]


def parse_maintenance_window(body: str) -> tuple[datetime | None, datetime | None, list[str]]:
    """从维护公告正文里抽维护窗口；抽不到就返回 None（**不猜时长**）。"""
    marker = body.find("维护时间")
    section = body[marker : marker + 120] if marker != -1 else body[:400]
    match = _MAINT_RANGE.search(section)
    if not match:
        return None, None, ["公告里没写清维护窗口（起止时刻）：待人工核对"]
    year = int(match.group(1))
    starts_at = datetime(
        year, int(match.group(2)), int(match.group(3)), int(match.group(4)), int(match.group(5)),
        tzinfo=SHANGHAI,
    )
    end_year = int(match.group(6)) if match.group(6) else year
    end_month = int(match.group(7)) if match.group(7) else int(match.group(2))
    if end_month < int(match.group(2)):
        end_year += 1
    ends_at = datetime(
        end_year, end_month, int(match.group(8)), int(match.group(9)), int(match.group(10)),
        tzinfo=SHANGHAI,
    )
    notes = ["维护窗口（预计）：截止时刻以游戏内为准"]
    if "预计" in section:
        notes.append("公告写的是预计时间")
    return starts_at, ends_at, notes


def _save_maintenance(items: list[dict[str, Any]]) -> None:
    path = maintenance_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(items, key=lambda item: str(item.get("starts_at") or ""), reverse=True)
    path.write_text(
        json.dumps(
            {"version": MAINTENANCE_VERSION, "items": ordered[:MAINTENANCE_KEEP]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _refresh_maintenance(
    announcements: list[dict[str, Any]],
    moment: datetime,
    detail_fetcher: Callable[[int], dict[str, Any]],
) -> list[dict[str, Any]]:
    """把维护公告的窗口收进 `maintenance_cn.json`（只记窗口，不进活动日程）。"""
    stored = {str(item.get("announcement_id")): item for item in load_maintenance()}
    noticed: list[dict[str, Any]] = []
    for item in announcements:
        if classify(item["title"]) != "maintenance":
            continue
        if str(item["id"]) in stored:
            continue
        try:
            detail = detail_fetcher(int(item["id"]))
        except Exception:
            continue
        starts_at, ends_at, notes = parse_maintenance_window(detail.get("body") or "")
        if starts_at is None:
            continue
        if ends_at is not None and ends_at < moment - timedelta(days=180):
            continue
        record = {
            "announcement_id": str(item["id"]),
            "title": item["title"],
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat() if ends_at else None,
            "source_url": f"https://game.bilibili.com/fgo/news.html#!news/0/1/{item['id']}",
            "note": "；".join(notes),
        }
        stored[record["announcement_id"]] = record
        noticed.append(record)
    if noticed:
        _save_maintenance(list(stored.values()))
    return noticed


def refresh_schedule(
    *,
    now: datetime | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    limit: int = 12,
    list_fetcher: Callable[..., list[dict[str, Any]]] = list_announcements,
    detail_fetcher: Callable[[int], dict[str, Any]] = fetch_announcement,
) -> dict[str, Any]:
    """把最近的活动类公告落成**候选**日程；返回一份给人看的汇总。

    * 已存在的条目：**confirmed 一律跳过**（不许降级），candidate 按最新正文更新；
    * 抓取/解析失败只记进 `errors`，不抛异常——页面不该因为官网抖动而挂。
    """
    moment = now or datetime.now(SHANGHAI)
    result: dict[str, Any] = {
        "added": [], "updated": [], "skipped": [], "stale": [], "errors": [], "checked": 0,
    }
    try:
        announcements = list_fetcher(page_size=page_size)
    except Exception as exc:  # 官网抖动 / 断网：只记一句
        result["errors"].append(f"拉公告列表失败：{exc}")
        return result
    existing = {item.event_id: item for item in schedule.load_schedule()}
    event_announcements = [item for item in announcements if classify(item["title"]) == "event"]
    result["maintenance"] = _refresh_maintenance(announcements, moment, detail_fetcher)
    for item in event_announcements[: max(1, int(limit))]:
        event_id = f"official-{item['id']}"
        current = existing.get(event_id)
        if current is not None and current.status == schedule.STATUS_CONFIRMED:
            result["skipped"].append(
                {"event_id": event_id, "title": current.title, "why": "已确认，不动"}
            )
            continue
        result["checked"] += 1
        try:
            detail = detail_fetcher(int(item["id"]))
        except Exception as exc:
            result["errors"].append(f"拉公告 {item['id']} 失败：{exc}")
            continue
        starts_at, ends_at, notes = parse_window(detail.get("body") or "", moment)
        title = _clean_title(item["title"])
        # 已经结束的旧公告不进日程：日程是"接下来会发生什么"，不是历史归档
        # （没有结束时间的（常驻/未写）只在开始时间还不算太旧时收进来）。
        if ends_at is not None and ends_at < moment:
            result["stale"].append({"event_id": event_id, "title": title, "why": "公告里的时间已过"})
            continue
        if ends_at is None and starts_at is not None and starts_at < moment - timedelta(days=30):
            result["stale"].append({"event_id": event_id, "title": title, "why": "没有结束时间且开始时间已过 30 天"})
            continue
        note = "；".join(notes)[:400]
        if starts_at is None:
            note = ((note + "；") if note else "") + "需要人工核对时间后再确认"
        payload = {
            "event_id": event_id,
            "title": title,
            "server": "CN",
            "starts_at": starts_at.isoformat() if starts_at else None,
            "ends_at": ends_at.isoformat() if ends_at else None,
            "source_title": f"国服官方公告 {item['id']}：{item['title']}",
            "source_url": f"https://game.bilibili.com/fgo/news.html#!news/0/1/{item['id']}",
            "note": note,
        }
        schedule.upsert_event(payload, confirm=False)
        bucket = "updated" if current is not None else "added"
        result[bucket].append(
            {"event_id": event_id, "title": title, "starts_at": payload["starts_at"]}
        )
    result["candidate_total"] = sum(
        1 for item in schedule.load_schedule() if item.status == schedule.STATUS_CANDIDATE
    )
    return result


def _main(argv: list[str] | None = None) -> int:  # pragma: no cover - 手工跑的小工具
    import argparse

    parser = argparse.ArgumentParser(description="把国服官方公告刷成候选日程（永不自动确认）")
    parser.add_argument("--limit", type=int, default=12, help="最多处理多少条活动类公告")
    args = parser.parse_args(argv)
    print(json.dumps(refresh_schedule(limit=args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
