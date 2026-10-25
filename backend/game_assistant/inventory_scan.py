"""账号库存（概念礼装 / 御主礼装）截图 → VLM 读数 → KB 匹配。

**本模块存在的意义就是"把图片挡在会话之外"**：图片只交给本机 VLM（Ollama），流程把它
读成结构化行，再对 FGO 图鉴库做匹配，最后把 JSON/CSV/HTML 落盘；调用方（人/agent）只读
**摘要**——计数 + 有界的异常列表。这样几百张截图也不会把上下文撑爆。

流程：
  1. 读入截图（用户自己拍的，或用设备层脚本采集的）；
  2. 逐图调用 VLM，抽取每张卡 `{name, level, limit_break}`（严格 JSON；读不出就留空，**不许猜**）；
  3. 归一化后在 KB 里精确匹配（含别名表）；命中就用 KB 的 rarity / cost / atk / hp / effects；
  4. 落盘 `rows.json` / `rows.csv` / `anomalies.json` / `summary.json` / `review.html`；
  5. **断点续跑**：每张图的读数单独缓存在 `--cache` 下，重跑时直接跳过已处理的图。

CLI：
    python -m game_assistant.inventory_scan --kind ce --images <截图目录> --out <输出目录>
只往 stdout 打**摘要**（计数 + 前 N 条异常），不打全量数据。
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

import config

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
ANOMALY_PREVIEW = 20


def _norm(text: str) -> str:
    """归一化：NFKC + 去空白 + 去间隔号，用于名称匹配。"""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    for ch in (" ", "\u3000", "·", "・", "．", "."):
        normalized = normalized.replace(ch, "")
    return normalized.strip().lower()


def _vlm_rows(image_bytes: bytes, model: str, pages_hint: str = "") -> list[dict[str, Any]]:
    """让本机 VLM 读一张库存截图，返回 [{name, level, limit_break}]。读不出就给空。"""
    prompt = (
        "你在读 Fate/Grand Order 国服的库存列表截图。"
        + (f"这些是{pages_hint}。" if pages_hint else "")
        + "只依据图中直接可见的文字，逐行输出每一项的名称、等级、以及突破次数（若图上没有就留空）。"
        "**不要猜测、不要补全、不要翻译**；看不清的行就整行跳过。"
        '只输出 JSON 对象：{"rows":[{"name":"原文名称","level":1,"limit_break":0}],"warnings":[]}'
    )
    response = requests.post(
        config.OLLAMA_BASE.rstrip("/") + "/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "images": [base64.b64encode(image_bytes).decode("ascii")],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 3000, "num_ctx": 8192},
        },
        timeout=max(config.GAME_ASSISTANT_LLM_TIMEOUT, 300),
    )
    response.raise_for_status()
    payload = response.json().get("response") or "{}"
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    rows = data.get("rows") if isinstance(data, dict) else None
    return [row for row in (rows or []) if isinstance(row, dict)]


def _kb_index(kind: str) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """读图鉴库：返回（按归一化名索引, 归一化名 -> 候选列表）。"""
    if kind == "ce":
        path = Path(config.GAME_ASSISTANT_KB_DIR) / "craft_essences_cn.json"
    else:
        path = Path(config.GAME_ASSISTANT_KB_DIR) / "mystic_codes_cn.json"
    if not path.exists():
        return {}, {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items") or []
    index: dict[str, list[dict]] = {}
    for item in items:
        name = _norm(str(item.get("name") or ""))
        if not name:
            continue
        index.setdefault(name, []).append(item)
    first = {name: candidates[0] for name, candidates in index.items() if len(candidates) == 1}
    return first, index


def _cache_path(cache_dir: Path, image: Path) -> Path:
    stat = image.stat()
    return cache_dir / f"{image.stem}_{stat.st_size}_{int(stat.st_mtime)}.json"


def scan_images(
    images: list[Path],
    *,
    kind: str = "ce",
    model: str | None = None,
    out_dir: Path,
    cache_dir: Path,
    limit: int = 0,
    vision=None,
    log=print,
) -> dict[str, Any]:
    """主流程。`vision` 可注入（测试用假实现，避免真的调 VLM）。"""
    vision = vision or _vlm_rows
    model = model or config.VLM_MODEL
    hint = "概念礼装（礼装）列表" if kind == "ce" else "御术礼装列表"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if limit:
        images = images[:limit]

    exact, index = _kb_index(kind)
    rows: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    processed = 0
    for image in images:
        cache_file = _cache_path(cache_dir, image)
        if cache_file.exists():
            try:
                raw_rows = json.loads(cache_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw_rows = None
        else:
            raw_rows = None
        if raw_rows is None:
            log(f"  [VLM] {image.name}")
            try:
                raw_rows = vision(image.read_bytes(), model, hint)
            except Exception as exc:  # VLM 失败不该中断整批
                raw_rows = []
                anomalies.append({"image": image.name, "reason": f"VLM 调用失败：{exc}", "name": ""})
            cache_file.write_text(json.dumps(raw_rows, ensure_ascii=False), encoding="utf-8")
        processed += 1
        for row in raw_rows:
            name = str(row.get("name") or "").strip()
            key = _norm(name)
            entry: dict[str, Any] = {
                "name": name,
                "level": row.get("level") or 0,
                "limit_break": row.get("limit_break") or 0,
                "source_image": image.name,
                "kb_match": False,
            }
            if not name:
                anomalies.append({"image": image.name, "name": "", "reason": "名称读不出"})
                rows.append(entry)
                continue
            candidates = index.get(key) or []
            if len(candidates) == 1:
                item = candidates[0]
                entry.update(
                    kb_match=True,
                    collection_no=item.get("collection_no"),
                    rarity=item.get("rarity"),
                    cost=item.get("cost"),
                    attack=item.get("atk_max"),
                    hp=item.get("hp_max"),
                    effects=item.get("effects") or [],
                )
            elif len(candidates) > 1:
                anomalies.append({"image": image.name, "name": name,
                                  "reason": f"KB 里同名 {len(candidates)} 条，需要人工选",})
            else:
                anomalies.append({"image": image.name, "name": name,
                                  "reason": "KB 里没有这个名字（可能是读错或未收录）"})
            rows.append(entry)

    # 重复行提示（重叠截图很常见；只提示、不自动删除）
    seen: dict[tuple, int] = {}
    for row in rows:
        key = (row.get("name"), row.get("level"), row.get("limit_break"))
        seen[key] = seen.get(key, 0) + 1
    duplicates = [{"name": k[0], "level": k[1], "limit_break": k[2], "count": v}
                  for k, v in seen.items() if v > 1]

    summary = {
        "kind": kind,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "images_processed": processed,
        "rows_total": len(rows),
        "rows_matched": sum(1 for row in rows if row.get("kb_match")),
        "rows_unmatched": sum(1 for row in rows if not row.get("kb_match")),
        "anomalies": len(anomalies),
        "duplicate_keys": len(duplicates),
        "model": model,
        "out_dir": str(out_dir),
    }
    (out_dir / "rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "anomalies.json").write_text(json.dumps(anomalies, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "rows.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "level", "limit_break", "kb_match",
                                                    "collection_no", "rarity", "cost", "source_image"])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})
    (out_dir / "review.html").write_text(_review_html(rows, anomalies, kind), encoding="utf-8")
    return summary


def _review_html(rows: list[dict], anomalies: list[dict], kind: str) -> str:
    """给**人**看的复核页（原图 + 读数 + 匹配结果并排）。"""
    label = "概念礼装" if kind == "ce" else "御主礼装"
    body_rows = "\n".join(
        "<tr><td>{src}</td><td>{name}</td><td>{level}</td><td>{lb}</td><td>{matched}</td>"
        "<td>{collection}</td></tr>".format(
            src=row.get("source_image", ""), name=row.get("name", ""), level=row.get("level", ""),
            lb=row.get("limit_break", ""), matched="✓" if row.get("kb_match") else "✗",
            collection=row.get("collection_no", ""),
        )
        for row in rows
    )
    anomaly_rows = "\n".join(
        f"<li>{item.get('image','')}｜{item.get('name','')}｜{item.get('reason','')}</li>" for item in anomalies
    )
    return f"""<!doctype html><html lang="zh"><meta charset="utf-8">
