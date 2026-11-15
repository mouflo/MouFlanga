"""Un chapitre présent à la fin d'un tome et au début du suivant est signalé (jamais corrigé tout seul)."""
import unittest

import chapitres_auto as ca


def tome(nums, estimes=(), valide=False):
    lu = {"chapitres": [{"num": n, "titre": f"Chapitre {n}", "page": 10 * i + 5, "image": 10 * i + 4, "confirme": True,
                         **({"estimee": True} if n in estimes else {})} for i, n in enumerate(nums)]}
    if valide:
        lu["valide_le"] = "2026-11-01"
    return lu


class DoublonsTest(unittest.TestCase):
    def test_fin_estimee_du_tome_precedent(self):
        b = ca.bilan_serie({"2": tome(range(21, 32), estimes=[31]), "3": tome(range(31, 41))}, [2, 3])
        self.assertEqual(b["a_verifier"], [2])
        self.assertIn("le chapitre 31 est aussi au début du tome 3", b["par_tome"]["2"]["raisons"])
        self.assertNotEqual(b["par_tome"]["3"]["niveau"], "a_verifier")

    def test_sinon_le_second_tome(self):
        b = ca.bilan_serie({"2": tome(range(21, 32)), "3": tome(range(31, 41))}, [2, 3])
        self.assertEqual(b["a_verifier"], [3])
        self.assertEqual(sum(b["comptes"].values()), 2)

    def test_tome_valide_jamais_signale(self):
        b = ca.bilan_serie({"2": tome(range(21, 32), valide=True), "3": tome(range(31, 41), valide=True)}, [2, 3])
        self.assertEqual(b["a_verifier"], [])
        self.assertEqual(b["par_tome"]["3"]["niveau"], "valide")

    def test_suite_normale_et_numeros_qui_repartent_a_un(self):
        self.assertEqual(ca.bilan_serie({"1": tome(range(1, 11)), "2": tome(range(11, 21))}, [1, 2])["a_verifier"], [])
        self.assertEqual(ca.bilan_serie({"1": tome(range(1, 9)), "2": tome(range(1, 9))}, [1, 2])["a_verifier"], [])


if __name__ == "__main__":
    unittest.main()
