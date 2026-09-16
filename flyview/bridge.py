import argparse
import asyncio
import base64
import hashlib
import json
import struct
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

DESCRIPTION = "Poll doomfly /state and republish a slim message on a local websocket."
SCHEMA = 1
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_SOURCE = "http://127.0.0.1:8766/state"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8767
DEFAULT_POLL = 0.125
PPL101_IDS = ("11327", "11900")
NEURON_KEYS = ("DNp20_L", "DNp20_R", "DNpe017", f"PPL101_{PPL101_IDS[0]}", f"PPL101_{PPL101_IDS[1]}")
MAX_CLIENT_FRAME = 1 << 20
CLIENT_QUEUE = 8
OPCODE_TEXT = 0x1
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


def accept_key(key: str) -> str:
    digest = hashlib.sha1((key + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(payload: bytes, opcode: int = OPCODE_TEXT) -> bytes:
    header = bytearray([0x80 | opcode])
    size = len(payload)
    if size < 126:
        header.append(size)
    elif size < 1 << 16:
        header.append(126)
        header.extend(struct.pack("!H", size))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", size))
    return bytes(header) + payload


def unmask(payload: bytes, mask: bytes) -> bytes:
    return bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))


async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    first, second = await reader.readexactly(2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    size = second & 0x7F
    if size == 126:
        size = struct.unpack("!H", await reader.readexactly(2))[0]
    elif size == 127:
        size = struct.unpack("!Q", await reader.readexactly(8))[0]
    if size > MAX_CLIENT_FRAME:
        raise ValueError(f"client frame of {size} bytes exceeds the limit")
    mask = await reader.readexactly(4) if masked else b""
    payload = await reader.readexactly(size)
    return opcode, unmask(payload, mask) if masked else payload


def handshake_response(request: bytes) -> bytes | None:
    lines = request.decode("latin-1").split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, separator, value = line.partition(":")
        if separator:
            headers[name.strip().lower()] = value.strip()
    key = headers.get("sec-websocket-key")
    if not key or "websocket" not in headers.get("upgrade", "").lower():
        return None
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key(key)}\r\n\r\n"
    ).encode("ascii")


@dataclass(eq=False)
class Client:
    writer: asyncio.StreamWriter
    queue: asyncio.Queue[bytes]

    def offer(self, frame: bytes) -> None:
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(frame)


class WebSocketServer:
    def __init__(self, host: str, port: int, verbose: bool = False) -> None:
        self.host = host
        self.port = port
        self.verbose = verbose
        self.clients: set[Client] = set()
        self.latest: bytes | None = None
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, self.host, self.port)

    async def close(self) -> None:
        for client in list(self.clients):
            client.writer.close()
        self.clients.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    @property
    def port_in_use(self) -> int:
        if self._server is None or not self._server.sockets:
            return self.port
        return int(self._server.sockets[0].getsockname()[1])

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
            writer.close()
            return
        response = handshake_response(request)
        if response is None:
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        writer.write(response)
        await writer.drain()
        client = Client(writer=writer, queue=asyncio.Queue(maxsize=CLIENT_QUEUE))
        self.clients.add(client)
        if self.latest is not None:
            client.offer(encode_frame(self.latest))
        self.log(f"client connected, {len(self.clients)} open")
        sender = asyncio.create_task(self._send(client))
        try:
            while True:
                opcode, payload = await read_frame(reader)
                if opcode == OPCODE_CLOSE:
                    break
                if opcode == OPCODE_PING:
                    client.offer(encode_frame(payload, OPCODE_PONG))
        except (asyncio.IncompleteReadError, ConnectionError, ValueError):
            pass
        finally:
            sender.cancel()
            self.clients.discard(client)
            writer.close()
            self.log(f"client gone, {len(self.clients)} open")

    async def _send(self, client: Client) -> None:
        try:
            while True:
                frame = await client.queue.get()
                client.writer.write(frame)
                await client.writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass

    def broadcast(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, separators=(",", ":")).encode()
        self.latest = payload
        frame = encode_frame(payload)
        for client in list(self.clients):
            client.offer(frame)

    def log(self, text: str) -> None:
        if self.verbose:
            print(f"[bridge] {text}", file=sys.stderr, flush=True)


