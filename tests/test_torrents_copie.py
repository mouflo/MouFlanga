"""Fichiers d'un torrent rangés dans MouFlanga : vraie copie par défaut (indépendante du torrent), lien physique si décoché."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import torrents  # noqa: E402


class CopieTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name) / "torrent" / "Gantz T01.cbz"
        self.src.parent.mkdir()
        self.src.write_bytes(b"contenu")
        self.cible = Path(self.tmp.name) / "MouFlanga" / "Gantz" / "Tome 01" / "Gantz - Tome 01.cbz"

    def tearDown(self):
        self.tmp.cleanup()

    def test_copie_par_defaut(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TORRENTS_COPIE", None)
            torrents.lier(self.src, self.cible)
        self.assertEqual(self.cible.read_bytes(), b"contenu")
        self.assertEqual(self.cible.stat().st_nlink, 1)             # indépendant : effacer le torrent ne change rien
        self.src.unlink()
        self.assertEqual(self.cible.read_bytes(), b"contenu")
        self.assertEqual([p.name for p in self.cible.parent.iterdir()], ["Gantz - Tome 01.cbz"])   # pas de copie temporaire

    def test_lien_si_decoche(self):
        with mock.patch.dict(os.environ, {"TORRENTS_COPIE": "0"}):
            torrents.lier(self.src, self.cible)
        self.assertEqual(self.cible.stat().st_nlink, 2)


if __name__ == "__main__":
    unittest.main()
