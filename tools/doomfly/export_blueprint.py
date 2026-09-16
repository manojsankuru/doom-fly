import argparse
import json
import time
from pathlib import Path

import numpy as np
import pyarrow.feather as feather

ROOT = Path(__file__).resolve().parents[2]
DOOMFLY = ROOT / "doomfly"
TARGET_NODES = 500
CONTROLLER_QUOTA = 40
EDGE_CAP = 6000
CONTACT_GAIN = 0.275
CONTROLLERS = {
    "10162": "DNp20_L",
    "10059": "DNp20_R",
    "10527": "DNpe017",
    "555871": "DNpe017",
    "11327": "PPL101_11327",
    "11900": "PPL101_11900",
}
V6_ONLY = {"11327", "11900"}
RASTER_SUPERCLASSES = ["ol_intrinsic", "visual_projection", "cb_intrinsic", "descending_neuron"]


def text(value: object) -> str:
    return "" if value is None or (isinstance(value, float) and np.isnan(value)) else str(value)


def raster_display(superclass: np.ndarray) -> list[int]:
    display: list[int] = []
    for name in RASTER_SUPERCLASSES:
        indices = np.flatnonzero(superclass == name)
        display.extend(indices[np.linspace(0, len(indices) - 1, min(32, len(indices)), dtype=int)].tolist())
    return display


def partner_contacts(pre: np.ndarray, post: np.ndarray, contacts: np.ndarray, weights: np.ndarray, n: int) -> np.ndarray:
    outgoing = weights[pre] > 0
    incoming = weights[post] > 0
    score = np.bincount(post[outgoing], weights=contacts[outgoing] * weights[pre[outgoing]], minlength=n)
    score += np.bincount(pre[incoming], weights=contacts[incoming] * weights[post[incoming]], minlength=n)
    return score


