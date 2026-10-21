import unittest

import tomes


class CarteFrancaise(unittest.TestCase):
    def test_la_liste_francaise_remplace_le_regroupement_anglais(self):
        d = {"tomes": {float(n): (n - 1) // 5 + 1 for n in range(1, 21)},              # anglais : 5 chapitres par tome
             "titres_tomes": {"details": {"1": {"chapitres": ["1. A", "2. B", "3. C"]},
                                          "2": {"chapitres": ["4. D", "5. E", "6. F", "7. G"]},
                                          "3": {"chapitres": ["8. H", "9. I", "10. J"]},
                                          "4": {"chapitres": [f"{n}. X" for n in range(11, 21)]}}}}
        c = tomes._carte_francaise(d)
        self.assertEqual((c[3.0], c[4.0], c[10.0], c[11.0]), (1, 2, 3, 4))

    def test_liste_partielle_ignoree(self):
        d = {"tomes": {float(n): 1 for n in range(1, 41)},
             "titres_tomes": {"details": {"1": {"chapitres": ["1. A"]}, "2": {"chapitres": ["2. B"]}, "3": {"chapitres": ["3. C"]}}}}
        self.assertIsNone(tomes._carte_francaise(d))

    def test_numerotation_qui_repart_a_chaque_tome_ignoree(self):
        d = {"tomes": {1.0: 1, 2.0: 1, 3.0: 2, 4.0: 2, 5.0: 3, 6.0: 3},
             "titres_tomes": {"details": {"1": {"chapitres": ["1. A", "2. B"]}, "2": {"chapitres": ["1. C", "2. D"]},
                                          "3": {"chapitres": ["1. E", "2. F"]}}}}
        self.assertIsNone(tomes._carte_francaise(d))
