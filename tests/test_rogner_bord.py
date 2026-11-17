"""✂️ Ce que le cadre ajoute au-delà de la page : papier clair pour une page claire, prolongement du bord pour une couverture (jamais une bande rose tirée du dessin)."""
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import optimiser  # noqa: E402


class AjoutHorsPageTest(unittest.TestCase):
    def test_couverture_au_bord_sombre_prolongee_sans_bande_claire_ou_rose(self):
        a = np.zeros((300, 200, 3), np.uint8)
        a[:] = (30, 40, 90)                                   # bord bleu sombre
        a[40:260, 30:170] = (240, 170, 180)                   # un dessin rose au milieu : c'est lui qui tirait le « ton du papier »
        sortie = np.array(optimiser._rogner_image(Image.fromarray(a), {"x": 0, "y": 0, "w": 200, "h": 360, "a": 0}))
        self.assertEqual(sortie.shape[:2], (360, 200))
        self.assertTrue((np.abs(sortie[330:].astype(int) - np.array([30, 40, 90])).max() < 8))   # le bas ajouté prolonge le bord bleu

    def test_page_claire_garde_le_ton_du_papier(self):
        a = np.full((300, 200), 238, np.uint8)
        a[100:200, 50:150] = 20
        sortie = np.array(optimiser._rogner_image(Image.fromarray(a), {"x": -10, "y": 0, "w": 220, "h": 320, "a": 0}))
        self.assertEqual(sortie.shape, (320, 220))
        self.assertTrue((sortie[:, :10] >= 230).all() and (sortie[305:] >= 230).all())

    def test_taille_exacte_et_rotation_d_une_couverture(self):
        a = np.full((300, 200, 3), (40, 40, 120), np.uint8)
        sortie = optimiser._rogner_image(Image.fromarray(a), {"x": -5, "y": -5, "w": 215, "h": 330, "a": 1.0})
        self.assertEqual(sortie.size, (215, 330))


if __name__ == "__main__":
    unittest.main()
