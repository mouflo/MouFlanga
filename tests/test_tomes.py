"""Tomes : répartition lue sur Wikipédia, fichiers de tome, rangement d'une série, lecture et téléchargement."""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tomes  # noqa: E402
import tomes_cbz  # noqa: E402


def _jpeg(couleur):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (40, 60), couleur).save(b, "JPEG")
    return b.getvalue()


def _pages(n, base=0):
    return [_jpeg(((base * 40 + k * 7) % 255, 10, 10)) for k in range(n)]


WIKI_NUMBERED = """
{{Graphic novel list/header}}
{{Graphic novel list
| VolumeNumber = 1
| ChapterList =
{{Numbered list|start = 1
| {{Nihongo|"Love Starts"|x|y}}
| {{Nihongo|"Space Alien"|x|y}}
}}
| ChapterListCol2 =
{{Numbered list|start = 3
| {{Nihongo|"Granny Clash"|x|y}}
}}
| Summary = Résumé
}}
{{Graphic novel list
| VolumeNumber = 2
| ChapterList =
{{Numbered list|start = 4
| "Toilets"
| "Turbo"
}}
}}
<!--{{Graphic novel list
| VolumeNumber = 3
| ChapterList =
{{Numbered list|start = 6
| "Futur"
}}
}}-->
{{Graphic novel list/footer}}

== Chapters not yet in ''tankōbon'' format ==
{{Numbered list|start = 6
| "Nouveau 6"
| "Nouveau 7"
}}

== References ==
"""

WIKI_ETOILES = """
{{Graphic novel list
|VolumeNumber = 1
|ChapterListCol1 =
*1. {{nihongo|"Dream"|夢|Yume}}
*2. "Moving In"
|ChapterListCol2 =
*Days 3: {{Nihongo|"Monster"|x|y}}
}}
{{Graphic novel list
|VolumeNumber = 2
|ChapterList =
* Chapter: 4–6
}}
{{Graphic novel list/footer}}

=== Chapters not yet in ''tankōbon'' format ===
*7. "Origin"
"""

WIKI_DIESES = """
{{Graphic novel list
|VolumeNumber = 1
|ChapterList =
# {{nihongo|"To You"|x|y}}
# {{nihongo|"That Day"|x|y}}
}}
{{Graphic novel list
|VolumeNumber = 2
|ChapterList =
# "Third"
}}
"""


