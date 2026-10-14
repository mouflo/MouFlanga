"""Conversion .cbr → .cbz dans la bibliothèque : fichier seul et fichier partagé par qBittorrent (lien physique)."""
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class ConvertirSerieTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root = t / "mangas"
        for n in ("01", "02"):
            d = self.root / "Serie" / f"Tome {n}"
            d.mkdir(parents=True)
            with zipfile.ZipFile(d / f"Serie - Tome {n}.cbr", "w") as z:
                z.writestr("001.jpg", b"un" + n.encode())
                z.writestr("002.jpg", b"deux")
        (t / "torrent").mkdir()
        os.link(self.root / "Serie" / "Tome 02" / "Serie - Tome 02.cbr", t / "torrent" / "t02.cbr")   # « partagé »
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        self.A = A
        A.MANGA_DIR = self.root

    def tearDown(self):
        self.tmp.cleanup()

    def test_fichier_seul(self):
        f = self.root / "Serie" / "Tome 01" / "Serie - Tome 01.cbr"
        cible = self.A._convertir_un_cbr(f)
        self.assertEqual(cible.suffix, ".cbz")
        self.assertTrue(cible.exists() and not f.exists())
        with zipfile.ZipFile(cible) as z:
            self.assertEqual(z.read("001.jpg"), b"un01")

    def test_fichier_partage(self):
        f = self.root / "Serie" / "Tome 02" / "Serie - Tome 02.cbr"
        cible = self.A._convertir_un_cbr(f)
        self.assertTrue(cible.exists() and not f.exists())
        self.assertEqual(sorted(p.name for p in cible.parent.iterdir()), ["Serie - Tome 02.cbz"])
        self.assertTrue((Path(self.tmp.name) / "torrent" / "t02.cbr").exists())      # le torrent n'est pas touché


if __name__ == "__main__":
    unittest.main()
