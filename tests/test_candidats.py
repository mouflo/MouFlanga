"""« Quelle série est-ce ? » : propositions rangées, doute, éditeurs (Ankama), choix gardé."""
import unittest
from unittest import mock

import ankama
import candidats
import reseau
import tomes

AFK = {"id": 141777, "titre": "Jian Yu Yuanzheng: Wu Mang Zhi Ren", "anglais": "Legends of Esperia", "natif": "", "annee": 2021, "statut": "FINISHED",
       "tomes": None, "chapitres": 20, "couverture": "", "lien": "", "format": "MANGA"}


class TestPropositions(unittest.TestCase):
    def _proposer(self, anilist, vega_liste=(), ankama_liste=(), tome_max=5, serie="Arena"):
        with mock.patch.object(tomes, "chercher_anilist", lambda n: anilist), \
                mock.patch.object(candidats.vega, "tomes_de_la_serie", lambda n: list(vega_liste)), \
                mock.patch.object(candidats.ankama, "tomes_de_la_serie", lambda n: list(ankama_liste)):
            return candidats.proposer(serie, tome_max)

    def test_editeur_francais_devant_une_fiche_sans_rapport(self):
        r = self._proposer([AFK], vega_liste=[{"tome": i, "url": f"https://v/{i}"} for i in range(1, 8)])
        self.assertEqual([c["source"] for c in r["propositions"]], ["vega", "anilist"])
        self.assertFalse(r["propositions"][1]["ok"] is True and r["propositions"][1]["score"] > r["propositions"][0]["score"])

    def test_trop_peu_de_chapitres_est_signale(self):
        c = candidats.juger({**AFK, "source": "anilist", "chapitres": 1, "titre": "Sanran"}, "Sanran", 19)
        self.assertFalse(c["ok"])
        self.assertIn("chapitre", c["raison"])

    def test_panne_dite_et_les_autres_sources_continuent(self):
        def panne(n):
            raise reseau.Panne("anilist", "pas de réponse")
        with mock.patch.object(tomes, "chercher_anilist", panne), \
                mock.patch.object(candidats.vega, "tomes_de_la_serie", lambda n: [{"tome": 1, "url": "u"}]), \
                mock.patch.object(candidats.ankama, "tomes_de_la_serie", lambda n: []):
            r = candidats.proposer("Arena", 5)
        self.assertEqual(r["pannes"], ["AniList"])
        self.assertEqual(len(r["propositions"]), 1)


class TestDoute(unittest.TestCase):
    def test_choix_fait_ou_editeur_trouve_pas_de_doute(self):
        self.assertFalse(candidats.y_a_doute("Arena", {}, {"aucune_fiche_anilist": True}, {}))
        self.assertFalse(candidats.y_a_doute("Arena", {}, {}, {"recherches": {"vega": {"tomes": [1, 2]}}}))

    def test_aucune_fiche_donne_doute(self):
        self.assertTrue(candidats.y_a_doute("Arena", {"anilist": None}, {}, {}))

    def test_fiche_sure_pas_de_doute_fiche_douteuse_oui(self):
        sure = {"anilist": 1, "titre": "Radiant", "synonymes": [], "volumes": 19}
        self.assertFalse(candidats.y_a_doute("Radiant", sure, {}, {}, 19))
        afk = {"anilist": 2, "titre": "Jian Yu", "titre_en": "Legends", "synonymes": ["AFK Arena"], "volumes": None, "chapitres": 20}
        self.assertTrue(candidats.y_a_doute("Arena", afk, {}, {}, 5))


class TestAnkama(unittest.TestCase):
    def test_isbn_valide(self):
        self.assertTrue(ankama._isbn_valide("9782359103915"))
        self.assertFalse(ankama._isbn_valide("9782359103916"))

    def test_tomes_de_la_serie_sans_coffret_ni_spinoff(self):
        accueil = '<a href="https://www.ankama-shop.com/fr/724-radiant-tony-valente">R</a>'
        cat = ('<a href="https://www.ankama-shop.com/fr/radiant-tony-valente/334-radiant-tome-1.html">1</a>'
               '<a href="https://www.ankama-shop.com/fr/livres/4714-radiant-tome-20-tony-valente.html">20</a>'
               '<a href="https://www.ankama-shop.com/fr/livres/4713-coffret-radiant-tome-20-tony-valente.html">c</a>'
               '<a href="https://www.ankama-shop.com/fr/radiant-tony-valente/4056-radiant-cyfandir-chronicles-tome-1-x.html">s</a>')

        def faux(url, **kw):
            return reseau.Reponse(200, accueil if url.endswith("/fr/") else (cat if kw.get("params") is None else ""), {}, url, False)
        with mock.patch.object(reseau, "get", faux):
            liste = ankama.tomes_de_la_serie("Radiant")
        self.assertEqual([t["tome"] for t in liste], [1, 20])


if __name__ == "__main__":
    unittest.main()
