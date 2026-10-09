"""Sources de recherche « Ajouter une série » : MangaDex et MangaUpdates (réponses simulées, pas de réseau)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import demandes  # noqa: E402


class Reponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


MANGADEX = {"data": [{
    "id": "abc", "attributes": {"title": {"en": "Radiant"}, "altTitles": [], "year": 2013, "status": "completed",
                                "lastVolume": "18", "originalLanguage": "fr"},
    "relationships": [{"type": "cover_art", "attributes": {"fileName": "cover.jpg"}}]}]}

MANGAUPDATES = {"results": [{"record": {"series_id": 7, "title": "Radiant", "year": "2013",
                                        "image": {"url": {"thumb": "https://cdn.example/t.jpg"}}}}]}


class SourcesTest(unittest.TestCase):
    def test_mangadex_lit_titre_couverture_et_langue(self):
        with mock.patch.object(demandes.requests, "get", return_value=Reponse(MANGADEX)):
            r = demandes.chercher_mangadex("radiant")[0]
        self.assertEqual(r["titre"], "Radiant")
        self.assertEqual(r["type"], "manga français")
        self.assertEqual(r["tomes"], 18)
        self.assertEqual(r["couverture"], "https://uploads.mangadex.org/covers/abc/cover.jpg.256.jpg")
        self.assertEqual(r["source"], "MangaDex")

    def test_mangaupdates_lit_titre_et_annee(self):
        with mock.patch.object(demandes.requests, "post", return_value=Reponse(MANGAUPDATES)):
            r = demandes.chercher_mangaupdates("radiant")[0]
        self.assertEqual((r["titre"], r["annee"], r["mangaupdates"]), ("Radiant", "2013", 7))

    def test_cle_titre_ignore_accents_ponctuation_et_o_barre(self):
        self.assertEqual(demandes._cle_titre("CØDE: BREAKER"), demandes._cle_titre("Code Breaker"))
        self.assertEqual(demandes._cle_titre("Été-Radiant!"), "eteradiant")

if __name__ == "__main__":
    unittest.main()
