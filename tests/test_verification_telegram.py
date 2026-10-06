"""Tests hors-ligne : alertes Telegram et vérification Cloudflare manuelle (aucun Internet requis)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifier
import japscan_scraper as js

TOKEN = "123456789:" + "A" * 35


class NotifierTest(unittest.TestCase):
    def test_formes(self):
        self.assertTrue(notifier.token_valide(TOKEN))
        self.assertFalse(notifier.token_valide("n'importe quoi"))
        self.assertTrue(notifier.chat_valide("123456789"))
        self.assertTrue(notifier.chat_valide("-1001234567890"))
        self.assertFalse(notifier.chat_valide("abc"))

    def test_jeton_masque_dans_les_erreurs(self):
        import requests
        erreur = requests.ConnectionError(f"HTTPSConnectionPool: /bot{TOKEN}/sendMessage")
        with mock.patch("notifier.requests.post", side_effect=erreur):
            ok, msg = notifier.envoyer("x", TOKEN, "123456789")
        self.assertFalse(ok)
        self.assertNotIn(TOKEN, msg)

    def test_non_configure(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}):
            self.assertFalse(notifier.configure())
            ok, _ = notifier.envoyer("x")
            self.assertFalse(ok)

    def test_indice_ne_montre_pas_le_jeton(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN}):
            self.assertNotIn(TOKEN, notifier.indice_token())
            self.assertTrue(notifier.indice_token().endswith(TOKEN[-4:]))

    def test_detection_identifiant(self):
        rep = {"ok": True, "result": [{"message": {"chat": {"id": 42, "type": "private"}}}]}
        with mock.patch("notifier._appel", return_value=(True, rep)):
            self.assertEqual(notifier.detecter_chat(TOKEN), (True, "42"))
        with mock.patch("notifier._appel", return_value=(True, {"ok": True, "result": []})):
            self.assertFalse(notifier.detecter_chat(TOKEN)[0])


class VerificationTest(unittest.TestCase):
    def test_aucune_verification(self):
        self.assertFalse(js.verif_etat()["actif"])
        with self.assertRaises(RuntimeError):
            js.verif_capture()
        with self.assertRaises(RuntimeError):
            js.verif_clic(10, 10)

    def test_titre_defi(self):
        self.assertTrue(js._titre_defi("Un instant…"))
        self.assertTrue(js._titre_defi("Just a moment..."))
        self.assertTrue(js._titre_defi(""))
        self.assertFalse(js._titre_defi("Dandadan - Lecture en ligne | Japscan"))

    def test_alerte_une_seule_fois(self):
        js._VERIF["alerte"] = 0.0
        with mock.patch("notifier.envoyer", return_value=(True, "ok")) as envoi:
            js._alerter_telegram("https://x/")
            js._alerter_telegram("https://x/")
        self.assertEqual(envoi.call_count, 1)
        js._VERIF["alerte"] = 0.0


class RoutesTest(unittest.TestCase):
    def setUp(self):
        import app as A
        self.A = A
        A.app.config["TESTING"] = True
        self.client = A.app.test_client()

    def _connecte(self):
        # Si la connexion est activée sur la machine de test, on s'identifie par la session
        with self.client.session_transaction() as s:
            s["user"] = "test"

    def test_routes_enregistrees(self):
        regles = {r.rule for r in self.A.app.url_map.iter_rules()}
        for r in ("/verification", "/api/japscan/verif/etat", "/api/japscan/verif/capture",
                  "/api/japscan/verif/clic", "/api/settings/telegram"):
            self.assertIn(r, regles)

    def test_telegram_validation(self):
        import settings_page  # noqa: F401
        c = self.client
        r = c.post("/api/settings/telegram", json={"action": "save", "token": "pas-un-jeton"})
        if r.status_code in (301, 302, 401):
            self.skipTest("connexion activée : routes protégées")
        self.assertEqual(r.status_code, 400)
        r = c.post("/api/settings/telegram", json={"action": "save", "chat_id": "abc"})
        self.assertEqual(r.status_code, 400)
        r = c.post("/api/settings/telegram", json={"action": "save", "app_url": "ftp://x"})
        self.assertEqual(r.status_code, 400)

    def test_clic_sans_verification(self):
        c = self.client
        r = c.post("/api/japscan/verif/clic", json={"x": 10, "y": 10})
        if r.status_code in (301, 302, 401):
            self.skipTest("connexion activée : routes protégées")
        self.assertEqual(r.status_code, 409)
        r = c.post("/api/japscan/verif/clic", json={"x": "abc", "y": 1})
        self.assertEqual(r.status_code, 400)
        r = c.get("/api/japscan/verif/capture")
        self.assertEqual(r.status_code, 409)


if __name__ == "__main__":
    unittest.main()
