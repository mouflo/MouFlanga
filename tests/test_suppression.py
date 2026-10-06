"""Suppression (mise à la corbeille) de chapitres et de séries depuis la bibliothèque."""
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _cbz(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("1.jpg", b"x")


class SuppressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root = t / "mangas"
        _cbz(self.root / "Serie" / "001.cbz")
        _cbz(self.root / "Serie" / "002.cbz")
        _cbz(self.root / "Autre" / "001.cbz")
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        self.A = A
        A.MANGA_DIR = self.root          # data/secrets.env du serveur peut imposer un autre dossier
        A.PROGRESS_FILE = t / "progress.json"
        A.PROGRESS_FILE.write_text(json.dumps({"Serie": {"current": "Serie/001.cbz", "page": 5,
                                                         "read": ["Serie/001.cbz", "Serie/002.cbz"]},
                                               "Autre": {"read": ["Autre/001.cbz"]}}))
        # Session connectée, comme après l'écran de connexion
        self._env = {k: os.environ.get(k) for k in ("APP_USER", "APP_PASSWORD_HASH")}
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        self.client = A.app.test_client()
        import auth
        with self.client.session_transaction() as sess:
            sess["u"], sess["f"] = "test", auth._fingerprint()
        self.jour = datetime.now().strftime("%Y-%m-%d")

    def tearDown(self):
        self.A.japscan_scraper.download_jobs.clear()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _post(self, body):
        return self.client.post("/api/delete", json=body)

    def test_un_chapitre_va_a_la_corbeille(self):
        r = self._post({"series": "Serie", "path": "Serie/001.cbz"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse((self.root / "Serie" / "001.cbz").exists())
        self.assertTrue((self.root / ".corbeille" / self.jour / "Serie" / "001.cbz").is_file())
        self.assertTrue((self.root / "Serie" / "002.cbz").is_file())
        p = json.loads(self.A.PROGRESS_FILE.read_text())["Serie"]
        self.assertEqual(p["read"], ["Serie/002.cbz"])
        self.assertNotIn("current", p)
        # La corbeille n'apparaît pas dans la bibliothèque
        self.assertNotIn(".corbeille", self.A._scan())

    def test_toute_la_serie(self):
        r = self._post({"series": "Serie", "all": True})
        self.assertEqual(r.json["supprimes"], 2)
        self.assertFalse((self.root / "Serie").exists())
        self.assertTrue((self.root / ".corbeille" / self.jour / "Serie" / "002.cbz").is_file())
        data = json.loads(self.A.PROGRESS_FILE.read_text())
        self.assertNotIn("Serie", data)
        self.assertIn("Autre", data)

    def test_meme_nom_deux_fois_le_meme_jour(self):
        self._post({"series": "Serie", "path": "Serie/001.cbz"})
        self._post({"series": "Serie", "all": True})
        self.assertEqual(len(list((self.root / ".corbeille" / self.jour).iterdir())), 2)

    def test_chemins_refuses(self):
        for body in ({"series": "Serie", "path": "../Autre/001.cbz"},
                     {"series": "Serie", "path": "Autre/001.cbz"},
                     {"series": "..", "all": True},
                     {"series": ".corbeille", "all": True}):
            self.assertEqual(self._post(body).status_code, 404, body)
        self.assertTrue((self.root / "Autre" / "001.cbz").is_file())

    def test_refus_pendant_un_telechargement(self):
        self.A.japscan_scraper.download_jobs["x"] = {"status": "running", "title": "Serie"}
        self.assertEqual(self._post({"series": "Serie", "all": True}).status_code, 409)
        self.assertTrue((self.root / "Serie" / "001.cbz").is_file())

    def test_vieille_corbeille_videe(self):
        vieux = self.root / ".corbeille" / (datetime.now() - timedelta(days=31)).strftime("%Y-%m-%d")
        _cbz(vieux / "X" / "1.cbz")
        self._post({"series": "Serie", "path": "Serie/001.cbz"})
        self.assertFalse(vieux.exists())
        self.assertTrue((self.root / ".corbeille" / self.jour).is_dir())


if __name__ == "__main__":
    unittest.main()
