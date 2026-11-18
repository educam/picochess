"""Helpers for the browser setup wizard (``/setup``).

The wizard lets a user choose and test an e-board from the web client instead
of the DGT clock menu or by editing ``picochess.ini`` by hand.

This module only contains presentation and probing helpers. It does not change
board drivers: the selected board is written to ``picochess.ini`` and is used
by the normal driver start-up path after PicoChess restarts.

Serial probing is blocking (pyserial). Callers on the shared asyncio loop must
run :func:`probe_dgt_port` and :func:`check_port_opens` through
``asyncio.to_thread``.
"""

from __future__ import annotations

import os
import platform
import time
from typing import Any, Callable, Iterable

from configobj import ConfigObj  # type: ignore[import-untyped]

# Board catalogue for the wizard, in display order.
# ``port`` describes how the driver uses the ``dgt-port`` setting:
#   "optional" - used when given, otherwise the driver searches for the board
#   "required" - the driver cannot start without it
#   "unused"   - the driver finds the board by itself (USB scan or Bluetooth LE)
# ``probe`` names the live test the wizard can run before restarting.
BOARD_TYPES: list[dict[str, str]] = [
    {
        "id": "noeboard",
        "label": "No e-board (play in the browser)",
        "transport": "none",
        "port": "unused",
        "probe": "none",
        "hint": "Moves are made on the web board. Nothing to connect.",
    },
    {
        "id": "dgt",
        "label": "DGT e-board (USB, serial or Bluetooth)",
        "transport": "serial",
        "port": "optional",
        "probe": "dgt",
        "hint": (
            "On Linux PicoChess searches USB ports and pairs Bluetooth boards by itself. "
            "On Windows and macOS pair the board in the system first, then choose its COM or /dev/cu.* port."
        ),
    },
    {
        "id": "certabo",
        "label": "Certabo",
        "transport": "usb",
        "port": "unused",
        "probe": "open",
        "hint": "PicoChess searches the USB ports for the board when it starts.",
    },
    {
        "id": "chesslink",
        "label": "Millennium ChessLink",
        "transport": "usb",
        "port": "unused",
        "probe": "open",
        "hint": "PicoChess searches the USB ports for the board when it starts.",
    },
    {
        "id": "chessnut",
        "label": "Chessnut (Bluetooth LE)",
        "transport": "ble",
        "port": "unused",
        "probe": "none",
        "hint": "Switch the board on. PicoChess connects over Bluetooth LE when it starts.",
    },
    {
        "id": "ichessone",
        "label": "iChessOne (Bluetooth LE)",
        "transport": "ble",
        "port": "unused",
        "probe": "none",
        "hint": "Switch the board on. PicoChess connects over Bluetooth LE when it starts.",
    },
    {
        "id": "citrine",
        "label": "Novag Citrine (experimental)",
        "transport": "serial",
        "port": "required",
        "probe": "open",
        "hint": "Choose the serial port the board is connected to.",
    },
    {
        "id": "osa",
        "label": "Saitek OSA (experimental)",
        "transport": "serial",
        "port": "required",
        "probe": "open",
        "hint": "Choose the serial port of the OSA module.",
    },
]

BOARD_TYPE_IDS = frozenset(board["id"] for board in BOARD_TYPES)
MAX_PORT_LENGTH = 200

# DGT serial protocol constants (see dgt/util.py DgtCmd and DgtMsg).
_DGT_SEND_RESET = 0x40
_DGT_SEND_BRD = 0x42
_DGT_MSG_BOARD_DUMP = 0x86
_DGT_SIZE_BOARD_DUMP = 67

_DGT_PIECES = {
    0x01: "P",
    0x02: "R",
    0x03: "N",
    0x04: "B",
    0x05: "K",
    0x06: "Q",
    0x07: "p",
    0x08: "r",
    0x09: "n",
    0x0A: "b",
    0x0B: "k",
    0x0C: "q",
}

_MAC_IGNORED_PORTS = ("Bluetooth-Incoming-Port", "debug-console", "wlan-debug")


def board_type_info(board_id: str) -> dict[str, str] | None:
    for board in BOARD_TYPES:
        if board["id"] == board_id:
            return board
    return None


def normalize_board_type(value: str) -> str | None:
    """Return the ini value for a board type, or None when it is unknown."""
    value = (value or "").strip().lower()
    if value == "none":
        value = "noeboard"
    return value if value in BOARD_TYPE_IDS else None


