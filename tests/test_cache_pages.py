"""Une page rendue par /api/page se revalide (ETag) : un tome réécrit ne montre jamais l'ancienne image mise en cache par le navigateur."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image


def faire_cbz(chemin, couleur):
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_STORED) as z:
        out = io.BytesIO()
        Image.new("RGB", (200, 300), couleur).save(out, "PNG")
        z.writestr("0001.png", out.getvalue())


class CachePagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MANGA_DIR"] = self.tmp.name
        racine = Path(self.tmp.name)
        (racine / "Serie").mkdir()
        self.cbz = racine / "Serie" / "Serie - Tome 01.cbz"
        faire_cbz(self.cbz, (255, 255, 255))
        sys.modules.pop("app", None)
        import app
        self.A = app
        self.patchs = [mock.patch.object(app, "MANGA_DIR", racine), mock.patch.object(app, "DATA_DIR", racine)]
        for p in self.patchs:
            p.start()

    def tearDown(self):
        for p in self.patchs:
            p.stop()
        self.tmp.cleanup()

    def _page(self, etag=None):
        h = {"If-None-Match": etag} if etag else {}
        with self.A.app.test_request_context("/api/page", query_string={"path": "Serie/Serie - Tome 01.cbz", "n": "0"}, headers=h):
            return self.A.api_page()

    def test_meme_fichier_304_fichier_reecrit_nouvelle_image(self):
        r1 = self._page()
        self.assertEqual(r1.status_code, 200)
        self.assertIn("no-cache", r1.headers["Cache-Control"])
        etag = r1.headers["ETag"]
        self.assertEqual(self._page(etag).status_code, 304)
        faire_cbz(self.cbz, (230, 180, 190))
        os.utime(self.cbz, ns=(self.cbz.stat().st_atime_ns, self.cbz.stat().st_mtime_ns + 5_000_000_000))
        r2 = self._page(etag)
        self.assertEqual(r2.status_code, 200)
        self.assertNotEqual(r2.headers["ETag"], etag)


if __name__ == "__main__":
    unittest.main()
