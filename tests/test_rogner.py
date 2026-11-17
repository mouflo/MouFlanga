"""✂️ Rognage manuel : chaque page coupée au rectangle choisi (taille exacte, aucun zoom), tournée si demandé, les autres pages et les fichiers du tome intacts."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import optimiser  # noqa: E402


def page(w=300, h=500, marque=(100, 200)):
    g = np.full((h, w), 235, np.uint8)
    g[marque[1]:marque[1] + 20, marque[0]:marque[0] + 20] = 10                      # un carré noir repérable
    return Image.fromarray(g)


def cbz(dossier, pages, nom="Serie - Tome 01.cbz"):
    chemin = Path(dossier) / nom
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_STORED) as z:
        for i, im in enumerate(pages, 1):
            out = io.BytesIO()
            im.save(out, "PNG")
            z.writestr(f"{i:04d}.png", out.getvalue())
        z.writestr("ComicInfo.xml", "<ComicInfo><PageCount>%d</PageCount></ComicInfo>" % len(pages))
    return chemin


def lire(chemin, i):
    with zipfile.ZipFile(chemin) as z:
        return np.array(Image.open(io.BytesIO(z.read(f"{i:04d}.png"))))


class RognerTest(unittest.TestCase):
    def test_taille_exacte_position_juste_et_pages_non_demandees_intactes(self):
        with tempfile.TemporaryDirectory() as d:
            c = cbz(d, [page(), page(), page()])
            avant1 = lire(c, 1)
            res = optimiser.rogner(c, {1}, boites={1: {"x": 90, "y": 190, "w": 120, "h": 150, "a": 0}})
            self.assertEqual(lire(c, 2).shape, (150, 120))
            self.assertEqual(lire(c, 2)[10, 10], 10)                                  # le carré est à 10 px du coin : position juste
            self.assertEqual(lire(c, 1).shape, avant1.shape)                          # page 1 non demandée : intacte
            self.assertTrue(np.array_equal(lire(c, 1), avant1))
            self.assertEqual(res["pages"], 3)
            self.assertEqual(res["carte"], {0: 0, 1: 1, 2: 2})
            self.assertTrue(res["avant"].exists())                                    # l'ancien fichier est gardé
            with zipfile.ZipFile(c) as z:
                self.assertIn("ComicInfo.xml", z.namelist())

    def test_ce_qui_depasse_de_la_page_est_rempli_de_papier(self):
        with tempfile.TemporaryDirectory() as d:
            c = cbz(d, [page()])
            optimiser.rogner(c, {0}, boites={0: {"x": -20, "y": -30, "w": 340, "h": 560, "a": 0}})
            g = lire(c, 1)
            self.assertEqual(g.shape, (560, 340))
            self.assertGreater(int(g[:25, :].mean()), 200)                             # marge ajoutée au ton du papier
            self.assertEqual(g[30 + 200, 20 + 100], 10)                                # le dessin n'a pas bougé

    def test_angle_sens_horaire(self):
        with tempfile.TemporaryDirectory() as d:
            h, w = 500, 300
            g = np.full((h, w), 235, np.uint8)
            g[20:30, :] = 10                                                          # un trait horizontal en haut, à gauche comme à droite
            c = cbz(d, [Image.fromarray(g)])
            optimiser.rogner(c, {0}, boites={0: {"x": 0, "y": 0, "w": w, "h": h, "a": 3.0}})
            s = lire(c, 1)
            # tournée de 3° dans le sens horaire : le côté droit du trait descend, le côté gauche monte
            col_g = float(np.where(s[:, 40] < 100)[0].mean())
            col_d = float(np.where(s[:, w - 40] < 100)[0].mean())
            self.assertGreater(col_d, col_g + 8)

    def test_boites_vides_ou_hors_tome_refusees_et_rien_n_est_touche(self):
        with tempfile.TemporaryDirectory() as d:
            c = cbz(d, [page()])
            avant = c.read_bytes()
            with self.assertRaises(RuntimeError):
                optimiser.rogner(c, set(), boites={})
            with self.assertRaises(RuntimeError):
                optimiser.rogner(c, {9}, boites={9: {"x": 0, "y": 0, "w": 10, "h": 10, "a": 0}})
            self.assertEqual(c.read_bytes(), avant)

    def test_tailles_pages_et_image_pour_l_ecran(self):
        with tempfile.TemporaryDirectory() as d:
            c = cbz(d, [page(300, 500), page(640, 480)])
            self.assertEqual(optimiser.tailles_pages(c), [[300, 500], [640, 480]])
            grand = Image.open(io.BytesIO(optimiser.page_jpeg(c, 1, largeur=320)))
            self.assertEqual(grand.size, (320, 240))                                    # réduite seulement au-delà de la largeur demandée
            entier = Image.open(io.BytesIO(optimiser.page_jpeg(c, 0, largeur=2200)))
            self.assertEqual(entier.size, (300, 500))


if __name__ == "__main__":
    unittest.main()
