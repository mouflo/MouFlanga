"""Série suivie encore sans fichier : identifiée quand même (synopsis, noms français), synopsis du tracker en dernier recours, route de lecture."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lecture_pages  # noqa: E402
import reseau  # noqa: E402
import suivi  # noqa: E402
from identification import Bilan  # noqa: E402
from test_page_tracker import HASH  # noqa: E402

PAGE = f"https://c411.org/torrents/{HASH}"


class SerieSuivieVideTest(unittest.TestCase):
    def setUp(self):
        import app as m
        self.m = m
        self.tmp = Path(tempfile.mkdtemp())
        self.sauve = (m.MANGA_DIR, m.PROGRESS_FILE, suivi._ETAT["fichier"])
        m.MANGA_DIR = self.tmp / "mangas"
        m.MANGA_DIR.mkdir()
        m.PROGRESS_FILE = self.tmp / "progress.json"
        suivi._ETAT["fichier"] = self.tmp / "suivies.json"
        suivi.ajouter("WIND BREAKER", {"titre": "Wind Breaker", "anilist": 135083, "annee": 2021})
        reseau.oublier_tout()

    def tearDown(self):
        self.m.MANGA_DIR, self.m.PROGRESS_FILE, suivi._ETAT["fichier"] = self.sauve

    def fiche(self, nom="WIND BREAKER"):
        with self.m.app.test_request_context(f"/api/series?id={nom}"):
            return self.m.api_series().get_json()

    # -- l'identification connaît la fiche choisie en ajoutant la série
    def test_la_fiche_choisie_en_ajoutant_la_serie_sert_a_l_identifier(self):
        self.assertEqual(self.m._anilist_choisi("WIND BREAKER"), 135083)
        self.assertIsNone(self.m._anilist_choisi("Inconnue"))
        suivi.ajouter("Sans fiche", {"titre": "Sans fiche"})
        self.assertIsNone(self.m._anilist_choisi("Sans fiche"))

    def test_une_fiche_choisie_a_la_main_passe_devant(self):
        import edition
        (self.m.MANGA_DIR / "WIND BREAKER").mkdir()
        edition.ecrire(self.m.MANGA_DIR / "WIND BREAKER", {"anilist_choisi": 99, "fichiers_relus": True})
        self.assertEqual(self.m._anilist_choisi("WIND BREAKER"), 99)

    def test_les_series_suivies_vides_sont_preparees_comme_les_autres(self):
        self.assertIn("WIND BREAKER", self.m._series_preparables())
        a = self.m._signature_serie("WIND BREAKER")
        suivi.ajouter("WIND BREAKER", {"anilist": 111})
        self.assertNotEqual(a, self.m._signature_serie("WIND BREAKER"))            # une autre fiche choisie : la série est refaite

    def test_le_contexte_d_identification_d_une_serie_sans_fichier(self):
        ctx = self.m._contexte_identification("WIND BREAKER")
        self.assertEqual(ctx["tomes"], set())
        self.assertFalse(ctx["edition_differente"])
        self.assertEqual(self.m._tomes_de("WIND BREAKER"), set())

    def test_identification_reelle_d_une_serie_suivie_vide_sans_internet(self):
        """Les étapes statut et fiche d'une série sans fichier tournent jusqu'au bout (faux Internet) et notent leur état."""
        import tomes
        from faux_internet import FauxInternet
        suivi.ajouter("Akame ga Kill !", {"titre": "Akame ga Kill !", "anilist": 55132})
        faux = FauxInternet()
        with faux.installer(), mock.patch.object(tomes, "SERIES_EXISTANTES", lambda: ["Akame ga Kill !"]):
            reprise = self.m._preparer_serie_suivie("Akame ga Kill !", lambda t: None)
        garde = tomes._charger("Akame ga Kill !")
        self.assertEqual(garde["statut_officiel"]["anilist"], 55132)                  # la fiche choisie à l'ajout sert d'identité
        self.assertEqual(sorted(garde["recherches"]), ["fiche", "statut"])
        self.assertEqual(garde["recherches"]["statut"]["etat"], "ok")
        self.assertIn(garde["recherches"]["fiche"]["etat"], ("ok", "partiel", "deja"))
        self.assertTrue(reprise is None or reprise > 0)

    def test_preparation_d_une_serie_suivie_vide(self):
        etapes = []

        def faux(nom, **kw):
            etapes.append((nom, kw.get("etapes")))
            return {"statut": Bilan("ok", "en cours", None), "fiche": Bilan("partiel", "x", 1234.0)}
        avec = []
        with mock.patch.object(self.m.identification, "identifier", side_effect=faux):
            reprise = self.m._preparer_serie("WIND BREAKER", avec.append)
        self.assertEqual(etapes, [("WIND BREAKER", ("statut", "fiche"))])
        self.assertEqual(reprise, 1234.0)                                         # l'étape qui attend un service sera reprise
        self.assertTrue(avec)
        with mock.patch.object(self.m.identification, "identifier") as ident:
            self.assertIsNone(self.m._preparer_serie("Retirée", lambda t: None))      # plus suivie : rien à faire
        ident.assert_not_called()

    # -- le synopsis de la fiche
    def test_synopsis_du_tracker_faute_d_un_autre(self):
        self.assertEqual(self.fiche()["resume"], "")
        suivi.noter_tracker("WIND BREAKER", {"synopsis": "Sakura arrive au lycée Furin et rêve d'en devenir le plus fort."}, PAGE, "C411")
        d = self.fiche()
        self.assertEqual(d["resume"], "Sakura arrive au lycée Furin et rêve d'en devenir le plus fort.")
        self.assertEqual((d["resume_langue"], d["resume_source"]), ("fr", "présentation du torrent sur C411"))

    def test_un_resume_officiel_en_francais_passe_devant_celui_du_tracker(self):
        import tomes
        suivi.noter_tracker("WIND BREAKER", {"synopsis": "Texte du tracker"}, PAGE, "C411")
        tomes.modifier("WIND BREAKER", lambda c: c.__setitem__("statut_officiel", {"anilist": 135083, "titre": "Wind Breaker", "resume": "Résumé officiel",
                                                                                   "resume_langue": "fr", "resume_source": "MangaDex"}))
        d = self.fiche()
        self.assertEqual((d["resume"], d["resume_source"]), ("Résumé officiel", ""))

    def test_un_resume_ecrit_a_la_main_passe_devant_tout(self):
        suivi.noter_tracker("WIND BREAKER", {"synopsis": "Texte du tracker"}, PAGE, "C411")
        with mock.patch.object(self.m, "_read_json", side_effect=lambda f, d: {"WIND BREAKER": "Écrit par moi"} if f == self.m.RESUMES else d):
            d = self.fiche()                                      # le fichier des résumés à la main est simulé : jamais le vrai
        self.assertEqual((d["resume"], d["resume_langue"], d["resume_source"]), ("Écrit par moi", "perso", ""))

    def test_la_fiche_n_envoie_aucun_lien_de_telechargement(self):
        d = suivi.lire()
        d["series"]["WIND BREAKER"]["propositions"] = [{"id": "a1", "titre": "t", "page": PAGE, "statut": "attente", "tomes": [1], "badges": [],
                                                        "lien": "http://p/10/download?apikey=CLE-SECRETE"}]
        suivi.ecrire(d)
        self.assertNotIn("CLE-SECRETE", str(self.fiche()))
        with self.m.app.test_request_context("/api/suivies"):
            self.assertNotIn("CLE-SECRETE", str(self.m.api_suivies().get_json()))

    # -- la route de lecture
    def test_route_page(self):
        m = self.m
        with mock.patch.object(lecture_pages, "lire_proposition", return_value={"ok": True, "message": "ok"}) as lp, \
                mock.patch.object(lecture_pages, "lire_page", return_value={"ok": False, "error": "non", "definitif": True}) as pg:
            with m.app.test_request_context("/api/torrents/page", method="POST", json={"serie": "WIND BREAKER", "proposition": "a1", "force": True}):
                self.assertTrue(m.api_torrents_page().get_json()["ok"])
            lp.assert_called_once_with("WIND BREAKER", "a1", True)
            with m.app.test_request_context("/api/torrents/page", method="POST", json={"page": PAGE, "titre": "Wind Breaker T07"}):
                r = m.api_torrents_page().get_json()
            pg.assert_called_once_with("", PAGE, "Wind Breaker T07", None, False)
            self.assertEqual((r["ok"], r["error"]), (False, "non"))
            with m.app.test_request_context("/api/torrents/page", method="POST", json={}):
                rep = m.api_torrents_page()
            self.assertEqual(rep[1], 400)

    def test_route_page_inconnue_ne_plante_pas(self):
        m = self.m
        with m.app.test_request_context("/api/torrents/page", method="POST", json={"serie": "WIND BREAKER", "proposition": "zzz"}):
            r = m.api_torrents_page().get_json()
        self.assertEqual((r["ok"], r["definitif"]), (False, True))

    def test_retirer_une_serie_suivie_vide_oublie_sa_memoire(self):
        import tomes
        tomes.modifier("WIND BREAKER", lambda c: c.__setitem__("statut_officiel", {"anilist": 135083}))
        self.assertTrue(tomes._charger("WIND BREAKER"))
        with self.m.app.test_request_context("/api/suivies", method="POST", json={"action": "retirer", "nom": "WIND BREAKER"}):
            self.assertTrue(self.m.api_suivies().get_json()["ok"])
        self.assertFalse(tomes._charger("WIND BREAKER"))


if __name__ == "__main__":
    unittest.main()
