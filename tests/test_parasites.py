"""🧹 Pages parasites : pages répétées regroupées, retirées des tomes (corbeille, signets recalés), refusées pour la suite."""
import io
import os
import random
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parasites  # noqa: E402


def _image(graine, texte=""):
    """Page « dessinée » au hasard (une vraie page du manga), ou la page de crédits si graine == 0 (pseudo variable)."""
    r = random.Random(graine)
    im = Image.new("L", (300, 450), 255)
    d = ImageDraw.Draw(im)
    for _ in range(25):
        x, y = r.randrange(300), r.randrange(450)
        d.rectangle((x, y, x + r.randrange(20, 120), y + r.randrange(20, 120)), fill=r.randrange(0, 200))
    if texte:
        d.text((20, 420), texte, fill=0)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return b.getvalue()


def _tome(chemin, pages, comicinfo=None):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(chemin, "w") as z:
        for k, data in enumerate(pages):
            z.writestr(f"{k + 1:04d}.jpg", data)
        if comicinfo:
            z.writestr("ComicInfo.xml", comicinfo)


class ParasitesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "mangas"
        self.credits = lambda n: _image(0, f"equipe {n}")
        # deux tomes : une page de crédits au début de chaque chapitre (3 chapitres par tome), une vraie page en double
        self.t1 = self.root / "Serie" / "Tome 01" / "Serie - Tome 01.cbz"
        self.t2 = self.root / "Serie" / "Tome 02" / "Serie - Tome 02.cbz"
        p1 = [self.credits(1), _image(1), _image(2), self.credits(2), _image(3), _image(3), self.credits(3), _image(4)]
        p2 = [self.credits(4), _image(5), self.credits(5), _image(6), self.credits(6), _image(7)]
        ci = ('<?xml version="1.0"?><ComicInfo><PageCount>8</PageCount><Pages><Page Image="0" Bookmark="Chapitre 1"/>'
              '<Page Image="3" Bookmark="Chapitre 2"/><Page Image="5"/><Page Image="6" Bookmark="Chapitre 3"/></Pages></ComicInfo>')
        _tome(self.t1, p1, ci)
        _tome(self.t2, p2)

    def tearDown(self):
        self.tmp.cleanup()

    def pages(self):
        out = []
        for f in (self.t1, self.t2):
            out += [(f.name, i, h, u) for i, h, u in parasites.empreintes_tome(f)]
        return out

    def test_groupes(self):
        g = parasites.grouper(self.pages())
        self.assertEqual(len(g), 1)                              # la vraie page en double (2 fois) n'est pas proposée
        self.assertEqual(sorted(g[0]["pages"]), [("Serie - Tome 01.cbz", 0), ("Serie - Tome 01.cbz", 3), ("Serie - Tome 01.cbz", 6),
                                                 ("Serie - Tome 02.cbz", 0), ("Serie - Tome 02.cbz", 2), ("Serie - Tome 02.cbz", 4)])
        self.assertEqual(g[0]["tomes"], 2)

    def test_retirer_et_signets(self):
        corbeille = []
        res = parasites.nettoyer_tome(self.t1, {0, 3, 6}, "Serie", corbeille.append)
        self.assertEqual((res["pages_avant"], res["pages"]), (8, 5))
        self.assertEqual(res["carte"], {1: 0, 2: 1, 4: 2, 5: 3, 7: 4})
        self.assertEqual(len(corbeille), 1)                      # l'ancien fichier part à la corbeille
        with zipfile.ZipFile(self.t1) as z:
            self.assertEqual(sorted(n for n in z.namelist() if n.endswith(".jpg")), ["0002.jpg", "0003.jpg", "0005.jpg", "0006.jpg", "0008.jpg"])
            ci = z.read("ComicInfo.xml").decode()
        self.assertIn("<PageCount>5</PageCount>", ci)
        # les signets posés sur les crédits retirés (pages 0, 3, 6) passent à la page gardée qui suit
        self.assertIn('Image="0" Bookmark="Chapitre 1"', ci)
        self.assertIn('Image="2" Bookmark="Chapitre 2"', ci)
        self.assertIn('Image="3" />', ci)                        # page 5 sans signet suivie
        self.assertIn('Image="4" Bookmark="Chapitre 3"', ci)

    def test_refusees_retrouvees_dans_un_nouveau_tome(self):
        g = parasites.grouper(self.pages())
        t3 = self.root / "Serie" / "Tome 03" / "Serie - Tome 03.cbz"
        _tome(t3, [self.credits(7), _image(8), _image(9), self.credits(8)])
        self.assertEqual(parasites.a_retirer(t3, [g[0]["empreinte"]]), [0, 3])
        self.assertTrue(parasites.grouper(self.pages(), [int(g[0]["empreinte"], 16)])[0]["refusee"])

    def test_fichier_partage_hors_dossier_jamais_modifie(self):
        lien = self.root / "Serie" / "Serie - Tome 04.cbz"
        _tome(lien, [self.credits(9), _image(10)])
        os.link(lien, Path(self.tmp.name) / "torrent.cbz")
        avant = lien.read_bytes()
        res = parasites.nettoyer_tome(lien, {0}, "Serie", lambda p: None)
        self.assertNotIn("carte", res)
        self.assertEqual(lien.read_bytes(), avant)

    def test_jamais_toutes_les_pages(self):
        with self.assertRaises(RuntimeError):
            parasites.retirer(self.t2, set(range(6)))


