"""Liens de téléchargement des torrents : celui de Prowlarr contient sa clé API, il ne part jamais vers le navigateur."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import torrents  # noqa: E402

PROWLARR = "http://192.168.1.133:9696/10/download?apikey=CLE-PROWLARR-SECRETE&link=abc&file=Wind.Breaker.T07"
RESULTATS = [{"titre": "Wind.Breaker.T07.FR.CBZ", "taille": 1, "sources": 9, "indexeur": "C411", "date": "2026-07-10", "badges": ["🇫🇷 FR"],
              "page": "https://c411.org/torrents/" + "a" * 40, "lien": PROWLARR},
             {"titre": "Magnet", "taille": 1, "sources": 1, "indexeur": "X", "date": "", "badges": [], "page": "", "lien": "magnet:?xt=urn:btih:abc"}]


class PublierTest(unittest.TestCase):
    def setUp(self):
        torrents._LIENS.clear()

    def test_le_lien_de_prowlarr_ne_sort_pas(self):
        pub = torrents.publier(RESULTATS)
        self.assertNotIn("lien", pub[0])
        self.assertNotIn("SECRETE", str(pub))
        self.assertEqual(pub[1]["lien"], "magnet:?xt=urn:btih:abc")                 # un magnet ne contient aucune clé
        self.assertEqual(pub[0]["page"], RESULTATS[0]["page"])
        self.assertEqual(RESULTATS[0]["lien"], PROWLARR)                            # la liste d'origine n'est pas modifiée

    def test_le_numero_retrouve_le_lien_pendant_deux_heures(self):
        pub = torrents.publier(RESULTATS)
        self.assertEqual(torrents.lien_de(pub[0]["id"]), PROWLARR)
        self.assertEqual(torrents.lien_de("inconnu"), "")
        self.assertEqual(torrents.lien_de(None), "")
        with mock.patch.object(torrents.time, "time", return_value=torrents.time.time() + torrents._LIENS_DUREE + 5):
            self.assertEqual(torrents.lien_de(pub[0]["id"]), "")
            torrents.publier([])                                                    # le ménage se fait à la publication suivante
        self.assertEqual(torrents._LIENS, {})

    def test_memoire_limitee(self):
        with mock.patch.object(torrents, "_LIENS_MAX", 3):
            for i in range(6):
                torrents.publier([{"titre": str(i), "lien": f"http://p/{i}?apikey=K"}])
        self.assertEqual(len(torrents._LIENS), 3)


class RoutesTest(unittest.TestCase):
    def setUp(self):
        import app as m
        self.m = m
        torrents._LIENS.clear()

    def poster(self, corps):
        with self.m.app.test_request_context("/api/torrents", method="POST", json=corps), \
                mock.patch.object(torrents, "lancer", return_value={}) as lancer, mock.patch.object(self.m, "_serie_proche", return_value=""):
            rep = self.m.api_torrents()
        return rep, lancer

    def test_la_recherche_ne_renvoie_pas_le_lien(self):
        with self.m.app.test_request_context("/api/torrents/chercher?q=wind+breaker"), mock.patch.object(torrents, "configure", return_value=True), \
                mock.patch.object(torrents, "chercher", return_value=[dict(r) for r in RESULTATS]):
            d = self.m.api_torrents_chercher().get_json()
        self.assertNotIn("SECRETE", str(d))
        self.assertTrue(all(r["id"] for r in d["resultats"]))

    def test_telechargement_par_numero_avec_la_page_du_tracker(self):
        pub = torrents.publier(RESULTATS)
        rep, lancer = self.poster({"resultat": pub[0]["id"], "titre": "Wind.Breaker.T07.FR.CBZ", "serie": "Wind Breaker", "page": RESULTATS[0]["page"]})
        self.assertTrue(rep.get_json()["ok"])
        lancer.assert_called_once_with(PROWLARR, "Wind.Breaker.T07.FR.CBZ", "Wind Breaker", None, RESULTATS[0]["page"])

    def test_un_lien_http_envoye_par_le_navigateur_est_refuse(self):
        rep, lancer = self.poster({"lien": "http://192.168.1.133:9696/10/download?apikey=AUTRE", "titre": "t", "serie": "S"})
        self.assertEqual(rep[1], 400)
        self.assertIn("relance la recherche", rep[0].get_json()["error"])
        lancer.assert_not_called()

    def test_un_numero_inconnu_est_refuse_et_un_magnet_accepte(self):
        rep, lancer = self.poster({"resultat": "inconnu", "titre": "t", "serie": "S"})
        self.assertEqual(rep[1], 400)
        lancer.assert_not_called()
        rep, lancer = self.poster({"lien": "magnet:?xt=urn:btih:abc", "titre": "t", "serie": "S"})
        self.assertTrue(rep.get_json()["ok"])
        self.assertEqual(lancer.call_args[0][0], "magnet:?xt=urn:btih:abc")

    def test_il_faut_un_nom_de_serie(self):
        pub = torrents.publier(RESULTATS)
        rep, lancer = self.poster({"resultat": pub[0]["id"], "titre": "t", "serie": ""})
        self.assertEqual(rep[1], 400)
        lancer.assert_not_called()

    def test_la_page_du_tracker_suit_le_telechargement(self):
        with mock.patch.object(torrents, "Qbit"), mock.patch.object(torrents, "_forcer_demarrage"), mock.patch.object(torrents, "_lire", return_value=[]), \
                mock.patch.object(torrents, "_ecrire") as ecrire, mock.patch.object(torrents, "reglages", return_value={"nok": "/x"}):
            j = torrents.lancer("magnet:?x", "T", "S", None, "https://c411.org/torrents/" + "a" * 40)
            sans = torrents.lancer("magnet:?x", "T", "S", None, "http://pas-https.example/x")
        self.assertEqual(j["page"], "https://c411.org/torrents/" + "a" * 40)
        self.assertNotIn("page", sans)
        self.assertTrue(ecrire.called)


if __name__ == "__main__":
    unittest.main()
