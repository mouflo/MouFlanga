"""✂️ Propositions de bords : trait du bord le plus intérieur, cohérent avec les pages de même parité, angle dans le bon sens, rien proposé quand rien n'est sûr."""
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
import bords_pages  # noqa: E402
import optimiser  # noqa: E402

H, W = 1000, 600


def page(g=40, d=560, pente=0.0, bande=True, trait_gauche=True, trait_droit=True):
    """Une page claire avec un trait de bord à gauche et à droite (qui penche de `pente` degrés : x augmente avec y), la bande de la page voisine derrière."""
    im = np.full((H, W), 240, np.uint8)
    k = np.tan(np.radians(pente))
    for cote, x, present in (("g", g, trait_gauche), ("d", d, trait_droit)):
        if present:
            cv2.line(im, (int(round(x - k * H / 2)), 0), (int(round(x + k * H / 2)), H - 1), 20, 2)
    if bande:
        im[:, d + 12:] = 150
    cv2.putText(im, "12", (250, 960), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 30, 2)
    return im


def cbz(dossier, pages):
    chemin = Path(dossier) / "Serie - Tome 01.cbz"
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_STORED) as z:
        for i, g in enumerate(pages, 1):
            out = io.BytesIO()
            Image.fromarray(g).save(out, "PNG")
            z.writestr(f"{i:04d}.png", out.getvalue())
    return chemin


class TraitTest(unittest.TestCase):
    def test_le_trait_du_bord_est_trouve_a_quelques_pixels(self):
        g = page(g=44, d=557)
        self.assertAlmostEqual(bords_pages.trait_bord(g, "gauche")["xm"], 44, delta=3)
        self.assertAlmostEqual(bords_pages.trait_bord(g, "droite")["xm"], 557, delta=3)

    def test_deux_traits_c_est_le_plus_interieur_qui_gagne(self):
        g = page(d=560)
        cv2.line(g, (585, 0), (585, H - 1), 20, 2)                                   # un liseré plus à l'extérieur, dans la bande de la page voisine
        self.assertAlmostEqual(bords_pages.trait_bord(g, "droite")["xm"], 560, delta=3)

    def test_pas_de_trait_pas_de_bord(self):
        self.assertIsNone(bords_pages.trait_bord(page(trait_gauche=False, trait_droit=False), "droite"))


class ProposerTest(unittest.TestCase):
    def _tome(self, d, **autres):
        pages = [page(g=40 + (i % 5), d=560 + (i % 7) - 3) for i in range(14)]
        for i, g in autres.items():
            pages[int(i[1:])] = g
        return cbz(d, pages)

    def test_chaque_page_a_ses_bords_et_la_largeur_commune_est_donnee(self):
        with tempfile.TemporaryDirectory() as d:
            r = bords_pages.proposer(self._tome(d))
            self.assertEqual(len(r["pages"]), 14)
            self.assertAlmostEqual(r["largeur"], 520, delta=8)
            self.assertAlmostEqual(r["pages"][3]["g"], 43, delta=3)
            self.assertEqual(r["analysees"], 14)

    def test_un_bord_trop_different_des_pages_de_meme_parite_n_est_pas_propose(self):
        with tempfile.TemporaryDirectory() as d:
            r = bords_pages.proposer(self._tome(d, p4=page(g=40, d=480)))              # le trait droit est à 80 px de là où il est d'habitude
            self.assertIsNone(r["pages"][4]["d"])
            self.assertIsNotNone(r["pages"][4]["g"])                                    # le côté gauche, lui, reste proposé

    def test_page_sans_trait_ni_double_page_ne_recoit_rien(self):
        with tempfile.TemporaryDirectory() as d:
            vide = page(trait_gauche=False, trait_droit=False, bande=False)
            double = np.full((H, 1300), 240, np.uint8)
            r = bords_pages.proposer(self._tome(d, p2=vide, p6=double))
            self.assertNotIn(2, r["pages"])
            self.assertNotIn(6, r["pages"])                                             # double page : ni analysée ni proposée
            self.assertEqual(r["analysees"], 13)

    def test_l_angle_propose_redresse_vraiment_la_page(self):
        with tempfile.TemporaryDirectory() as d:
            pages = [page(g=40, d=560, pente=0.8) for _ in range(14)]
            c = cbz(d, pages)
            prop = bords_pages.proposer(c)["pages"][0]
            self.assertAlmostEqual(prop["a"], 0.8, delta=0.25)                          # bords en « \ » : tourner dans le sens horaire (positif)
            im = Image.fromarray(pages[0])
            droit = np.array(optimiser._rogner_image(im, {"x": 0, "y": 0, "w": W, "h": H, "a": prop["a"]}).convert("L"))
            apres = bords_pages.trait_bord(droit, "droite")
            self.assertIsNotNone(apres)
            self.assertLess(abs(apres["pente"]), 0.3)                                   # le bord est maintenant vertical

    def test_resultat_gardé_tant_que_le_fichier_ne_change_pas(self):
        with tempfile.TemporaryDirectory() as d:
            c = self._tome(d)
            a = bords_pages.proposer(c)
            self.assertIs(bords_pages.proposer(c), a)


if __name__ == "__main__":
    unittest.main()
