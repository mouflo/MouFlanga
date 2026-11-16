"""Sommaire qui ne donne que « Chapitre N titre », sans numéro de page (Nori Taka)."""
import unittest

import sommaire

LU = """NOROTAHA LE ROLDE LABAETON
Chapitre L LE POINT FAIBLE DE KIRAWEA..?! |
Chapitre 2 L'ENTRAÎNEMENT HOMO :
Chapitre 3 LE MATCH D'ENTRAÎNEMENT SPÉCIAL |
DE KIRAWEA
Chapitre 4 LE RÉSULTAT DES ÉTUDES
Chapitre S LES DEUX COACHS FONT LA PAIRE
Chapitre & 2 JOURS AVANT LE MATCH
Chapitre 1 DÉBUT DU MATCH !
Chapitre 8 LES ATTAQUES DE MAÎTRE DE SAWAMURA
Chapitre 9 KIRAWEA SUR LE CARREAU ?!"""


class ListeSansPagesTest(unittest.TestCase):
    def test_numeros_remis_d_apres_la_suite(self):
        liste = sommaire.liste_sans_pages(LU)
        self.assertEqual([c["num"] for c in liste], [float(n) for n in range(1, 10)])
        self.assertEqual(liste[5]["titre"], "2 JOURS AVANT LE MATCH")       # le « 2 » du titre n'est pas une page
        self.assertEqual(liste[2]["titre"], "LE MATCH D'ENTRAÎNEMENT SPÉCIAL DE KIRAWEA")

    def test_sommaire_ordinaire_laisse_au_lecteur_habituel(self):
        self.assertEqual(sommaire.liste_sans_pages("Chapitre 1 Le début 5\nChapitre 2 La suite 25\nChapitre 3 La fin 47\nChapitre 4 Encore 69"), [])

    def test_trop_peu_de_lignes(self):
        self.assertEqual(sommaire.liste_sans_pages("Chapitre 1 Le début\nChapitre 2 La suite"), [])

    def test_places_estimees_entre_les_ouvertures_trouvees(self):
        ch = [{"num": float(n), "titre": "x", "page": None, "image": i} for n, i in zip(range(1, 10), [None, None, 23, 41, None, None, 63, 73, None])]
        sommaire._estimer_places(ch, 3, 93)
        images = [c["image"] for c in ch]
        self.assertEqual(images[2:4] + images[6:8], [23, 41, 63, 73])
        self.assertTrue(all(b > a for a, b in zip(images, images[1:])))
        self.assertEqual([bool(c.get("estimee")) for c in ch], [True, True, False, False, True, True, False, False, True])

    def test_pages_incroyables(self):
        ch = lambda pages: [{"page": p} for p in pages]
        self.assertTrue(sommaire._pages_credibles(ch([5, 25, 47, 69, 91]), 100))
        self.assertFalse(sommaire._pages_credibles(ch([1, 4, 7, 76, 402, 727, 872, 1017, 1163]), 92))   # Nori Taka tome 16
        self.assertFalse(sommaire._pages_credibles(ch([2, 9]), 93))

    def test_une_seule_ouverture_rien_n_est_estime(self):
        ch = [{"num": 1.0, "titre": "x", "page": None, "image": None}, {"num": 2.0, "titre": "y", "page": None, "image": 30},
              {"num": 3.0, "titre": "z", "page": None, "image": None}]
        sommaire._estimer_places(ch, 2, 90)
        self.assertEqual([c["image"] for c in ch], [None, 30, None])


if __name__ == "__main__":
    unittest.main()
