# flyview

Viewer-side tools for the doomfly simulator. The bridge turns the simulator's ~470 KB `/state` into a ~370-byte message on a websocket. Two pages draw from that message: the fly in its arena, and a blueprint of 500 of its neurons.

```
doomfly server  --HTTP poll-->  bridge.py  --websocket-->  web/index.html      three.js arena + HUD
127.0.0.1:8766                  :8767                      web/blueprint.html  neuron graph that glows
```

Step-by-step terminal instructions are in the [root README](../README.md#run-it-yourself).

## The viewer

`web/index.html` is one file. three.js loads from jsDelivr, so the first load needs internet access.

- **Arena:** the real map, a 768 x 768 box with walls 192 units high, tiled in Doom's 64-unit flats.
- **Fly:** drawn at the streamed `pos` and `heading`, with a ring and pointer on the floor under it and a trail of its recent path.
- **HUD, top left:** title, round, health with a bar, kills, ammo, and connection status.
- **Controls:** drag to orbit, scroll to zoom, **F** to toggle a chase camera.
- **Cutaway walls:** a wall whose outside faces the camera fades, so the fly never hides behind the near wall.
- **Death:** when `round` goes up, the screen flashes red, a round banner shows, the fly snaps to its respawn point, and the trail resets.
- **Another bridge:** `index.html?ws=ws://host:port` points the page elsewhere. The default is `ws://localhost:8767`.

The fly renders 180 ms behind the stream and interpolates between messages, so motion is smooth at the bridge's ~7 messages per second. A jump over 64 units, a new round, or a restarted run snaps instead of gliding. Normal movement is at most 20 units per frame, and respawns jump 300 or more.

Status line meanings: **live** (data flowing), **no data for N s** (bridge up, simulator quiet), **simulator offline** (the bridge says so), **bridge offline, retrying** (reconnects with backoff up to 5 s).

### Coordinates

Doom `(x, y)` maps to three.js `(x / 32, 0, -y / 32)`. Heading is degrees counter-clockwise from +x, so 0 is east and 90 is north. That was measured, not assumed: over 1,709 moving frames the direction of travel matches the heading within 6.6° (median). `tests/test_conventions.py` keeps checking it against the fixture.

## Run the bridge

Standard library only. Any Python 3.11 works, including Windows Python while the simulator runs in WSL.

```sh
python flyview/bridge.py                                        # live, from 127.0.0.1:8766
python flyview/bridge.py --record flyview/replays/run.jsonl     # live, and keep a copy
python flyview/bridge.py --replay flyview/fixtures/replay-round-change.jsonl   # no simulator needed
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--source` | `http://127.0.0.1:8766/state` | doomfly `/state` URL |
| `--host`, `--port` | `127.0.0.1`, `8767` | websocket address |
| `--poll` | `0.125` | seconds between polls (the server publishes at most 8 per second) |
| `--replay FILE` | | serve a `.jsonl` instead of polling. Lines may be slim messages or raw `/state` |
| `--record FILE` | | append each slim message to a `.jsonl` |
| `--speed` | `1.0` | replay speed. Gaps longer than 2 s are shortened to 2 s |
| `--once` | | stop after one pass of the replay instead of looping |
| `--activity` | off | add per-neuron firing rates, for the blueprint. Replays of raw `/state` get them too |
| `-v` | | log connects and source changes to stderr |

## Message

One JSON text frame per new simulator frame. A client that connects mid-stream gets the latest message at once.

```json
{
  "v": 1,
  "status": "running",
  "run_id": "f5b5b571-9fd9-4395-8226-927956bf9b2e",
  "sequence": 25784,
  "t_ms": 1789566619417,
  "round": 30,
  "health": 46,
  "ammo": 16,
  "kills": 7,
  "pos": [-366.719, 6.98, 0.0],
  "heading": 84.133,
  "neurons": {
    "DNp20_L": {"rate_hz": 32.97, "spikes": 1},
    "DNp20_R": {"rate_hz": 37.161, "spikes": 2},
    "DNpe017": {"rate_hz": 52.987, "spikes": 2},
    "PPL101_11327": null,
    "PPL101_11900": null
  }
}
```

That is a real message from the live baseline.

| Field | Source in `/state` | Notes |
| --- | --- | --- |
| `round` | `game.episode` | Starts at 1 |
| `health`, `ammo`, `kills` | `game.*` | Post-action counters |
| `pos` | `spectator.player` x, y, z | Doom map units. `null` if the server sent no `spectator` |
| `heading` | `spectator.player.angle` | Degrees, engine convention |
| `neurons.DNp20_L`, `DNp20_R` | `readouts[]` by type and side | `rate_hz` is the decoder's 100 ms filtered rate. `spikes` is this game tic |
| `neurons.DNpe017` | both DNpe017 readouts, summed | Summed because that is what the decoder drives forward motion with |
| `neurons.PPL101_*` | `readouts[]` by body id | `null` on the baseline model. Present only with `--model experimental-v6` |

### With `--activity`

The message gains one field. The default message stays exactly as above.

```json
"activity": {
  "window_ms": 85.7,
  "observed": 142,
  "rates": {"48911": 35.0, "129403": 35.0, "151919": 58.3, "10059": 35.5, "10162": 30.25, "10527": 30.25, "555871": 17.39}
}
```

- `observed` counts the cells the simulator exposes: the 14 decoder readouts and its 128 raster display neurons.
- `rates` lists only cells firing now, in Hz, keyed by body id. Any observed cell that is missing is at 0 Hz.
- Readout rates are the decoder's filtered rates. Raster rates are this window's spike count over `window_ms`.

That is a real message from `fixtures/replay-activity.jsonl`.

The list is sparse because the network is mostly quiet. In 144 s of live baseline (967 messages) only 9 of the 142 cells fired at all. Seven fired in every message: the four controller cells, and L1, L3 and Dm12 in the optic lobe. L1 and L3 get the model's declared 12 mV tonic lamina drive. Two more fired briefly: a second L3 twice and a Tm1 once. The other 133 stayed silent.

When the simulator is unreachable or not running, the bridge sends one message with `"status": "offline"`, every other field `null`, and an `error` string. It sends it once per change, not on every retry.

## The blueprint

`web/blueprint.html` draws 500 neurons from the male fly connectome as a force-directed graph, and makes a cell glow when its firing rate rises. It needs `blueprint-graph.json` beside it, so serve the folder (`python -m http.server 8780` in `flyview/web`). Opened as a file, it asks you to pick the JSON.

- **The five controllers** are the bridge's five keys, each in its own color: DNp20 left, DNp20 right, DNpe017 (both cells), PPL101 11327 and PPL101 11900.
- **Glow means a rise,** not a high rate. Each cell keeps a fast (0.4 s) and a slow (6 s) average of its rate. It glows by how far the fast one climbs above the slow one. A steady 30 Hz cell stays dark. A silent cell that suddenly fires lights up fully.
- **Four cell states:** live readout (white ring), live raster sample (blue), no live data (dim), and not streaming on this model (dashed ring). PPL101 stays dashed on the baseline model.
- **Edges:** blue excitatory, red inhibitory, thicker for more synapses. The slider hides weak edges. Hover a cell to see its type, transmitter, connections and live rate, with its edges highlighted.
- **Controls:** drag the background to pan, scroll to zoom, drag a cell to move it.
- **Without `--activity`,** only the controllers can glow, and the page says so.

### Which 500 neurons

`tools/doomfly/export_blueprint.py` builds the graph from `doomfly/outputs/doom/malecns_v1/graph.npz`, in three steps:

1. **Every cell the simulator can stream, 144 in all:** the 6 controller cells, the other 10 decoder readouts, and the 128 raster display neurons. The raster ids are cross-checked against a live `/state`, and match exactly.
2. **The circuit around each controller:** the top 40 synaptic partners of each of the 5 controller groups, by contact count.
3. **Wiring context:** the cells with the most contacts to the streamed set, up to 500.

Edges: 9,724 run between these 500 cells. The export keeps 6,000: every cell's strongest edge, all controller edges, then the strongest of the rest. Self edges are dropped. 460 cells form one connected component. 36 raster cells have no partner among the 500 and float at the edge. They are genuinely unconnected, not cut by the edge cap. Only 142 cells can ever glow (144 on the experimental-v6 model), because the simulator exposes activity for no others.

## Three things a viewer should know

- **Death has no health-zero frame.** The server resets the round between publishes, so health jumps straight from its last value to 100. Watch `round` increase instead.
- **Not every frame arrives.** `/state` only holds the latest message, so the poller occasionally skips one (about 95% delivery in testing). Nothing arrives stale or twice.
- **The arena** is one 768 x 768 box, x and y from -384 to +384, floor 0, ceiling 192.

## Files

| Path | What |
| --- | --- |
| `bridge.py` | The bridge |
| `web/index.html` | The arena viewer |
| `web/blueprint.html` | The neuron blueprint |
| `web/blueprint-graph.json` | 500 neurons and 6,000 edges, exported from the prepared graph |
| `preflight.sh` | Host checks before bringing doomfly up. Installs nothing |
| `docs/telemetry.md` | Session 1: the full `/state` format |
| `docs/state-example.json` | One real `/state`, trimmed |
| `fixtures/replay-round-change.jsonl` | 50 s of live baseline around a death, 314 messages |
| `fixtures/replay-activity.jsonl` | 30 s of live baseline with `--activity`, including a rare L3 spike and a death |
| `replays/` | Your recordings. Not tracked |
| `tests/` | `python -m pytest flyview/tests` |
