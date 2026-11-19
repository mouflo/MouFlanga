"""✏️ Cadre redessiné après un rognage à la main au ras des cases (rognage.traits_coupe)."""
import unittest

import cv2
import numpy as np
from PIL import Image

import rognage


def page():
    """Page 400 × 600 : une case encadrée (trait de 2 px) remplie d'un dessin, marge blanche autour, une tranche parasite à droite."""
    g = np.full((600, 400), 245, np.uint8)
    cv2.rectangle(g, (40, 40), (340, 560), 15, 2)
    for k in range(50, 330, 12):
        cv2.line(g, (k, 50), (k + 40, 550), 60, 3)          # du dessin jusqu'aux bords de la case
    g[:, 375:378] = 80                                        # tranche des pages voisines
    return g


class TraitsCoupeTest(unittest.TestCase):
    def test_coupe_dans_la_case_redessine_le_cadre(self):
        g = page()
        cadre = g[40:561, 40:300].copy()                       # coupé au ras à droite, à travers le dessin (le trait de droite de la case est perdu)
        out = rognage.traits_coupe(g, cadre, 40, 40, 260, 521)
        self.assertLess(int(np.median(out[20:500, -2:])), 60)   # un trait droit tracé le long de la coupe, à droite
        self.assertEqual(int(out[200, 0]), int(cadre[200, 0]))  # à gauche, le vrai trait était déjà là : rien n'est ajouté

    def test_image_qui_va_jusqu_au_bord_du_papier_reste_ouverte(self):
        g = page()
        g[:, 340:] = 60                                         # le dessin continue jusqu'au bord du papier à droite (fond perdu)
        cadre = g[40:561, 40:300].copy()
        out = rognage.traits_coupe(g, cadre, 40, 40, 260, 521)
        self.assertTrue((out[:, -3:] == cadre[:, -3:]).all())

    def test_cadre_au_bord_de_la_page_sans_trait(self):
        g = page()
        cadre = g[0:600, 40:400].copy()
        out = rognage.traits_coupe(g, cadre, 40, 0, 360, 600)
        self.assertTrue((out[:3] == cadre[:3]).all() and (out[:, -3:] == cadre[:, -3:]).all())

    def test_rendre_page_avec_traits(self):
        im = Image.fromarray(page())
        sans = np.array(rognage.rendre_page(im, {"x": 40, "y": 40, "w": 260, "h": 521, "a": 0}, (260, 521)))
        avec = np.array(rognage.rendre_page(im, {"x": 40, "y": 40, "w": 260, "h": 521, "a": 0}, (260, 521), traits=True))
        self.assertGreater(int(np.median(sans[20:500, -1])), int(np.median(avec[20:500, -1])))


if __name__ == "__main__":
    unittest.main()
