#!/usr/bin/env python3
"""Simulated DGT e-board for testing PicoChess without hardware (Linux and macOS).

The simulator opens a pseudo-terminal that speaks the DGT serial protocol, so
PicoChess runs its real DGT driver against it:

    venv/bin/python tools/dgt_simulator.py --link /tmp/dgt-sim
    # picochess.ini: board-type = dgt   and   dgt-port = /tmp/dgt-sim

Open http://localhost:8081 to move pieces. Click a piece to lift it and click
a square to put it down, exactly like the physical board: PicoChess sees every
lift and every placement. After the engine moves, either make its move on the
simulated board or press "Copy PicoChess position".

No DGT clock is simulated; PicoChess then uses its web clock.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("dgt-simulator")

# DGT protocol: commands from PicoChess (see dgt/util.py DgtCmd).
CMD_SEND_RESET = 0x40
CMD_SEND_BRD = 0x42
CMD_SEND_UPDATE = 0x43
CMD_SEND_UPDATE_BRD = 0x44
CMD_RETURN_SERIALNR = 0x45
CMD_RETURN_BUSADRES = 0x46
CMD_SEND_TRADEMARK = 0x47
CMD_SEND_EE_MOVES = 0x49
CMD_SEND_UPDATE_NICE = 0x4B
CMD_SEND_BATTERY_STATUS = 0x4C
CMD_SEND_VERSION = 0x4D
CMD_RETURN_LONG_SERIALNR = 0x55
CMD_CLOCK_MESSAGE = 0x2B

# Messages to PicoChess (see dgt/util.py DgtMsg).
MSG_BOARD_DUMP = 0x86
MSG_FIELD_UPDATE = 0x8E
MSG_SERIALNR = 0x91
MSG_VERSION = 0x93
MSG_LONG_SERIALNR = 0xA2

PIECE_CODES = {"P": 1, "R": 2, "N": 3, "B": 4, "K": 5, "Q": 6, "p": 7, "r": 8, "n": 9, "b": 10, "k": 11, "q": 12}
CODE_PIECES = {code: piece for piece, code in PIECE_CODES.items()}
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
FILES = "abcdefgh"


def message(message_id: int, payload: bytes) -> bytes:
    """Encode a DGT message: id, 14-bit length (header included), payload."""
    length = len(payload) + 3
    return bytes([message_id, (length >> 7) & 0x7F, length & 0x7F]) + payload


def square_index(name: str) -> int:
    """DGT square index for a square name: a8 = 0 ... h1 = 63."""
    name = name.strip().lower()
    if len(name) != 2 or name[0] not in FILES or name[1] not in "12345678":
        raise ValueError("not a square: %r" % name)
    return (8 - int(name[1])) * 8 + FILES.index(name[0])


def square_name(index: int) -> str:
    return FILES[index % 8] + str(8 - index // 8)


class SimulatedBoard:
    """The board state and the DGT protocol. It does no I/O itself."""

    def __init__(self, fen: str = START_FEN):
        self.squares = [0] * 64
        self.in_hand: list[str] = []  # pieces lifted and not yet put down
        self.update_mode = False
        self.log: list[str] = []
        self.set_fen(fen)

    # ── position ───────────────────────────────────────────
    def fen(self) -> str:
        rows = []
        for rank in range(8):
            row, empty = "", 0
            for code in self.squares[rank * 8: rank * 8 + 8]:
                if code == 0:
                    empty += 1
                    continue
                if empty:
                    row, empty = row + str(empty), 0
                row += CODE_PIECES[code]
            rows.append(row + (str(empty) if empty else ""))
        return "/".join(rows)

    def set_fen(self, fen: str) -> None:
        placement = fen.strip().split(" ")[0]
        rows = placement.split("/")
        if len(rows) != 8:
            raise ValueError("a FEN placement has 8 ranks")
        squares: list[int] = []
        for row in rows:
            count = 0
            for char in row:
                if char.isdigit():
                    squares.extend([0] * int(char))
                    count += int(char)
                elif char in PIECE_CODES:
                    squares.append(PIECE_CODES[char])
                    count += 1
                else:
                    raise ValueError("unknown piece %r" % char)
            if count != 8:
                raise ValueError("rank %r does not have 8 squares" % row)
        self.squares = squares
        self.in_hand = []

    # ── piece handling: each change is one field update ──────
    def _field_update(self, index: int) -> bytes:
        if not self.update_mode:
            return b""
        return message(MSG_FIELD_UPDATE, bytes([index, self.squares[index]]))

    def lift(self, square: str) -> bytes:
        index = square_index(square)
        code = self.squares[index]
        if not code:
            raise ValueError("%s is empty" % square)
        self.squares[index] = 0
        self.in_hand.append(CODE_PIECES[code])
        return self._field_update(index)

    def place(self, square: str, piece: str | None = None) -> bytes:
        """Put a piece down: the given piece, or the last lifted one.

        An occupied square is lifted first, as a hand would do on a real board.
        """
        if piece is None:
            if not self.in_hand:
                raise ValueError("no piece in hand")
            piece = self.in_hand.pop()
        elif piece in self.in_hand:
            self.in_hand.remove(piece)
        if piece not in PIECE_CODES:
            raise ValueError("unknown piece %r" % piece)
        index = square_index(square)
        out = b""
        if self.squares[index]:
            out += self.lift(square)
            self.in_hand.pop()  # a captured piece leaves the board
        self.squares[index] = PIECE_CODES[piece]
        return out + self._field_update(index)

    def remove(self, square: str) -> bytes:
        out = self.lift(square)
        self.in_hand.pop()
        return out

    def move(self, uci: str) -> bytes:
        """Make a move like a person: capture first, then lift, then place."""
        uci = uci.strip().lower()
        if len(uci) not in (4, 5):
            raise ValueError("use a move such as e2e4 or e7e8q")
        src, dst = uci[:2], uci[2:4]
        piece = CODE_PIECES.get(self.squares[square_index(src)])
        if piece is None:
            raise ValueError("%s is empty" % src)
        out = b""
        if self.squares[square_index(dst)]:
            out += self.remove(dst)
        elif piece in "Pp" and src[0] != dst[0]:  # en passant
            out += self.remove(dst[0] + src[1])
        out += self.lift(src)
        if len(uci) == 5:
            self.in_hand.pop()
            promoted = uci[4]
            piece = promoted.upper() if piece.isupper() else promoted
        out += self.place(dst, piece)
        if piece in "Kk" and abs(FILES.index(src[0]) - FILES.index(dst[0])) == 2:  # castling: move the rook too
            rank = src[1]
            rook_src, rook_dst = ("h" + rank, "f" + rank) if dst[0] == "g" else ("a" + rank, "d" + rank)
            rook = "R" if piece == "K" else "r"
            if self.squares[square_index(rook_src)] == PIECE_CODES[rook]:
                out += self.lift(rook_src) + self.place(rook_dst)
        return out

    def changes_to(self, fen: str) -> bytes:
        """Field updates that turn the current position into ``fen``."""
        target = SimulatedBoard(fen).squares
        out = b""
        for index in range(64):  # remove first, then place, like a person would
            if self.squares[index] and self.squares[index] != target[index]:
                self.squares[index] = 0
                out += self._field_update(index)
        for index in range(64):
            if target[index] and self.squares[index] != target[index]:
                self.squares[index] = target[index]
                out += self._field_update(index)
        self.in_hand = []
        return out

    # ── protocol ─────────────────────────────────────────────
    def board_dump(self) -> bytes:
        return message(MSG_BOARD_DUMP, bytes(self.squares))

    def handle(self, data: bytes) -> tuple[bytes, int]:
        """Answer PicoChess commands. Returns (reply, bytes consumed)."""
        reply = b""
        pos = 0
        while pos < len(data):
            command = data[pos]
            if command == CMD_CLOCK_MESSAGE:
                # [0x2B, n, n bytes]; no clock is simulated, so it is not answered
                if pos + 1 >= len(data) or pos + 2 + data[pos + 1] > len(data):
                    break  # wait for the rest of the clock message
                pos += 2 + data[pos + 1]
                self._note("clock message ignored")
                continue
            pos += 1
            if command == CMD_SEND_RESET:
                self.update_mode = False
                self._note("reset")
            elif command == CMD_SEND_BRD:
                reply += self.board_dump()
                self._note("board requested")
            elif command in (CMD_SEND_UPDATE, CMD_SEND_UPDATE_BRD, CMD_SEND_UPDATE_NICE):
                self.update_mode = True
                self._note("update mode on")
            elif command == CMD_SEND_VERSION:
                reply += message(MSG_VERSION, bytes([3, 1]))
                self._note("version requested")
            elif command == CMD_RETURN_SERIALNR:
                reply += message(MSG_SERIALNR, b"SIM01")
            elif command == CMD_RETURN_LONG_SERIALNR:
                reply += message(MSG_LONG_SERIALNR, b"0000000001")
            elif command in (CMD_RETURN_BUSADRES, CMD_SEND_TRADEMARK, CMD_SEND_EE_MOVES, CMD_SEND_BATTERY_STATUS):
                self._note("command 0x%02X not simulated" % command)
            else:
                self._note("unknown command 0x%02X" % command)
        return reply, pos

    def _note(self, text: str) -> None:
        if self.log and self.log[-1].startswith(text):
            return  # keep the log readable when PicoChess repeats itself
        self.log.append(text)
        del self.log[:-30]

    def state(self) -> dict[str, Any]:
        return {"fen": self.fen(), "in_hand": list(self.in_hand), "update_mode": self.update_mode, "log": self.log}


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DGT Simulator</title>
<style>
:root { color-scheme: light dark; --bg:#f4f6f8; --fg:#1f2933; --muted:#52606d; --card:#fff; --line:#c8d0da; --acc:#3b71ca; }
@media (prefers-color-scheme: dark) { :root { --bg:#0b0f14; --fg:#edf2f7; --muted:#b6c2cf; --card:#141a22; --line:#344253; --acc:#7aa2e8; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.4 system-ui, sans-serif; }
main { max-width: 980px; margin: 0 auto; padding: 16px; display:flex; gap:20px; flex-wrap:wrap; }
h1 { font-size:1.3rem; margin:0 0 4px; width:100%; }
p.sub { margin:0 0 8px; color:var(--muted); width:100%; }
#board { display:grid; grid-template-columns: repeat(8, min(11vw, 60px)); grid-auto-rows: min(11vw, 60px); align-self:flex-start; border:2px solid var(--line); user-select:none; }
.sq { width:min(11vw, 60px); height:min(11vw, 60px); display:flex; align-items:center; justify-content:center;
      font-size:min(8.5vw, 44px); cursor:pointer; position:relative; color:#111; }
.l { background:#f0d9b5; } .d { background:#b58863; }
.sq.light { box-shadow: inset 0 0 0 4px #e0a800; }
.sq small { position:absolute; left:2px; bottom:0; font-size:10px; opacity:.55; }
.panel { flex:1 1 300px; display:flex; flex-direction:column; gap:10px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; }
button, input { font:inherit; }
button { padding:6px 12px; border-radius:8px; border:1px solid var(--line); background:var(--bg); color:var(--fg); cursor:pointer; }
button.primary { background:var(--acc); border-color:var(--acc); color:#fff; }
input[type=text] { width:100%; padding:6px 8px; border-radius:8px; border:1px solid var(--line); background:var(--bg); color:var(--fg); }
.row { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
#hand { font-size:2rem; min-height:2.6rem; color:var(--fg); }
#palette button { font-size:1.4rem; padding:2px 8px; }
#log { font-family: ui-monospace, monospace; font-size:.85rem; color:var(--muted); max-height:9rem; overflow:auto; white-space:pre-wrap; }
#status.err { color:#d33; }
[hidden] { display:none !important; }
</style></head><body><main>
<h1>DGT e-board simulator</h1>
<p class="sub">Click a piece to lift it, then click a square to put it down. PicoChess sees each step, as on a real DGT board.</p>
<div id="board" aria-label="Simulated board"></div>
<div class="panel">
  <div class="card">
    <strong>In hand</strong> <span class="sub">(click a square to put down, click here to drop off the board)</span>
    <div id="hand" title="Click to take these pieces off the board"></div>
    <div id="palette" class="row" aria-label="Add a piece"></div>
  </div>
  <div class="card" id="engineCard" hidden>
    <strong>PicoChess shows the engine move <span id="light"></span></strong>
    <div class="row" style="margin-top:6px"><button class="primary" id="engineBtn">Make this move on the board</button></div>
  </div>
  <div class="card">
    <label for="move"><strong>Make a move</strong> (e2e4, e7e8q)</label>
    <div class="row"><input type="text" id="move" autocomplete="off"><button id="moveBtn">Move</button></div>
    <div class="row" style="margin-top:8px">
      <button class="primary" id="sync">Copy PicoChess position</button>
      <button id="start">Start position</button>
      <button id="clear">Clear board</button>
    </div>
    <label for="fen" style="display:block;margin-top:8px"><strong>Position (FEN)</strong></label>
    <div class="row"><input type="text" id="fen" autocomplete="off"><button id="setFen">Set</button></div>
    <p id="status" role="status"></p>
  </div>
  <div class="card"><strong>Protocol</strong> <span id="mode"></span><div id="log"></div></div>
</div>
</main>
<script>
var GLYPH = {K:'♔',Q:'♕',R:'♖',B:'♗',N:'♘',P:'♙',k:'♚',q:'♛',r:'♜',b:'♝',n:'♞',p:'♟'};
var FILES = 'abcdefgh', state = null;
function expand(fen) { var out = []; fen.split('/').forEach(function (row) { row.split('').forEach(function (c) {
  if (/\d/.test(c)) { for (var i = 0; i < +c; i++) out.push(''); } else out.push(c); }); }); return out; }
function status(text, err) { var s = document.getElementById('status'); s.textContent = text || ''; s.className = err ? 'err' : ''; }
function send(action, data) {
  return fetch('/api/' + action, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data || {}) })
    .then(function (r) { return r.json(); }).then(function (res) { if (res.error) status(res.error, true); else status(res.message || ''); render(res.state); return res; });
}
function render(s) {
  if (!s) return; state = s;
  var squares = expand(s.fen), board = document.getElementById('board');
  board.innerHTML = '';
  squares.forEach(function (piece, i) {
    var name = FILES[i % 8] + (8 - Math.floor(i / 8));
    var el = document.createElement('div');
    el.className = 'sq ' + (((i % 8) + Math.floor(i / 8)) % 2 ? 'd' : 'l');
    el.textContent = GLYPH[piece] || '';
    el.title = name;
    if (s.light && (s.light.slice(0, 2) === name || s.light.slice(2, 4) === name)) el.classList.add('light');
    if (i % 8 === 0 || i >= 56) { var lbl = document.createElement('small'); lbl.textContent = name; el.appendChild(lbl); }
    el.addEventListener('click', function () {
      if (s.in_hand.length) send('place', { square: name });
      else if (piece) send('lift', { square: name });
    });
    board.appendChild(el);
  });
  document.getElementById('hand').textContent = s.in_hand.map(function (p) { return GLYPH[p]; }).join(' ');
  document.getElementById('fen').value = s.fen;
  document.getElementById('mode').textContent = s.update_mode ? '- PicoChess connected' : '- waiting for PicoChess';
  document.getElementById('engineCard').hidden = !s.light;
  document.getElementById('light').textContent = s.light || '';
  document.getElementById('log').textContent = s.log.slice().reverse().join('\n');
}
'KQRBNPkqrbnp'.split('').forEach(function (p) {
  var b = document.createElement('button'); b.textContent = GLYPH[p]; b.title = 'Take a new ' + p + ' in hand';
  b.addEventListener('click', function () { send('take', { piece: p }); });
  document.getElementById('palette').appendChild(b);
});
document.getElementById('hand').addEventListener('click', function () { if (state && state.in_hand.length) send('drop'); });
document.getElementById('moveBtn').addEventListener('click', function () { send('move', { move: document.getElementById('move').value }); document.getElementById('move').value = ''; });
document.getElementById('move').addEventListener('keydown', function (e) { if (e.key === 'Enter') document.getElementById('moveBtn').click(); });
document.getElementById('engineBtn').addEventListener('click', function () { send('engine'); });
document.getElementById('sync').addEventListener('click', function () { send('sync'); });
document.getElementById('start').addEventListener('click', function () { send('fen', { fen: 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR' }); });
document.getElementById('clear').addEventListener('click', function () { send('fen', { fen: '8/8/8/8/8/8/8/8' }); });
document.getElementById('setFen').addEventListener('click', function () { send('fen', { fen: document.getElementById('fen').value }); });
function poll() { fetch('/api/state').then(function (r) { return r.json(); }).then(function (res) { if (!state || JSON.stringify(res.state) !== JSON.stringify(state)) render(res.state); }).catch(function () {}); }
poll(); setInterval(poll, 1500);
</script></body></html>
"""