class ChapitresParReperesTest(unittest.TestCase):
    """Les pages d'équipe (avant retrait) donnent les débuts de chapitres (Defense Devil)."""

    def test_credits_au_debut_de_chaque_chapitre(self):                 # tome 4 : crédits 0, 19, 38…
        c = parasites.chapitres_par_reperes([0, 19, 38, 57, 74, 96, 114, 133, 152, 174], 193, range(28, 38))
        self.assertEqual([x["image"] for x in c], [1, 20, 39, 58, 75, 97, 115, 134, 153, 175])
        self.assertEqual([x["num"] for x in c], [float(n) for n in range(28, 38)])
        self.assertFalse(any(x.get("estimee") for x in c))

    def test_trou_regulier_comble(self):                                # tome 3 : 3 chapitres sans crédits
        d = parasites.debuts_de_chapitres([0, 18, 37, 56, 75, 131, 149, 167], 186)
        self.assertEqual([i for i, _ in d], [1, 19, 38, 57, 76, 95, 114, 132, 150, 168])
        self.assertEqual([i for i, e in d if e], [95, 114])

    def test_pages_d_equipe_qui_se_suivent_en_fin_de_tome(self):
        d = parasites.debuts_de_chapitres([0, 1, 2, 22, 42, 60, 61, 62, 63, 64], 65)
        self.assertEqual([i for i, _ in d], [3, 23, 43])

    def test_compte_different_de_la_liste_rien(self):                  # mieux vaut rien qu'un décalage
        self.assertEqual(parasites.chapitres_par_reperes([0, 19, 38, 57], 76, range(10, 15)), [])

    def test_suite_du_tome_precedent(self):
        c = parasites.chapitres_par_reperes([0, 19, 38, 57], 76, (), suite_de=17)
        self.assertEqual([x["num"] for x in c], [18.0, 19.0, 20.0, 21.0])


