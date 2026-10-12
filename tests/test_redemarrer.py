"""Bouton « 🔄 Redémarrer l'appli » : prévient d'un travail en cours, puis s'envoie un arrêt normal (systemd relance)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flask import Flask  # noqa: E402
import redemarrer  # noqa: E402


class RedemarrerTest(unittest.TestCase):
    def _client(self, occupe):
        app = Flask(__name__)
        redemarrer.init_app(app, occupe)
        return app.test_client()

    def test_occupe_puis_force(self):
        c = self._client(lambda: ["téléchargement"])
        with mock.patch.object(redemarrer.threading, "Thread") as t:
            r = c.post("/api/redemarrer", json={})
            self.assertEqual((r.status_code, r.json["occupe"]), (409, ["téléchargement"]))
            t.assert_not_called()
            r = c.post("/api/redemarrer", json={"forcer": True})
            self.assertTrue(r.json["ok"])
            t.assert_called_once()

    def test_arret_normal(self):
        c = self._client(None)
        with mock.patch.object(redemarrer.threading, "Thread") as t:
            c.post("/api/redemarrer", json={})
        cible = t.call_args.kwargs["target"]
        with mock.patch.object(redemarrer.time, "sleep"), mock.patch.object(redemarrer.os, "kill") as kill, \
                mock.patch.object(redemarrer.os, "_exit"):
            cible()
        self.assertEqual(kill.call_args.args[1], redemarrer.signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
