"""« ✏️ Mon édition » : nom, nombre de tomes, page de l'éditeur ; les ISBN des tomes servent de preuve (Rave, 13/11/2026)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import glenat  # noqa: E402
import mon_edition  # noqa: E402
import reseau  # noqa: E402
from test_glenat import URL1, FauxGlenat  # noqa: E402

PAGES = [{"tomes": [8], "tracker": "C411", "presentation": "Rave The Goove Adventure\n\nTome 08\n\nFormat E-book\n\nISBN : 9782344060483\nÉditeur : Glénat"},
         {"tomes": [1], "tracker": "C411", "presentation": "Tome 01 ISBN 978-2-344-06041-4"},
         {"tomes": [1, 2, 3], "tracker": "TR4KER", "presentation": "Lot de 3 tomes : 9782344060414 9782344060421"},      # plusieurs tomes : pas d'attribution
         {"tomes": [4], "tracker": "C411", "presentation": "ISBN 9782344060446"}]                                           # clé fausse : refusé


class TestIsbn(unittest.TestCase):
    def test_isbn_ecrits_dans_un_texte(self):
        self.assertEqual(mon_edition.isbn13_dans("ISBN : 978-2-344-06048-3 et 9782344060483 puis 9782344060446"), ["9782344060483"])

    def test_isbn_des_pages_de_torrents_et_des_tomes(self):
        out = mon_edition.isbn_des_tomes({"isbn": {"2": "9782344060421", "x": "abc"}}, PAGES)
        self.assertEqual({t: [x["isbn"] for x in v] for t, v in out.items()}, {1: ["9782344060414"], 2: ["9782344060421"], 8: ["9782344060483"]})
        self.assertEqual(out[2][0]["source"], "lu dans le tome")
        self.assertIn("C411", out[8][0]["source"])

    def test_echantillon(self):
        self.assertEqual(mon_edition.echantillon({1: 0, 2: 0, 4: 0, 8: 0, 9: 0}), [1, 4, 9])
        self.assertEqual(mon_edition.echantillon({}), [])


class TestVerifierLien(unittest.TestCase):
    def verifier(self, lien, isbn):
        with mock.patch.object(reseau, "get", FauxGlenat()):
            return mon_edition.verifier_lien(lien, isbn)

    def test_les_isbn_des_tomes_sont_ceux_de_l_edition(self):
        isbn = mon_edition.isbn_des_tomes({}, PAGES)
        v = self.verifier(URL1, isbn)
        self.assertTrue(v["ok"])
        self.assertEqual((v["edition"], v["serie"], v["pages"]), ("Édition originale", "Rave", 384))
        self.assertEqual(v["concordent"], [1, 8])

    def test_une_autre_edition_est_refusee(self):
        isbn = {1: [{"isbn": "9782723463829", "source": "lu dans le tome"}], 8: [{"isbn": "9782723458412", "source": "lu dans le tome"}]}
        v = self.verifier(URL1, isbn)
        self.assertFalse(v["ok"])
        self.assertEqual(sorted(v["differents"]), [1, 8])

    def test_sans_isbn_on_ne_peut_que_lire_la_page(self):
        v = self.verifier(URL1, {})
        self.assertTrue(v["ok"])
        self.assertEqual((v["edition"], v["concordent"], v["lus"]), ("Édition originale", [], [1]))

    def test_adresse_d_un_autre_site_refusee(self):
        with self.assertRaises(glenat.PageIllisible):
            mon_edition.verifier_lien("https://www.kana.fr/manga/rave", {})

    def test_panne_de_l_editeur(self):
        with mock.patch.object(reseau, "get", FauxGlenat(panne=True)), self.assertRaises(reseau.Panne):
            mon_edition.verifier_lien(URL1, {})


class TestFormulaire(unittest.TestCase):
    def test_validation(self):
        self.assertIsNone(mon_edition.valider({"nom": "Deluxe", "volumes": "18", "lien": ""}))
        self.assertIsNone(mon_edition.valider({"nom": "", "volumes": "", "lien": ""}))
        for mauvais in ({"volumes": "0"}, {"volumes": "dix"}, {"volumes": "1000"}, {"nom": "x" * 81}, {"nom": "a<b"}, {"lien": "h" * 301}):
            self.assertTrue(mon_edition.valider(mauvais), mauvais)

    def test_ce_qui_est_retenu(self):
        r = mon_edition.a_retenir({"nom": "", "volumes": "18", "lien": URL1}, {}, {"edition": "Édition originale"})
        self.assertEqual(r, {"edition": "Édition originale", "volumes_attendus": 18, "volumes_manuel": True, "edition_lien": URL1, "edition_editeur": "Glénat"})
        # le nom tapé l'emporte sur celui de l'éditeur ; rien de rempli = tout oublier
        self.assertEqual(mon_edition.a_retenir({"nom": "  Ma   Deluxe ", "volumes": ""}, {}, {"edition": "X"}), {"edition": "Ma Deluxe"})
        self.assertEqual(mon_edition.a_retenir({}, {"edition": "Avant"}), {})
        self.assertEqual(mon_edition.a_retenir({"lien": "https://exemple.org/x"}, {}), {})           # adresse non lue : pas gardée


if __name__ == "__main__":
    unittest.main()


class TestRoute(unittest.TestCase):
    """POST /api/edition/mon-edition : enregistre, vérifie le lien avec les ISBN, ne perd rien en cas de panne (série d'essai jetable)."""

    def setUp(self):
        import os
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MANGA_DIR"] = str(Path(self.tmp.name) / "mangas")
        (Path(self.tmp.name) / "mangas" / "Rave").mkdir(parents=True)
        sys.modules.pop("app", None)
        import app as A
        import auth
        self.A = A
        A.MANGA_DIR = Path(self.tmp.name) / "mangas"
        A.torrents._ETAT["fichier"] = Path(self.tmp.name) / "torrents.json"
        self.scan = mock.patch.object(A, "_scan", return_value={"Rave": []})
        self.scan.start()
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        self.client = A.app.test_client()
        with self.client.session_transaction() as s:
            s["u"], s["f"] = "test", auth._fingerprint()
        self.role = mock.patch.object(A.auth, "role", return_value="admin")
        self.role.start()
        self.pages = mock.patch.object(A, "_pages_de_torrents", return_value=PAGES[:2])      # T8 et T1 : ISBN de l'édition originale
        self.pages.start()

    def tearDown(self):
        for p in (self.pages, self.role, self.scan):
            p.stop()
        self.tmp.cleanup()

    def infos(self):
        import edition
        return edition.lire(self.A.MANGA_DIR / "Rave")

    def poster(self, **corps):
        return self.client.post("/api/edition/mon-edition", json={"series": "Rave", **corps})

    def test_lecture_montre_les_isbn_des_tomes(self):
        r = self.client.get("/api/edition/mon-edition?series=Rave").get_json()
        self.assertEqual([(x["tome"], x["isbn"]) for x in r["isbn"]], [(1, "9782344060414"), (8, "9782344060483")])
        self.assertEqual((r["nom"], r["volumes"], r["lien"]), ("", None, ""))

    def test_enregistre_nom_tomes_et_page_de_l_editeur_apres_verification(self):
        with mock.patch.object(reseau, "get", FauxGlenat()):
            r = self.poster(nom="", volumes="18", lien=URL1)
        self.assertTrue(r.get_json()["ok"], r.get_json())
        d = self.infos()
        self.assertEqual((d["edition"], d["volumes_attendus"], d["volumes_manuel"], d["edition_lien"], d["edition_editeur"]),
                         ("Édition originale", 18, True, URL1, "Glénat"))
        self.assertIn("ISBN confirmés pour T1, T8", r.get_json()["message"])
        g = self.client.get("/api/edition/mon-edition?series=Rave").get_json()
        self.assertEqual((g["nom"], g["volumes"], g["lien"], g["editeur_lu"]), ("Édition originale", 18, URL1, True))

    def test_un_nom_tape_l_emporte(self):
        with mock.patch.object(reseau, "get", FauxGlenat()):
            self.poster(nom="Édition originale Glénat", volumes="18", lien=URL1)
        self.assertEqual(self.infos()["edition"], "Édition originale Glénat")

    def test_seulement_le_nombre_de_tomes_reste_comme_avant(self):
        r = self.poster(volumes="11")
        self.assertTrue(r.get_json()["ok"])
        d = self.infos()
        self.assertEqual((d["volumes_attendus"], d["volumes_manuel"], d["edition"]), (11, True, "Édition en 11 tomes (indiquée à la main)"))

    def test_une_autre_edition_exige_une_confirmation(self):
        import mon_edition
        with mock.patch.object(self.A, "_pages_de_torrents", return_value=[{"tomes": [1], "tracker": "C411", "presentation": "ISBN 9782723463829"}]), \
                mock.patch.object(reseau, "get", FauxGlenat()):
            r = self.poster(volumes="18", lien=URL1)
            self.assertEqual(r.status_code, 409)
            self.assertTrue(r.get_json()["confirmer"])
            self.assertEqual(self.infos().get("edition_lien"), None)                        # rien n'est modifié
            r = self.poster(volumes="18", lien=URL1, confirme=True)
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(self.infos()["edition_lien"], URL1)

    def test_editeur_qui_ne_repond_pas_ne_modifie_rien(self):
        with mock.patch.object(reseau, "get", FauxGlenat(panne=True)):
            r = self.poster(volumes="18", lien=URL1)
        self.assertEqual(r.status_code, 503)
        self.assertIn("rien n'est modifié", r.get_json()["error"])
        self.assertNotIn("volumes_attendus", self.infos())

    def test_adresse_non_lue_refusee_et_champs_invalides(self):
        self.assertEqual(self.poster(lien="https://www.kana.fr/manga/rave").status_code, 400)
        self.assertEqual(self.poster(volumes="dix").status_code, 400)
        self.assertEqual(self.client.post("/api/edition/mon-edition", json={"series": "Inconnue"}).status_code, 404)

    def test_tout_vider_revient_a_la_detection_automatique(self):
        with mock.patch.object(reseau, "get", FauxGlenat()):
            self.poster(volumes="18", lien=URL1)
        r = self.poster()
        self.assertEqual(r.get_json()["message"], "Édition : détection automatique.")
        d = self.infos()
        for cle in ("edition", "volumes_attendus", "volumes_manuel", "edition_lien", "edition_editeur", "edition_manuelle"):
            self.assertNotIn(cle, d)


class TestSerieMelant2Editions(unittest.TestCase):
    def test_les_tomes_d_une_autre_edition_ne_comptent_pas(self):
        """Rave réelle : tomes 1-12 de l'édition originale, tomes 25-35 de l'ancienne (ISBN 978-2-7234…). Seuls les tomes que la page de
        l'éditeur peut avoir (1 à 16) servent de preuve."""
        isbn = mon_edition.isbn_des_tomes({"isbn": {"25": "9782723457972", "35": "9782723464857"}}, PAGES[:2])
        with mock.patch.object(reseau, "get", FauxGlenat()):
            v = mon_edition.verifier_lien(URL1, isbn)
        self.assertTrue(v["ok"])
        self.assertEqual(v["concordent"], [1, 8])                    # pas 25 ni 35
