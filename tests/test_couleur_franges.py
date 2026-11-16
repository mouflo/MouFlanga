"""Détection de la couleur : les franges de couleur du scanner ne font pas une page en couleur, une vraie zone de couleur si."""
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import optimiser  # noqa: E402


def page_grise(h=1080, w=636):
    a = np.full((h, w, 3), 235, np.uint8)
    for y0, y1 in ((60, 480), (520, 1020)):                      # deux cases cadrées de noir
        a[y0:y0 + 4, 40:w - 40] = 20
        a[y1:y1 + 4, 40:w - 40] = 20
        a[y0:y1, 40:44] = 20
        a[y0:y1, w - 44:w - 40] = 20
    return a


class FrangesTest(unittest.TestCase):
    def test_franges_rouges_et_vertes_le_long_des_traits_ne_sont_pas_de_la_couleur(self):
        a = page_grise()
        a[58:60, 60:600] = (230, 40, 40)           # liseré rouge sur un trait horizontal (1 à 2 px)
        a[1020:1023, 40:600] = (30, 200, 60)
        a[520:521, 40:600] = (240, 60, 60)
        a[:, 0:2] = (0, 160, 0)                                         # bord de page : un reste de couverture
        a[-2:, :] = (220, 40, 40)
        self.assertFalse(optimiser.est_couleur(Image.fromarray(a)))

    def test_une_vraie_zone_de_couleur_reste_de_la_couleur(self):
        a = page_grise()
        a[100:300, 100:400] = (200, 20, 30)                             # une grande zone rouge : environ 9 % de la page
        self.assertTrue(optimiser.est_couleur(Image.fromarray(a)))

    def test_petit_accent_de_couleur_laisse_la_page_en_noir_et_blanc(self):
        a = page_grise()
        a[700:760, 100:230] = (180, 10, 20)                             # ≈ 1,1 % de la page (le « D » rouge d'un titre : la page reste noir et blanc)
        self.assertFalse(optimiser.est_couleur(Image.fromarray(a)))

    def test_page_teintee_mais_grise_et_page_en_niveaux_de_gris(self):
        jaune = page_grise().astype(np.int16)
        jaune[..., 2] -= 12                                              # papier un peu jauni : écart faible partout
        self.assertFalse(optimiser.est_couleur(Image.fromarray(np.clip(jaune, 0, 255).astype(np.uint8))))
        self.assertFalse(optimiser.est_couleur(Image.fromarray(page_grise()[..., 0])))


if __name__ == "__main__":
    unittest.main()
