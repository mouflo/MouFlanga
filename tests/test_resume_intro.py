import unittest

import tomes


class ResumeSansIntro(unittest.TestCase):
    INTRO = "Tatsumi quitte son village natal pour la Cité impériale où il fait la rencontre d'un groupe d'assassins : le Night Raid, avec à sa tête Akame. "

    def test_intro_reconnue_malgre_une_virgule_ou_une_apostrophe_differente(self):
        reste = tomes._apres_intro("Tatsumi quitte son village natal pour la Cité impériale où il fait la rencontre d’un groupe d’assassins: le Night Raid avec à sa tête Akame. Esdeath arrive.", self.INTRO)
        self.assertEqual(reste, "Esdeath arrive.")

    def test_notice_recopiee_gardee_pour_le_plus_petit_tome_seulement(self):
        texte = "Mine commence à prendre conscience de ses sentiments pour Tatsumi, tandis que Najenda est prête à se battre."
        brut = {"resumes_tomes": {"9": {"texte": texte}, "12": {"texte": texte}}, "intros": []}
        self.assertEqual(tomes._resume_de_serie(texte, brut, 9), texte)
        self.assertEqual(tomes._resume_de_serie(texte, brut, 12), "")

    def test_partie_du_tome_apres_le_marqueur_du_fichier(self):
        generale = "Dans un monde peuplé de créatures étranges, Tatsumi est un jeune garçon de la campagne en quête de rêve."
        propre = "Mine commence à prendre conscience de ses sentiments pour Tatsumi, tandis que Najenda se prépare."
        r = tomes.resume_propre_du_fichier("Série inconnue", 9, f"{generale}\n\n>Tome 9< \n{propre}", {})
        self.assertEqual(r, propre)


class AutreSerie(unittest.TestCase):
    def test_notice_d_une_serie_derivee_refusee(self):
        self.assertTrue(tomes._autre_serie("Akame ga Kill ! Zero - Tome 10", "Akame ga Kill !"))
        self.assertFalse(tomes._autre_serie("Akame ga Kill ! - Tome 10", "Akame ga Kill !"))
        self.assertFalse(tomes._autre_serie("Akame ga Kill ! Zero - Tome 10", "Akame ga Kill ! Zero"))