class WikipediaTest(unittest.TestCase):
    def _lire(self, texte):
        with mock.patch.object(tomes, "_pages_wiki", return_value=["List of X chapters"]), \
                mock.patch.object(tomes, "_wiki", return_value={"parse": {"wikitext": texte}}):
            return tomes._wikipedia(["X"])

    def test_listes_numerotees_et_hors_tome(self):
        info = self._lire(WIKI_NUMBERED)
        self.assertEqual(info["tomes"], {1.0: 1, 2.0: 1, 3.0: 1, 4.0: 2, 5.0: 2, 6.0: None, 7.0: None})
        self.assertEqual(info["titres"][3.0], "Granny Clash")
        self.assertEqual(info["titres"][4.0], "Toilets")

    def test_tome_en_commentaire_ignore(self):
        info = self._lire(WIKI_NUMBERED)
        self.assertIsNone(tomes.tome_de(6.0, info))            # le tome 3 « en préparation » est en commentaire

    def test_lignes_etoile_et_plages(self):
        info = self._lire(WIKI_ETOILES)
        self.assertEqual(info["tomes"], {1.0: 1, 2.0: 1, 3.0: 1, 4.0: 2, 5.0: 2, 6.0: 2, 7.0: None})
        self.assertEqual(info["titres"][1.0], "Dream")
        self.assertEqual(info["titres"][3.0], "Monster")

    def test_liste_implicite(self):
        info = self._lire(WIKI_DIESES)
        self.assertEqual(info["tomes"], {1.0: 1, 2.0: 1, 3.0: 2})
        self.assertEqual(info["titres"][2.0], "That Day")

    def test_chapitre_decimal_suit_son_tome(self):
        info = {"tomes": {12.0: 3, 13.0: None}, "titres": {}}
        self.assertEqual(tomes.tome_de(12.5, info), 3)
        self.assertIsNone(tomes.tome_de(13.5, info))
        self.assertIsNone(tomes.tome_de(99.0, info))

    def test_garde_en_memoire(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(tomes, "DOSSIER", Path(t)), \
                mock.patch.object(tomes, "_wikipedia", return_value={"source": "Wikipédia", "tomes": {1.0: 1}, "titres": {}}) as w, \
                mock.patch.object(tomes, "_mangadex", return_value=None):
            self.assertEqual(tomes.chercher("Série")["tomes"], {1.0: 1})
            tomes.chercher("Série")
            self.assertEqual(w.call_count, 1)


class FichierTomeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "Serie"

    def tearDown(self):
        self.tmp.cleanup()

    def test_ajout_dans_le_desordre_et_lecture(self):
        f = tomes_cbz.ajouter(self.dir, "Serie", 1, 3.0, "Trois", _pages(2, 3))
        tomes_cbz.ajouter(self.dir, "Serie", 1, 1.0, "Un", _pages(3, 1))
        tomes_cbz.ajouter(self.dir, "Serie", 1, 2.5, "", _pages(1, 2))
        self.assertEqual(f, self.dir / "Tome 01" / "Serie - Tome 01.cbz")
        ch = tomes_cbz.chapitres(f)
        self.assertEqual([(c["num"], c["titre"], c["debut"], c["nb"]) for c in ch],
                         [(1.0, "Un", 0, 3), (2.5, "", 3, 1), (3.0, "Trois", 4, 2)])
        with zipfile.ZipFile(f) as zf:
            self.assertIn("ComicInfo.xml", zf.namelist())
            self.assertIn("<Volume>1</Volume>", zf.read("ComicInfo.xml").decode())

    def test_remplacer_puis_retirer(self):
        f = tomes_cbz.ajouter(self.dir, "Serie", None, 5.0, "A", _pages(2))
        tomes_cbz.ajouter(self.dir, "Serie", None, 5.0, "B", _pages(4))
        self.assertEqual([(c["titre"], c["nb"]) for c in tomes_cbz.chapitres(f)], [("B", 4)])
        self.assertEqual(f.parent.name, "Hors tome")
        self.assertEqual(tomes_cbz.retirer(f, {5.0}), 0)
        self.assertFalse(f.exists())
        self.assertFalse(f.parent.exists())

    def test_nettoyer_titre(self):
        n = tomes_cbz.nettoyer_titre
        self.assertEqual(n("​Chapitre 3: La vieille"), "La vieille")
        self.assertEqual(n("003 - ​Chapitre 3 La vieille et la vielle"), "La vieille et la vielle")
        self.assertEqual(n("Chapitre 12"), "")
        self.assertEqual(n("Un titre"), "Un titre")


class BibliothequeTest(unittest.TestCase):
    """Série téléchargée « un fichier par chapitre », rangée en tomes, puis lue."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root = t / "mangas"
        for n in (1, 2, 3, 4, 6):
            p = self.root / "Serie" / f"{n:03d} - ​Chapitre {n} Titre {n}.cbz"
            p.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(p, "w") as z:
                for k, d in enumerate(_pages(2, n), 1):
                    z.writestr(f"page_{k:03d}.jpg", d)
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        self.A = A
        A.MANGA_DIR = self.root
        A.PROGRESS_FILE = t / "progress.json"
        A.PROGRESS_FILE.write_text(json.dumps({"Serie": {
            "current": "Serie/003 - ​Chapitre 3 Titre 3.cbz", "page": 1,
            "read": ["Serie/001 - ​Chapitre 1 Titre 1.cbz", "Serie/002 - ​Chapitre 2 Titre 2.cbz"]}}))
        self._env = {k: os.environ.get(k) for k in ("APP_USER", "APP_PASSWORD_HASH")}
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        self.client = A.app.test_client()
        import auth
        with self.client.session_transaction() as sess:
            sess["u"], sess["f"] = "test", auth._fingerprint()
        self.info = {"source": "test", "tomes": {1.0: 1, 2.0: 1, 3.0: 2, 4.0: 2, 5.0: None, 6.0: None}, "titres": {5.0: "Wiki 5"}}

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_rangement_et_progression(self):
        self.assertEqual(self.A._ranger_en_tomes("Serie", self.info), 5)
        noms = sorted(str(p.relative_to(self.root / "Serie")) for p in (self.root / "Serie").rglob("*.cbz"))
        self.assertEqual(noms, ["Hors tome/Serie - Hors tome.cbz", "Tome 01/Serie - Tome 01.cbz", "Tome 02/Serie - Tome 02.cbz"])
        self.assertEqual(len(list((self.root / ".corbeille").rglob("*.cbz"))), 5)    # anciens fichiers gardés 30 jours
        s = self.client.get("/api/series?id=Serie").json
        self.assertEqual([c["key"] for c in s["chapters"]], ["#1", "#2", "#3", "#4", "#6"])
        self.assertEqual([c["groupe"] for c in s["chapters"]], ["Tome 01", "Tome 01", "Tome 02", "Tome 02", "Hors tome"])
        self.assertEqual(s["chapters"][2]["title"], "Chapitre 3 : Titre 3")
        self.assertEqual([c["read"] for c in s["chapters"]], [True, True, False, False, False])
        self.assertEqual((s["current"], s["page"]), ("#3", 1))                         # position gardée
        self.assertEqual(s["manquants"], ["5"])
        self.assertFalse(s["a_ranger"])

    def test_lecture_d_un_chapitre_dans_le_tome(self):
        self.A._ranger_en_tomes("Serie", self.info)
        c4 = next(c for c in self.client.get("/api/series?id=Serie").json["chapters"] if c["key"] == "#4")
        self.assertEqual((c4["debut"], c4["nb"]), (2, 2))
        page = self.client.get(f"/api/page?path={c4['path']}&n={c4['debut']}").data
        self.assertEqual(page, _pages(2, 4)[0])
        self.assertTrue(self.client.post("/api/progress", json={"series": "Serie", "path": "#4", "page": 1}).json["ok"])
        self.assertEqual(self.client.post("/api/progress", json={"series": "Serie", "path": "#x"}).status_code, 400)

    def test_position_gardee_quand_le_tome_est_recomplete(self):
        self.A._ranger_en_tomes("Serie", self.info)
        self.client.post("/api/progress", json={"series": "Serie", "path": "#4", "page": 1})
        # Le chapitre 6 sort en tome 2 : il quitte « Hors tome » et rejoint le tome 2
        self.info["tomes"][6.0] = 2
        self.A._ranger_en_tomes("Serie", self.info)
        s = self.client.get("/api/series?id=Serie").json
        self.assertEqual([c["groupe"] for c in s["chapters"]], ["Tome 01", "Tome 01", "Tome 02", "Tome 02", "Tome 02"])
        self.assertFalse((self.root / "Serie" / "Hors tome").exists())
        self.assertEqual((s["current"], s["page"]), ("#4", 1))

    def test_supprimer_un_chapitre_du_tome(self):
        self.A._ranger_en_tomes("Serie", self.info)
        r = self.client.post("/api/delete", json={"series": "Serie", "path": "#3"})
        self.assertTrue(r.json["ok"], r.json)
        keys = [c["key"] for c in self.client.get("/api/series?id=Serie").json["chapters"]]
        self.assertEqual(keys, ["#1", "#2", "#4", "#6"])
        self.assertTrue(list((self.root / ".corbeille").rglob("Chapitre 3.cbz")))

    def test_deja_telecharges_par_numero(self):
        self.A._ranger_en_tomes("Serie", self.info)
        marques = self.A._marquer_deja([{"title": "x", "chapter_id": "4"}, {"title": "y", "chapter_id": "5"}], "Serie")
        self.assertEqual([c["deja"] for c in marques], [True, False])


class TelechargementTomesTest(unittest.TestCase):
    def test_chapitre_range_dans_son_tome(self):
        import japscan_scraper as js
        with tempfile.TemporaryDirectory() as t:
            dossier = Path(t) / "Serie"
            sc = js.JapscanScraper(dossier)

            class Faux:
                async def __aenter__(self):
                    return object()

                async def __aexit__(self, *a):
                    return False

            async def ouvrir(p):
                return ("n", "c")

            async def fermer(s):
                pass

            async def lire(url, **kw):
                return _pages(3)
            chapitres = [{"title": "​Chapitre 2: Deux", "url": "u/2/", "chapter_id": "2", "num": 2},
                         {"title": "Chapitre 9", "url": "u/9/", "chapter_id": "9", "num": 3}]
            info = {"source": "test", "tomes": {2.0: 1, 9.0: None}, "titres": {9.0: "Titre wiki"}}
            with mock.patch.object(sc, "_ouvrir_session", ouvrir), mock.patch.object(sc, "_fermer_session", fermer), \
                    mock.patch.object(js, "async_playwright", lambda: Faux()), \
                    mock.patch.object(sc, "download_chapter_pages", lire), mock.patch.dict(os.environ, {"JAPSCAN_PAUSE": "0"}):
                sc.download_manga_sync("tt", "Serie", chapitres, preparer=lambda: info)
            self.assertEqual(js.download_jobs["tt"]["status"], "completed")
            t1 = tomes_cbz.chapitres(dossier / "Tome 01" / "Serie - Tome 01.cbz")
            hors = tomes_cbz.chapitres(dossier / "Hors tome" / "Serie - Hors tome.cbz")
            self.assertEqual([(c["num"], c["titre"], c["nb"]) for c in t1], [(2.0, "Deux", 3)])
            self.assertEqual([(c["num"], c["titre"]) for c in hors], [(9.0, "Titre wiki")])


if __name__ == "__main__":
    unittest.main()


class OrganiserTest(BibliothequeTest):
    """Série ajoutée à la main, avec des tomes complets au nom encombré."""

    def setUp(self):
        super().setUp()
        self.vrac = self.root / "Gintama Integrale T01-03 [eBooks officiels][FR][CBZ]"
        for t in (1, 2, 4):
            p = self.vrac / f"Gintama T{t:02d} (Sorachi) (2007) [Digital-1700] [Manga FR].cbz"
            p.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(p, "w") as z:
                for k, d in enumerate(_pages(3, t), 1):
                    z.writestr(f"{k:03d}.jpg", d)
        (self.vrac / "cover.jpg").write_bytes(_jpeg((1, 2, 3)))
        ancien = self.vrac.name + "/Gintama T02 (Sorachi) (2007) [Digital-1700] [Manga FR].cbz"
        data = json.loads(self.A.PROGRESS_FILE.read_text())
        data[self.vrac.name] = {"current": ancien, "page": 7, "read": [self.vrac.name + "/Gintama T01 (Sorachi) (2007) [Digital-1700] [Manga FR].cbz"]}
        self.A.PROGRESS_FILE.write_text(json.dumps(data))

    def test_plan_propose(self):
        s = self.client.get("/api/series?id=" + self.vrac.name).json
        self.assertEqual(s["organiser"], {"nom": "Gintama", "tomes": 3, "a_deplacer": 3, "chapitres": 0,
                                          "premier_tome": 1, "dernier_tome": 4})
        self.assertEqual([c["title"] for c in s["chapters"]], ["Tome 01", "Tome 02", "Tome 04"])
        self.assertEqual((s["type_manquants"], s["manquants"]), ("tomes", ["3"]))

    def test_organiser(self):
        with mock.patch.object(tomes, "chercher", return_value=None):
            r = self.client.post("/api/organiser", json={"series": self.vrac.name, "nom": "Gintama"})
        self.assertEqual(r.json, {"ok": True, "id": "Gintama"})
        self.assertFalse(self.vrac.exists())
        g = self.root / "Gintama"
        self.assertEqual(sorted(str(p.relative_to(g)) for p in g.rglob("*") if p.is_file()),
                         ["Tome 01/Gintama - Tome 01.cbz", "Tome 02/Gintama - Tome 02.cbz",
                          "Tome 04/Gintama - Tome 04.cbz", "cover.jpg"])
        s = self.client.get("/api/series?id=Gintama").json
        self.assertIsNone(s["organiser"])
        self.assertEqual((s["current"], s["page"]), ("Gintama/Tome 02/Gintama - Tome 02.cbz", 7))
        self.assertEqual([c["read"] for c in s["chapters"]], [True, False, False])
        self.assertTrue(s["cover_perso"])

    def test_nom_deja_pris(self):
        r = self.client.post("/api/organiser", json={"series": self.vrac.name, "nom": "Serie"})
        self.assertEqual(r.status_code, 409)
        self.assertTrue(self.vrac.exists())

    def test_tome_complet_jamais_reecrit(self):
        with mock.patch.object(tomes, "chercher", return_value=None):
            self.client.post("/api/organiser", json={"series": self.vrac.name, "nom": "Gintama"})
        complet = self.root / "Gintama" / "Tome 01" / "Gintama - Tome 01.cbz"
        avant = complet.read_bytes()
        with self.assertRaises(FileExistsError):
            tomes_cbz.ajouter(self.root / "Gintama", "Gintama", 1, 3.0, "", _pages(1))
        self.assertEqual(complet.read_bytes(), avant)

    def test_chapitres_couverts_par_un_tome_complet(self):
        with mock.patch.object(tomes, "chercher", return_value=None):
            self.client.post("/api/organiser", json={"series": self.vrac.name, "nom": "Gintama"})
        with mock.patch.object(tomes, "_charger", return_value={"tomes": {1.0: 1, 2.0: 1, 3.0: 2, 9.0: 5}}):
            s = self.client.get("/api/series?id=Gintama").json
            self.assertEqual(s["chapters"][0]["title"], "Tome 01 · chapitres 1 à 2")
            marques = self.A._marquer_deja([{"chapter_id": "2"}, {"chapter_id": "9"}], "Gintama")
        self.assertEqual([c["deja"] for c in marques], [True, False])
