"""Alertes Telegram dans un sujet de groupe (message_thread_id), sans toucher au vrai Telegram."""
import os
import unittest
from unittest import mock

import notifier

TOKEN = "123456789:" + "A" * 35


class TestSujet(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "-1001234567890"})
        self._env.start()
        os.environ.pop("TELEGRAM_THREAD_ID", None)

    def tearDown(self):
        self._env.stop()

    def test_validation(self):
        self.assertTrue(notifier.thread_valide("4"))
        self.assertFalse(notifier.thread_valide("abc"))
        self.assertFalse(notifier.thread_valide(""))

    def test_sans_sujet_comportement_inchange(self):
        with mock.patch.object(notifier, "_appel", return_value=(True, {})) as a:
            notifier.envoyer("salut")
        self.assertNotIn("message_thread_id", a.call_args[0][2])

    def test_avec_sujet(self):
        os.environ["TELEGRAM_THREAD_ID"] = "7"
        with mock.patch.object(notifier, "_appel", return_value=(True, {})) as a:
            notifier.envoyer("salut")
        self.assertEqual(a.call_args[0][2]["message_thread_id"], 7)
        self.assertEqual(a.call_args[0][2]["chat_id"], "-1001234567890")

    def test_sujet_vide_force_aucun(self):
        os.environ["TELEGRAM_THREAD_ID"] = "7"
        with mock.patch.object(notifier, "_appel", return_value=(True, {})) as a:
            notifier.envoyer("salut", thread_id="")
        self.assertNotIn("message_thread_id", a.call_args[0][2])

    def test_detection_du_sujet(self):
        maj = {"result": [
            {"message": {"chat": {"type": "private", "id": 5}}},
            {"message": {"chat": {"type": "supergroup", "id": -1009}, "message_thread_id": 12, "is_topic_message": True}},
            {"message": {"chat": {"type": "supergroup", "id": -1009}}},   # sujet « Général » : pas de numéro
        ]}
        with mock.patch.object(notifier, "_appel", return_value=(True, maj)):
            self.assertEqual(notifier.detecter_groupe(TOKEN), (True, "-1009", "12", ""))
        with mock.patch.object(notifier, "_appel", return_value=(True, {"result": []})):
            ok, _c, _t, err = notifier.detecter_groupe(TOKEN)
        self.assertFalse(ok)
        self.assertIn("administrateur", err)


if __name__ == "__main__":
    unittest.main()


class LienEtWebhookTest(unittest.TestCase):
    def test_lien_de_message(self):
        self.assertEqual(notifier.lire_lien("https://t.me/c/1234567890/45/678"), (True, "-1001234567890", "45", ""))
        self.assertEqual(notifier.lire_lien("t.me/c/1234567890/678"), (True, "-1001234567890", "678", ""))
        self.assertFalse(notifier.lire_lien("https://exemple.fr/x")[0])

    def test_webhook_explique(self):
        with mock.patch("notifier._appel", return_value=(False, "Conflict: can't use getUpdates method while webhook is active")):
            ok, msg = notifier.detecter_chat("123456789:" + "A" * 35)
        self.assertFalse(ok)
        self.assertIn("Jeedom", msg)

    def test_sujet_general_pas_precise(self):
        with mock.patch("notifier._appel", return_value=(True, {})) as appel:
            notifier.envoyer("x", "123456789:" + "A" * 35, "-1001", "1")
        self.assertNotIn("message_thread_id", appel.call_args[0][2])
