# Repo layout

```
8710/
  README.md                    what is here and how to bring doomfly up
  claude.md                    project instructions, loaded by Claude Code at this root
  .gitignore                   ignores .env, venvs, doomfly/, logs
  plans/
    baseline.md                doomfly bring-up steps (upstream README)
    session.md                 the four flyview session prompts
    repo.md                    this file
  tools/doomfly/               our sudo-free bring-up, tracked here, operates on the clone
    setup_env.sh               uv + Python 3.11 + the pinned requirements
    download_malecns.py        the README download block, checksum verified
    build_graph.sh             connectome, prepare, audit_data, build_kernel
    run_server.sh              the baseline server on 127.0.0.1:8766
    stop_server.sh             stops the simulator cleanly (SIGTERM, then waits)
    export_blueprint.py        exports the 500-neuron graph (run_export.sh runs it in WSL)
    capture_state.py           saves one live /state
    trim_state.py              trims a /state into the docs example
    check_readouts.py          compares a fresh build's readouts to the prior artifact
    bin/clang++                shim to g++, because build_kernel calls clang++
    logs/                      untracked
  doomfly/                     upstream clone, own git history, untracked here
    connectome_data/           1.1 GB MaleCNS v1.0, checksum verified, untracked
    .venv-neural/              Python 3.11 via uv, untracked
  flyview/                     our work against doomfly
    README.md                  bridge usage and the slim message format
    preflight.sh               checks python/compiler/RAM/disk/vizdoom, installs nothing
    bridge.py                  Session 2: polls :8766, republishes on ws://127.0.0.1:8767, --replay, --record
    docs/telemetry.md          Session 1: the port 8766 wire format
    docs/state-example.json    one real /state message, trimmed
    fixtures/                  replay-round-change.jsonl (a death), replay-activity.jsonl (with --activity)
    replays/                   local recordings, untracked
    tests/                     python -m pytest flyview/tests
    web/index.html             Session 3: three.js arena, fly avatar, HUD, ws://localhost:8767
    web/blueprint.html         Session 4: force-directed graph of 500 neurons, glows on rising rates
    web/blueprint-graph.json   the exported 500 neurons and 6,000 edges
```

## Rules

- doomfly stays an unmodified upstream checkout. Everything we add lives in `tools/doomfly/` or `flyview/`, both tracked.
- Nothing large or secret is tracked: `.env`, `connectome_data/`, venvs, `outputs/`, logs.
- Run `flyview/preflight.sh` before a bring-up. It tells you which of the five host requirements is missing without changing the machine.
