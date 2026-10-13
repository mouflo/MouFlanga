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
import archives  # noqa: E402
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

    def test_qualite_manuelle(self):
        a = optimiser.analyser(self.f, qualite_forcee=70)
        self.assertEqual(a["qualite"], 70)                               # le choix est respecté, sans seuil d'écart
        self.assertGreater(a["gain_estime"], 0)
        b = optimiser.analyser(self.f, qualite_forcee=98)
        self.assertLess(b["gain_estime"], a["gain_estime"])              # plus fidèle = moins de gain
        corbeille = []
        optimiser.lancer("Serie", [self.f], False, corbeille.append, qualite_forcee=70)
        for _ in range(300):
            if not optimiser.etat("Serie").get("en_cours"):
                break
            time.sleep(0.05)
        self.assertEqual(optimiser.etat("Serie")["rapport"][0]["qualite"], 70)

    def test_ameliorer_un_vieux_scan(self):
        import numpy as np
        rng = np.random.default_rng(1)
        page = np.full((300, 200), 185, np.float32) + rng.normal(0, 8, (300, 200))   # papier gris et granuleux
        page[:, :100] -= 20                                                            # jauni d'un côté
        page[100:200, 40:160] = 70                                                     # grande zone d'encre délavée
        page[20:22, 150:152] = 90                                                      # une poussière isolée
        page[250:253, 30:33] = page[250:253, 37:40] = page[250:253, 44:47] = 60        # des points de suspension
        im = Image.fromarray(np.clip(page, 0, 255).astype(np.uint8), "L")
        r = np.asarray(optimiser.ameliorer(im, "2,2,2,1,2,0,0,0"), dtype=np.float32)
        self.assertGreater(r[20:90, 10:90].mean(), 245)                  # papier blanchi, même du côté jauni
        self.assertGreater(r[20:90, 110:190].mean(), 245)
        self.assertLess(r[130:170, 70:130].mean(), 40)                   # l'encre reste noire, sans halo au milieu
        self.assertGreater(r[19:23, 149:153].min(), 200)                 # la poussière est partie
        self.assertLess(r[250:253, 44:47].mean(), 120)                   # les points de suspension restent
        self.assertEqual(optimiser.ameliorer(Image.new("RGB", (100, 150), (200, 30, 30)), "3,3,3,3,3,3,3").mode, "RGB")   # couleur : intacte
        self.assertIsNone(optimiser.reglages_amelioration("0,0,0,0,0,0,0,0"))
        self.assertEqual(optimiser.reglages_amelioration("9,a,1")["debruit"], 3)
        self.assertEqual(optimiser.reglages_amelioration(True)["papier"], 2)              # ancien « 🧼 éclaircir »
        trame = np.full((300, 200), 235, np.uint8)
        trame[100:200, 40:160] = 200
        trame[100:200:3, 40:160:3] = 60                                                # aplat gris en petits points
        t = np.asarray(optimiser.ameliorer(Image.fromarray(trame), "0,2,0,0,0,0,0,0"), dtype=np.float32)
        self.assertLess(t[120:180, 60:140].std(), 12)                    # devenu un gris uni
        self.assertEqual(optimiser.ameliorer(im, "0,0,0,0,0,2,0,0").size, (200, 300))   # lissé : taille gardée
        self.assertEqual(optimiser.ameliorer(im, "0,0,0,0,0,2,0,1").size, (400, 600))   # petite page agrandie ×2

    def test_comparer_avec_amelioration(self):
        r = optimiser.comparer(self.f, 2, 85, "2,2,2,1,1,2,0,0")
        self.assertTrue(r["ameliore"] or r["couleur"])
        self.assertNotEqual(r["avant"], r["apres"])

    def test_couleur(self):
        couleur = Image.new("RGB", (100, 150), (200, 30, 30))
        self.assertTrue(optimiser.est_couleur(couleur))
        self.assertFalse(optimiser.est_couleur(Image.new("RGB", (100, 150), (120, 120, 120))))


