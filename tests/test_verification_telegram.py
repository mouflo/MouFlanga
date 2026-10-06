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


class RepriseTest(unittest.TestCase):
    """MouFlanga reprend les réglages Telegram d'une autre appli du serveur."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self.tmp.name)
        autre = self.racine / "moufloster" / "data"
        autre.mkdir(parents=True)
        (autre / "secrets.env").write_text(f'TELEGRAM_BOT_TOKEN="{TOKEN}"\nTELEGRAM_CHAT_ID="987654321"\nAUTRE="x"\n')
        self.patchs = [mock.patch.object(notifier, "RACINE_APPLIS", self.racine),
                       mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""})]
        for p in self.patchs:
            p.start()
        notifier.vider_cache()

    def tearDown(self):
        for p in self.patchs:
            p.stop()
        notifier.vider_cache()
        self.tmp.cleanup()

    def test_reprise_env(self):
        self.assertTrue(notifier.configure())
        self.assertEqual(notifier.source_reprise(), "moufloster")
        self.assertEqual(notifier._chat(), "987654321")

    def test_valeurs_mal_formees_ignorees(self):
        (self.racine / "moufloster" / "data" / "secrets.env").write_text('TELEGRAM_BOT_TOKEN="pas-un-jeton"\nTELEGRAM_CHAT_ID="abc"\n')
        notifier.vider_cache()
        self.assertFalse(notifier.configure())

    def test_reprise_json(self):
        import json
        d = self.racine / "mouflopening" / "data"
        d.mkdir(parents=True)
        (d / "settings.json").write_text(json.dumps({"telegram": {"bot_token": TOKEN, "chat_id": 555666777}}))
        (self.racine / "moufloster" / "data" / "secrets.env").unlink()
        notifier.vider_cache()
        self.assertEqual(notifier.source_reprise(), "mouflopening")

    def test_cle_au_nom_inhabituel(self):
        """Le jeton est reconnu à sa forme, même si la clé s'appelle juste BOT_TOKEN."""
        f = self.racine / "moufloster" / "data" / "secrets.env"
        f.write_text(f'BOT_TOKEN="{TOKEN}"\nTG_CHAT="123456789"\n')
        notifier.vider_cache()
        self.assertEqual(notifier._token(), TOKEN)
        self.assertEqual(notifier._chat(), "123456789")

    def test_fichier_yaml(self):
        d = self.racine / "mouflanimexer" / "config"
        d.mkdir(parents=True)
        (d / "app.yml").write_text(f"notifications:\n  telegram_token: {TOKEN}\n  telegram_chat_id: 424242424\n")
        (self.racine / "moufloster" / "data" / "secrets.env").unlink()
        notifier.vider_cache()
        self.assertEqual(notifier.source_reprise(), "mouflanimexer")
        self.assertEqual(notifier._chat(), "424242424")

    def test_jeton_sans_identifiant(self):
        (self.racine / "moufloster" / "data" / "secrets.env").write_text(f'BOT_TOKEN="{TOKEN}"\n')
        notifier.vider_cache()
        self.assertTrue(notifier.configure())
        self.assertEqual(notifier._chat(), "")
        with mock.patch("notifier.detecter_chat", return_value=(True, "777888999")), \
             mock.patch("notifier._appel", return_value=(True, {"ok": True})) as appel:
            ok, _ = notifier.envoyer("x")
        self.assertTrue(ok)
        self.assertEqual(appel.call_args[0][2]["chat_id"], "777888999")

    def test_diagnostic_sans_valeur_secrete(self):
        texte = "\n".join(notifier.diagnostic())
        self.assertNotIn(TOKEN, texte)
        self.assertIn("moufloster", texte)
        self.assertIn("…" + TOKEN[-4:], texte)

    def test_diagnostic_aucun_resultat(self):
        (self.racine / "moufloster" / "data" / "secrets.env").write_text("AUTRE=1\n")
        notifier.vider_cache()
        texte = "\n".join(notifier.diagnostic())
        self.assertIn("Aucun jeton Telegram trouvé", texte)

    def test_reglages_perso_prioritaires(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "1" * 9 + ":" + "B" * 35, "TELEGRAM_CHAT_ID": "111222333"}):
            self.assertEqual(notifier.source_reprise(), "")
            self.assertEqual(notifier._chat(), "111222333")


class VerificationTest(unittest.TestCase):
    def test_aucune_verification(self):
        self.assertFalse(js.verif_etat()["actif"])
        with self.assertRaises(RuntimeError):
            js.verif_capture()
        with self.assertRaises(RuntimeError):
            js.verif_clic(10, 10)

    def test_historique_limite(self):
        js._HISTORIQUE.clear()
        for i in range(40):
            js._noter(f"événement {i}")
        h = js.verif_historique()
        self.assertEqual(len(h), 60)
        self.assertIn("événement 39", h[-1])
        js._HISTORIQUE.clear()

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
