"""🎵 Générique choisi à la main dans la liste d'AnimeThemes : posé, retenu, jamais remplacé par la recherche automatique."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

THEMES = [{"slug": "OP1", "type": "OP", "sequence": 1, "titre": "Mune ga Dokidoki", "episodes": "1-30", "lien": "http://x/op1.ogg"},
          {"slug": "OP5", "type": "OP", "sequence": 5, "titre": "Truth", "episodes": "124-142", "lien": "http://x/op5.ogg"}]


class ChoixGeneriqueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root = t / "mangas"
        (self.root / "Conan" / "Tome 01").mkdir(parents=True)
        (self.root / "Conan" / "Tome 01" / "Conan - Tome 01.cbz").write_bytes(b"x")
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        self.A = A
        A.MANGA_DIR = self.root
        A.generiques._ETAT["fichier"] = t / "generiques.json"
        self.poses = []
        self.p = [mock.patch.object(A.generiques, "telecharger", side_effect=self._poser),
                  mock.patch.object(A.generiques, "themes_de_l_anime", return_value=THEMES),
                  mock.patch.object(A, "_anime_pour_generique", return_value=(235, "Detective Conan")),
                  mock.patch.object(A, "_scan", return_value={"Conan": {}})]
        for x in self.p:
            x.start()
        import auth
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        self.client = A.app.test_client()
        with self.client.session_transaction() as sess:
            sess["u"], sess["f"] = "test", auth._fingerprint()
        self.role = mock.patch.object(A.auth, "role", return_value="admin")
        self.role.start()

    def _poser(self, lien, cible):
        self.poses.append(lien)
        Path(cible).write_bytes(lien.encode())

    def tearDown(self):
        self.role.stop()
        for x in self.p:
            x.stop()
        self.tmp.cleanup()

    def son(self):
        return self.root / "Conan" / self.A.generiques.FICHIER_SON

    def test_liste_et_choix(self):
        r = self.client.get("/api/generique/liste?id=Conan").get_json()
        self.assertEqual([t["slug"] for t in r["themes"]], ["OP1", "OP5"])
        r = self.client.post("/api/generique/choisir", json={"series": "Conan", "slug": "OP5"}).get_json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.son().read_bytes(), b"http://x/op5.ogg")
        r = self.client.get("/api/generique/liste?id=Conan").get_json()
        self.assertEqual((r["actuel"], r["manuel"]), ("OP5", True))

    def test_choix_jamais_remplace_par_l_automatique(self):
        self.client.post("/api/generique/choisir", json={"series": "Conan", "slug": "OP5"})
        g = self.A.generiques
        self.assertEqual(g.pour_serie("Conan", self.root / "Conan", 1, forcer=True), "deja")
        with mock.patch.object(g.threading, "Thread") as th:
            g.tout(["Conan"], self.root, lambda n: 1, lambda n: False, lambda t: None, forcer=True)
        self.assertEqual(g._ETAT["total"], 0)
        self.assertEqual(self.son().read_bytes(), b"http://x/op5.ogg")

    def test_aucun_generique(self):
        self.son().write_bytes(b"op1")
        r = self.client.post("/api/generique/choisir", json={"series": "Conan", "slug": "aucun"}).get_json()
        self.assertTrue(r["ok"], r)
        self.assertFalse(self.son().exists())
        self.assertEqual(self.client.get("/api/generique/liste?id=Conan").get_json()["actuel"], "aucun")

    def test_lecteur_refuse(self):
        with mock.patch.object(self.A.auth, "role", return_value="lecteur"):
            r = self.client.post("/api/generique/choisir", json={"series": "Conan", "slug": "OP5"})
        self.assertNotEqual(r.status_code, 200)
        self.assertFalse(self.son().exists())


if __name__ == "__main__":
    unittest.main()
