"""Téléchargement : arrêt après des échecs de suite, annulation, liste des jobs."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import japscan_scraper as js


def _chapitres(n):
    return [{"title": f"Chapitre {i}", "url": f"https://x/{i}/", "num": i, "chapter_id": str(i)} for i in range(1, n + 1)]


class _FauxPlaywright:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *a):
        return False


class TelechargementTest(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self.sc = js.JapscanScraper(self.dossier)

        async def ouvrir(p):
            return ("navigateur", "contexte")

        async def fermer(session):
            self.fermees = getattr(self, "fermees", 0) + 1
        for cible, valeur in (("_ouvrir_session", ouvrir), ("_fermer_session", fermer)):
            patcher = mock.patch.object(self.sc, cible, valeur)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(os.environ, {"JAPSCAN_PAUSE": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(js, "async_playwright", lambda: _FauxPlaywright())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_arret_apres_trois_echecs_de_suite(self):
        async def vide(url, **kw):
            return []
        with mock.patch.object(self.sc, "download_chapter_pages", vide):
            self.sc.download_manga_sync("t1", "Test", _chapitres(10))
        job = js.download_jobs["t1"]
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["progress"], 3)
        self.assertIn("3 chapitres de suite", job["error"])

    def test_succes_et_remise_a_zero_des_echecs(self):
        appels = []

        async def une_sur_deux(url, **kw):
            appels.append(url)
            return [] if len(appels) % 2 else [b"\xff\xd8" + b"0" * 20000]
        with mock.patch.object(self.sc, "download_chapter_pages", une_sur_deux):
            self.sc.download_manga_sync("t2", "Test", _chapitres(6))
        job = js.download_jobs["t2"]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(job["downloaded"]), 3)
        self.assertEqual(len(job["failed"]), 3)

    def test_annulation(self):
        async def page(url, **kw):
            js.download_jobs["t3"]["annule"] = True
            return [b"\xff\xd8" + b"0" * 20000]
        with mock.patch.object(self.sc, "download_chapter_pages", page):
            self.sc.download_manga_sync("t3", "Test", _chapitres(5))
        job = js.download_jobs["t3"]
        self.assertEqual(job["status"], "annule")
        self.assertEqual(job["progress"], 1)
        self.assertEqual(self.fermees, 1)   # le navigateur est refermé une seule fois, à la fin


    def test_captchas_groupes_gardes_pour_la_fin(self):
        """Mode groupé : les chapitres à captcha passent à la fin, une seule alerte, tout est téléchargé."""
        ordre = []

        async def lire(url, reporter_captcha=False, alerter=True, **kw):
            ordre.append((url, reporter_captcha, alerter))
            if reporter_captcha and url.endswith(("/1/", "/3/")):
                raise js.CaptchaReporte(url)
            return [b"\xff\xd8" + b"0" * 20000]
        with mock.patch.object(self.sc, "download_chapter_pages", lire), \
                mock.patch.dict(os.environ, {"JAPSCAN_CAPTCHAS_GROUPES": "1"}), \
                mock.patch.object(js, "_alerter_telegram") as alerte:
            self.sc.download_manga_sync("g1", "Test", _chapitres(4))
        job = js.download_jobs["g1"]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(job["downloaded"]), 4)
        self.assertEqual(job["progress"], 4)
        self.assertEqual(alerte.call_count, 1)                       # une seule alerte groupée
        fin = [(u, r, a) for u, r, a in ordre[4:]]
        self.assertEqual([u[-3:] for u, _, _ in fin], ["/1/", "/3/"])  # repris à la fin, dans l'ordre
        self.assertTrue(all(not r and not a for _, r, a in fin))     # sans report ni alerte par page

    def test_mode_normal_sans_report(self):
        vus = []

        async def lire(url, reporter_captcha=False, **kw):
            vus.append(reporter_captcha)
            return [b"\xff\xd8" + b"0" * 20000]
        with mock.patch.object(self.sc, "download_chapter_pages", lire), \
                mock.patch.dict(os.environ, {"JAPSCAN_CAPTCHAS_GROUPES": ""}):
            self.sc.download_manga_sync("g2", "Test", _chapitres(3))
        self.assertEqual(vus, [False, False, False])
        self.assertEqual(js.download_jobs["g2"]["status"], "completed")

if __name__ == "__main__":
    unittest.main()