class ParasitesRoutesTest(unittest.TestCase):
    """Routes : seul l'administrateur nettoie ; empreintes retenues avec la série ; nouveaux tomes nettoyés seuls."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "mangas"
        self.f1 = self.root / "Serie" / "Tome 01" / "Serie - Tome 01.cbz"
        _tome(self.f1, [_image(0, "a"), _image(1), _image(0, "b"), _image(2), _image(0, "c"), _image(3)])
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        self.A = A
        A.MANGA_DIR = self.root
        self.scan = mock.patch.object(A, "_scan", side_effect=lambda: {"Serie": sorted(self.root.glob("Serie/*/*.cbz"))})
        self.scan.start()
        self.rec = mock.patch.object(A, "_recaler_progression")
        self.rec.start()
        import auth
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        self.client = A.app.test_client()
        with self.client.session_transaction() as sess:
            sess["u"], sess["f"] = "test", auth._fingerprint()
        self.role = mock.patch.object(A.auth, "role", return_value="admin")
        self.role.start()

    def tearDown(self):
        self.role.stop()
        self.rec.stop()
        self.scan.stop()
        parasites._ETAT.clear()
        self.tmp.cleanup()

    def attendre(self):
        import time
        for _ in range(200):
            if not parasites.etat("Serie").get("en_cours"):
                return
            time.sleep(0.05)

    def test_chercher_puis_retirer(self):
        self.assertTrue(self.client.post("/api/parasites/analyser", json={"series": "Serie"}).get_json()["ok"])
        self.attendre()
        r = self.client.get("/api/parasites?series=Serie").get_json()
        self.assertEqual([g["nb"] for g in r["groupes"]], [3])
        e = r["groupes"][0]["empreinte"]
        self.assertTrue(self.client.post("/api/parasites/retirer", json={"series": "Serie", "empreintes": [e]}).get_json()["ok"])
        self.attendre()
        with zipfile.ZipFile(self.f1) as z:
            self.assertEqual(len([n for n in z.namelist() if n.endswith(".jpg")]), 3)
        import edition
        infos = edition.lire(self.root / "Serie")
        self.assertEqual(infos["pages_parasites"], [e])
        self.assertEqual(infos["parasites_verifies"]["Serie - Tome 01.cbz"], self.f1.stat().st_size)
        # un nouveau tome arrive : nettoyé tout seul par le passage automatique
        f2 = self.root / "Serie" / "Tome 02" / "Serie - Tome 02.cbz"
        _tome(f2, [_image(0, "d"), _image(4), _image(5)])
        self.A._nettoyer_nouveaux_tomes()
        with zipfile.ZipFile(f2) as z:
            self.assertEqual(sorted(n for n in z.namelist() if n.endswith(".jpg")), ["0002.jpg", "0003.jpg"])

    def test_chapitres_deduits_avant_retrait(self):
        """Un long tome : crédits au début de chaque chapitre ; après retrait, les chapitres pointent sur la 1re page."""
        f = self.root / "Serie" / "Tome 02" / "Serie - Tome 02.cbz"
        pages = []
        for ch in range(4):
            pages += [_image(0, f"equipe {ch}")] + [_image(100 + ch * 20 + k) for k in range(12)]
        _tome(f, pages)
        import edition
        infos = edition.lire(self.root / "Serie")
        infos["sommaires"] = {"1": {"chapitres": [{"num": 1.0, "image": 0}, {"num": 2.0, "image": 5}]}}
        edition.ecrire(self.root / "Serie", infos)
        self.client.post("/api/parasites/analyser", json={"series": "Serie"})
        self.attendre()
        e = self.client.get("/api/parasites?series=Serie").get_json()["groupes"][0]["empreinte"]
        self.client.post("/api/parasites/retirer", json={"series": "Serie", "empreintes": [e]})
        self.attendre()
        lu = edition.lire(self.root / "Serie")["sommaires"]["2"]
        self.assertEqual(lu["source"], "pages d'équipe")
        self.assertEqual([(c["num"], c["image"], c["page"]) for c in lu["chapitres"]],
                         [(3.0, 0, 1), (4.0, 12, 13), (5.0, 24, 25), (6.0, 36, 37)])

    def test_page_du_lecteur(self):
        r = self.client.post("/api/parasites/page", json={"series": "Serie", "fichier": "Serie/Tome 01/Serie - Tome 01.cbz", "index": 1}).get_json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["pages"], 5)

    def test_lecteur_refuse(self):
        with mock.patch.object(self.A.auth, "role", return_value="lecteur"):
            r = self.client.post("/api/parasites/page", json={"series": "Serie", "fichier": "Serie/Tome 01/Serie - Tome 01.cbz", "index": 1})
        self.assertNotEqual(r.status_code, 200)
        with zipfile.ZipFile(self.f1) as z:
            self.assertEqual(len([n for n in z.namelist() if n.endswith(".jpg")]), 6)


if __name__ == "__main__":
    unittest.main()
