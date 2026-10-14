"""Les tests ne doivent jamais envoyer de vrais messages (Telegram, notifications du téléphone)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notifier  # noqa: E402


class AucunEnvoiTest(unittest.TestCase):
    def test_pas_d_appel_reseau(self):
        self.assertTrue(notifier._en_test())
        with mock.patch.object(notifier.requests, "post") as post:
            ok, msg = notifier._appel("123:abc", "sendMessage", {"chat_id": "1", "text": "x"})
        self.assertFalse(ok)
        post.assert_not_called()

    def test_relais_non_appeles(self):
        vus = []
        notifier.RELAIS.append(vus.append)
        try:
            notifier.envoyer("bonjour", token="123:abc", chat_id="1", thread_id="")
        finally:
            notifier.RELAIS.remove(vus.append)
        self.assertEqual(vus, [])


if __name__ == "__main__":
    unittest.main()
