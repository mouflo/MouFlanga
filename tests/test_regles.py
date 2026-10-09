"""Règles de recherche : profils (doit / ne doit pas / séries / taille) et formats personnalisés (score)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import regles  # noqa: E402

GO = 1024 ** 3


class ReglesTest(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.ancien = regles.FICHIER
        regles.FICHIER = Path(self.dossier.name) / "regles.json"

    def tearDown(self):
        regles.FICHIER = self.ancien
        self.dossier.cleanup()

    def titres(self, *titres, taille=GO):
        return [{"titre": t, "taille": taille} for t in titres]

    def test_doit_contenir(self):
        regles.enregistrer_profil("", "Kaf", True, "kaf", "", "", "")
        out = regles.filtrer(self.titres("Kaf 01 FR", "Autre 01 FR"), "Kaf")
        self.assertEqual([x["titre"] for x in out], ["Kaf 01 FR"])

    def test_ne_doit_pas_contenir(self):
        regles.enregistrer_profil("", "Sans VO", True, "", "VOSTFR", "", "")
        out = regles.filtrer(self.titres("Kaf 01 VOSTFR", "Kaf 01 FR"), "Kaf")
        self.assertEqual([x["titre"] for x in out], ["Kaf 01 FR"])

    def test_profil_desactive_ignore(self):
        regles.enregistrer_profil("", "Off", False, "jamais", "", "", "")
        self.assertEqual(len(regles.filtrer(self.titres("Kaf 01"), "Kaf")), 1)

    def test_profil_limite_aux_series(self):
        regles.enregistrer_profil("", "Kaf seulement", True, "FR", "", "Kaf", "")
        out = regles.filtrer(self.titres("One Piece 01 VO"), "One Piece")
        self.assertEqual(len(out), 1)            # ne concerne pas One Piece
        self.assertEqual(len(regles.filtrer(self.titres("Kaf 01 VO"), "Kaf")), 0)

    def test_taille_maximale(self):
        regles.enregistrer_profil("", "Moins de 3 Go", True, "", "", "", "3")
        out = regles.filtrer([{"titre": "Gros", "taille": 5 * GO}, {"titre": "Petit", "taille": 2 * GO}], "")
        self.assertEqual([x["titre"] for x in out], ["Petit"])

    def test_score_des_formats(self):
        regles.enregistrer_format("", "FR Anime", "Tsundere-Raws, SR-71", "50")
        regles.enregistrer_format("", "Multi", "MULTI", "10")
        out = regles.filtrer(self.titres("Kaf 01 SR-71 MULTI", "Kaf 01 Autre"), "")
        scores = {x["titre"]: x["score"] for x in out}
        self.assertEqual(scores, {"Kaf 01 SR-71 MULTI": 60, "Kaf 01 Autre": 0})

    def test_score_negatif(self):
        regles.enregistrer_format("", "Pénalité", "Scan", "-20")
        self.assertEqual(regles.filtrer(self.titres("Kaf Scan"), "")[0]["score"], -20)

    def test_modification_remplace_sans_doublon(self):
        i = regles.enregistrer_format("", "Ancien", "a", "1")
        regles.enregistrer_format(i, "Nouveau", "b", "2")
        self.assertEqual([(f["nom"], f["score"]) for f in regles.formats()], [("Nouveau", 2)])

    def test_validation(self):
        with self.assertRaises(ValueError):
            regles.enregistrer_profil("", "  ", True, "", "", "", "")
        with self.assertRaises(ValueError):
            regles.enregistrer_profil("", "X", True, "", "", "", "beaucoup")
        with self.assertRaises(ValueError):
            regles.enregistrer_format("", "X", "a", "dix")

    def test_suppression(self):
        i = regles.enregistrer_profil("", "À supprimer", True, "", "", "", "")
        regles.supprimer("profil", i)
        self.assertEqual(regles.profils(), [])


if __name__ == "__main__":
    unittest.main()
