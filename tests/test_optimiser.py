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

    def test_tome_partage_dans_son_dossier_est_allege_sans_toucher_au_torrent(self):
        racine = Path(self.tmp.name) / "Serie"
        dossier = racine / "Tome 01"
        dossier.mkdir(parents=True)
        tome = dossier / "Serie - Tome 01.cbz"
        os.replace(self.f, tome)
        torrent = Path(self.tmp.name) / "torrent.cbz"
        os.link(tome, torrent)                                   # le fichier du torrent (même inode)
        (dossier / "cover.jpg").write_bytes(b"jpeg")
        avant_taille = torrent.stat().st_size
        corbeille = []
        optimiser.lancer("Serie", [tome], True, corbeille.append, largeur_max=1200)
        for _ in range(400):
            if not optimiser.etat("Serie").get("en_cours"):
                break
            time.sleep(0.05)
        ligne = optimiser.etat("Serie")["rapport"][0]
        self.assertGreater(ligne.get("gagne_mo", 0), 0, ligne)
        self.assertLess(tome.stat().st_size, avant_taille)               # le tome de la bibliothèque est plus léger
        self.assertEqual(torrent.stat().st_size, avant_taille)           # le fichier du torrent est intact
        self.assertTrue((dossier / "cover.jpg").is_file())
        self.assertEqual(len(corbeille), 1)                              # l'ancien dossier part à la corbeille
        self.assertFalse(any(x.name.startswith(".") for x in racine.iterdir() if x not in corbeille))
        with zipfile.ZipFile(tome) as z:
            self.assertIsNone(z.testzip())

    def test_comparer_avant_apres(self):
        r = optimiser.comparer(self.f, 2, 85, largeur_max=1200)
        self.assertEqual(r["pages"], 6)
        self.assertEqual(r["dimensions"][1][0], 1200)                    # même réglage que « Appliquer » : largeur réduite
        self.assertLess(r["apres_ko"], r["avant_ko"])
        a, b = Image.open(io.BytesIO(r["avant"])), Image.open(io.BytesIO(r["apres"]))
        self.assertEqual(a.size, b.size)                                  # même géométrie pour comparer
        z = optimiser.comparer(self.f, 2, 85, largeur_max=1200, zoom=(0.5, 0.5))
        self.assertEqual(Image.open(io.BytesIO(z["apres"])).size, (640, 640))
        rien = optimiser.comparer(self.f, 2, None)                       # tome laissé tel quel : mêmes octets
        self.assertTrue(rien["inchange"])

    def test_eclaircir_seulement_le_gris(self):
        gris = Image.new("L", (100, 150), 200)
        self.assertEqual(optimiser.eclaircir(gris.point(lambda v: 40 if v < 100 else v)).getextrema()[1], 200)
        couleur = Image.new("RGB", (100, 150), (200, 30, 30))
        self.assertTrue(optimiser.est_couleur(couleur))
        self.assertFalse(optimiser.est_couleur(Image.new("RGB", (100, 150), (120, 120, 120))))


if __name__ == "__main__":
    unittest.main()
