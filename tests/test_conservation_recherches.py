"""Chaque recherche d'tomes.py distingue trouvé / rien trouvé / panne : une panne ne change rien, rien trouvé ne vide rien."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reseau  # noqa: E402
import tomes  # noqa: E402

S = "Série test"
PANNE = reseau.Panne("Wikipédia", "trop de demandes", time.time() + 600)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = [mock.patch.object(tomes, "DOSSIER", Path(self.tmp.name)), mock.patch.object(tomes, "SERIES_EXISTANTES", lambda: [S])]
        for p in self.p:
            p.start()
        tomes._CACHE_FICHES.clear()

    def tearDown(self):
        for p in self.p:
            p.stop()
        tomes._CACHE_FICHES.clear()
        self.tmp.cleanup()

    def ecrire(self, **kw):
        tomes._fichier(S).write_text(json.dumps(kw), encoding="utf-8")
        tomes._CACHE_FICHES.clear()

    def lire(self):
        return json.loads(tomes._fichier(S).read_text(encoding="utf-8"))


class StockageTest(Base):
    def test_enregistrer_sans_resultat_garde_la_repartition(self):
        self.ecrire(date=1, source="Wikipédia", tomes={"1": 1, "2": 1}, titres={"1": "A"})
        tomes._enregistrer(S, {"source": None})
        d = self.lire()
        self.assertEqual((d["tomes"], d["source"], d["essais"]), ({"1": 1, "2": 1}, "Wikipédia", 1))
        self.assertGreater(d["date"], 1)                                          # le prochain essai est repoussé

    def test_renommer_suit_le_cache_et_oublier_l_efface(self):
        self.ecrire(date=1, tomes={"1": 1})
        tomes.deplacer(S, "Nouveau nom")
        self.assertFalse(tomes._fichier(S).exists())
        self.assertTrue(tomes._fichier("Nouveau nom").exists())
        tomes.oublier("Nouveau nom")
        self.assertFalse(tomes._fichier("Nouveau nom").exists())

    def test_renommer_vers_un_nom_qui_a_deja_un_cache_garde_celui_ci(self):
        self.ecrire(date=1, tomes={"1": 1})
        tomes._fichier("Autre").write_text(json.dumps({"tomes": {"9": 9}}), encoding="utf-8")
        tomes.deplacer(S, "Autre")
        self.assertEqual(json.loads(tomes._fichier("Autre").read_text(encoding="utf-8"))["tomes"], {"9": 9})


class StatutTest(Base):
    MEDIA = {"id": 7, "title": {"romaji": "Serie", "english": None}, "synonyms": ["Série test"], "status": "FINISHED", "volumes": 3,
             "chapters": 20, "format": "MANGA", "description": "An English story about something long enough to count as a summary."}

    def ancien(self, **kw):
        base = {"date": 1, "statut": "FINISHED", "volumes": 3, "anilist": 7, "resume": "Un beau résumé français, assez long pour compter.",
                "resume_langue": "fr", "resume_source": "MangaDex", "resume_v": tomes.RESUME_VERSION, "synonymes": []}
        base.update(kw)
        self.ecrire(statut_officiel=base)

    def test_panne_d_anilist_garde_l_ancienne_fiche(self):
        self.ancien()
        with mock.patch.object(tomes, "_media_anilist", side_effect=PANNE):
            st, etat, pannes = tomes.statut_officiel_bilan(S, forcer=True)
        self.assertEqual((etat, st["resume_langue"], len(pannes)), ("panne", "fr", 1))
        self.assertEqual(self.lire()["statut_officiel"]["date"], 1)                # rien n'a été écrit

    def test_le_resume_francais_n_est_jamais_remplace_par_l_anglais(self):
        self.ancien()
        with mock.patch.object(tomes, "_media_anilist", return_value=self.MEDIA), \
                mock.patch.object(tomes, "_resume", return_value=("An English story about something long enough.", "en", [], "AniList")):
            tomes.statut_officiel_bilan(S, forcer=True)
        st = self.lire()["statut_officiel"]
        self.assertEqual((st["resume_langue"], st["resume"][:8]), ("fr", "Un beau "))
        self.assertEqual(st["synonymes"], ["Série test"])                          # le reste est mis à jour

    def test_wikipedia_en_francais_ne_remplace_pas_mangadex_mais_le_meme_service_se_rafraichit(self):
        self.ancien()
        with mock.patch.object(tomes, "_media_anilist", return_value=self.MEDIA), \
                mock.patch.object(tomes, "_resume", return_value=("Résumé de Wikipédia, assez long pour être gardé ici.", "fr", [], "Wikipédia")):
            tomes.statut_officiel_bilan(S, forcer=True)
        self.assertEqual(self.lire()["statut_officiel"]["resume_source"], "MangaDex")
        with mock.patch.object(tomes, "_media_anilist", return_value=self.MEDIA), \
                mock.patch.object(tomes, "_resume", return_value=("Nouveau résumé de MangaDex, assez long pour être gardé.", "fr", [], "MangaDex")):
            tomes.statut_officiel_bilan(S, forcer=True)
        self.assertIn("Nouveau résumé", self.lire()["statut_officiel"]["resume"])

    def test_inconnue_ne_remplace_pas_une_fiche_trouvee(self):
        self.ancien()
        with mock.patch.object(tomes, "_media_anilist", return_value=None), \
                mock.patch.object(tomes, "_resume_sans_anilist", return_value=("", "", [], "")):
            st, etat, _ = tomes.statut_officiel_bilan(S, forcer=True)
        self.assertEqual((etat, self.lire()["statut_officiel"]["anilist"]), ("vide", 7))

    def test_service_du_resume_en_panne_refait_dans_l_heure(self):
        base = {"date": time.time() - 4000, "statut": "FINISHED", "resume": "x" * 60, "resume_langue": "en", "resume_v": tomes.RESUME_VERSION,
                "synonymes": [], "resume_incomplet": ["MangaDex"]}
        self.assertFalse(tomes.statut_a_jour(base))
        self.assertTrue(tomes.statut_a_jour(dict(base, date=time.time() - 600)))

    def test_resume_anglais_d_une_serie_terminee_cherche_a_nouveau_chaque_mois(self):
        base = {"statut": "FINISHED", "resume": "x" * 60, "resume_langue": "en", "resume_v": tomes.RESUME_VERSION, "synonymes": []}
        self.assertTrue(tomes.statut_a_jour(dict(base, date=time.time() - 10 * 86400)))
        self.assertFalse(tomes.statut_a_jour(dict(base, date=time.time() - 40 * 86400)))
        self.assertTrue(tomes.statut_a_jour(dict(base, resume_langue="fr", date=time.time() - 400 * 86400)))

    def test_fiche_d_avant_sans_synonymes_refaite_une_fois(self):
        self.assertFalse(tomes.statut_a_jour({"date": time.time(), "statut": "FINISHED", "resume": "x" * 60, "resume_langue": "fr",
                                              "resume_v": tomes.RESUME_VERSION}))


class RepartitionTest(Base):
    def test_wikipedia_en_panne_et_mangadex_repond_repartition_provisoire(self):
        with mock.patch.object(tomes, "_wikipedia", side_effect=PANNE), \
                mock.patch.object(tomes, "_mangadex", return_value={"source": "MangaDex", "tomes": {1.0: 1, 2.0: 2}, "titres": {}}):
            info, etat, pannes = tomes.chercher_bilan(S)
        self.assertEqual((etat, info["source"], self.lire()["provisoire"]), ("partiel", "MangaDex", True))
        self.assertEqual(tomes.chercher_bilan(S)[1], "deja")                       # dans l'heure : on ne harcèle pas Wikipédia
        d = self.lire()
        d["date"] -= 7200                                                          # une heure plus tard : refait
        self.ecrire(**d)
        with mock.patch.object(tomes, "_wikipedia", return_value={"source": "Wikipédia", "tomes": {1.0: 1, 2.0: 1, 3.0: 2}, "titres": {}}), \
                mock.patch.object(tomes, "_mangadex", return_value=None):
            info, etat, _ = tomes.chercher_bilan(S)
        self.assertEqual((etat, info["source"]), ("ok", "Wikipédia"))
        self.assertNotIn("provisoire", self.lire())

    def test_tout_en_panne_garde_l_ancienne_repartition(self):
        self.ecrire(date=1, source="Wikipédia", tomes={"1": 1, "2": 1})
        with mock.patch.object(tomes, "_wikipedia", side_effect=PANNE), mock.patch.object(tomes, "_mangadex", side_effect=PANNE):
            info, etat, pannes = tomes.chercher_bilan(S, forcer=True)
        self.assertEqual((etat, len(pannes), info["source"]), ("panne", 2, "Wikipédia"))
        self.assertEqual(self.lire()["date"], 1)

    def test_la_liste_francaise_passe_devant_une_page_anglaise_mal_lue(self):
        """20th Century Boys : 3 tomes lus sur la page anglaise, 22 dans la liste française de Wikipédia."""
        en = {"source": "Wikipédia (List of X chapters)", "tomes": {1.0: 1, 2.0: 1, 40.0: 3}, "titres": {}}
        fr = {"source": "Wikipédia (liste française)", "tomes": {float(n): (n + 1) // 2 for n in range(1, 45)}, "titres": {}}
        with mock.patch.object(tomes, "_wikipedia", return_value=en), mock.patch.object(tomes, "_mangadex", return_value=None), \
                mock.patch.object(tomes, "titres_tomes", return_value={}), mock.patch.object(tomes, "_carte_liste_francaise", return_value=fr):
            info, etat, _ = tomes.chercher_bilan(S)
        self.assertEqual((info["source"], etat), ("Wikipédia (liste française)", "ok"))

    def test_la_page_anglaise_reste_la_reference_quand_elle_est_complete(self):
        en = {"source": "Wikipédia (List of X chapters)", "tomes": {float(n): (n + 3) // 4 for n in range(1, 41)}, "titres": {}}
        fr = {"source": "Wikipédia (liste française)", "tomes": {float(n): (n + 4) // 5 for n in range(1, 41)}, "titres": {}}
        with mock.patch.object(tomes, "_wikipedia", return_value=en), mock.patch.object(tomes, "_mangadex", return_value=None), \
                mock.patch.object(tomes, "titres_tomes", return_value={}), mock.patch.object(tomes, "_carte_liste_francaise", return_value=fr):
            info, _, _ = tomes.chercher_bilan(S)
        self.assertEqual(info["source"], "Wikipédia (List of X chapters)")

    def test_repartition_pauvre_refaite_apres_un_jour_puis_de_plus_en_plus_tard(self):
        self.ecrire(date=time.time() - 2 * 86400, source="MangaDex", tomes={"1": 1, "2": 1}, statut_officiel={"statut": "FINISHED", "volumes": 14})
        self.assertTrue(tomes._repartition_pauvre(tomes._charger(S)))
        pauvre = {"source": "MangaDex", "tomes": {1.0: 1, 2.0: 1, 3.0: 2}, "titres": {}}
        with mock.patch.object(tomes, "_wikipedia", return_value=None), mock.patch.object(tomes, "_mangadex", return_value=pauvre), \
                mock.patch.object(tomes, "_noms_anglais", return_value=[]), mock.patch.object(tomes, "titres_tomes", return_value={}), \
                mock.patch.object(tomes, "_carte_liste_francaise", return_value=None):
            tomes.chercher_bilan(S)                                        # les sources ne font pas mieux…
            self.assertEqual(self.lire()["pauvre_essais"], 1)
            self.assertEqual(tomes.chercher_bilan(S)[1], "deja")           # …alors on ne recommence pas tout de suite
        d = self.lire()
        d["date"] -= 3 * 86400
        self.ecrire(**d)
        with mock.patch.object(tomes, "_wikipedia", return_value=None), mock.patch.object(tomes, "_mangadex", return_value=pauvre), \
                mock.patch.object(tomes, "_noms_anglais", return_value=[]), mock.patch.object(tomes, "titres_tomes", return_value={}), \
                mock.patch.object(tomes, "_carte_liste_francaise", return_value=None):
            self.assertEqual(tomes.chercher_bilan(S)[1], "ok")             # 3 jours plus tard : refaite (2e essai)
        self.assertEqual(self.lire()["pauvre_essais"], 2)

    def test_aucune_source_ne_connait_la_serie_est_un_vrai_vide(self):
        with mock.patch.object(tomes, "_wikipedia", return_value=None), mock.patch.object(tomes, "_mangadex", return_value=None), \
                mock.patch.object(tomes, "_noms_anglais", return_value=[]), mock.patch.object(tomes, "_carte_liste_francaise", return_value=None), \
                mock.patch.object(tomes, "titres_tomes", return_value={}):
            info, etat, pannes = tomes.chercher_bilan(S)
        self.assertEqual((info, etat, pannes, self.lire()["essais"]), (None, "vide", [], 1))


class ListeFrancaiseTest(Base):
    def test_panne_ne_note_rien_et_vide_espace_les_essais(self):
        with mock.patch.object(tomes.wikifr, "trouver_pages", side_effect=PANNE), mock.patch.object(tomes, "_pages_wiki", side_effect=PANNE):
            titres, etat, pannes = tomes.titres_tomes_bilan(S)
        self.assertEqual((titres, etat, len(pannes)), ({}, "panne", 2))
        self.assertFalse(tomes._fichier(S).exists())                                # rien n'est écrit : réessai immédiat possible
        with mock.patch.object(tomes.wikifr, "trouver_pages", return_value=[]), mock.patch.object(tomes, "_pages_wiki", return_value=[]):
            titres, etat, _ = tomes.titres_tomes_bilan(S)
        self.assertEqual(etat, "vide")
        self.assertEqual(self.lire()["titres_tomes"]["essais"], 1)

    PAGE = "{{TomeBD/Entête\n| langue_2 = Français\n}}\n{{TomeBD\n| volume = 1\n| sortie_2 = {{date|1|mai|2010}}\n}}"

    def relire(self, **kw):
        with mock.patch.object(tomes.wikifr, "trouver_pages", return_value=["Page"]), mock.patch.object(tomes.wikifr, "liens_listes", return_value=[]), \
                mock.patch.object(tomes.wikifr, "wikitexte", return_value=self.PAGE), mock.patch.object(tomes, "_pages_wiki", return_value=[]):
            return tomes.titres_tomes_bilan(S, forcer=True, **kw)

    def test_meme_page_complete_sans_rien_retirer(self):
        self.ecrire(titres_tomes={"date": 1, "v": 1, "pages": ["Page"], "titres": {"1": "Un"},
                                  "details": {"1": {"isbn": "9782000000011", "titre": "Un"}}})
        self.relire()
        d = self.lire()["titres_tomes"]["details"]["1"]
        self.assertEqual((d["isbn"], d["titre"], d["sortie"]), ("9782000000011", "Un", "1 mai 2010"))        # l'ancien reste, le nouveau s'ajoute

    def test_autre_page_remplace_un_ancien_mauvais_rapprochement(self):
        """Boruto avait reçu les 73 volumes de Naruto : une lecture réussie d'autres pages les remplace, sans mélanger leurs champs."""
        self.ecrire(titres_tomes={"date": 1, "v": 1, "pages": ["Liste des chapitres de Naruto"], "titres": {"1": "Naruto Uzumaki", "50": "Autre"},
                                  "details": {"1": {"isbn": "9782000000011", "chapitres": ["1. Faux"]}, "50": {"isbn": "9782000000028"}}})
        self.relire()
        t = self.lire()["titres_tomes"]
        self.assertEqual(list(t["details"]), ["1"])
        self.assertNotIn("isbn", t["details"]["1"])
        self.assertEqual(t["titres"], {})

    def test_lecture_partielle_ne_remplace_rien(self):
        self.ecrire(titres_tomes={"date": 1, "v": 1, "pages": ["Ancienne"], "titres": {}, "details": {"7": {"isbn": "9782000000011"}}})
        with mock.patch.object(tomes.wikifr, "trouver_pages", return_value=["Page"]), mock.patch.object(tomes.wikifr, "liens_listes", return_value=[]), \
                mock.patch.object(tomes.wikifr, "wikitexte", return_value=self.PAGE), mock.patch.object(tomes, "_pages_wiki", side_effect=PANNE):
            tomes.titres_tomes_bilan(S, forcer=True)                       # Wikipédia en anglais n'a pas répondu : lecture partielle
        t = self.lire()["titres_tomes"]
        self.assertEqual(sorted(t["details"]), ["1", "7"])
        self.assertTrue(t["partiel"])


