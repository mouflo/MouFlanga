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
        A.CHOIX = t / "choix.json"                       # pas la vraie mémoire des choix
        A.RESUMES = t / "resumes.json"                   # ni les vrais résumés écrits à la main
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
        self.assertEqual({k: s["organiser"][k] for k in ("nom", "tomes", "a_deplacer", "chapitres", "premier_tome", "dernier_tome", "archives", "pdf")},
                         {"nom": "Gintama", "tomes": 3, "a_deplacer": 3, "chapitres": 0, "premier_tome": 1, "dernier_tome": 4,
                          "archives": 0, "pdf": 0})
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
            self.assertEqual((s["chapters"][0]["title"], s["chapters"][0]["sous"]), ("Tome 01", "Chapitres 1 à 2"))
            marques = self.A._marquer_deja([{"chapter_id": "2"}, {"chapter_id": "9"}], "Gintama")
        self.assertEqual([c["deja"] for c in marques], [True, False])


class ImportTest(BibliothequeTest):
    """Archives de plusieurs tomes et PDF ajoutés à la main."""

    def _attendre(self, nom):
        import time
        for _ in range(200):
            if not (self.A._RANGEMENTS.get(nom) or {}).get("en_cours"):
                return self.A._RANGEMENTS.get(nom)
            time.sleep(0.05)
        self.fail("import trop long")

    def setUp(self):
        super().setUp()
        self.A.LOT_MIN = 1                                # dans les tests, toute archive .zip est un « paquet »
        d = self.root / "nanatsu no taizai"
        d.mkdir()
        with zipfile.ZipFile(d / "nanatsu no taizai.zip", "w") as z:
            z.writestr("Nanatsu No Taizai Tome 29/00.png", _jpeg((9, 9, 9)))          # couverture hors chapitre
            for ch in (232, 233):
                for k in (1, 2):
                    z.writestr(f"Nanatsu No Taizai Tome 29/{ch}/{ch}-{k:03d}.png", _jpeg((ch % 255, k, 0)))
            for k in (1, 2, 3):
                z.writestr(f"Nanatsu No Taizai Tome 30/Nanatsu.Tome 30.P{k:03d}.jpg", _jpeg((k, 30, 0)))
        import pymupdf
        g = self.root / "Gamaran" / "Gamaran.T01.FRENCH.HYBRiD.eBook-X"
        g.mkdir(parents=True)
        doc = pymupdf.open()
        for k in range(3):
            page = doc.new_page(width=300, height=450)
            page.insert_image(page.rect, stream=_jpeg((k * 50, 0, 0)))
        doc.save(g / "Gamaran.T01.FRENCH.HYBRiD.eBook-X.pdf")

    def test_reconnaissance(self):
        import importer
        self.assertEqual([importer.numero_tome(n) for n in ("Kenichi.t01-29", "Toriko.Tome.38", "tome 07", "Chapitre 3")],
                         [None, 38, 7, None])
        s = self.client.get("/api/series?id=nanatsu no taizai").json
        self.assertEqual(s["organiser"]["nom"], "Nanatsu no Taizai")
        self.assertEqual(s["organiser"]["archives"], 1)
        self.assertTrue(s["chapters"][0]["a_importer"])
        self.assertEqual(self.client.get("/api/series?id=Gamaran").json["organiser"]["pdf"], 1)

    def test_archive_de_tomes(self):
        r = self.client.post("/api/organiser", json={"series": "nanatsu no taizai", "nom": "Nanatsu no Taizai"})
        self.assertTrue(r.json["ok"], r.json)
        with mock.patch.object(tomes, "chercher", return_value=None):
            etat = self._attendre("Nanatsu no Taizai")
        self.assertIn("2 tome(s) importé(s)", etat["message"])
        s = self.client.get("/api/series?id=Nanatsu no Taizai").json
        self.assertEqual([(c["title"], c.get("nb")) for c in s["chapters"]],
                         [("Chapitre 232", 3), ("Chapitre 233", 2), ("Tome 30", None)])  # couverture en tête du 232
        self.assertFalse(list((self.root / "Nanatsu no Taizai").glob("*.zip")))     # original à la corbeille
        self.assertTrue(list((self.root / ".corbeille").rglob("nanatsu no taizai.zip")))
        self.assertFalse((self.root / "Nanatsu no Taizai" / ".import").exists())

    def test_pdf(self):
        with mock.patch.object(tomes, "chercher", return_value=None):
            self.client.post("/api/organiser", json={"series": "Gamaran", "nom": "Gamaran"})
            self._attendre("Gamaran")
        f = self.root / "Gamaran" / "Tome 01" / "Gamaran - Tome 01.cbz"
        self.assertEqual(len(__import__("archives").pages(f)), 3)
        self.assertEqual(sorted(p.name for p in (self.root / "Gamaran").iterdir()), ["Tome 01"])   # dossier du PDF vidé

    def test_apprend_des_choix(self):
        self.A._noter_choix("Toriko [Scan-FR]", "Toriko Scan", "Toriko")
        self.assertEqual(self.A._appris("Autre", "One Piece Scan"), "One Piece")          # mot que tu retires
        self.assertEqual(self.A._appris("Toriko [Scan-FR]", "peu importe"), "Toriko")       # même dossier, même nom

    def test_organisation_automatique(self):
        with mock.patch.dict(os.environ, {"ORGANISER_AUTO": "1"}), mock.patch.object(tomes, "chercher", return_value=None):
            self.A._AUTO["dernier"] = 0
            self.client.get("/api/library")
            nom = next(n for n in self.A._RANGEMENTS)
            self._attendre(nom)
        self.assertIn(nom, ("Gamaran", "Nanatsu no Taizai"))