<title>{label}库存复核</title>
<style>body{{font-family:system-ui,sans-serif;margin:16px}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:4px 8px;font-size:13px}}li{{font-size:13px}}</style>
<h1>{label}库存复核（{len(rows)} 条 / 异常 {len(anomalies)} 条）</h1>
<p>核对要点：逐行对照截图；`✗` 表示 KB 没匹配上（多半是读错或未收录）。图片请对照同目录下的截图文件。</p>
<h2>异常（需要人看）</h2><ul>{anomaly_rows or "<li>无</li>"}</ul>
<h2>全部读数</h2>
<table><tr><th>来源截图</th><th>读到的名称</th><th>等级</th><th>突破</th><th>KB 匹配</th><th>图鉴编号</th></tr>
{body_rows}</table></html>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="库存截图 → VLM 读数 → KB 匹配（只打摘要）")
    parser.add_argument("--kind", choices=("ce", "mc"), default="ce")
    parser.add_argument("--images", required=True, help="截图目录（按文件名排序处理）")
    parser.add_argument("--out", required=True, help="输出目录（rows/anomalies/summary/review.html）")
    parser.add_argument("--cache", default="", help="读数缓存目录（断点续跑用；默认 <out>/cache）")
    parser.add_argument("--model", default="", help=f"VLM 模型（默认 {config.VLM_MODEL}）")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 张（试跑用）")
    args = parser.parse_args(argv)

    images = sorted(
        path for path in Path(args.images).iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    out_dir = Path(args.out)
    cache_dir = Path(args.cache) if args.cache else out_dir / "cache"
    summary = scan_images(images, kind=args.kind, model=args.model or None, out_dir=out_dir,
                          cache_dir=cache_dir, limit=args.limit)
    print(json.dumps({k: v for k, v in summary.items() if k != "out_dir"}, ensure_ascii=False, indent=2))
    anomalies = json.loads((out_dir / "anomalies.json").read_text(encoding="utf-8"))
    for item in anomalies[:ANOMALY_PREVIEW]:
        print(f"  异常: {item.get('image')}｜{item.get('name')}｜{item.get('reason')}")
    if len(anomalies) > ANOMALY_PREVIEW:
        print(f"  （还有 {len(anomalies) - ANOMALY_PREVIEW} 条异常，见 {out_dir / 'anomalies.json'}）")
    print(f"人工复核页：{out_dir / 'review.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
