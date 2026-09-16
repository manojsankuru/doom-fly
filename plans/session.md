Session 1, read before writing.

Read README.md, AGENTS.md, doom/README.md, and docs/doom-live-training.md. Tell me the exact shape of the telemetry the server broadcasts on port 8766. Which fields carry fly position, heading, health, ammo, round number, and per-neuron activity? Do not write code. Output a JSON example of one telemetry message.

Session 2, the bridge.

Using the telemetry shape from the previous session, write flyview/bridge.py. Python 3.11, type hints. Subscribe to the server stream. Republish a slim message on a local websocket at port 8767 with only: pos, heading, health, ammo, kills, round, and the activity of DNp20 left, DNp20 right, DNpe017, and the two PPL101 cells. Add a --replay file.jsonl flag so the viewer runs without the simulator.

That replay flag matters. It lets you build the UI before the connectome finishes downloading.

Session 3, the avatar.

Write flyview/web/index.html. One file, three.js from a CDN. A tiled arena room with walls. A fly model at the streamed position and heading. A HUD in the top left: title, round, health, kills, ammo. Connect to ws://localhost:8767. Run against the replay file first.

Session 4, the blueprint.

Write flyview/web/blueprint.html. Load a static JSON of 500 neuron IDs and their connections, exported once from the prepared graph. Draw a force-directed graph. Brighten a node when its firing rate rises in the live stream. Color the five controller neurons differently.