class CasArchivesTest(unittest.TestCase):
    """Formats rencontrés dans de vraies archives."""

    def _archive(self, dossier, noms):
        p = Path(dossier) / "x.zip"
        with zipfile.ZipFile(p, "w") as z:
            for n in noms:
                z.writestr(n, _jpeg((len(n) % 255, 0, 0)))
        return p

    def test_suite_dans_la_meme_archive(self):
        import importer
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            lot = self._archive(t, ["20th-century-boys/Tome.01/001.jpg", "20th-century-boys/Tome.01/002.jpg",
                                    "20th-century-boys/Tome.02/001.jpg", "21st-century-boys/volume-1/001.jpg"])
            serie = t / "20th Century Boys"
            serie.mkdir()
            crees = importer.importer_lot(lot, serie, "20th Century Boys", {})
            self.assertEqual(sorted(str(c.relative_to(t)) for c in crees),
                             ["20th Century Boys/Tome 01/20th Century Boys - Tome 01.cbz",
                              "20th Century Boys/Tome 02/20th Century Boys - Tome 02.cbz",
                              "21st Century Boys/Tome 01/21st Century Boys - Tome 01.cbz"])

    def test_numero_sans_le_mot_tome_et_parentheses(self):
        import importer
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            lot = self._archive(t, ["MAR/MAR.07/a.jpg", "MAR/MAR.08/a.jpg", "tome 01 (ch. 01 - 07)/b.jpg"])
            importer.extraire(lot, t / "x")
            series, _ = importer.repartir(t / "x")
            # numéros à la suite (1 et 7-8) : une seule série
            self.assertEqual({p: sorted(v) for p, v in series.items()}, {"": [1, 7, 8]})

    def _repartir(self, noms, fichiers_en_plus=()):
        import importer
        t = Path(self.tmp.name) / "r"
        if t.exists():
            import shutil
            shutil.rmtree(t)
        t.mkdir(parents=True)
        lot = self._archive(t.parent, noms)
        importer.extraire(lot, t)
        importer.deplier(t)
        return importer.repartir(t)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_shot_et_tome_dans_le_nom_des_images(self):
        series, _ = self._repartir(["Jaco/Jaco.p001.jpg", "Jaco/Jaco.p002.jpg"])
        self.assertEqual({k: sorted(v) for k, v in series.items()}, {"": [1]})
        series, _ = self._repartir(["Side/Side story.Tome 02.P001.jpg"])
        self.assertEqual({k: sorted(v) for k, v in series.items()}, {"": [2]})

    def test_chapitres_sans_tome_et_plages(self):
        series, _ = self._repartir(["green/001/1_01.jpg", "green/002/2_01.jpg"])
        self.assertEqual(sorted(series[""][None]["chapitres"]), [1.0, 2.0])          # « Hors tome »
        import importer
        self.assertIsNone(importer._tome_souple("the breaker 01 à 10"))

    def test_archives_et_pdf_interieurs(self):
        import importer, pymupdf
        t = Path(self.tmp.name)
        interieur = t / "Slam Dunk - T02.zip"
        with zipfile.ZipFile(interieur, "w") as z:
            z.writestr("p1.jpg", _jpeg((1, 2, 3)))
        doc = pymupdf.open(); page = doc.new_page(width=200, height=300); page.insert_image(page.rect, stream=_jpeg((9, 9, 9)))
        pdf = t / "Slam.T03.FRENCH.pdf"; doc.save(pdf)
        lot = t / "lot.zip"
        with zipfile.ZipFile(lot, "w") as z:
            z.write(interieur, "Slam Dunk/Slam Dunk - T02.zip")
            z.write(pdf, "Slam Dunk/Slam.T03.FRENCH/Slam.T03.FRENCH.pdf")
            z.writestr("Slam Dunk/Slam Dunk - T01/a.jpg", _jpeg((5, 5, 5)))
        dest = t / "x"
        importer.extraire(lot, dest); importer.deplier(dest)
        series, _ = importer.repartir(dest)
        self.assertEqual(sorted(series[""]), [1, 2, 3])