def validate_port(value: str) -> str | None:
    """Return a cleaned port name, "" for automatic, or None when invalid."""
    value = (value or "").strip()
    if len(value) > MAX_PORT_LENGTH:
        return None
    if any(ch in value for ch in "\r\n\0#="):
        return None
    return value


def dgt_board_dump_to_fen(squares: Iterable[int]) -> str:
    """Convert a 64-byte DGT board dump (a8..h1) to a FEN piece placement.

    Like dgt/board.py this is the raw orientation as the board reports it.
    """
    values = list(squares)
    if len(values) != 64:
        raise ValueError("a DGT board dump has 64 squares, got %d" % len(values))
    rows = []
    for rank in range(8):
        row = ""
        empty = 0
        for value in values[rank * 8: rank * 8 + 8]:
            piece = _DGT_PIECES.get(value & 0x0F) if value < 0x0D else None
            if piece is None:
                empty += 1
                continue
            if empty:
                row += str(empty)
                empty = 0
            row += piece
        if empty:
            row += str(empty)
        rows.append(row)
    return "/".join(rows)


def _port_kind(device: str, description: str, hwid: str, vid: Any) -> str:
    text = " ".join((device, description, hwid)).lower()
    if "bluetooth" in text or "bthenum" in text or "rfcomm" in text:
        return "bluetooth"
    if vid is not None or "usb" in text:
        return "usb"
    return "other"


def _port_hint(description: str, manufacturer: str, kind: str) -> str:
    text = " ".join((description, manufacturer)).lower()
    if "dgt" in text:
        return "Looks like a DGT board"
    if "certabo" in text:
        return "Looks like a Certabo board"
    if "millennium" in text or "chesslink" in text:
        return "Looks like a Millennium board"
    if kind == "bluetooth":
        return "Bluetooth serial port"
    if kind == "usb":
        return "USB serial port"
    return ""


def list_serial_ports(comports: Callable[[], Iterable[Any]] | None = None) -> list[dict[str, Any]]:
    """Describe the serial ports the operating system offers.

    ``comports`` is injectable for tests; by default pyserial's port listing is
    used, which works on Linux, macOS and Windows.
    """
    if comports is None:
        try:
            from serial.tools import list_ports
        except ImportError:  # pragma: no cover - pyserial is a hard requirement
            return []

        def comports():
            return list_ports.comports(include_links=True)

    ports: list[dict[str, Any]] = []
    for info in comports():
        device = str(getattr(info, "device", "") or "")
        if not device:
            continue
        if any(name in device for name in _MAC_IGNORED_PORTS):
            continue
        description = str(getattr(info, "description", "") or "")
        if description == "n/a":
            description = ""
        hwid = str(getattr(info, "hwid", "") or "")
        if hwid == "n/a":
            hwid = ""
        manufacturer = str(getattr(info, "manufacturer", "") or "")
        vid = getattr(info, "vid", None)
        pid = getattr(info, "pid", None)
        kind = _port_kind(device, description, hwid, vid)
        ports.append(
            {
                "device": device,
                "description": description,
                "manufacturer": manufacturer,
                "hwid": hwid,
                "vid": "%04X" % vid if isinstance(vid, int) else "",
                "pid": "%04X" % pid if isinstance(pid, int) else "",
                "kind": kind,
                "hint": _port_hint(description, manufacturer, kind),
            }
        )

    # macOS lists each port twice: prefer the call-out device (/dev/cu.*).
    devices = {port["device"] for port in ports}
    ports = [
        port
        for port in ports
        if not (port["device"].startswith("/dev/tty.") and "/dev/cu." + port["device"][9:] in devices)
    ]
    kind_order = {"usb": 0, "bluetooth": 1, "other": 2}
    ports.sort(key=lambda port: (kind_order.get(port["kind"], 3), port["device"]))
    return ports


def _open_serial(port: str, timeout: float):
    from serial import Serial

    return Serial(port, baudrate=9600, timeout=timeout, write_timeout=timeout)


