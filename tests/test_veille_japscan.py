"""Veille de l'extension Japscan : message seulement quand le dernier commit change, jamais au premier passage, panne dite et non cachée."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reseau  # noqa: E402
import veille_japscan as V  # noqa: E402


class VeilleJapscanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = {"d": {}}
        self.patches = [mock.patch.object(V, "FICHIER", Path(self.tmp.name) / "v.json"),
                        mock.patch.object(V, "LIRE", lambda f, defaut: dict(self.base["d"])),
                        mock.patch.object(V, "ECRIRE", lambda f, d: self.base.update(d=dict(d)))]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        self.addCleanup(self.tmp.cleanup)
        self.messages = []

    def _commit(self, sha, titre="Mise à jour"):
        return mock.patch.object(V, "dernier_commit", return_value={"sha": sha, "titre": titre, "date": "2026-11-03", "lien": "https://x/y"})

    def test_premier_passage_sans_message(self):
        with self._commit("a"):
            V.verifier(self.messages.append)
        self.assertEqual(self.messages, [])
        self.assertEqual(V.etat()["dernier"], "a")

    def test_message_quand_le_commit_change_une_seule_fois(self):
        with self._commit("a"):
            V.verifier(self.messages.append)
        with self._commit("b", "Nouveau site"):
            V.verifier(self.messages.append)
            V.verifier(self.messages.append)
        self.assertEqual(len(self.messages), 1)
        self.assertIn("Nouveau site", self.messages[0])

    def test_panne_de_github_ne_change_rien(self):
        with self._commit("a"):
            V.verifier(self.messages.append)
        with mock.patch.object(V, "dernier_commit", side_effect=reseau.Panne("github", "hors service")):
            msg = V.verifier(self.messages.append)
        self.assertIn("n'a pas répondu", msg)
        self.assertEqual(V.etat()["dernier"], "a")
        self.assertEqual(self.messages, [])

    def test_option_decochee_gardee(self):
        V.regler(False)
        self.assertFalse(V.etat()["actif"])


if __name__ == "__main__":
    unittest.main()
