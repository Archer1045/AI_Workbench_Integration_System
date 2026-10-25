"""3P/群交提示词人数解析与体位预设构图提示测试。"""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for path in (ROOT / "rag_knowledge_base", ROOT / "agent"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from prompt_agent import POSE_PRESETS
import routers.draw as draw_module
from routers.draw import MAX_GROUP_CANDIDATES, _expected_count


def test_expected_count_sums_genders() -> None:
    assert _expected_count("1girl, 2boys, double penetration, group sex") == 3
    assert _expected_count("2girls 1boy, threesome") == 3


def test_expected_count_parses_people_phrases() -> None:
    assert _expected_count("four people, orgy, group sex") == 4
    assert _expected_count("exactly 3 separate people in one frame") == 3
    assert _expected_count("exactly 4 people on a bed") == 4
    assert _expected_count("exactly 4 separate women in one wide shot") == 4
    assert _expected_count("exactly 3 separate men in one wide shot") == 3
    assert _expected_count("multiple people lined up") is None


def test_review_counts_prefers_enumerated_heads_over_reported_total() -> None:
    review_data = {
        "heads": [
            {"x": 100, "y": 200},
            {"x": 300, "y": 200},
            {"x": 500, "y": 200},
            {"x": 700, "y": 200},
            {"x": 900, "y": 200},
        ],
        "character_count": 4,
    }

    assert draw_module._review_counts(review_data) == (5, 4)
    assert draw_module._review_counts({"character_count": "3"}) == (None, 3)
    assert draw_module._review_counts({"heads": [], "character_count": 0}) == (0, 0)


def test_expected_gender_counts_parse_group_roles() -> None:
    assert draw_module._expected_gender_counts(
        "1 female bending forward between 2 standing males, group sex"
    ) == (1, 2)
    assert draw_module._expected_gender_counts(
        "1girl, 3boys, gangbang queue, group sex"
    ) == (1, 3)


def test_review_image_flags_missing_expected_female(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-png")
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "response": json.dumps(
                    {
                        "heads": [
                            {"x": 100, "y": 200, "gender": "male", "visibility": "full"},
                            {"x": 300, "y": 200, "gender": "male", "visibility": "full"},
                            {"x": 500, "y": 200, "gender": "male", "visibility": "full"},
                        ],
                        "character_count": 3,
                        "multiple_same": False,
                        "pose_matches": True,
                        "action_matches": True,
                        "composition_matches": True,
                        "anatomy_matches": True,
                        "single_scene": True,
                        "wrong_reason": "",
                    }
                )
            }

    def fake_post(*args, **kwargs) -> FakeResponse:
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(draw_module.requests, "post", fake_post)

    review = draw_module._review_image(
        image_path,
        3,
        "1girl, 2boys, spitroast, group sex",
    )

    assert review["ok"] is False
    assert review["reason"] == "gender_count"
    assert review["expected_female_count"] == 1
    assert review["female_count"] == 0
    assert "女性和男性数量" in captured["json"]["prompt"]


def _fake_vlm_response(payload: dict):
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"response": json.dumps(payload)}

    return FakeResponse()


def _group_detail_payload(
    *,
    character_count: int = 3,
    female_count: int = 1,
    male_count: int = 2,
    include_pose: bool = True,
) -> dict:
    heads = []
    for index in range(female_count):
        heads.append(
            {
                "x": 100 + index * 200,
                "y": 200,
                "gender": "female",
                "visibility": "full",
            }
        )
    for index in range(male_count):
        heads.append(
            {
                "x": 300 + index * 200,
                "y": 300,
                "gender": "male",
                "visibility": "full",
            }
        )
    payload = {
        "heads": heads,
        "character_count": character_count,
        "multiple_same": False,
        "action_matches": True,
        "composition_matches": True,
        "anatomy_matches": True,
        "single_scene": True,
        "wrong_reason": "",
    }
    if include_pose:
        payload["pose_matches"] = True
    return payload


def _counter_payload(count: int) -> dict:
    heads = [
        {
            "x": 100 + index * 100,
            "y": 200,
            "gender": "female" if index == 0 else "male",
            "visibility": "full",
        }
        for index in range(count)
    ]
    return {
        "heads": heads,
        "character_count": count,
        "count_confident": True,
        "uncertain": False,
    }


