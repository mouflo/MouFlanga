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

    def test_la_liste_des_tomes_dit_lesquels_sont_deja_rognes(self):
        import edition
        import traitements
        with self.A.app.test_request_context("/rogner", query_string={"id": "Serie"}):
            avant = self.A.page_rogner()
        self.assertNotIn("rogné", avant)
        racine = Path(self.tmp.name)
        infos = edition.lire(racine / "Serie")
        traitements.noter(infos, self.cbz.name, self.cbz.stat().st_size, self.cbz.stat().st_size, {"rognage": {"detail": "3 page(s) rognée(s) à la main"}}, date="2026-11-17")
        edition.ecrire(racine / "Serie", infos)
        with self.A.app.test_request_context("/rogner", query_string={"id": "Serie"}):
            apres = self.A.page_rogner()
        self.assertIn("rogné le 17/11/2026", apres)
        self.assertIn("3 page(s) rognée(s) à la main", apres)

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

    def test_appliquer_refuse_des_tailles_differentes_et_ne_touche_a_rien(self):
        avant = self.cbz.read_bytes()
        boites = {"0": {"x": 0, "y": 0, "w": 200, "h": 300, "a": 0}, "1": {"x": 0, "y": 0, "w": 210, "h": 300, "a": 0}}        # deux pages simples, deux tailles
        rep, code = self._post("/api/rogner/appliquer", {"series": "Serie", "fichier": self.cbz.name, "boites": boites})
        self.assertEqual(code, 400)
        self.assertIn("même taille", rep.get_json()["error"])
        boites = {"0": {"x": 0, "y": 0, "w": 200, "h": 300, "a": 0}, "1": {"x": 0, "y": 0, "w": 200, "h": 320, "a": 0}}        # une hauteur différente
        self.assertEqual(self._post("/api/rogner/appliquer", {"series": "Serie", "fichier": self.cbz.name, "boites": boites})[1], 400)
        self.assertEqual(self.cbz.read_bytes(), avant)

    def test_la_reference_de_la_serie_est_rendue_aux_autres_tomes_de_meme_resolution(self):
        d = self.A._rognages_lire()
        d["__reference__"] = {"Serie": {"W": 250, "H": 450, "pw": 300, "ph": 500, "defaut": {"0": {"x": 10, "y": 5, "a": 0}}, "tome": "Serie - Tome 02.cbz"}}
        self.A._rognages_ecrire(d)
        ref = self._get("/api/rogner/infos", series="Serie", fichier=self.cbz.name)[0].get_json()["reference"]
        self.assertEqual((ref["W"], ref["H"]), (250, 450))                              # ce tome a la même résolution : il reprend la taille
        d["__reference__"]["Serie"]["pw"] = 600                                         # tome de l'autre résolution : la même taille en pixels n'aurait pas de sens
        self.A._rognages_ecrire(d)
        self.assertIsNone(self._get("/api/rogner/infos", series="Serie", fichier=self.cbz.name)[0].get_json()["reference"])
        d["__reference__"]["Serie"].update(pw=300, tome=self.cbz.name)                  # la référence est ce tome lui-même : rien à reprendre
        self.A._rognages_ecrire(d)
        self.assertIsNone(self._get("/api/rogner/infos", series="Serie", fichier=self.cbz.name)[0].get_json()["reference"])


if __name__ == "__main__":
    unittest.main()
