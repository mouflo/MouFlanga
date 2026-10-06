"""Tests hors-ligne du scraper et de ses routes (sans Internet ni navigateur)."""
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import japscan_scraper as js


class NomSurTest(unittest.TestCase):
    def test_pas_de_chemin(self):
        self.assertNotIn("/", js.nom_sur("../../etc/passwd"))
        self.assertNotIn("..", js.nom_sur("../../etc/passwd"))

    def test_titre_vide(self):
        self.assertEqual(js.nom_sur("   "), "sans-titre")

    def test_titre_normal(self):
        self.assertEqual(js.nom_sur("Dandadan 247"), "Dandadan 247")


class EcranTest(unittest.TestCase):
    def test_ecran_deja_present(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"DISPLAY": ":5"}):
            js._assurer_ecran()          # ne doit rien lancer
            self.assertEqual(os.environ["DISPLAY"], ":5")

    def test_ecran_demarre_tout_seul(self):
        import shutil
        from unittest import mock
        if not shutil.which("Xvfb"):
            self.skipTest("Xvfb absent de cette machine de test")
        env = {k: v for k, v in os.environ.items() if k != "DISPLAY"}
        with mock.patch.dict(os.environ, env, clear=True):
            js._assurer_ecran()
            self.assertTrue(os.environ["DISPLAY"].startswith(":"))
            if js._XVFB["proc"]:
                js._XVFB["proc"].terminate()
                js._XVFB["proc"] = None


class CoordonneesTest(unittest.TestCase):
    def test_fenetre_sans_decor(self):
        # fenêtre en (0,0), barre d'outils de 85 px : un point de la page est décalé vers le bas
        self.assertEqual(js.coord_ecran({"sx": 0, "sy": 0, "dw": 0, "dh": 85}, 100, 200), (100, 285))

    def test_fenetre_decalee(self):
        self.assertEqual(js.coord_ecran({"sx": 10, "sy": 20, "dw": 16, "dh": 100}, 5, 5), (23, 125))

    def test_valeurs_negatives_ignorees(self):
        self.assertEqual(js.coord_ecran({"dw": -3, "dh": -9}, 7, 8), (7, 8))


class Xdotool(unittest.TestCase):
    def test_deja_installe(self):
        from unittest import mock
        with mock.patch("shutil.which", return_value="/usr/bin/xdotool"):
            self.assertEqual(js._installer_xdotool(), "/usr/bin/xdotool")

    def test_une_seule_tentative_par_heure(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(js, "PROFIL", Path(d) / "profil"), \
                 mock.patch("shutil.which", return_value=None), \
                 mock.patch("subprocess.run", return_value=mock.Mock(returncode=100, stdout="", stderr="erreur")) as lance:
                self.assertIsNone(js._installer_xdotool())
                self.assertIsNone(js._installer_xdotool())
            self.assertEqual(lance.call_count, 1)


class CbzTest(unittest.TestCase):
    def test_creation_et_extensions(self):
        with tempfile.TemporaryDirectory() as d:
            sc = js.JapscanScraper(Path(d))
            pages = [b"\x89PNG....", b"\xff\xd8\xff....", b"RIFF\0\0\0\0WEBPxx"]
            sortie = Path(d) / "x.cbz"
            self.assertTrue(sc.create_cbz(pages, sortie))
            noms = zipfile.ZipFile(sortie).namelist()
            self.assertEqual(noms, ["page_001.png", "page_002.jpg", "page_003.webp"])

    def test_aucune_page(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(js.JapscanScraper(Path(d)).create_cbz([], Path(d) / "x.cbz"))


class TelechargementTest(unittest.TestCase):
    def test_job_complet(self):
        with tempfile.TemporaryDirectory() as d:
            sc = js.JapscanScraper(Path(d))

            class _FauxPW:
                async def __aenter__(self):
                    return None

                async def __aexit__(self, *a):
                    return False

            async def ouvrir(p):
                return ("navigateur", "contexte")

            async def fermer(session):
                return None

            async def faux(url, **kw):
                return [b"\xff\xd8\xff" + b"0" * 20] if "ok" in url else []
            sc.download_chapter_pages = faux
            sc._ouvrir_session = ouvrir
            sc._fermer_session = fermer
            js.async_playwright = lambda: _FauxPW()
            os.environ["JAPSCAN_PAUSE"] = "0"
            chapitres = [
                {"title": "Chap ../1", "url": "https://x/ok/1/", "num": 1},
                {"title": "Chap 2", "url": "https://x/vide/2/", "num": 2},
            ]
            js.download_jobs.clear()
            sc.download_manga_sync("j1", "Test", chapitres)
            job = js.download_jobs["j1"]
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["progress"], 2)
            self.assertEqual(len(job["downloaded"]), 1)
            self.assertEqual(job["failed"], ["Chap 2"])
            for f in job["downloaded"]:
                self.assertEqual(Path(f).parent, Path(d))


class RoutesTest(unittest.TestCase):
    def test_import_sans_patchright_et_routes(self):
        import app as A
        self.assertTrue(callable(js.download_manga_background))
        client = A.app.test_client()
        # Les routes existent avec la bonne méthode
        regles = {(r.rule, tuple(sorted(r.methods - {"HEAD", "OPTIONS"}))) for r in A.app.url_map.iter_rules()}
        self.assertIn(("/api/japscan/chapters/<manga_id>", ("POST",)), regles)


if __name__ == "__main__":
    unittest.main()
