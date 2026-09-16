import math
from pathlib import Path

import bridge

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "replay-round-change.jsonl"
ARENA_HALF = 384
PLAYER_RADIUS = 16
SNAP_UNITS = 64


def angle_between(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def moving_pairs() -> list[tuple[dict, dict]]:
    messages = bridge.load_replay(FIXTURE)
    return [
        (a, b)
        for a, b in zip(messages, messages[1:])
        if a["round"] == b["round"]
        and b["sequence"] - a["sequence"] == 1
        and math.hypot(b["pos"][0] - a["pos"][0], b["pos"][1] - a["pos"][1]) >= 8
    ]


def test_heading_is_counter_clockwise_from_positive_x() -> None:
    pairs = moving_pairs()
    assert len(pairs) > 100
    counter_clockwise = [
        angle_between(math.degrees(math.atan2(b["pos"][1] - a["pos"][1], b["pos"][0] - a["pos"][0])) % 360, a["heading"] % 360)
        for a, b in pairs
    ]
    clockwise = [
        angle_between(math.degrees(math.atan2(b["pos"][1] - a["pos"][1], b["pos"][0] - a["pos"][0])) % 360, -a["heading"] % 360)
        for a, b in pairs
    ]
    assert sum(error < 20 for error in counter_clockwise) / len(pairs) > 0.9
    assert sum(error < 20 for error in clockwise) / len(pairs) < 0.5


def test_positions_stay_inside_the_arena_the_viewer_draws() -> None:
    limit = ARENA_HALF - PLAYER_RADIUS
    for message in bridge.load_replay(FIXTURE):
        x, y, z = message["pos"]
        assert -limit - 1 <= x <= limit + 1
        assert -limit - 1 <= y <= limit + 1
        assert z == 0


def test_in_round_steps_never_trigger_the_viewer_snap() -> None:
    messages = bridge.load_replay(FIXTURE)
    for a, b in zip(messages, messages[1:]):
        step = math.hypot(b["pos"][0] - a["pos"][0], b["pos"][1] - a["pos"][1])
        if a["round"] == b["round"]:
            assert step < SNAP_UNITS
        else:
            assert step > SNAP_UNITS
