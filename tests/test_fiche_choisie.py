"""« 🔎 Choisir la fiche » : la fiche AniList choisie à la main remplace la recherche automatique."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tomes  # noqa: E402


class FicheChoisieTest(unittest.TestCase):
    def test_identifiant_choisi_sans_recherche(self):
        media = {"id": 46708, "title": {"romaji": "Crows", "english": None}, "synonyms": [], "status": "FINISHED",
                 "volumes": 28, "chapters": None, "format": "MANGA", "description": ""}
        appels = []
        def post(url, json=None, timeout=None):
            appels.append(json["variables"])
            return mock.Mock(status_code=200, json=mock.Mock(return_value={"data": {"Media": media}}))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(tomes, "DOSSIER", Path(d)), \
                mock.patch.object(tomes, "ID_CHOISI", lambda s: 46708), \
                mock.patch.object(tomes._SESSION, "post", side_effect=post), \
                mock.patch.object(tomes, "_resume", return_value=("Résumé", "fr")):
            st = tomes.statut_officiel("Crows", forcer=True)
        self.assertEqual(appels, [{"i": 46708}])
        self.assertEqual((st["anilist"], st["volumes"], st["choisi"]), (46708, 28, True))

    def test_recherche_resultats(self):
        rep = mock.Mock(status_code=200, json=mock.Mock(return_value={"data": {"Page": {"media": [
            {"id": 1, "title": {"romaji": "Crows", "english": None, "native": "クローズ"}, "status": "FINISHED", "volumes": 28,
             "chapters": 0, "format": "MANGA", "startDate": {"year": 1990}, "coverImage": {"medium": "x.jpg"}, "siteUrl": "u"}]}}}))
        with mock.patch.object(tomes._SESSION, "post", return_value=rep):
            r = tomes.chercher_anilist("Crows Takahashi")
        self.assertEqual((r[0]["id"], r[0]["natif"], r[0]["annee"], r[0]["tomes"]), (1, "クローズ", 1990, 28))


if __name__ == "__main__":
    unittest.main()
