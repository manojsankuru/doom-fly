import json
import sys
import urllib.request
from pathlib import Path

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766/state"
out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("state-capture.json")
with urllib.request.urlopen(url, timeout=20) as response:
    state = json.loads(response.read())
out.write_text(json.dumps(state, indent=2) + "\n")

print("status:", state.get("status"), "sequence:", state.get("sequence"))
print("top-level keys:", sorted(state))
print("has spectator:", "spectator" in state)
if "spectator" in state:
    spectator = state["spectator"]
    print("spectator keys:", sorted(spectator))
    print("player:", json.dumps(spectator["player"]))
    print("objects:", len(spectator["objects"]), "first:", json.dumps(spectator["objects"][:2]))
    print("sectors:", len(spectator["sectors"]), "lines in first:", len(spectator["sectors"][0]["lines"]))
print("game:", json.dumps(state.get("game")))
print("action:", json.dumps(state.get("action")))
print("readouts:", json.dumps(state.get("readouts")))
print("clocks:", json.dumps(state.get("clocks")))
print("has learning:", "learning" in state)
print("bytes:", out.stat().st_size)
