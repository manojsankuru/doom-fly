import json
from collections import Counter
from pathlib import Path
from typing import Any

import bridge

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "web" / "blueprint-graph.json"
ACTIVITY = ROOT / "fixtures" / "replay-activity.jsonl"
CONTROLLER_CELLS = {
    "10162": "DNp20_L",
    "10059": "DNp20_R",
    "10527": "DNpe017",
    "555871": "DNpe017",
    "11327": "PPL101_11327",
    "11900": "PPL101_11900",
}


def graph() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(GRAPH.read_text(encoding="utf-8"))
    return payload


def test_graph_has_500_unique_neurons_and_valid_edges() -> None:
    data = graph()
    nodes, edges = data["nodes"], data["edges"]
    assert len(nodes) == 500
    assert len({n["id"] for n in nodes}) == 500
    assert len(edges) == data["stats"]["edges"]
    assert len({(s, t) for s, t, _, _ in edges}) == len(edges)
    for source, target, contacts, sign in edges:
        assert 0 <= source < 500 and 0 <= target < 500 and source != target
        assert contacts >= 1
        assert sign in (1, -1)


def test_the_five_controller_groups_are_the_bridge_keys() -> None:
    controllers = {n["id"]: n["controller"] for n in graph()["nodes"] if "controller" in n}
    assert controllers == CONTROLLER_CELLS
    assert set(controllers.values()) == set(bridge.NEURON_KEYS)


def test_every_streamed_cell_is_a_live_node_in_the_graph() -> None:
    nodes = {n["id"]: n for n in graph()["nodes"]}
    streaming = {body for body, node in nodes.items() if node["live"] in ("readout", "raster")}
    messages = bridge.load_replay(ACTIVITY)
    assert {m["activity"]["observed"] for m in messages} == {len(streaming)}
    fired = {body for m in messages for body in m["activity"]["rates"]}
    assert fired
    assert fired <= streaming


def test_live_labels_match_groups() -> None:
    counts = Counter((n["group"], n["live"]) for n in graph()["nodes"])
    assert counts[("controller", "readout")] == 4
    assert counts[("controller", "v6")] == 2
    assert counts[("readout", "readout")] == 10
    assert counts[("raster", "raster")] == 128
    assert counts[("context", "none")] == 356


def test_activity_fixture_is_continuous_and_holds_a_rare_spike() -> None:
    messages = bridge.load_replay(ACTIVITY)
    sequences = [m["sequence"] for m in messages]
    assert max(b - a for a, b in zip(sequences, sequences[1:])) <= 3
    assert any("64902" in m["activity"]["rates"] for m in messages)
    assert all(m["neurons"]["PPL101_11327"] is None for m in messages)
