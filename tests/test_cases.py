"""🧩 Recadrage aux cases (cases.py) sur un petit tome synthétique : deux pages par scan, une bande parasite côté reliure, un flash-back sur fond noir."""
import io
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
from PIL import Image

import cases

W2, H2 = 320, 530                              # une moitié de scan


def page_blanche(dos):
    """Moitié de scan : cases en grille, bande grise du dos (« dos » : côté de la reliure)."""
    g = np.full((H2, W2), 245, np.uint8)
    for y0, y1 in ((20, 180), (192, 350), (362, 510)):
        for x0, x1 in ((20, 150), (162, 300)):
            cv2.rectangle(g, (x0, y0), (x1, y1), 15, 2)                        # trait fin, comme sur un vrai scan
            cv2.circle(g, ((x0 + x1) // 2, (y0 + y1) // 2), 30, 60, -1)        # un dessin dans chaque case
    if dos == "droite":
        g[:, W2 - 10:] = 150
    else:
        g[:, :10] = 150
    return g


def page_noire():
    """Flash-back : fond noir du papier de y=12 à y=518 (papier clair au-dessus et en dessous), cases claires entre gouttières noires."""
    g = np.full((H2, W2), 235, np.uint8)
    g[12:518] = 20
    for y0, y1 in ((60, 190), (210, 340), (360, 480)):
        g[y0:y1, 40:280] = 240
        cv2.rectangle(g, (40, y0), (280, y1), 10, 2)
        cv2.circle(g, (160, (y0 + y1) // 2), 25, 70, -1)
    return g


def faire_tome(chemin, moities):
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_STORED) as z:
        couverture = io.BytesIO()
        Image.new("L", (400, 600), 128).save(couverture, "JPEG")
        z.writestr("0000.jpg", couverture.getvalue())
        for i, g in enumerate(moities, 1):
            out = io.BytesIO()
            Image.fromarray(g).save(out, "JPEG", quality=95)
            z.writestr(f"{i:04d}.jpg", out.getvalue())


class OutilsTest(unittest.TestCase):
    def test_paires(self):
        tailles = [(400, 600), (320, 530), (300, 534), (640, 530), (320, 530), (310, 530), (320, 600)]
        self.assertEqual(cases.paires(tailles), [(1, 2), (4, 5)])
        # une page seule entre deux scans ne décale pas les paires suivantes (appariement glouton : 3-4 puis 5 seule ; tome 3 réel, page 6)
        tailles = [(400, 600), (637, 1068), (638, 1068), (620, 1068), (637, 1060), (638, 1060), (637, 1082), (638, 1082)]
        self.assertEqual(cases.paires(tailles), [(1, 2), (4, 5), (6, 7)])

    def test_flashback_cases_intactes_fond_noir(self):
        g = np.full((400, 300), 120, np.uint8)                          # fond délavé gris
        g[40:180, 30:270] = 240
        g[200:360, 30:270] = 240
        g[100:120, 100:140] = 50                                       # dessin sombre dans une case
        out, contenu = cases.fond_cases(g)
        self.assertTrue((out[100:120, 100:140] == 50).all())           # l'intérieur des cases n'est pas touché
        self.assertLessEqual(int(out[10, 150]), 25)                    # le fond devient noir
        self.assertLessEqual(int(out[190, 150]), 25)                   # la gouttière aussi
        self.assertTrue(contenu[50, 50] and not contenu[190, 150])

    def test_page_blanche_bande_du_dos_supprimee(self):
        g = page_blanche("droite")
        rempli = np.zeros_like(g, bool)
        out, _ = cases.couper_cases(g, rempli, "droite")
        self.assertGreater(out[:, W2 - 10:].min(), 240)               # la bande grise du dos est partie
        self.assertEqual(int(out[100, 85]), int(g[100, 85]))           # le dessin d'une case est intact

    def test_hauteur_reelle_sur_les_flashbacks(self):
        self.assertEqual(cases.hauteur_reelle([(page_noire(), True), (page_noire(), True)]), 506)


class TomeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cbz = self.dir / "tome.cbz"
        faire_tome(self.cbz, [page_blanche("droite"), page_blanche("gauche"), page_noire(), page_noire(), page_blanche("droite"), page_blanche("gauche")])

    def tearDown(self):
        self.tmp.cleanup()

    def test_tome_recadre(self):
        dest = self.dir / "sortie.cbz"
        r = cases.recadrer_tome(self.cbz, self.cbz, {}, (300, 500), None, dest)
        self.assertEqual(r["pages"], 6)
        self.assertEqual(r["flashbacks"], [3, 4])
        self.assertEqual(r["hauteur"], 506)
        with zipfile.ZipFile(dest) as z, zipfile.ZipFile(self.cbz) as z0:
            noms = sorted(z.namelist())
            self.assertEqual(noms, sorted(z0.namelist()))
            self.assertEqual(z.read("0000.jpg"), z0.read("0000.jpg"))  # la couverture n'est pas une moitié de scan : recopiée telle quelle
            for n in noms[1:]:
                im = Image.open(io.BytesIO(z.read(n)))
                self.assertEqual(im.size, (300, 500))
            fb = np.array(Image.open(io.BytesIO(z.read("0003.jpg"))).convert("L"))
            self.assertLess(int(np.median(fb[:15])), 40)               # flash-back : cadre noir gardé en haut
            bl = np.array(Image.open(io.BytesIO(z.read("0001.jpg"))).convert("L"))
            self.assertGreater(int(np.median(bl[:, -6:])), 230)        # page blanche : plus de bande grise côté dos

    def test_ecrire_tome_garde_l_ancien(self):
        source = self.dir / ".rognage" / "tome.cbz"
        travail = {"source": str(source), "copier_source": True, "boites": {}, "W": 300, "H": 500, "retouches": None}
        avant = self.cbz.read_bytes()
        res = cases.ecrire_tome(self.cbz, set(), travail=travail)
        self.assertEqual(res["avant"].read_bytes(), avant)              # l'ancien fichier est gardé (corbeille)
        self.assertEqual(source.read_bytes(), avant)                    # pages d'origine gardées avant d'écrire
        self.assertEqual(len(travail["empreintes"]), 7)


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MANGA_DIR"] = self.tmp.name
        racine = Path(self.tmp.name)
        (racine / "Serie" / "Tome 01").mkdir(parents=True)
        self.cbz = racine / "Serie" / "Tome 01" / "Serie - Tome 01.cbz"
        faire_tome(self.cbz, [page_blanche("droite"), page_blanche("gauche"), page_noire(), page_noire()])
        (racine / "data").mkdir()
        sys.modules.pop("app", None)
        import app
        self.A = app
        self.patchs = [mock.patch.object(app, "_scan", return_value={"Serie": [self.cbz]}), mock.patch.object(app, "MANGA_DIR", racine),
                       mock.patch.object(app, "DATA_DIR", racine / "data")]
        for p in self.patchs:
            p.start()

    def tearDown(self):
        for p in self.patchs:
            p.stop()
        self.tmp.cleanup()

    def _post(self, corps):
        with self.A.app.test_request_context("/", method="POST", json=corps):
            rep = self.A.api_rogner_cases()
        return rep if isinstance(rep, tuple) else (rep, 200)

    def test_verifier_puis_lancer(self):
        rep, code = self._post({"series": "Serie", "fichier": self.cbz.name, "verifier": True})
        self.assertEqual(code, 200)
        self.assertEqual((rep.get_json()["pages"], rep.get_json()["autres"]), (4, 1))
        avant = self.cbz.read_bytes()
        with mock.patch.object(self.A, "_vers_corbeille"):
            rep, code = self._post({"series": "Serie", "fichier": self.cbz.name})
            self.assertEqual(code, 200)
            for _ in range(300):
                if not self.A.optimiser.coupes_etat("Serie").get("en_cours"):
                    break
                time.sleep(0.1)
        etat = self.A.optimiser.coupes_etat("Serie")
        self.assertNotIn("erreur", str(etat.get("rapport")))
        self.assertNotEqual(self.cbz.read_bytes(), avant)
        import rognage
        e = rognage._lire(str(Path(self.tmp.name) / "data" / "rognage.json"))["tomes"]["Serie"][self.cbz.name]
        self.assertTrue(e["produit"]["cases"])
        self.assertEqual(e["produit"]["octets"], self.cbz.stat().st_size)  # le tome écrit est connu : il ne passera pas pour changé par ailleurs


if __name__ == "__main__":
    unittest.main()
