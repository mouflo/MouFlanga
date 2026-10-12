"""⭐ Favorites : propres à chaque compte, rangés avec la progression."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FavorisTest(unittest.TestCase):
    def setUp(self):
        import app as m
        self.m = m
        self.tmp = Path(tempfile.mkdtemp())
        self.sauve = (m.PROGRESS_FILE, m.MANGA_DIR)
        m.PROGRESS_FILE = self.tmp / "progress.json"
        m.MANGA_DIR = self.tmp / "mangas"
        (m.MANGA_DIR / "Gantz").mkdir(parents=True)
        self.orig_scan = m._scan
        m._scan = lambda: {"Gantz": []}
        m.app.config["TESTING"] = True

    def tearDown(self):
        self.m.PROGRESS_FILE, self.m.MANGA_DIR = self.sauve
        self.m._scan = self.orig_scan

    def test_cocher_puis_decocher(self):
        m = self.m
        with m.app.test_request_context("/api/favori", method="POST", json={"series": "Gantz", "favori": True}):
            r = m.api_favori()
        self.assertTrue(r.get_json()["ok"])
        self.assertTrue(json.loads(m.PROGRESS_FILE.read_text())["Gantz"]["favori"])
        with m.app.test_request_context("/api/favori", method="POST", json={"series": "Gantz", "favori": False}):
            m.api_favori()
        self.assertNotIn("Gantz", json.loads(m.PROGRESS_FILE.read_text()))

    def test_serie_inconnue(self):
        m = self.m
        with m.app.test_request_context("/api/favori", method="POST", json={"series": "Nope", "favori": True}):
            r = m.api_favori()
        self.assertEqual(r[1], 404)


if __name__ == "__main__":
    unittest.main()