def components(count: int, edges: np.ndarray) -> tuple[int, int]:
    parent = list(range(count))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for source, target in edges:
        a, b = find(int(source)), find(int(target))
        if a != b:
            parent[a] = b
    sizes: dict[int, int] = {}
    for item in range(count):
        root = find(item)
        sizes[root] = sizes.get(root, 0) + 1
    degree = np.zeros(count, dtype=int)
    for source, target in edges:
        degree[int(source)] += 1
        degree[int(target)] += 1
    return max(sizes.values()), int(np.sum(degree == 0))


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a 500-neuron blueprint graph from the prepared MaleCNS graph.")
    parser.add_argument("--out", type=Path, default=ROOT / "flyview/web/blueprint-graph.json")
    parser.add_argument("--check-state", type=Path, help="a captured /state to cross-check the raster ids against")
    args = parser.parse_args()

    started = time.time()
    graph = np.load(DOOMFLY / "outputs/doom/malecns_v1/graph.npz")
    ptr, post, weight, body_ids = graph["ptr"], graph["post"], graph["weight"], graph["ids"]
    superclass = graph["superclass"]
    n = len(body_ids)
    ids = np.array([str(x) for x in body_ids])
    index_of = {body: i for i, body in enumerate(ids)}
    nodes = feather.read_table(DOOMFLY / "connectome_data/malecns_v1/normalized/neurons.feather").to_pandas()
    annotations = feather.read_table(DOOMFLY / "connectome_data/malecns_v1/annotations.feather").to_pandas().set_index("bodyId")
    sides = annotations.reindex(body_ids)["somaSide"].fillna("").astype(str).to_numpy()
    manifest = json.loads((DOOMFLY / "outputs/doom/malecns_v1/manifest.json").read_text())

    pre = np.repeat(np.arange(n, dtype=np.int32), np.diff(ptr))
    contacts = np.rint(np.abs(weight) / CONTACT_GAIN).astype(np.int32)
    sign = np.sign(weight).astype(np.int8)

    controller_index = [index_of[body] for body in CONTROLLERS]
    readout_index = [int(r["index"]) for r in manifest["readouts"]]
    raster_index = raster_display(superclass)
    if args.check_state:
        captured = json.loads(args.check_state.read_text())["raster"]["neuron_ids"]
        assert captured == [ids[i] for i in raster_index], "raster ids differ from the live server"
        print("raster ids match the captured /state exactly")

    chosen: list[int] = []
    group: dict[int, str] = {}
    for index in controller_index:
        chosen.append(index)
        group[index] = "controller"
    for index in readout_index:
        if index not in group:
            chosen.append(index)
            group[index] = "readout"
    for index in raster_index:
        if index not in group:
            chosen.append(index)
            group[index] = "raster"
    observable = len(chosen)

    taken = np.zeros(n, dtype=bool)
    taken[chosen] = True
    for key in dict.fromkeys(CONTROLLERS.values()):
        members = [index_of[body] for body, name in CONTROLLERS.items() if name == key]
        factor = np.zeros(n, dtype=np.float64)
        factor[members] = 1.0
        score = partner_contacts(pre, post, contacts, factor, n)
        score[taken] = 0
        for index in np.argsort(-score)[:CONTROLLER_QUOTA]:
            if score[index] > 0:
                chosen.append(int(index))
                group[int(index)] = "context"
                taken[index] = True

    factor = np.zeros(n, dtype=np.float64)
    factor[[i for i in chosen if group[i] != "context"]] = 1.0
    score = partner_contacts(pre, post, contacts, factor, n)
    score[taken] = 0
    for index in np.argsort(-score)[: TARGET_NODES - len(chosen)]:
        chosen.append(int(index))
        group[int(index)] = "context"
        taken[index] = True
    assert len(chosen) == TARGET_NODES == len(set(chosen))

    local = np.full(n, -1, dtype=np.int32)
    local[chosen] = np.arange(len(chosen), dtype=np.int32)
    inside = (local[pre] >= 0) & (local[post] >= 0) & (pre != post)
    edge_source, edge_target = local[pre[inside]], local[post[inside]]
    edge_contacts, edge_sign = contacts[inside], sign[inside]
    all_edges = len(edge_source)
    is_controller = np.array([group[i] == "controller" for i in chosen])
    keep_first = is_controller[edge_source] | is_controller[edge_target]
    covered = np.zeros(TARGET_NODES, dtype=bool)
    for edge in np.argsort(-edge_contacts, kind="stable"):
        source, target = edge_source[edge], edge_target[edge]
        if not covered[source] or not covered[target]:
            keep_first[edge] = True
            covered[source] = covered[target] = True
    order = np.lexsort((-edge_contacts, ~keep_first))[:EDGE_CAP]
    order = order[np.lexsort((edge_target[order], edge_source[order]))]

    kept = np.stack([edge_source[order], edge_target[order]], axis=1)
    largest, isolated = components(TARGET_NODES, kept)
    live_counts = {"readout": 0, "raster": 0, "v6": 0, "none": 0}
    node_rows = []
    for index in chosen:
        body = ids[index]
        kind = group[index]
        if body in V6_ONLY:
            live = "v6"
        elif kind in ("controller", "readout"):
            live = "readout"
        elif kind == "raster":
            live = "raster"
        else:
            live = "none"
        live_counts[live] += 1
        row = {
            "id": body,
            "type": text(nodes.cell_type.iloc[index]),
            "superclass": str(superclass[index]),
            "side": sides[index],
            "nt": text(nodes.neurotransmitter.iloc[index]),
            "group": kind,
            "live": live,
        }
        if body in CONTROLLERS:
            row["controller"] = CONTROLLERS[body]
        node_rows.append(row)

    payload = {
        "schema": 1,
        "dataset": manifest["dataset"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "doomfly/outputs/doom/malecns_v1/graph.npz",
        "selection": (
            f"{observable} observable cells (6 controllers, {len(readout_index)} readouts, 128 raster display neurons), "
            f"then the top {CONTROLLER_QUOTA} synaptic partners of each of the 5 controller groups by contacts, "
            f"then the cells with the most contacts to the observable set, up to {TARGET_NODES}"
        ),
        "edges_note": (
            f"{len(order)} strongest of {all_edges} directed edges among these neurons, controller edges first, "
            "self edges dropped. contacts are synapse counts; sign is +1 excitatory or uncertain, -1 inhibitory"
        ),
        "stats": {
            "nodes": TARGET_NODES,
            "edges": int(len(order)),
            "edges_available": int(all_edges),
            "largest_component": largest,
            "isolated_nodes": isolated,
            "live": live_counts,
        },
        "nodes": node_rows,
        "edges": [[int(s), int(t), int(c), int(g)] for s, t, c, g in zip(edge_source[order], edge_target[order], edge_contacts[order], edge_sign[order])],
    }
    args.out.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(payload["stats"]))
    print("groups:", {k: sum(1 for r in node_rows if r["group"] == k) for k in ("controller", "readout", "raster", "context")})
    print("controllers:", [(r["id"], r["controller"], r["type"], r["side"]) for r in node_rows if "controller" in r])
    print("wrote", args.out, args.out.stat().st_size, "bytes in", round(time.time() - started, 1), "s")


if __name__ == "__main__":
    main()
