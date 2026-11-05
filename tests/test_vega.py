"""Vega Livres (éditeur) : « Arena », manga français absent d'AniList, et fiche AniList devinée à tort (« AFK Arena »)."""
import pathlib
import unittest
from unittest import mock

import reseau
import tomes
import vega

F = pathlib.Path(__file__).parent / "fixtures"


def _faux_get(url, **kw):
    nom = "vega_arena_liste.html" if "catalog?series=" in url else "vega_arena_tome1.html"
    return reseau.Reponse(200, (F / nom).read_text(), {}, url, False)


class TestVega(unittest.TestCase):
    def test_liste_des_tomes(self):
        with mock.patch.object(reseau, "get", _faux_get):
            liste = vega.tomes_de_la_serie("Arena")
        self.assertEqual([t["tome"] for t in liste], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(liste[0]["isbn"], "9782379502194")

    def test_page_d_un_tome(self):
        with mock.patch.object(reseau, "get", _faux_get):
            obs = vega.lire_tome("https://www.vega-livres.fr/catalog/9782379502194/arena-tome-1")
        self.assertIn("Gabriel", obs["resume"])
        self.assertEqual(obs["date"], "2022-07-08")
        self.assertIn("Vega", obs["editeur"])

    def test_chercher_seulement_les_tomes_voulus(self):
        with mock.patch.object(reseau, "get", _faux_get):
            out = vega.chercher(["Inconnue", "Arena"], voulus={1, 2})
        self.assertEqual(sorted(out), [1, 2])
        self.assertEqual(out[1]["isbn"], "9782379502194")

    def test_panne_n_est_pas_rien_trouve(self):
        def panne(url, **kw):
            raise reseau.Panne("vega", "pas de réponse")
        with mock.patch.object(reseau, "get", panne), self.assertRaises(reseau.Panne):
            vega.chercher(["Arena"])


class TestFicheDouteuse(unittest.TestCase):
    afk = {"title": {"romaji": "Jian Yu Yuanzheng: Wu Mang Zhi Ren", "english": "Legends of Esperia: The Silent Blade"},
           "synonyms": ["AFK Arena"], "volumes": None}

    def test_un_mot_contenu_dans_un_autre_titre_est_refuse(self):
        self.assertTrue(tomes._douteuse(self.afk, "Arena", 5))

    def test_titre_identique_ou_tomes_compatibles_acceptes(self):
        self.assertFalse(tomes._douteuse({"title": {"romaji": "Arena!"}, "volumes": 2}, "Arena", 5))
        self.assertFalse(tomes._douteuse({"title": {"romaji": "Shijou Saikyou no Deshi Kenichi"}, "synonyms": [], "volumes": 61}, "Kenichi", 14))
        self.assertFalse(tomes._douteuse(self.afk, "Arena Nova", 5))          # plusieurs mots : règle inchangée

    def test_fiche_gardee_reconnue(self):
        st = {"titre": "Jian Yu Yuanzheng: Wu Mang Zhi Ren", "titre_en": "Legends of Esperia", "synonymes": ["AFK Arena"], "volumes": None}
        self.assertTrue(tomes._douteuse(st, "Arena", 5))


class TestFicheSansAniList(unittest.TestCase):
    def test_champs_de_la_fiche_retiree_sont_purges(self):
        import tempfile
        brut = {"statut_officiel": {"statut": None, "anilist": None},
                "fiche": {"sources": ["AniList"], "romaji": "Jian Yu", "scenario": "Shou Ji Quan", "mangaupdates": 1, "editeur_fr": "Vega-Dupuis",
                          "genres": "action", "date": 0, "debut": "2021"}}
        gardes = {}
        with mock.patch.object(tomes, "_charger", lambda s: brut), \
                mock.patch.object(tomes, "modifier", lambda s, f: gardes.update(brut=f(brut) or brut)), \
                mock.patch.object(tomes, "_page_wikipedia", lambda *a, **k: None), \
                mock.patch.object(tomes, "_mangaupdates", lambda t: None), \
                mock.patch.object(tomes, "_google_books", lambda t: None):
            f = tomes.fiche_bilan("Arena", forcer=True)[0]
        self.assertNotIn("romaji", f)
        self.assertNotIn("scenario", f)
        self.assertEqual(f["editeur_fr"], "Vega-Dupuis")