class DoublesTest(unittest.TestCase):
    """📖 Doubles pages : découpe en deux, numéros et ComicInfo recalés, moitié droite d'abord (manga)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Path(self.tmp.name) / "Serie - Tome 01.cbz"
        gauche = Image.new("RGB", (100, 150), (255, 0, 0))
        droite = Image.new("RGB", (100, 150), (0, 0, 255))
        double = Image.new("RGB", (200, 150))
        double.paste(gauche, (0, 0))
        double.paste(droite, (100, 0))
        buf = io.BytesIO()
        Image.new("RGB", (100, 150), (0, 255, 0)).save(buf, "JPEG", quality=95)
        with zipfile.ZipFile(self.f, "w") as z:
            z.writestr("c0001.00-p001.jpg", buf.getvalue())
            z.writestr("c0001.00-p002.jpg", _page(2))
            z.writestr("c0001.00-p003.jpg", _page(3))
            z.writestr("c0002.00-p001.jpg", _page(4))
            z.writestr("ComicInfo.xml", "<ComicInfo><PageCount>4</PageCount><Pages><Page Image=\"0\"/><Page Image=\"2\"/><Page Image=\"3\"/></Pages></ComicInfo>")
        # la double page est la 2e image (numéro 1) : on la remplace dans le fichier
        with zipfile.ZipFile(self.f) as z:
            contenus = {n: z.read(n) for n in z.namelist()}
        b = io.BytesIO()
        double.save(b, "JPEG", quality=95)
        contenus["c0001.00-p002.jpg"] = b.getvalue()
        with zipfile.ZipFile(self.f, "w") as z:
            for n, d in contenus.items():
                z.writestr(n, d)

    def tearDown(self):
        self.tmp.cleanup()

    def test_repere_les_doubles(self):
        self.assertEqual([d["index"] for d in optimiser.reperer_doubles(self.f)], [1])

    def test_coupe_moitie_droite_d_abord_et_recale(self):
        res = optimiser.couper(self.f, {1}, sens_manga=True)
        self.assertEqual((res["pages_avant"], res["pages"]), (4, 5))
        self.assertEqual(res["carte"], {0: 0, 1: 1, 2: 3, 3: 4})         # la moitié droite (1) suit l'ancienne page 1
        with zipfile.ZipFile(self.f) as z:
            pages = archives.pages(self.f)
            self.assertEqual(len(pages), 5)
            premiere = Image.open(io.BytesIO(z.read(pages[1]))).convert("RGB")
            self.assertGreater(premiere.getpixel((50, 75))[2], 150)      # bleu = moitié droite, lue en premier
            self.assertEqual(Image.open(io.BytesIO(z.read(pages[2]))).convert("RGB").getpixel((50, 75))[0] > 150, True)
            info = z.read("ComicInfo.xml").decode()
            self.assertIn("<PageCount>5</PageCount>", info)
            self.assertIn('Image="3"', info)                             # signet de l'ancienne page 2 recalé
        self.assertTrue(self.f.with_name(self.f.name + ".avant").exists())   # l'ancien attend la corbeille

    def test_recalage_de_la_position_manga_et_occidental(self):
        res = optimiser.couper(self.f, {1}, sens_manga=False)
        with zipfile.ZipFile(self.f) as z:
            premiere = Image.open(io.BytesIO(z.read(archives.pages(self.f)[1]))).convert("RGB")
            self.assertGreater(premiere.getpixel((50, 75))[0], 150)      # occidental : la moitié gauche d'abord
        self.assertEqual(res["pages"], 5)

    def test_fichier_partage_coupe_a_part(self):
        dest = Path(self.tmp.name) / "coupe.cbz"
        res = optimiser.couper(self.f, {1}, True, destination=dest)
        self.assertTrue(dest.exists())
        self.assertEqual(res["pages"], 5)
        self.assertEqual(zipfile.ZipFile(self.f).namelist().count("c0001.00-p002.jpg"), 1)   # l'original est intact