def _readout_activity(readout: dict[str, Any]) -> dict[str, float]:
    return {"rate_hz": float(readout.get("rate_hz", 0.0)), "spikes": int(readout.get("spikes", 0))}


def _sum_activity(readouts: Iterable[dict[str, Any]]) -> dict[str, float] | None:
    found = list(readouts)
    if not found:
        return None
    return {
        "rate_hz": round(sum(float(r.get("rate_hz", 0.0)) for r in found), 3),
        "spikes": sum(int(r.get("spikes", 0)) for r in found),
    }


def neuron_activity(state: dict[str, Any]) -> dict[str, dict[str, float] | None]:
    readouts: list[dict[str, Any]] = state.get("readouts") or []

    def one(cell_type: str, side: str) -> dict[str, float] | None:
        for readout in readouts:
            if readout.get("type") == cell_type and readout.get("side") == side:
                return _readout_activity(readout)
        return None

    activity: dict[str, dict[str, float] | None] = {
        "DNp20_L": one("DNp20", "L"),
        "DNp20_R": one("DNp20", "R"),
        "DNpe017": _sum_activity(r for r in readouts if r.get("type") == "DNpe017"),
    }
    for body_id in PPL101_IDS:
        match = next((r for r in readouts if str(r.get("id")) == body_id), None)
        activity[f"PPL101_{body_id}"] = None if match is None else _readout_activity(match)
    return activity


def activity_rates(state: dict[str, Any]) -> dict[str, Any]:
    rates: dict[str, float] = {}
    observed: set[str] = set()
    raster: dict[str, Any] = state.get("raster") or {}
    bins: list[dict[str, Any]] = raster.get("bins") or []
    window = float(bins[-1].get("window_ms") or 0.0) if bins else 0.0
    if window > 0:
        for body_id, count in zip(raster.get("neuron_ids") or [], bins[-1].get("counts") or []):
            observed.add(str(body_id))
            if count:
                rates[str(body_id)] = round(count / window * 1000.0, 1)
    for readout in state.get("readouts") or []:
        body_id = str(readout.get("id"))
        observed.add(body_id)
        rate = round(float(readout.get("rate_hz", 0.0)), 2)
        if rate:
            rates[body_id] = rate
        else:
            rates.pop(body_id, None)
    return {"window_ms": window, "observed": len(observed), "rates": rates}


def slim(state: dict[str, Any], activity: bool = False) -> dict[str, Any]:
    game: dict[str, Any] = state.get("game") or {}
    spectator: dict[str, Any] = state.get("spectator") or {}
    player: dict[str, Any] = spectator.get("player") or {}
    position = None
    heading = None
    if player:
        position = [round(float(player.get(axis, 0.0)), 3) for axis in ("x", "y", "z")]
        heading = round(float(player.get("angle", 0.0)), 3)
    message: dict[str, Any] = {
        "v": SCHEMA,
        "status": state.get("status", "running"),
        "run_id": state.get("run_id"),
        "sequence": state.get("sequence"),
        "t_ms": state.get("generated_at_ms"),
        "round": game.get("episode"),
        "health": game.get("health"),
        "ammo": game.get("ammo"),
        "kills": game.get("kills"),
        "pos": position,
        "heading": heading,
        "neurons": neuron_activity(state),
    }
    if activity:
        message["activity"] = activity_rates(state)
    return message


def offline(reason: str) -> dict[str, Any]:
    return {
        "v": SCHEMA,
        "status": "offline",
        "run_id": None,
        "sequence": None,
        "t_ms": int(time.time() * 1000),
        "round": None,
        "health": None,
        "ammo": None,
        "kills": None,
        "pos": None,
        "heading": None,
        "neurons": {key: None for key in NEURON_KEYS},
        "error": reason,
    }