def _describe_open_error(port: str, exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if "permission" in lowered or "access is denied" in lowered:
        if platform.system() == "Linux":
            return "No permission to open %s. Add your user to the 'dialout' group and log in again." % port
        return "No permission to open %s." % port
    if "busy" in lowered or "in use" in lowered:
        return "%s is in use by another program. Close other chess software and try again." % port
    if "no such file" in lowered or "could not open port" in lowered or "filenotfound" in lowered:
        return "%s was not found. Check that the board is switched on and connected." % port
    return "Cannot open %s: %s" % (port, text)


def check_port_opens(port: str, timeout: float = 1.0, opener=None) -> dict[str, Any]:
    """Blocking: check that a serial port can be opened."""
    opener = opener or _open_serial
    try:
        serial_port = opener(port, timeout)
    except Exception as exc:  # pyserial raises SerialException/OSError variants
        return {"ok": False, "message": _describe_open_error(port, exc)}
    try:
        serial_port.close()
    except Exception:
        pass
    return {"ok": True, "message": "%s opened successfully." % port}


def _read_exact(serial_port, size: int, deadline: float) -> bytes:
    data = b""
    while len(data) < size and time.monotonic() < deadline:
        chunk = serial_port.read(size - len(data))
        if chunk:
            data += chunk
    return data


def probe_dgt_port(port: str, timeout: float = 4.0, opener=None) -> dict[str, Any]:
    """Blocking: ask a DGT board on ``port`` for its pieces.

    Returns ``{"ok": True, "fen": ...}`` when the board answered with a board
    dump, otherwise ``{"ok": False, "message": ...}``.
    """
    opener = opener or _open_serial
    try:
        serial_port = opener(port, 0.5)
    except Exception as exc:
        return {"ok": False, "message": _describe_open_error(port, exc)}

    deadline = time.monotonic() + timeout
    try:
        serial_port.write(bytes([_DGT_SEND_RESET]))
        serial_port.write(bytes([_DGT_SEND_BRD]))
        next_request = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            header = _read_exact(serial_port, 1, min(deadline, next_request))
            if not header:
                if time.monotonic() >= next_request:
                    # Bluetooth boards may need a second request after connecting.
                    serial_port.write(bytes([_DGT_SEND_BRD]))
                    next_request = time.monotonic() + 1.5
                continue
            message_id = header[0]
            if not message_id & 0x80:
                continue  # resynchronize on the next message header
            length_bytes = _read_exact(serial_port, 2, deadline)
            if len(length_bytes) != 2:
                break
            length = (length_bytes[0] << 7) | length_bytes[1]
            if length < 3:
                continue
            payload = _read_exact(serial_port, length - 3, deadline)
            if message_id == _DGT_MSG_BOARD_DUMP and length == _DGT_SIZE_BOARD_DUMP and len(payload) == 64:
                return {
                    "ok": True,
                    "fen": dgt_board_dump_to_fen(payload),
                    "message": "The DGT board on %s answered." % port,
                }
    except Exception as exc:
        return {"ok": False, "message": "Communication with %s failed: %s" % (port, exc)}
    finally:
        try:
            serial_port.close()
        except Exception:
            pass
    return {
        "ok": False,
        "message": "%s opened, but no DGT board answered. Check the port, cable or Bluetooth pairing." % port,
    }


def read_board_settings(ini_path: str) -> dict[str, str]:
    config = ConfigObj(ini_path, default_encoding="utf8")
    board_type = normalize_board_type(str(config.get("board-type", "dgt"))) or "dgt"
    port = str(config.get("dgt-port", "") or "")
    return {"board_type": board_type, "port": port}


def write_board_settings(ini_path: str, board_type: str, port: str) -> dict[str, Any]:
    """Persist the board choice. Returns whether the stored values changed."""
    config = ConfigObj(ini_path, default_encoding="utf8")
    old_type = normalize_board_type(str(config.get("board-type", "dgt"))) or "dgt"
    old_port = str(config.get("dgt-port", "") or "")
    config["board-type"] = board_type
    if port:
        config["dgt-port"] = port
    elif "dgt-port" in config:
        del config["dgt-port"]
    config.write()
    return {"changed": old_type != board_type or old_port != port}


def restart_hint() -> str:
    """Tell the user how to restart PicoChess on this computer."""
    system_name = platform.system()
    if system_name == "Linux" and os.environ.get("INVOCATION_ID"):
        return "Restart PicoChess to use the new board: sudo systemctl restart picochess"
    if system_name == "Windows":
        return "Restart PicoChess to use the new board: close it and run start-picochess-windows.ps1 again."
    if system_name == "Darwin":
        return "Restart PicoChess to use the new board: stop it and run start-picochess-mac.sh again."
    return "Restart PicoChess to use the new board."
