"""Sommaires et ISBN : deux lecteurs de texte (tesseract, moderne), on garde le meilleur résultat ; ISBN en double mis en doute."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sommaire  # noqa: E402


def _ch(n, estimee=False):
    return [{"num": float(i), "titre": f"T{i}", "page": i * 10, "image": i * 10, **({"estimee": True} if estimee else {})}
            for i in range(1, n + 1)]


class DeuxLecteursTest(unittest.TestCase):
    def _lire(self, par_mode, numeros=None, moderne=True):
        appels = []

        def faux(mode, vision, *a, **k):
            appels.append(mode)
            return {"chapitres": par_mode[mode], "page_sommaire": 3, "decalage": 0}
        with mock.patch.object(sommaire, "_lire_avec", faux), \
                mock.patch.object(sommaire, "_moteur", lambda: object() if moderne else None), \
                mock.patch.object(sommaire.shutil, "which", lambda n: "/usr/bin/tesseract"), \
                mock.patch.object(sommaire, "cle_claude", lambda: ""):
            return sommaire.lire("x.cbz", lambda i: b"", 10, None, numeros), appels

    def test_le_moderne_gagne_quand_tesseract_ne_trouve_rien(self):
        r, appels = self._lire({"tesseract": [], "moderne": _ch(9)})
        self.assertEqual(len(r["chapitres"]), 9)
        self.assertEqual(appels, ["tesseract", "moderne"])

    def test_a_egalite_tesseract_est_garde(self):
        a, b = _ch(5), _ch(5)
        b[0]["titre"] = "autre"
        r, _ = self._lire({"tesseract": a, "moderne": b})
        self.assertEqual(r["chapitres"][0]["titre"], "T1")

    def test_resultat_complet_et_sur_pas_de_seconde_lecture(self):
        r, appels = self._lire({"tesseract": _ch(9), "moderne": _ch(3)}, numeros=list(range(1, 10)))
        self.assertEqual(appels, ["tesseract"])
        self.assertEqual(len(r["chapitres"]), 9)

    def test_moins_de_pages_estimees_est_mieux(self):
        r, _ = self._lire({"tesseract": _ch(9, estimee=True), "moderne": _ch(9)})
        self.assertFalse(any(c.get("estimee") for c in r["chapitres"]))

    def test_sans_lecteur_moderne_tesseract_seul(self):
        r, appels = self._lire({"tesseract": _ch(4), "moderne": _ch(9)}, moderne=False)
        self.assertEqual(appels, ["tesseract"])
        self.assertEqual(len(r["chapitres"]), 4)


class IsbnEnDoubleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MANGA_DIR"] = self.tmp.name
        sys.modules.pop("app", None)
        import app
        self.A = app

    def tearDown(self):
        self.tmp.cleanup()

    def test_isbn_lu_dans_deux_tomes_est_suspect(self):
        infos = {"isbn": {"49": "9782505008712", "50": "9782505008712", "51": "9782505009924"},
                 "sommaires": {"49": {"isbn": "9782505008712"}, "50": {"isbn": "9782505008712"}, "51": {"isbn": "9782505009924"}}}
        self.assertEqual(self.A._isbn_en_double(infos), {"49", "50"})

    def test_isbn_note_a_la_main_jamais_mis_en_doute(self):
        infos = {"isbn": {"1": "9782505008712", "2": "9782505008712"}, "sommaires": {}}
        self.assertEqual(self.A._isbn_en_double(infos), set())

    def test_le_bon_isbn_lu_remplace_la_copie_du_tome_voisin(self):
        # Naruto 50 : l'ISBN noté est celui du tome 49, mais la lecture des pages a trouvé le bon
        infos = {"isbn": {"49": "9782505008712", "50": "9782505008712"},
                 "sommaires": {"49": {"isbn": "9782505008712"}, "50": {"isbn": "9782505009566"}}}
        connus = self.A._isbn_connus(infos)
        self.assertEqual(connus["50"], "9782505009566")
        self.assertEqual(connus["49"], "9782505008712")

    def test_isbn_unique_note_n_est_pas_remplace(self):
        infos = {"isbn": {"49": "9782505008712", "50": "9782505009924"},
                 "sommaires": {"50": {"isbn": "9782505009566"}}}
        self.assertEqual(self.A._isbn_connus(infos)["50"], "9782505009924")


if __name__ == "__main__":
    unittest.main()
