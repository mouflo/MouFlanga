import unittest

import sommaire as S


def _lignes(n):
    return [{"num": float(k), "titre": f"Dossier {k}", "page": 5 + 18 * k} for k in range(1, n + 1)]


class NumerotationDuTomeTest(unittest.TestCase):
    NUMEROS = [91.0, 92.0, 93.0, 94.0, 95.0, 96.0, 97.0, 98.0, 99.0, 100.0, 100.5]

    def test_dossiers_de_1_a_10_dans_un_tome_91_a_100_sont_acceptes(self):
        self.assertTrue(S._compatible(_lignes(10), self.NUMEROS))

    def test_ils_reprennent_les_numeros_du_tome(self):
        lignes = S._renumeroter_du_tome(_lignes(10), self.NUMEROS)
        self.assertEqual([x["num"] for x in lignes], [91.0, 92.0, 93.0, 94.0, 95.0, 96.0, 97.0, 98.0, 99.0, 100.0])

    def test_pas_le_meme_nombre_de_lignes_refuse_comme_avant(self):
        self.assertFalse(S._compatible(_lignes(7), self.NUMEROS))      # une page de crédits « 1 à 7 » : toujours écartée

    def test_tome_normal_inchange(self):
        lignes = [{"num": float(n), "titre": "", "page": 10 * k} for k, n in enumerate(range(5, 9), 1)]
        self.assertTrue(S._compatible(lignes, [5.0, 6.0, 7.0, 8.0]))
        self.assertEqual([x["num"] for x in S._renumeroter_du_tome(lignes, [5.0, 6.0, 7.0, 8.0])], [5.0, 6.0, 7.0, 8.0])

    def test_le_mot_dossier_est_un_mot_de_chapitre(self):
        r = S.analyser("SOMMAIRE\nDOSSIER 1 Le décalage horaire 5\nDOSSIER 2 Le fameux détective de l'Ouest 23\nDOSSIER 3 Deux raisonnements 41")
        self.assertEqual([x["page"] for x in r], [5, 23, 41])


if __name__ == "__main__":
    unittest.main()
