"""Un angle réglé à la main est l'angle FINAL de la page : pas de redressement automatique par-dessus (rognage.rendre_redressee)."""
import unittest
from unittest import mock

import numpy as np
from PIL import Image

import rognage
import reliure


class AngleFinalTest(unittest.TestCase):
    def _page(self):
        a = np.full((400, 300), 240, np.uint8)
        a[100:110, :] = 20                                 # un trait horizontal
        return Image.fromarray(a, "L")

    def test_angle_manuel_sans_correction_automatique(self):
        im = self._page()
        boite = {"x": 10, "y": 10, "w": 250, "h": 350, "a": 1.5}
        taille = (250, 350)
        with mock.patch.object(reliure, "redressement", return_value={"genre": "rotation", "p": [0.9, 0, 0, 0]}) as auto:
            sortie = rognage.rendre_redressee(im, boite, taille)
        auto.assert_not_called()                           # la correction automatique n'est même pas essayée
        attendu = rognage.rendre_page(im, boite, taille)
        self.assertEqual(np.asarray(sortie).tolist(), np.asarray(attendu).tolist())

    def test_sans_angle_manuel_la_correction_automatique_reste(self):
        im = self._page()
        boite = {"x": 10, "y": 10, "w": 250, "h": 350, "a": 0.0}
        with mock.patch.object(reliure, "redressement", return_value=None) as auto:
            rognage.rendre_redressee(im, boite, (250, 350))
        auto.assert_called_once()


if __name__ == "__main__":
    unittest.main()
