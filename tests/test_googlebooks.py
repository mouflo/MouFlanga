"""googlebooks.py : une recherche pour toute la série, jamais un autre livre, quota et panne remontés sans rien perdre."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import googlebooks as G  # noqa: E402
import reseau  # noqa: E402

DESC = "Akame et ses compagnons du Night Raid affrontent un nouvel ennemi redoutable dans la capitale impériale."


def item(titre, isbn, desc=DESC, langue="fr", editeur="Kurokawa"):
    return {"volumeInfo": {"title": titre, "language": langue, "publisher": editeur, "description": desc, "publishedDate": "2015-03-01",
                           "industryIdentifiers": [{"type": "ISBN_13", "identifier": isbn}] if isbn else []}}


class Rep:
    def __init__(self, statut=200, corps=None):
        self.status_code = statut
        self._c = corps if corps is not None else {}
        self.text = ""
        self.headers = {}

    def json(self):
        return self._c


class NoticeTest(unittest.TestCase):
    NOMS = ["Akame ga Kill !", "Red Eyes Sword"]

    def test_tome_reconnu_avec_isbn_et_resume(self):
        n = G.notice(item("Red Eyes Sword - Akame ga Kill ! - Tome 5", "9782368520543"), self.NOMS)
        self.assertEqual((n["tome"], n["isbn"], n["editeur"], n["date"]), (5, "9782368520543", "Kurokawa", "2015"))
        self.assertEqual(n["resume"], DESC)

    def test_autres_livres_refuses(self):
        rejets = [item("Akame ga Kill ! Zero - Tome 10", "9782368527276"),                  # série dérivée
                  item("Akame ga Kill ! - Tome 5 - Édition limitée", "9782368520543"),      # autre édition
                  item("Akame ga Kill !", "9782368520543"),                                  # pas de numéro de tome
                  item("Akame ga Kill ! - Tome 5", "9782368520544"),                         # somme de contrôle fausse
                  item("Akame ga Kill ! - Tome 5", "9786525920122"),                         # édition brésilienne
                  item("Akame ga Kill ! - Tome 5", "9782368520543", langue="en"),
                  item("Autre série - Tome 5", "9782368520543")]
        for it in rejets:
            self.assertIsNone(G.notice(it, self.NOMS), it["volumeInfo"]["title"])

    def test_pas_d_isbn_mais_un_resume(self):
        n = G.notice(item("Akame ga Kill ! - Tome 6", "", DESC), self.NOMS)
        self.assertEqual((n["tome"], n["isbn"], n["resume"]), (6, "", DESC))

    def test_resume_trop_court_ou_balises_nettoyees(self):
        self.assertEqual(G.notice(item("Akame ga Kill ! - Tome 6", "", "Court"), self.NOMS)["resume"], "")
        n = G.notice(item("Akame ga Kill ! - Tome 6", "", "<b>Gras</b><br/>" + DESC), self.NOMS)
        self.assertNotIn("<", n["resume"])


class SansNumeroDansLeTitreTest(unittest.TestCase):
    """Cas réel : pour Air Gear, Google rend les tomes français sous le titre « Air Gear » tout court, sans le numéro."""
    NOMS = ["Air Gear"]

    def test_l_isbn_connu_donne_le_tome(self):
        it = item("Air Gear", "9782811602680", editeur="Pika")
        self.assertIsNone(G.notice(it, self.NOMS))                                                  # sans autre source : on ne sait pas quel tome
        n = G.notice(it, self.NOMS, isbn_tomes={"9782811602680": 1})
        self.assertEqual((n["tome"], n["isbn"], n["editeur"], n["resume"]), (1, "9782811602680", "Pika", DESC))
        self.assertIsNone(G.notice(it, self.NOMS, isbn_tomes={"9782811610166": 2}))                 # cet ISBN n'est celui d'aucun tome connu
        self.assertIsNone(G.notice(item("Livres de France", "9782811602680"), self.NOMS, isbn_tomes={"9782811602680": 1}))    # pas la série

    def test_le_numero_du_titre_passe_devant(self):
        n = G.notice(item("Air Gear T23", "9782811624972"), self.NOMS, isbn_tomes={"9782811624972": 7})
        self.assertEqual(n["tome"], 23)

    def test_parle_de_la_serie(self):
        self.assertTrue(G.parle_de_la_serie(item("Air Gear", "9782811602680"), self.NOMS))
        self.assertTrue(G.parle_de_la_serie(item("Air Gear Unlimited Tome 1", ""), self.NOMS))
        self.assertFalse(G.parle_de_la_serie(item("Chine moderne", ""), self.NOMS))


class RechercheTest(unittest.TestCase):
    def setUp(self):
        reseau.oublier_tout()
        self.env = mock.patch.dict(os.environ, {"GOOGLE_BOOKS_API_KEY": "CLE" * 10})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        reseau.oublier_tout()

    def test_une_recherche_pour_toute_la_serie_s_arrete_quand_tout_est_trouve(self):
        page1 = {"items": [item("Akame ga Kill ! - Tome 1", "9782368520444"), item("Akame ga Kill ! - Tome 2", "9782368520512"),
                           item("Akame ga Kill ! - Tome 3", "9782368520529")]}
        with mock.patch.object(reseau.SESSION, "get", side_effect=[Rep(200, page1)]) as get:
            r = G.chercher_serie(["Akame ga Kill !"], voulus={3})
        self.assertEqual(sorted(r), [1, 2, 3])                                       # tout ce que la page contenait est gardé
        self.assertEqual(get.call_count, 1)                                          # et on ne demande pas la suite

    def test_pages_de_vingt_la_suite_commence_la_ou_la_precedente_s_arrete(self):
        """Google rend 20 résultats par page même quand on en demande 40 : on ne conclut pas « fini » et on ne saute rien."""
        p1 = {"items": [item(f"Akame ga Kill ! - Tome {i}", "") for i in (1, 2, 3)] + [item("Autre livre", "")] * 17}
        p2 = {"items": [item(f"Akame ga Kill ! - Tome {i}", "") for i in (4, 5)] + [item("Autre livre", "")] * 18}
        p3 = {"items": [item("Chine moderne", "")] * 20}                                           # Google passe au hors-sujet : fini
        with mock.patch.object(reseau.SESSION, "get", side_effect=[Rep(200, p1), Rep(200, p2), Rep(200, p3), Rep(200, p3)]) as get:
            r = G.chercher_serie(["Akame ga Kill !"], voulus={1, 2, 3, 4, 5, 9})
        self.assertEqual(sorted(r), [1, 2, 3, 4, 5])
        self.assertEqual([c.kwargs["params"]["startIndex"] for c in get.call_args_list], [0, 20, 40])
        self.assertEqual(get.call_count, 3)

    def test_isbn_connus_passes_a_la_recherche(self):
        page = {"items": [item("Air Gear", "9782811602680"), item("Air Gear", "9782811610166"), item("Air Gear T23", "9782811624972")]}
        with mock.patch.object(reseau.SESSION, "get", return_value=Rep(200, page)):
            r = G.chercher_serie(["Air Gear"], voulus={1, 2, 23}, isbn_tomes={"9782811602680": 1, "9782811610166": 2})
        self.assertEqual(sorted(r), [1, 2, 23])

    def test_sans_cle_aucun_appel(self):
        with mock.patch.dict(os.environ, {"GOOGLE_BOOKS_API_KEY": ""}), mock.patch.object(reseau.SESSION, "get") as get:
            self.assertEqual(G.chercher_serie(["Akame ga Kill !"]), {})
            self.assertIsNone(G.chercher_tome(["Akame ga Kill !"], 3))
            get.assert_not_called()

    def test_quota_atteint_remonte_une_quota(self):
        rep = Rep(429, {"error": {"message": "Quota exceeded for limit 'Queries per day'"}})
        rep.text = "Quota exceeded ... Queries per day"
        with mock.patch.object(reseau.SESSION, "get", return_value=rep):
            with self.assertRaises(reseau.Quota):
                G.chercher_serie(["Akame ga Kill !"])
            with self.assertRaises(reseau.Quota):                                 # puis plus aucun appel : la pause est retenue
                G.chercher_tome(["Akame ga Kill !"], 3)

    def test_panne_apres_une_page_garde_ce_qui_a_ete_trouve(self):
        base = [item("Akame ga Kill ! - Tome 1", "9782368520444"), item("Akame ga Kill ! - Tome 2", "9782368520512")]
        page_pleine = {"items": base + [item("Autre livre", "")] * 38}              # 40 notices : une 2e page est demandée
        with mock.patch.object(reseau.SESSION, "get", side_effect=[Rep(200, page_pleine)] + [Rep(503)] * 6):
            r = G.chercher_serie(["Akame ga Kill !"], voulus={1, 2, 3})
        self.assertEqual(sorted(r), [1, 2])                                          # la panne de la 2e page ne fait rien perdre

    def test_infos_serie(self):
        items = {"items": [{"volumeInfo": {"title": "Radiant Tome 3", "publisher": "Ankama", "authors": ["Tony Valente"]}},
                           {"volumeInfo": {"title": "Radiant - Tome 11", "publisher": "Ankama"}},
                           {"volumeInfo": {"title": "Autre livre", "publisher": "X"}}]}
        with mock.patch.object(reseau.SESSION, "get", return_value=Rep(200, items)):
            r = G.infos_serie("Radiant")
        self.assertEqual((r["editeur"], r["auteurs"], r["tomes"]), ("Ankama", "Tony Valente", 11))


if __name__ == "__main__":
    unittest.main()
