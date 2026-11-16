"""🖼 Couvertures : après une action sur un tome, la page se rouvre calée sur ce tome (pas tout en haut)."""
import os
import sys
import tempfile
import unittest


class AncreCouverturesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MANGA_DIR"] = self.tmp.name
        sys.modules.pop("app", None)
        import app
        self.A = app

    def tearDown(self):
        self.tmp.cleanup()

    def _retour(self, donnees, **kw):
        with self.A.app.test_request_context("/couvertures/envoyer", method="POST", data=donnees):
            return self.A._retour_couvertures("Nori Taka", **kw)

    def test_le_retour_vise_le_tome_modifie(self):
        rep = self._retour({"id": "Nori Taka", "tome": "14"}, ok="fait")
        self.assertTrue(rep.headers["Location"].endswith("#t14"), rep.headers["Location"])
        self.assertIn("ok=fait", rep.headers["Location"])

    def test_sans_tome_ou_tome_illisible_pas_d_ancre(self):
        for donnees in ({"id": "Nori Taka"}, {"id": "Nori Taka", "tome": "abc"}):
            self.assertNotIn("#", self._retour(donnees, erreur="x").headers["Location"])

    def test_chaque_ligne_de_tome_a_son_ancre(self):
        html = (os.path.join(os.path.dirname(__file__), "..", "templates", "couvertures.html"))
        self.assertIn('id="t{{ l.tome }}"', open(html, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
