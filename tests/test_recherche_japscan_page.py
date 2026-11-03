"""Recherche Japscan lue dans la page /catalogue : titres propres, seulement les œuvres cherchées, une fois chacune."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import japscan_scraper as J  # noqa: E402


class ResultatsPageTest(unittest.TestCase):
    def test_etiquettes_du_site_ne_sont_pas_des_titres(self):
        brut = [["/manga/terra-formars/", "", ["En Cours", "Terra Formars"]], ["/manga/terra-formars/", "", ["Terminé"]],
                ["/manhua/autre-chose/", "", ["Terra"]], ["/manga/terra-formars-gaiden/", "", ["Terminé"]]]
        r = J._resultats_de_la_page(brut, "Terra formars")
        self.assertEqual([x["name"] for x in r], ["Terra Formars", "Terra Formars Gaiden"])

    def test_titre_du_lien_prefere(self):
        r = J._resultats_de_la_page([["/manga/terra-formars/", "Terra Formars", ["En Cours"]]], "terra formars")
        self.assertEqual(r[0]["name"], "Terra Formars")


if __name__ == "__main__":
    unittest.main()


class ChapitresDeLaPageTest(unittest.TestCase):
    def test_liste_de_volumes_de_la_nouvelle_presentation(self):
        from bs4 import BeautifulSoup
        html = ('<a href="/manga/terra-formars/1/1">Commencer la lecture</a>'
                '<ul><li><a data-chapter-slug="22" href="/manga/terra-formars/22/1">Volume 22 27 novembre 2021 · 208 p.</a></li>'
                '<li><a data-chapter-slug="1" href="/manga/terra-formars/1/1">Volume 1 27 novembre 2021 · 214 p.</a></li>'
                '<li><a data-chapter-slug="1" href="/manga/autre/1/1">Volume 1</a></li></ul>')
        r = J._chapitres_de_la_page(BeautifulSoup(html, "html.parser"), "terra-formars", "manga")
        self.assertEqual([(c["volume"], c["url"]) for c in r],
                         [(22, "https://japscan.st/manga/terra-formars/22/1"), (1, "https://japscan.st/manga/terra-formars/1/1")])
