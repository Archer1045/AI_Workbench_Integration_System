"""Compact CN servant base stats for the 3T recommender.

The private account snapshot stores class, level, NP level, and skills but no
attack value, and the simplified simulator needs an attack number. This module
turns the local Atlas Academy CN cache into a small table and looks attack up by
servant level.

Nothing here is written by the training or drawing pipelines: it is a derived
read-only view of a public servant catalog. Entries that cannot be matched fall
back to a class/rarity median and are reported as missing data instead of being
silently invented.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import config

STATS_FILENAME = "servant_stats_cn.json"

# Atlas Academy 的宝具卡色编码：1=Arts、2=Buster、3=Quick。
NP_CARD_MULTIPLIER = {1: 1.0, 2: 1.5, 3: 0.8}
NP_CARD_NAME = {1: "Arts", 2: "Buster", 3: "Quick"}

_CLASS_MAP = {
    "saber": "Saber",
    "archer": "Archer",
    "lancer": "Lancer",
    "rider": "Rider",
    "caster": "Caster",
    "assassin": "Assassin",
    "berserker": "Berserker",
    "shielder": "Shielder",
    "ruler": "Ruler",
    "avenger": "Avenger",
    "alterego": "Alterego",
    "mooncancer": "MoonCancer",
    "pretender": "Pretender",
    "foreigner": "Foreigner",
}


def normalize_class(atlas_class: str) -> str:
    """Map an Atlas className onto the account snapshot naming.

    图鉴里存在大量特殊/异闻职阶（`unBeastOlgaMarie`、`beastEresh`、
    `loreGrandCaster`、`uOlgaMarie*` 等）。不能只按 `beast` 前缀判断，否则这些从者
    会被标成 Unknown，并在按职阶匹配时被过滤掉（已实证：奥尔加玛丽）。
    """
    key = str(atlas_class or "").strip().lower()
    if key in _CLASS_MAP:
        return _CLASS_MAP[key]
    if "beast" in key or key.startswith("uolgamarie"):
        return "Beast"
    if key.startswith("loregrand"):
        return "Caster"
    return "Unknown"


def normalize_name(name: str) -> str:
    """Strip display decorations so account and Atlas names can be compared.

    NFKC 归一必须最先做：图鉴里的 `Ｕ－奥尔加玛丽` 是全角写法，而账户快照里是半角
    `U` + 全角连字符。不做宽度归一就会漏配（已实证：她会退化成中位数回退）。
    """
    value = unicodedata.normalize("NFKC", str(name or ""))
    value = re.sub(r"[（(][^)）]*[)）]", "", value)
    value = re.sub(r"[〔【\[][^〕】\]]*[〕】\]]", "", value)
    value = re.sub(r"[“”「」『』\s]", "", value)
    return value.replace("：", ":").strip()


ALIAS_FILENAME = "servant_name_aliases.json"


def build_aliases(
    account_rows: list[dict[str, Any]],
    atlas_servants: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """由账号快照生成「账号名 → 图鉴正式名」别名表。

    账号里的名字是国服社区名（始皇帝 / 开膛手杰克 / 虞美人 …），图鉴里是官译名
    （祖政 / 雾都弃子 / 雏罂 …），靠字符串归一匹配不上。但导入行的 notes 带着
    `variant=<collectionNo>_<svtId>`，可以直接按 id 定位图鉴条目——所以这张表是
    **推导出来的**，不是手写的：2026-10-11 实测 261 个账号从者里 29 个未匹配，
    29 个全部由此法对上（详见 tests/test_game_assistant_kb.py 的别名用例）。
    """
    by_id = {int(item["id"]): item for item in atlas_servants if item.get("id") is not None}
    by_no = {
        int(item["collectionNo"]): item
        for item in atlas_servants
        if item.get("collectionNo")
    }
    mapping: dict[str, dict[str, Any]] = {}
    for row in account_rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        match = re.search(r"variant=(\d+)_(\d+)", str(row.get("notes") or ""))
        if not match:
            continue
        collection, svt_id = int(match.group(1)), int(match.group(2))
        entry = by_id.get(svt_id) or by_no.get(collection)
        if not entry:
            continue
        mapping[name] = {
            "atlas_name": str(entry.get("name") or ""),
            "svt_id": int(entry.get("id")),
            "collection_no": int(entry.get("collectionNo") or 0),
            "class_name": normalize_class(entry.get("className", "")),
            "evidence": f"variant={collection}_{svt_id}",
        }
    return mapping


def alias_path() -> Path:
    return Path(config.GAME_ASSISTANT_COMBAT_DIR) / ALIAS_FILENAME


def load_aliases(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """读取别名表；缺失或损坏时返回空表（匹配退化为原有行为）。"""
    target = Path(path) if path else alias_path()
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8")).get("aliases") or {}
    except Exception:  # noqa: BLE001
        return {}


def make_lookup(entries: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """构建 名字 -> 候选 索引：同一名字可对应多个职阶，必须保留全部候选。"""
    exact: dict[str, list[dict[str, Any]]] = {}
    normalized: dict[str, list[dict[str, Any]]] = {}
    battle: dict[str, list[dict[str, Any]]] = {}
    for item in entries:
        exact.setdefault(str(item.get("name") or ""), []).append(item)
        normalized.setdefault(normalize_name(item.get("name") or ""), []).append(item)
        battle_name = item.get("battle_name")
        if battle_name:
            battle.setdefault(normalize_name(battle_name), []).append(item)
    return {"exact": exact, "normalized": normalized, "battle": battle}


def lookup_entry(
    indexes: dict[str, dict[str, list[dict[str, Any]]]],
    name: str,
    class_name: str = "",
    rarity: int | None = None,
) -> dict[str, Any] | None:
    """按 名字 +（可选）职阶 +（可选）稀有度 匹配；职阶映射缺口（Unknown）不做消歧。

    同名同职阶的从者必须用稀有度消歧：图鉴里有两条 `BB`（4★ 原版 collection 166、
    5★ 水着 collection 220），而账号里的 `BB(SSR)` 是 5★。只按列表顺序取第一条会把
    水着 BB 的手牌固定技能（无貌之月 EX）整体丢掉。
    """
    candidates = lookup_candidates(indexes, name, class_name)
    if not candidates:
        candidates = list(indexes.get("exact", {}).get(name) or [])
    if not candidates:
        return None
    if rarity:
        exact_rarity = [item for item in candidates if item.get("rarity") == rarity]
        if exact_rarity:
            return exact_rarity[0]
    return candidates[0]


def lookup_candidates(
    indexes: dict[str, dict[str, list[dict[str, Any]]]],
    name: str,
    class_name: str = "",
) -> list[dict[str, Any]]:
    """返回过滤职阶后的全部同名候选，供调用方报告歧义。"""
    wanted_class = str(class_name or "").strip()
    for key, lookup in (
        (name, indexes["exact"]),
        (normalize_name(name), indexes["normalized"]),
        (normalize_name(name), indexes["battle"]),
    ):
        candidates = list(lookup.get(key) or [])
        if not candidates:
            continue
        if wanted_class:
            matched = [item for item in candidates if item.get("class_name") == wanted_class]
            if matched:
                return matched
            unmapped = [item for item in candidates if item.get("class_name") == "Unknown"]
            if unmapped:
                return unmapped
            continue
        return candidates
    return []


def build_stats(atlas_path: Path | str) -> dict[str, Any]:
    entries = json.loads(Path(atlas_path).read_text(encoding="utf-8"))
    servants: list[dict[str, Any]] = []
    for entry in entries:
        growth = [int(value) for value in (entry.get("atkGrowth") or []) if isinstance(value, (int, float))]
        if not growth:
            continue
        card, target_type, damage_values, np_target, special_values = _noble_phantasm(entry)
        servants.append(
            {
                "id": entry.get("id"),
                "collection_no": entry.get("collectionNo"),
                "name": entry.get("name") or "",
                "battle_name": entry.get("battleName") or "",
                "class_name": normalize_class(entry.get("className", "")),
                "rarity": entry.get("rarity"),
                "lv_max": entry.get("lvMax"),
                "atk_base": entry.get("atkBase"),
                "atk_max": entry.get("atkMax"),
                "atk_growth": growth,
                "hp_max": entry.get("hpMax"),
                "attribute": entry.get("attribute") or "",
                "np_card": card,
                "np_target_type": target_type,
                "np_target": np_target,
                "np_damage_values": damage_values,
                "np_special_values": special_values,
            }
        )
    servants.sort(key=lambda item: (item["class_name"], item["name"]))
    return {
        "source": {
            "name": "Atlas Academy CN servant catalog",
            "generated_from": str(atlas_path),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "entries": len(servants),
        },
        "servants": servants,
    }


def _noble_phantasm(entry: dict[str, Any]) -> tuple[int | None, str, list[int], str, list[int]]:
    """返回 (卡色, 设定类型名, 每宝具等级的伤害倍率 x1000, 实际目标域)。

    只有带 `damageNp` 函数的宝具才有伤害倍率；纯辅助宝具返回空列表。
    单体/光炮必须取自伤害函数的 `funcTargetType`（enemy = 单体，enemyAll = 光炮）：
    设定里的「对人宝具／对军宝具」是剧情用语，会与实际不符
    （例如阿尔托莉雅·潘德拉贡〔Lily〕标着对人宝具，实际打全体）。
    """
    phantasms = entry.get("noblePhantasms") or []
    if not phantasms:
        return None, "", [], "", []
    first = phantasms[0]
    card = first.get("card")
    target_type = str(first.get("type") or "")
    np_target = ""
    for function in first.get("functions") or []:
        # 伤害类宝具函数有多个变体：damageNp / damageNpIndividual / damageNpPierce 等。
        if not str(function.get("funcType") or "").startswith("damageNp"):
            continue
        func_target = str(function.get("funcTargetType") or "")
        if func_target == "enemyAll":
            np_target = "area"
        elif func_target == "enemy":
            np_target = "single"
        values = [
            int(item["Value"])
            for item in (function.get("svals") or [])
            if isinstance(item, dict) and isinstance(item.get("Value"), (int, float))
        ]
        # `damageNpIndividualSum` 还有一个按“个体数”叠加的第二成分（Value2）：
        # 例：所长的宝具是〔拥有人、星之力〕特攻，文案写明过量充能时特攻威力提升。
        # 用户确认口径：个体数 = 场上敌人数。
        # 过量充能表：Atlas 用 svals / svals2 / svals3 / svals4 / svals5 表示 OC 1-5，
        # 特攻成分（Value2）随 OC 递增（所长：1500 → 1625 → 1750 → 1875 → 2000）。
        special: list[int] = []
        for key in ("svals", "svals2", "svals3", "svals4", "svals5"):
            rows = [item for item in (function.get(key) or []) if isinstance(item, dict)]
            value2 = next((item.get("Value2") for item in rows if isinstance(item.get("Value2"), (int, float))), None)
            if value2 is not None:
                special.append(int(value2))
        if values:
            return int(card) if card is not None else None, target_type, values, np_target, special
    return int(card) if card is not None else None, target_type, [], np_target, []


def np_multiplier(entry: dict[str, Any], np_level: int | None) -> float | None:
    """宝具的实际伤害倍率（含卡色修正）。

    Atlas 的 damageNp 数值以 0.1% 为单位记录，除以 1000 得到 FGO 公式里的倍率，
    再乘卡色修正（Arts 1.0 / Buster 1.5 / Quick 0.8）。
    """
    values = entry.get("np_damage_values") or []
    if not values:
        return None
    index = min(max(int(np_level or 1), 1), 5) - 1
    index = min(index, len(values) - 1)
    card = entry.get("np_card")
    return (values[index] / 1000.0) * NP_CARD_MULTIPLIER.get(int(card) if card else 1, 1.0)


def np_special_multiplier(entry: dict[str, Any], overcharge: int | None = 1) -> float:
    """宝具“个体数”第二成分（每个场上敌人叠加的倍率，含卡色修正）。

    用户 2026-10-10 确认：个体数按**场上敌人数**计算；该成分随**过量充能等级**提升
    （`svals`…`svals5` = OC 1-5）。没有该成分的宝具返回 0。
    """
    values = entry.get("np_special_values") or []
    if not values:
        return 0.0
    index = min(max(int(overcharge or 1), 1), 5) - 1
    index = min(index, len(values) - 1)
    card = entry.get("np_card")
    return (values[index] / 1000.0) * NP_CARD_MULTIPLIER.get(int(card) if card else 1, 1.0)


class ServantStatsStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or Path(config.GAME_ASSISTANT_COMBAT_DIR) / STATS_FILENAME)
        self._payload: dict[str, Any] | None = None
        self._index: dict[str, dict[str, list[dict[str, Any]]]] | None = None
        self._aliases: dict[str, dict[str, Any]] | None = None

    def available(self) -> bool:
        return self.path.exists()

    def aliases(self) -> dict[str, dict[str, Any]]:
        """账号名 → 图鉴正式名的别名表（来自导入行的 variant 线索，见 build_aliases）。"""
        if self._aliases is None:
            self._aliases = load_aliases()
        return self._aliases

    def alias_name(self, name: str) -> str:
        entry = self.aliases().get(str(name or "").strip())
        return str(entry.get("atlas_name") or "") if entry else ""

    def load(self) -> dict[str, Any]:
        if self._payload is None:
            if not self.path.exists():
                self._payload = {"source": {}, "servants": []}
            else:
                self._payload = json.loads(self.path.read_text(encoding="utf-8"))
        return self._payload

    @property
    def servants(self) -> list[dict[str, Any]]:
        return list(self.load().get("servants") or [])

    def _indexes(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """名字 -> 候选列表。同一名字可以对应多个职阶（例如阿尔托莉雅的 Saber/Archer 两版），
        所以索引必须保留全部候选，交给 `find` 按职阶消歧，不能用字典覆盖。"""
        if self._index is None:
            self._index = make_lookup(self.servants)
        return self._index

    def find(self, name: str, class_name: str = "", rarity: int | None = None) -> dict[str, Any] | None:
        """按 名字 +（可选）职阶 匹配。

        先优先“名字和职阶都对上”，再退化为只按名字匹配；同名多职阶时若调用方给了
        职阶就用职阶消歧，否则返回第一候选并由调用方记录歧义。
        图鉴职阶未被识别（Unknown）时不做职阶消歧——那是映射缺口，不是名字冲突。
        同名同职阶时（例如两条 `BB`）再用账号里的稀有度消歧。

        别名表（账号社区名 → 图鉴官译名，按导入行 `variant` 编号推导）**优先于名字匹配**：
        实测有三处按名字会落到错误的从者身上——`阿尔托莉雅·潘德拉贡〔Alter〕(Rider)` 会被
        名字归一吃掉职阶变体落到普通 Saber、`贞德〔Alter〕(Berserker)` 落到 `贞德`、
        `织田信长(Avenger)` 落到 Archer 版的 `织田信长`。按 id 推导的别名在这三处都是对的。
        """
        alias = self.alias_name(name)
        if alias:
            entry = lookup_entry(self._indexes(), alias, class_name, rarity)
            if entry is not None:
                return entry
        return lookup_entry(self._indexes(), name, class_name, rarity)

    def candidates(self, name: str, class_name: str = "") -> list[dict[str, Any]]:
        """返回过滤职阶后的同名候选，供调用方报告歧义。"""
        alias = self.alias_name(name)
        if alias:
            found = lookup_candidates(self._indexes(), alias, class_name)
            if found:
                return found
        return lookup_candidates(self._indexes(), name, class_name)

    def attack_at_level(self, entry: dict[str, Any], level: int | None) -> float | None:
        growth = entry.get("atk_growth") or []
        if not growth:
            return None
        index = max(1, int(level or 1)) - 1
        index = min(index, len(growth) - 1)
        return float(growth[index])

    def median_attack(self, class_name: str, rarity: int | None) -> float | None:
        """Fallback attack for unmatched servants, from the same class/rarity pool."""
        pool = [
            float(item["atk_max"])
            for item in self.servants
            if item.get("atk_max")
            and item.get("class_name") == class_name
            and (rarity is None or item.get("rarity") == rarity)
        ]
        return statistics.median(pool) if pool else None


_STORE: ServantStatsStore | None = None


def get_servant_stats() -> ServantStatsStore:
    global _STORE
    if _STORE is None:
        _STORE = ServantStatsStore()
    return _STORE


def reset_servant_stats() -> None:
    global _STORE
    _STORE = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 Atlas CN 从者缓存压缩成本地基础数据表")
    parser.add_argument("--atlas", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument(
        "--aliases-from",
        default="",
        help="账号快照 sqlite（含 ga_account_servants）；给出后同时重建 账号名→图鉴名 别名表",
    )
    args = parser.parse_args(argv)
    payload = build_stats(args.atlas)
    target = Path(args.out or Path(config.GAME_ASSISTANT_COMBAT_DIR) / STATS_FILENAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {target}：{payload['source']['entries']} 条从者基础数据", flush=True)
    if args.aliases_from:
        from datetime import datetime as _datetime
        import sqlite3

        db_path = Path(args.aliases_from)
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = [
                dict(row)
                for row in conn.execute(
                    "select name, class_name, rarity, notes from ga_account_servants"
                )
            ]
        finally:
            conn.close()
        atlas_servants = json.loads(Path(args.atlas).read_text(encoding="utf-8"))
        aliases = build_aliases(rows, atlas_servants)
        alias_target = alias_path()
        alias_target.parent.mkdir(parents=True, exist_ok=True)
        alias_target.write_text(
            json.dumps(
                {
                    "source": {
                        "name": "账号快照 + Atlas CN 图鉴（按 variant 编号推导，非手写）",
                        "file": db_path.name,
                        "entries": len(rows),
                        "kept": len(aliases),
                        "generated_at": _datetime.now()
                        .astimezone()
                        .isoformat(timespec="seconds"),
                    },
                    "aliases": aliases,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"已写入 {alias_target}：{len(aliases)} 条别名", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