def test_review_image_rejects_empty_head_census(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-png")
    monkeypatch.setattr(
        draw_module.requests,
        "post",
        lambda *args, **kwargs: _fake_vlm_response(
            {
                "heads": [],
                "character_count": 0,
                "multiple_same": False,
                "pose_matches": True,
                "action_matches": True,
                "composition_matches": True,
                "anatomy_matches": True,
                "single_scene": True,
            }
        ),
    )

    review = draw_module._review_image(
        image_path,
        3,
        "1girl, 2boys, threesome, group sex",
    )

    assert review["ok"] is False
    assert review["reason"] == "invalid_review"
    assert review["count_consensus"] is False
    assert review["counter_character_count"] is None


def test_review_image_rejects_reported_count_mismatch(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-png")
    payload = _group_detail_payload(character_count=4)
    monkeypatch.setattr(
        draw_module.requests,
        "post",
        lambda *args, **kwargs: _fake_vlm_response(payload),
    )

    review = draw_module._review_image(
        image_path,
        3,
        "1girl, 2boys, threesome, group sex",
    )

    assert review["ok"] is False
    assert review["reason"] == "invalid_review"
    assert review["character_count"] == 3
    assert review["reported_character_count"] == 4


def test_review_image_rejects_missing_group_field(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-png")
    payload = _group_detail_payload(include_pose=False)
    monkeypatch.setattr(
        draw_module.requests,
        "post",
        lambda *args, **kwargs: _fake_vlm_response(payload),
    )

    review = draw_module._review_image(
        image_path,
        3,
        "1girl, 2boys, threesome, group sex",
    )

    assert review["ok"] is False
    assert review["reason"] == "invalid_review"
    assert review["pose_ok"] is None


def test_review_image_requires_independent_count_consensus(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-png")

    def fake_post(*args, **kwargs):
        model = kwargs["json"]["model"]
        if model == draw_module.VLM_COUNT_MODEL:
            return _fake_vlm_response(_counter_payload(4))
        return _fake_vlm_response(_group_detail_payload())

    monkeypatch.setattr(draw_module.requests, "post", fake_post)

    review = draw_module._review_image(
        image_path,
        3,
        "1girl, 2boys, threesome, group sex",
    )

    assert review["ok"] is False
    assert review["reason"] == "independent_count"
    assert review["count_consensus"] is False
    assert review["counter_character_count"] == 4


def test_review_image_accepts_crop_overcount_from_split_boundary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-png")
    monkeypatch.setattr(
        draw_module,
        "_encode_region_images",
        lambda _: {"left": "left-image", "right": "right-image"},
    )

    def fake_post(*args, **kwargs):
        model = kwargs["json"]["model"]
        prompt = kwargs["json"]["prompt"]
        if model != draw_module.VLM_COUNT_MODEL:
            return _fake_vlm_response(_group_detail_payload())
        if "检查完整图片" in prompt:
            return _fake_vlm_response(_counter_payload(3))
        return _fake_vlm_response(_counter_payload(2))

    monkeypatch.setattr(draw_module.requests, "post", fake_post)

    review = draw_module._review_image(
        image_path,
        3,
        "1girl, 2boys, threesome, group sex",
    )

    assert review["ok"] is True
    assert review["reason"] == ""
    assert review["count_consensus"] is True
    assert review["crop_counts"] == {"left": 2, "right": 2}
    assert review["crop_sum"] == 4


def test_review_image_rejects_crop_undercount(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-png")

    def fake_count(model, encoded_image, scope, *, allow_uncertain=False):
        if scope == "full":
            return 3, "", {}
        return 1, "", {}

    monkeypatch.setattr(
        draw_module,
        "_encode_region_images",
        lambda _: {"left": "left-image", "right": "right-image"},
    )
    monkeypatch.setattr(draw_module, "_independent_count", fake_count)
    monkeypatch.setattr(
        draw_module.requests,
        "post",
        lambda *args, **kwargs: _fake_vlm_response(_group_detail_payload()),
    )

    review = draw_module._review_image(
        image_path,
        3,
        "1girl, 2boys, threesome, group sex",
    )

    assert review["ok"] is False
    assert review["reason"] == "crop_count"
    assert review["count_consensus"] is False
    assert review["crop_sum"] == 2


def test_review_image_keeps_crop_errors_advisory(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-png")

    def fake_count(model, encoded_image, scope, *, allow_uncertain=False):
        if scope == "full":
            return 3, "", {}
        if scope == "left":
            return 2, "", {}
        return None, "inconsistent_count", {}

    monkeypatch.setattr(
        draw_module,
        "_encode_region_images",
        lambda _: {"left": "left-image", "right": "right-image"},
    )
    monkeypatch.setattr(draw_module, "_independent_count", fake_count)
    monkeypatch.setattr(
        draw_module.requests,
        "post",
        lambda *args, **kwargs: _fake_vlm_response(_group_detail_payload()),
    )

    review = draw_module._review_image(
        image_path,
        3,
        "1girl, 2boys, threesome, group sex",
    )

    assert review["ok"] is True
    assert review["count_consensus"] is True
    assert review["crop_sum"] is None
    assert review["crop_errors"] == {"right": "inconsistent_count"}


def test_counter_image_is_downsampled_to_stable_jpeg(tmp_path: Path) -> None:
    from PIL import Image

    image_path = tmp_path / "candidate.png"
    Image.new("RGB", (1920, 1080), "white").save(image_path)

    encoded = draw_module._encode_counter_image(image_path)

    with Image.open(io.BytesIO(base64.b64decode(encoded))) as prepared:
        assert prepared.format == "JPEG"
        assert prepared.size == (1280, 720)
        assert max(prepared.size) <= draw_module.COUNTER_IMAGE_MAX_SIDE


def test_counter_image_falls_back_for_undecodable_input(tmp_path: Path) -> None:
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-png")

    encoded = draw_module._encode_counter_image(image_path)

    assert base64.b64decode(encoded) == b"fake-png"


def test_independent_count_accepts_placeholder_enum_values(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        draw_module.requests,
        "post",
        lambda *args, **kwargs: _fake_vlm_response(
            {
                "heads": [
                    {
                        "x": 100,
                        "y": 100,
                        "gender": "male/female/unknown",
                        "visibility": "full/partial",
                    }
                ],
                "character_count": 1,
                "count_confident": True,
                "uncertain": False,
            }
        ),
    )

    count, error, _ = draw_module._independent_count(
        draw_module.VLM_COUNT_MODEL,
        "counter-image",
        "right",
    )

    assert count == 1
    assert error == ""


def test_independent_count_retries_transient_invalid_json(
    monkeypatch,
) -> None:
    calls = 0

    class FakeResponse:
        def __init__(self, body: str) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"response": self.body}

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return FakeResponse('{"heads": [}')
        return _fake_vlm_response(_counter_payload(3))

    monkeypatch.setattr(draw_module.requests, "post", fake_post)

    count, error, _ = draw_module._independent_count(
        draw_module.VLM_COUNT_MODEL,
        "counter-image",
        "full",
    )

    assert calls == 4
    assert count == 3
    assert error == ""


def test_independent_count_uses_majority_result(monkeypatch) -> None:
    counts = iter((3, 4, 3))

    def fake_post(*args, **kwargs):
        return _fake_vlm_response(_counter_payload(next(counts)))

    monkeypatch.setattr(draw_module.requests, "post", fake_post)

    count, error, _ = draw_module._independent_count(
        draw_module.VLM_COUNT_MODEL,
        "counter-image",
        "full",
    )

    assert count == 3
    assert error == ""


def test_independent_count_allows_uncertain_crop_majority(monkeypatch) -> None:
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        payload = _counter_payload(2)
        payload["uncertain"] = True
        return _fake_vlm_response(payload)

    monkeypatch.setattr(draw_module.requests, "post", fake_post)

    count, error, _ = draw_module._independent_count(
        draw_module.VLM_COUNT_MODEL,
        "counter-image",
        "right",
        allow_uncertain=True,
    )

    assert calls == 3
    assert count == 2
    assert error == ""


def test_independent_count_rejects_uncertain_full_image(monkeypatch) -> None:
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        payload = _counter_payload(3)
        payload["uncertain"] = True
        return _fake_vlm_response(payload)

    monkeypatch.setattr(draw_module.requests, "post", fake_post)

    count, error, _ = draw_module._independent_count(
        draw_module.VLM_COUNT_MODEL,
        "counter-image",
        "full",
    )

    assert calls == 5
    assert count is None
    assert error == "uncertain"


def test_call_ollama_json_requests_deterministic_json_mode(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(*args, **kwargs):
        captured.update(kwargs["json"])
        return _fake_vlm_response(_counter_payload(3))

    monkeypatch.setattr(draw_module.requests, "post", fake_post)

    draw_module._call_ollama_json(
        draw_module.VLM_COUNT_MODEL,
        "counter",
        ["counter-image"],
        num_predict=180,
    )

    assert captured["format"] == "json"
    assert captured["options"]["temperature"] == 0.1
    assert captured["options"]["top_p"] == 0.9


def test_review_image_uses_preprocessed_counter_image(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"fake-png")
    monkeypatch.setattr(
        draw_module,
        "_encode_counter_image",
        lambda _: "counter-image",
    )
    monkeypatch.setattr(
        draw_module,
        "_encode_region_images",
        lambda _: {"left": "left-image", "right": "right-image"},
    )
    counter_images: list[str] = []

    def fake_post(*args, **kwargs):
        model = kwargs["json"]["model"]
        prompt = kwargs["json"]["prompt"]
        if model != draw_module.VLM_COUNT_MODEL:
            return _fake_vlm_response(_group_detail_payload())
        if "检查完整图片" in prompt:
            counter_images.extend(kwargs["json"]["images"])
            return _fake_vlm_response(_counter_payload(3))
        return _fake_vlm_response(
            _counter_payload(2 if "左半区" in prompt else 1)
        )

    monkeypatch.setattr(draw_module.requests, "post", fake_post)

    review = draw_module._review_image(
        image_path,
        3,
        "1girl, 2boys, threesome, group sex",
    )

    assert review["ok"] is True
    assert counter_images == ["counter-image"] * 3


def test_group_pose_presets_have_draw_prompt() -> None:
    group_presets = [
        preset
        for preset in POSE_PRESETS
        if preset.get("category") in ("3P", "群交")
    ]
    assert group_presets
    for preset in group_presets:
        assert str(preset.get("draw_prompt") or "").strip(), preset.get("id")
        assert "exactly" in str(preset["draw_prompt"]).lower() or "or more" in str(
            preset["draw_prompt"]
        ).lower() or "multiple" in str(preset["draw_prompt"]).lower(), preset.get("id")


def test_group_pose_presets_have_explicit_people_pose_action_and_composition() -> None:
    group_presets = [
        preset
        for preset in POSE_PRESETS
        if preset.get("category") in ("3P", "群交")
    ]
    assert group_presets
    for preset in group_presets:
        prompt = str(preset.get("draw_prompt") or "").lower()
        preset_id = str(preset.get("id"))
        assert _expected_count(prompt) in (3, 4), preset_id
        assert "separate " in prompt, preset_id
        assert "wide shot" in prompt, preset_id
        assert any(
            marker in prompt
            for marker in (
                "kneels",
                "kneeling",
                "lies",
                "lying",
                "straddles",
                "stands",
                "on all fours",
                "lifted",
            )
        ), preset_id
        assert any(
            marker in prompt
            for marker in (
                "penetrates",
                "performs fellatio",
                "receives cunnilingus",
                "fingers",
                "strokes",
                "enter",
                "enters",
            )
        ), preset_id
        assert any(
            marker in prompt
            for marker in (
                "contact mapping",
                "contact point",
                "contact points",
                "insertion",
                "insertions",
                "both pairs",
            )
        ), preset_id
        assert "no extra people" in prompt, preset_id
        assert "no missing people" in prompt, preset_id
        assert "no merged bodies" in prompt, preset_id
        assert "single continuous scene" in prompt, preset_id
        assert "exactly one head, two arms, and two legs" in prompt, preset_id


def test_train_line_uses_gangbang_queue_wording() -> None:
    preset = next(item for item in POSE_PRESETS if item["id"] == "train_line")
    prompt = str(preset["draw_prompt"]).lower()
    assert "gangbang queue" in prompt
    assert "connected train" not in prompt


def _guard_args(prompt: str) -> dict:
    return {
        "prompt": prompt,
        "negative_prompt": "",
        "width": 1080,
        "height": 1920,
        "steps": 18,
        "cfg": 1.0,
        "model": "test.safetensors",
        "loras": [],
        "seed": 123,
        "lora_strength_model": 0.8,
        "lora_strength_clip": 0.8,
        "lora_strengths": None,
    }


def test_people_guard_retries_with_new_seed_and_strengthened_prompt(monkeypatch) -> None:
    calls: list[dict] = []
    reviews = iter(
        [
            {
                "ok": False,
                "character_count": 2,
                "expected_count": 3,
                "multiple_same": False,
                "reason": "character_count",
                "quality_score": 20,
                "message": "提示词期望 3 个角色，图片检测到 2 个",
            },
            {
                "ok": True,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": False,
                "review_status": "auto_passed",
                "quality_score": 60,
                "message": "",
            },
            {
                "ok": False,
                "character_count": 2,
                "expected_count": 3,
                "multiple_same": False,
                "reason": "character_count",
                "quality_score": 99,
                "message": "提示词期望 3 个角色，图片检测到 2 个",
            },
        ]
    )

    def fake_generate(**kwargs) -> dict:
        calls.append(kwargs)
        return {
            "saved_path": f"/tmp/candidate-{len(calls)}.png",
            "image_url": f"/api/images/candidate-{len(calls)}.png",
            "seed": kwargs["seed"],
        }

    monkeypatch.setattr(draw_module, "generate", fake_generate)
    monkeypatch.setattr(draw_module, "_maybe_visual_review", lambda *_: next(reviews))
    monkeypatch.setattr(draw_module.random, "randint", lambda *_: next(seeds))
    seeds = iter([777, 888])

    result, review, guard = draw_module._generate_with_people_guard(
        **_guard_args("1girl, 2boys, threesome")
    )

    assert [call["seed"] for call in calls] == [123, 777, 888]
    assert "exactly 3 separate people" in calls[1]["prompt"]
    assert "preserve every specified character position" in calls[1]["prompt"]
    assert "do not change the pose or roles" in calls[1]["prompt"]
    assert "exactly 3 separate people" in calls[2]["prompt"]
    assert result["seed"] == 777
    assert review and review["ok"] is True
    assert guard is not None
    assert guard["expected_count"] == 3
    assert guard["attempts"] == 3
    assert guard["retries"] == 2
    assert guard["passed"] is True
    assert guard["strengthened"] is True
    assert guard["reason"] == ""
    assert guard["candidate_count"] == 3
    assert guard["selected_attempt"] == 2
    assert guard["quality_score"] == 60


def test_people_guard_returns_best_failed_candidate_when_all_fail(monkeypatch) -> None:
    calls: list[dict] = []
    reviews = iter(
        [
            {
                "ok": False,
                "character_count": 2,
                "expected_count": 3,
                "multiple_same": False,
                "reason": "character_count",
                "quality_score": 20,
                "message": "提示词期望 3 个角色，图片检测到 2 个",
            },
            {
                "ok": False,
                "character_count": 2,
                "expected_count": 3,
                "multiple_same": False,
                "reason": "character_count",
                "quality_score": 80,
                "message": "提示词期望 3 个角色，图片检测到 2 个",
            },
            {
                "ok": False,
                "character_count": 2,
                "expected_count": 3,
                "multiple_same": False,
                "reason": "character_count",
                "quality_score": 10,
                "message": "提示词期望 3 个角色，图片检测到 2 个",
            },
        ]
    )
    seeds = iter([777, 888])

    def fake_generate(**kwargs) -> dict:
        calls.append(kwargs)
        return {
            "saved_path": f"/tmp/candidate-{len(calls)}.png",
            "image_url": f"/api/images/candidate-{len(calls)}.png",
            "seed": kwargs["seed"],
        }

    monkeypatch.setattr(draw_module, "generate", fake_generate)
    monkeypatch.setattr(draw_module, "_maybe_visual_review", lambda *_: next(reviews))
    monkeypatch.setattr(draw_module.random, "randint", lambda *_: next(seeds))

    result, review, guard = draw_module._generate_with_people_guard(
        **_guard_args("1girl, 2boys, threesome")
    )

    assert len(calls) == 3
    assert result["seed"] == 777
    assert review and review["ok"] is False
    assert review["quality_score"] == 80
    assert guard is not None
    assert guard["attempts"] == 3
    assert guard["retries"] == 2
    assert guard["passed"] is False
    assert guard["reason"] == "character_count"
    assert guard["selected_attempt"] == 2


def test_people_guard_skips_retry_when_expected_count_unknown(monkeypatch) -> None:
    calls: list[dict] = []
    review = {
        "ok": False,
        "character_count": 2,
        "expected_count": None,
        "multiple_same": True,
        "message": "图片检测到多个相同角色",
    }

    def fake_generate(**kwargs) -> dict:
        calls.append(kwargs)
        return {
            "saved_path": "/tmp/candidate.png",
            "image_url": "/api/images/candidate.png",
            "seed": kwargs["seed"],
        }

    monkeypatch.setattr(draw_module, "generate", fake_generate)
    monkeypatch.setattr(draw_module, "_maybe_visual_review", lambda *_: review)

    result, returned_review, guard = draw_module._generate_with_people_guard(
        **_guard_args("multiple people lined up, group sex")
    )

    assert len(calls) == 1
    assert result["seed"] == 123
    assert returned_review == review
    assert guard is None


def test_generation_error_retry_does_not_count_as_people_guard_retry(monkeypatch) -> None:
    calls: list[dict] = []
    reviews = iter(
        [
            {
                "ok": False,
                "character_count": 2,
                "expected_count": 3,
                "multiple_same": False,
                "reason": "character_count",
                "quality_score": 20,
                "message": "提示词期望 3 个角色，图片检测到 2 个",
            },
            {
                "ok": True,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": False,
                "review_status": "auto_passed",
                "quality_score": 65,
                "message": "",
            },
            {
                "ok": False,
                "character_count": 2,
                "expected_count": 3,
                "multiple_same": False,
                "reason": "character_count",
                "quality_score": 90,
                "message": "提示词期望 3 个角色，图片检测到 2 个",
            },
        ]
    )
    seeds = iter([777, 888])

    def fake_generate(**kwargs) -> dict:
        calls.append(kwargs)
        if len(calls) == 1:
            raise TimeoutError("timeout")
        return {
            "saved_path": f"/tmp/candidate-{len(calls)}.png",
            "image_url": f"/api/images/candidate-{len(calls)}.png",
            "seed": kwargs["seed"],
        }

    monkeypatch.setattr(draw_module, "generate", fake_generate)
    monkeypatch.setattr(draw_module, "_maybe_visual_review", lambda *_: next(reviews))
    monkeypatch.setattr(draw_module.random, "randint", lambda *_: next(seeds))
    monkeypatch.setattr(draw_module.time, "sleep", lambda *_: None)

    result, review, guard = draw_module._generate_with_people_guard(
        **_guard_args("1girl, 2boys, threesome")
    )

    assert [call["seed"] for call in calls] == [123, 123, 777, 888]
    assert calls[0]["prompt"] == calls[1]["prompt"]
    assert "exactly 3 separate people" not in calls[1]["prompt"]
    assert "exactly 3 separate people" in calls[2]["prompt"]
    assert "exactly 3 separate people" in calls[3]["prompt"]
    assert result["seed"] == 777
    assert review and review["ok"] is True
    assert guard is not None
    assert guard["attempts"] == 3
    assert guard["retries"] == 2
    assert guard["selected_attempt"] == 2


def test_people_guard_retries_when_group_pose_or_action_mismatch(monkeypatch) -> None:
    calls: list[dict] = []
    reviews = iter(
        [
            {
                "ok": False,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": False,
                "pose_ok": False,
                "action_ok": True,
                "composition_ok": False,
                "wrong_reason": "角色位置颠倒",
                "reason": "group_pose",
                "quality_score": 25,
                "message": "群交姿势与提示词不符",
            },
            {
                "ok": True,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": False,
                "pose_ok": True,
                "action_ok": True,
                "composition_ok": True,
                "reason": "",
                "review_status": "auto_passed",
                "quality_score": 70,
                "message": "",
            },
            {
                "ok": False,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": False,
                "pose_ok": True,
                "action_ok": False,
                "composition_ok": True,
                "wrong_reason": "动作关系错误",
                "reason": "group_action",
                "quality_score": 98,
                "message": "群交动作与提示词不符",
            },
        ]
    )
    seeds = iter([888, 999])

    def fake_generate(**kwargs) -> dict:
        calls.append(kwargs)
        return {
            "saved_path": f"/tmp/candidate-{len(calls)}.png",
            "image_url": f"/api/images/candidate-{len(calls)}.png",
            "seed": kwargs["seed"],
        }

    monkeypatch.setattr(draw_module, "generate", fake_generate)
    monkeypatch.setattr(draw_module, "_maybe_visual_review", lambda *_: next(reviews))
    monkeypatch.setattr(draw_module.random, "randint", lambda *_: next(seeds))

    result, review, guard = draw_module._generate_with_people_guard(
        **_guard_args("1girl, 2boys, threesome, group sex")
    )

    assert [call["seed"] for call in calls] == [123, 888, 999]
    assert "preserve every specified character position" in calls[1]["prompt"]
    assert "preserve every specified character position" in calls[2]["prompt"]
    assert result["seed"] == 888
    assert review and review["ok"] is True
    assert guard is not None
    assert guard["attempts"] == 3
    assert guard["retries"] == 2
    assert guard["passed"] is True
    assert guard["strengthened"] is True
    assert guard["reason"] == ""
    assert guard["selected_attempt"] == 2
    assert guard["quality_score"] == 70
    assert guard["pose_ok"] is True
    assert guard["action_ok"] is True
    assert guard["composition_ok"] is True


def test_group_pose_detection_requires_group_marker_and_three_people() -> None:
    assert draw_module._is_group_pose_prompt(
        "exactly 3 separate people in one wide shot, threesome, group sex"
    )
    assert not draw_module._is_group_pose_prompt(
        "exactly 3 separate people in one wide shot, friends standing"
    )
    assert not draw_module._is_group_pose_prompt(
        "exactly 2 separate people in one wide shot, threesome"
    )


def test_multiple_same_triggers_retry_and_passes_after_clean_candidate(monkeypatch) -> None:
    calls: list[dict] = []
    reviews = iter(
        [
            {
                "ok": False,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": True,
                "reason": "multiple_same",
                "quality_score": 15,
                "message": "图片检测到多个相同角色",
            },
            {
                "ok": True,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": False,
                "reason": "",
                "review_status": "auto_passed",
                "quality_score": 75,
                "message": "",
            },
            {
                "ok": False,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": True,
                "reason": "multiple_same",
                "quality_score": 95,
                "message": "图片检测到多个相同角色",
            },
        ]
    )
    seeds = iter([999, 1000])

    def fake_generate(**kwargs) -> dict:
        calls.append(kwargs)
        return {
            "saved_path": f"/tmp/candidate-{len(calls)}.png",
            "image_url": f"/api/images/candidate-{len(calls)}.png",
            "seed": kwargs["seed"],
        }

    monkeypatch.setattr(draw_module, "generate", fake_generate)
    monkeypatch.setattr(draw_module, "_maybe_visual_review", lambda *_: next(reviews))
    monkeypatch.setattr(draw_module.random, "randint", lambda *_: next(seeds))

    result, review, guard = draw_module._generate_with_people_guard(
        **_guard_args("1girl, 2boys, threesome, group sex")
    )

    assert [call["seed"] for call in calls] == [123, 999, 1000]
    assert "no duplicated characters" in calls[1]["prompt"]
    assert "no duplicated characters" in calls[2]["prompt"]
    assert result["seed"] == 999
    assert review and review["ok"] is True
    assert guard is not None
    assert guard["passed"] is True
    assert guard["retries"] == 2
    assert guard["selected_attempt"] == 2
    assert guard["reason"] == ""


def test_multiple_same_keeps_guard_failed_when_retry_is_still_dirty(monkeypatch) -> None:
    calls: list[dict] = []
    reviews = iter(
        [
            {
                "ok": False,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": True,
                "reason": "multiple_same",
                "quality_score": 30,
                "message": "图片检测到多个相同角色",
            },
            {
                "ok": False,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": True,
                "reason": "multiple_same",
                "quality_score": 88,
                "message": "图片检测到多个相同角色",
            },
            {
                "ok": False,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": True,
                "reason": "multiple_same",
                "quality_score": 45,
                "message": "图片检测到多个相同角色",
            },
        ]
    )
    seeds = iter([1001, 1002])

    def fake_generate(**kwargs) -> dict:
        calls.append(kwargs)
        return {
            "saved_path": f"/tmp/candidate-{len(calls)}.png",
            "image_url": f"/api/images/candidate-{len(calls)}.png",
            "seed": kwargs["seed"],
        }

    monkeypatch.setattr(draw_module, "generate", fake_generate)
    monkeypatch.setattr(draw_module, "_maybe_visual_review", lambda *_: next(reviews))
    monkeypatch.setattr(draw_module.random, "randint", lambda *_: next(seeds))

    _, review, guard = draw_module._generate_with_people_guard(
        **_guard_args("1girl, 2boys, threesome, group sex")
    )

    assert len(calls) == 3
    assert review and review["ok"] is False
    assert review["quality_score"] == 88
    assert guard is not None
    assert guard["passed"] is False
    assert guard["reason"] == "multiple_same"
    assert guard["selected_attempt"] == 2


def test_group_candidates_pick_highest_quality_and_delete_rejected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict] = []
    reviews = iter(
        [
            {
                "ok": True,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": False,
                "review_status": "auto_passed",
                "quality_score": 40,
            },
            {
                "ok": True,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": False,
                "review_status": "auto_passed",
                "quality_score": 96,
            },
            {
                "ok": True,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": False,
                "review_status": "auto_passed",
                "quality_score": 80,
            },
        ]
    )
    seeds = iter([2001, 2002])

    def fake_generate(**kwargs) -> dict:
        calls.append(kwargs)
        path = tmp_path / f"candidate-{len(calls)}.png"
        path.write_bytes(b"fake-png")
        return {
            "saved_path": str(path),
            "image_url": f"/api/images/{path.name}",
            "seed": kwargs["seed"],
        }

    monkeypatch.setattr(draw_module, "generate", fake_generate)
    monkeypatch.setattr(draw_module, "_maybe_visual_review", lambda *_: next(reviews))
    monkeypatch.setattr(draw_module.random, "randint", lambda *_: next(seeds))

    result, review, guard = draw_module._generate_with_people_guard(
        **_guard_args("1girl, 2boys, threesome, group sex")
    )

    selected_path = tmp_path / "candidate-2.png"
    assert len(calls) == MAX_GROUP_CANDIDATES
    assert result["saved_path"] == str(selected_path)
    assert selected_path.exists()
    assert not (tmp_path / "candidate-1.png").exists()
    assert not (tmp_path / "candidate-3.png").exists()
    assert review and review["quality_score"] == 96
    assert guard is not None
    assert guard["candidate_count"] == MAX_GROUP_CANDIDATES
    assert guard["selected_attempt"] == 2
    assert guard["quality_score"] == 96


def test_invalid_review_candidate_cannot_beat_valid_candidate(monkeypatch) -> None:
    calls: list[dict] = []
    reviews = iter(
        [
            {
                "ok": True,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": False,
                "review_status": "auto_passed",
                "quality_score": 55,
            },
            {
                "ok": False,
                "character_count": None,
                "expected_count": 3,
                "multiple_same": None,
                "reason": "invalid_review",
                "review_status": "manual_review",
                "quality_score": 100,
            },
            {
                "ok": False,
                "character_count": 2,
                "expected_count": 3,
                "multiple_same": False,
                "reason": "character_count",
                "review_status": "manual_review",
                "quality_score": 100,
            },
        ]
    )
    seeds = iter([2101, 2102])

    def fake_generate(**kwargs) -> dict:
        calls.append(kwargs)
        return {
            "saved_path": f"/tmp/candidate-{len(calls)}.png",
            "image_url": f"/api/images/candidate-{len(calls)}.png",
            "seed": kwargs["seed"],
        }

    monkeypatch.setattr(draw_module, "generate", fake_generate)
    monkeypatch.setattr(draw_module, "_maybe_visual_review", lambda *_: next(reviews))
    monkeypatch.setattr(draw_module.random, "randint", lambda *_: next(seeds))

    result, review, guard = draw_module._generate_with_people_guard(
        **_guard_args("1girl, 2boys, threesome, group sex")
    )

    assert len(calls) == MAX_GROUP_CANDIDATES
    assert result["seed"] == 123
    assert review and review["ok"] is True
    assert guard is not None
    assert guard["passed"] is True
    assert guard["selected_attempt"] == 1


def test_all_group_candidates_fail_returns_best_failed_candidate(monkeypatch) -> None:
    calls: list[dict] = []
    reviews = iter(
        [
            {
                "ok": False,
                "character_count": 2,
                "expected_count": 3,
                "multiple_same": False,
                "reason": "character_count",
                "review_status": "manual_review",
                "quality_score": 10,
            },
            {
                "ok": False,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": False,
                "pose_ok": False,
                "reason": "group_pose",
                "review_status": "manual_review",
                "quality_score": 80,
            },
            {
                "ok": False,
                "character_count": 3,
                "expected_count": 3,
                "multiple_same": None,
                "reason": "invalid_review",
                "review_status": "manual_review",
                "quality_score": 100,
            },
        ]
    )
    seeds = iter([2201, 2202])

    def fake_generate(**kwargs) -> dict:
        calls.append(kwargs)
        return {
            "saved_path": f"/tmp/candidate-{len(calls)}.png",
            "image_url": f"/api/images/candidate-{len(calls)}.png",
            "seed": kwargs["seed"],
        }

    monkeypatch.setattr(draw_module, "generate", fake_generate)
    monkeypatch.setattr(draw_module, "_maybe_visual_review", lambda *_: next(reviews))
    monkeypatch.setattr(draw_module.random, "randint", lambda *_: next(seeds))

    result, review, guard = draw_module._generate_with_people_guard(
        **_guard_args("1girl, 2boys, threesome, group sex")
    )

    assert len(calls) == MAX_GROUP_CANDIDATES
    assert result["seed"] == 2201
    assert review and review["reason"] == "group_pose"
    assert review["review_status"] == "manual_review"
    assert guard is not None
    assert guard["passed"] is False
    assert guard["reason"] == "group_pose"
    assert guard["selected_attempt"] == 2
    assert guard["review_status"] == "manual_review"


def test_non_group_prompt_uses_single_candidate(monkeypatch) -> None:
    calls: list[dict] = []
    review = {
        "ok": True,
        "character_count": 2,
        "expected_count": 2,
        "multiple_same": False,
        "review_status": "auto_passed",
        "quality_score": 80,
    }

    def fake_generate(**kwargs) -> dict:
        calls.append(kwargs)
        return {
            "saved_path": "/tmp/non-group.png",
            "image_url": "/api/images/non-group.png",
            "seed": kwargs["seed"],
        }

    monkeypatch.setattr(draw_module, "generate", fake_generate)
    monkeypatch.setattr(draw_module, "_maybe_visual_review", lambda *_: review)

    result, returned_review, guard = draw_module._generate_with_people_guard(
        **_guard_args("1girl, 1boy, standing together")
    )

    assert len(calls) == 1
    assert result["seed"] == 123
    assert returned_review == review
    assert guard is not None
    assert guard["attempts"] == 1
    assert guard["retries"] == 0
    assert guard["passed"] is True
    assert "candidate_count" not in guard
