"""Univers : rattacher une série à un univers avec son rang de lecture, la détacher, refuser les mauvais caractères."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class UniversTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root = t / "mangas"
        (self.root / "Immortal Regis" / "Tome 01").mkdir(parents=True)
        (self.root / "Immortal Regis" / "Tome 01" / "x.cbz").write_bytes(b"x")
        (self.root / "Cavalier" / "Tome 01").mkdir(parents=True)
        (self.root / "Cavalier" / "Tome 01" / "y.cbz").write_bytes(b"y")
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        self.A = A
        A.MANGA_DIR = self.root
        A.UNIVERS_FICHIER = t / "univers.json"
        import auth
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        self.client = A.app.test_client()
        with self.client.session_transaction() as sess:
            sess["u"], sess["f"] = "test", auth._fingerprint()

    def tearDown(self):
        self.tmp.cleanup()

    def poster(self, corps):
        return self.client.post("/api/univers", json=corps)

    def test_rattacher_puis_lister(self):
        self.assertTrue(self.poster({"series": "Immortal Regis", "univers": "Chaos Chronicle", "ordre": "1", "description": "Les bases."}).get_json()["ok"])
        self.poster({"series": "Cavalier", "univers": "Chaos Chronicle", "ordre": "2"})
        groupes = self.client.get("/api/univers").get_json()["univers"]
        self.assertEqual([s["id"] for s in groupes[0]["series"]], ["Immortal Regis", "Cavalier"])
        self.assertEqual(groupes[0]["description"], "Les bases.")

    def test_detacher(self):
        self.poster({"series": "Cavalier", "univers": "X", "ordre": "1"})
        self.poster({"series": "Cavalier", "univers": ""})
        self.assertEqual(self.client.get("/api/univers").get_json()["univers"], [])

    def test_refus(self):
        rep = self.poster({"series": "Cavalier", "univers": 'Mauvais "nom"'})
        self.assertEqual(rep.status_code, 400)
        rep = self.poster({"series": "Cavalier", "univers": "X", "ordre": "deux"})
        self.assertEqual(rep.status_code, 400)


if __name__ == "__main__":
    unittest.main()
