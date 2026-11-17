"""✂️ Rognage manuel, routes : tailles des pages, brouillon borné et oublié quand le tome change, jamais d'écriture sans pages à rogner."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image


def faire_cbz(chemin, nb=3):
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_STORED) as z:
        for i in range(1, nb + 1):
            out = io.BytesIO()
            Image.new("L", (300, 500), 230).save(out, "PNG")
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

    def _get(self, route, **q):
        with self.A.app.test_request_context(route, query_string=q):
            rep = getattr(self.A, {"/api/rogner/infos": "api_rogner_infos", "/api/rogner/image": "api_rogner_image"}[route])()
        return rep if isinstance(rep, tuple) else (rep, rep.status_code)

    def _post(self, route, corps):
        with self.A.app.test_request_context(route, method="POST", json=corps):
            rep = getattr(self.A, {"/api/rogner/brouillon": "api_rogner_brouillon", "/api/rogner/appliquer": "api_rogner_appliquer"}[route])()
        return rep if isinstance(rep, tuple) else (rep, 200)

    def test_infos_donne_les_tailles_et_pas_de_brouillon_au_depart(self):
        rep, code = self._get("/api/rogner/infos", series="Serie", fichier=self.cbz.name)
        self.assertEqual(code, 200)
        d = rep.get_json()
        self.assertEqual(d["tailles"], [[300, 500]] * 3)
        self.assertIsNone(d["brouillon"])

    def test_tome_ou_serie_inconnus(self):
        self.assertEqual(self._get("/api/rogner/infos", series="Serie", fichier="autre.cbz")[1], 404)
        self.assertEqual(self._get("/api/rogner/infos", series="Autre", fichier=self.cbz.name)[1], 404)
        self.assertEqual(self._get("/api/rogner/image", series="Serie", fichier="autre.cbz", n="0")[1], 404)

    def test_brouillon_borne_garde_puis_oublie_quand_le_tome_change(self):
        brouillon = {"W": 1e9, "H": 700, "pages": {"0": {"x": 12.4, "y": "7", "a": 99, "ok": True}, "9": {"x": 1, "y": 1, "a": 0, "ok": True}, "x": {}, "1": {"exclue": True}},
                     "defaut": {"0": {"x": 5, "y": 6, "a": -50}, "2": {"x": 1, "y": 1}}}
        rep, code = self._post("/api/rogner/brouillon", {"series": "Serie", "fichier": self.cbz.name, "brouillon": brouillon})
        self.assertEqual(code, 200)
        d = self._get("/api/rogner/infos", series="Serie", fichier=self.cbz.name)[0].get_json()["brouillon"]
        self.assertEqual(d["W"], 20000)                                               # borné
        self.assertEqual(sorted(d["pages"]), ["0", "1"])                              # page 9 (hors tome) et « x » jetées
        self.assertEqual(d["pages"]["0"]["a"], 10)                                    # angle borné
        self.assertTrue(d["pages"]["1"]["exclue"])
        self.assertEqual(sorted(d["defaut"]), ["0"])                                  # seules les parités 0 et 1 existent
        self.assertEqual(d["defaut"]["0"]["a"], -10)
        faire_cbz(self.cbz, nb=4)                                                      # le tome change (une page de plus) : les numéros ne valent plus
        self.assertIsNone(self._get("/api/rogner/infos", series="Serie", fichier=self.cbz.name)[0].get_json()["brouillon"])

    def test_appliquer_sans_page_valide_refuse_et_ne_touche_a_rien(self):
        avant = self.cbz.read_bytes()
        for boites in ({}, {"0": {"x": 0, "y": 0, "w": 10, "h": 10}}, {"x": {"x": 0, "y": 0, "w": 300, "h": 500}}):          # vide, trop petite, numéro invalide
            rep, code = self._post("/api/rogner/appliquer", {"series": "Serie", "fichier": self.cbz.name, "boites": boites})
            self.assertEqual(code, 400)
        self.assertEqual(self.cbz.read_bytes(), avant)


if __name__ == "__main__":
    unittest.main()
