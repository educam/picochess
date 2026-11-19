import unittest
from pathlib import Path


class TestWebEngineSearch(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parents[1]
        self.template = (root / "web/picoweb/templates/clock.html").read_text(encoding="utf-8")
        self.css = (root / "web/picoweb/static/css/base.css").read_text(encoding="utf-8")

    def test_engine_menu_offers_search(self):
        self.assertIn("labelKey: 'search'", self.template)
        self.assertIn("navigateTo(openEngineSearch)", self.template)
        self.assertIn('id="ovl-engine-search"', self.template)
        self.assertIn(".pico-engine-search", self.css)

    def test_search_matches_all_catalogs_and_reuses_level_picker(self):
        self.assertIn("var matches = _engAllData.filter(", self.template)
        self.assertIn("populateLevels(eng.file, eng.levels);", self.template)

    def test_other_engine_views_hide_the_search_box(self):
        # showEngine, openEngineCat, showEngineInfo and showEngineSort
        self.assertEqual(4, self.template.count("_setEngineSearchVisible(false);"))


if __name__ == "__main__":
    unittest.main()
