"""🔍 Lire les ISBN de toute la série (OCR) + case « ISBN » du pense-bête « où j'en suis »."""
import io
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _jpeg(c):
    b = io.BytesIO()
    Image.new("RGB", (60, 80), (c, c, c)).save(b, "JPEG")
    return b.getvalue()


class IsbnSerieTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "mangas"
        for n in (1, 2, 3):
            d = self.root / "Serie" / f"Tome {n:02d}"
            d.mkdir(parents=True)
            with zipfile.ZipFile(d / f"Serie - Tome {n:02d}.cbz", "w") as z:
                for i in range(10):
                    z.writestr(f"{i:03d}.jpg", _jpeg(n * 10 + i))
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        import auth
        import sommaire
        self.A, self.auth, self.som = A, auth, sommaire
        self._role, self._ocr, self._dispo = auth.role, sommaire.ocr, sommaire.disponible
        auth.role = lambda: "admin"
        sommaire.disponible = lambda: True
        # fausse lecture : le tome 1 et le tome 3 ont un ISBN valide sur leur dernière page, le tome 2 n'en a pas
        self.isbn = {10: "9782505013112", 30: "9782505013129"}        # couleur du gris de la dernière page -> ISBN
        sommaire.ocr = self._faux_ocr
        A.MANGA_DIR = self.root
        A._scan_invalider()
        self.c = A.app.test_client()

    def _faux_ocr(self, octets, clair=False):
        gris = Image.open(io.BytesIO(octets)).getpixel((0, 0))[0]
        v = {19: "9782505013112", 39: "9782505013129"}.get(gris)         # dernière page de chaque tome
        return f"Achevé d'imprimer ISBN {v}" if v else "texte sans rien"

    def tearDown(self):
        self.auth.role = self._role
        self.som.ocr, self.som.disponible = self._ocr, self._dispo
        self.tmp.cleanup()

    def _attendre(self):
        for _ in range(400):
            st = self.c.get("/api/serie/isbn/lire", query_string={"series": "Serie"}).get_json()
            if not st["en_cours"]:
                return st
            time.sleep(0.05)
        self.fail("lecture trop longue")

    def test_lecture_et_enregistrement(self):
        r = self.c.post("/api/serie/isbn/lire", json={"series": "Serie"}).get_json()
        self.assertTrue(r["ok"], r)
        st = self._attendre()
        self.assertIn("2 ISBN lu(s) sur 3", st["message"])
        self.assertIn("tome 2", st["message"])
        import edition
        isbn = edition.lire(self.root / "Serie").get("isbn") or {}
        self.assertEqual(isbn.get("1"), "9782505013112")
        self.assertEqual(isbn.get("3"), "9782505013129")
        self.assertNotIn("2", isbn)

    def test_ne_relit_pas_ce_qui_est_connu(self):
        import edition
        d = edition.lire(self.root / "Serie")
        d["isbn"] = {"1": "9782505013112"}
        edition.ecrire(self.root / "Serie", d)
        g = self.c.get("/api/serie/isbn/lire", query_string={"series": "Serie"}).get_json()
        self.assertEqual(g["total"], 2)
        self.assertEqual(g["deja"], 1)

    def test_case_isbn_dans_le_pense_bete(self):
        cles = [k for k, _ in self.A.TRAVAIL]
        self.assertIn("isbn", cles)
        import edition
        d = edition.lire(self.root / "Serie")
        d["isbn"] = {"1": "9782505013112", "2": "9782505013129", "3": "9782505013136"}
        edition.ecrire(self.root / "Serie", d)
        self.A._CACHE_EDITION.clear()
        self.assertIn("isbn", self.A._travail_de("Serie")["suggere"])           # tous connus : case suggérée
        r = self.c.post("/api/series/travail", json={"series": "Serie", "cle": "isbn", "fait": True}).get_json()
        self.assertIn("isbn", r["fait"])


class LireIsbnTest(unittest.TestCase):
    def test_fin_puis_debut_et_somme_de_controle(self):
        import sommaire
        vus = []

        def page(i):
            vus.append(i)
            return b""
        ancien = sommaire.ocr
        sommaire.ocr = lambda b, clair=False: "ISBN 978-2-505-01311-2" if len(vus) == 3 else ""
        try:
            self.assertEqual(sommaire.lire_isbn(page, 20), "9782505013112")
            self.assertEqual(vus[:3], [19, 18, 17])                               # d'abord la fin
        finally:
            sommaire.ocr = ancien


if __name__ == "__main__":
    unittest.main()


class ComptesTest(unittest.TestCase):
    """« Où j'en suis » : combien de tomes sont faits, étape par étape."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "mangas"
        for n in (1, 2, 3, 4):
            d = self.root / "Serie" / f"Tome {n:02d}"
            d.mkdir(parents=True)
            with zipfile.ZipFile(d / f"Serie - Tome {n:02d}.cbz", "w") as z:
                z.writestr("000.jpg", _jpeg(n))
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        import auth
        self.A, self.auth = A, auth
        self._role = auth.role
        auth.role = lambda: "admin"
        A.MANGA_DIR = self.root
        A._scan_invalider()
        self.c = A.app.test_client()

    def tearDown(self):
        self.auth.role = self._role
        self.tmp.cleanup()

    def test_comptes_par_etape(self):
        import edition
        d = edition.lire(self.root / "Serie")
        d["resumes_tomes"] = {"1": "Un résumé écrit à la main", "2": "Un autre"}
        d["isbn"] = {"1": "9782505013112", "3": "9782505013129", "4": "9782505013136"}
        d["sommaires"] = {"1": {"chapitres": [{"num": 1, "titre": "A", "image": 3}], "valide_le": "2026-10-14"},
                          "2": {"chapitres": [{"num": 2, "titre": "B"}], "manuel": True},
                          "3": {"chapitres": [{"num": 3, "titre": "C", "image": 5}]}}      # lu mais pas validé : ne compte pas
        edition.ecrire(self.root / "Serie", d)
        self.A._CACHE_EDITION.clear()
        r = self.c.get("/api/series/travail/comptes", query_string={"series": "Serie"}).get_json()
        self.assertEqual(r["total"], 4)
        c = r["comptes"]
        self.assertEqual(c["resumes"], 2)
        self.assertEqual(c["isbn"], 3)
        self.assertEqual(c["titres"], 2)          # deux tomes validés (le 3 est seulement lu)
        self.assertEqual(c["liens"], 1)           # un seul validé avec une page de départ pour tous ses chapitres
        self.assertEqual(c["couvertures"], 0)
        self.assertEqual(c["reecriture"], 0)

    def test_serie_inconnue(self):
        self.assertEqual(self.c.get("/api/series/travail/comptes", query_string={"series": "Nope"}).status_code, 404)
