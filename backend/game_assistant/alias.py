"""别名解析：把用户口语简称（攻略里也常用）归一成图鉴正式名 —— 从者与礼装两个域。

数据来源两处，都是"有出处"的：
  1. `AIproduct/game_assistant_kb/alias_user.json`：**用户确认过的口语简称**（人工维护，
     每条带确认日期）。攻略里出现的"C呆""贝拉丽莎"这类写法就靠它。
  2. `AIproduct/game_assistant_combat/servant_name_aliases.json`：账号名 → 图鉴名
     （由账号导入的 variant 编号机器生成，带 svt_id / 图鉴号 / 职阶）。

规则（与 decisions.md 的"不猜"一致）：
  * 只做**归一化后的精确匹配**：NFKC（全角→半角、（）→()）、去空格、去掉 `·`、小写化；
    不做模糊匹配、不做包含匹配。
  * 命中多个**不同目标** ⇒ `ambiguous=True` 并把候选原样返回，**绝不挑一个**。
  * 未命中 ⇒ `matched=False`，`target` 原样回传，下游继续按原名字走（保持旧行为）。
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import config

SERVANT = "servant"
CRAFT_ESSENCE = "craft_essence"

USER_ALIAS_PATH = Path(config.GAME_ASSISTANT_KB_DIR) / "alias_user.json"
SERVANT_ALIAS_PATH = Path(config.GAME_ASSISTANT_COMBAT_DIR) / "servant_name_aliases.json"


def normalize(text: str) -> str:
    """归一化：全角折半角、去空白、去间隔号、统一括号、小写。"""
    value = unicodedata.normalize("NFKC", str(text))
    # 间隔号 / 全角点 / 连字符 / 引号都要吃掉：图鉴里有叫「“山中老人”」的从者，
    # 用户写「山中老人」时必须也能命中（2026-10-13 实测）。
    for token in (
        " ", "\u3000", "·", "・", "･", "．", ".", "\u2010", "-", "－",
        "「", "」", "『", "』", "“", "”", "‘", "’", "\"", "'",
    ):
        value = value.replace(token, "")
    return value.strip().lower()


@dataclass(frozen=True)
class AliasHit:
    """一条别名命中的目标（可能带职阶 / 图鉴编号，用来消歧同名变体）。"""

    target: str
    domain: str
    class_name: str = ""
    collection_no: int | None = None
    source: str = ""
    kind: str = ""  # abbr(简称) / nickname(昵称) / account(账号名) / official(正式名)
    raw: str = ""  # 表里登记的原写法（在文本里按这个做替换，长别名优先）

    def label(self) -> str:
        if self.class_name:
            return f"{self.target}({self.class_name})"
        return self.target


@dataclass
class AliasResolution:
    """一次解析的结果。`matched=False` 时 target 就是输入原文。"""

    text: str
    domain: str
    matched: bool = False
    ambiguous: bool = False
    unknown_alias: bool = False  # 没命中、而且既不是正式名也不是账号名 ⇒ 疑似未收录的简称
    target: str = ""
    class_name: str = ""
    collection_no: int | None = None
    kind: str = ""
    candidates: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def report(self) -> str:
        if self.ambiguous:
            return f"「{self.text}」有多个候选，未消歧：{'、'.join(self.candidates)}"
        if self.unknown_alias:
            return (
                f"不认识「{self.text}」：它既不是图鉴正式名也不是账号里的名字，"
                "疑似没收录的简称 —— 补进 alias_user.json 或改用正式名"
            )
        if not self.matched:
            return f"「{self.text}」没有别名记录，按原名继续"
        suffix = f"({self.class_name})" if self.class_name else ""
        return f"「{self.text}」→ {self.target}{suffix}" + (f"［{self.kind}］" if self.kind else "")


def _load_user_aliases(path: Path | None = None) -> dict[str, list[AliasHit]]:
    target_path = Path(path or USER_ALIAS_PATH)
    table: dict[str, list[AliasHit]] = {}
    if not target_path.exists():
        return table
    payload = json.loads(target_path.read_text(encoding="utf-8"))
    for item in payload.get("aliases") or []:
        domain = str(item.get("domain") or SERVANT)
        hit = AliasHit(
            target=str(item.get("target") or ""),
            domain=domain,
            class_name=str(item.get("class_name") or ""),
            collection_no=item.get("collection_no"),
            source=f"alias_user.json({item.get('confirmed') or '未标日期'})",
            kind=str(item.get("kind") or "abbr"),
            raw=str(item.get("alias") or ""),
        )
        if not hit.target:
            continue
        table.setdefault(normalize(item.get("alias") or ""), []).append(hit)
    return table


def _load_account_servant_aliases(path: Path | None = None) -> dict[str, list[AliasHit]]:
    """账号名 → 图鉴名（含职阶与图鉴编号，用来消歧同名变体）。"""
    target_path = Path(path or SERVANT_ALIAS_PATH)
    table: dict[str, list[AliasHit]] = {}
    if not target_path.exists():
        return table
    payload = json.loads(target_path.read_text(encoding="utf-8"))
    for account_name, info in (payload.get("aliases") or {}).items():
        hit = AliasHit(
            target=str(info.get("atlas_name") or account_name),
            domain=SERVANT,
            class_name=str(info.get("class_name") or ""),
            collection_no=info.get("collection_no"),
            source=f"servant_name_aliases.json({info.get('evidence') or ''})",
            kind="account",
            raw=str(account_name),
        )
        table.setdefault(normalize(account_name), []).append(hit)
    return table


_TABLE_CACHE: dict[str, dict[str, list[AliasHit]]] = {}
_KNOWN_CACHE: dict[str, set[str]] = {}


def _known_names(domain: str, servant_path: Path | None = None) -> set[str]:
    """该域里"本来就是正式名 / 账号名"的名字集合（判断未命中是不是"疑似未收录简称"）。

    读不到就当空集合 —— 那时**不做**未收录判定（宁可不报，也不误报）。
    """
    key = f"{domain}|{servant_path}"
    if key in _KNOWN_CACHE:
        return _KNOWN_CACHE[key]
    names: set[str] = set()
    try:
        if domain == SERVANT:
            payload = json.loads(Path(servant_path or SERVANT_ALIAS_PATH).read_text(encoding="utf-8"))
            for account_name, info in (payload.get("aliases") or {}).items():
                names.add(normalize(account_name))
                names.add(normalize(str(info.get("atlas_name") or "")))
            stats = Path(config.GAME_ASSISTANT_COMBAT_DIR) / "servant_stats_cn.json"
            if stats.exists():
                rows = json.loads(stats.read_text(encoding="utf-8")).get("servants") or []
                for row in rows:
                    names.add(normalize(str(row.get("name") or "")))
        else:
            path = Path(config.GAME_ASSISTANT_KB_DIR) / "craft_essences_cn.json"
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                # 实测顶层键是 library / source / items（2026-10-13），留几个别名以防改版
                rows = payload.get("items") or payload.get("craft_essences") or payload.get("ces") or []
                for row in rows:
                    names.add(normalize(str(row.get("name") or "")))
    except Exception:
        names = set()
    names.discard("")
    _KNOWN_CACHE[key] = names
    return names


def build_table(
    user_path: Path | None = None,
    servant_path: Path | None = None,
) -> dict[str, list[AliasHit]]:
    """合并两张表（用户简称优先，账号名补充）。返回 归一化别名 -> 候选列表。"""
    key = f"{user_path}|{servant_path}"
    if key in _TABLE_CACHE:
        return _TABLE_CACHE[key]
    table = _load_account_servant_aliases(servant_path)
    for alias, hits in _load_user_aliases(user_path).items():
        merged = table.setdefault(alias, [])
        for hit in hits:
            if not any(existing.target == hit.target and existing.class_name == hit.class_name for existing in merged):
                merged.append(hit)
    _TABLE_CACHE[key] = table
    return table


def reset_cache() -> None:
    _TABLE_CACHE.clear()
    _KNOWN_CACHE.clear()


def resolve(
    text: str,
    domain: str = SERVANT,
    user_path: Path | None = None,
    servant_path: Path | None = None,
) -> AliasResolution:
    """解析一个名字。同名不同职阶的多个候选**不算歧义**（职阶本身就是区分信息），
    只有当同一别名指向多个**同名同职阶**目标时才报歧义。"""
    result = AliasResolution(text=str(text), domain=domain, target=str(text))
    if not str(text).strip():
        return result
    hits = [hit for hit in build_table(user_path, servant_path).get(normalize(text), []) if hit.domain == domain]
    if not hits:
        known = _known_names(domain, servant_path)
        if known and normalize(text) not in known:
            # 第四态：不是别名、也不是正式名/账号名 ⇒ 大概率是"表里还没收的简称"。
            # 必须说出来，否则下游只会报"资料库里没有从者 X"这种难懂的错。
            result.unknown_alias = True
            result.notes.append("既不是图鉴正式名也不是账号名，疑似没收录的简称（不猜）")
        else:
            result.notes.append("别名表里没有这条，按原名字继续（不做模糊匹配）")
        return result
    distinct = {(hit.target, hit.class_name) for hit in hits}
    if len(distinct) > 1:
        result.ambiguous = True
        result.candidates = sorted(f"{target}({klass})" if klass else target for target, klass in distinct)
        result.notes.append("同一别名指向多个目标，需要人工消歧（不猜）")
        return result
    hit = hits[0]
    result.matched = True
    result.target = hit.target
    result.class_name = hit.class_name
    result.collection_no = hit.collection_no
    result.kind = hit.kind
    result.notes.append(f"来源：{hit.source}")
    return result


def apply_to_text(
    text: str,
    domain: str = SERVANT,
    user_path: Path | None = None,
    servant_path: Path | None = None,
) -> tuple[str, list[tuple[str, str]]]:
    """把一段文本里的已知别名换成正式名（攻略入料前先过一遍）。

    替换按**长别名优先**，否则「泳装C呆」会被「C呆」先吃掉；只替换表里登记过的写法，
    未登记的原文一个字不动（不猜）。返回 (新文本, [(别名, 正式名), ...])。
    """
    table = build_table(user_path, servant_path)
    pairs: list[tuple[str, str]] = []
    for hits in table.values():
        for hit in hits:
            if hit.domain != domain or not hit.target:
                continue
            raw = hit.raw or hit.target
            label = f"{hit.target}({hit.class_name})" if hit.class_name else hit.target
            if normalize(raw) != normalize(label):
                pairs.append((raw, label))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    output = str(text)
    changes: list[tuple[str, str]] = []
    for raw, label in pairs:
        if raw and raw in output:
            output = output.replace(raw, label)
            changes.append((raw, label))
    return output, changes
