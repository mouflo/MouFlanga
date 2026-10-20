import unittest

import titres_chapitres as tc


def _tome(*paires):
    return {"chapitres": [{"num": n, "titre": t} for n, t in paires]}


class ApprendreTest(unittest.TestCase):
    def test_apprend_le_mot_fixe(self):
        chapitres = _tome((1, "Trick 1"), (2, "Trick 2"), (3, "Trick 3"))["chapitres"]
        self.assertEqual(tc.apprendre({"1": chapitres}), ("Trick", 3))

    def test_pas_assez_d_exemples(self):
        self.assertEqual(tc.apprendre({"1": [{"num": 1, "titre": "Trick 1"}]}), ("", 0))

    def test_titres_reels_ne_font_pas_de_modele(self):
        s = {"1": [{"num": n, "titre": f"Le titre {n} de la vie"} for n in range(1, 6)]}
        self.assertEqual(tc.apprendre(s), ("", 0))


class ProposerTest(unittest.TestCase):
    def setUp(self):
        self.infos = {
            "1": _tome((1, "Trick 1"), (2, "Trick 2"), (3, "Trick 3")),
            "2": _tome((4, "Trick 4"), (5, "Trick 5"), (6, "Trick 6")),
            "3": _tome((7, ""), (8, "8"), (9, "Trick 90")),
        }

    def test_propose_titres_vides_et_numeros_seuls(self):
        r = tc.proposer(self.infos)
        self.assertEqual(r["nb_appris"], 6)
        apres = {(c["tome"], c["num"]): c["apres"] for c in r["changements"]}
        self.assertEqual(apres, {("3", 7): "Trick 7", ("3", 8): "Trick 8", ("3", 9): "Trick 9"})

    def test_ne_touche_pas_un_vrai_titre(self):
        infos = {"1": _tome((1, "Trick 1"), (2, "Trick 2"), (3, "Trick 3"), (4, "La valeur de la vie"))}
        self.assertEqual(tc.proposer(infos)["changements"], [])

    def test_chapitre_bonus_ignore(self):
        infos = {"1": _tome((1, "Trick 1"), (2, "Trick 2"), (3, "Trick 3"), (3.5, ""))}
        self.assertEqual(tc.proposer(infos)["changements"], [])

    def test_sans_modele_rien_a_proposer(self):
        self.assertEqual(tc.proposer({"1": _tome((1, ""))}), {"modele": None, "nb_appris": 0, "changements": []})


class AppliquerTest(unittest.TestCase):
    def test_ecrit_les_titres(self):
        infos = {"1": _tome((1, "Trick 1"), (2, "Trick 2"), (3, "Trick 3")),
                 "2": _tome((4, ""), (5, "5"))}
        r = tc.proposer(infos)
        self.assertEqual(tc.appliquer(infos, r["changements"]), 2)
        self.assertEqual([c["titre"] for c in infos["2"]["chapitres"]], ["Trick 4", "Trick 5"])


if __name__ == "__main__":
    unittest.main()
