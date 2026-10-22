"""Lecture automatique des pages de tracker des propositions : la ligne de la proposition, la fiche de la série suivie, et jamais d'écrasement."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lecture_pages  # noqa: E402
import page_tracker  # noqa: E402
import reseau  # noqa: E402
import suivi  # noqa: E402
from test_page_tracker import HASH, SLUG, FauxTrackers, indexeurs  # noqa: E402

PAGE_C411 = f"https://c411.org/torrents/{HASH}"
TITRE_C411 = "Wind.Breaker.T07.Nii.Satoru.FR.[CBZ]-Dogbanov"


def proposition(pid, titre, page, **plus):
    return {"id": pid, "type": "nouveau", "titre": titre, "page": page, "lien": "", "taille": 1, "sources": 1, "badges": ["🇫🇷 FR"], "meme_equipe": False,
            "tomes": [7], "date": "2026-10-22", "statut": "attente", **plus}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.sauve = (suivi._ETAT["fichier"], page_tracker.FICHIER, lecture_pages.NOMS)
        suivi._ETAT["fichier"] = self.tmp / "suivies.json"
        page_tracker.FICHIER = self.tmp / "torrent-pages.json"
        lecture_pages.NOMS = lambda nom: []
        reseau.oublier_tout()
        page_tracker.oublier_indexeurs()
        self.faux = FauxTrackers()
        self.patches = [mock.patch("torrents.reglages", return_value={"prowlarr": "http://192.168.1.133:9696", "prowlarr_cle": "CLE-PROWLARR-SECRETE"}),
                        mock.patch.object(reseau.SESSION, "get", side_effect=self.faux)]
        for p in self.patches:
            p.start()
        suivi.ajouter("Wind Breaker", {"titre": "Wind Breaker", "anilist": 135083})
        self.mettre("Wind Breaker", [proposition("a1", TITRE_C411, PAGE_C411)])

    def tearDown(self):
        for p in self.patches:
            p.stop()
        suivi._ETAT["fichier"], page_tracker.FICHIER, lecture_pages.NOMS = self.sauve
        page_tracker.oublier_indexeurs()
        reseau.oublier_tout()

    def mettre(self, nom, propositions):
        d = suivi.lire()
        d["series"][nom]["propositions"] = propositions
        suivi.ecrire(d)

    def entree(self, nom="Wind Breaker"):
        return suivi.lire()["series"][nom]


class NomDuTorrentTest(unittest.TestCase):
    def test_nom_dans_titre(self):
        for titre, attendu in (("Wind.Breaker.T07.Nii.Satoru.FR.[CBZ]-Dogbanov", "Wind Breaker"),
                               ("Wind Breaker T01 à T06 - Satoru Nii (Paprika+) [CBZ] FR", "Wind Breaker"),
                               ("Gachiakuta.PACK.T01.a.T13.FRENCH.CBZ-NoTAG", "Gachiakuta"),
                               ("One.Punch.Man.T01.Yusuke.MURATA.ONE.FRENCH.[CBZ]-Paprika+", "One Punch Man"),
                               ("Beelzebub.T01-T28.FRENCH.HYBRiD.eBook-PRESSECiTRON", "Beelzebub"),
                               ("Dogsred.T04.2025.FR.CBZ-NoTag", "Dogsred"),
                               ("Kagurabachi T01  [CBZ] Fr  [ScanZone]", "Kagurabachi"),
                               ("One Piece - Tome 111 - Eiichiro Oda", "One Piece"),
                               ("20th Century Boys T01 FR", "20th Century Boys"),
                               ("No.Guns.Life.Integrale.FR.[CBZ].[Digital-2540]-TONER-PapriKa", "No Guns Life"),
                               ("", "")):
            self.assertEqual(lecture_pages.nom_dans_titre(titre), attendu, titre)

    def test_est_la_serie(self):
        e = lecture_pages.est_la_serie
        self.assertTrue(e(["Wind Breaker"], "Wind.Breaker.T07.Nii.Satoru.FR.[CBZ]-Dogbanov"))
        self.assertFalse(e(["Wind Breaker"], "The.Breaker.T01.FR.CBZ"))
        self.assertFalse(e(["One Piece"], "One.Piece.FullColor.Compressed.FR.T001-T105.CBZ-Chromatique"))     # autre édition
        self.assertFalse(e(["One Piece"], "One Piece Party T03 FR"))                                          # série dérivée
        self.assertFalse(e(["Crows"], "No.Guns.Life.Integrale.FR.[CBZ]-TONER-PapriKa"))                        # proposition d'une autre série
        self.assertFalse(e(["Rooster Fighter"], "Coq.de.Baston.T01.Sakuratani.Shu.2022.FR.[CBZ]-PapriKa"))   # titre français encore inconnu
        self.assertTrue(e(["Rooster Fighter", "Coq de Baston"], "Coq.de.Baston.T01.Sakuratani.Shu.2022.FR.[CBZ]-PapriKa"))   # connu par ses synonymes
        self.assertFalse(e(["Wind Breaker"], ""))

    def test_le_titre_francais_cache_dans_un_synonyme(self):
        """AniList : « Rooster Fighter - Coq de Baston » ; les torrents français s'appellent « Coq de Baston »."""
        e = lecture_pages.est_la_serie
        noms = ["Rooster Fighter", "Rooster Fighter - Coq de Baston", "Rooster Fighter: O Galo Lutador"]
        self.assertTrue(e(noms, "Coq.de.Baston.T01.Sakuratani.Shu.2022.FR.[CBZ]-PapriKa"))
        self.assertTrue(e(noms, "Rooster.Fighter.T01.FR.CBZ"))
        self.assertFalse(e(noms, "Coq.de.Baston.Gaiden.T01.FR.CBZ"))                      # série dérivée
        self.assertFalse(e(["Rooster Fighter"], "Coq.de.Baston.T01.FR.CBZ"))             # sans le synonyme, rien à reconnaître
        self.assertFalse(e(["Bleach", "Bleach - Part 2"], "Part.2.T01.FR.CBZ"))           # un morceau trop court n'est pas un nom
        self.assertEqual(lecture_pages.avec_sous_titres(["Kenichi", "Kenichi - Le disciple ultime"]), ["Kenichi", "Kenichi - Le disciple ultime", "Le disciple ultime"])
        self.assertEqual(lecture_pages.avec_sous_titres(["Autre - Truc machin", "Rien"]), ["Autre - Truc machin", "Rien"])      # le début n'est pas un nom connu


