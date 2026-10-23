"""Surveillance des séries suivies : on ne propose que des tomes manquants, ou une meilleure qualité d'après le profil."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import suivi  # noqa: E402


def r(titre, score=0, sources=5, badges=("🇫🇷 FR",)):
    return {"titre": titre, "score": score, "sources": sources, "badges": list(badges), "taille": 1, "lien": "http://x/" + titre, "page": ""}


def info(**kw):
    base = {"tomes": {1, 2, 3}, "source": "Digital", "qualite": "Digital", "equipe": "", "equipe_tomes": {}, "complete": False, "en_cours": False,
            "profil": False, "scores_tomes": {}, "arret": None}
    base.update(kw)
    return base


class PropositionsTest(unittest.TestCase):
    def test_nouveau_ne_garde_que_les_tomes_manquants(self):
        p = suivi.propositions_pour("Kaf", info(), [r("Kaf.T01-T05.FR")], [])
        self.assertEqual((p[0]["type"], p[0]["tomes"]), ("nouveau", [4, 5]))

    def test_rien_si_tout_est_deja_la_sans_profil(self):
        self.assertEqual(suivi.propositions_pour("Kaf", info(), [r("Kaf.T01-T03.FR", badges=("🇫🇷 FR",))], []), [])

    def test_avec_profil_tome_present_propose_seulement_si_mieux_note(self):
        i = info(profil=True, scores_tomes={1: 100, 2: 100, 3: 1100}, arret=1000)
        p = suivi.propositions_pour("Kaf", i, [r("Kaf.T01-T03.FR", score=1100)], [])
        self.assertEqual((p[0]["type"], p[0]["tomes"], p[0]["score"]), ("meilleur", [1, 2], 1100))        # T3 est déjà « assez bon »

    def test_avec_profil_pas_de_proposition_si_pas_mieux(self):
        i = info(profil=True, scores_tomes={1: 500, 2: 500, 3: 500}, arret=1000)
        self.assertEqual(suivi.propositions_pour("Kaf", i, [r("Kaf.T01-T03.FR", score=500), r("Kaf.T02.FR", score=100)], []), [])

    def test_provenance_inconnue_jamais_proposee_comme_amelioration(self):
        i = info(profil=True, scores_tomes={}, arret=None)
        self.assertEqual(suivi.propositions_pour("Kaf", i, [r("Kaf.T01-T03.FR", score=5000)], []), [])

    def test_sans_profil_ancien_comportement_scan_vers_digital(self):
        i = info(source="Scan", qualite="Digital")
        p = suivi.propositions_pour("Kaf", i, [r("Kaf.T01-T03.FR.Digital", badges=("🇫🇷 FR", "Digital"))], [])
        self.assertEqual(p[0]["type"], "meilleur")


class PurgeTest(unittest.TestCase):
    def test_nouveau_devenu_inutile(self):
        props = [{"type": "nouveau", "tomes": [4, 5], "statut": "attente"}, {"type": "nouveau", "tomes": [4, 9], "statut": "attente"}]
        self.assertEqual(suivi.purger(props, info(tomes={1, 2, 3, 4, 5})), 1)
        self.assertEqual([p["statut"] for p in props], ["ignore", "attente"])

    def test_meilleur_devenu_inutile_et_deja_traitees_intactes(self):
        props = [{"type": "meilleur", "tomes": [1], "score": 1000, "statut": "attente"}, {"type": "nouveau", "tomes": [1], "statut": "telecharge"}]
        suivi.purger(props, info(profil=True, scores_tomes={1: 1000}))
        self.assertEqual([p["statut"] for p in props], ["ignore", "telecharge"])

    def test_plage(self):
        self.assertEqual(suivi.plage([5, 1, 2, 3, 7, 8, 12]), "T1–T3, T5, T7–T8, T12")


if __name__ == "__main__":
    unittest.main()
