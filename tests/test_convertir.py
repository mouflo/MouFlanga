"""Conversion .cbr → .cbz : mêmes pages, vérifiées ; une copie ratée n'est jamais gardée."""
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import convertir  # noqa: E402


class ConvertirTest(unittest.TestCase):
    def test_zip_nomme_cbr(self):
        t = Path(tempfile.mkdtemp())
        src = t / "Tome 01.cbr"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("002.jpg", b"deux")
            z.writestr("001.jpg", b"un")
            z.writestr("ComicInfo.xml", "<ComicInfo/>")
            z.writestr("__MACOSX/._001.jpg", b"x")
        n = convertir.vers_cbz(src, t / "Tome 01.cbz")
        self.assertEqual(n, 2)
        with zipfile.ZipFile(t / "Tome 01.cbz") as z:
            self.assertEqual(sorted(z.namelist()), ["001.jpg", "002.jpg", "ComicInfo.xml"])
            self.assertEqual(z.read("001.jpg"), b"un")
        self.assertTrue(src.exists())                       # la source n'est jamais touchée ici

    def test_sans_image_refuse(self):
        t = Path(tempfile.mkdtemp())
        src = t / "a.cbr"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("notes.txt", b"rien")
        with self.assertRaises(RuntimeError):
            convertir.vers_cbz(src, t / "a.cbz")
        self.assertFalse((t / "a.cbz").exists())

    def test_vrai_rar(self):
        import shutil
        import subprocess
        import archives
        if not archives.rar_available() or not shutil.which("rar"):
            self.skipTest("pas d'outil pour fabriquer un RAR")
        t = Path(tempfile.mkdtemp())
        (t / "001.jpg").write_bytes(b"un")
        subprocess.run(["rar", "a", "-ep", str(t / "a.cbr"), str(t / "001.jpg")], check=True, capture_output=True)
        self.assertEqual(convertir.vers_cbz(t / "a.cbr", t / "a.cbz"), 1)


if __name__ == "__main__":
    unittest.main()