if __name__ == "__main__":
    unittest.main()


class ResumeDeSerieDepuisLeTomeTest(Base):
    def test_anglais_remplace_par_le_francais_du_tome_1_jamais_l_inverse(self):
        texte = "Le héros quitte son village pour la capitale et rejoint un groupe d'assassins très particulier."
        self.ecrire(statut_officiel={"statut": "FINISHED", "resume": "An English summary that is long enough.", "resume_langue": "en",
                                     "resume_source": "AniList", "anilist": 1})
        self.assertTrue(tomes.resume_de_serie_depuis_le_tome(S, texte))
        st = self.lire()["statut_officiel"]
        self.assertEqual((st["resume_langue"], st["resume_source"], st["resume"]), ("fr", "Tome 1", texte))
        self.assertFalse(tomes.resume_de_serie_depuis_le_tome(S, "Un autre texte français, lui aussi assez long pour compter ici."))   # déjà en français
        self.assertEqual(self.lire()["statut_officiel"]["resume"], texte)

    def test_un_resume_de_mangadex_ou_wikipedia_reprend_la_main(self):
        self.ecrire(statut_officiel={"statut": "FINISHED", "resume": "Un résumé du tome 1, assez long pour compter comme résumé.", "resume_langue": "fr",
                                     "resume_source": "Tome 1", "anilist": 7, "date": 1, "volumes": 3, "synonymes": []})
        media = StatutTest.MEDIA
        with mock.patch.object(tomes, "_media_anilist", return_value=media), \
                mock.patch.object(tomes, "_resume", return_value=("Résumé de Wikipédia, assez long pour être gardé ici, en français.", "fr", [], "Wikipédia")):
            tomes.statut_officiel_bilan(S, forcer=True)
        self.assertEqual(self.lire()["statut_officiel"]["resume_source"], "Wikipédia")


