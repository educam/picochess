import unittest

import web_setup
from tools import dgt_simulator as sim


START = sim.START_FEN


def field_updates(data: bytes) -> list[tuple[str, int]]:
    """Decode a stream of DGT field-update messages into (square, piece code)."""
    out = []
    while data:
        assert data[0] == sim.MSG_FIELD_UPDATE, data
        out.append((sim.square_name(data[3]), data[4]))
        data = data[5:]
    return out


class TestEncoding(unittest.TestCase):
    def test_squares(self):
        self.assertEqual(0, sim.square_index("a8"))
        self.assertEqual(63, sim.square_index("h1"))
        self.assertEqual(36, sim.square_index("e4"))
        self.assertEqual("e4", sim.square_name(36))
        with self.assertRaises(ValueError):
            sim.square_index("i9")

    def test_board_dump_is_read_like_the_driver_reads_it(self):
        board = sim.SimulatedBoard()
        dump = board.board_dump()
        self.assertEqual(bytes([0x86, 0x00, 0x43]), dump[:3])
        self.assertEqual(START, web_setup.dgt_board_dump_to_fen(dump[3:]))

    def test_fen_round_trip(self):
        fen = "r3k2r/8/8/3pP3/8/8/8/R3K2R"
        self.assertEqual(fen, sim.SimulatedBoard(fen).fen())
        with self.assertRaises(ValueError):
            sim.SimulatedBoard("8/8/8")


class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.board = sim.SimulatedBoard()

    def test_driver_handshake(self):
        reply, used = self.board.handle(bytes([sim.CMD_SEND_UPDATE_NICE, sim.CMD_SEND_VERSION]))
        self.assertEqual(2, used)
        self.assertEqual(bytes([0x93, 0x00, 0x05, 3, 1]), reply)
        self.assertTrue(self.board.update_mode)

        reply, _ = self.board.handle(bytes([sim.CMD_SEND_BRD, sim.CMD_RETURN_SERIALNR]))
        self.assertEqual(self.board.board_dump() + bytes([0x91, 0x00, 0x08]) + b"SIM01", reply)

    def test_clock_messages_are_consumed_without_answer(self):
        clock = bytes([sim.CMD_CLOCK_MESSAGE, 0x03, 0x03, 0x09, 0x00])
        reply, used = self.board.handle(clock + bytes([sim.CMD_SEND_VERSION]))
        self.assertEqual(len(clock) + 1, used)
        self.assertEqual(bytes([0x93, 0x00, 0x05, 3, 1]), reply)

    def test_partial_clock_message_waits_for_more_bytes(self):
        reply, used = self.board.handle(bytes([sim.CMD_CLOCK_MESSAGE, 0x03, 0x03]))
        self.assertEqual((b"", 0), (reply, used))

    def test_no_field_updates_before_update_mode(self):
        self.assertEqual(b"", self.board.lift("e2"))


class TestPieceHandling(unittest.TestCase):
    def setUp(self):
        self.board = sim.SimulatedBoard()
        self.board.handle(bytes([sim.CMD_SEND_UPDATE_NICE]))

    def test_lift_and_place(self):
        self.assertEqual([("e2", 0)], field_updates(self.board.lift("e2")))
        self.assertEqual(["P"], self.board.in_hand)
        self.assertEqual([("e4", 1)], field_updates(self.board.place("e4")))
        self.assertEqual("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR", self.board.fen())

    def test_capture_removes_the_captured_piece_first(self):
        self.board.set_fen("4k3/8/8/3p4/4P3/8/8/4K3")
        updates = field_updates(self.board.move("e4d5"))
        self.assertEqual([("d5", 0), ("e4", 0), ("d5", 1)], updates)
        self.assertEqual("4k3/8/8/3P4/8/8/8/4K3", self.board.fen())
        self.assertEqual([], self.board.in_hand)

    def test_castling_moves_the_rook(self):
        self.board.set_fen("4k3/8/8/8/8/8/8/R3K2R")
        self.board.move("e1g1")
        self.assertEqual("4k3/8/8/8/8/8/8/R4RK1", self.board.fen())
        self.board.set_fen("r3k3/8/8/8/8/8/8/4K3")
        self.board.move("e8c8")
        self.assertEqual("2kr4/8/8/8/8/8/8/4K3", self.board.fen())
        self.board.set_fen("4k3/8/8/8/8/8/8/4K3")
        self.board.move("e1g1")  # no rook: only the king moves
        self.assertEqual("4k3/8/8/8/8/8/8/6K1", self.board.fen())

    def test_en_passant_and_promotion(self):
        self.board.set_fen("4k3/8/8/3pP3/8/8/8/4K3")
        self.board.move("e5d6")
        self.assertEqual("4k3/8/3P4/8/8/8/8/4K3", self.board.fen())
        self.board.set_fen("4k3/P7/8/8/8/8/8/4K3")
        self.board.move("a7a8q")
        self.assertEqual("Q3k3/8/8/8/8/8/8/4K3", self.board.fen())

    def test_changes_to_sends_only_differences(self):
        target = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR"
        updates = field_updates(self.board.changes_to(target))
        self.assertEqual({"e2", "e7", "e4", "e5"}, {square for square, _ in updates})
        self.assertEqual(target, self.board.fen())

    def test_errors(self):
        with self.assertRaises(ValueError):
            self.board.lift("e4")
        with self.assertRaises(ValueError):
            self.board.place("e4")
        with self.assertRaises(ValueError):
            self.board.move("e2")


class TestProbeAgainstSimulator(unittest.TestCase):
    """The setup wizard's DGT probe reads the simulated board."""

    def test_probe(self):
        board = sim.SimulatedBoard("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR")

        class Port:
            def __init__(self):
                self.buffer = b""

            def write(self, data):
                reply, _ = board.handle(bytes(data))
                self.buffer += reply

            def read(self, size):
                chunk, self.buffer = self.buffer[:size], self.buffer[size:]
                return chunk

            def close(self):
                pass

        result = web_setup.probe_dgt_port("/dev/sim", timeout=1.0, opener=lambda port, timeout: Port())
        self.assertTrue(result["ok"], result)
        self.assertEqual(board.fen(), result["fen"])


if __name__ == "__main__":
    unittest.main()
