"""Torrents « comme Sonarr » : un seul choix par tome, 🤖 Auto, téléchargements bloqués, tomes en cours, flux des nouveautés."""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auto_telechargement  # noqa: E402
import suivi  # noqa: E402
import torrents  # noqa: E402


def r(titre, score=0, sources=5, badges=("🇫🇷 FR",)):
    return {"titre": titre, "score": score, "sources": sources, "badges": list(badges), "taille": 1, "lien": "http://x/" + titre,
            "page": "", "rejet": "", "profil": "Manga · Français"}


def info(**kw):
    base = {"tomes": {1, 2, 3}, "source": "Digital", "qualite": "Digital", "equipe": "", "equipe_tomes": {}, "complete": False,
            "en_cours": False, "tomes_en_cours": set(), "deja_pris": set(), "profil": True, "scores_tomes": {}, "arret": None}
    base.update(kw)
    return base


class UnSeulChoixParTome(unittest.TestCase):
    def test_plus_de_doublons_le_mieux_note_gagne(self):
        res = [r("Kaf.T04.FR-NoTag", score=260), r("Kaf.T04.FR-Paprika", score=1260), r("Kaf.T04.FR.cbz-NoTag", score=260), r("Kaf.T05.FR", score=100)]
        p = suivi.propositions_pour("Kaf", info(), res, [])
        self.assertEqual([(x["titre"], x["tomes"]) for x in p], [("Kaf.T04.FR-Paprika", [4]), ("Kaf.T05.FR", [5])])

    def test_integrale_a_une_source_passe_apres_les_tomes_bien_partages(self):
        res = [r("Kaf.Integrale.T01-T06.FR", sources=1), r("Kaf.T04.FR", sources=12), r("Kaf.T05.FR", sources=8), r("Kaf.T06.FR", sources=3)]
        p = suivi.propositions_pour("Kaf", info(), res, [])
        self.assertEqual(sorted(x["titre"] for x in p), ["Kaf.T04.FR", "Kaf.T05.FR", "Kaf.T06.FR"])

    def test_le_pack_bien_partage_couvre_tout_d_un_coup(self):
        res = [r("Kaf.T04-T06.FR", sources=9), r("Kaf.T04.FR", sources=12)]
        p = suivi.propositions_pour("Kaf", info(), res, [])
        self.assertEqual([(x["titre"], x["tomes"]) for x in p], [("Kaf.T04-T06.FR", [4, 5, 6])])

    def test_un_tome_seul_prefere_a_une_integrale_pour_un_seul_manquant(self):
        res = [r("Kaf.T01-T04.FR", sources=9), r("Kaf.T04.FR", sources=9)]
        p = suivi.propositions_pour("Kaf", info(), res, [])
        self.assertEqual([x["titre"] for x in p], ["Kaf.T04.FR"])

    def test_pas_un_gros_pack_pour_deux_tomes_si_les_tomes_seuls_existent(self):
        i = info(tomes=set(range(1, 30)) | {32})
        res = [r("Kaf.T01-T32.FR", sources=45), r("Kaf.T30.FR", sources=20), r("Kaf.T31.FR", sources=20)]
        self.assertEqual(sorted(x["titre"] for x in suivi.propositions_pour("Kaf", i, res, [])), ["Kaf.T30.FR", "Kaf.T31.FR"])
        self.assertEqual([x["titre"] for x in suivi.propositions_pour("Kaf", i, res[:2], [])], ["Kaf.T30.FR", "Kaf.T01-T32.FR"])

    def test_tomes_en_cours_et_torrents_deja_pris_ecartes(self):
        res = [r("Kaf.T04.FR"), r("Kaf.T05.FR"), r("Kaf.T06.FR")]
        p = suivi.propositions_pour("Kaf", info(tomes_en_cours={4}, deja_pris={"Kaf.T05.FR"}), res, [])
        self.assertEqual([x["titre"] for x in p], ["Kaf.T06.FR"])

    def test_integrale_en_cours_bloque_toute_la_serie(self):
        self.assertEqual(suivi.propositions_pour("Kaf", info(en_cours=True), [r("Kaf.T04.FR")], []), [])

    def test_dedoublonner_les_anciennes_propositions(self):
        props = [{"titre": "a", "tomes": [20], "score": 100, "statut": "attente"}, {"titre": "b", "tomes": [20], "score": 300, "statut": "attente"},
                 {"titre": "c", "tomes": [20, 21], "score": 50, "statut": "attente"}, {"titre": "d", "tomes": [20], "statut": "telecharge"}]
        self.assertEqual(suivi.dedoublonner(props), 1)
        self.assertEqual([p["statut"] for p in props], ["ignore", "attente", "attente", "telecharge"])

    def test_plan_du_bouton_robot_meme_ordre(self):
        res = [r("Kaf.Integrale.T01-T06.FR", sources=1), r("Kaf.T04.FR", sources=12), r("Kaf.T05.FR", sources=8), r("Kaf.T06.FR", sources=3)]
        p = auto_telechargement.plan(res, {1, 2, 3}, 6, info())
        self.assertEqual(sorted(x["titre"] for x in p["torrents"]), ["Kaf.T04.FR", "Kaf.T05.FR", "Kaf.T06.FR"])


