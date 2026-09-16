import json
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "doomfly"
manifest = json.loads((root / "outputs/doom/malecns_v1/manifest.json").read_text())
prior = json.loads((root / "outputs/doom/bci-readouts.json").read_text())
fresh = [r for r in manifest["readouts"] if r["type"] in ("DNp20", "DNpe017")]

key = lambda r: (r["id"], r["type"], r["side"])
print("fresh:", json.dumps(sorted(fresh, key=key)))
print("prior:", json.dumps(sorted(prior, key=key)))
print("ids match:", sorted(map(key, fresh)) == sorted(map(key, prior)))
print("index match:", sorted(r["index"] for r in fresh) == sorted(r["index"] for r in prior))
print("total readouts:", len(manifest["readouts"]))
print("types:", sorted({r["type"] for r in manifest["readouts"]}))