class EtatSerieTest(OrganiserTest):
    """Marque fini / incomplet / en cours sur la couverture."""

    def _etat(self, statut):
        with mock.patch.object(tomes, "chercher", return_value=None):
            self.client.post("/api/organiser", json={"series": self.vrac.name, "nom": "Gintama"})
        with mock.patch.object(tomes, "_charger", return_value={"statut_officiel": statut, "tomes": {}}), \
                mock.patch.object(self.A, "_remplir_statuts"):
            lib = {s["id"]: s for s in self.client.get("/api/library").json["series"]}
            serie = self.client.get("/api/series?id=Gintama").json
        return lib["Gintama"]["etat"], serie["etat_texte"]

    def test_incomplet(self):                      # tomes 1, 2 et 4 sur 4
        etat, texte = self._etat({"statut": "FINISHED", "volumes": 4, "chapitres": 30, "titre": "Gintama"})
        self.assertEqual(etat, "incomplet")
        self.assertIn("il te manque le tome 3", texte)

    def test_fini(self):                           # 2 tomes officiels, les tomes 1 et 2 sont là
        etat, texte = self._etat({"statut": "FINISHED", "volumes": 2, "chapitres": 10, "titre": "Gintama"})
        self.assertEqual(etat, "fini")
        self.assertIn("tout est là", texte)

    def test_en_cours(self):
        etat, texte = self._etat({"statut": "RELEASING", "volumes": None, "chapitres": None, "titre": "Gintama"})
        self.assertEqual((etat, texte), ("en_cours", "En cours de parution."))


class VolumeTest(unittest.TestCase):
    def test_volume_devient_un_tome(self):
        import japscan_scraper as js
        with tempfile.TemporaryDirectory() as t:
            dossier = Path(t) / "Gamaran"
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
                return _pages(4)
            vols = [{"title": "Volume 21", "url": "u/volume-21/", "chapter_id": "volume-21", "volume": 21, "num": 1},
                    {"title": "Volume 22: FIN", "url": "u/volume-22/", "chapter_id": "volume-22", "volume": 22, "num": 2}]
            with mock.patch.object(sc, "_ouvrir_session", ouvrir), mock.patch.object(sc, "_fermer_session", fermer), \
                    mock.patch.object(js, "async_playwright", lambda: Faux()), \
                    mock.patch.object(sc, "download_chapter_pages", lire), mock.patch.dict(os.environ, {"JAPSCAN_PAUSE": "0"}):
                sc.download_manga_sync("vv", "Gamaran", vols, preparer=lambda: {"source": "t", "tomes": {}, "titres": {}})
            self.assertTrue((dossier / "Tome 21" / "Gamaran - Tome 21.cbz").is_file())
            self.assertTrue((dossier / "Tome 22" / "Gamaran - Tome 22.cbz").is_file())


class OccupeTest(BibliothequeTest):
    def test_occupe(self):
        c = self.A.app.test_client()                     # sans connexion, depuis le serveur lui-même
        self.assertEqual(c.get("/api/occupe").json, {"occupe": False, "raisons": []})
        self.A._RANGEMENTS["Serie"] = {"en_cours": True}
        try:
            self.assertEqual(c.get("/api/occupe").json["raisons"], ["rangement de Serie"])
        finally:
            self.A._RANGEMENTS.pop("Serie")
        self.assertEqual(c.get("/api/occupe", environ_base={"REMOTE_ADDR": "192.168.1.50"}).status_code, 401)


