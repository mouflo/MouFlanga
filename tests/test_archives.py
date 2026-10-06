"""Lecture des archives (ZIP/CBR), tri des pages, chemins piégés.
Lancer : python3 -m unittest discover -s tests (Flask et Pillow doivent être installés)."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import archives  # noqa: E402


def _zip(path, names):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, b"\xff\xd8\xff" + n.encode())


class ArchivesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tri_naturel_des_pages(self):
        f = self.dir / "c.cbz"
        _zip(f, ["10.jpg", "2.jpg", "1.jpg", "11.jpg", "notes.txt", "__MACOSX/1.jpg", "dossier/.cache.jpg"])
        self.assertEqual(archives.pages(f), ["1.jpg", "2.jpg", "10.jpg", "11.jpg"])

    def test_cbr_qui_est_un_zip(self):
        f = self.dir / "c.cbr"
        _zip(f, ["a/1.png", "a/2.png"])
        self.assertEqual(len(archives.pages(f)), 2)
        data, mime = archives.read_page(f, 1)
        self.assertEqual(mime, "image/png")
        self.assertIn(b"a/2.png", data)

    def test_page_hors_limites(self):
        f = self.dir / "c.cbz"
        _zip(f, ["1.jpg"])
        for n in (-1, 1, 99):
            with self.assertRaises(archives.ArchiveError):
                archives.read_page(f, n)

    def test_format_inconnu(self):
        f = self.dir / "faux.cbz"
        f.write_bytes(b"ceci n'est pas une archive")
        with self.assertRaises(archives.ArchiveError):
            archives.pages(f)

    def test_cache_suit_les_modifications(self):
        f = self.dir / "c.cbz"
        _zip(f, ["1.jpg"])
        self.assertEqual(len(archives.pages(f)), 1)
        _zip(f, ["1.jpg", "2.jpg"])
        os.utime(f, (1, 1))
        self.assertEqual(len(archives.pages(f)), 2)

    def test_rar_sans_module_message_clair(self):
        f = self.dir / "r.cbr"
        f.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 20)
        try:
            import rarfile  # noqa: F401
            self.skipTest("rarfile installé : le cas « module absent » ne peut pas être testé")
        except ImportError:
            pass
        with self.assertRaises(archives.ArchiveError) as cm:
            archives.pages(f)
        self.assertIn("rarfile", str(cm.exception))


class CheminsTest(unittest.TestCase):
    def test_chemin_hors_dossier_refuse(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "mangas"
            (root / "S").mkdir(parents=True)
            _zip(root / "S" / "c.cbz", ["1.jpg"])
            (Path(t) / "secret.cbz").write_bytes(b"x")
            os.environ["MANGA_DIR"] = str(root)
            os.environ.pop("APP_USER", None)
            for mod in ("app",):
                sys.modules.pop(mod, None)
            import app as A
            self.assertIsNotNone(A._safe_path("S/c.cbz"))
            self.assertIsNone(A._safe_path("../secret.cbz"))
            self.assertIsNone(A._safe_path("/etc/passwd"))
            self.assertIsNone(A._safe_path("S/../../secret.cbz"))
            (root / "S" / "note.txt").write_text("x")
            self.assertIsNone(A._safe_path("S/note.txt"))
            os.symlink(Path(t) / "secret.cbz", root / "S" / "lien.cbz")
            self.assertIsNone(A._safe_path("S/lien.cbz"))


if __name__ == "__main__":
    unittest.main()
