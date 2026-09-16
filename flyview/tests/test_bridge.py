import asyncio
import base64
import json
import os
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import bridge

EXAMPLE = Path(__file__).resolve().parents[1] / "docs" / "state-example.json"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "replay-round-change.jsonl"


def example_state() -> dict[str, Any]:
    state: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return state


def masked_frame(payload: bytes, opcode: int = bridge.OPCODE_TEXT) -> bytes:
    mask = os.urandom(4)
    size = len(payload)
    header = bytearray([0x80 | opcode])
    if size < 126:
        header.append(0x80 | size)
    else:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", size))
    return bytes(header) + mask + bridge.unmask(payload, mask)


async def connect(port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    key = base64.b64encode(os.urandom(16)).decode()
    writer.write(
        (
            "GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    await writer.drain()
    response = (await reader.readuntil(b"\r\n\r\n")).decode()
    assert response.startswith("HTTP/1.1 101")
    assert f"Sec-WebSocket-Accept: {bridge.accept_key(key)}" in response
    return reader, writer


async def receive(reader: asyncio.StreamReader, timeout: float = 5.0) -> dict[str, Any]:
    opcode, payload = await asyncio.wait_for(bridge.read_frame(reader), timeout)
    assert opcode == bridge.OPCODE_TEXT
    message: dict[str, Any] = json.loads(payload)
    return message


async def hang_up(writer: asyncio.StreamWriter) -> None:
    writer.write(masked_frame(b"", bridge.OPCODE_CLOSE))
    await writer.drain()
    writer.close()


def test_accept_key_matches_rfc_6455_example() -> None:
    assert bridge.accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


@pytest.mark.parametrize(
    ("size", "header"),
    [(5, bytes([0x81, 5])), (200, bytes([0x81, 126]) + struct.pack("!H", 200)), (70000, bytes([0x81, 127]) + struct.pack("!Q", 70000))],
)
def test_encode_frame_uses_the_right_length_field(size: int, header: bytes) -> None:
    frame = bridge.encode_frame(b"x" * size)
    assert frame.startswith(header)
    assert len(frame) == len(header) + size


def test_read_frame_unmasks_client_payload() -> None:
    async def scenario() -> tuple[int, bytes]:
        reader = asyncio.StreamReader()
        reader.feed_data(masked_frame(b"hello fly" * 20))
        return await bridge.read_frame(reader)

    assert asyncio.run(scenario()) == (bridge.OPCODE_TEXT, b"hello fly" * 20)


def test_handshake_rejects_plain_http() -> None:
    assert bridge.handshake_response(b"GET /state HTTP/1.1\r\nHost: x\r\n\r\n") is None


def test_slim_from_real_capture() -> None:
    message = bridge.slim(example_state())
    assert message == {
        "v": 1,
        "status": "running",
        "run_id": "f5b5b571-9fd9-4395-8226-927956bf9b2e",
        "sequence": 264,
        "t_ms": 1789515456259,
        "round": 1,
        "health": 76,
        "ammo": 48,
        "kills": 2,
        "pos": [-334.197, 154.055, 0.0],
        "heading": 61.595,
        "neurons": {
            "DNp20_L": {"rate_hz": 31.733, "spikes": 1},
            "DNp20_R": {"rate_hz": 29.447, "spikes": 1},
            "DNpe017": {"rate_hz": 44.423, "spikes": 1},
            "PPL101_11327": None,
            "PPL101_11900": None,
        },
    }


def test_activity_is_opt_in_and_sparse() -> None:
    state = example_state()
    assert "activity" not in bridge.slim(state)
    assert bridge.slim(state, activity=True)["activity"] == {
        "window_ms": 57.1,
        "observed": 8,
        "rates": {"10059": 29.45, "10162": 31.73, "10527": 32.45, "555871": 11.98},
    }


def test_activity_converts_raster_counts_to_rates() -> None:
    state = example_state()
    state["raster"] = {
        "neuron_ids": ["10009", "24062", "31565"],
        "bins": [{"window_ms": 90.0, "counts": [9, 0, 9]}, {"window_ms": 57.1, "counts": [3, 0, 1]}],
    }
    state["readouts"] = [{**state["readouts"][0], "rate_hz": 0.0}]
    activity = bridge.slim(state, activity=True)["activity"]
    assert activity == {"window_ms": 57.1, "observed": 4, "rates": {"10009": 52.5, "31565": 17.5}}


def test_activity_without_raster_still_reports_readouts() -> None:
    state = example_state()
    del state["raster"]
    activity = bridge.slim(state, activity=True)["activity"]
    assert activity["window_ms"] == 0.0
    assert activity["observed"] == 4
    assert set(activity["rates"]) == {"10059", "10162", "10527", "555871"}


def test_replay_of_raw_states_can_add_activity(tmp_path: Path) -> None:
    path = tmp_path / "raw.jsonl"
    path.write_text(json.dumps(example_state()) + "\n", encoding="utf-8")
    assert "activity" not in bridge.load_replay(path)[0]
    assert bridge.load_replay(path, activity=True)[0]["activity"]["observed"] == 8


def test_slim_without_spectator_has_no_position() -> None:
    state = example_state()
    del state["spectator"]
    message = bridge.slim(state)
    assert message["pos"] is None
    assert message["heading"] is None
    assert message["health"] == 76


def test_slim_reads_ppl101_when_the_v6_model_appends_them() -> None:
    state = example_state()
    state["readouts"] = state["readouts"] + [
        {"index": 9, "id": "11900", "type": "PPL101", "side": "R", "spikes": 2, "rate_hz": 14.5},
        {"index": 8, "id": "11327", "type": "PPL101", "side": "L", "spikes": 0, "rate_hz": 9.25},
    ]
    neurons = bridge.slim(state)["neurons"]
    assert list(neurons) == list(bridge.NEURON_KEYS)
    assert neurons["PPL101_11327"] == {"rate_hz": 9.25, "spikes": 0}
    assert neurons["PPL101_11900"] == {"rate_hz": 14.5, "spikes": 2}


def test_offline_message_has_the_slim_keys() -> None:
    message = bridge.offline("unreachable: URLError")
    assert set(message) == set(bridge.slim(example_state())) | {"error"}
    assert message["status"] == "offline"
    assert list(message["neurons"]) == list(bridge.NEURON_KEYS)


def test_load_replay_accepts_raw_and_slim_lines(tmp_path: Path) -> None:
    raw = example_state()
    slim = bridge.slim(raw)
    path = tmp_path / "mixed.jsonl"
    path.write_text(json.dumps(raw) + "\n\n" + json.dumps(slim) + "\n", encoding="utf-8")
    assert bridge.load_replay(path) == [slim, slim]


def test_recorded_fixture_is_a_clean_continuous_round_change() -> None:
    messages = bridge.load_replay(FIXTURE)
    sequences = [m["sequence"] for m in messages]
    steps = [b - a for a, b in zip(sequences, sequences[1:])]
    rounds = [m["round"] for m in messages]
    change = next(i for i in range(1, len(rounds)) if rounds[i] != rounds[i - 1])
    assert len({m["run_id"] for m in messages}) == 1
    assert all(m["status"] == "running" and m["pos"] is not None for m in messages)
    assert set(messages[0]) == set(bridge.slim(example_state()))
    assert 1 <= min(steps) and max(steps) <= 3
    assert rounds[change] == rounds[change - 1] + 1
    assert messages[change]["health"] == 100
    assert messages[change - 1]["health"] < 100


def test_load_replay_rejects_garbage(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="bad.jsonl:1"):
        bridge.load_replay(path)


def test_replay_streams_every_message_in_order(tmp_path: Path) -> None:
    base = bridge.slim(example_state())
    messages = [{**base, "sequence": n, "t_ms": base["t_ms"] + 20 * n, "health": 76 - n} for n in range(3)]
    path = tmp_path / "replay.jsonl"
    path.write_text("".join(json.dumps(m) + "\n" for m in messages), encoding="utf-8")

    async def scenario() -> list[dict[str, Any]]:
        server = bridge.WebSocketServer("127.0.0.1", 0)
        await server.start()
        reader, writer = await connect(server.port_in_use)
        pump = asyncio.create_task(bridge.pump_replay(server, path, speed=1.0, once=True))
        received = [await receive(reader) for _ in messages]
        await pump
        await hang_up(writer)
        await server.close()
        return received

    assert asyncio.run(scenario()) == messages


class StateHandler(BaseHTTPRequestHandler):
    states: list[dict[str, Any]] = []
    hits = 0

    def do_GET(self) -> None:
        cls = type(self)
        state = cls.states[min(cls.hits, len(cls.states) - 1)]
        cls.hits += 1
        body = json.dumps(state).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


def serve_states(states: list[dict[str, Any]]) -> ThreadingHTTPServer:
    StateHandler.states = states
    StateHandler.hits = 0
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), StateHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def test_live_polling_drops_repeated_sequences_and_records(tmp_path: Path) -> None:
    first = example_state()
    second = {**example_state(), "sequence": 265, "game": {**first["game"], "health": 70}}
    httpd = serve_states([first, first, first, second])
    source = f"http://127.0.0.1:{httpd.server_address[1]}/state"
    record = tmp_path / "live.jsonl"

    async def scenario() -> list[dict[str, Any]]:
        server = bridge.WebSocketServer("127.0.0.1", 0)
        await server.start()
        reader, writer = await connect(server.port_in_use)
        pump = asyncio.create_task(bridge.pump_live(server, source, poll=0.01, record=record))
        received = [await receive(reader), await receive(reader)]
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        await hang_up(writer)
        await server.close()
        return received

    try:
        received = asyncio.run(scenario())
    finally:
        httpd.shutdown()
    assert [m["sequence"] for m in received] == [264, 265]
    assert [m["health"] for m in received] == [76, 70]
    assert StateHandler.hits >= 4
    assert bridge.load_replay(record) == received


def test_late_joiner_gets_the_latest_message_at_once() -> None:
    async def scenario() -> dict[str, Any]:
        server = bridge.WebSocketServer("127.0.0.1", 0)
        await server.start()
        server.broadcast(bridge.slim(example_state()))
        reader, writer = await connect(server.port_in_use)
        message = await receive(reader, timeout=2.0)
        await hang_up(writer)
        await server.close()
        return message

    assert asyncio.run(scenario())["sequence"] == 264


def test_unreachable_source_announces_offline_once() -> None:
    async def scenario() -> tuple[dict[str, Any], bool]:
        server = bridge.WebSocketServer("127.0.0.1", 0)
        await server.start()
        reader, writer = await connect(server.port_in_use)
        pump = asyncio.create_task(bridge.pump_live(server, "http://127.0.0.1:9/state", poll=0.01, record=None))
        message = await receive(reader)
        try:
            await receive(reader, timeout=2.5)
            repeated = True
        except asyncio.TimeoutError:
            repeated = False
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        await hang_up(writer)
        await server.close()
        return message, repeated

    message, repeated = asyncio.run(scenario())
    assert message["status"] == "offline"
    assert message["error"].startswith("unreachable")
    assert repeated is False


def test_connection_resets_are_silenced_but_other_errors_are_not() -> None:
    reported: list[dict[str, Any]] = []

    class Loop:
        def default_exception_handler(self, context: dict[str, Any]) -> None:
            reported.append(context)

    loop: Any = Loop()
    bridge.ignore_connection_resets(loop, {"message": "reset", "exception": ConnectionResetError(10054, "reset")})
    bridge.ignore_connection_resets(loop, {"message": "aborted", "exception": ConnectionAbortedError()})
    bridge.ignore_connection_resets(loop, {"message": "real bug", "exception": KeyError("x")})
    assert [c["message"] for c in reported] == ["real bug"]


def test_abrupt_disconnect_leaves_the_server_serving() -> None:
    async def scenario() -> tuple[int, int, int]:
        server = bridge.WebSocketServer("127.0.0.1", 0)
        await server.start()
        _, rude = await connect(server.port_in_use)
        await asyncio.sleep(0.1)
        rude.transport.abort()
        await asyncio.sleep(0.3)
        after_abort = len(server.clients)
        server.broadcast(bridge.slim(example_state()))
        reader, writer = await connect(server.port_in_use)
        message = await receive(reader)
        while_connected = len(server.clients)
        await hang_up(writer)
        await server.close()
        return after_abort, int(message["sequence"]), while_connected

    after_abort, sequence, while_connected = asyncio.run(scenario())
    assert after_abort == 0
    assert sequence == 264
    assert while_connected == 1


def test_ping_gets_a_pong() -> None:
    async def scenario() -> tuple[int, bytes]:
        server = bridge.WebSocketServer("127.0.0.1", 0)
        await server.start()
        reader, writer = await connect(server.port_in_use)
        writer.write(masked_frame(b"are you there", bridge.OPCODE_PING))
        await writer.drain()
        reply = await asyncio.wait_for(bridge.read_frame(reader), 5.0)
        await hang_up(writer)
        await server.close()
        return reply

    assert asyncio.run(scenario()) == (bridge.OPCODE_PONG, b"are you there")
