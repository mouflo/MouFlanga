"""Résumés Google Books : la présentation de la série est retirée aux phrases entières, jamais au milieu d'une phrase."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tomes  # noqa: E402

PITCH = ("Une salle de cours, un professeur, des élèves... et des coups de feu ! Les élèves de la classe 3-E du collège "
         "de Kunugigaoka sont des assassins en herbe, et leur professeur est leur cible à abattre ! ")


class ResumeIntroTest(unittest.TestCase):
    def brut(self, **kw):
        b = {"resumes_tomes": {
            "1": {"texte": PITCH + "Découvrez le quotidien insolite d'un drôle de professeur et de ses élèves !!"},
            "7": {"texte": PITCH + "Un nouvel élève arrive dans la classe E et personne ne sait d'où il vient exactement."},
        }}
        b.update(kw)
        return b

    def test_points_de_suspension_pas_une_fin_de_phrase(self):
        b = self.brut()
        r = tomes._resume_de_serie(b["resumes_tomes"]["7"]["texte"], b, 7)
        self.assertFalse(r.startswith("et des"), r)
        self.assertTrue(r.startswith("Un nouvel élève"), r)
        self.assertEqual(b["intros"], [PITCH])                    # l'intro retenue finit à « abattre ! », pas à « élèves... »

    def test_intro_fautive_deja_memorisee_ignoree(self):
        b = self.brut(intros=["Une salle de cours, un professeur, des élèves... "])
        r = tomes._resume_de_serie(b["resumes_tomes"]["7"]["texte"], b, 7)
        self.assertFalse(r.startswith("et des"), r)
        self.assertTrue(r.startswith("Un nouvel élève"), r)

    def test_abreviation_pas_une_fin_de_phrase(self):
        commun = "Le professeur de la classe E est une cible vivante que tout le monde veut abattre, dit M. "
        self.assertEqual(tomes._fin_de_phrase(commun + "Koro et la suite", commun), -1)

    def test_vraie_fin_de_phrase_gardee(self):
        commun = "Le professeur de la classe E est une cible vivante que tout le monde veut abattre ! "
        self.assertEqual(tomes._fin_de_phrase(commun + "Découvrez la suite", commun), len(commun))


if __name__ == "__main__":
    unittest.main()


class DoublonsEtQuotaTest(unittest.TestCase):
    def test_meme_notice_sur_plusieurs_tomes(self):
        t1 = PITCH + "Découvrez le quotidien insolite d'un drôle de professeur et de ses élèves !!"
        t19 = t1.replace("! ", "!")                           # mêmes mots, espaces perdus
        b = {"resumes_tomes": {"1": {"texte": t1}, "16": {"texte": t1}, "19": {"texte": t19},
                               "2": {"texte": "Une ravissante professeur d'anglais est affectée à la classe E, tueuse professionnelle."}}}
        self.assertEqual(tomes._resume_de_serie(t19, b, 19), "")
        self.assertEqual(tomes._resume_de_serie(t1, b, 16), "")
        self.assertTrue(tomes._resume_de_serie(t1, b, 1).startswith("Une salle de cours"))   # le tome 1 la garde entière

    def test_pause_apres_quota(self):
        import time
        import unittest.mock as m
        tomes._GOOGLE_PAUSE["jusqua"] = 0.0
        with m.patch.object(tomes, "cle_google_books", return_value="k"), \
             m.patch.object(tomes, "_charger", return_value={}), \
             m.patch.object(tomes._SESSION, "get") as g:
            g.return_value.status_code = 429
            self.assertEqual(tomes.resume_tome_google("Serie X", 3), "")
            self.assertEqual(g.call_count, 1)
            self.assertGreater(tomes._GOOGLE_PAUSE["jusqua"], time.time())
            self.assertEqual(tomes.resume_tome_google("Serie X", 4), "")   # pas d'appel pendant la pause
            self.assertEqual(g.call_count, 1)
        tomes._GOOGLE_PAUSE["jusqua"] = 0.0


class ApostropheTest(unittest.TestCase):
    def test_apostrophe_typographique_meme_notice(self):
        t1 = PITCH + "Découvrez le quotidien insolite d'un drôle de professeur et de ses élèves !!"
        b = {"resumes_tomes": {"1": {"texte": t1}, "16": {"texte": t1.replace("d'un", "d’un")}}}
        self.assertEqual(tomes._resume_de_serie(b["resumes_tomes"]["16"]["texte"], b, 16), "")
