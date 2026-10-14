"""🎨 Apparence : validation du CSS, couleurs, assemblage de /skin.css, comptes et brouillons."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apparence as A


class CssTest(unittest.TestCase):
    def test_accepte_variables_et_images_du_skin(self):
        self.assertIsNone(A.verifier_css(":root{--bg:#fff} .x{background:url(/ui/skins/a/b.jpg)} .y{background:url(\"data:image/png;base64,AAA\")}"))

    def test_refuse_import_et_adresses_externes(self):
        for css in ("@import url('x.css');", "a{background:url(http://x/y.png)}", "a{background:url(//x/y.png)}",
                    "</style><script>", "a{background:url(javascript:alert(1))}", "a{width:expression(1)}",
                    "a{background:\\75 rl(http://x/y)}", "@IMPORT 'x';"):
            self.assertIsNotNone(A.verifier_css(css), css)

    def test_commentaire_ne_cache_rien_et_taille(self):
        self.assertIsNone(A.verifier_css("/* @import oublié */ a{color:red}"))
        self.assertIsNotNone(A.verifier_css("a{}" * 60000))


class CouleursTest(unittest.TestCase):
    def test_filtre(self):
        self.assertEqual(A.couleurs_valides({"accent": "#FF0000", "fond": "rouge", "x": "#000000", "texte": "#12345"}), {"accent": "#ff0000"})

    def test_css(self):
        self.assertEqual(A.css_couleurs({}), "")
        css = A.css_couleurs({"accent": "#ff0000", "fond": "#ffffff"})
        self.assertIn("--accent: #ff0000", css)
        self.assertIn("--bg: #ffffff", css)
        self.assertIn("color-scheme: light", css)
        self.assertNotIn("--card", css)                       # rien d'autre n'est touché


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        A.DATA_DIR = t / "data"
        A.SKINS_DIR = t / "skins"
        (A.SKINS_DIR / "sakura").mkdir(parents=True)
        (A.SKINS_DIR / "sakura" / "skin.css").write_text(":root{--accent:#ff69b4}", encoding="utf-8")
        (A.SKINS_DIR / "sakura" / "skin.json").write_text('{"nom":"Sakura","auteur":"Copain"}', encoding="utf-8")
        (A.SKINS_DIR / "mauvais").mkdir()
        (A.SKINS_DIR / "mauvais" / "skin.css").write_text("@import 'http://x/y.css';", encoding="utf-8")
        from flask import Flask
        self.app = Flask(__name__)
        import auth
        self.auth = auth
        self._role, self._util = auth.role, auth.utilisateur
        self.qui = ["admin", None]
        auth.role = lambda: self.qui[0]
        auth.utilisateur = lambda: self.qui[1]
        A.init_app(self.app)
        self.c = self.app.test_client()

    def tearDown(self):
        self.auth.role, self.auth.utilisateur = self._role, self._util
        self.tmp.cleanup()

    def test_defaut_vide_et_choix(self):
        self.assertEqual(self.c.get("/skin.css").data, b"")
        r = self.c.post("/api/apparence", json={"skin": "sakura", "couleurs": {"accent": "#00ff00"}})
        self.assertTrue(r.get_json()["ok"])
        css = self.c.get("/skin.css").data.decode()
        self.assertIn("--accent:#ff69b4", css)
        self.assertLess(css.index("#ff69b4"), css.index("#00ff00"))        # les couleurs choisies passent en dernier
        self.assertEqual(self.c.get("/skin.css?off=1").data, b"")

    def test_skin_invalide_ignore(self):
        self.c.post("/api/apparence", json={"skin": "mauvais"})
        self.assertEqual(self.c.get("/skin.css").data, b"")              # skin présent mais refusé à la lecture
        r = self.c.post("/api/apparence", json={"skin": "n-existe-pas"})
        self.assertEqual(r.status_code, 400)

    def test_par_compte(self):
        self.c.post("/api/apparence", json={"skin": "sakura"})
        self.qui = ["lecteur", "copain"]
        self.assertEqual(self.c.get("/skin.css").data, b"")
        self.qui = ["admin", None]
        self.assertIn("ff69b4", self.c.get("/skin.css").data.decode())

    def test_personne_de_connecte(self):
        self.qui = [None, None]
        self.assertEqual(self.c.get("/skin.css").data, b"")
        self.assertEqual(self.c.get("/api/apparence").status_code, 401)

    def test_brouillon_prive(self):
        self.qui = ["lecteur", "copain"]
        r = self.c.post("/api/apparence/brouillon", json={"nom": "Mon Essai", "css": ":root{--bg:#222}"})
        self.assertTrue(r.get_json()["ok"])
        ident = r.get_json()["id"]
        self.assertEqual(ident, "perso:mon-essai")
        self.assertTrue(self.c.post("/api/apparence", json={"skin": ident}).get_json()["ok"])
        self.assertIn("--bg:#222", self.c.get("/skin.css").data.decode())
        self.qui = ["admin", None]                                           # l'admin ne voit pas le brouillon d'un autre
        self.assertNotIn(ident, [s["id"] for s in self.c.get("/api/apparence").get_json()["skins"]])
        bad = self.c.post("/api/apparence/brouillon", json={"nom": "x", "css": "@import 'a';"})
        self.assertEqual(bad.status_code, 400)

    def test_secours_reset(self):
        self.c.post("/api/apparence", json={"skin": "sakura"})
        self.assertEqual(self.c.get("/apparence/reset").status_code, 302)
        self.assertEqual(self.c.get("/skin.css").data, b"")


if __name__ == "__main__":
    unittest.main()
