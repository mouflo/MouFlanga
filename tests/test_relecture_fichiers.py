"""Relecture du ComicInfo.xml des tomes : édition, ISBN, chapitres (liens) et verrou « à la main » suivent les fichiers."""
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class RelectureFichiersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root = t / "mangas"
        d = self.root / "Berserk" / "Tome 01"
        d.mkdir(parents=True)
        with zipfile.ZipFile(d / "Berserk - Tome 01.cbz", "w") as z:
            z.writestr("001.jpg", b"x")
            z.writestr("ComicInfo.xml", '<ComicInfo><Series>Berserk</Series><Number>1</Number><Format>Édition colossale</Format>'
                       '<GTIN>9782723488525</GTIN><Notes>MouFlanga: {"v":1,"sommaire":"manuel","valide_le":"2026-10-01",'
                       '"serie":{"anilist":30002,"choisi":true},"volumes_attendus":12}</Notes>'
                       '<Pages><Page Image="0" Bookmark="1. Le Chevalier noir"/><Page Image="40" Bookmark="2. Rencontre"/></Pages></ComicInfo>')
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        self.A = A
        A.MANGA_DIR = self.root
        A.RESUMES = t / "resumes.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_tout_est_repris(self):
        infos = self.A._relire_fichiers_serie("Berserk", {})
        self.assertEqual(infos["edition"], "Édition colossale")
        self.assertEqual(infos["volumes_attendus"], 12)
        self.assertEqual(infos["anilist_choisi"], 30002)
        self.assertEqual(infos["isbn"]["1"], "9782723488525")
        rec = infos["sommaires"]["1"]
        self.assertTrue(rec["manuel"])
        self.assertEqual([(c["num"], c["image"]) for c in rec["chapitres"]], [(1.0, 0), (2.0, 40)])
        self.assertTrue(infos["fichiers_relus"])

    def test_ce_qui_est_deja_note_n_est_pas_remplace(self):
        deja = {"edition": "Perfect", "isbn": {"1": "9782756058061"}, "anilist_choisi": 5,
                "sommaires": {"1": {"chapitres": [{"num": 1.0, "titre": "A", "image": 3}]}}}
        infos = self.A._relire_fichiers_serie("Berserk", dict(deja))
        self.assertEqual(infos["edition"], "Perfect")
        self.assertEqual(infos["isbn"]["1"], "9782756058061")
        self.assertEqual(infos["anilist_choisi"], 5)
        self.assertEqual(infos["sommaires"]["1"]["chapitres"][0]["image"], 3)


if __name__ == "__main__":
    unittest.main()