class RenommerEtOrdreTest(BibliothequeTest):
    def test_ordre_et_compte_melange(self):
        """Tomes complets 1-2 et tome 3 à chapitres (cas de Karate) : dans l'ordre, et « 3 tomes »."""
        d = self.root / "Karate"
        for t in (1, 2):
            p = d / f"Tome {t:02d}" / f"Karate - Tome {t:02d}.cbz"
            p.parent.mkdir(parents=True)
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("001.jpg", _jpeg((t, 0, 0)))
        tomes_cbz.ajouter(d, "Karate", 3, 21.0, "", _pages(2))
        tomes_cbz.ajouter(d, "Karate", 3, 22.0, "", _pages(2))
        s = self.client.get("/api/series?id=Karate").json
        self.assertEqual([c["title"] for c in s["chapters"]], ["Tome 01", "Tome 02", "Chapitre 21", "Chapitre 22"])
        self.assertEqual(s["compte"], "3 tomes")

    def test_renommer(self):
        self.A._ranger_en_tomes("Serie", self.info)
        r = self.client.post("/api/renommer", json={"series": "Serie", "nom": "Nouvelle Série"})
        self.assertEqual((r.json["ok"], r.json["id"]), (True, "Nouvelle Série"))
        noms = sorted(p.name for p in (self.root / "Nouvelle Série").rglob("*.cbz"))
        self.assertEqual(noms, ["Nouvelle Série - Hors tome.cbz", "Nouvelle Série - Tome 01.cbz", "Nouvelle Série - Tome 02.cbz"])
        s = self.client.get("/api/series?id=Nouvelle Série").json
        self.assertEqual((s["current"], [c["read"] for c in s["chapters"]][:2]), ("#3", [True, True]))
        self.assertEqual(self.client.post("/api/renommer", json={"series": "Nouvelle Série", "nom": "Nouvelle Série"}).status_code, 400)

    def test_resume_modifie_a_la_main(self):
        r = self.client.post("/api/resume", json={"series": "Serie", "texte": "  Mon résumé.  "})
        self.assertTrue(r.json["ok"])
        s = self.client.get("/api/series?id=Serie").json
        self.assertEqual((s["resume"], s["resume_langue"]), ("Mon résumé.", "perso"))
        self.client.post("/api/renommer", json={"series": "Serie", "nom": "Autre"})        # le résumé suit
        self.assertEqual(self.client.get("/api/series?id=Autre").json["resume"], "Mon résumé.")
        self.client.post("/api/resume", json={"series": "Autre", "texte": ""})              # retour à l'automatique
        self.assertNotEqual(self.client.get("/api/series?id=Autre").json["resume_langue"], "perso")
        self.assertEqual(self.client.post("/api/resume", json={"series": "Inconnue", "texte": "x"}).status_code, 404)

    def test_renommer_vers_serie_existante_propose_la_fusion(self):
        """Cas d'« Alice-in-borderland » (tomes 1-5, 7) renommée en « Alice in Borderland » (tome 6, et un tome 7 en double)."""
        for serie, ts in (("Alice-in-borderland", (1, 7)), ("Alice in Borderland", (6, 7))):
            for t in ts:
                f = self.root / serie / f"Tome {t:02d}" / f"{serie} - Tome {t:02d}.cbz"
                f.parent.mkdir(parents=True)
                with zipfile.ZipFile(f, "w") as z:
                    z.writestr("001.jpg", _jpeg((t, 0, 0)))
        self.A._write_json(self.A.PROGRESS_FILE, {
            "Alice-in-borderland": {"read": ["Alice-in-borderland/Tome 01/Alice-in-borderland - Tome 01.cbz"], "last": "2026-10-01 10:00"},
            "Alice in Borderland": {"read": [], "current": "Alice in Borderland/Tome 06/Alice in Borderland - Tome 06.cbz", "page": 4, "last": "2026-10-05 10:00"}})
        r = self.client.post("/api/renommer", json={"series": "Alice-in-borderland", "nom": "Alice in Borderland"})
        self.assertEqual((r.status_code, r.json.get("existe")), (409, True))
        r = self.client.post("/api/renommer", json={"series": "Alice-in-borderland", "nom": "Alice in Borderland", "fusionner": True})
        self.assertTrue(r.json["ok"], r.json)
        self.assertIn("1 fichier(s) en double", r.json["message"])
        self.assertFalse((self.root / "Alice-in-borderland").exists())
        noms = sorted(p.name for p in (self.root / "Alice in Borderland").rglob("*.cbz"))
        self.assertEqual(noms, ["Alice in Borderland - Tome 01.cbz", "Alice in Borderland - Tome 06.cbz", "Alice in Borderland - Tome 07.cbz"])
        self.assertEqual(len(list((self.root / ".corbeille").rglob("*.cbz"))), 1)
        prog = self.A._read_json(self.A.PROGRESS_FILE, {})
        self.assertNotIn("Alice-in-borderland", prog)
        p = prog["Alice in Borderland"]
        self.assertEqual((p["read"], p["page"]), (["Alice in Borderland/Tome 01/Alice in Borderland - Tome 01.cbz"], 4))