class Verification(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ancien, self.hook = suivi._ETAT["fichier"], suivi.AUTRES_SERIES
        suivi._ETAT["fichier"] = Path(self.tmp.name) / "suivies.json"
        suivi.AUTRES_SERIES = lambda nom: []
        suivi.ajouter("Kaf")
        self.lances = []

    def tearDown(self):
        suivi._ETAT["fichier"], suivi.AUTRES_SERIES = self.ancien, self.hook
        self.tmp.cleanup()

    def lancer(self, lien, titre, nom, remplacer, page=""):
        self.lances.append((titre, remplacer))

    def verifier(self, res, **kw):
        return suivi.verifier("Kaf", lambda q: [dict(x) for x in res], lambda n: info(**kw), self.lancer)

    def test_sans_auto_rien_ne_part_et_pas_de_doublon_au_passage_suivant(self):
        nouv = self.verifier([r("Kaf.T04.FR"), r("Kaf.T04.FR-bis")])
        self.assertEqual(([p["titre"] for p in nouv], self.lances), (["Kaf.T04.FR"], []))
        self.assertEqual(self.verifier([r("Kaf.T04.FR"), r("Kaf.T04.FR-bis")]), [])
        props = suivi.lire()["series"]["Kaf"]["propositions"]
        self.assertEqual([(p["titre"], p["statut"]) for p in props], [("Kaf.T04.FR", "attente")])
        self.assertNotIn("lien", props[0])                       # le lien de Prowlarr (sa clé) n'est jamais gardé

    def test_un_meilleur_torrent_remplace_la_proposition_en_attente(self):
        self.verifier([r("Kaf.T04.FR-NoTag", score=260)])
        nouv = self.verifier([r("Kaf.T04.FR-NoTag", score=260), r("Kaf.T04.FR-Paprika", score=1260)])
        self.assertEqual([p["titre"] for p in nouv], ["Kaf.T04.FR-Paprika"])
        etat = {p["titre"]: p["statut"] for p in suivi.lire()["series"]["Kaf"]["propositions"]}
        self.assertEqual(etat, {"Kaf.T04.FR-NoTag": "ignore", "Kaf.T04.FR-Paprika": "attente"})

    def test_auto_lance_les_tomes_manquants_sans_remplacer(self):
        self.verifier([r("Kaf.T04.FR")])                         # proposition gardée avant l'activation du mode 🤖
        d = suivi.lire(); d["series"]["Kaf"]["auto"] = True; suivi.ecrire(d)
        nouv = self.verifier([r("Kaf.T04.FR"), r("Kaf.T05.FR"), r("Kaf.T06.FR", sources=0)])
        self.assertEqual(sorted(self.lances), [("Kaf.T04.FR", False), ("Kaf.T05.FR", False)])
        self.assertTrue(all(p.get("auto") for p in nouv if p["titre"] != "Kaf.T06.FR"))
        etat = {p["titre"]: p["statut"] for p in suivi.lire()["series"]["Kaf"]["propositions"]}
        self.assertEqual(etat, {"Kaf.T04.FR": "telecharge", "Kaf.T05.FR": "telecharge", "Kaf.T06.FR": "attente"})
        self.assertIn("📥", suivi.message("Kaf", nouv))

    def test_plafond_par_jour(self):
        d = suivi.lire(); d["series"]["Kaf"]["auto"] = True
        d["auto_jour"] = {"date": datetime.now().strftime("%Y-%m-%d"), "n": suivi.AUTO_MAX_JOUR - 1}; suivi.ecrire(d)
        self.verifier([r("Kaf.T04.FR"), r("Kaf.T05.FR")])
        self.assertEqual(len(self.lances), 1)
        self.assertEqual(suivi.lire()["auto_jour"]["n"], suivi.AUTO_MAX_JOUR)


class Flux(unittest.TestCase):
    def test_series_du_flux(self):
        series = {"One Piece": {"surveiller": True, "titres": ["One Piece"], "propositions": [{"titre": "One.Piece.T113.FR"}]},
                  "Dandadan": {"surveiller": False, "titres": ["Dandadan"]}}
        res = [{"titre": "One.Piece.T114.(ODA).2026.FR.[CBR]-NoFace696"}, {"titre": "One.Piece.T113.FR"},
               {"titre": "Dandadan.T24.FR"}, {"titre": "Journal.26.Oct.2026.Pdf"}, {"titre": "One.Piece.T115.FR"}]
        self.assertEqual(suivi.series_du_flux(res, series, {"One.Piece.T115.FR"}),
                         {"One Piece": ["One.Piece.T114.(ODA).2026.FR.[CBR]-NoFace696"]})


class FauxQbit:
    def __init__(self, infos): self.infos, self.appels = infos, []
    def info(self, **p): return self.infos
    def appel(self, chemin, **data): self.appels.append((chemin, data))


class Bloques(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ancien = dict(torrents._ETAT)
        torrents._ETAT["fichier"] = Path(self.tmp.name) / "torrents.json"
        self.rates = []
        torrents._ETAT["apres_rate"] = self.rates.extend

    def tearDown(self):
        torrents._ETAT.clear(); torrents._ETAT.update(self.ancien)
        self.tmp.cleanup()

    def job(self, heures, **kw):
        debut = (datetime.now() - timedelta(hours=heures)).strftime("%Y-%m-%d %H:%M")
        torrents._ecrire([{"id": "j1", "titre": "Crows Integrale T01-26 [Scantrad][FR]", "serie": "Crows", "etat": "telechargement", "debut": debut, **kw}])

    def test_bloque_depuis_trop_longtemps_retire_et_rate(self):
        self.job(30)
        q = FauxQbit([{"hash": "h1", "progress": 0, "state": "forcedDL", "num_seeds": 0, "category": "mouflanga"}])
        torrents.traiter(q, torrents._lire(), None, lambda m: None, None)
        self.assertEqual(q.appels, [("torrents/delete", {"hashes": "h1", "deleteFiles": "true"})])
        j = torrents._lire()[0]
        self.assertEqual(j["etat"], "rate")
        self.assertIn("aucune source", j["message"])
        self.assertEqual([(x["serie"], x["chercher"]) for x in self.rates], [("Crows", True)])
        self.assertIn("Crows Integrale T01-26 [Scantrad][FR]", torrents.deja_pris())
        self.assertEqual(torrents.en_cours_de("Crows"), [])

    def test_recent_ou_en_pause_ou_qui_avance_reste(self):
        for etat, progres, heures, avance in (("stalledDL", 0, 3, None), ("pausedDL", 0, 300, None), ("downloading", 0.4, 300, 0.2)):
            self.job(heures, **({"avance": avance} if avance is not None else {}))
            q = FauxQbit([{"hash": "h1", "progress": progres, "state": etat, "num_seeds": 0, "category": "mouflanga"}])
            torrents.traiter(q, torrents._lire(), None, lambda m: None, None)
            self.assertEqual((etat, q.appels, torrents._lire()[0]["etat"]), (etat, [], "telechargement"))

    def test_jamais_un_torrent_d_une_autre_categorie(self):
        self.job(30)
        q = FauxQbit([{"hash": "h1", "progress": 0, "state": "stalledDL", "num_seeds": 0, "category": "sonarr"}])
        torrents.traiter(q, torrents._lire(), None, lambda m: None, None)
        self.assertEqual(q.appels, [])
        self.assertEqual(torrents._lire()[0]["etat"], "rate")

    def test_supprime_a_la_main_rate_sans_nouvelle_recherche(self):
        self.job(1)
        torrents.traiter(FauxQbit([]), torrents._lire(), None, lambda m: None, None)
        self.assertEqual(torrents._lire()[0]["etat"], "rate")
        self.assertEqual([x["chercher"] for x in self.rates], [False])


if __name__ == "__main__":
    unittest.main()
