"""📱 Notifications téléphone : clés créées une fois, abonnements par compte et par sujet, appareil disparu oublié."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import push  # noqa: E402

SUB = {"endpoint": "https://push.exemple/abc", "keys": {"p256dh": "x", "auth": "y"}}


class PushTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        push._ETAT["dossier"] = Path(self.tmp.name)

    def tearDown(self):
        push._ETAT["dossier"] = None
        self.tmp.cleanup()

    def test_cle_creee_une_fois(self):
        a = push.cle_publique()
        self.assertEqual(a, push.cle_publique())
        self.assertGreater(len(a), 60)
        self.assertEqual(oct((Path(self.tmp.name) / "vapid.json").stat().st_mode)[-3:], "600")

    def test_abonnement_et_sujets(self):
        push.abonner("lecteur:lea", SUB, ["demandes", "inconnu"])
        self.assertEqual(push.abonnement("lecteur:lea", SUB["endpoint"])["sujets"], ["demandes"])
        with self.assertRaises(ValueError):
            push.abonner("lecteur:lea", {"endpoint": "http://pas-https"}, [])
        push.desabonner("lecteur:lea", SUB["endpoint"])
        self.assertIsNone(push.abonnement("lecteur:lea", SUB["endpoint"]))

    def test_envoi_filtre_et_appareil_disparu(self):
        push.cle_publique()
        push.abonner("admin", SUB, ["alertes"])
        push.abonner("lecteur:lea", dict(SUB, endpoint="https://push.exemple/lea"), ["nouveaux"])
        import pywebpush
        envoyes = []
        def faux(sub, data, **k):
            envoyes.append((sub["endpoint"], json.loads(data)["texte"]))
            if sub["endpoint"].endswith("lea"):
                raise pywebpush.WebPushException("parti", response=mock.Mock(status_code=410))
        with mock.patch.object(pywebpush, "webpush", side_effect=faux):
            push.envoyer(None, "nouveaux", "T", "Nouveau tome", "/")
            for _ in range(100):
                if envoyes and push.abonnement("lecteur:lea", "https://push.exemple/lea") is None:
                    break
                time.sleep(0.02)
        self.assertEqual(envoyes, [("https://push.exemple/lea", "Nouveau tome")])
        self.assertIsNone(push.abonnement("lecteur:lea", "https://push.exemple/lea"))


if __name__ == "__main__":
    unittest.main()