class LireUnePageTest(Base):
    def test_la_ligne_et_la_fiche_recoivent_ce_que_dit_la_page(self):
        r = lecture_pages.lire_proposition("Wind Breaker", "a1")
        self.assertTrue(r["ok"] and r["serie_ok"])
        self.assertEqual(sorted(r["applique"]), ["auteur", "editeur", "synopsis"])
        self.assertIn("ajouté à la fiche de « Wind Breaker »", r["message"])
        t = self.entree()["tracker"]
        self.assertTrue(t["synopsis"].startswith("Afin de venir en aide"))
        self.assertEqual((t["auteur"], t["editeur"]), ("Nii Satoru", "Pika"))
        self.assertEqual(t["synopsis_de"], {"tracker": "C411", "page": PAGE_C411})
        lu = self.entree()["propositions"][0]["lu"]
        self.assertEqual((lu["tracker"], lu["editeur"], lu["pages"], lu["resolution"], lu["isbn"]), ("C411", "Pika", 191, "1499x2250", "9782811686901"))
        self.assertTrue(lu["synopsis"])
        self.assertNotIn("erreur", lu)

    def test_rien_n_est_jamais_remplace(self):
        d = suivi.lire()
        d["series"]["Wind Breaker"]["tracker"] = {"synopsis": "Mon texte à moi", "editeur": "Éditeur choisi"}
        suivi.ecrire(d)
        r = lecture_pages.lire_proposition("Wind Breaker", "a1")
        self.assertEqual(r["applique"], ["auteur"])
        t = self.entree()["tracker"]
        self.assertEqual((t["synopsis"], t["editeur"], t["auteur"]), ("Mon texte à moi", "Éditeur choisi", "Nii Satoru"))
        self.assertNotIn("synopsis_de", t)

    def test_la_page_d_une_autre_serie_n_ajoute_rien(self):
        self.mettre("Wind Breaker", [proposition("b1", "Beelzebub.T28.FRENCH.CBZ.eBook-ebdz", "https://theoldschool.cc/torrents/325466")])
        r = lecture_pages.lire_proposition("Wind Breaker", "b1")
        self.assertTrue(r["ok"])
        self.assertIs(r["serie_ok"], False)
        self.assertEqual(r["applique"], [])
        self.assertIn("ne semble pas parler de « Wind Breaker »", r["message"])
        self.assertNotIn("tracker", self.entree())
        self.assertEqual(self.entree()["propositions"][0]["lu"]["tracker"], "The Old School (API)")     # la page est quand même lue et résumée

    def test_page_d_un_resultat_de_recherche_sans_serie(self):
        r = lecture_pages.lire_page("", f"https://tr4ker.net/torrent/{SLUG}", "Dogsred.T04.2025.FR.CBZ-NoTag")
        self.assertTrue(r["ok"])
        self.assertIsNone(r["serie_ok"])
        self.assertEqual(r["applique"], [])
        self.assertEqual(r["message"], "Page lue sur TR4KER.")
        self.assertEqual(suivi.lire()["series"]["Wind Breaker"].get("tracker"), None)

    def test_proposition_inconnue(self):
        self.assertEqual(lecture_pages.lire_proposition("Wind Breaker", "zzz")["ok"], False)
        self.assertEqual(lecture_pages.lire_proposition("Inconnue", "a1")["ok"], False)


