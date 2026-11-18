import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from tornado.testing import AsyncHTTPTestCase
import tornado.web

import web_setup
from dgt.util import EBoard as EBoardType


START_DUMP = (
    [0x08, 0x09, 0x0A, 0x0C, 0x0B, 0x0A, 0x09, 0x08]
    + [0x07] * 8
    + [0x00] * 32
    + [0x01] * 8
    + [0x02, 0x03, 0x04, 0x06, 0x05, 0x04, 0x03, 0x02]
)
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"


class FakeDgtSerial:
    """Answers DGT_SEND_BRD with a board dump, after some unrelated traffic."""

    def __init__(self, dump=START_DUMP, answer=True):
        self.dump = dump
        self.answer = answer
        self.buffer = bytearray()
        self.written = []
        self.closed = False

    def write(self, data):
        self.written.append(bytes(data))
        if self.answer and data == bytes([0x42]):
            # an unrelated serial-number message first, then the board dump
            self.buffer += bytes([0x91, 0x00, 0x08]) + b"12345"
            self.buffer += bytes([0x86, 0x00, 0x43]) + bytes(self.dump)

    def read(self, size):
        chunk = bytes(self.buffer[:size])
        del self.buffer[:size]
        return chunk

    def close(self):
        self.closed = True


class TestDgtBoardDump(unittest.TestCase):
    def test_start_position(self):
        self.assertEqual(web_setup.dgt_board_dump_to_fen(START_DUMP), START_FEN)

    def test_empty_board_and_special_pieces(self):
        dump = [0x00] * 64
        dump[0] = 0x0D  # draughts/special piece codes are ignored like dgt/board.py
        dump[63] = 0x05
        self.assertEqual(web_setup.dgt_board_dump_to_fen(dump), "8/8/8/8/8/8/8/7K")

    def test_wrong_length(self):
        with self.assertRaises(ValueError):
            web_setup.dgt_board_dump_to_fen([0] * 10)


class TestProbe(unittest.TestCase):
    def test_probe_reads_board_dump(self):
        fake = FakeDgtSerial()
        result = web_setup.probe_dgt_port("COM7", timeout=1.0, opener=lambda port, timeout: fake)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["fen"], START_FEN)
        self.assertIn(bytes([0x42]), fake.written)
        self.assertTrue(fake.closed)

    def test_probe_without_answer(self):
        fake = FakeDgtSerial(answer=False)
        result = web_setup.probe_dgt_port("COM7", timeout=0.3, opener=lambda port, timeout: fake)
        self.assertFalse(result["ok"])
        self.assertIn("no DGT board answered", result["message"])
        self.assertTrue(fake.closed)

    def test_probe_open_errors_are_explained(self):
        def opener(port, timeout):
            raise OSError("[Errno 13] Permission denied: '/dev/ttyACM0'")

        result = web_setup.probe_dgt_port("/dev/ttyACM0", opener=opener)
        self.assertFalse(result["ok"])
        self.assertIn("No permission", result["message"])

    def test_check_port_opens(self):
        fake = FakeDgtSerial()
        self.assertTrue(web_setup.check_port_opens("COM3", opener=lambda port, timeout: fake)["ok"])
        self.assertTrue(fake.closed)


class TestPorts(unittest.TestCase):
    def test_list_serial_ports_classifies_and_deduplicates(self):
        ports = [
            SimpleNamespace(device="/dev/tty.DGT_BT", description="n/a", hwid="n/a", manufacturer=None,
                            vid=None, pid=None),
            SimpleNamespace(device="/dev/cu.DGT_BT", description="n/a", hwid="n/a", manufacturer=None,
                            vid=None, pid=None),
            SimpleNamespace(device="/dev/cu.Bluetooth-Incoming-Port", description="n/a", hwid="n/a",
                            manufacturer=None, vid=None, pid=None),
            SimpleNamespace(device="COM7", description="Standard Serial over Bluetooth link (COM7)",
                            hwid="BTHENUM\\{00001101}", manufacturer="Microsoft", vid=None, pid=None),
            SimpleNamespace(device="/dev/ttyACM0", description="DGT e-Board", hwid="USB VID:PID=045B:8111",
                            manufacturer="DGT", vid=0x045B, pid=0x8111),
        ]
        result = web_setup.list_serial_ports(lambda: ports)
        devices = [port["device"] for port in result]
        self.assertEqual(devices, ["/dev/ttyACM0", "COM7", "/dev/cu.DGT_BT"])
        self.assertEqual(result[0]["kind"], "usb")
        self.assertEqual(result[0]["vid"], "045B")
        self.assertEqual(result[0]["hint"], "Looks like a DGT board")
        self.assertEqual(result[1]["kind"], "bluetooth")

    def test_validate_port(self):
        self.assertEqual(web_setup.validate_port("  COM7 "), "COM7")
        self.assertEqual(web_setup.validate_port(""), "")
        self.assertIsNone(web_setup.validate_port("COM7\nengine = x"))
        self.assertIsNone(web_setup.validate_port("x" * 300))

    def test_normalize_board_type(self):
        self.assertEqual(web_setup.normalize_board_type("DGT"), "dgt")
        self.assertEqual(web_setup.normalize_board_type("none"), "noeboard")
        self.assertIsNone(web_setup.normalize_board_type("unknown"))

    def test_catalogue_matches_eboard_enum(self):
        self.assertEqual(web_setup.BOARD_TYPE_IDS, {member.name.lower() for member in EBoardType})


