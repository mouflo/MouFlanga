"""Langue : l'anglais est refusé à tout prix (marques explicites seulement) ; un résultat sans marque est accepté seulement si un profil le juge bon."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auto_telechargement  # noqa: E402
import regles  # noqa: E402
import suivi  # noqa: E402


class AnglaisTest(unittest.TestCase):
    def test_marques_anglaises(self):
        for t in ("One-Punch Man T01 à T19 [CBR-CBZ ENG] [Ebooks Officiels]", "20th Century Boys - Intégrale (22 tomes) [PDF] [EN]",
                  "Kaf.T01.ENGLISH.CBZ", "Kaf T01 (EN)", "Kaf T01 [PDF EN]", "Kaf_T01_ENG"):
            self.assertTrue(regles.est_anglais(t), t)

    def test_francais_jamais_pris_pour_de_l_anglais(self):
        for t in ("One.Piece.En.Couleurs.Compresse.[T001.T104].FR.[CBZ]-TeamChromatique", "Boutonne.en.jalousie.2025.FRENCH.CBZ", "ONE PIECE EN COULEURS FR",
                  "Dengeki Daisy T01 FR", "Kaf [En Couleurs] FR", "Air.Gear.T01.FRENCH.CBZ.eBook-ebdz", "Kaf MULTI T02"):
            self.assertFalse(regles.est_anglais(t), t)


class FiltreTest(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.ancien = regles.FICHIER
        regles.FICHIER = Path(self.dossier.name) / "regles.json"

    def tearDown(self):
        regles.FICHIER = self.ancien
        self.dossier.cleanup()

    def res(self, titre):
        return {"titre": titre, "taille": 1, "sources": 9, "indexeur": "I", "badges": ["🇫🇷 FR"] if "FR" in titre else [], "lien": "http://x/" + titre}

    def test_anglais_refuse_meme_sans_profil(self):
        out = regles.filtrer([self.res("Kaf T01 ENG FR"), self.res("Kaf T02 FR")], "Kaf", avec_rejets=True)
        self.assertEqual({x["titre"]: bool(x["rejet"]) for x in out}, {"Kaf T01 ENG FR": True, "Kaf T02 FR": False})
        self.assertEqual([x["titre"] for x in regles.filtrer([self.res("Kaf T01 ENG FR"), self.res("Kaf T02 FR")], "Kaf")], ["Kaf T02 FR"])

    def test_profil_francais_exige_des_indices(self):
        f1 = regles.enregistrer_format("", "Marqué français", "", "0", [{"type": "badge", "valeur": "FR"}])
        f2 = regles.enregistrer_format("", "Vocabulaire", "", "0", [{"type": "regex", "valeur": r"\b(tomes?|int[ée]grale)\b"}])
        regles.enregistrer_profil("", "Manga · Français", True, "", "", [], "", scores={f1: "100", f2: "30"}, score_min="30", sources_min="1")
        out = {x["titre"]: x for x in regles.filtrer([self.res("Kaf Intégrale CBZ"), self.res("Kaf T01 FR"), self.res("Kaf 01-09")], "Kaf", avec_rejets=True)}
        self.assertEqual(out["Kaf Intégrale CBZ"]["rejet"], "")           # sans marque mais mot français
        self.assertEqual(out["Kaf T01 FR"]["rejet"], "")
        self.assertIn("score trop bas", out["Kaf 01-09"]["rejet"])        # aucun indice
        self.assertEqual(out["Kaf Intégrale CBZ"]["profil"], "Manga · Français")

    def test_sans_marque_fr_pris_seulement_si_un_profil_l_accepte(self):
        sans_profil = {"titre": "Kaf.T01.CBZ", "score": 0, "sources": 5, "badges": [], "rejet": "", "lien": "http://x", "profil": ""}
        avec_profil = {**sans_profil, "profil": "Manga · Français"}
        self.assertEqual(auto_telechargement.plan([sans_profil], set(), 1)["torrents"], [])
        self.assertEqual(len(auto_telechargement.plan([avec_profil], set(), 1)["torrents"]), 1)
        i = {"tomes": set(), "source": "", "qualite": "Digital", "equipe": "", "equipe_tomes": {}, "complete": False, "en_cours": False, "profil": True,
             "scores_tomes": {}, "arret": None}
        self.assertEqual(suivi.propositions_pour("Kaf", i, [sans_profil], []), [])
        self.assertEqual(len(suivi.propositions_pour("Kaf", i, [avec_profil], [])), 1)

    def test_refuse_n_est_jamais_propose(self):
        r = {"titre": "Kaf.T01.ENG.FR", "score": 0, "sources": 5, "badges": ["🇫🇷 FR"], "rejet": "marqué en anglais", "lien": "http://x"}
        i = {"tomes": set(), "source": "", "qualite": "Digital", "equipe": "", "equipe_tomes": {}, "complete": False, "en_cours": False, "profil": False,
             "scores_tomes": {}, "arret": None}
        self.assertEqual(suivi.propositions_pour("Kaf", i, [r], []), [])


if __name__ == "__main__":
    unittest.main()
