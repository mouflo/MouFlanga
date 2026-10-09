"""Doublons rangés à la main : « Ne rien faire » ferme la demande, et une paire disparue ou refusée ne revient plus."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class DoublonsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root = t / "mangas"
        for chemin in ("Serie/Tome 07/Serie - Tome 07.cbz", "Serie/Tome 07/Serie-copie - Tome 07.cbz"):
            (self._fichier(chemin)).write_bytes(b"x" * 10)
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        self.A = A
        A.MANGA_DIR = self.root
        A.DOUBLONS_IGNORES = t / "ignores.json"
        A.torrents._ETAT["fichier"] = t / "torrents.json"
        self.envois = []
        import notifier
        self.patch = mock.patch.object(notifier, "envoyer", side_effect=lambda txt, *a, **k: self.envois.append(txt))
        self.patch.start()

    def _fichier(self, chemin):
        f = self.root / chemin
        f.parent.mkdir(parents=True, exist_ok=True)
        return f

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def paire(self):
        return [(self.root / "Serie/Tome 07/Serie-copie - Tome 07.cbz", self.root / "Serie/Tome 07/Serie - Tome 07.cbz", 7)]

    def taches(self):
        return [j for j in self.A.torrents._lire() if j.get("manuel")]

    def test_signale_une_fois(self):
        self.A._signaler_doublons("Serie", self.paire())
        self.A._signaler_doublons("Serie", self.paire())
        self.assertEqual(len(self.taches()), 1)
        self.assertEqual(len(self.envois), 1)

    def test_ne_rien_faire_ferme_et_ne_revient_plus(self):
        self.A._signaler_doublons("Serie", self.paire())
        j = self.taches()[0]
        import auth
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        client = self.A.app.test_client()
        with client.session_transaction() as sess:
            sess["u"], sess["f"] = "test", auth._fingerprint()
        with mock.patch.object(self.A.auth, "role", return_value="admin"):
            rep = client.post("/api/torrents/decider", json={"id": j["id"], "remplacer": "ignorer"})
        self.assertTrue(rep.get_json()["ok"], rep.get_json())
        self.assertEqual(self.taches()[0]["etat"], "fini")
        self.A._signaler_doublons("Serie", self.paire())
        self.assertEqual(len(self.envois), 1)                 # pas de nouvelle notification
        self.assertEqual([x for x in self.taches() if x["etat"] == "a_valider"], [])

    def test_paire_disparue_ignoree(self):
        (self.root / "Serie/Tome 07/Serie-copie - Tome 07.cbz").unlink()
        self.A._signaler_doublons("Serie", self.paire())
        self.assertEqual(self.taches(), [])
        self.assertEqual(self.envois, [])


if __name__ == "__main__":
    unittest.main()
