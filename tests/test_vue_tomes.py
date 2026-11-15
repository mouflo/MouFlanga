"""Fiche d'une série : les couvertures des tomes en grille, et « Reprendre la lecture » à l'accueil."""
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


class VueTomesTest(unittest.TestCase):
    def setUp(self):
        self.js = (RACINE / "ui" / "mouflanga.js").read_text(encoding="utf-8")
        self.css = (RACINE / "ui" / "mouflanga.css").read_text(encoding="utf-8")
        self.page = (RACINE / "templates" / "index.html").read_text(encoding="utf-8")

    def test_la_fiche_montre_les_couvertures_des_tomes(self):
        self.assertIn("/api/tome/couverture?id=", self.js)
        self.assertIn("tomes-grille", self.js)
        self.assertIn(".tomes-grille", self.css)
        self.assertIn("data-vue-tomes", self.js)             # on peut revenir à la liste

    def test_la_grille_est_la_vue_par_defaut(self):
        self.assertIn("pref('mfVueTomes','grille')", self.js.replace(" ", "").replace("pref('mfVueTomes','grille')", "pref('mfVueTomes','grille')"))

    def test_reprendre_la_lecture_a_l_accueil(self):
        self.assertIn('id="reprendre"', self.page)
        self.assertIn("dessinerReprendre", self.js)

    def test_un_lecteur_ne_declenche_pas_d_appels_refuses(self):
        corbeille = (RACINE / "ui" / "corbeille.js").read_text(encoding="utf-8")
        self.assertIn("classList.contains('lecteur')", corbeille)
        debut = self.js.index("async function verifierChoix()")
        self.assertIn("classList.contains('lecteur')", self.js[debut:debut + 200])


if __name__ == "__main__":
    unittest.main()
