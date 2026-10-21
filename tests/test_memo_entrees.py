import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class MemoEntreesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MANGA_DIR"] = self.tmp.name
        self.dossier = Path(self.tmp.name) / "Serie"
        self.dossier.mkdir()
        self.fichier = self.dossier / "Serie - Tome 01.cbz"
        self.fichier.write_bytes(b"x")
        sys.modules.pop("app", None)
        import app
        self.A = app
        self.patch = mock.patch.object(app, "MANGA_DIR", Path(self.tmp.name))   # jamais la vraie bibliothèque
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_signature_change_avec_les_infos(self):
        avant = self.A._signature_entrees([self.fichier])
        (self.dossier / ".mouflanga-infos.json").write_text("{}")
        apres = self.A._signature_entrees([self.fichier])
        self.assertNotEqual(avant, apres)

    def test_plusieurs_series_pas_gardees(self):
        autre = Path(self.tmp.name) / "Autre"
        autre.mkdir()
        f2 = autre / "Autre - Tome 01.cbz"
        f2.write_bytes(b"x")
        self.assertIsNone(self.A._signature_entrees([self.fichier, f2]))

    def test_les_entrees_gardees_ne_sont_pas_partagees(self):
        with mock.patch.object(self.A, "_entrees_calculees", return_value=[{"key": "a", "tome": 1}]) as calcul:
            premiere = self.A._entrees([self.fichier])
            premiere[0]["tome"] = 99                       # l'appelant modifie son résultat
            seconde = self.A._entrees([self.fichier])
        self.assertEqual(calcul.call_count, 1)
        self.assertEqual(seconde[0]["tome"], 1)


if __name__ == "__main__":
    unittest.main()