class TestBoardSettingsFile(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".ini")
        with os.fdopen(handle, "w", encoding="utf-8") as ini:
            ini.write("# my comment\nboard-type = noeboard\nengine = engines/x/a-stockf\n")

    def tearDown(self):
        os.unlink(self.path)

    def test_write_and_read(self):
        result = web_setup.write_board_settings(self.path, "dgt", "COM7")
        self.assertTrue(result["changed"])
        self.assertEqual(web_setup.read_board_settings(self.path), {"board_type": "dgt", "port": "COM7"})
        with open(self.path, encoding="utf-8") as ini:
            text = ini.read()
        self.assertIn("# my comment", text)
        self.assertIn("engine = engines/x/a-stockf", text)

    def test_empty_port_removes_setting(self):
        web_setup.write_board_settings(self.path, "dgt", "COM7")
        result = web_setup.write_board_settings(self.path, "dgt", "")
        self.assertTrue(result["changed"])
        self.assertEqual(web_setup.read_board_settings(self.path)["port"], "")
        self.assertFalse(web_setup.write_board_settings(self.path, "dgt", "")["changed"])


class TestSetupHandlers(AsyncHTTPTestCase):
    def get_app(self):
        import server

        handle, self.ini_path = tempfile.mkstemp(suffix=".ini")
        with os.fdopen(handle, "w", encoding="utf-8") as ini:
            ini.write("board-type = noeboard\n")
        self.shared = {"eboard_status": {"event": "Status", "eboard": "connected"}, "dgt_fen": START_FEN}
        self.patches = [
            patch.object(server, "_get_ini_path", return_value=self.ini_path),
            patch.object(server, "_is_local_request", return_value=True),
        ]
        for item in self.patches:
            item.start()
        shared = dict(shared=self.shared)
        return tornado.web.Application(
            [
                (r"/setup/state", server.SetupStateHandler, shared),
                (r"/setup/probe", server.SetupProbeHandler, shared),
                (r"/setup/board", server.SetupBoardHandler, shared),
            ]
        )

    def tearDown(self):
        for item in self.patches:
            item.stop()
        os.unlink(self.ini_path)
        super().tearDown()

    def post(self, url, **params):
        return self.fetch(url, method="POST", body=urlencode(params))

    def test_state_reports_catalogue_and_configuration(self):
        response = self.fetch("/setup/state")
        self.assertEqual(response.code, 200)
        data = json.loads(response.body)
        self.assertEqual(data["configured"], {"board_type": "noeboard", "port": ""})
        self.assertIn("dgt", [board["id"] for board in data["board_types"]])

    def test_save_board_writes_ini(self):
        response = self.post("/setup/board", type="dgt", port="COM7")
        data = json.loads(response.body)
        self.assertTrue(data["ok"])
        self.assertTrue(data["restart_required"])
        self.assertEqual(web_setup.read_board_settings(self.ini_path), {"board_type": "dgt", "port": "COM7"})

    def test_returning_to_startup_board_needs_no_restart(self):
        self.shared["startup_board"] = {"board_type": "noeboard", "port": ""}
        self.assertTrue(json.loads(self.post("/setup/board", type="dgt", port="COM7").body)["restart_required"])
        data = json.loads(self.post("/setup/board", type="noeboard", port="").body)
        self.assertFalse(data["restart_required"])

    def test_save_board_rejects_bad_input(self):
        self.assertEqual(self.post("/setup/board", type="bogus", port="").code, 400)
        self.assertEqual(self.post("/setup/board", type="citrine", port="").code, 400)

    def test_ble_board_does_not_store_port(self):
        self.post("/setup/board", type="chessnut", port="COM7")
        self.assertEqual(web_setup.read_board_settings(self.ini_path)["port"], "")

    def test_probe_running_board_uses_live_state(self):
        with patch("server.ModeInfo.get_eboard_type", return_value=EBoardType.DGT), \
                patch.object(web_setup, "probe_dgt_port") as probe:
            data = json.loads(self.post("/setup/probe", type="dgt", port="COM7").body)
        probe.assert_not_called()
        self.assertTrue(data["live"])
        self.assertEqual(data["fen"], START_FEN)

    def test_probe_other_board_opens_port(self):
        with patch("server.ModeInfo.get_eboard_type", return_value=EBoardType.NOEBOARD), \
                patch.object(web_setup, "probe_dgt_port", return_value={"ok": True, "fen": START_FEN}) as probe:
            data = json.loads(self.post("/setup/probe", type="dgt", port="COM7").body)
        probe.assert_called_once_with("COM7")
        self.assertEqual(data["fen"], START_FEN)


if __name__ == "__main__":
    unittest.main()
