"""Règles de recherche, version « Sonarr » : conditions des formats, points par profil, scores minimum, refus expliqués, tri."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import regles  # noqa: E402
import torrents  # noqa: E402

GO = 1024 ** 3


def r(titre, taille=GO, sources=10, indexeur="C411", badges=()):
    return {"titre": titre, "taille": taille, "sources": sources, "indexeur": indexeur, "badges": list(badges)}


class FormatsTest(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.ancien = regles.FICHIER
        regles.FICHIER = Path(self.dossier.name) / "regles.json"

    def tearDown(self):
        regles.FICHIER = self.ancien
        self.dossier.cleanup()

    def fmt(self, conds, nom="F", score="10"):
        i = regles.enregistrer_format("", nom, "", score, conds)
        return next(f for f in regles.formats() if f["id"] == i)

    def test_ancien_format_a_termes_devient_une_condition(self):
        regles._ecrire({"profils": [], "formats": [{"id": "a", "nom": "Ancien", "termes": ["SR-71"], "score": 5}]})
        f = regles.formats()[0]
        self.assertEqual(f["conditions"][0]["type"], "titre")
        self.assertTrue(regles.format_correspond(f, r("Kaf SR-71")))

    def test_une_condition_facultative_suffit(self):
        f = self.fmt([{"type": "titre", "valeur": "aaa"}, {"type": "titre", "valeur": "bbb"}])
        self.assertTrue(regles.format_correspond(f, r("x bbb")))
        self.assertFalse(regles.format_correspond(f, r("x ccc")))

    def test_obligatoire_et_inversee(self):
        f = self.fmt([{"type": "titre", "valeur": "FR", "obligatoire": True}, {"type": "titre", "valeur": "VOSTFR", "inverse": True, "obligatoire": True}])
        self.assertTrue(regles.format_correspond(f, r("Kaf FR")))
        self.assertFalse(regles.format_correspond(f, r("Kaf FR VOSTFR")))
        self.assertFalse(regles.format_correspond(f, r("Kaf")))

    def test_regex(self):
        f = self.fmt([{"type": "regex", "valeur": r"\bt\d+-\d+\b"}])
        self.assertTrue(regles.format_correspond(f, r("Kaf T01-20")))
        self.assertFalse(regles.format_correspond(f, r("Kaf T01")))

    def test_regex_invalide_refusee(self):
        with self.assertRaises(ValueError):
            regles.enregistrer_format("", "X", "", "1", [{"type": "regex", "valeur": "(abc"}])

    def test_equipe_indexeur_badge_taille(self):
        self.assertTrue(regles.format_correspond(self.fmt([{"type": "equipe", "valeur": "paprika"}]), r("One.Piece.T101.FR.[CBZ]-TONER-Paprika")))
        self.assertFalse(regles.format_correspond(self.fmt([{"type": "equipe", "valeur": "paprika"}]), r("Kaf FR")))
        self.assertTrue(regles.format_correspond(self.fmt([{"type": "indexeur", "valeur": "c411"}]), r("x", indexeur="C411")))
        self.assertTrue(regles.format_correspond(self.fmt([{"type": "badge", "valeur": "FR"}]), r("x", badges=["🇫🇷 FR"])))
        self.assertTrue(regles.format_correspond(self.fmt([{"type": "taille_max", "valeur": "2"}]), r("x", taille=GO)))
        self.assertFalse(regles.format_correspond(self.fmt([{"type": "taille_min", "valeur": "2"}]), r("x", taille=GO)))
        self.assertFalse(regles.format_correspond(self.fmt([{"type": "taille_max", "valeur": "2"}]), r("x", taille=0)))   # taille inconnue

    def test_format_sans_condition_ne_reconnait_rien(self):
        self.assertFalse(regles.format_correspond(self.fmt([]), r("x")))

    def test_condition_vide_ignoree(self):
        self.assertEqual(self.fmt([{"type": "titre", "valeur": "  "}, {"type": "titre", "valeur": "a"}])["conditions"][0]["valeur"], ["a"])


class ProfilsTest(FormatsTest):
    def profil(self, **kw):
        a = dict(nom="P", actif=True, doit="", ne_doit_pas="", series="", taille=""), kw
        p = {"id_": "", "nom": "P", "actif": True, "doit": "", "ne_doit_pas": "", "series": "", "taille_max_go": ""}
        p.update(kw)
        return regles.enregistrer_profil(**p)

    def test_points_du_profil_remplacent_ceux_du_format(self):
        fid = regles.enregistrer_format("", "VF", "", "10", [{"type": "titre", "valeur": "FR"}])
        self.profil(scores={fid: "200"})
        out = regles.filtrer([r("Kaf FR")], "Kaf")
        self.assertEqual(out[0]["score"], 200)
        self.assertEqual(out[0]["formats"], ["VF"])

    def test_points_par_defaut_sans_profil(self):
        regles.enregistrer_format("", "VF", "", "10", [{"type": "titre", "valeur": "FR"}])
        self.assertEqual(regles.filtrer([r("Kaf FR")], "Kaf")[0]["score"], 10)

    def test_score_minimum_refuse_avec_raison(self):
        fid = regles.enregistrer_format("", "Scan", "", "0", [{"type": "titre", "valeur": "scan"}])
        self.profil(scores={fid: "-50"}, score_min="0")
        self.assertEqual(regles.filtrer([r("Kaf scan")], "Kaf"), [])
        x = regles.filtrer([r("Kaf scan")], "Kaf", avec_rejets=True)[0]
        self.assertIn("score trop bas", x["rejet"])

    def test_sources_minimum(self):
        self.profil(sources_min="3")
        out = regles.filtrer([r("a", sources=1), r("b", sources=5)], "Kaf", avec_rejets=True)
        self.assertEqual({x["titre"]: bool(x["rejet"]) for x in out}, {"a": True, "b": False})

    def test_assez_bon(self):
        fid = regles.enregistrer_format("", "VF", "", "0", [{"type": "titre", "valeur": "FR"}])
        self.profil(scores={fid: "100"}, score_arret="100")
        out = {x["titre"]: x["assez_bon"] for x in regles.filtrer([r("a FR"), r("b")], "Kaf")}
        self.assertEqual(out, {"a FR": True, "b": False})

    def test_un_seul_profil_le_plus_precis(self):
        self.profil(nom="Général", doit="FR")
        self.profil(nom="Kaf", series=["Kaf"], ne_doit_pas="VO")
        self.assertEqual(regles.profil_pour("Kaf 01")["nom"], "Kaf")
        self.assertEqual(regles.profil_pour("One Piece")["nom"], "Général")
        # le profil de Kaf n'exige pas « FR » : le général ne s'y ajoute pas
        self.assertEqual(len(regles.filtrer([r("Kaf 01")], "Kaf")), 1)

    def test_profil_force_ou_aucun(self):
        self.profil(doit="FR")
        self.assertEqual(len(regles.filtrer([r("Kaf")], "Kaf", profil=None)), 1)
        self.assertEqual(len(regles.filtrer([r("Kaf")], "Kaf")), 0)

    def test_suppression_du_format_retire_ses_points(self):
        fid = regles.enregistrer_format("", "VF", "", "0", [{"type": "titre", "valeur": "FR"}])
        self.profil(scores={fid: "100"})
        regles.supprimer("format", fid)
        self.assertEqual(regles.profils()[0]["scores"], {})

    def test_modification_garde_les_points_si_non_fournis(self):
        fid = regles.enregistrer_format("", "VF", "", "0", [{"type": "titre", "valeur": "FR"}])
        pid = self.profil(scores={fid: "100"})
        regles.enregistrer_profil(pid, "P2", True, "", "", "", "")
        self.assertEqual(regles.profils()[0]["scores"], {fid: 100})

    def test_modeles_sans_doublon_et_profil_desactive(self):
        n = regles.ajouter_modeles()
        self.assertGreater(n, 5)
        self.assertEqual(regles.ajouter_modeles(), 0)
        self.assertFalse(regles.profils()[0]["actif"])

    def test_modele_refuse_vostfr_et_garde_la_vf(self):
        regles.ajouter_modeles()
        p = regles.profils()[0]
        regles.enregistrer_profil(p["id"], p["nom"], True, "", "", "", "", scores=None, score_min="0", score_arret="150", sources_min="1")
        out = {x["titre"]: x for x in regles.filtrer([r("Kaf T01 FR CBZ", badges=["🇫🇷 FR"]), r("Kaf T01 VOSTFR")], "Kaf", avec_rejets=True)}
        self.assertEqual(out["Kaf T01 FR CBZ"]["rejet"], "")
        self.assertIn("score trop bas", out["Kaf T01 VOSTFR"]["rejet"])


class TriTest(FormatsTest):
    def lancer(self, resultats, **kw):
        brut = [{"title": x["titre"], "size": x["taille"], "seeders": x["sources"], "indexer": "I", "downloadUrl": "http://p/" + x["titre"]}
                for x in resultats]
        reponse = mock.Mock(status_code=200, json=lambda: brut)
        with mock.patch.object(torrents, "reglages", return_value={"prowlarr": "http://p", "prowlarr_cle": "k"}), \
                mock.patch.object(torrents.requests, "get", return_value=reponse):
            return torrents.chercher("kaf", **kw)

    def test_sans_source_en_dernier_meme_si_francais_et_integrale(self):
        out = self.lancer([r("Kaf Intégrale FR digital", sources=0), r("Kaf T01", sources=12), r("Kaf T02", sources=40)])
        self.assertEqual([x["titre"] for x in out], ["Kaf T02", "Kaf T01", "Kaf Intégrale FR digital"])

    def test_refuses_apres_tout_le_reste(self):
        regles.enregistrer_profil("", "P", True, "", "VOSTFR", "", "")
        out = self.lancer([r("Kaf VOSTFR", sources=99), r("Kaf FR", sources=1), r("Kaf zéro", sources=0)], avec_rejets=True)
        self.assertEqual([x["titre"] for x in out], ["Kaf FR", "Kaf zéro", "Kaf VOSTFR"])
        self.assertEqual([x["titre"] for x in self.lancer([r("Kaf VOSTFR"), r("Kaf FR")])], ["Kaf FR"])


if __name__ == "__main__":
    unittest.main()
