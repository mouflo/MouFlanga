"""Tomes lus dans un nom de torrent : plages entre crochets ou parenthèses (« Tome.[1 à 100] », « (T1-T20) »)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import suivi  # noqa: E402


class PlageCrochetsTest(unittest.TestCase):
    def test_crochets(self):
        t = suivi.tomes_du_titre("One.Piece.Tome.[1 à 100].3.HS.Eichiro.Oda.FR.[CBZ]-PRiNTER.PapriKa+")
        self.assertEqual((min(t), max(t), len(t)), (1, 100, 100))

    def test_parentheses_et_tirets(self):
        self.assertEqual(suivi.tomes_du_titre("Kaf (T1-T3) FR"), {1, 2, 3})
        self.assertEqual(suivi.tomes_du_titre("Kaf [Tomes 4 à 6] FR"), {4, 5, 6})

    def test_anciennes_formes_inchangees(self):
        self.assertEqual(suivi.tomes_du_titre("One.Piece.T103.Oda.FR.[CBZ]-TONER-Paprika"), {103})
        self.assertEqual(suivi.tomes_du_titre("Kaf T01-T14"), set(range(1, 15)))
        self.assertEqual(suivi.tomes_du_titre("Air.Gear.[INTEGRAL].FR.[CBZ]-Digital1417"), set())
        self.assertEqual(suivi.tomes_du_titre("Kaf.[CBZ].2024.[1080p]"), set())


if __name__ == "__main__":
    unittest.main()
