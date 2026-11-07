"""Enrich CombatProfile enemies with verifiable Atlas quest-phase traits.

The CN quest-phase endpoint can omit ``stages[].enemies`` (the battle rows),
while the JP endpoint for the same quest id exposes the full enemy records.
This module therefore fetches the requested region first and optionally falls
back to another region only when every wave, class, level, and HP value matches
the existing CombatProfile exactly. A mismatch is an error, not a guessed
merge.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from .combat_domain import CombatProfile

ATLAS_API_ROOT = "https://api.atlasacademy.io/nice"
TRAIT_NOISE = {"canBeInBattle", "notBasedOnServant", "unknown"}
STALE_TRAIT_NOTES = (
    "敌人属性（天/地/人）未从该表取得",
    "敌方特性尚未填写",
)


def phase_url(region: str, atlas_quest_id: int, phase: int = 1) -> str:
    query = urlencode({"lang": "en"})
    return f"{ATLAS_API_ROOT}/{region.upper()}/quest/{atlas_quest_id}/{phase}?{query}"


def fetch_phase(
    region: str,
    atlas_quest_id: int,
    phase: int = 1,
    timeout: int = 30,
) -> dict[str, Any]:
    url = phase_url(region, atlas_quest_id, phase)
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 AI-Workbench/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Atlas 返回不是对象：{url}")
    return payload


def _enemy_record(enemy: dict[str, Any]) -> dict[str, Any]:
    servant = enemy.get("svt") if isinstance(enemy.get("svt"), dict) else {}
    trait_rows = [
        *(enemy.get("traits") or []),
        *(servant.get("traits") or []),
    ]
    traits = sorted(
        {
            str(row.get("name") or "").strip()
            for row in trait_rows
            if isinstance(row, dict)
            and str(row.get("name") or "").strip()
            and str(row.get("name") or "").strip() not in TRAIT_NOISE
        }
    )
    return {
        "name": str(enemy.get("name") or servant.get("name") or ""),
        "class_name": str(servant.get("className") or ""),
        "level": int(enemy.get("lv") or 0),
        "hp": int(enemy.get("hp") or 0),
        "attribute": str(servant.get("attribute") or ""),
        "traits": traits,
    }


def phase_enemy_waves(payload: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    """Return ``{wave_index: enemy_records}`` from a quest-phase payload."""
    waves: dict[int, list[dict[str, Any]]] = {}
    for stage in payload.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        wave = int(stage.get("wave") or 0)
        enemies = [
            _enemy_record(enemy)
            for enemy in (stage.get("enemies") or [])
            if isinstance(enemy, dict)
        ]
        if wave:
            waves[wave] = enemies
    return waves


def align_phase_waves(
    profile: CombatProfile,
    waves: dict[int, list[dict[str, Any]]],
) -> dict[int, list[dict[str, Any]]]:
    """Align source enemies to profile units by class/level/HP.

    Atlas and Mooncell list the same wave in different orders (for example,
    the 40,748-HP add appears before the 475,056-HP guardian). Position-based
    matching therefore rejects valid data. We match each profile unit to
    exactly one unused source row with the same class/level/HP instead.
    """
    if not waves:
        raise ValueError("Atlas 阶段没有任何敌人战斗行")
    mismatches: list[str] = []
    aligned: dict[int, list[dict[str, Any]]] = {}
    for wave in profile.waves:
        source = waves.get(wave.wave_index, [])
        if len(source) != len(wave.units):
            mismatches.append(
                f"第 {wave.wave_index} 面敌人数不同：档案 {len(wave.units)} / Atlas {len(source)}"
            )
            continue
        unused = list(source)
        wave_aligned: list[dict[str, Any]] = []
        for index, unit in enumerate(wave.units, start=1):
            expected_class = str(unit.class_name).lower()
            candidates = [
                enemy
                for enemy in unused
                if str(enemy.get("class_name") or "").lower() == expected_class
                and int(enemy.get("level") or 0) == int(unit.level)
                and int(enemy.get("hp") or 0) == int(unit.hp)
            ]
            if not candidates:
                mismatches.append(
                    f"第 {wave.wave_index} 面第 {index} 个敌人没有匹配行："
                    f"档案 {unit.class_name}/Lv{unit.level}/HP{unit.hp}"
                )
                continue
            matched = candidates[0]
            unused.remove(matched)
            wave_aligned.append(matched)
        if len(wave_aligned) == len(wave.units):
            aligned[wave.wave_index] = wave_aligned
    expected_wave_indexes = [wave.wave_index for wave in profile.waves]
    if sorted(waves) != sorted(expected_wave_indexes):
        mismatches.append(
            f"波次不同：档案 {expected_wave_indexes} / Atlas {sorted(waves)}"
        )
    if mismatches:
        raise ValueError("Atlas 阶段与 CombatProfile 不一致，拒绝写入：" + "；".join(mismatches))
    return aligned


def apply_phase_traits(
    profile: CombatProfile,
    payload: dict[str, Any],
    *,
    source_url: str,
    source_note: str = "",
) -> CombatProfile:
    waves = align_phase_waves(profile, phase_enemy_waves(payload))
    enriched = profile.model_copy(deep=True)
    for wave in enriched.waves:
        source = waves[wave.wave_index]
        for unit, enemy in zip(wave.units, source):
            unit.attribute = str(enemy.get("attribute") or unit.attribute)
            unit.traits = list(enemy.get("traits") or [])
            unit.notes = [
                note
                for note in unit.notes
                if not any(marker in note for marker in STALE_TRAIT_NOTES)
            ]
    enriched.notes = [
        note
        for note in enriched.notes
        if not any(marker in note for marker in STALE_TRAIT_NOTES)
    ]
    enriched.notes.append(
        f"敌方属性/特性来源：Atlas Academy 关卡阶段 {source_url}"
    )
    if source_note:
        enriched.notes.append(source_note)
    return enriched


def enrich_profile(
    profile: CombatProfile,
    *,
    atlas_quest_id: int,
    region: str = "CN",
    fallback_region: str = "",
    phase: int = 1,
    timeout: int = 30,
) -> tuple[CombatProfile, dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    regions = [region.upper()]
    if fallback_region and fallback_region.upper() not in regions:
        regions.append(fallback_region.upper())
    for candidate_region in regions:
        url = phase_url(candidate_region, atlas_quest_id, phase)
        try:
            payload = fetch_phase(candidate_region, atlas_quest_id, phase, timeout)
            raw_waves = phase_enemy_waves(payload)
            if not raw_waves:
                raise ValueError("阶段接口没有敌人战斗行")
            waves = align_phase_waves(profile, raw_waves)
        except Exception as exc:  # noqa: BLE001 - try the fallback, report all attempts
            attempts.append({"region": candidate_region, "url": url, "error": str(exc)})
            continue
        fallback_note = ""
        if candidate_region != regions[0]:
            fallback_note = (
                f"该阶段来自 {candidate_region} 服同关卡号；已逐面核对职阶、等级、HP "
                "与 CN 战斗档案完全一致后才写入。"
            )
        enriched = apply_phase_traits(
            profile,
            payload,
            source_url=url,
            source_note=fallback_note,
        )
        return enriched, {
            "ok": True,
            "region": candidate_region,
            "url": url,
            "attempts": attempts,
            "wave_enemies": {
                str(wave): [
                    {
                        "name": enemy["name"],
                        "class_name": enemy["class_name"],
                        "level": enemy["level"],
                        "hp": enemy["hp"],
                        "attribute": enemy["attribute"],
                        "traits": enemy["traits"],
                    }
                    for enemy in enemies
                ]
                for wave, enemies in waves.items()
            },
        }
    raise ValueError("没有可用的 Atlas 阶段数据：" + json.dumps(attempts, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="给 CombatProfile 补齐 Atlas 可核对的敌方属性/特性"
    )
    parser.add_argument("--profile", required=True)
    parser.add_argument("--atlas-quest-id", required=True, type=int)
    parser.add_argument("--region", default="CN")
    parser.add_argument("--fallback-region", default="JP")
    parser.add_argument("--phase", default=1, type=int)
    parser.add_argument("--timeout", default=30, type=int)
    parser.add_argument("--out", default="")
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args(argv)
    if args.out and args.in_place:
        parser.error("--out 与 --in-place 不能同时使用")

    profile_path = Path(args.profile)
    profile = CombatProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    enriched, report = enrich_profile(
        profile,
        atlas_quest_id=args.atlas_quest_id,
        region=args.region,
        fallback_region=args.fallback_region,
        phase=args.phase,
        timeout=args.timeout,
    )
    report["profile"] = str(profile_path)
    report["output"] = str(profile_path if args.in_place else args.out or "")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.in_place or args.out:
        target = profile_path if args.in_place else Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(enriched.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
