# DOOMFLY telemetry on port 8766

Session 1 output. Source of truth: `doomfly/doom/server.py` (`run_loop`, `Handler`), `doom/broadcast.py`, `doom/game.py`, `doom/engine.py`, `doom/training.py`. The four docs describe the loop but not the wire format.

## Transport

Port 8766 is a plain HTTP server bound to 127.0.0.1. It is not a websocket and it does not push.

| Endpoint | Body |
| --- | --- |
| `GET /state` | Latest full message (below). Replaced at most 8 times per wall second (`DISPLAY_FPS = 8`). |
| `GET /index` | `{transport, status, run_id, generated_at_ms, sequence, segments[-4:], playout_delay_ms: 2500, capture_fps_limit, phase}` |
| `GET /segments/<run_id>/<unix_second>` | Immutable 1 s batch: `{transport: 1, shared: {...}, frames: [...]}`. The last 30 are kept. |
| `GET /health` | `{status, run_id, sequence, generated_at_ms}` |
| `GET /observer?...` | Native spectator render for a camera pose. |

A bridge must poll `/state` (about 125 ms) or follow `/index` and fetch new segments. Segment `frames[]` carry a subset: `sequence, generated_at_ms, frame, clocks, game, episodes, action, readouts, total_spikes, window_spikes, window_ms, total_action_ticks, audit, reward, luminance, raster_bin`, plus `learning` and `spectator` when present. `neuron_voltage_mv`, `populations` and `retina` are only in `/state`.

Before the loop starts, `/state` is `{"status":"starting","generated_at_ms":0}`. On a crash it becomes `{"status":"error",...}`.

## Field map

| Want | Field | Notes |
| --- | --- | --- |
| Fly position | `spectator.player.x`, `.y`, `.z` | Doom map units. Pre-action state. Nothing in `game` carries position. |
| Heading | `spectator.player.angle` | Degrees, engine value. `pitch` is also present. |
| Health | `game.health` | Post-action. Goes negative on death. |
| Ammo | `game.ammo` | ViZDoom `AMMO2` (bullets). |
| Kills | `game.kills` | Per round. |
| Round | `game.episode` | Starts at 1. Also in `spectator.episode` and `audit.episode`. Finished rounds are in `episodes[]` (last 12). |
| Per-neuron activity, controller cells | `readouts[]` | `{index, id, type, side, spikes, rate_hz}`. `spikes` is this game tic. `rate_hz` is a 100 ms exponential filter. |
| Per-neuron voltage | `neuron_voltage_mv` | Map of readout body id to mV. |
| Wider sample | `raster.neuron_ids` + `raster.bins[].counts` | 128 fixed display neurons, spike counts per publish window (`window_ms`). |
| Population activity | `populations[]` | `{name, neurons, spikes, mean_rate_hz}` per superclass. |
| Retina | `retina.*` | Every 8th receptor: `uv, luminance, filtered_luminance, drive_mv, spikes_last_step`. |

