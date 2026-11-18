"""✂️ Rognage à la main, routes : infos sur les pages d'origine, réglages gardés, application en arrière-plan puis seules les pages modifiées réécrites."""
import io
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image


def faire_cbz(chemin, nb=3):
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_STORED) as z:
        for i in range(1, nb + 1):
            out = io.BytesIO()
            im = Image.new("L", (300, 500), 200 + i)
            im.paste(20, (40 * i, 60, 40 * i + 90, 200))                        # un dessin : chaque cadre donne une image différente
            im.save(out, "PNG")
            z.writestr(f"{i:04d}.png", out.getvalue())


class RoutesRognerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MANGA_DIR"] = self.tmp.name
        racine = Path(self.tmp.name)
        (racine / "Serie" / "Tome 01").mkdir(parents=True)
        self.cbz = racine / "Serie" / "Tome 01" / "Serie - Tome 01.cbz"
        faire_cbz(self.cbz)
        (racine / "data").mkdir()
        self.racine = racine
        sys.modules.pop("app", None)
        import app
        self.A = app
        self.patchs = [mock.patch.object(app, "_scan", return_value={"Serie": [self.cbz]}), mock.patch.object(app, "MANGA_DIR", racine),
                       mock.patch.object(app, "DATA_DIR", racine / "data")]       # jamais les vraies données
        for p in self.patchs:
            p.start()

    def tearDown(self):
        for p in self.patchs:
            p.stop()
        self.tmp.cleanup()

    def _get(self, fonction, route, **q):
        with self.A.app.test_request_context(route, query_string=q):
            rep = getattr(self.A, fonction)()
        return rep if isinstance(rep, tuple) else (rep, getattr(rep, "status_code", 200))

    def _post(self, fonction, corps):
        with self.A.app.test_request_context("/", method="POST", json=corps):
            rep = getattr(self.A, fonction)()
        return rep if isinstance(rep, tuple) else (rep, 200)

    def infos(self):
        rep, code = self._get("api_rogner_infos", "/api/rogner/infos", series="Serie", fichier=self.cbz.name)
        self.assertEqual(code, 200)
        return rep.get_json()

    def attendre(self):
        import optimiser
        for _ in range(200):
            if not optimiser.coupes_etat("Serie").get("en_cours"):
                return optimiser.coupes_etat("Serie")
            time.sleep(0.05)
        self.fail("rognage jamais terminé")

    def test_infos_au_depart(self):
        d = self.infos()
        self.assertEqual(d["tailles"], [[300, 500]] * 3)
        self.assertEqual(d["boites"], {})
        self.assertIsNone(d["produit"])
        self.assertFalse(d["origine"])

    def test_tome_ou_serie_inconnus(self):
        self.assertEqual(self._get("api_rogner_infos", "/api/rogner/infos", series="Serie", fichier="autre.cbz")[1], 404)
        self.assertEqual(self._get("api_rogner_infos", "/api/rogner/infos", series="Autre", fichier=self.cbz.name)[1], 404)
        self.assertEqual(self._get("api_rogner_image", "/api/rogner/image", series="Serie", fichier="autre.cbz", n="0")[1], 404)
        self.assertEqual(self._post("api_rogner_sauver", {"series": "Serie", "fichier": "x.cbz", "boites": {}})[1], 404)

    def test_reglages_gardes_et_bornes(self):
        corps = {"series": "Serie", "fichier": self.cbz.name, "W": 250, "H": 400,
                 "boites": {"0": {"x": 10, "y": 20, "w": 250, "h": 400, "a": 0.5}, "9": {"x": 0, "y": 0, "w": 50, "h": 50}, "1": {"x": 0, "y": 0, "w": 2, "h": 2}}}
        self.assertEqual(self._post("api_rogner_sauver", corps)[1], 200)
        d = self.infos()
        self.assertEqual(sorted(d["boites"]), ["0"])                                 # page hors du tome et cadre minuscule jetés
        self.assertEqual((d["W"], d["H"]), (250, 400))
        self.assertEqual(self._post("api_rogner_sauver", dict(corps, boites="x"))[1], 400)

    def test_appliquer_puis_ne_reecrire_que_la_page_modifiee(self):
        b = {"x": 10, "y": 20, "w": 250, "h": 400, "a": 0}
        self._post("api_rogner_sauver", {"series": "Serie", "fichier": self.cbz.name, "W": 250, "H": 400, "boites": {"0": b}})
        v = self._post("api_rogner_appliquer", {"series": "Serie", "fichier": self.cbz.name, "verifier": True})[0].get_json()
        self.assertEqual((v["ecrire"], v["garder"], v["non_reglees"], v["W"], v["H"]), (3, 0, 2, 250, 400))
        self.assertTrue(self.cbz.exists())
        rep, code = self._post("api_rogner_appliquer", {"series": "Serie", "fichier": self.cbz.name})
        self.assertEqual(code, 200, rep.get_json())
        e = self.attendre()
        self.assertFalse(any("erreur" in str(x.get("note", "")) for x in e.get("rapport", [])), e)
        with zipfile.ZipFile(self.cbz) as z:
            noms = sorted(z.namelist())
            tailles = [Image.open(io.BytesIO(z.read(n))).size for n in noms]
            avant = [z.read(n) for n in noms]
        self.assertEqual(tailles, [(250, 400)] * 3)
        d = self.infos()
        self.assertTrue(d["origine"])
        self.assertEqual(d["tailles"], [[300, 500]] * 3)                               # on règle sur les pages d'origine gardées
        self.assertTrue((self.racine / ".rognage" / "Serie" / self.cbz.name).is_file())
        v = self._post("api_rogner_appliquer", {"series": "Serie", "fichier": self.cbz.name, "verifier": True})[0].get_json()
        self.assertEqual(v["ecrire"], 0)
        self.assertEqual(self._post("api_rogner_appliquer", {"series": "Serie", "fichier": self.cbz.name})[1], 400)   # rien à écrire
        boites = dict(d["boites"])
        boites["2"] = {"x": 0, "y": 0, "w": 200, "h": 500, "a": 0}
        self._post("api_rogner_sauver", {"series": "Serie", "fichier": self.cbz.name, "W": 250, "H": 400, "boites": boites})
        self.assertEqual(self._post("api_rogner_appliquer", {"series": "Serie", "fichier": self.cbz.name})[1], 200)
        self.attendre()
        with zipfile.ZipFile(self.cbz) as z:
            apres = [z.read(n) for n in sorted(z.namelist())]
        self.assertEqual([a == b for a, b in zip(avant, apres)], [True, True, False])
        with self.A.app.test_request_context("/rogner", query_string={"id": "Serie"}):
            html = self.A.page_rogner()
        self.assertIn("rogné le", html)

    def test_repartir_oublie_les_reglages(self):
        self._post("api_rogner_sauver", {"series": "Serie", "fichier": self.cbz.name, "W": None, "H": None, "boites": {"0": {"x": 1, "y": 1, "w": 200, "h": 300, "a": 0}}})
        self.assertEqual(self._post("api_rogner_repartir", {"series": "Serie", "fichier": self.cbz.name})[1], 200)
        self.assertEqual(self.infos()["boites"], {})

    def test_page_editeur_et_liste(self):
        with self.A.app.test_request_context("/rogner", query_string={"id": "Serie", "fichier": self.cbz.name}):
            html = self.A.page_rogner()
        self.assertIn("rgCadre", html)
        with self.A.app.test_request_context("/rogner", query_string={"id": "Serie"}):
            html = self.A.page_rogner()
        self.assertIn(self.cbz.name.replace(" ", "%20"), html)


if __name__ == "__main__":
    unittest.main()
