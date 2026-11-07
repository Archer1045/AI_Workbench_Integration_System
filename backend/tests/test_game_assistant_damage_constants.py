from __future__ import annotations

import pytest

from game_assistant.damage_constants import (
    attribute_relation_multiplier,
    class_attack_rate,
    class_relation_multiplier,
    combined_class_multiplier,
)


def test_beast_class_relation_is_not_forced_neutral() -> None:
    assert class_attack_rate("Beast") == pytest.approx(1.0)
    assert class_relation_multiplier("Beast", "Rider") == pytest.approx(1.5)
    assert combined_class_multiplier("Beast", "Rider") == pytest.approx(1.5)


def test_class_attack_rate_and_triangle_are_combined() -> None:
    assert class_attack_rate("Assassin") == pytest.approx(0.9)
    assert class_relation_multiplier("Assassin", "Rider") == pytest.approx(2.0)
    assert combined_class_multiplier("Assassin", "Rider") == pytest.approx(1.8)


def test_attribute_relation_uses_atlas_table() -> None:
    assert attribute_relation_multiplier("star", "beast") == pytest.approx(1.1)
    assert attribute_relation_multiplier("star", "human") == pytest.approx(1.0)
