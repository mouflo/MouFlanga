"""La série visée par une recherche : un nom connu ne compte que s'il forme des mots entiers (« mar » ne se trouve pas dans « Terra formars »)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import regles  # noqa: E402


class ResolueTest(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.ancien = regles.FICHIER
        regles.FICHIER = Path(self.dossier.name) / "regles.json"

    def tearDown(self):
        regles.FICHIER = self.ancien
        self.dossier.cleanup()

    def resolue(self, texte, *connues):
        with mock.patch.object(regles, "SERIES_CONNUES", lambda: list(connues)):
            return regles._resolue(texte)

    def test_terra_formars_ne_vise_pas_mar(self):
        self.assertEqual(self.resolue("Terra formars", "MAR", "Gantz"), "terraformars")

    def test_terra_formars_vise_sa_serie_si_elle_existe(self):
        self.assertEqual(self.resolue("Terra formars", "MAR", "Terra Formars"), "terraformars")

    def test_nom_entier_reconnu_dans_une_recherche(self):
        self.assertEqual(self.resolue("MAR T03", "MAR", "Gantz"), "mar")

    def test_le_plus_long_nom_gagne(self):
        self.assertEqual(self.resolue("Gantz : Osaka T03", "Gantz", "Gantz : Osaka"), "gantzosaka")
        self.assertEqual(self.resolue("Air Gear intégrale", "Air Gear", "Air Gear Unlimited"), "airgear")

    def test_ponctuation_et_collage_acceptes(self):
        self.assertEqual(self.resolue("Gantz:Osaka", "Gantz : Osaka"), "gantzosaka")
        self.assertEqual(self.resolue("One Punch Man 12", "One-Punch Man"), "onepunchman")

    def test_chiffres_colles_au_nom(self):
        self.assertEqual(self.resolue("Kaf01 FR", "Kaf"), "kaf")

    def test_rien_de_connu_renvoie_la_requete(self):
        self.assertEqual(self.resolue("Terra formars", "Gantz"), "terraformars")

    def test_profil_compte_comme_nom_connu(self):
        regles.enregistrer_profil("", "Kaf seulement", True, "", "", "Kaf", "")
        self.assertEqual(regles._resolue("Kaf 01"), "kaf")
        self.assertEqual(regles._resolue("Terra formars"), "terraformars")


if __name__ == "__main__":
    unittest.main()
