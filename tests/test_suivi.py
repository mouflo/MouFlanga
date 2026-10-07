"""Séries suivies : une série supprimée n'est plus suivie."""
import tempfile
import unittest
from pathlib import Path

import suivi


class RetirerTest(unittest.TestCase):
    def test_retirer(self):
        with tempfile.TemporaryDirectory() as t:
            ancien = suivi._ETAT["fichier"]
            suivi._ETAT["fichier"] = Path(t) / "suivies.json"
            try:
                suivi.ajouter("Beelzebub Side Story")
                suivi.ajouter("Gintama")
                self.assertTrue(suivi.retirer("Beelzebub Side Story"))
                self.assertFalse(suivi.retirer("Beelzebub Side Story"))
                self.assertEqual(list(suivi.lire()["series"]), ["Gintama"])
            finally:
                suivi._ETAT["fichier"] = ancien


if __name__ == "__main__":
    unittest.main()
