"""✂️ Recadrer et aligner : bords du papier, même taille pour toutes les pages, bandes d'ombre coupées, aucun zoom, pages d'une autre taille ou sans bande laissées tranquilles."""
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import optimiser  # noqa: E402
import reliure  # noqa: E402

H, W = 1080, 636


def page(gauche=0, droite=0, haut=0, bas=0, dy=0):
    """Une page de manga : papier clair, un cadre, des bandes sombres de largeur donnée (ombre de la page voisine, bande du scanner) sur les bords."""
    g = np.full((H, W), 235, np.uint8)
    cv2.rectangle(g, (60, 70 + dy), (560, 1000 + dy), 20, 4)
    cv2.putText(g, "70", (80, 1050), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 30, 2)
    if gauche:
        g[:, :gauche] = 70
    if droite:
        g[:, W - droite:] = 80
    if haut:
        g[:haut, :] = 75
    if bas:
        g[H - bas:, :] = 90
    return g


class BordsTest(unittest.TestCase):
    def test_les_bandes_sombres_du_bord_sont_reperees(self):
        x0, y0, x1, y1 = reliure.bords_page(page(gauche=25, droite=15, bas=12))
        self.assertTrue(25 <= x0 <= 31, x0)
        self.assertTrue(W - 21 <= x1 <= W - 15, x1)
        self.assertEqual(y0, 0)
        self.assertTrue(H - 18 <= y1 <= H - 12, y1)

    def test_page_sans_bande_ni_trop_large_pas_touchee(self):
        self.assertEqual(reliure.bords_page(page()), (0, 0, W, H))
        self.assertEqual(reliure.bords_page(page(gauche=120))[0], 0)             # plus de 8 % : ce n'est plus une bande du scanner, on ne devine pas
        noire = np.full((H, W), 40, np.uint8)
        self.assertEqual(reliure.bords_page(noire), (0, 0, W, H))

    def test_le_numero_de_page_et_le_cadre_sont_gardes(self):
        x0, y0, x1, y1 = reliure.bords_page(page(gauche=25, bas=12))
        self.assertLessEqual(x0, 40)
        self.assertGreaterEqual(y1, 1060)                                       # le « 70 » de la ligne 1050 est dans la zone gardée


class CadreTest(unittest.TestCase):
    def _tome(self):
        return [page(gauche=(i * 7) % 40, droite=(i * 5) % 25, bas=4 + (i * 3) % 14, dy=(i % 5) - 2) for i in range(14)]

    def test_pas_assez_de_pages_pas_de_cadre_commun(self):
        self.assertIsNone(reliure.cadre_tome([page(gauche=20) for _ in range(3)]))
        self.assertIsNone(reliure.cadre_tome([]))

    def test_toutes_les_pages_ont_la_meme_taille_sans_zoom_et_sans_bande(self):
        pages = self._tome()
        cadre = reliure.cadre_tome(pages)
        self.assertIsNotNone(cadre)
        self.assertLess(cadre["w"], W)
        self.assertLess(cadre["h"], H)
        sorties = [reliure.recadrer(g, cadre) for g in pages]
        self.assertEqual({s.shape for s in sorties}, {(cadre["h"], cadre["w"])})
        for g, s in zip(pages, sorties):
            self.assertGreater(int(s[:, :4].mean()), 200)                       # plus de bande sombre à gauche
            self.assertGreater(int(s[-3:, :].mean()), 200)                      # ni en bas
            self.assertGreater(int(s[:, -4:].mean()), 200)                      # ni à droite
        # pas de zoom : le cadre dessiné garde sa largeur de 500 px partout
        for s in sorties:
            ligne = s[s.shape[0] // 2]
            sombres = np.where(ligne < 60)[0]
            self.assertAlmostEqual(int(sombres.max() - sombres.min()), 500 + 3, delta=2)

    def test_page_d_une_autre_taille_rendue_telle_quelle(self):
        cadre = reliure.cadre_tome(self._tome())
        petite = np.full((H // 2, W // 2), 235, np.uint8)
        self.assertIs(reliure.recadrer(petite, cadre), petite)

    def test_double_page_gardee_prend_la_hauteur_des_pages_simples(self):
        cadre = reliure.cadre_tome(self._tome())
        double = np.hstack([page(gauche=30, bas=12, dy=3), page(droite=25, bas=12, dy=3)])
        sortie = reliure.recadrer(double, cadre)
        self.assertEqual(sortie.shape[0], cadre["h"])                            # même hauteur que les simples
        self.assertLess(sortie.shape[1], double.shape[1])                        # bandes des deux bords coupées
        self.assertGreater(sortie.shape[1], 1.8 * cadre["w"])                    # mais toujours une double page, sans zoom
        self.assertGreater(int(sortie[:, :4].mean()), 200)
        self.assertGreater(int(sortie[:, -4:].mean()), 200)

    def test_dans_ameliorer_le_reglage_recadrer_agit_seulement_avec_un_cadre(self):
        cadre = reliure.cadre_tome(self._tome())
        im = Image.fromarray(page(gauche=20))
        sortie = optimiser.ameliorer(im, "0,0,0,0,0,0,0,0,0,0,0,0,0,1", cadre=cadre)
        self.assertEqual(sortie.size, (cadre["w"], cadre["h"]))
        self.assertIs(optimiser.ameliorer(im, "0,0,0,0,0,0,0,0,0,0,0,0,0,1"), im)       # sans cadre mesuré : rien ne change
        self.assertEqual(optimiser.reglages_amelioration("0,0,0,0,0,0,0,0,0,0,0,0,0,9")["recadrer"], 1)
        self.assertEqual(optimiser.reglages_amelioration("0,0,0,0,0,0,0,0,0,0,2,1,1")["recadrer"], 0)   # anciennes chaînes de 13 valeurs


if __name__ == "__main__":
    unittest.main()
