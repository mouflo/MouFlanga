"""Provenance saisie à la main : un nom de torrent collé est reconnu, applicable à toute la série."""
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import provenance  # noqa: E402

NOM = "Video Girl - Ai (01-15) (Katsura) (2008) [Digital-1482] (PapriKa+) [CBZ]"


class SaisieTest(unittest.TestCase):
    def test_nom_de_torrent_colle(self):
        eq, orig = provenance.analyser_saisie(NOM)
        self.assertEqual(eq, "PapriKa+")
        self.assertEqual(orig, "Torrent : " + NOM)

    def test_equipe_seule(self):
        self.assertEqual(provenance.analyser_saisie("PapriKa+"), ("PapriKa+", ""))
        self.assertEqual(provenance.analyser_saisie("PapriKa+", "Achat"), ("PapriKa+", "Achat"))


class SerieTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "mangas"
        for n in (1, 2, 3):
            d = self.root / "Serie" / f"Tome {n:02d}"
            d.mkdir(parents=True)
            with zipfile.ZipFile(d / f"Serie - Tome {n:02d}.cbz", "w") as z:
                z.writestr("000.jpg", b"x")
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        import auth
        self.A, self.auth = A, auth
        self._role = auth.role
        auth.role = lambda: "admin"
        A.MANGA_DIR = self.root
        A._scan_invalider()
        self.c = A.app.test_client()

    def tearDown(self):
        self.auth.role = self._role
        self.tmp.cleanup()

    def test_toute_la_serie_ecrase_les_deductions_et_la_saisie_precedente(self):
        import edition
        d = edition.lire(self.root / "Serie")
        provenance.noter(d, 1, "Mauvaise équipe coupée (Pap", "Saisie à la main", manuel=True, ecrase=True)
        provenance.noter(d, 2, "", "Torrent : autre.nom.faux", manuel=False)
        edition.ecrire(self.root / "Serie", d)
        r = self.c.post("/api/serie/provenance", json={"series": "Serie", "texte": NOM}).get_json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["tomes"], 3)
        p = provenance.lire(edition.lire(self.root / "Serie"))
        for t in ("1", "2", "3"):
            self.assertEqual(p[t]["equipe"], "PapriKa+")
            self.assertEqual(p[t]["origine"], "Torrent : " + NOM)
            self.assertTrue(p[t]["manuel"])

    def test_tome_seul_avec_nom_colle(self):
        import edition
        r = self.c.post("/api/tome/provenance", json={"series": "Serie", "tome": 2, "equipe": NOM, "origine": ""}).get_json()
        self.assertTrue(r["ok"], r)
        p = provenance.lire(edition.lire(self.root / "Serie"))
        self.assertEqual(p["2"]["equipe"], "PapriKa+")
        self.assertTrue(p["2"]["origine"].endswith("(PapriKa+) [CBZ]"))


if __name__ == "__main__":
    unittest.main()
