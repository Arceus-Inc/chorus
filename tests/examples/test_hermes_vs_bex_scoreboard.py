from __future__ import annotations

from examples.hermes_vs_bex_hard10 import _scoreboard


def test_scoreboard_aggregates_pass_rate_spawns_and_medians() -> None:
    rows = [
        {
            "hermes_pytest": True,
            "bex_ok": True,
            "gap": {
                "hermes_wall_s": 10,
                "bex_wall_s": 20,
                "bex_spawns": 2,
                "bex_slower": True,
            },
        },
        {
            "hermes_pytest": True,
            "bex_ok": False,
            "gap": {
                "hermes_wall_s": 12,
                "bex_wall_s": 30,
                "bex_spawns": 0,
                "bex_slower": True,
            },
        },
    ]

    scoreboard = _scoreboard(rows)

    assert scoreboard == {
        "tickets_compared": 2,
        "hermes_pass_at_1": 2,
        "bex_pass_at_1": 1,
        "bex_completion_rate": 0.5,
        "bex_spawn_total": 2,
        "bex_median_wall_s": 25.0,
        "hermes_median_wall_s": 11.0,
        "bex_slower_count": 2,
    }
