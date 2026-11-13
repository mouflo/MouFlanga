"""Registre des traitements d'un tome (« où j'en suis ») : ce qui a été fait, et seulement sur le fichier concerné."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import traitements as T


class TailleTest(unittest.TestCase):
    def test_tolerance(self):
        self.assertTrue(T.proche(100_000_000, 100_000_000))
        self.assertTrue(T.proche(100_000_000, 102_900_000))        # quelques ko d'infos écrites dans le tome
        self.assertFalse(T.proche(100_000_000, 70_000_000))        # un tome allégé ou remplacé
        for mauvais in (None, "x", 0, -5):
            self.assertFalse(T.proche(mauvais, 100))
            self.assertFalse(T.proche(100, mauvais))


class RegistreTest(unittest.TestCase):
    def test_note_puis_lit(self):
        infos = {}
        T.noter(infos, "T05.cbz", 140_000_000, 96_000_000, {"allegement": {"detail": "qualité 85"}, "image": {}}, date="2026-11-13")
        marques = T.lire(infos, "T05.cbz", 96_000_000)
        self.assertEqual(set(marques), {"allegement", "image"})
        self.assertEqual(marques["allegement"]["date"], "2026-11-13")
        self.assertEqual(marques["allegement"]["detail"], "qualité 85")

    def test_un_tome_remplace_n_a_plus_de_marques(self):
        infos = {}
        T.noter(infos, "T05.cbz", 140_000_000, 96_000_000, {"allegement": {}})
        self.assertEqual(T.lire(infos, "T05.cbz", 200_000_000), {})          # même nom, mais une autre version (autre taille)
        self.assertEqual(T.lire(infos, "T99.cbz", 96_000_000), {})           # fichier jamais vu

    def test_un_nouveau_travail_garde_les_marques_d_avant(self):
        infos = {}
        T.noter(infos, "T05.cbz", 100_000_000, 100_000_000, {"doubles": {}})
        T.noter(infos, "T05.cbz", 100_000_000, 70_000_000, {"allegement": {}})    # l'allègement change la taille du fichier
        marques = T.lire(infos, "T05.cbz", 70_000_000)
        self.assertEqual(set(marques), {"doubles", "allegement"})                 # les doubles pages restent faites

    def test_un_travail_sur_un_fichier_change_depuis_oublie_l_ancien(self):
        infos = {}
        T.noter(infos, "T05.cbz", 100_000_000, 100_000_000, {"doubles": {}})
        T.noter(infos, "T05.cbz", 150_000_000, 120_000_000, {"allegement": {}})   # le fichier d'avant n'était plus celui des marques
        self.assertEqual(set(T.lire(infos, "T05.cbz", 120_000_000)), {"allegement"})

    def test_oublier(self):
        infos = {}
        T.noter(infos, "A.cbz", 10, 10, {"allegement": {}})
        T.noter(infos, "B.cbz", 10, 10, {"allegement": {}})
        T.oublier(infos, "A.cbz")
        self.assertEqual(T.lire(infos, "A.cbz", 10), {})
        self.assertTrue(T.lire(infos, "B.cbz", 10))
        T.oublier(infos)
        self.assertEqual(T.lire(infos, "B.cbz", 10), {})

    def test_les_donnees_abimees_ne_font_pas_planter(self):
        infos = {"traitements": {"A.cbz": "n'importe quoi", "B.cbz": {"taille": "x", "etapes": []}}}
        self.assertEqual(T.lire(infos, "A.cbz", 10), {})
        self.assertEqual(T.lire(infos, "B.cbz", 10), {})
        T.noter(infos, "A.cbz", 10, 10, {"image": {}})
        self.assertEqual(set(T.lire(infos, "A.cbz", 10)), {"image"})


class MainTest(unittest.TestCase):
    def test_cocher_et_decocher_a_la_main(self):
        infos = {}
        self.assertTrue(T.marquer_main(infos, "T01.cbz", 100, "image", True, date="2026-11-13"))
        self.assertTrue(T.lire(infos, "T01.cbz", 100)["image"]["manuel"])
        self.assertTrue(T.marquer_main(infos, "T01.cbz", 100, "image", False))
        self.assertEqual(T.lire(infos, "T01.cbz", 100), {})

    def test_une_marque_de_l_appli_ne_se_decoche_pas(self):
        infos = {}
        T.noter(infos, "T01.cbz", 100, 100, {"allegement": {"detail": "x"}})
        self.assertFalse(T.marquer_main(infos, "T01.cbz", 100, "allegement", False))
        self.assertFalse(T.marquer_main(infos, "T01.cbz", 100, "allegement", True))      # déjà connue de l'appli : pas de marque « à la main » par-dessus
        self.assertNotIn("manuel", T.lire(infos, "T01.cbz", 100)["allegement"])

    def test_etape_non_cochable(self):
        self.assertFalse(T.marquer_main({}, "T01.cbz", 100, "uniformise", True))     # l'uniformité se mesure
        self.assertFalse(T.marquer_main({}, "T01.cbz", 100, "n'importe quoi", True))

    def test_une_marque_a_la_main_sur_un_fichier_change_repart_de_zero(self):
        infos = {}
        T.marquer_main(infos, "T01.cbz", 100_000_000, "image", True)
        T.marquer_main(infos, "T01.cbz", 200_000_000, "allegement", True)                # le tome a été remplacé entre-temps
        self.assertEqual(set(T.lire(infos, "T01.cbz", 200_000_000)), {"allegement"})


class ResumeTest(unittest.TestCase):
    def test_ligne_discrete_seulement_ce_qui_est_commence(self):
        self.assertEqual(T.resume_court({"uniformise": 10, "doubles": 3, "allegement": 6, "resumes": 10}, 10), "📖 3/10 · 🎨 10/10 · 🗜 6/10")
        self.assertEqual(T.resume_court({}, 10), "")
        self.assertEqual(T.resume_court({"couvertures": 4, "isbn": 4}, 10), "")           # ni les couvertures ni l'identification


if __name__ == "__main__":
    unittest.main()
