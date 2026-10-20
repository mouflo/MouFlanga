import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import deux_tomes


class NumerosTest(unittest.TestCase):
    def test_deux_tomes(self):
        self.assertEqual(deux_tomes.numeros("Kenichi T45-46 (Matsuena) [Digital-1088] [Manga FR]"), (45, 46))
        self.assertEqual(deux_tomes.numeros("Kenichi T57-58 (Matsuena) (2018) [Digital-1920] [Manga FR] (PapriKa)"), (57, 58))
        self.assertEqual(deux_tomes.numeros("Serie Tomes 3 et 4"), (3, 4))

    def test_pas_deux_tomes(self):
        self.assertIsNone(deux_tomes.numeros("Gintama T01-29"))              # lot de plusieurs tomes
        self.assertIsNone(deux_tomes.numeros("Kenichi T45"))
        self.assertIsNone(deux_tomes.numeros("Kenichi T45-48"))
        self.assertIsNone(deux_tomes.numeros("Serie (2018) [Digital-1920]"))


class SeparerTest(unittest.TestCase):
    def _cbz(self, dossier, nb):
        f = Path(dossier) / "Serie T1-2.cbz"
        with zipfile.ZipFile(f, "w") as z:
            for i in range(nb):
                z.writestr(f"{i + 1:03d}.jpg", f"page{i}".encode())
        return f

    def test_coupe_avant_le_sommaire(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._cbz(d, 120)
            cibles = [Path(d) / "a" / "T1.cbz", Path(d) / "b" / "T2.cbz"]
            ocr = lambda lire, i: "TABLE DES MATIÈRES" if i == 61 else "du texte"
            with mock.patch.object(deux_tomes, "_texte", ocr):
                self.assertTrue(deux_tomes.separer(f, cibles))
            self.assertEqual(len(zipfile.ZipFile(cibles[0]).namelist()), 60)
            self.assertEqual(len(zipfile.ZipFile(cibles[1]).namelist()), 60)
            self.assertEqual(zipfile.ZipFile(cibles[1]).read("0001.jpg"), b"page60")

    def test_coupe_par_le_chapitre(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._cbz(d, 120)
            cibles = [Path(d) / "a.cbz", Path(d) / "b.cbz"]
            textes = {70: "BATAILLE 448\nVENGEANCE", 69: "TABLE DES MATIÈRES"}
            with mock.patch.object(deux_tomes, "_texte", lambda l, i: textes.get(i, "texte")):
                self.assertTrue(deux_tomes.separer(f, cibles, 448))
            self.assertEqual(len(zipfile.ZipFile(cibles[0]).namelist()), 68)      # titre + sommaire partent avec le second tome

    def test_sans_sommaire_rien_n_est_coupe(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._cbz(d, 120)
            cibles = [Path(d) / "a.cbz", Path(d) / "b.cbz"]
            with mock.patch.object(deux_tomes, "_texte", lambda l, i: "du texte"):
                self.assertFalse(deux_tomes.separer(f, cibles))
            self.assertFalse(cibles[0].exists() or cibles[1].exists())

    def test_n_ecrase_jamais(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._cbz(d, 120)
            cibles = [Path(d) / "a.cbz", Path(d) / "b.cbz"]
            cibles[1].write_bytes(b"existant")
            with mock.patch.object(deux_tomes, "_texte", lambda l, i: "TABLE DES MATIÈRES" if i == 61 else ""):
                self.assertFalse(deux_tomes.separer(f, cibles))
            self.assertEqual(cibles[1].read_bytes(), b"existant")
            self.assertFalse(cibles[0].exists())


if __name__ == "__main__":
    unittest.main()
