"""📖 Reliure : ombre du dos éclaircie, page redressée d'après ses bords de cases, bandes noires du scanner enlevées, rien touché quand il n'y a pas de défaut."""
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import optimiser  # noqa: E402
import reliure  # noqa: E402


def page_a_cases(h=900, w=600, papier=235):
    """Une page avec deux cases cadrées de traits noirs (de quoi mesurer une inclinaison)."""
    g = np.full((h, w), papier, np.uint8)
    for (y0, y1) in ((40, 420), (460, 860)):
        cv2.rectangle(g, (40, y0), (w - 40, y1), 20, 3)
    cv2.line(g, (w // 2, 460), (w // 2, 860), 20, 3)
    return g


def avec_ombre(g, cote_gauche=0.75, largeur=0.25):
    """Papier assombri vers le bord gauche : 75 % au bord, 100 % à 25 % de la largeur."""
    w = g.shape[1]
    x = np.arange(w) / w
    facteur = np.clip(cote_gauche + (1 - cote_gauche) * x / largeur, 0, 1)
    return np.clip(g.astype(np.float32) * facteur.reshape(1, -1), 0, 255).astype(np.uint8)


def papier_colonnes(g):
    return np.percentile(g, 85, axis=0)


class OmbreDuDosTest(unittest.TestCase):
    def test_le_bord_sombre_est_eclairci_le_centre_ne_bouge_pas(self):
        g = avec_ombre(page_a_cases())
        avant = papier_colonnes(g)
        apres = papier_colonnes(reliure.ombre_dos(g, 2))
        self.assertLess(avant[:20].mean() / avant[300], 0.8)                       # le défaut est bien là
        self.assertGreater(apres[:20].mean() / apres[300], 0.96)                   # corrigé
        self.assertLessEqual(abs(float(apres[250:350].mean()) - float(avant[250:350].mean())), 1.0)       # le centre n'a pas changé

    def test_le_niveau_leger_corrige_moins_que_le_fort(self):
        g = avec_ombre(page_a_cases())
        leger, fort = (papier_colonnes(reliure.ombre_dos(g, n))[:20].mean() for n in (1, 3))
        self.assertLess(leger, fort)

    def test_page_sans_ombre_rendue_telle_quelle(self):
        g = page_a_cases()
        self.assertTrue(np.array_equal(reliure.ombre_dos(g, 3), g))

    def test_page_sombre_non_touchee(self):
        noire = np.full((600, 400), 60, np.uint8)
        self.assertTrue(np.array_equal(reliure.ombre_dos(avec_ombre(noire), 3), avec_ombre(noire)))

    def test_double_page_chaque_moitie_a_son_dos(self):
        gauche = avec_ombre(page_a_cases(w=800))[:, ::-1]                           # la page de gauche s'assombrit vers sa droite (le dos)
        droite = avec_ombre(page_a_cases(w=800))                                    # celle de droite vers sa gauche
        double = np.hstack([gauche, droite])
        m = 800                                                                    # deux pages de 800 px : plus large que haute, donc reconnue comme une double page
        avant, apres = papier_colonnes(double), papier_colonnes(reliure.ombre_dos(double, 2))
        self.assertLess(avant[m - 15:m + 15].mean() / avant[m // 2], 0.8)             # le dos est sombre au milieu
        self.assertGreater(apres[m - 15:m + 15].mean() / apres[m // 2], 0.96)         # éclairci des deux côtés du dos
        self.assertLessEqual(abs(float(apres[200:300].mean()) - float(avant[200:300].mean())), 1.0)


class BordsNoirsTest(unittest.TestCase):
    def test_bandes_etroites_effacees(self):
        g = page_a_cases()
        g[:3] = 10
        g[:, :4] = 15
        sortie = reliure.bords_noirs(g)
        self.assertGreater(sortie[:3].mean(), 200)
        self.assertGreater(sortie[:, :4].mean(), 200)
        self.assertTrue(np.array_equal(sortie[10:, 10:], g[10:, 10:]))               # le reste est identique

    def test_grande_zone_noire_au_bord_est_gardee(self):
        g = page_a_cases()
        g[:, :200] = 10                                                             # page en pleine image : un aplat noir large
        self.assertTrue(np.array_equal(reliure.bords_noirs(g), g))

    def test_bord_qui_touche_un_trait_noir_du_dessin_est_garde(self):
        g = page_a_cases()
        g[:3, 100:140] = 10                                                        # un bout seulement de la ligne : ce n'est pas une bande
        self.assertTrue(np.array_equal(reliure.bords_noirs(g), g))


class RedresserTest(unittest.TestCase):
    def _tournee(self, degres_horaires):
        g = page_a_cases()
        h, w = g.shape
        m = cv2.getRotationMatrix2D((w / 2, h / 2), -degres_horaires, 1.0)             # OpenCV : positif = sens inverse ; on tourne la page dans le sens horaire
        return cv2.warpAffine(g, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=235)

    def test_la_mesure_donne_l_inclinaison_avec_son_signe(self):
        for a in (0.6, -0.8, 1.5):
            mesure = reliure.angle_page(self._tournee(a))
            self.assertIsNotNone(mesure, a)
            self.assertAlmostEqual(mesure, a, delta=0.15)

    def test_la_page_pivotee_est_droite(self):
        g = self._tournee(1.0)
        apres = reliure.pivoter(g, reliure.angle_page(g))
        self.assertTrue(reliure.angle_page(apres) is None or abs(reliure.angle_page(apres)) < 0.2)       # plus rien à redresser
        self.assertEqual(apres.shape, g.shape)

    def test_page_droite_trop_penchee_ou_sans_traits_ne_bouge_pas(self):
        self.assertIsNone(reliure.angle_page(page_a_cases()))                            # déjà droite
        self.assertIsNone(reliure.angle_page(self._tournee(5.0)))                        # plus de 3° : c'est peut-être le dessin
        self.assertIsNone(reliure.angle_page(np.full((900, 600), 235, np.uint8)))        # aucun trait à mesurer


class DansAmeliorerTest(unittest.TestCase):
    def test_les_trois_reglages_agissent_et_gardent_la_taille(self):
        g = avec_ombre(page_a_cases())
        g[:3] = 10
        im = Image.fromarray(g)
        sortie = np.asarray(optimiser.ameliorer(im, "0,0,0,0,0,0,0,0,0,0,2,1,1"))
        self.assertEqual(sortie.shape, g.shape)
        self.assertGreater(sortie[:3].mean(), 200)                                       # bord enlevé
        self.assertGreater(papier_colonnes(sortie)[:20].mean() / papier_colonnes(sortie)[300], 0.96)    # ombre éclaircie

    def test_anciennes_chaines_sans_reliure_inchangees(self):
        r = optimiser.reglages_amelioration("0,0,0,0,0,0,0,0,0,2")
        self.assertEqual((r["ia"], r["dos"], r["redresser"], r["bords"]), (2, 0, 0, 0))
        r = optimiser.reglages_amelioration("0,0,0,0,0,0,0,0,0,0,9,9,9")
        self.assertEqual((r["dos"], r["redresser"], r["bords"]), (3, 1, 1))              # bornés

    def test_page_en_couleur_non_touchee(self):
        couleur = Image.fromarray(np.dstack([np.full((300, 200), v, np.uint8) for v in (230, 120, 60)]))
        self.assertIs(optimiser.ameliorer(couleur, "0,0,0,0,0,0,0,0,0,0,3,1,1"), couleur)


if __name__ == "__main__":
    unittest.main()
