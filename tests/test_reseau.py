"""reseau.py : un échec n'est jamais pris pour « rien trouvé » (Panne), les pauses et les quotas sont respectés."""
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reseau  # noqa: E402


class Rep:
    def __init__(self, statut=200, corps=None, texte=None, entetes=None):
        self.status_code = statut
        self.text = texte if texte is not None else json.dumps(corps if corps is not None else {})
        self.headers = entetes or {}

    def json(self):
        return json.loads(self.text)


class Scenario:
    """Réponses jouées dans l'ordre ; une exception est levée telle quelle."""

    def __init__(self, *reponses):
        self.reponses, self.appels = list(reponses), []

    def __call__(self, url, **kw):
        self.appels.append((url, kw))
        r = self.reponses.pop(0) if len(self.reponses) > 1 else self.reponses[0]
        if isinstance(r, Exception):
            raise r
        return r


class ReseauTest(unittest.TestCase):
    def setUp(self):
        reseau.oublier_tout()
        self.fichier = reseau.FICHIER_ETAT
        reseau.FICHIER_ETAT = None

    def tearDown(self):
        reseau.FICHIER_ETAT = self.fichier
        reseau.oublier_tout()

    def jouer(self, *reponses, methode="get"):
        sc = Scenario(*reponses)
        return mock.patch.object(reseau.SESSION, methode, side_effect=sc), sc

    def test_reponse_normale_et_404_rendus_tels_quels(self):
        p, sc = self.jouer(Rep(200, {"a": 1}))
        with p:
            self.assertEqual(reseau.get("https://fr.wikipedia.org/w/api.php").json(), {"a": 1})
        p, sc = self.jouer(Rep(404, {"erreur": "inconnu"}))
        with p:
            r = reseau.get("https://api.mangadex.org/manga/x")
            self.assertEqual(r.statut, 404)

    def test_erreur_serveur_puis_succes(self):
        p, sc = self.jouer(Rep(503), Rep(200, {"ok": True}))
        with p:
            self.assertEqual(reseau.get("https://api.mangadex.org/manga").json(), {"ok": True})
        self.assertEqual(len(sc.appels), 2)

    def test_toujours_en_erreur_leve_panne_jamais_un_resultat_vide(self):
        p, sc = self.jouer(Rep(502))
        with p:
            with self.assertRaises(reseau.Panne) as c:
                reseau.get("https://api.mangadex.org/manga")
        self.assertEqual(len(sc.appels), 3)
        self.assertEqual(c.exception.service, "MangaDex")

    def test_pas_de_reseau_leve_panne(self):
        p, sc = self.jouer(requests.ConnectionError("coupé"))
        with p:
            with self.assertRaises(reseau.Panne):
                reseau.get("https://api.mangadex.org/manga")

    def test_page_d_erreur_a_la_place_du_json_est_une_panne(self):
        p, sc = self.jouer(Rep(200, texte="<html>Just a moment...</html>"))
        with p:
            with self.assertRaises(reseau.Panne) as c:
                reseau.get("https://graphql.anilist.co")
            self.assertIn("illisible", c.exception.raison)

    def test_texte_attendu_n_est_pas_lu_comme_json(self):
        p, sc = self.jouer(Rep(200, texte="<xml/>"))
        with p:
            self.assertEqual(reseau.get("https://catalogue.bnf.fr/api/SRU", attendu="xml").texte, "<xml/>")

    def test_trop_de_demandes_longue_pause_gardee_puis_aucun_appel(self):
        p, sc = self.jouer(Rep(429, entetes={"Retry-After": "120"}))
        with p:
            with self.assertRaises(reseau.Panne) as c:
                reseau.get("https://graphql.anilist.co")
            self.assertGreater(c.exception.reprise, time.time() + 100)
            n = len(sc.appels)
            with self.assertRaises(reseau.Panne):
                reseau.get("https://graphql.anilist.co")
            self.assertEqual(len(sc.appels), n)                  # en pause : aucune requête
        self.assertGreater(reseau.en_pause("anilist"), 0)

    def test_courte_pause_demandee_on_patiente_et_on_reessaie(self):
        p, sc = self.jouer(Rep(429, entetes={"Retry-After": "3"}), Rep(200, {"ok": 1}))
        with p:
            self.assertEqual(reseau.get("https://api.mangaupdates.com/v1/x").json(), {"ok": 1})

    def test_trois_pannes_de_suite_mettent_le_service_en_pause(self):
        p, sc = self.jouer(Rep(500))
        with p:
            for _ in range(3):
                with self.assertRaises(reseau.Panne):
                    reseau.get("https://api.mangadex.org/manga", essais=1)
            n = len(sc.appels)
            with self.assertRaises(reseau.Panne):
                reseau.get("https://api.mangadex.org/manga", essais=1)
        self.assertEqual(len(sc.appels), n)

    def test_google_quota_du_jour(self):
        corps = {"error": {"code": 429, "message": "Quota exceeded for quota metric 'Queries' and limit 'Queries per day'"}}
        p, sc = self.jouer(Rep(429, corps))
        with p:
            with self.assertRaises(reseau.Quota) as c:
                reseau.get("https://www.googleapis.com/books/v1/volumes", params={"q": "x"})
            self.assertGreater(c.exception.reprise, time.time())
            self.assertLessEqual(c.exception.reprise, time.time() + 86400)
            with self.assertRaises(reseau.Quota):
                reseau.get("https://www.googleapis.com/books/v1/volumes", params={"q": "x"})
        self.assertEqual(len(sc.appels), 1)

    def test_google_reserve_pour_les_demandes_a_la_main(self):
        p, sc = self.jouer(Rep(200, {"items": []}))
        with p:
            s = reseau.SERVICES["google"]
            s.jour, s.n_jour = reseau._jour_pacifique(), 900
            reseau.get("https://www.googleapis.com/books/v1/volumes", reserve=50)        # 900 < 950 : permis
            s.n_jour = 960
            with self.assertRaises(reseau.Quota):
                reseau.get("https://www.googleapis.com/books/v1/volumes", reserve=reseau.RESERVE_FOND)
            reseau.get("https://www.googleapis.com/books/v1/volumes")                    # à la main : permis
        self.assertEqual(reseau.reste_du_jour("google"), 1000 - 961)

    def test_wikipedia_maxlag_est_une_panne(self):
        p, sc = self.jouer(Rep(200, {"error": {"code": "maxlag", "info": "waiting"}}))
        with p:
            with self.assertRaises(reseau.Panne):
                reseau.get("https://fr.wikipedia.org/w/api.php")

    def test_wikipedia_page_inexistante_est_rendue_a_l_appelant(self):
        p, sc = self.jouer(Rep(200, {"error": {"code": "missingtitle"}}))
        with p:
            self.assertEqual(reseau.get("https://fr.wikipedia.org/w/api.php").json()["error"]["code"], "missingtitle")

    def test_anilist_erreur_sans_donnees_panne_mais_fiche_inconnue_none(self):
        p, sc = self.jouer(Rep(200, {"errors": [{"message": "Too many", "status": 500}], "data": None}), methode="post")
        with p:
            with self.assertRaises(reseau.Panne):
                reseau.anilist("query{}")
        reseau.oublier_tout()
        p, sc = self.jouer(Rep(404, {"errors": [{"message": "Not Found.", "status": 404}], "data": {"Media": None}}), methode="post")
        with p:
            self.assertIsNone(reseau.anilist("query{}"))

    def test_memo(self):
        p, sc = self.jouer(Rep(200, {"n": 1}))
        reseau.MEMO_ACTIF = True
        self.addCleanup(setattr, reseau, "MEMO_ACTIF", False)
        with p:
            a = reseau.get("https://fr.wikipedia.org/w/api.php", params={"p": 1}, memo=60)
            b = reseau.get("https://fr.wikipedia.org/w/api.php", params={"p": 1}, memo=60)
            self.assertIs(a, b)
            reseau.get("https://fr.wikipedia.org/w/api.php", params={"p": 2}, memo=60)
        self.assertEqual(len(sc.appels), 2)

    def test_pause_gardee_dans_le_fichier_et_relue(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            reseau.FICHIER_ETAT = Path(d) / "reseau.json"
            reseau.poser_pause("google", time.time() + 3000, "quota du jour")
            reseau.SERVICES["google"].pause_jusqua = 0.0
            reseau._charger_etat()
            self.assertGreater(reseau.en_pause("google"), 0)

    def test_hote_inconnu_service_generique(self):
        self.assertEqual(reseau.service_de("https://onepiece.fandom.com/fr/api.php").nom, "web")
        self.assertEqual(reseau.service_de("https://catalogue.bnf.fr/api/SRU").nom, "bnf")


if __name__ == "__main__":
    unittest.main()
