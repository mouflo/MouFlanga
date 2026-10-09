"""Identification d'un hors-série : enregistrer le choix, l'afficher dans la liste, le retirer."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class IdentificationHorsSerieTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "mangas"
        serie = self.root / "One Piece"
        serie.mkdir(parents=True)
        (serie / "One Piece HS - Blue (Oda) (2005) [Digital-1920] (PRiNTER-PapriKa+).cbz").write_bytes(b"x")
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        self.A = A
        A.MANGA_DIR = self.root
        import auth
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        self.client = A.app.test_client()
        with self.client.session_transaction() as sess:
            sess["u"], sess["f"] = "test", auth._fingerprint()
        self.cle = "One Piece/One Piece HS - Blue (Oda) (2005) [Digital-1920] (PRiNTER-PapriKa+).cbz"

    def tearDown(self):
        self.tmp.cleanup()

    def titre_affiche(self):
        entrees = self.A._entrees(self.A._scan()["One Piece"])
        return next(e for e in entrees if e.get("groupe") == "Hors-série")

    def test_choisir_puis_retirer(self):
        rep = self.client.post("/api/hors-serie", json={"series": "One Piece", "key": self.cle, "action": "choisir",
                                                        "titre": "One Piece — Eiichiro Oda. Blue", "annee": "2004",
                                                        "auteur": "Eiichiro Oda", "source": "Google Books",
                                                        "lien": "https://books.google.be/x"})
        self.assertTrue(rep.get_json()["ok"])
        e = self.titre_affiche()
        self.assertEqual(e["title"], "One Piece — Eiichiro Oda. Blue")
        self.assertIn("2004", e["sous"])
        self.client.post("/api/hors-serie", json={"series": "One Piece", "key": self.cle, "action": "retirer"})
        self.assertEqual(self.titre_affiche()["title"], "Blue (Oda) (2005)")

    def test_titre_obligatoire(self):
        rep = self.client.post("/api/hors-serie", json={"series": "One Piece", "key": self.cle, "action": "choisir", "titre": "  "})
        self.assertEqual(rep.status_code, 400)

    def test_fichier_inconnu(self):
        rep = self.client.post("/api/hors-serie", json={"series": "One Piece", "key": "One Piece/inconnu.cbz", "action": "choisir", "titre": "X"})
        self.assertEqual(rep.status_code, 404)


if __name__ == "__main__":
    unittest.main()
