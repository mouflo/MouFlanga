"""Alerte « redémarrage inattendu » (module commun redemarrage.py)."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redemarrage  # noqa: E402


class RedemarrageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.journal = self.dir / "j.log"
        self.journal.write_text("2026-10-06 - ERROR - Boum\n")
        self.envois = []
        patch = mock.patch.object(redemarrage.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda s: target()})())
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(redemarrage.signal, "signal")      # ne pas toucher au vrai SIGTERM des tests
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _demarrer(self):
        redemarrage.verifier(self.dir, "Essai", self.journal, self.envois.append)

    def test_arret_normal_rien(self):
        self._demarrer()
        (self.dir / "data" / "en-marche").unlink()               # arrêt propre
        self._demarrer()
        self.assertEqual(self.envois, [])

    def test_plantage(self):
        self._demarrer()
        self._demarrer()                                         # témoin resté : plantage
        self.assertIn("plantage", self.envois[0])
        self.assertIn("Boum", self.envois[0])

    def test_serveur_redemarre(self):
        self._demarrer()
        os.utime(self.dir / "data" / "en-marche", (0, 0))       # témoin plus ancien que le démarrage du serveur
        self._demarrer()
        self.assertIn("le serveur lui-même a redémarré", self.envois[0])

    def test_alerte_coupee(self):
        self._demarrer()
        (self.dir / "data" / "alerte-redemarrage-coupee").write_text("1")
        self._demarrer()
        self.assertEqual(self.envois, [])
