"""Couvertures des tomes : remplacement à part du fichier, retour en arrière, sources en ligne acceptées seulement de MangaDex et ZOO."""
import io
import json
import sys
import tempfile
import time
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
        for cible, retour in (("couvertures", {}), ("chercher_serie", (0, 0, []))):      # jamais les vraies données ni Internet
            p = mock.patch.object(ct.editeurs, cible, return_value=retour)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(ct, "mangadex_images_ok", return_value=True)       # jamais Internet
        p.start()
        self.addCleanup(p.stop)
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

    def test_ponctuation_gardee(self):
        """« Again!! » (Mitsurou Kubo) ne doit pas passer pour « Again » (autre série)."""
        reponse = mock.Mock()
        reponse.json.return_value = {"data": [
            {"id": "again-kubo", "attributes": {"title": {"ja-ro": "Again!!"}, "altTitles": []}}]}
        with mock.patch.object(ct._SESSION, "get", return_value=reponse):
            self.assertIsNone(ct._mangadex_manga(["Again"]))
            self.assertEqual(ct._mangadex_manga(["Again!!"]), "again-kubo")

    def test_formats_courants_acceptes(self):
        """WebP et PNG transparent sont convertis en JPEG ; la transparence devient blanche."""
        from PIL import Image
        for format_, mode in (("WEBP", "RGB"), ("PNG", "RGBA")):
            b = io.BytesIO()
            Image.new(mode, (300, 450), (200, 30, 30, 0) if mode == "RGBA" else (200, 30, 30)).save(b, format_)
            with tempfile.TemporaryDirectory() as tmp:
                cible = ct.enregistrer_image(Path(tmp), 1, b.getvalue())
                with Image.open(cible) as img:
                    self.assertEqual(img.format, "JPEG")
                    attendu = (255, 255, 255) if mode == "RGBA" else (200, 30, 30)
                    self.assertTrue(all(abs(a - b) <= 8 for a, b in zip(img.getpixel((5, 5)), attendu)))  # JPEG : marge

    def test_heic_accepte(self):
        """Les photos d'iPhone (HEIC) sont lues une fois pillow-heif installé."""
        try:
            import pillow_heif
        except ImportError:
            self.skipTest("pillow-heif non installé")
        from PIL import Image
        pillow_heif.register_heif_opener()
        b = io.BytesIO()
        Image.new("RGB", (300, 450), (30, 30, 200)).save(b, "HEIF")
        with tempfile.TemporaryDirectory() as tmp:
            cible = ct.enregistrer_image(Path(tmp), 2, b.getvalue())
            self.assertTrue(cible.is_file())

    def test_plus_au_lieu_du_signe_plus(self):
        """« + Again » est trouvé sous son titre anglais « Plus Again » (l'API ignore le « + »)."""
        reponse = mock.Mock()
        reponse.json.return_value = {"data": [
            {"id": "plus-again", "attributes": {"title": {"en": "+Again"}, "altTitles": [{"en": "Plus Again"}]}}]}
        with mock.patch.object(ct._SESSION, "get", return_value=reponse):
            self.assertEqual(ct._mangadex_manga(["+ Again"]), "plus-again")

    def test_cache_separe_par_serie(self):
        """« + Again » et « Again » n'ont pas le même fichier de cache."""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(ct, "DOSSIER_CACHE", Path(tmp)), mock.patch.object(ct, "_mangadex_manga", return_value=None):
                ct.couvertures_en_ligne("+ Again", ["+ Again"])
                ct.couvertures_en_ligne("Again", ["Again"])
                self.assertEqual(len(list(Path(tmp).glob("*.json"))), 2)

    def test_ancien_cache_refait(self):
        """Un cache d'une ancienne version (résultats possiblement faux) est ignoré et refait."""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(ct, "DOSSIER_CACHE", Path(tmp)):
                (Path(tmp) / "Again.json").write_text(json.dumps({"date": time.time(), "manga": "faux", "tomes": {
                    "1": [{"url": "https://uploads.mangadex.org/covers/faux/x.jpg", "vignette": "", "langue": "en"}]}}),
                    encoding="utf-8")
                with mock.patch.object(ct, "_mangadex_manga", return_value=None) as recherche:
                    self.assertEqual(ct.couvertures_en_ligne("Again", ["Again"]), {})
                    recherche.assert_called_once()


PAGE_ZOO = ('<a href="manga/noritaka/21535-8-noritaka-le-roi-de-la-baston-t_8"><img src="https://cdn.zoolemag.com/red/alb/21535/426268-1.jpg"></a>'
            '<a href="manga/noritaka/21536-9-noritaka-le-roi-de-la-baston-t_9"><img src="https://cdn.zoolemag.com/red/alb/21536/426269-1.jpg"></a>'
            '<a href="manga/noritaka/21536-9-noritaka-le-roi-de-la-baston-t_9">doublon</a>')