class EchecsTest(Base):
    def test_un_echec_est_garde_et_reessaye_plus_tard(self):
        self.faux.pannes = {"c411.org": "503"}
        r = lecture_pages.lire_proposition("Wind Breaker", "a1")
        self.assertFalse(r["ok"])
        self.assertFalse(r["definitif"])
        p = suivi.proposition("Wind Breaker", "a1")
        self.assertIn("n'a pas répondu", p["lu"]["erreur"])
        self.assertFalse(lecture_pages.a_lire(p))                                  # on ne retape pas tout de suite
        with mock.patch.object(lecture_pages.time, "time", return_value=time.time() + lecture_pages.ATTENTE_ECHEC + 10):
            self.assertTrue(lecture_pages.a_lire(p))                               # plus tard, si, tant que le tracker était seulement en panne
        self.assertNotIn("tracker", self.entree())

    def test_pas_d_acces_prevu_n_est_jamais_reessaye(self):
        self.mettre("Wind Breaker", [proposition("h1", "Wind.Breaker.T01.FR", "https://hdf.world/torrents.php?id=1")])
        r = lecture_pages.lire_proposition("Wind Breaker", "h1")
        self.assertTrue(r["definitif"])
        p = suivi.proposition("Wind Breaker", "h1")
        with mock.patch.object(lecture_pages.time, "time", return_value=time.time() + 10 * 86400):
            self.assertFalse(lecture_pages.a_lire(p))

    def test_a_lire(self):
        a = lecture_pages.a_lire
        self.assertTrue(a(proposition("x", "t", PAGE_C411)))
        self.assertFalse(a(proposition("x", "t", PAGE_C411, statut="ignore")))
        self.assertFalse(a(proposition("x", "t", "")))
        self.assertFalse(a(proposition("x", "t", PAGE_C411, lu={"tracker": "C411"})))


