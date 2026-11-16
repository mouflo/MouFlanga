"""Toucher la couverture d'un tome ouvre CE tome, même si ses chapitres portent les mêmes numéros que ceux d'un autre."""
import unittest

import app


class ClesUniquesTest(unittest.TestCase):
    def test_numeros_qui_repartent_a_un(self):
        e = [{"key": "#1", "groupe": "Tome 01", "path": "a.cbz"}, {"key": "#2", "groupe": "Tome 01", "path": "a.cbz"},
             {"key": "#1", "groupe": "Tome 02", "path": "b.cbz"}, {"key": "#1", "groupe": "Tome 02", "path": "b.cbz", "debut": 40},
             {"key": "S/T03.cbz", "path": "S/T03.cbz"}]
        app._cles_uniques(e)
        cles = [x["key"] for x in e]
        self.assertEqual(len(set(cles)), 5)
        self.assertEqual(cles[:2], ["#1", "#2"])            # les premières ne changent pas : la progression déjà enregistrée reste
        self.assertEqual(cles[2], "#1@Tome 02")
        self.assertEqual(cles[4], "S/T03.cbz")


if __name__ == "__main__":
    unittest.main()
