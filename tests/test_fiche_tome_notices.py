"""La fiche d'un tome (ⓘ) : l'ISBN et le résumé viennent des notices d'Internet (Wikipédia, BnF, Google Books), derrière ce qui est saisi
à la main ou lu dans le tome ; l'accord de deux sources est annoncé ; rien n'est cherché sur Internet à l'ouverture."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _jpeg():
    b = io.BytesIO()
    Image.new("RGB", (60, 80), (9, 9, 9)).save(b, "JPEG")
    return b.getvalue()


class FicheTomeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "mangas"
        d = self.root / "Serie" / "Tome 01"
        d.mkdir(parents=True)
        with zipfile.ZipFile(d / "Serie - Tome 01.cbz", "w") as z:
            z.writestr("001.jpg", _jpeg())
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        import auth
        import notices
        import tomes
        self.A, self.auth, self.notices, self.tomes = A, auth, notices, tomes
        self._role = auth.role
        auth.role = lambda: "admin"
        A.MANGA_DIR = self.root
        self.dossier = mock.patch.object(tomes, "DOSSIER", Path(self.tmp.name) / "tomes")
        self.dossier.start()
        tomes._CACHE_FICHES.clear()
        A._scan_invalider()
        self.c = A.app.test_client()

    def tearDown(self):
        self.dossier.stop()
        self.auth.role = self._role
        self.tomes._CACHE_FICHES.clear()
        self.tmp.cleanup()

    def fiche(self):
        return self.c.get("/api/tome", query_string={"id": "Serie", "tome": "1"}).get_json()

    def test_isbn_et_resume_d_internet_avec_leurs_sources(self):
        resume = "Akame et ses compagnons du Night Raid affrontent un nouvel ennemi redoutable dans la capitale impériale."
        self.notices.enregistrer("Serie", "wikipedia", {1: {"isbn": "9782368520444"}})
        self.notices.enregistrer("Serie", "bnf", {1: {"isbn": "9782368520444", "resume": resume}})
        self.notices.enregistrer("Serie", "google", {1: {"isbn": "9782368520512"}})
        d = self.fiche()
        self.assertEqual((d["isbn"], d["isbn_source"]), ("9782368520444", "wikipedia + bnf".replace("wikipedia", "Wikipédia").replace("bnf", "BnF")))
        self.assertEqual(d["isbn_autres"], ["9782368520512"])
        self.assertEqual((d["resume"], d["resume_source"]), (resume, "BnF"))
        self.assertNotIn("en_preparation", d)

    def test_isbn_saisi_a_la_main_passe_devant(self):
        import edition
        self.notices.enregistrer("Serie", "bnf", {1: {"isbn": "9782368520444"}})
        info = edition.lire(self.root / "Serie")
        info["isbn"] = {"1": "9782505013112"}
        edition.ecrire(self.root / "Serie", info)
        self.A._CACHE_EDITION.clear()
        d = self.fiche()
        self.assertEqual(d["isbn"], "9782505013112")
        self.assertIn("main", d["isbn_source"])
        self.assertNotIn("isbn_autres", d)

    def test_rien_encore_cherche_la_preparation_s_en_charge(self):
        with mock.patch.object(self.A.prechauffage, "demander") as demander:
            d = self.fiche()
        self.assertEqual((d.get("resume"), d.get("en_preparation")), ("", True))
        demander.assert_called_once()

    def test_deja_cherche_sans_resultat_n_est_pas_en_preparation(self):
        self.tomes.modifier("Serie", lambda b: b.setdefault("recherches", {}).__setitem__("notices", {"etat": "ok", "detail": "x"}))
        with mock.patch.object(self.A.prechauffage, "demander") as demander:
            d = self.fiche()
        self.assertNotIn("en_preparation", d)
        demander.assert_not_called()


if __name__ == "__main__":
    unittest.main()
