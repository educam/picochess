import os
import tempfile
import unittest
from unittest.mock import patch

import utilities


class TestInstallPaths(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.home, "engines", "x86_64"))
        open(os.path.join(self.home, "engines", "x86_64", "a-stockf"), "w").close()
        self.patch = patch.object(utilities, "PICOCHESS_HOME", self.home)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_picochess_path(self):
        self.assertEqual(os.path.join(self.home, "games", "x.pgn"), utilities.picochess_path("games", "x.pgn"))

    def test_standard_install_path_maps_to_checkout(self):
        self.assertEqual(
            os.path.join(self.home, "engines", "x86_64", "a-stockf"),
            utilities.resolve_install_path("/opt/picochess/engines/x86_64/a-stockf"),
        )

    def test_missing_file_keeps_original_path(self):
        path = "/opt/picochess/engines/x86_64/b-lc0"
        self.assertEqual(path, utilities.resolve_install_path(path))

    def test_other_paths_are_unchanged(self):
        for path in ("engines/x86_64/a-stockf", "/usr/games/stockfish", "C:\\engines\\sf.exe", "", None):
            self.assertEqual(path, utilities.resolve_install_path(path))

    def test_checkout_in_standard_place_is_unchanged(self):
        with patch.object(utilities, "PICOCHESS_HOME", utilities.STANDARD_INSTALL_HOME):
            path = "/opt/picochess/engines/x86_64/a-stockf"
            self.assertEqual(path, utilities.resolve_install_path(path))


if __name__ == "__main__":
    unittest.main()
