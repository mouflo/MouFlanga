"""Un numéro de chapitre relu en lettres (« OOG » pour 006) n'est pas un titre."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sommaire  # noqa: E402


class FauxTitresTest(unittest.TestCase):
    def test_numero_relu_en_lettres_retire_vrai_titre_garde(self):
        res = {"chapitres": [{"num": 6.0, "titre": "OOG"}, {"num": 10.0, "titre": "DID"}, {"num": 1.0, "titre": ""},
                             {"num": 2.0, "titre": "Le code d'honneur"}, {"num": 3.0, "titre": "Dog"}]}
        titres = [c["titre"] for c in sommaire._sans_faux_titres(res)["chapitres"]]
        self.assertEqual(titres, ["", "", "", "Le code d'honneur", "Dog"])

    def test_sans_chapitres(self):
        self.assertEqual(sommaire._sans_faux_titres({"chapitres": []}), {"chapitres": []})
        self.assertIsNone(sommaire._sans_faux_titres(None))


if __name__ == "__main__":
    unittest.main()