class Simulator:
    """Connects a SimulatedBoard to a pseudo-terminal and a small web page."""

    def __init__(self, board: SimulatedBoard, picochess_url: str):
        self.board = board
        self.picochess_url = picochess_url.rstrip("/")
        self.master_fd = -1
        self.device = ""
        self.pending = b""
        self.light = ""  # engine move PicoChess shows on the board LEDs
        self.picochess_online = False
        self.follower: asyncio.Future | None = None

    def state(self) -> dict[str, Any]:
        state = self.board.state()
        state["light"] = self.light
        state["picochess_online"] = self.picochess_online
        return state

    async def follow_picochess(self) -> None:
        """Listen to PicoChess's web events for the engine move to make on the board."""
        from tornado.websocket import websocket_connect

        url = "ws" + self.picochess_url[len("http"):] + "/event"
        while True:
            try:
                connection = await websocket_connect(url)
                self.picochess_online = True
                while True:
                    raw = await connection.read_message()
                    if raw is None:
                        break
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        continue
                    if event.get("event") == "Light":
                        self.light = str(event.get("move") or "")
                    elif event.get("event") == "Clear" or (
                        event.get("event") == "Fen" and event.get("play") == "computer"
                    ):
                        self.light = ""
                    elif event.get("event") == "NewGame":
                        self.light = ""
            except Exception as exc:  # PicoChess not running yet or restarted
                logger.debug("waiting for PicoChess: %s", exc)
            self.picochess_online = False
            self.light = ""
            await asyncio.sleep(3)

    def open_pty(self, link: str | None) -> str:
        import pty
        import tty

        master, slave = pty.openpty()
        tty.setraw(slave)
        try:
            tty.setraw(master)
        except Exception:  # not needed on every platform
            pass
        os.set_blocking(master, False)
        self.master_fd = master
        self.device = os.ttyname(slave)
        self._slave = slave  # keep the slave open so the device stays available
        if link:
            if os.path.islink(link):
                os.unlink(link)
            os.symlink(self.device, link)
        return self.device

    def write(self, data: bytes) -> None:
        if data and self.master_fd >= 0:
            try:
                os.write(self.master_fd, data)
            except OSError as exc:
                logger.warning("cannot write to PicoChess: %s", exc)

    def on_readable(self) -> None:
        try:
            data = os.read(self.master_fd, 1024)
        except BlockingIOError:
            return
        except OSError:
            return
        self.pending += data
        reply, used = self.board.handle(self.pending)
        self.pending = self.pending[used:]
        self.write(reply)

    async def picochess_fen(self) -> str:
        from tornado.httpclient import AsyncHTTPClient

        response = await AsyncHTTPClient().fetch(self.picochess_url + "/dgt?action=get_last_move", request_timeout=5)
        data = json.loads(response.body or b"{}")
        fen = data.get("fen") or ""
        if not fen:
            raise ValueError("PicoChess has no position yet")
        return fen

    async def api(self, action: str, data: dict[str, Any]) -> dict[str, Any]:
        board = self.board
        try:
            if action == "lift":
                self.write(board.lift(data["square"]))
            elif action == "place":
                self.write(board.place(data["square"]))
            elif action == "take":
                piece = str(data.get("piece", ""))
                if piece not in PIECE_CODES:
                    raise ValueError("unknown piece")
                board.in_hand.append(piece)
            elif action == "drop":
                board.in_hand = []
            elif action == "move":
                self.write(board.move(str(data.get("move", ""))))
            elif action == "fen":
                self.write(board.changes_to(str(data.get("fen", ""))))
            elif action == "engine":
                if not self.light:
                    raise ValueError("PicoChess is not waiting for an engine move")
                self.write(board.move(self.light))
            elif action == "sync":
                self.write(board.changes_to(await self.picochess_fen()))
                if self.light:
                    self.write(board.move(self.light))
                return {"state": self.state(), "message": "Board now shows the PicoChess position."}
            elif action != "state":
                raise ValueError("unknown action")
        except (KeyError, ValueError) as exc:
            return {"state": self.state(), "error": str(exc)}
        except Exception as exc:  # network errors from PicoChess
            return {"state": self.state(), "error": "Cannot read PicoChess: %s" % exc}
        return {"state": self.state()}


