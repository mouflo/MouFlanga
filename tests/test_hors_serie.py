"""Hors-série : les fichiers HS, Data Book, artbook et one-shot sont regroupés à part, en premier."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as A  # noqa: E402


class HorsSerieTest(unittest.TestCase):
    def test_reconnu(self):
        for nom in ("One Piece HS - Blue (Oda) (2005) [Digital-1920] (PRiNTER-PapriKa+)",
                    "Seven Deadly Sins Data Book", "Kenshin Artbook", "Bakuman one-shot", "Seven_Deadly_Sins_-_HS1", "Naruto Gaiden"):
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

    def test_numero_a_part_et_fixe(self):
        """Un hors-série a son numéro (1000 et plus) pour sa couverture et sa fiche ⓘ ; en ajouter un ne change pas les autres."""
        blue, red = Path("/m/One Piece/One Piece HS - Blue.cbz"), Path("/m/One Piece/OP Databook Red.cbz")
        tome = Path("/m/One Piece/One Piece - Tome 105.cbz")
        n = A._numeros_hs([blue, tome])
        self.assertEqual(list(n), [str(blue)])
        self.assertGreaterEqual(n[str(blue)], A.HS_BASE)
        self.assertEqual(A._numeros_hs([red, blue, tome])[str(blue)], n[str(blue)])
        self.assertTrue(A._est_numero_hs(n[str(blue)]) and not A._est_numero_hs(105))


if __name__ == "__main__":
    unittest.main()


class FandomTest(unittest.TestCase):
    """Fiche d'un databook sur le wiki Fandom : titre, éditeur, pages, « à lire après le tome N »."""

    def test_fiche_databook(self):
        import hors_serie
        from unittest import mock
        wikitexte = ("{{Databook box\n| nom = Blue : Grand Data File\n| parutionf = novembre 2005\n| editf = Glénat\n| pages = 196\n"
                     "| isbnf = ISBN 9782723450263\n}}\n'''''One Piece Blue : Grand Data File''''' est le second [[Databooks|Databook]] "
                     "publié en novembre 2005 en France. Il résume les 24 premiers [[Tomes One Piece|tomes]].\n")
        def get(url, params=None, timeout=None):
            if params["action"] == "query":
                return mock.Mock(status_code=200, headers={"content-type": "application/json"},
                                 json=mock.Mock(return_value={"query": {"search": [{"title": "All Blue"}, {"title": "One Piece Blue : Grand Data File"}]}}))
            if params["page"] == "All Blue":
                return mock.Mock(json=mock.Mock(return_value={"parse": {"wikitext": {"*": "{{Lieu\n| nom = All Blue\n}}\nUne mer."}}}))
            return mock.Mock(json=mock.Mock(return_value={"parse": {"wikitext": {"*": wikitexte}}}))
        with mock.patch.object(hors_serie._SESSION, "get", side_effect=get), \
                mock.patch.object(hors_serie, "_wikis_fandom", return_value=["https://onepiece.fandom.com/fr/api.php"]):
            f = hors_serie.fandom("One Piece", "Blue")
        self.assertEqual((f["titre"], f["editeur"], f["pages"], f["annee"], f["apres_tome"], f["type"]),
                         ("One Piece Blue : Grand Data File", "Glénat", "196", 2005, 24, "Databook"))