class ListeFrancaiseValideeTest(Base):
    def details(self, par_tome):
        self.ecrire(titres_tomes={"date": 1, "v": 3, "titres": {}, "details": {str(t): {"numeros": nums} for t, nums in par_tome.items()}})

    def test_numerotation_continue_acceptee(self):
        self.details({1: [1, 2, 3], 2: [4, 5], 3: [6, 7, 8], 4: [9]})
        carte = tomes._carte_liste_francaise(S)
        self.assertEqual((carte["tomes"][4.0], len(carte["tomes"])), (2, 9))

    def test_numerotation_qui_repart_a_chaque_tome_refusee(self):
        """20th Century Boys : « Chapitre 1 » dans chaque volume ; seule la 1re ligne comptait, la carte était fausse (4 tomes sur 22)."""
        self.details({1: [1, 2, 3], 2: [1, 2, 3], 3: [1, 2, 3], 4: [1, 2]})
        self.assertIsNone(tomes._carte_liste_francaise(S))

    def test_numeros_meles_refuses(self):
        self.details({1: [1, 2, 9], 2: [3, 4], 3: [5, 6]})
        self.assertIsNone(tomes._carte_liste_francaise(S))

    def test_moins_de_trois_tomes_refuse(self):
        self.details({1: [1, 2], 2: [3, 4]})
        self.assertIsNone(tomes._carte_liste_francaise(S))

    def test_listes_d_une_autre_serie_citees_par_l_article_ecartees(self):
        """L'article « Boruto » cite les listes de chapitres de « Naruto » : elles ne sont pas lues pour Boruto."""
        lues = []

        def lire(texte, deja=None):
            lues.append(texte)
            return deja if deja is not None else {}
        with mock.patch.object(tomes.wikifr, "trouver_pages", side_effect=lambda f, fa=(), a=(), liste=False, limite=5, meres=(): [] if liste else ["Boruto"]), \
                mock.patch.object(tomes.wikifr, "liens_listes", return_value=["Liste des chapitres de Naruto (1re partie)", "Liste des chapitres de Boruto (2e partie)"]), \
                mock.patch.object(tomes.wikifr, "wikitexte", side_effect=lambda p: "TEXTE:" + p), \
                mock.patch.object(tomes.wikifr, "lire_volumes", side_effect=lire), mock.patch.object(tomes, "_pages_wiki", return_value=[]):
            tomes.titres_tomes_bilan("Boruto", forcer=True)
        self.assertIn("TEXTE:Boruto", lues)
        self.assertIn("TEXTE:Liste des chapitres de Boruto (2e partie)", lues)
        self.assertNotIn("TEXTE:Liste des chapitres de Naruto (1re partie)", lues)
