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
