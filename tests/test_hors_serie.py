"""Hors-série : les fichiers HS, Data Book, artbook et one-shot sont regroupés à part, en premier."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as A  # noqa: E402


class HorsSerieTest(unittest.TestCase):
    def test_reconnu(self):
        for nom in ("One Piece HS - Blue (Oda) (2005) [Digital-1920] (PRiNTER-PapriKa+)",
                    "Seven Deadly Sins Data Book", "Kenshin Artbook", "Bakuman one-shot", "Seven_Deadly_Sins_-_HS1"):
            self.assertTrue(A._est_hors_serie(nom), nom)

    def test_tome_normal_non(self):
        for nom in ("One Piece - Tome 105", "Hunter x Hunter Tome 01", "Dandadan T04"):
            self.assertFalse(A._est_hors_serie(nom), nom)

    def test_titre_court(self):
        self.assertEqual(A._titre_hors_serie("One Piece HS - Yellow (Oda) (2009) [Digital-1920] [Manga FR] (PRiNTER-PapriKa+)"),
                         "Yellow (Oda) (2009)")

    def test_lecture_d_une_page_de_fiche(self):
        import hors_serie as h
        page = ('<html><head><meta property="og:title" content="One Piece - Yellow (Grand format - Autre 2009), de Eiichiro Oda | '
                'Éditions Glénat"><meta property="og:site_name" content="Éditions Glénat"></head></html>')
        infos = h.lire_page_texte(page, "https://www.glenat.com/one-piece-yellow/")
        self.assertEqual((infos["titre"], infos["annee"], infos["auteur"], infos["editeur"]),
                         ("One Piece - Yellow", 2009, "Eiichiro Oda", "Éditions Glénat"))

    def test_titre_de_secours(self):
        import hors_serie as h
        infos = h.lire_page_texte("<title>Blue (2004) | Boutique</title>", "https://exemple.org/blue")
        self.assertEqual((infos["titre"], infos["annee"], infos["editeur"]), ("Blue", 2004, "Boutique"))

    def test_adresses_refusees(self):
        import hors_serie as h
        self.assertFalse(h._adresse_permise("http://192.168.1.10/fiche"))
        self.assertFalse(h._adresse_permise("http://localhost:5002/"))
        self.assertFalse(h._adresse_permise("file:///etc/passwd"))
        self.assertTrue(h._adresse_permise("https://www.glenat.com/x"))


if __name__ == "__main__":
    unittest.main()
