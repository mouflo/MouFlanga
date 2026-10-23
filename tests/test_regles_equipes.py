"""Profils par équipe tenus à jour, série visée comparée par son nom entier, téléchargement automatique d'une série."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auto_telechargement  # noqa: E402
import regles  # noqa: E402


def r(titre, tomes=None, score=0, sources=5, badges=("🇫🇷 FR",), rejet="", lien="http://x/"):
    return {"titre": titre, "score": score, "sources": sources, "badges": list(badges), "rejet": rejet, "lien": lien + titre, "taille": 1, "indexeur": "I"}


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.ancien, self.connues = regles.FICHIER, regles.SERIES_CONNUES
        regles.FICHIER = Path(self.dossier.name) / "regles.json"

    def tearDown(self):
        regles.FICHIER, regles.SERIES_CONNUES = self.ancien, self.connues
        self.dossier.cleanup()


class SerieVisee(BaseTest):
    def test_gantz_ne_touche_pas_gantz_osaka(self):
        regles.SERIES_CONNUES = lambda: ["Gantz", "Gantz : Osaka"]
        regles.enregistrer_profil("", "Papri", True, "", "VOSTFR", ["Gantz"], "")
        self.assertEqual(len(regles.filtrer([r("Gantz T01 VOSTFR")], "Gantz T05")), 0)          # profil appliqué
        self.assertEqual(len(regles.filtrer([r("Gantz Osaka T01 VOSTFR")], "Gantz : Osaka T03")), 1)   # profil non appliqué

    def test_air_gear_et_air_gear_unlimited(self):
        regles.SERIES_CONNUES = lambda: ["Air Gear"]
        regles.enregistrer_profil("", "Dog", True, "Dogbanov", "", ["Air Gear Unlimited"], "")
        self.assertEqual(len(regles.filtrer([r("Air.Gear.T01.ebdz")], "Air Gear intégrale")), 1)   # série « Air Gear » : pas de profil
        self.assertEqual(len(regles.filtrer([r("Air.Gear.T01.ebdz")], "Air Gear Unlimited T01")), 0)  # série « Unlimited » : profil

    def test_profil_precis_passe_avant_le_general(self):
        regles.enregistrer_profil("", "Général", True, "FR", "", [], "")
        regles.enregistrer_profil("", "Kaf", True, "", "VO", ["Kaf"], "")
        self.assertEqual(regles.profil_pour("Kaf 01")["nom"], "Kaf")
        self.assertEqual(regles.profil_pour("Autre")["nom"], "Général")


class Equipes(BaseTest):
    def test_deux_series_font_un_profil(self):
        b = regles.synchroniser_equipes({"Gantz": "PapriKa+", "Reborn": "PRiNTER-PapriKa+", "Kuroko": "Tadatoshi FUJIMAKI", "Solo": "Matsuena"})
        self.assertEqual(b["crees"], ["Manga · PapriKa"])
        p = regles.profils()[0]
        self.assertEqual((p["series"], p["actif"], p["auto"], p["sources_min"]), (["Gantz", "Reborn"], True, True, 1))
        f = next(f for f in regles.formats() if f["nom"] == "Équipe PapriKa")
        self.assertEqual((f["score"], p["scores"][f["id"]]), (0, 1000))

    def test_une_seule_serie_ou_nom_d_auteur_ou_trop_court_ignores(self):
        b = regles.synchroniser_equipes({"A": "Matsuena", "B": "Oku", "C": "Oku", "D": "Jean DUPONT", "E": "Jean DUPONT"})
        self.assertEqual(b, {"crees": [], "mis_a_jour": [], "supprimes": []})

    def test_idempotent_et_mise_a_jour_et_suppression(self):
        regles.synchroniser_equipes({"A": "Paprika", "B": "Paprika"})
        self.assertEqual(regles.synchroniser_equipes({"A": "Paprika", "B": "Paprika"}), {"crees": [], "mis_a_jour": [], "supprimes": []})
        self.assertEqual(regles.synchroniser_equipes({"A": "Paprika", "B": "Paprika", "C": "Paprika"})["mis_a_jour"], ["Manga · Paprika"])
        self.assertEqual(regles.synchroniser_equipes({"A": "Paprika"})["supprimes"], ["Manga · Paprika"])
        self.assertEqual(regles.profils(), [])

    def test_profil_fait_a_la_main_jamais_touche(self):
        regles.enregistrer_profil("", "Manga · Paprika", True, "", "", ["Zzz"], "")
        regles.enregistrer_profil("", "Ma liste", True, "", "", ["A"], "")
        b = regles.synchroniser_equipes({"A": "Paprika", "B": "Paprika", "C": "Paprika"})
        self.assertEqual(b["crees"], [])                       # même nom fait à la main : on s'efface
        regles.supprimer("profil", regles.profils()[0]["id"])
        b = regles.synchroniser_equipes({"A": "Paprika", "B": "Paprika", "C": "Paprika"})
        self.assertEqual(regles.profils()[1]["series"], ["B", "C"])     # « A » est déjà dans un profil à la main

    def test_modifier_un_profil_auto_le_rend_manuel(self):
        regles.synchroniser_equipes({"A": "Paprika", "B": "Paprika"})
        p = regles.profils()[0]
        regles.enregistrer_profil(p["id"], p["nom"], True, "", "", p["series"], "")
        self.assertFalse(regles.profils()[0].get("auto"))
        self.assertEqual(regles.synchroniser_equipes({"A": "Paprika"})["supprimes"], [])


class AutoTelechargement(unittest.TestCase):
    def test_prend_les_tomes_manquants_sans_doublon(self):
        res = [r("Kaf.T01-T05.FR", score=0), r("Kaf.T03.FR", score=0), r("Kaf.T06.FR", score=0), r("Kaf.T07.VOSTFR", badges=())]
        p = auto_telechargement.plan(res, {1, 2}, 7)
        self.assertEqual([(x["titre"], x["tomes"]) for x in p["torrents"]], [("Kaf.T01-T05.FR", [3, 4, 5]), ("Kaf.T06.FR", [6])])
        self.assertEqual(p["manquants"], [7])

    def test_ecarte_refuses_sans_source_non_francais(self):
        res = [r("Kaf.T01.FR", rejet="mot interdit"), r("Kaf.T02.FR", sources=0), r("Kaf.T03", badges=()), r("Kaf.T04.FR")]
        self.assertEqual([x["titre"] for x in auto_telechargement.plan(res, set(), 4)["torrents"]], ["Kaf.T04.FR"])

    def test_le_meilleur_score_d_abord_puis_le_plus_de_tomes(self):
        res = [r("Kaf.T01.FR", score=1000), r("Kaf.T02.FR", score=1000), r("Kaf.T01-T02.FR", score=0)]
        self.assertEqual([x["titre"] for x in auto_telechargement.plan(res, set(), 2)["torrents"]], ["Kaf.T01.FR", "Kaf.T02.FR"])
        res = [r("Kaf.T01.FR", score=5), r("Kaf.T01-T02.FR", score=5)]
        self.assertEqual([x["titre"] for x in auto_telechargement.plan(res, set(), 2)["torrents"]], ["Kaf.T01-T02.FR"])

    def test_integrale_sans_numeros_couvre_tous_les_tomes_attendus(self):
        res = [r("Kaf.[INTEGRALE].FR", badges=("🇫🇷 FR", "Intégrale"))]
        self.assertEqual(auto_telechargement.plan(res, {1}, 5)["torrents"][0]["tomes"], [2, 3, 4, 5])

    def test_serie_complete_rien_a_faire(self):
        self.assertEqual(auto_telechargement.plan([r("Kaf.T01.FR")], {1}, 1), {"torrents": [], "manquants": []})


if __name__ == "__main__":
    unittest.main()