def make_app(simulator: Simulator):
    import tornado.web

    class PageHandler(tornado.web.RequestHandler):
        def get(self):
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.write(PAGE)

    class ApiHandler(tornado.web.RequestHandler):
        async def get(self, action):
            self.write(await simulator.api(action, {}))

        async def post(self, action):
            try:
                data = json.loads(self.request.body or b"{}")
            except ValueError:
                data = {}
            self.write(await simulator.api(action, data if isinstance(data, dict) else {}))

    return tornado.web.Application([(r"/", PageHandler), (r"/api/([a-z]+)", ApiHandler)])


async def run(args: argparse.Namespace) -> None:
    simulator = Simulator(SimulatedBoard(args.fen), args.picochess_url)
    device = simulator.open_pty(args.link)
    asyncio.get_running_loop().add_reader(simulator.master_fd, simulator.on_readable)
    make_app(simulator).listen(args.port, address=args.address)
    simulator.follower = asyncio.ensure_future(simulator.follow_picochess())
    port_name = args.link or device
    print("DGT simulator ready")
    print("  serial port : %s" % port_name)
    print("  web page    : http://localhost:%d" % args.port)
    print("Set in picochess.ini:  board-type = dgt   and   dgt-port = %s" % port_name)
    await asyncio.Event().wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simulated DGT e-board for PicoChess (Linux and macOS).")
    parser.add_argument("--port", type=int, default=8081, help="web page port (default 8081)")
    parser.add_argument("--address", default="127.0.0.1", help="web page address (default 127.0.0.1)")
    parser.add_argument("--link", default="/tmp/dgt-sim", help="stable symlink to the serial device ('' for none)")
    parser.add_argument("--picochess-url", default="http://localhost:8080", help="PicoChess web address")
    parser.add_argument("--fen", default=START_FEN, help="starting piece placement")
    args = parser.parse_args(argv)
    if os.name != "posix":
        print("The simulator needs a pseudo-terminal: run it on Linux or macOS.", file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    finally:
        if args.link and os.path.islink(args.link):
            os.unlink(args.link)
    return 0


if __name__ == "__main__":
    sys.exit(main())
