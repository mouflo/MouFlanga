"""Éditions spéciales (« Gantz - Perfect Édition ») : nom de dossier séparé, identification sur le titre de base,
et l'apprentissage des noms ne retire plus un mot vu une seule fois."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as A  # noqa: E402
import tomes  # noqa: E402


class EditionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ancien = A.CHOIX
        A.CHOIX = Path(self.tmp.name) / "choix.json"
        A.CHOIX.write_text(json.dumps([{"dossier": "Cat's Eye Édition de luxe", "propose": "Cat's Eye Édition de luxe", "choisi": "Cat's Eye"},
                                       {"dossier": "x", "propose": "Truc - Bidule", "choisi": "Truc Bidule"}]))
        self.officiel = mock.patch.object(A, "_titre_officiel", side_effect=lambda t: t)
        self.officiel.start()

    def tearDown(self):
        self.officiel.stop()
        A.CHOIX = self.ancien
        self.tmp.cleanup()

    def test_variantes_sans_edition(self):
        self.assertEqual(tomes._variantes("Gantz : Perfect"), ["Gantz : Perfect", "Gantz"])
        self.assertEqual(tomes._variantes("Cat's Eye Édition de luxe")[1], "Cat's Eye")
        self.assertEqual(tomes._variantes("Perfect Blue"), ["Perfect Blue"])

    def test_appris_garde_tirets_et_editions(self):
        self.assertEqual(A._appris("autre", "Gantz - Perfect Édition"), "Gantz - Perfect Édition")

    def test_autre_edition_d_une_serie_presente(self):
        n = "Gantz - Perfect Édition (01-18) (Oku) (2017) [Digital-1920u] (PapriKa+).rar"
        self.assertEqual(A._nom_depuis_archive(n, ["Gantz", "Gantz : Osaka PDF"]), "Gantz : Perfect Édition")
        self.assertEqual(A._nom_depuis_archive("Gantz Perfect Edition T01-18.rar", ["Gantz"]), "Gantz : Perfect Edition")
        self.assertEqual(A._nom_depuis_archive("Gantz T01-37.rar", ["Gantz"]), "Gantz")
        self.assertEqual(A._nom_depuis_archive(n, []), "Gantz")      # pas d'autre édition : nom de la série seule


if __name__ == "__main__":
    unittest.main()
