"""Fiche d'une série ajoutée (➕) mais encore sans tomes : s'ouvre avec ses infos, accepte un poster."""
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class SerieVideTest(unittest.TestCase):
    def setUp(self):
        import app as m
        import suivi
        self.m, self.suivi = m, suivi
        self.tmp = Path(tempfile.mkdtemp())
        self.sauve = (m.MANGA_DIR, m.PROGRESS_FILE, suivi._ETAT["fichier"])
        m.MANGA_DIR = self.tmp / "mangas"
        m.MANGA_DIR.mkdir()
        m.PROGRESS_FILE = self.tmp / "progress.json"
        suivi._ETAT["fichier"] = self.tmp / "suivies.json"
        suivi.ajouter("Omniscient Reader", {"titre": "Omniscient Reader", "annee": 2020, "auteur": "Sing Shong",
                                            "couverture": "https://exemple.org/c.jpg", "source": "AniList"})

    def tearDown(self):
        self.m.MANGA_DIR, self.m.PROGRESS_FILE, self.suivi._ETAT["fichier"] = self.sauve

    def test_fiche_ouverte_avec_les_infos(self):
        m = self.m
        with m.app.test_request_context("/api/series?id=Omniscient Reader"):
            d = m.api_series().get_json()
        self.assertTrue(d["recherchee"])
        self.assertEqual(d["chapters"], [])
        self.assertEqual(d["cover_externe"], "https://exemple.org/c.jpg")
        self.assertIn("Sing Shong", d["compte"])

    def test_serie_inconnue_reste_introuvable(self):
        m = self.m
        with m.app.test_request_context("/api/series?id=Inconnue"):
            r = m.api_series()
        self.assertEqual(r[1], 404)

    def test_poster_enregistre_et_servi(self):
        m = self.m
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (40, 60), (200, 30, 30)).save(buf, "PNG")
        buf.seek(0)

        class Envoi:
            def read(self, n):
                return buf.read(n)
        rep, code = m._enregistrer_couverture("Omniscient Reader", Envoi())
        self.assertEqual(code, 200)
        self.assertTrue((m.MANGA_DIR / "Omniscient Reader" / "cover.jpg").is_file())
        with m.app.test_request_context("/api/cover?id=Omniscient Reader"):
            r = m.api_cover()
        self.assertEqual(getattr(r, "status_code", 200), 200)


if __name__ == "__main__":
    unittest.main()
