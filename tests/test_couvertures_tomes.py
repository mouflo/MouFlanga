"""Couvertures des tomes : remplacement à part du fichier, retour en arrière, sources en ligne acceptées seulement de MangaDex."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import couvertures_tomes as ct  # noqa: E402


def _image(taille=(300, 450), couleur=(200, 30, 30)):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", taille, couleur).save(b, "PNG")
    return b.getvalue()


class CouverturesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.serie = Path(self.tmp.name) / "Worst"
        self.serie.mkdir()
        self.ancien_cache = ct.DOSSIER_CACHE
        ct.DOSSIER_CACHE = Path(self.tmp.name) / "cache"

    def tearDown(self):
        ct.DOSSIER_CACHE = self.ancien_cache
        self.tmp.cleanup()

    def test_remplacer_garde_l_ancienne_et_retirer_revient(self):
        ct.enregistrer_image(self.serie, 10, _image(couleur=(255, 0, 0)))
        ct.enregistrer_image(self.serie, 10, _image(couleur=(0, 0, 255)))
        self.assertTrue(ct.chemin(self.serie, 10).is_file())
        self.assertTrue((ct.dossier_couvertures(self.serie) / "010.ancienne.jpg").is_file())
        self.assertTrue(ct.retirer(self.serie, 10))
        self.assertIsNone(ct.remplacement(self.serie, 10))

    def test_image_refusee(self):
        with self.assertRaises(ValueError):
            ct.enregistrer_image(self.serie, 1, b"pas une image")
        with self.assertRaises(ValueError):
            ct.enregistrer_image(self.serie, 1, _image(taille=(100, 100)))

    def test_seule_mangadex_est_accepte(self):
        with self.assertRaises(ValueError):
            ct.telecharger("https://exemple.org/image.jpg")

    def test_couvertures_en_ligne_par_volume(self):
        recherche = mock.Mock()
        recherche.json.return_value = {"data": [{"id": "abc", "attributes": {"title": {"ja-ro": "WORST"}}}]}
        covers = mock.Mock()
        covers.json.return_value = {"total": 2, "data": [
            {"attributes": {"volume": "10", "fileName": "a.jpg", "locale": "fr"}},
            {"attributes": {"volume": "12", "fileName": "b.jpg", "locale": "ja"}}]}
        with mock.patch.object(ct._SESSION, "get", side_effect=[recherche, covers]):
            tomes = ct.couvertures_en_ligne("Worst", ["WORST"], forcer=True)
        self.assertEqual(tomes[10][0]["url"], "https://uploads.mangadex.org/covers/abc/a.jpg")
        self.assertEqual(tomes[12][0]["langue"], "ja")

    def test_titre_identique_seulement(self):
        """« WORST外伝 » (autre série) ne doit pas passer pour « WORST »."""
        reponse = mock.Mock()
        reponse.json.return_value = {"data": [
            {"id": "gaiden", "attributes": {"title": {"en": "Worst Gaiden"}, "altTitles": [{"ja": "WORST外伝 ゼットン先生"}]}},
            {"id": "principal", "attributes": {"title": {"ja-ro": "WORST"}, "altTitles": []}}]}
        with mock.patch.object(ct._SESSION, "get", return_value=reponse):
            self.assertEqual(ct._mangadex_manga(["WORST"]), "principal")


if __name__ == "__main__":
    unittest.main()
