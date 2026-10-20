import os
import sys
import tempfile
import unittest
from unittest import mock

import tomes


class SousTitreTest(unittest.TestCase):
    INTRO = ("Ken-ichi, le disciple ultime (史上最強の弟子 ケンイチ) est un manga écrit et dessiné par Syun Matsuena. "
             "La première saison, Ken-ichi, le disciple ultime, allant du tome 1 au tome 29.")

    def test_titre_francais_complet_avec_auteur_est_la_meme_serie(self):
        with mock.patch.object(tomes, "introduction_fr", return_value=self.INTRO):
            self.assertTrue(tomes.meme_serie_sous_titre("Kenichi", "Le Disciple Ultime Matsuena"))

    def test_une_vraie_suite_n_est_pas_la_meme_serie(self):
        with mock.patch.object(tomes, "introduction_fr", return_value=self.INTRO):
            self.assertFalse(tomes.meme_serie_sous_titre("Kenichi", "Les Disciples de l'Ombre Hors Série"))

    def test_un_seul_mot_ne_suffit_pas(self):
        with mock.patch.object(tomes, "introduction_fr", return_value=self.INTRO):
            self.assertFalse(tomes.meme_serie_sous_titre("Kenichi", "Matsuena"))

    def test_sans_article_wikipedia_jamais_la_meme_serie(self):
        with mock.patch.object(tomes, "introduction_fr", return_value=""):
            self.assertFalse(tomes.meme_serie_sous_titre("Kenichi", "Le Disciple Ultime"))


class PageWikiTraitUnionTest(unittest.TestCase):
    def test_ken_ichi_correspond_a_kenichi(self):
        self.assertTrue(tomes.page_correspond("Ken-ichi", ["Kenichi : Le Disciple Ultime", "Kenichi"]))

    def test_suite_distincte_toujours_refusee(self):
        self.assertFalse(tomes.page_correspond("Red Eyes Sword: Akame ga Kill!", ["Akame ga Kill! Zero"]))


if __name__ == "__main__":
    unittest.main()