Controller readout ids in MaleCNS v1.0 (from `outputs/doom/bci-readouts.json`, a prior build's artifact): DNp20 R `10059`, DNp20 L `10162`, DNpe017 L `10527`, DNpe017 R `555871`.

Key on `id` plus `type` and `side`. Never key on `index`: that is a position into the node array `doom.prepare` generates, so it is build-specific. `id` is the MaleCNS bodyId and is stable.

## Three gaps for Session 2

1. **PPL101 is absent from the baseline server.** `baseline.md` runs `python -m doom.server --port 8766`, which is `--model baseline`. The two PPL101 cells (`11327`, `11900`) appear only with `--model experimental-v6`. Then they are appended to `manifest.readouts`, show in `readouts[]`, and `learning.DAN_spikes_last_tic` gives their spikes as a 2-element list in `brain.circuit["dan"]` order (not verified against ids yet). The bridge must emit `null` for them on the baseline.
2. **`spectator` is conditional.** It is present only when the game was started with `spectator=True` (the server does this) and the map has at most 256 objects, 32 sectors and 128 lines per sector. Otherwise position and heading are unavailable. Confirmed present on our live baseline run: one sector, floor 0, ceiling 192, four walls forming a 768 x 768 box from -384 to +384 on both axes, with 19 objects live. The bridge should still treat it as optional.
3. **No push.** "Subscribe to the server stream" means polling. The bridge should dedupe on `(run_id, sequence)` and reset on a new `run_id`.

## One message

Captured from our own baseline server on 127.0.0.1:8766 (run `f5b5b571`, sequence 264), trimmed: arrays shortened, `frame` truncated, only the four BCI readouts kept. Every value below is real. Full file: [`state-example.json`](state-example.json), 6 KB.

```json
{
  "schema": 1,
  "status": "running",
  "run_id": "f5b5b571-9fd9-4395-8226-927956bf9b2e",
  "sequence": 264,
  "generated_at_ms": 1789515456259,
  "condition": "intact",
  "decoder": "bci",
  "frame": "data:image/jpeg;base64,/9j/4AAQSkZJRgA...",
  "input_frame_sha256": "fd8ea17c322473a13e79ff045eb39e13e325248462099ccb81bbbda1eea716c8",
  "clocks": {"wall_seconds": 60.637, "neural_seconds": 21.4857, "game_seconds": 21.4857, "speed": 0.354, "brain_step_ms": 55.818},
  "game": {"episode": 1, "tick": 752, "finished": false, "health": 76, "kills": 2, "ammo": 48, "score": 0.0,
           "enemies": 8, "enemies_spawned": 10, "ammo_pickups": 0, "ammo_spawned": 4, "imps": 4, "zombies": 4},
  "episodes": [],
  "action": {"turn": -0.2742930156996461, "forward": 17.769179511714807, "attack": true},
  "readouts": [
    {"index": 48, "id": "10059", "type": "DNp20", "side": "R", "spikes": 1, "rate_hz": 29.447},
    {"index": 146, "id": "10162", "type": "DNp20", "side": "L", "spikes": 1, "rate_hz": 31.733},
    {"index": 489, "id": "10527", "type": "DNpe017", "side": "L", "spikes": 1, "rate_hz": 32.447},
    {"index": 142493, "id": "555871", "type": "DNpe017", "side": "R", "spikes": 0, "rate_hz": 11.976}
  ],
  "neuron_voltage_mv": {"10059": -52.0, "10162": -51.964, "10527": -52.0, "555871": -47.804},
  "reward": {"mode": "off", "sugar_pulses": 0, "active": false, "plasticity": false},
  "spectator": {
    "version": 1, "timing": "pre-action", "episode": 1, "tick": 751,
    "player": {"x": -334.19728088378906, "y": 154.0548095703125, "z": 0.0, "angle": 61.59484864715367, "pitch": 0.0},
    "objects": [
      {"id": 96, "name": "DoomImpBall", "x": -78.5323486328125, "y": -128.6601104736328, "z": 32.0, "angle": 137.17694649872763},
      {"id": 20, "name": "DoomFlyImp", "x": -29.1861572265625, "y": -173.9901123046875, "z": 0.0, "angle": 135.00000003143214}
    ],
    "sectors": [{"floor": 0.0, "ceiling": 192.0, "lines": [[-384.0, -384.0, -384.0, 384.0], [-384.0, 384.0, 384.0, 384.0],
                 [384.0, 384.0, 384.0, -384.0], [384.0, -384.0, -384.0, -384.0]]}]
  }
}
```

Two things Session 3 can take from this capture. The arena is one sector: a 768 x 768 box, floor 0, ceiling 192. `spectator.tick` trails `game.tick` by one, because the spectator geometry is pre-action and the game counters are post-action.

With `--model experimental-v6` the message also has `learning`, including `DAN_spikes_last_tic` (2 PPL101 cells), `MBON_spikes_last_tic`, `KC_spikes_last_tic`, `stimulus_active` and the efficacy histogram.
