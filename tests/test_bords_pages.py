"""🪄 Cadres proposés pour le rognage à la main : bord de la bande voisine trouvé, cohérent avec les pages voisines, cadres réglés à la main jamais remplacés."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bords_pages  # noqa: E402


def page_scannee(w=600, h=1000, bande=None, cote="droite"):
    """Page claire avec du dessin au milieu ; « bande » : largeur de la bande de la page voisine (traits verticaux), finie par un trait sombre."""
    a = np.full((h, w), 240, np.uint8)
    a[150:850, 120:480] = 60
    if bande:
        x = w - bande if cote == "droite" else bande
        zone = slice(x, w) if cote == "droite" else slice(0, x)
        a[:, zone] = 205
        for k in range(3, bande, 6):
            xx = x + k if cote == "droite" else x - k
            a[:, xx] = 170
        a[:, x - 1:x + 2] = 40                                   # le bord de la page : trait sombre sur toute la hauteur
    return a


def faire_cbz(chemin, pages):
    with zipfile.ZipFile(chemin, "w") as z:
        for i, a in enumerate(pages, 1):
            out = io.BytesIO()
            Image.fromarray(a).save(out, "PNG")
            z.writestr(f"{i:04d}.png", out.getvalue())


class BordsTest(unittest.TestCase):
    def test_trait_du_bord_trouve(self):
        t = bords_pages.trait_bord(page_scannee(bande=40), "droite")
        self.assertIsNotNone(t)
        self.assertAlmostEqual(t["xm"], 560, delta=3)
        self.assertIsNone(bords_pages.trait_bord(page_scannee(), "droite"))     # pas de bande, pas de trait

    def test_propositions_sur_un_tome(self):
        with tempfile.TemporaryDirectory() as d:
            cbz = Path(d) / "t.cbz"
            pages = [page_scannee(bande=40 + (i % 3)) if i % 2 == 0 else page_scannee(bande=30, cote="gauche") for i in range(12)]
            pages.append(np.full((1000, 1300), 240, np.uint8))                 # une double page : jamais proposée
            faire_cbz(cbz, pages)
            mesures = bords_pages.mesurer(cbz)
        tailles = [[a.shape[1], a.shape[0]] for a in pages]
        reglee = {"x": 0, "y": 20, "w": 555, "h": 950, "a": 0.0}
        p = bords_pages.proposer(mesures, tailles, {"0": reglee, "1": dict(reglee, c=1)})
        self.assertNotIn(0, p)                                                  # un cadre réglé à la main n'est jamais remplacé
        self.assertNotIn(1, p)                                                  # ni un cadre copié
        self.assertNotIn(12, p)
        self.assertAlmostEqual(p[2]["x"] + p[2]["w"], 558, delta=4)              # bord droit : le trait
        self.assertEqual(p[2]["x"], 0)                                          # à gauche, pas de bande : le bord de la page
        self.assertAlmostEqual(p[3]["x"], 30, delta=4)
        self.assertEqual(p[3]["x"] + p[3]["w"], 600)
        self.assertEqual((p[4]["y"], p[4]["h"]), (20, 950))                     # la hauteur vient du cadre réglé à la main (même parité)
        self.assertEqual((p[3]["y"], p[3]["h"]), (20, 950))                     # (sinon les autres pages réglées)
        refaites = bords_pages.proposer(mesures, tailles, {"2": dict(p[2], x=99, d=1)})
        self.assertIn(2, refaites)                                              # une proposition pas encore revue peut être refaite


if __name__ == "__main__":
    unittest.main()
