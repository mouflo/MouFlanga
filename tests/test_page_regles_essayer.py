"""Page Règles, onglet 🧪 Essayer : rappelle les préférences en une phrase, comme la page Télécharger."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class PageReglesEssayerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MANGA_DIR"] = str(Path(self.tmp.name) / "mangas")
        sys.modules.pop("app", None)
        import app as A
        import auth
        import regles
        self.A, self.regles = A, regles
        self.ancien = regles.FICHIER
        regles.FICHIER = Path(self.tmp.name) / "regles.json"
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        self.client = A.app.test_client()
        with self.client.session_transaction() as sess:
            sess["u"], sess["f"] = "test", auth._fingerprint()
        self.role = mock.patch.object(A.auth, "role", return_value="admin")
        self.role.start()

    def tearDown(self):
        self.role.stop()
        self.regles.FICHIER = self.ancien
        self.tmp.cleanup()

    def test_sans_preferences_enregistrees_on_propose_de_les_regler(self):
        html = self.client.get("/regles?onglet=tester").get_data(as_text=True)
        self.assertIn("Régler mes préférences", html)
        self.assertNotIn("Tes préférences :", html)

    def test_avec_preferences_la_phrase_est_en_tete_de_l_onglet(self):
        import regles_simples
        regles_simples.enregistrer({"pdf": True})
        html = self.client.get("/regles?onglet=tester").get_data(as_text=True)
        self.assertIn("Tes préférences :", html)
        self.assertIn(regles_simples.phrase(regles_simples.etat()["prefs"]).replace("'", "&#39;"), html)
        self.assertLess(html.index("Tes préférences :"), html.index('id="tq"'))       # avant le champ de recherche

    def test_les_autres_onglets_ne_montrent_pas_la_phrase_de_l_essai(self):
        import regles_simples
        regles_simples.enregistrer({})
        html = self.client.get("/regles?onglet=formats").get_data(as_text=True)
        self.assertNotIn('id="tq"', html)


if __name__ == "__main__":
    unittest.main()
