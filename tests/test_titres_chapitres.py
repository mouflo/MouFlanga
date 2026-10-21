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


class PrefixeChoisi(unittest.TestCase):
    def test_prefixe_devant_tous_les_chapitres(self):
        infos = {"1": {"chapitres": [{"num": 1, "titre": "Chapitre 1"}, {"num": 2, "titre": "La nuit des assassins"},
                                     {"num": 3, "titre": "Kill:3 : Déjà là"}, {"num": 4, "titre": "Retour 4 ans plus tard"},
                                     {"num": 5, "titre": ""}, {"num": 5.5, "titre": "Bonus"}]}}
        r = tc.proposer(infos, "Kill")
        apres = {c["num"]: c["apres"] for c in r["changements"]}
        self.assertEqual(apres, {1: "Kill 1", 2: "Kill 2 : La nuit des assassins", 3: "Kill 3 : Déjà là",
                                 4: "Kill 4 : Retour 4 ans plus tard", 5: "Kill 5"})
        tc.appliquer(infos, r["changements"])
        self.assertEqual(tc.proposer(infos, "Kill")["changements"], [])          # rejouer ne change plus rien


class TitresOfficiels(unittest.TestCase):
    def test_titre_de_la_fiche_quand_le_tome_n_en_donne_pas(self):
        infos = {"2": {"chapitres": [{"num": 5, "titre": "Kill 5"}, {"num": 6, "titre": ""}, {"num": 7, "titre": "Rêves lus"}]}}
        r = tc.proposer(infos, "Kill", {5: "Le coupeur de têtes", 6: "L'utilisateur d'arme impériale", 7: "Rêves"})
        apres = {c["num"]: c["apres"] for c in r["changements"]}
        self.assertEqual(apres, {5: "Kill 5 : Le coupeur de têtes", 6: "Kill 6 : L'utilisateur d'arme impériale",
                                 7: "Kill 7 : Rêves lus"})              # le titre lu dans le tome passe avant celui de la fiche


class Retrait(unittest.TestCase):
    def test_retire_le_mot_devant_le_numero_sans_toucher_aux_vrais_titres(self):
        infos = {"1": {"chapitres": [{"num": 5, "titre": "Kill 5 : Le coupeur de têtes"}, {"num": 6, "titre": "Kill 6"},
                                     {"num": 7, "titre": "Rêves"}, {"num": 8, "titre": "Retour 8 ans plus tard"},
                                     {"num": 9, "titre": "Trick 9"}]}}
        r = tc.proposer(infos, retirer=True, officiels={6: "L'utilisateur"})
        apres = {c["num"]: c["apres"] for c in r["changements"]}
        self.assertEqual(apres, {5: "Le coupeur de têtes", 6: "L'utilisateur", 9: ""})
