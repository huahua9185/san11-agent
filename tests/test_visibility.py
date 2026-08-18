from __future__ import annotations

import pytest

from san11agent.visibility import (
    StaticVisibilitySource,
    UnresolvedVisibilitySource,
    VisibilityUnknownError,
)


def test_static_visibility_source_defaults_to_nothing_visible():
    vis = StaticVisibilitySource(_player_faction_id=0)
    assert vis.player_faction_id == 0
    assert vis.is_city_explored(1) is False
    assert vis.is_troop_visible(1) is False
    assert vis.is_general_discovered(1) is False


def test_static_visibility_source_respects_explicit_sets():
    vis = StaticVisibilitySource(
        _player_faction_id=0,
        explored_city_indices=frozenset({2, 5}),
        visible_troop_indices=frozenset({7}),
        discovered_general_indices=frozenset({9}),
    )
    assert vis.is_city_explored(2) is True
    assert vis.is_city_explored(3) is False
    assert vis.is_troop_visible(7) is True
    assert vis.is_troop_visible(8) is False
    assert vis.is_general_discovered(9) is True
    assert vis.is_general_discovered(10) is False


def test_unresolved_visibility_source_reports_player_faction_id_without_error():
    # player_faction_id 不依赖任何未知内存字段，见 docs/visibility_research.md 第2节。
    vis = UnresolvedVisibilitySource(player_faction_id=3)
    assert vis.player_faction_id == 3


@pytest.mark.parametrize(
    "method_name",
    ["is_city_explored", "is_troop_visible", "is_general_discovered"],
)
def test_unresolved_visibility_source_raises_for_unknown_questions(method_name):
    vis = UnresolvedVisibilitySource(player_faction_id=0)
    method = getattr(vis, method_name)
    with pytest.raises(VisibilityUnknownError):
        method(0)
