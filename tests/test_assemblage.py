"""Assembler deux pages simples en une double page (l'inverse de la découpe) : ordre, sens, noms de chapitres, signets, relecture."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import archives  # noqa: E402
import optimiser  # noqa: E402
from PIL import Image  # noqa: E402


def png(couleur, taille=(40, 60)):
    b = io.BytesIO()
    Image.new("RGB", taille, couleur).save(b, "PNG")
    return b.getvalue()


def cbz(chemin, pages, extra=None):
    with zipfile.ZipFile(chemin, "w") as z:
        for nom, data in pages:
            z.writestr(nom, data)
        for nom, data in (extra or []):
            z.writestr(nom, data)


def pixel(chemin, nom, xy):
    with zipfile.ZipFile(chemin) as z:
        return Image.open(io.BytesIO(z.read(nom))).convert("RGB").getpixel(xy)


class AssemblerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Path(self.tmp.name) / "Tome 01.cbz"
        cbz(self.f, [("001.png", png((255, 0, 0))), ("002.png", png((0, 255, 0))), ("003.png", png((0, 0, 255))), ("004.png", png((9, 9, 9)))])

    def tearDown(self):
        self.tmp.cleanup()

    def test_manga_la_premiere_page_est_a_droite(self):
        r = optimiser.assembler(self.f, {0}, sens_manga=True)
        self.assertEqual((r["pages_avant"], r["pages"]), (4, 3))
        with zipfile.ZipFile(self.f) as z:
            self.assertEqual(Image.open(io.BytesIO(z.read("001.png"))).size, (80, 60))
        self.assertEqual(pixel(self.f, "001.png", (70, 10)), (255, 0, 0))     # page 1 à droite
        self.assertEqual(pixel(self.f, "001.png", (10, 10)), (0, 255, 0))
        self.assertEqual(r["carte"], {0: 0, 1: 0, 2: 1, 3: 2})
        self.assertTrue(r["avant"].exists())                                  # l'ancien fichier est gardé pour la corbeille

    def test_occidental_la_premiere_page_est_a_gauche(self):
        optimiser.assembler(self.f, {0}, sens_manga=False)
        self.assertEqual(pixel(self.f, "001.png", (10, 10)), (255, 0, 0))

    def test_hauteurs_differentes_agrandies_a_la_plus_haute(self):
        cbz(self.f, [("001.png", png((255, 0, 0), (40, 30))), ("002.png", png((0, 255, 0), (40, 60)))])
        optimiser.assembler(self.f, {0})
        with zipfile.ZipFile(self.f) as z:
            self.assertEqual(Image.open(io.BytesIO(z.read("001.png"))).size, (120, 60))

    def test_deux_paires(self):
        r = optimiser.assembler(self.f, {0, 2})
        self.assertEqual(r["pages"], 2)

    def test_une_page_dans_deux_paires_refusee_et_rien_modifie(self):
        avant = self.f.read_bytes()
        for indices in ({0, 1}, {3}, {7}, set()):
            with self.assertRaises(RuntimeError):
                optimiser.assembler(self.f, indices)
        self.assertEqual(self.f.read_bytes(), avant)

    def test_aller_retour_couper_puis_assembler(self):
        cbz(self.f, [("001.png", png((255, 0, 0), (80, 60))), ("002.png", png((0, 0, 255)))])
        optimiser.couper(self.f, {0}, sens_manga=True)
        self.assertEqual(len(archives.pages(self.f)), 3)
        optimiser.assembler(self.f, {0}, sens_manga=True)
        self.assertEqual(len(archives.pages(self.f)), 2)
        with zipfile.ZipFile(self.f) as z:
            self.assertEqual(Image.open(io.BytesIO(z.read("001.png"))).size, (80, 60))
        self.assertEqual(pixel(self.f, "001.png", (10, 10)), (255, 0, 0))

    def test_noms_de_pages_de_chapitre_renumerotes_et_signets_suivis(self):
        import tomes_cbz
        noms = [tomes_cbz.nom_page(12, i, ext="png") for i in (1, 2, 3)] + [tomes_cbz.nom_page(13, 1, ext="png")]
        info = ('<?xml version="1.0"?><ComicInfo><PageCount>4</PageCount><Pages><Page Image="0"/><Page Image="3" Bookmark="x"/></Pages></ComicInfo>').encode()
        cbz(self.f, [(n, png((i * 40, 0, 0))) for i, n in enumerate(noms)], extra=[("ComicInfo.xml", info)])
        r = optimiser.assembler(self.f, {0})
        with zipfile.ZipFile(self.f) as z:
            visibles = [n for n in z.namelist() if n.endswith(".png")]
            self.assertEqual(len(visibles), 3)
            self.assertEqual(visibles[:2], [tomes_cbz.nom_page(12, 1, ext="png"), tomes_cbz.nom_page(12, 2, ext="png")])
            xml = z.read("ComicInfo.xml").decode()
        self.assertIn("<PageCount>3</PageCount>", xml)
        self.assertIn('Image="2"', xml)                                      # le signet de la dernière page a suivi
        self.assertEqual(r["carte"][3], 2)


class RouteTest(unittest.TestCase):
    def test_une_page_dans_deux_paires_est_refusee_avant_tout_travail(self):
        import app as m
        from unittest import mock
        with m.app.test_request_context("/api/doubles/assembler", method="POST",
                                        json={"series": "S", "plan": [{"fichier": "T.cbz", "indices": [3, 4]}]}), \
                mock.patch.object(m, "_scan", return_value={"S": []}), mock.patch.object(m, "_en_telechargement", return_value=False), \
                mock.patch.object(m, "_fichiers_a_alleger", return_value=[Path("T.cbz")]), mock.patch.object(m.zipfile, "is_zipfile", return_value=True), \
                mock.patch.object(m.optimiser, "lancer_coupes") as lancer:
            rep = m.api_doubles_assembler()
        self.assertEqual(rep[1], 400)
        lancer.assert_not_called()


class JointureTest(unittest.TestCase):
    """La raie blanche au milieu d'une double page assemblée (marges des scans, léger décalage en hauteur)."""

    def _fond(self):
        import numpy as np
        return np.add.outer(np.sin(np.arange(400) / 7) * 60 + 120, np.sin(np.arange(600) / 5) * 60 + np.arange(600) / 10).clip(0, 255).astype("uint8")

    def test_marges_unies_du_milieu_enlevees(self):
        from PIL import Image
        base = self._fond()
        g, d = Image.new("L", (309, 400), 255), Image.new("L", (309, 400), 255)
        g.paste(Image.fromarray(base[:, :300]), (0, 0))
        d.paste(Image.fromarray(base[:, 300:]), (9, 0))
        out = optimiser._coller(g.convert("RGB"), d.convert("RGB"), False)
        self.assertEqual(out.size[0], 600)

    def test_apercu_identique_a_l_assemblage(self):
        import io, tempfile, zipfile
        from PIL import Image
        base = self._fond()
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.cbz"
            with zipfile.ZipFile(f, "w") as z:
                for i, (x0, x1) in enumerate([(0, 300), (300, 600)]):
                    b = io.BytesIO()
                    Image.fromarray(base[:, x0:x1]).save(b, "PNG")
                    z.writestr("%03d.png" % i, b.getvalue())
            im = Image.open(io.BytesIO(optimiser.apercu_paire(f, 0, False, 900)))
        self.assertEqual(im.size, (600, 400))

    def test_chapitres_et_sommaire_suivent_l_assemblage(self):
        import app as m
        carte = {0: 0, 1: 0, 2: 1, 3: 2, 4: 2, 5: 3, 6: 4}          # paires (0,1) et (3,4) assemblées
        infos = {"sommaires": {"3": {"chapitres": [{"num": 1, "image": 2}, {"num": 2, "image": 5}], "page_sommaire": 1}}}
        m._suivre_sommaire(infos, Path("/x/Serie - Tome 03.cbz"), carte)
        lu = infos["sommaires"]["3"]
        self.assertEqual([c["image"] for c in lu["chapitres"]], [1, 3])
        self.assertEqual(lu["page_sommaire"], 0)

    def test_carte_retrouvee_apres_coup(self):
        import io, tempfile, zipfile
        from PIL import Image
        base = self._fond()
        with tempfile.TemporaryDirectory() as d:
            avant, apres = Path(d) / "a.cbz", Path(d) / "b.cbz"

            def png(arr):
                b = io.BytesIO()
                Image.fromarray(arr).save(b, "PNG")
                return b.getvalue()
            pages = [png(base[:, i * 100:(i + 1) * 100]) for i in range(6)]
            with zipfile.ZipFile(avant, "w") as z:
                for i, p in enumerate(pages):
                    z.writestr("%03d.png" % i, p)
            with zipfile.ZipFile(apres, "w") as z:                       # pages 1 et 2 collées, 4 et 5 aussi
                for i, p in enumerate([pages[0], png(base[:, 100:300]), pages[3], png(base[:, 400:600])]):
                    z.writestr("%03d.png" % i, p)
            self.assertEqual(optimiser.carte_assemblage(avant, apres), {0: 0, 1: 1, 2: 1, 3: 2, 4: 3, 5: 3})

    def test_decalage_vertical_retrouve(self):
        import numpy as np
        from PIL import Image
        base = self._fond()
        g = Image.fromarray(base[:, :300]).convert("RGB")
        d = Image.fromarray(np.roll(base[:, 300:], 5, 0)).convert("RGB")
        self.assertEqual(optimiser._decalage_vertical(g, d), -5)
        d = Image.fromarray(np.roll(base[:, 300:], 23, 0)).convert("RGB")
        self.assertEqual(optimiser._decalage_vertical(g, d), -23)
        self.assertEqual(optimiser._decalage_vertical(g, Image.fromarray(base[:, 300:]).convert("RGB")), 0)


if __name__ == "__main__":
    unittest.main()
