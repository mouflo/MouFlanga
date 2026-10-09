"""Hors-série : les fichiers HS, Data Book, artbook et one-shot sont regroupés à part, en premier."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as A  # noqa: E402


class HorsSerieTest(unittest.TestCase):
    def test_reconnu(self):
        for nom in ("One Piece HS - Blue (Oda) (2005) [Digital-1920] (PRiNTER-PapriKa+)",
                    "Seven Deadly Sins Data Book", "Kenshin Artbook", "Bakuman one-shot", "Seven_Deadly_Sins_-_HS1"):
            self.assertTrue(A._est_hors_serie(nom), nom)

    def test_tome_normal_non(self):
        for nom in ("One Piece - Tome 105", "Hunter x Hunter Tome 01", "Dandadan T04"):
            self.assertFalse(A._est_hors_serie(nom), nom)

    def test_titre_court(self):
        self.assertEqual(A._titre_hors_serie("One Piece HS - Yellow (Oda) (2009) [Digital-1920] [Manga FR] (PRiNTER-PapriKa+)"),
                         "Yellow (Oda) (2009)")


if __name__ == "__main__":
    unittest.main()
