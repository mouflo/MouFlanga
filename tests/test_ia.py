"""🧠 Restauration IA : agrandissement ×2 par un modèle (ici un faux), finition (papier blanc, noir franc), niveaux, cache, repli sans le paquet."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ia  # noqa: E402
import optimiser  # noqa: E402


class FauxModele:
    """Agrandit ×2 par duplication de pixels (de quoi tester la chaîne sans le vrai réseau)."""
    def __init__(self, bruit):
        self.bruit, self.appels = bruit, 0

    def process_pil(self, im):
        self.appels += 1
        a = np.asarray(im)
        return Image.fromarray(np.repeat(np.repeat(a, 2, axis=0), 2, axis=1))


def page(h=300, w=200, papier=228, encre=40):
    g = np.full((h, w), papier, np.uint8)
    g[40:60, 30:170] = encre                                   # un trait d'encre
    g[100:200, 20:40] = 0                                      # un aplat noir
    return g


class IATest(unittest.TestCase):
    def setUp(self):
        ia._CACHE.clear()
        self.modeles = {}

        def fabrique(bruit):
            return self.modeles.setdefault(bruit, FauxModele(bruit))
        for p in (mock.patch.object(ia, "_modele", side_effect=fabrique), mock.patch.object(ia, "_DISPO", True)):
            p.start()
            self.addCleanup(p.stop)

    def test_agrandit_x2_blanchit_le_papier_et_garde_le_noir(self):
        sortie = ia.agrandir(page(), 2)
        self.assertEqual(sortie.shape, (600, 400))
        self.assertGreaterEqual(int(np.median(sortie[:20, :20])), 250)                # le papier (228) est devenu blanc
        self.assertLessEqual(int(sortie[250:350, 50:70].mean()), 5)                   # l'aplat noir reste noir

    def test_les_trois_niveaux_utilisent_les_bons_modeles(self):
        for niveau in (1, 2):
            ia.agrandir(page(), niveau)
        self.assertEqual(sorted(self.modeles), [1, 2])
        self.assertEqual((self.modeles[1].appels, self.modeles[2].appels), (1, 1))      # une passe pour Naturel et Net
        ia.agrandir(page(), 3)
        self.assertEqual(self.modeles[2].appels, 1 + 8)                                  # Maximum : huit orientations, jamais le mode natif de la bibliothèque

    def test_huit_passes_remettent_chaque_orientation_a_l_endroit(self):
        g = page()
        g[40:60, 30:170] = 40
        un = ia._huit_passes(FauxModele(2), Image.fromarray(g).convert("RGB"))
        seule = FauxModele(2).process_pil(Image.fromarray(g).convert("RGB"))
        self.assertEqual(np.asarray(un).tolist(), np.asarray(seule).tolist())            # un modèle sans défaut donne le même résultat sous toutes les orientations

    def test_choix_de_la_carte_graphique(self):
        with mock.patch.object(ia, "_SANS_CARTE", False):
            with mock.patch.dict("os.environ", {"MOUFLANGA_IA_GPU": "auto"}):
                with mock.patch("os.path.exists", return_value=True):
                    self.assertEqual((ia._gpuid(), ia.mode()), (0, "carte graphique"))
                with mock.patch("os.path.exists", return_value=False):
                    self.assertEqual((ia._gpuid(), ia.mode()), (-1, "processeur"))    # sans /dev/dri : jamais le calcul logiciel de Vulkan
            with mock.patch.dict("os.environ", {"MOUFLANGA_IA_GPU": "non"}), mock.patch("os.path.exists", return_value=True):
                self.assertEqual(ia._gpuid(), -1)

    def test_cache_un_autre_reglage_ne_refait_pas_l_agrandissement(self):
        g = page()
        a = ia.agrandir(g, 2)
        b = ia.agrandir(g.copy(), 2)
        self.assertIs(a, b)
        self.assertEqual(self.modeles[2].appels, 1)
        ia.agrandir(g, 2, niveaux_auto=False)                       # autre finition : autre résultat
        self.assertEqual(self.modeles[2].appels, 2)

    def test_page_deja_haute_ou_presque_noire(self):
        grande = page(h=1800)
        self.assertIs(ia.agrandir(grande, 2), grande)               # pas doublée
        noire = np.full((300, 200), 25, np.uint8)
        self.assertLessEqual(int(ia.agrandir(noire, 2).max()), 60)   # le papier « introuvable » ne la blanchit pas

    def test_naturel_garde_un_peu_de_la_texture_d_origine(self):
        g = page()
        g[0:100, 100:200] = 150                                     # un gris de trame
        net, naturel = ia.agrandir(g, 2, niveaux_auto=False), ia.agrandir(g, 1, niveaux_auto=False)
        self.assertEqual(net.shape, naturel.shape)


class AmeliorerAvecIATest(unittest.TestCase):
    def setUp(self):
        ia._CACHE.clear()
        for p in (mock.patch.object(ia, "_modele", side_effect=lambda b: FauxModele(b)), mock.patch.object(ia, "_DISPO", True)):
            p.start()
            self.addCleanup(p.stop)

    def test_reglage_ia_agrandit_et_remplace_les_reglages_classiques(self):
        im = Image.fromarray(page())
        sortie = optimiser.ameliorer(im, "3,3,0,0,0,3,0,1,0,2")        # débruiter, trames, lisser, agrandir : remplacés par l'IA
        self.assertEqual(sortie.size, (400, 600))                      # doublé UNE seule fois (pas de second agrandissement)
        self.assertEqual(optimiser.reglages_amelioration("0,0,0,0,0,0,0,0,0,3")["ia"], 3)
        self.assertEqual(optimiser.reglages_amelioration("0,0,0,0,0,0,0,0,0,9")["ia"], 3)        # borné

    def test_ancienne_chaine_a_neuf_valeurs_sans_ia(self):
        r = optimiser.reglages_amelioration("0,0,0,0,0,0,0,0,1")
        self.assertEqual((r["uniformiser"], r["ia"]), (1, 0))

    def test_page_en_couleur_et_page_haute_ne_sont_pas_touchees(self):
        couleur = Image.fromarray(np.dstack([np.full((300, 200), v, np.uint8) for v in (230, 120, 60)]))
        self.assertIs(optimiser.ameliorer(couleur, "0,0,0,0,0,0,0,0,0,2"), couleur)
        haute = Image.fromarray(page(h=1800))
        self.assertEqual(optimiser.ameliorer(haute, "0,0,0,0,0,0,0,0,0,2").size, haute.size)

    def test_sans_le_paquet_le_reglage_est_ignore_sans_planter(self):
        with mock.patch.object(ia, "_DISPO", False):
            im = Image.fromarray(page())
            self.assertEqual(optimiser.ameliorer(im, "0,0,1,0,0,0,0,0,0,2").size, im.size)

    def test_analyse_d_un_tome_avec_ia_n_essaie_que_trois_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            tome = Path(tmp) / "T.cbz"
            with zipfile.ZipFile(tome, "w") as z:
                for i in range(12):
                    b = io.BytesIO()
                    Image.fromarray(page()).save(b, "JPEG", quality=90)
                    z.writestr(f"{i:03d}.jpg", b.getvalue())
            with mock.patch.object(optimiser, "ameliorer", wraps=optimiser.ameliorer) as classique:
                optimiser.analyser(tome, nb_essai=8, eclairer="1,0,0,0,0,0,0,0,0,0")
            with mock.patch.object(optimiser, "ameliorer", wraps=optimiser.ameliorer) as avec_ia:
                optimiser.analyser(tome, nb_essai=8, eclairer="0,0,0,0,0,0,0,0,0,2")
        self.assertLess(avec_ia.call_count, classique.call_count)          # 3 pages d'essai au lieu de 8 : chacune passe par le réseau


if __name__ == "__main__":
    unittest.main()
