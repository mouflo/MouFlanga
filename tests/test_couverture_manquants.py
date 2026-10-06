"""Couverture choisie, chapitres manquants et nom des séries Japscan."""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import japscan_scraper as js  # noqa: E402


def _cbz(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("1.jpg", b"x")


def _image(couleur=(200, 30, 30), taille=(300, 450)):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", taille, couleur).save(b, "PNG")
    return b.getvalue()


class TitreSerieTest(unittest.TestCase):
    def test_numero_du_dernier_chapitre_retire(self):
        self.assertEqual(js.titre_serie("Dandadan 247", "https://x/manga/dandadan/247/"), "Dandadan")
        self.assertEqual(js.titre_serie("One Piece 1100.5", "https://x/manga/one-piece/1100.5/"), "One Piece")

    def test_titre_sans_numero_inchange(self):
        self.assertEqual(js.titre_serie("Kaiju n°8", "https://x/manga/kaiju-8/"), "Kaiju n°8")
        self.assertEqual(js.titre_serie("2001 Nights", ""), "2001 Nights")
        self.assertEqual(js.titre_serie("Blue Lock 364", "https://x/manga/blue-lock/12/"), "Blue Lock 364")


class AppliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root = t / "mangas"
        for n in (1, 2, 3, 6, 9, 10):
            _cbz(self.root / "Serie" / f"{n:03d} - Chapitre {n} Titre.cbz")
        _cbz(self.root / "Dandadan 247" / "001 - Chapitre 1 Début.cbz")
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        self.A = A
        A.MANGA_DIR = self.root
        A.PROGRESS_FILE = t / "progress.json"
        A.PROGRESS_FILE.write_text(json.dumps({"Dandadan 247": {"current": "Dandadan 247/001 - Chapitre 1 Début.cbz",
                                                                 "read": ["Dandadan 247/001 - Chapitre 1 Début.cbz"]}}))
        self._env = {k: os.environ.get(k) for k in ("APP_USER", "APP_PASSWORD_HASH")}
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        self.client = A.app.test_client()
        import auth
        with self.client.session_transaction() as sess:
            sess["u"], sess["f"] = "test", auth._fingerprint()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_chapitres_manquants(self):
        r = self.client.get("/api/series?id=Serie").json
        self.assertEqual(r["manquants"], ["4–5", "7–8"])
        self.assertEqual((r["premier"], r["dernier"]), (1, 10))

    def test_numero_lu_dans_les_noms(self):
        n = self.A._numero_chapitre
        self.assertEqual(n("003 - ​Chapitre 3 La vieille"), 3)
        self.assertEqual(n("Chap. 12,5 - bonus"), 12.5)
        self.assertEqual(n("045 sans mot"), 45)
        self.assertIsNone(n("Prologue"))

    def test_couverture_choisie_puis_automatique(self):
        r = self.client.post("/api/cover/choisir", data={"id": "Serie", "image": (io.BytesIO(_image()), "photo.png")},
                             content_type="multipart/form-data")
        self.assertTrue(r.json["ok"], r.json)
        cover = self.root / "Serie" / "cover.jpg"
        self.assertTrue(cover.is_file())
        self.assertTrue(self.client.get("/api/series?id=Serie").json["cover_perso"])
        self.assertEqual(self.client.get("/api/cover?id=Serie").data, cover.read_bytes())
        # Une deuxième couverture : l'ancienne part à la corbeille
        self.client.post("/api/cover/choisir", data={"id": "Serie", "image": (io.BytesIO(_image((0, 0, 200))), "b.png")},
                         content_type="multipart/form-data")
        self.assertEqual(len(list((self.root / ".corbeille").rglob("cover*.jpg"))), 1)
        self.assertTrue(self.client.post("/api/cover/automatique", json={"id": "Serie"}).json["ok"])
        self.assertFalse(cover.exists())
        self.assertFalse(self.client.get("/api/series?id=Serie").json["cover_perso"])

    def test_couverture_refusee(self):
        r = self.client.post("/api/cover/choisir", data={"id": "Serie", "image": (io.BytesIO(b"pas une image"), "x.png")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/cover/choisir", data={"id": "../x", "image": (io.BytesIO(_image()), "x.png")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 404)

    def test_ancien_dossier_renomme_avec_la_progression(self):
        dossier = self.A._dossier_serie("Dandadan")   # titre tel que donné par la liste du site
        self.assertEqual(dossier, self.root / "Dandadan")
        self.assertTrue((self.root / "Dandadan" / "001 - Chapitre 1 Début.cbz").is_file())
        self.assertFalse((self.root / "Dandadan 247").exists())
        p = json.loads(self.A.PROGRESS_FILE.read_text())
        self.assertEqual(p["Dandadan"]["read"], ["Dandadan/001 - Chapitre 1 Début.cbz"])
        self.assertEqual(p["Dandadan"]["current"], "Dandadan/001 - Chapitre 1 Début.cbz")

    def test_chapitres_deja_telecharges(self):
        chapitres = [{"title": "Chapitre 1 Début", "chapter_id": "1"}, {"title": "Chapitre 2 Suite", "chapter_id": "2"}]
        marques = self.A._marquer_deja(chapitres, "Dandadan")
        self.assertEqual([c["deja"] for c in marques], [True, False])


if __name__ == "__main__":
    unittest.main()


class CleApiTest(AppliTest):
    """Accès de MouFloster (ou d'une autre appli) avec la clé API générée dans les Réglages."""

    def setUp(self):
        super().setUp()
        import api_externe
        self.api = api_externe
        self._cles = {k: os.environ.get(k) for k in ("MOUFLANGA_CLE_API_SHA256", "MOUFLANGA_CLE_API_FIN")}
        api_externe._ECHECS.clear()
        from unittest import mock
        patcher = mock.patch("api_externe.write_secret")     # ne pas toucher au vrai data/secrets.env
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cle = self.client.post("/api/settings/cle-api", json={"action": "generer"}).json["cle"]
        self.externe = self.A.app.test_client()               # sans session : comme une autre appli

    def tearDown(self):
        for k, v in self._cles.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def test_cle_jamais_redonnee(self):
        etat = self.client.get("/api/settings/cle-api").json
        self.assertTrue(etat["configured"])
        self.assertEqual(etat["hint"], "…" + self.cle[-4:])
        self.assertNotIn(self.cle, json.dumps(etat))
        self.assertNotEqual(os.environ["MOUFLANGA_CLE_API_SHA256"], self.cle)

    def test_liste_et_envoi_avec_la_cle(self):
        r = self.externe.get("/api/externe/series", headers={"X-Cle-API": self.cle})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Serie", [s["name"] for s in r.json["series"]])
        r = self.externe.post("/api/externe/couverture", headers={"X-Cle-API": self.cle},
                              data={"id": "Serie", "image": (io.BytesIO(_image()), "p.png")}, content_type="multipart/form-data")
        self.assertTrue(r.json["ok"], r.json)
        self.assertTrue((self.root / "Serie" / "cover.jpg").is_file())
        r = self.externe.get("/api/externe/couverture?id=Serie", headers={"X-Cle-API": self.cle})
        self.assertEqual(r.data, (self.root / "Serie" / "cover.jpg").read_bytes())

    def test_sans_cle_ou_mauvaise_cle(self):
        self.assertEqual(self.externe.get("/api/externe/series").status_code, 401)
        self.assertEqual(self.externe.get("/api/externe/series", headers={"X-Cle-API": "mauvaise"}).status_code, 401)
        # Les autres routes restent derrière l'écran de connexion, même avec la clé
        self.assertEqual(self.externe.get("/api/series?id=Serie", headers={"X-Cle-API": self.cle}).status_code, 401)

    def test_blocage_apres_trop_d_essais(self):
        for _ in range(10):
            self.externe.get("/api/externe/series", headers={"X-Cle-API": "mauvaise"})
        self.assertEqual(self.externe.get("/api/externe/series", headers={"X-Cle-API": self.cle}).status_code, 429)

    def test_cle_supprimee(self):
        self.client.post("/api/settings/cle-api", json={"action": "supprimer"})
        self.assertEqual(self.externe.get("/api/externe/series", headers={"X-Cle-API": self.cle}).status_code, 403)
