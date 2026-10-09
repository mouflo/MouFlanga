"""Google Books (clé API) et MangaUpdates : lectures et test de clé, réponses simulées (pas de réseau)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tomes  # noqa: E402


class Reponse:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}

    def json(self):
        return self._data


class CleGoogleTest(unittest.TestCase):
    def setUp(self):
        self.ancien = os.environ.get("GOOGLE_BOOKS_API_KEY")

    def tearDown(self):
        if self.ancien is None:
            os.environ.pop("GOOGLE_BOOKS_API_KEY", None)
        else:
            os.environ["GOOGLE_BOOKS_API_KEY"] = self.ancien

    def test_cle_acceptee(self):
        with mock.patch.object(tomes._SESSION, "get", return_value=Reponse(200, {"items": []})):
            self.assertEqual(tomes.verifier_cle_google("CLE" * 10)[0], True)

    def test_cle_refusee_sans_renvoyer_la_cle(self):
        cle = "CLE" * 10
        with mock.patch.object(tomes._SESSION, "get", return_value=Reponse(400, {"error": {"message": cle}})):
            ok, msg = tomes.verifier_cle_google(cle)
        self.assertFalse(ok)
        self.assertNotIn(cle, msg)

    def test_api_non_activee(self):
        rep = Reponse(403, {"error": {"errors": [{"reason": "accessNotConfigured"}]}})
        with mock.patch.object(tomes._SESSION, "get", return_value=rep):
            ok, msg = tomes.verifier_cle_google("CLE" * 10)
        self.assertFalse(ok)
        self.assertIn("Books API", msg)

    def test_quota(self):
        with mock.patch.object(tomes._SESSION, "get", return_value=Reponse(429)):
            self.assertIn("Quota", tomes.verifier_cle_google("CLE" * 10)[1])

    def test_pas_de_cle_pas_d_appel(self):
        os.environ.pop("GOOGLE_BOOKS_API_KEY", None)
        with mock.patch.object(tomes._SESSION, "get") as get:
            self.assertIsNone(tomes._google_books("Radiant"))
            get.assert_not_called()

    def test_google_books_lit_editeur_et_tome_max(self):
        os.environ["GOOGLE_BOOKS_API_KEY"] = "CLE" * 10
        items = {"items": [
            {"volumeInfo": {"title": "Radiant Tome 3", "publisher": "Ankama", "authors": ["Tony Valente"]}},
            {"volumeInfo": {"title": "Radiant - Tome 11", "publisher": "Ankama"}},
            {"volumeInfo": {"title": "Autre livre", "publisher": "X"}}]}
        with mock.patch.object(tomes._SESSION, "get", return_value=Reponse(200, items)):
            r = tomes._google_books("Radiant")
        self.assertEqual((r["editeur"], r["auteurs"], r["tomes"]), ("Ankama", "Tony Valente", 11))


class MangaUpdatesTest(unittest.TestCase):
    def test_editeurs_auteurs_volumes(self):
        recherche = Reponse(200, {"results": [{"record": {"series_id": 7, "title": "Radiant"}}]})
        fiche = Reponse(200, {"status": "19 Volumes (Ongoing)",
                              "publishers": [{"publisher_name": "Ankama Editions"}, {"publisher_name": "Viz"}],
                              "authors": [{"name": "Tony Valente"}, {"name": "Tony Valente"}]})
        with mock.patch.object(tomes._SESSION, "post", return_value=recherche), \
                mock.patch.object(tomes._SESSION, "get", return_value=fiche):
            r = tomes._mangaupdates(["Radiant"])
        self.assertEqual(r["editeurs"], ["Ankama Editions", "Viz"])
        self.assertEqual(r["auteurs"], ["Tony Valente"])
        self.assertEqual(r["volumes"], 19)


if __name__ == "__main__":
    unittest.main()