class EnFondTest(Base):
    def test_travail_lit_les_pages_une_a_une_meme_si_l_une_plante(self):
        self.mettre("Wind Breaker", [proposition("a1", TITRE_C411, PAGE_C411),
                                     proposition("a2", "Wind.Breaker.T08.FR.CBZ", "https://c411.org/torrents/" + "1" * 40),      # supprimée du tracker
                                     proposition("a3", "Wind.Breaker.T09.FR", "https://exemple.org/x")])                          # pas un tracker de Prowlarr
        lecture_pages._travail("Wind Breaker", ["a1", "a2", "a3"])
        ps = {p["id"]: p for p in self.entree()["propositions"]}
        self.assertEqual(ps["a1"]["lu"]["tracker"], "C411")
        self.assertIn("ne connaît plus", ps["a2"]["lu"]["erreur"])
        self.assertTrue(ps["a3"]["lu"]["definitif"])

    def test_lire_en_fond_ne_bloque_pas_et_se_limite(self):
        props = [proposition(f"p{i}", TITRE_C411, PAGE_C411) for i in range(9)] + [proposition("deja", "t", PAGE_C411, lu={"tracker": "C411"})]
        with mock.patch.object(lecture_pages.threading, "Thread") as fil:
            lecture_pages.lire_en_fond("Wind Breaker", props)
        nom, ids = fil.call_args[1]["args"]
        self.assertEqual(nom, "Wind Breaker")
        self.assertEqual(len(ids), lecture_pages.MAX_PAR_PASSE)
        self.assertNotIn("deja", ids)
        fil.return_value.start.assert_called_once()

    def test_rattrapage_deux_par_serie_et_seulement_les_trackers_lisibles(self):
        self.mettre("Wind Breaker", [proposition("h1", "Wind.Breaker.T01.FR", "https://hdf.world/torrents.php?id=1"),
                                     proposition("a1", TITRE_C411, PAGE_C411),
                                     proposition("a2", "Wind.Breaker.T08.FR", "https://c411.org/torrents/" + "2" * 40),
                                     proposition("a3", "Wind.Breaker.T09.FR", "https://c411.org/torrents/" + "3" * 40)])
        with mock.patch.object(lecture_pages, "lire_en_fond") as lire:
            n = lecture_pages.rattrapage()
        self.assertEqual(n, 2)
        nom, choisies = lire.call_args[0][:2]
        self.assertEqual((nom, [p["id"] for p in choisies]), ("Wind Breaker", ["a3", "a2"]))          # les plus récentes d'abord, sans HD-Forever


class SuiviTest(Base):
    def test_verifier_ne_garde_pas_le_lien_de_prowlarr_et_appelle_apres(self):
        res = [{"titre": "Wind.Breaker.T08.Nii.Satoru.FR.[CBZ]-Dogbanov", "badges": ["🇫🇷 FR"], "page": "https://c411.org/torrents/" + "4" * 40,
                "lien": "http://192.168.1.133:9696/10/download?apikey=CLE-PROWLARR-SECRETE&link=x"}]
        vus = []
        nouv = suivi.verifier("Wind Breaker", lambda t: res, lambda n: {"tomes": set(range(1, 8))}, apres=lambda nom, n: vus.append((nom, [p["id"] for p in n])))
        self.assertEqual(len(nouv), 1)
        self.assertEqual(vus, [("Wind Breaker", [nouv[0]["id"]])])
        garde = [p for p in self.entree()["propositions"] if p["id"] == nouv[0]["id"]][0]
        self.assertNotIn("lien", garde)
        self.assertEqual(garde["page"], "https://c411.org/torrents/" + "4" * 40)
        self.assertNotIn("SECRETE", suivi._ETAT["fichier"].read_text(encoding="utf-8"))

    def test_un_hook_qui_plante_n_empeche_pas_la_verification(self):
        res = [{"titre": "Wind.Breaker.T08.FR.CBZ", "badges": ["🇫🇷 FR"], "page": "", "lien": ""}]

        def mauvais(nom, nouvelles):
            raise RuntimeError("panne")
        nouv = suivi.verifier("Wind Breaker", lambda t: res, lambda n: {"tomes": set(range(1, 8))}, apres=mauvais)
        self.assertEqual(len(nouv), 1)
        self.assertEqual(len(self.entree()["propositions"]), 2)

    def test_nettoyer_et_cacher_les_liens(self):
        d = suivi.lire()
        d["series"]["Wind Breaker"]["propositions"][0]["lien"] = "http://p/14/download?apikey=CLE-PROWLARR-SECRETE"
        suivi.ecrire(d)
        envoye = suivi.sans_liens(suivi.lire()["series"]["Wind Breaker"])
        self.assertNotIn("lien", envoye["propositions"][0])
        self.assertIn("lien", suivi.lire()["series"]["Wind Breaker"]["propositions"][0])               # la copie ne touche pas à l'original
        self.assertEqual(suivi.nettoyer_liens(), 1)
        self.assertEqual(suivi.nettoyer_liens(), 0)
        self.assertNotIn("SECRETE", suivi._ETAT["fichier"].read_text(encoding="utf-8"))
        self.assertIsNone(suivi.sans_liens(None))

    def test_noter_tracker_serie_inconnue(self):
        self.assertEqual(suivi.noter_tracker("Inconnue", {"synopsis": "x" * 50}, "https://c411.org/x", "C411"), [])


if __name__ == "__main__":
    unittest.main()
