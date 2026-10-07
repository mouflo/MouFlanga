"""🧲 Torrents : badges, chemins, copie par lien physique, suivi jusqu'à l'import (qBittorrent simulé)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import torrents  # noqa: E402


class FauxQbit:
    def __init__(self, infos): self.infos, self.appels = infos, []
    def info(self, **p): return self.infos
    def appel(self, chemin, **data): self.appels.append((chemin, data))


class TorrentsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.t = Path(self.tmp.name)
        torrents._ETAT["fichier"] = self.t / "torrents.json"
        self._env = dict(os.environ)
        os.environ.update(TORRENTS_OK="/ok", TORRENTS_CHEMINS="")

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env); self.tmp.cleanup()

    def test_mot_de_passe_avec_caracteres_speciaux(self):
        import base64
        os.environ["QBIT_PASSWORD_B64"] = base64.b64encode('a"b$c`d\\e'.encode()).decode()
        self.assertEqual(torrents.reglages()["qbit_mdp"], 'a"b$c`d\\e')

    def test_badges_et_chemins(self):
        b = torrents.badges("Air Gear T01-T37 Integrale FRENCH CBZ Digital")
        self.assertEqual(b, ["🇫🇷 FR", "Digital", "Intégrale", "T1–37"])
        os.environ["TORRENTS_CHEMINS"] = "/downloads=>/mnt/nas/Downloads"
        self.assertEqual(torrents.chemin_local("/downloads/Mouflanga.NOK/x"), Path("/mnt/nas/Downloads/Mouflanga.NOK/x"))

    def test_suivi_jusqu_a_l_import(self):
        nok = self.t / "NOK" / "Air Gear [FR]"; (nok / "sub").mkdir(parents=True)
        (nok / "sub" / "Air Gear T01.cbz").write_bytes(b"x"); (nok / "lisezmoi.exe").write_bytes(b"x")
        torrents._ecrire([{"id": "abc", "titre": "Air Gear FR", "serie": "Air Gear", "etat": "telechargement"}])
        biblio, importes, messages = self.t / "mangas", [], []
        q = FauxQbit([{"progress": 0.5, "state": "downloading"}])
        torrents.traiter(q, torrents._lire(), None, messages.append, biblio)
        self.assertEqual(torrents._lire()[0]["progression"], 50)
        q = FauxQbit([{"progress": 1, "hash": "h1", "content_path": str(nok), "state": "uploading"}])
        torrents.traiter(q, torrents._lire(), lambda s, c: importes.append((s, c)) or "1 tome", messages.append, biblio)
        copie = biblio / "Air Gear" / "sub" / "Air Gear T01.cbz"
        self.assertTrue(copie.exists()); self.assertFalse((biblio / "Air Gear" / "lisezmoi.exe").exists())
        self.assertEqual(os.stat(copie).st_ino, os.stat(nok / "sub" / "Air Gear T01.cbz").st_ino)   # lien physique
        self.assertEqual(importes[0][0], "Air Gear")
        self.assertEqual(q.appels, [("torrents/setLocation", {"hashes": "h1", "location": "/ok"})])
        self.assertEqual(torrents._lire()[0]["etat"], "fini"); self.assertIn("importé", messages[0])


if __name__ == "__main__":
    unittest.main()
