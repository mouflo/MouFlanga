"""Infos d'un tome écrites dans son ComicInfo.xml (résumé, notes) et relues."""
import tempfile
import unittest
import zipfile
from pathlib import Path

import signets


class InfosTomeFichierTest(unittest.TestCase):
    def test_ecrire_et_relire(self):
        t = Path(tempfile.mkdtemp())
        src = t / "a.cbz"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("001.jpg", b"x")
            z.writestr("002.jpg", b"y")
        infos = {"Title": "Romance Dawn", "Summary": "Un résumé.", "Notes": 'MouFlanga: {"v":1,"equipe":"X"}'}
        signets.ecrire(src, None, t / "b.cbz", infos)
        lu = signets.lire_infos(t / "b.cbz")
        self.assertEqual(lu["resume"], "Un résumé.")
        self.assertEqual(lu["titre"], "Romance Dawn")
        self.assertEqual(lu["notes"], {"v": 1, "equipe": "X"})
        # chapitres ajoutés ensuite : infos gardées, signets écrits
        signets.ecrire(t / "b.cbz", [{"num": 1, "titre": "A", "image": 0}], t / "c.cbz")
        self.assertEqual(signets.lire_infos(t / "c.cbz")["resume"], "Un résumé.")
        self.assertEqual(signets.lire(t / "c.cbz")[0]["titre"], "A")

    def test_notes_etrangeres_gardees(self):
        t = Path(tempfile.mkdtemp())
        src = t / "a.cbz"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("001.jpg", b"x")
            z.writestr("ComicInfo.xml", "<ComicInfo><Notes>Scan par X</Notes></ComicInfo>")
        signets.ecrire(src, None, t / "b.cbz", {"Notes": 'MouFlanga: {"v":1}'})
        with zipfile.ZipFile(t / "b.cbz") as z:
            self.assertIn("Scan par X", z.read("ComicInfo.xml").decode())
        self.assertEqual(signets.lire_infos(t / "b.cbz")["notes"], {"v": 1})


if __name__ == "__main__":
    unittest.main()
