"""Scan → officiel : un tome en scantrad est remplacé par un ebook officiel ; jamais un tome qui n'en a pas besoin."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auto_telechargement  # noqa: E402
import suivi  # noqa: E402


def r(titre, score=0, sources=10):
    return {"titre": titre, "score": score, "sources": sources, "badges": ["🇫🇷 FR"], "rejet": "", "lien": "http://x/" + titre, "taille": 1, "indexeur": "I", "profil": ""}


def info(**kw):
    b = {"tomes": set(range(1, 6)), "source": "Mixte", "qualite": "Digital", "equipe": "", "equipe_tomes": {}, "complete": False, "en_cours": False,
         "profil": False, "scores_tomes": {}, "arret": None, "sources_tomes": {"1": "Scantrad", "2": "Scantrad", "3": "Digital", "4": "Digital", "5": "Digital"}}
    b.update(kw)
    return b


class OfficielTest(unittest.TestCase):
    def test_est_officiel(self):
        for t in ("Gachiakuta.T12.FRENCH.CBZ.eBook-NEO.RIP-Club", "Kaf T11 [Digital-1500px] [NEO RIP-Club]", "Kaf T01 Digital", "Kaf eBook officiel", "Kaf.T01.eBook-Paprika"):
            self.assertTrue(suivi.est_officiel(t), t)
        for t in ("Gachiakuta.T01.FRENCH.CBZ.eBook-ebdz", "Kaf.T01.FR.[CBZ]-Dogbanov"):
            self.assertFalse(suivi.est_officiel(t), t)

    def test_scantrad_remplace_par_officiel(self):
        p = suivi.propositions_pour("Kaf", info(), [r("Kaf.T01.FRENCH.CBZ.eBook-NEO.RIP-Club")], [])
        self.assertEqual((p[0]["type"], p[0]["tomes"]), ("meilleur", [1]))

    def test_tome_deja_officiel_ou_torrent_scan_pas_propose(self):
        self.assertEqual(suivi.propositions_pour("Kaf", info(), [r("Kaf.T04.FRENCH.CBZ.eBook-NEO.RIP-Club"), r("Kaf.T01.FRENCH.CBZ.eBook-ebdz")], []), [])

    def test_plan_remplacement_et_nouveau(self):
        res = [r("Kaf.T01.eBook-NEO.RIP-Club"), r("Kaf.T02.eBook-NEO.RIP-Club"), r("Kaf.T06.FR")]
        p = auto_telechargement.plan(res, set(range(1, 6)), None, info())
        self.assertEqual(sorted((x["type"], x["tomes"][0]) for x in p["torrents"]), [("meilleur", 1), ("meilleur", 2), ("nouveau", 6)])

    def test_pack_qui_remplacerait_un_tome_inutile_n_est_pas_pris_comme_remplacement(self):
        res = [r("Kaf.T01-T04.eBook-NEO.RIP-Club")]                      # T3 et T4 sont déjà officiels : on ne remplace pas
        self.assertEqual(auto_telechargement.plan(res, set(range(1, 6)), None, info())["torrents"], [])
        res = [r("Kaf.T01-T06.eBook-NEO.RIP-Club")]                      # apporte T6 : pris, mais sans rien remplacer
        p = auto_telechargement.plan(res, set(range(1, 6)), None, info())
        self.assertEqual([(x["type"], x["tomes"]) for x in p["torrents"]], [("nouveau", [6])])

    def test_sans_info_comportement_inchange(self):
        p = auto_telechargement.plan([r("Kaf.T06.FR")], {1}, None)
        self.assertEqual([(x["type"], x["tomes"]) for x in p["torrents"]], [("nouveau", [6])])


class EditionEnScanSansProvenanceTest(unittest.TestCase):
    """Rave (13/11/2026) : 35 tomes sur 35, ancienne édition en scan dont on ne sait pas d'où vient chaque tome : un profil « Neo Rip Club » doit
    quand même faire proposer les ebooks officiels, même si la série est complète."""

    def rave(self, **kw):
        base = dict(tomes=set(range(1, 9)), source="Scan", complete=True, profil=True, profil_precis=True, arret=1000, sources_tomes={})
        base.update(kw)
        return info(**base)

    def res(self):
        return [r("Rave.The.Goove.Adventure.Tome.0%d.Hiro.Mashima.FR.[CBZ]-NeoRipClub" % n, score=1240) for n in range(1, 9)]

    def test_serie_complete_en_scan_sans_provenance_propose_l_officiel(self):
        p = suivi.propositions_pour("Rave", self.rave(), self.res(), [])
        self.assertEqual(sorted((x["type"], x["tomes"][0]) for x in p), [("meilleur", n) for n in range(1, 9)])

    def test_serie_incomplete_pareil(self):
        p = suivi.propositions_pour("Rave", self.rave(complete=False), self.res(), [])
        self.assertEqual(len(p), 8)

    def test_edition_mixte_ou_digitale_jamais_remplacee_sans_preuve(self):
        for source in ("Mixte", "Digital", ""):
            self.assertEqual(suivi.propositions_pour("Rave", self.rave(source=source), self.res(), []), [], source)

    def test_un_tome_dont_on_connait_la_source_n_est_pas_devine(self):
        info_ = self.rave(sources_tomes={str(n): "Digital" for n in range(1, 9)})
        self.assertEqual(suivi.propositions_pour("Rave", info_, self.res(), []), [])

    def test_un_tome_venu_d_un_torrent_note_par_le_profil_n_est_pas_devine(self):
        info_ = self.rave(scores_tomes={n: 1240 for n in range(1, 9)})
        self.assertEqual(suivi.propositions_pour("Rave", info_, self.res(), []), [])

    def test_profil_general_ou_sans_profil_ne_devine_pas(self):
        # « Manga · Français » (aucune série nommée) ne suffit pas : seule une règle écrite pour la série autorise la devinette
        self.assertEqual(suivi.propositions_pour("Rave", self.rave(profil_precis=False), self.res(), []), [])
        self.assertEqual(suivi.propositions_pour("Rave", self.rave(profil=False, profil_precis=False), self.res(), []), [])

    def test_torrent_non_officiel_pas_propose(self):
        res = [r("Rave.T01.Hiro.Mashima.FR.[CBZ]-Dogbanov", score=500)]
        self.assertEqual(suivi.propositions_pour("Rave", self.rave(), res, []), [])

    def test_serie_complete_ne_recoit_ni_nouveau_ni_serie_entiere(self):
        res = [r("Rave.The.Goove.Adventure.Tome.09.Hiro.Mashima.FR.[CBZ]-NeoRipClub", score=1240)]      # T9 : pas dans la bibliothèque
        self.assertEqual(suivi.propositions_pour("Rave", self.rave(source="Mixte"), res, []), [])
        res = [r("Rave.[INTEGRALE].FR.[CBZ]-Skandery", score=0)]
        res[0]["badges"] = ["🇫🇷 FR", "Digital"]
        self.assertEqual(suivi.propositions_pour("Rave", self.rave(profil=False), res, []), [])

    def test_plan_automatique_remplace_tous_les_tomes_en_scan(self):
        p = auto_telechargement.plan(self.res(), set(range(1, 9)), 8, self.rave())
        self.assertEqual(sorted((x["type"], x["tomes"][0]) for x in p["torrents"]), [("meilleur", n) for n in range(1, 9)])


if __name__ == "__main__":
    unittest.main()
