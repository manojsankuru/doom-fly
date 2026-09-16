import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
state = json.loads(source.read_text())
bci = {"DNp20", "DNpe017"}

trimmed = {
    **{k: state[k] for k in ("schema", "status", "run_id", "sequence", "generated_at_ms", "condition", "decoder")},
    "frame": state["frame"][:38] + "...",
    "input_frame_sha256": state["input_frame_sha256"],
    "display_jpeg_sha256": state["display_jpeg_sha256"],
    "provenance": {"...": "graph, kernel and game asset hashes"},
    "manifest": {
        "dataset": state["manifest"]["dataset"],
        "neurons": state["manifest"]["neurons"],
        "edges": state["manifest"]["edges"],
        "readouts": [{k: r[k] for k in ("index", "id", "type", "side")} for r in state["readouts"] if r["type"] in bci],
    },
    "clocks": state["clocks"],
    "game": state["game"],
    "episodes": state["episodes"][:1],
    "action": state["action"],
    "readouts": [r for r in state["readouts"] if r["type"] in bci],
    "total_spikes": state["total_spikes"],
    "window_spikes": state["window_spikes"],
    "window_ms": state["window_ms"],
    "total_action_ticks": state["total_action_ticks"],
    "neuron_voltage_mv": {r["id"]: state["neuron_voltage_mv"][r["id"]] for r in state["readouts"] if r["type"] in bci},
    "populations": state["populations"][:2],
    "retina": {k: (v[:3] if isinstance(v, list) else v) for k, v in state["retina"].items()},
    "raster": {
        "neuron_ids": state["raster"]["neuron_ids"][:4],
        "bins": [{**state["raster"]["bins"][-1], "counts": state["raster"]["bins"][-1]["counts"][:4]}],
    },
    "timeline": state["timeline"][-1:],
    "audit": {k: state["audit"][k] for k in ("run_id", "tick", "neural_ms", "episode", "requested", "applied", "reward") if k in state["audit"]},
    "reward": state["reward"],
    "protocol": {k: state["protocol"][k] for k in ("scenario", "phase", "broadcast_capture_fps_limit", "frame_timing", "episode_end") if k in state["protocol"]},
    "spectator": {
        **{k: state["spectator"][k] for k in ("version", "timing", "episode", "tick", "player")},
        "objects": state["spectator"]["objects"][:3],
        "sectors": state["spectator"]["sectors"],
    },
}
target.write_text(json.dumps(trimmed, indent=2) + "\n")
print("wrote", target, target.stat().st_size, "bytes")
print("objects kept", len(trimmed["spectator"]["objects"]), "of", len(state["spectator"]["objects"]))
print(json.dumps(trimmed["spectator"], indent=1)[:900])