def is_slim(message: dict[str, Any]) -> bool:
    return "neurons" in message and "game" not in message


def fetch_state(source: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(source, timeout=timeout) as response:
        payload: dict[str, Any] = json.loads(response.read())
    return payload


async def pump_live(server: WebSocketServer, source: str, poll: float, record: Path | None, activity: bool = False) -> None:
    loop = asyncio.get_running_loop()
    last_key: tuple[Any, Any] | None = None
    offline_reason: str | None = None
    handle = record.open("a", encoding="utf-8") if record is not None else None
    try:
        while True:
            try:
                state = await loop.run_in_executor(None, fetch_state, source, 10.0)
            except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as error:
                reason = f"unreachable: {type(error).__name__}"
            else:
                status = str(state.get("status", "unknown"))
                reason = None if status == "running" else status
            if reason is not None:
                if reason != offline_reason:
                    server.broadcast(offline(reason))
                    server.log(f"source {reason}")
                    offline_reason = reason
                    last_key = None
                await asyncio.sleep(max(poll, 1.0))
                continue
            if offline_reason is not None:
                server.log("source running")
                offline_reason = None
            key = (state.get("run_id"), state.get("sequence"))
            if key != last_key:
                last_key = key
                message = slim(state, activity)
                server.broadcast(message)
                if handle is not None:
                    handle.write(json.dumps(message, separators=(",", ":")) + "\n")
                    handle.flush()
            await asyncio.sleep(poll)
    finally:
        if handle is not None:
            handle.close()


def load_replay(path: Path, activity: bool = False) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise SystemExit(f"{path}:{number}: not JSON ({error})") from error
        messages.append(record if is_slim(record) else slim(record, activity))
    if not messages:
        raise SystemExit(f"{path} has no messages")
    return messages


async def pump_replay(server: WebSocketServer, path: Path, speed: float, once: bool, activity: bool = False) -> None:
    messages = load_replay(path, activity)
    server.log(f"replaying {len(messages)} messages from {path}")
    while True:
        previous: int | None = None
        for message in messages:
            stamp = message.get("t_ms")
            if previous is not None and isinstance(stamp, int):
                delay = min(max((stamp - previous) / 1000.0, 0.0), 2.0) / max(speed, 0.01)
                await asyncio.sleep(delay)
            else:
                await asyncio.sleep(DEFAULT_POLL / max(speed, 0.01))
            if isinstance(stamp, int):
                previous = stamp
            server.broadcast(message)
        if once:
            return


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="doomfly /state URL")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL, help="seconds between polls")
    parser.add_argument("--replay", type=Path, help="serve a .jsonl file instead of the simulator")
    parser.add_argument("--record", type=Path, help="append the slim messages to a .jsonl file")
    parser.add_argument("--speed", type=float, default=1.0, help="replay speed multiplier")
    parser.add_argument("--once", action="store_true", help="stop after one pass of the replay")
    parser.add_argument("--activity", action="store_true", help="add per-neuron firing rates for the blueprint view")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def ignore_connection_resets(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    if isinstance(context.get("exception"), (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return
    loop.default_exception_handler(context)


async def run(args: argparse.Namespace) -> None:
    asyncio.get_running_loop().set_exception_handler(ignore_connection_resets)
    server = WebSocketServer(args.host, args.port, verbose=args.verbose)
    await server.start()
    where = f"replay {args.replay}" if args.replay else args.source
    extra = " (+activity)" if args.activity else ""
    print(f"flyview bridge: ws://{args.host}:{server.port_in_use}  <-  {where}{extra}", flush=True)
    try:
        if args.replay:
            await pump_replay(server, args.replay, args.speed, args.once, args.activity)
        else:
            await pump_live(server, args.source, args.poll, args.record, args.activity)
    finally:
        await server.close()


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
