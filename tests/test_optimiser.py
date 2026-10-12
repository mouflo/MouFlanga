"""🪶 Allègement : pages réduites et recompressées sans écart visible, structure du tome intacte, fichier partagé jamais touché."""
import io
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import optimiser  # noqa: E402


def _page(seed, gris=True):
    rng = np.random.default_rng(seed)
    a = np.full((1500, 2000 if not gris else 1000), 235, dtype=np.uint8)
    a[200:1300, 100:900] = rng.integers(0, 60, size=(1100, 800), dtype=np.uint8)     # zone sombre texturée
    im = Image.fromarray(a, "L").resize((1900, 2850))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=97)
    return b.getvalue()


class OptimiserTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Path(self.tmp.name) / "Serie - Tome 01.cbz"
        with zipfile.ZipFile(self.f, "w") as z:
            for i in range(6):
                z.writestr(f"c0001.00-p{i:03d}.jpg", _page(i))
            z.writestr("chapitres.json", json.dumps({"titres": {"1": "Début"}}))
            z.writestr("ComicInfo.xml", "<ComicInfo/>")

    def tearDown(self):
        self.tmp.cleanup()

    def test_allege_et_garde_la_structure(self):
        avant_noms = zipfile.ZipFile(self.f).namelist()
        a = optimiser.analyser(self.f, largeur_max=1200)
        self.assertIsNotNone(a["qualite"])
        self.assertGreaterEqual(a["psnr_min"], optimiser.PSNR_MIN)
        gagne = optimiser.reecrire(self.f, a["qualite"], largeur_max=1200)
        self.assertGreater(gagne, 0)
        with zipfile.ZipFile(self.f) as z:
            self.assertEqual(z.namelist(), avant_noms)
            self.assertEqual(json.loads(z.read("chapitres.json"))["titres"]["1"], "Début")
            self.assertEqual(Image.open(io.BytesIO(z.read(avant_noms[0]))).width, 1200)
        self.assertTrue(self.f.with_name(self.f.name + ".avant").exists())     # l'ancien attend la corbeille

    def test_fichier_partage_jamais_touche(self):
        os.link(self.f, Path(self.tmp.name) / "copie-torrent.cbz")
        corbeille = []
        optimiser.lancer("Serie", [self.f], True, corbeille.append, largeur_max=1200)
        for _ in range(300):
            if not optimiser.etat("Serie").get("en_cours"):
                break
            time.sleep(0.05)
        self.assertIn("qBittorrent", optimiser.etat("Serie")["rapport"][0]["note"])
        self.assertEqual(corbeille, [])

    def test_eclaircir_seulement_le_gris(self):
        gris = Image.new("L", (100, 150), 200)
        self.assertEqual(optimiser.eclaircir(gris.point(lambda v: 40 if v < 100 else v)).getextrema()[1], 200)
        couleur = Image.new("RGB", (100, 150), (200, 30, 30))
        self.assertTrue(optimiser.est_couleur(couleur))
        self.assertFalse(optimiser.est_couleur(Image.new("RGB", (100, 150), (120, 120, 120))))


if __name__ == "__main__":
    unittest.main()