class ZooTest(unittest.TestCase):
    def setUp(self):
        for cible, retour in (("couvertures", {}), ("chercher_serie", (0, 0, []))):
            p = mock.patch.object(ct.editeurs, cible, return_value=retour)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(ct, "mangadex_images_ok", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.ancien_cache = ct.DOSSIER_CACHE
        ct.DOSSIER_CACHE = Path(self.tmp.name) / "cache"

    def tearDown(self):
        ct.DOSSIER_CACHE = self.ancien_cache
        self.tmp.cleanup()

    def test_adresse_normalisee_oubliee_ou_refusee(self):
        self.assertEqual(ct.zoo_definir("Noritaka", "https://zoolemag.com/serie-5382-noritaka?x=1#a"), "https://zoolemag.com/serie-albums-5382-noritaka")
        self.assertEqual(ct.zoo_adresse("Noritaka"), "https://zoolemag.com/serie-albums-5382-noritaka")
        for mauvaise in ("https://exemple.org/serie-1-x", "https://zoolemag.com/manga/noritaka/21536-9-noritaka-t_9", "javascript:alert(1)"):
            with self.assertRaises(ValueError):
                ct.zoo_definir("Noritaka", mauvaise)
        self.assertEqual(ct.zoo_definir("Noritaka", ""), "")
        self.assertEqual(ct.zoo_adresse("Noritaka"), "")

    def test_tomes_lus_sur_la_page_en_grand_format(self):
        page = mock.Mock(statut=200, texte=PAGE_ZOO)
        with mock.patch.object(ct.reseau, "get", return_value=page):
            tomes = ct._zoo_tomes("https://zoolemag.com/serie-albums-5382-noritaka")
        self.assertEqual(sorted(tomes), [8, 9])
        self.assertEqual(len(tomes[9]), 1)
        self.assertEqual(tomes[9][0]["url"], "https://cdn.zoolemag.com/red/alb/21536/720-sw/426269-1.jpg")
        self.assertEqual(tomes[9][0]["langue"], "fr")

    def test_zoo_passe_devant_et_une_panne_n_enleve_rien(self):
        ct.zoo_definir("Noritaka", "https://zoolemag.com/serie-5382-noritaka")
        md = {9: [{"url": ct.PREFIXE_MANGADEX + "a/b.jpg", "vignette": "", "langue": "fr"}]}
        with mock.patch.object(ct, "_couvertures_mangadex", return_value=md), \
                mock.patch.object(ct.reseau, "get", return_value=mock.Mock(statut=200, texte=PAGE_ZOO)):
            tomes = ct.couvertures_en_ligne("Noritaka", ["Noritaka"])
        self.assertEqual([c["url"].startswith(ct.PREFIXE_ZOO) for c in tomes[9]], [True, False])
        self.assertEqual(len(md[9]), 1)                      # le résultat de MangaDex (gardé en cache) n'est pas modifié
        with mock.patch.object(ct, "_couvertures_mangadex", return_value=md), \
                mock.patch.object(ct.reseau, "get", side_effect=ct.reseau.Panne("zoo", "coupé")):
            self.assertEqual(ct.couvertures_en_ligne("Noritaka", ["Noritaka"]), md)

    def test_telechargement_zoo_accepte_et_retombe_sur_la_petite(self):
        grande, petite = mock.Mock(status_code=404), mock.Mock(status_code=200, content=b"ok")
        with mock.patch.object(ct._SESSION, "get", side_effect=[grande, petite]) as g, mock.patch.object(ct, "ZOO_INTERVALLE", 0):
            self.assertEqual(ct.telecharger("https://cdn.zoolemag.com/red/alb/1/720-sw/x.jpg"), b"ok")
        self.assertEqual(g.call_args_list[1].args[0], "https://cdn.zoolemag.com/red/alb/1/x.jpg")


if __name__ == "__main__":
    unittest.main()


class TestTomesPresentsEnChapitres(unittest.TestCase):
    """Série découpée en chapitres : les entrées n'ont pas de champ « tome », seulement le dossier « Tome NN »."""

    def test_numero_du_tome_d_une_entree(self):
        import app as A
        self.assertEqual(A._numero_du_tome_d_une_entree({"tome": 4, "groupe": "Tome 04"}), 4)
        self.assertEqual(A._numero_du_tome_d_une_entree({"num": 7.0, "groupe": "Tome 03"}), 3)
        self.assertIsNone(A._numero_du_tome_d_une_entree({"num": 7.0, "groupe": None}))
        self.assertIsNone(A._numero_du_tome_d_une_entree({"groupe": "Tome 03", "a_importer": True}))


class MangaDexBloqueTest(unittest.TestCase):
    def test_propositions_mangadex_masquees_quand_leurs_images_sont_bloquees(self):
        md = {"url": ct.PREFIXE_MANGADEX + "x/a.jpg", "vignette": ct.PREFIXE_MANGADEX + "x/a.jpg.256.jpg", "langue": "fr"}
        ed = {"url": "https://media.hachette.fr/a.jpg", "vignette": "https://media.hachette.fr/a.jpg", "langue": "fr", "source": "Pika"}
        with mock.patch.object(ct, "_couvertures_mangadex", return_value={1: [md]}), mock.patch.object(ct, "zoo_adresse", return_value=""), \
                mock.patch.object(ct.editeurs, "couvertures", return_value={1: [ed]}), mock.patch.object(ct, "mangadex_images_ok", return_value=False):
            self.assertEqual(ct.couvertures_en_ligne("S", ["S"])[1], [ed])
        with mock.patch.object(ct, "_couvertures_mangadex", return_value={1: [md]}), mock.patch.object(ct, "zoo_adresse", return_value=""), \
                mock.patch.object(ct.editeurs, "couvertures", return_value={1: [ed]}), mock.patch.object(ct, "mangadex_images_ok", return_value=True):
            self.assertEqual(ct.couvertures_en_ligne("S", ["S"])[1], [ed, md])

    def test_controle_anti_robot_detecte(self):
        class R:
            status_code = 302
            headers = {"content-type": "text/plain"}
            def close(self): pass
        with tempfile.TemporaryDirectory() as t, mock.patch.object(ct, "DOSSIER_CACHE", Path(t)), mock.patch.object(ct._SESSION, "get", return_value=R()):
            (Path(t) / "a.json").write_text('{"tomes": {"1": [{"url": "u", "vignette": "v"}]}}')
            ct._MD_ETAT[0] = 0
            self.assertFalse(ct.mangadex_images_ok())
        ct._MD_ETAT[0] = 0
