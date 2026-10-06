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

            async def faux(url):
                return [b"\xff\xd8\xff" + b"0" * 20] if "ok" in url else []
            sc.download_chapter_pages = faux
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
