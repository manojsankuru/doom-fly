# 8710

A fly connectome plays Doom, and we watch it. Two pieces: the upstream simulator, and our viewers built on top.

## What this is

Scientists mapped every neuron and connection in one male fruit fly: 166,700 neurons and 25,582,938 connections. [doomfly](https://github.com/nftechie/doomfly) runs a simplified model of that wiring and plugs it into a Doom arena.

- **Eyes:** each game frame sets the brightness input of 3,335 light-sensing cells.
- **Brain:** activity spreads through the real wiring. Nobody wrote a game strategy.
- **Hands:** four neurons are read out as controls. DNp20 right minus left turns the fly. DNpe017 moves it forward and fires.
- **The game keeps score:** enemies attack, health falls, and death starts a new round.

The fly does not play well. In the baseline model its wiring is fixed and nothing learns. DNpe017 fires almost constantly, so the fly holds forward and fire, turns little, and runs into walls. Walls do not hurt it. Four imps throwing fireballs and four zombies with guns do. Our arena view draws only the fly, not the enemies. Upstream describes the project as an experiment, "not demonstrated learned survival".

This repo makes the experiment watchable:

- `flyview/bridge.py` reads the simulator and streams a small message.
- `flyview/web/index.html` shows the fly moving in its arena, with round, health, kills and ammo.
- `flyview/web/blueprint.html` shows 500 of the neurons and their connections, lighting up when their firing rate rises.

Neuron data: MaleCNS v1.0, by the MaleCNS collaboration including FlyEM at HHMI Janelia, the University of Cambridge Department of Zoology, the MRC Laboratory of Molecular Biology and Google Research. Released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) at https://male-cns.janelia.org/download/. `flyview/web/blueprint-graph.json` is derived from it: 500 selected neurons, with synapse counts summarized per connection.

| Path | What it is |
| --- | --- |
| `doomfly/` | Upstream clone of [nftechie/doomfly](https://github.com/nftechie/doomfly). A fly connectome drives ViZDoom. It has its own git history and is not tracked here. |
| `flyview/` | Our work: a telemetry bridge, a 3D arena viewer and a neuron blueprint. |
| `tools/doomfly/` | Scripts that set up, build, run, stop and export from doomfly. |
| `plans/` | The baseline steps, the four session prompts and the repo layout. |

## Run it yourself

Everything below runs in **Windows PowerShell**. Use one terminal per step. Stop anything with **Ctrl+C** in its terminal.

### Terminal 1: the simulator

```powershell
wsl bash /mnt/c/Projects/8710/tools/doomfly/run_server.sh
```

It prints `{"status": "running", ...}` once the neural loop starts. Check it from any terminal:

```powershell
curl.exe http://127.0.0.1:8766/health
```

Right after `running` it also prints a traceback ending in `ObserverUnavailable: Native observer is not installed`. That is harmless. doomfly's optional native spectator is not built here, the server logs "primary continues", and the simulation runs normally. None of our pages use it.

Opening `http://127.0.0.1:8766/` in a browser shows a blank page. That is expected. The simulator only serves JSON at `/state`, `/index` and `/health`.

### Terminal 2: the bridge

```powershell
cd C:\Projects\8710
py -3.11 flyview\bridge.py --activity
```

`--activity` adds per-neuron rates for the blueprint. The arena viewer works with or without it.

**No simulator?** Skip terminal 1 and replay a recording instead:

```powershell
py -3.11 flyview\bridge.py --replay flyview\fixtures\replay-activity.jsonl
```

### Terminal 3: the web pages

```powershell
cd C:\Projects\8710\flyview\web
py -3.11 -m http.server 8780 --bind 127.0.0.1
```

Then open in a browser:

| Session | Page |
| --- | --- |
| 3, the arena | http://127.0.0.1:8780/index.html |
| 4, the blueprint | http://127.0.0.1:8780/blueprint.html |

The arena also opens by double-clicking `index.html`, no server needed. The blueprint needs terminal 3: browsers block a file-opened page from reading its graph JSON. If you open it as a file anyway, it asks you to pick `blueprint-graph.json`.

### Session 1: the telemetry spec

Nothing to run. Read `flyview\docs\telemetry.md`. To see a live message while terminal 1 runs:

```powershell
curl.exe http://127.0.0.1:8766/health
curl.exe -o state.json http://127.0.0.1:8766/state
```

### Checks

```powershell
cd C:\Projects\8710
py -3.11 -m pytest flyview\tests -q
wsl bash /mnt/c/Projects/8710/flyview/preflight.sh
```

### Stop everything

Ctrl+C in each terminal. If the simulator was started some other way and keeps running:

```powershell
wsl bash /mnt/c/Projects/8710/tools/doomfly/stop_server.sh
```

## Rebuilding doomfly from scratch

Already done on this machine. On a fresh clone of this repo, doomfly is not included. Clone it beside the other folders first, at the commit this work was built against:

```powershell
git clone https://github.com/nftechie/doomfly
git -C doomfly checkout 71ecf53
```

The kernel builds on POSIX only (`clang++`, `libneural.so`), so doomfly runs under WSL. The paths below assume the repo lives at `C:\Projects\8710`.

```powershell
wsl bash /mnt/c/Projects/8710/tools/doomfly/setup_env.sh      # uv + Python 3.11 + pinned deps
py -3.11 tools\doomfly\download_malecns.py                     # 1.1 GB, checksum verified
wsl bash /mnt/c/Projects/8710/tools/doomfly/build_graph.sh    # connectome, prepare, audit, kernel (~5 min)
wsl bash /mnt/c/Projects/8710/tools/doomfly/run_export.sh     # re-export the 500-neuron blueprint graph
```

Two deviations from `plans/baseline.md`, both because this machine has no sudo in WSL:

- Python 3.11 comes from `uv`, not `apt`.
- `tools/doomfly/bin/clang++` is a shim that calls the installed `g++`. The build flags are compatible.

`doomfly/connectome_data/` (1.1 GB), `.venv-neural/` and `outputs/` stay out of git.

## The sessions

- **Session 1** `flyview/docs/telemetry.md`: what port 8766 actually serves. It is polled HTTP, not a stream.
- **Session 2** `flyview/bridge.py`: republishes a ~370-byte message on `ws://127.0.0.1:8767`. Standard library only.
- **Session 3** `flyview/web/index.html`: the fly in its arena, with a HUD.
- **Session 4** `flyview/web/blueprint.html`: 500 connectome neurons as a force-directed graph that glows with live activity.

Details in `flyview/README.md`.
