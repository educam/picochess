import json
import os
import tempfile
import unittest
from unittest.mock import patch

import tornado.web
from tornado.testing import AsyncHTTPTestCase

import settings_schema


class TestSettingsSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = settings_schema.build_schema()
        cls.settings = cls.schema["settings"]

    def test_every_listed_key_exists(self):
        listed = [key for _, _, _, keys in settings_schema.SECTIONS for key in keys]
        self.assertEqual(len(listed), len(set(listed)), "a key is listed in two sections")
        for key in listed:
            self.assertIn(key, self.settings, key)

    def test_every_parser_option_has_a_section(self):
        other = [key for key, entry in self.settings.items() if entry["section"] == "other"]
        self.assertEqual([], other)

    def test_parser_metadata_is_used(self):
        log_level = self.settings["log-level"]
        self.assertEqual("choice", log_level["kind"])
        self.assertIn("debug", log_level["choices"])
        self.assertEqual("warning", log_level["default"])
        self.assertEqual("logging level", log_level["help"])

        self.assertEqual("int", self.settings["smtp-port"]["kind"])
        self.assertEqual("float", self.settings["online-decrement"]["kind"])
        self.assertEqual("bool", self.settings["web-speech-remote"]["kind"])
        self.assertEqual("true", self.settings["web-speech-remote"]["default"])
        self.assertEqual("flag", self.settings["premove"]["kind"])
        self.assertEqual("false", self.settings["premove"]["default"])
        self.assertIn("100%", self.settings["volume-voice"]["help"])  # "%%" is unescaped

    def test_presentation_data(self):
        self.assertEqual("now", self.settings["web-audio-backend-remote"]["applies"])
        self.assertEqual("reload", self.settings["pieces"]["applies"])
        self.assertEqual("restart", self.settings["engine"]["applies"])
        self.assertTrue(self.settings["smtp-pass"]["secret"])
        self.assertFalse(self.settings["engine"]["secret"])
        self.assertEqual("board", self.settings["board-type"]["section"])
        self.assertEqual("choice", self.settings["board-type"]["kind"])
        self.assertFalse(self.settings["board-type"]["strict"])
        self.assertEqual("network", self.settings["hotspot-ssid"]["section"])

    def test_sections_keep_display_order(self):
        board = next(section for section in self.schema["sections"] if section["id"] == "board")
        self.assertEqual(["board-type", "dgt-port"], board["keys"][:2])

    def test_no_internal_options(self):
        self.assertNotIn("help", self.settings)
        self.assertNotIn("version", self.settings)

    def test_validate_value(self):
        validate = settings_schema.validate_value
        self.assertIsNone(validate(self.settings["log-level"], "info"))
        self.assertIn("Choose one of", validate(self.settings["log-level"], "loud"))
        self.assertIsNone(validate(self.settings["depth"], "12"))
        self.assertIsNotNone(validate(self.settings["depth"], "120"))
        self.assertIsNone(validate(self.settings["smtp-port"], "587"))
        self.assertEqual("Use a whole number.", validate(self.settings["smtp-port"], "abc"))
        self.assertEqual("Use a number.", validate(self.settings["online-decrement"], "x"))
        self.assertIsNone(validate(self.settings["premove"], "False"))
        self.assertEqual("Use true or false.", validate(self.settings["premove"], "maybe"))
        self.assertIsNone(validate(self.settings["board-type"], "something-new"))  # not strict
        self.assertIsNone(validate(self.settings["engine"], "anything"))

    def test_validate_entries_ignores_disabled_and_unknown(self):
        errors = settings_schema.validate_entries(
            self.schema,
            [
                {"key": "smtp-port", "value": "abc", "enabled": False},
                {"key": "my-own-key", "value": "abc", "enabled": True},
                {"key": "log-level", "value": "loud", "enabled": True},
            ],
        )
        self.assertEqual(["log-level"], list(errors))

    def test_example_ini_files_are_valid(self):
        from pathlib import Path

        root = Path(__file__).parents[1]
        for example in sorted(root.glob("picochess.ini.example-*")):
            with self.subTest(example=example.name):
                from server import _parse_ini_entries

                lines = example.read_text(encoding="utf-8").splitlines(keepends=True)
                entries = list(_parse_ini_entries(lines).values())
                self.assertEqual({}, settings_schema.validate_entries(self.schema, entries))


class TestSettingsHandlers(AsyncHTTPTestCase):
    def get_app(self):
        import server

        handle, self.ini_path = tempfile.mkstemp(suffix=".ini")
        with os.fdopen(handle, "w", encoding="utf-8") as ini:
            ini.write("# logging level\nlog-level = warning\nsmtp-port = 587\n")
        self.patches = [
            patch.object(server, "_get_ini_path", return_value=self.ini_path),
            patch.object(server, "_is_local_request", return_value=True),
        ]
        for item in self.patches:
            item.start()
        return tornado.web.Application(
            [
                (r"/settings/schema", server.SettingsSchemaHandler),
                (r"/settings/save", server.SettingsSaveHandler, dict(shared={})),
            ]
        )

    def tearDown(self):
        for item in self.patches:
            item.stop()
        os.unlink(self.ini_path)
        super().tearDown()

    def save(self, entries):
        return self.fetch("/settings/save", method="POST", body=json.dumps({"entries": entries}))

    def read_ini(self):
        with open(self.ini_path, encoding="utf-8") as ini:
            return ini.read()

    def test_schema_endpoint(self):
        data = json.loads(self.fetch("/settings/schema").body)
        self.assertIn("board", [section["id"] for section in data["sections"]])
        self.assertEqual("choice", data["settings"]["log-level"]["kind"])

    def test_invalid_value_is_rejected_and_file_unchanged(self):
        before = self.read_ini()
        response = self.save([{"key": "smtp-port", "value": "abc", "enabled": True}])
        self.assertEqual(400, response.code)
        self.assertEqual({"smtp-port": "Use a whole number."}, json.loads(response.body)["errors"])
        self.assertEqual(before, self.read_ini())

    def test_valid_values_are_saved(self):
        response = self.save(
            [
                {"key": "log-level", "value": "info", "enabled": True},
                {"key": "depth", "value": "12", "enabled": True},
            ]
        )
        self.assertEqual(200, response.code)
        text = self.read_ini()
        self.assertIn("log-level = info", text)
        self.assertIn("depth = 12", text)
        self.assertIn("# logging level", text)


if __name__ == "__main__":
    unittest.main()
