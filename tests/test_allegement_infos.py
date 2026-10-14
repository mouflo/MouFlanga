"""🪶 + 📝 : l'allègement d'une série écrit aussi les infos du tome (route /api/optimiser avec « infos »)."""
import io
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _jpeg(seed):
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 255, size=(1200, 800), dtype=np.uint8)
    b = io.BytesIO()
    Image.fromarray(a, "L").save(b, "JPEG", quality=97)
    return b.getvalue()


class AllegementInfosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "mangas"
        for n in (1, 2):
            d = self.root / "Serie" / f"Tome {n:02d}"
            d.mkdir(parents=True)
            with zipfile.ZipFile(d / f"Serie - Tome {n:02d}.cbz", "w") as z:
                for i in range(4):
                    z.writestr(f"{i:03d}.jpg", _jpeg(n * 10 + i))
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        import auth
        self.A, self.auth = A, auth
        self._role = auth.role
        auth.role = lambda: "admin"
        A.MANGA_DIR = self.root
        A._scan_invalider()
        self.c = A.app.test_client()

    def tearDown(self):
        self.auth.role = self._role
        self.tmp.cleanup()

    def _lancer(self, **kw):
        r = self.c.post("/api/optimiser", json=dict({"series": "Serie", "appliquer": True, "largeur": "800"}, **kw))
        self.assertTrue(r.get_json().get("ok"), r.get_json())
        import optimiser
        for _ in range(600):
            if not optimiser.etat("Serie").get("en_cours"):
                break
            time.sleep(0.05)
        return optimiser.etat("Serie")

    def test_avec_infos(self):
        etat = self._lancer(infos=True)
        self.assertTrue(all(l.get("infos") for l in etat["rapport"]), etat["rapport"])
        for n in (1, 2):
            f = self.root / "Serie" / f"Tome {n:02d}" / f"Serie - Tome {n:02d}.cbz"
            with zipfile.ZipFile(f) as z:
                self.assertIn("ComicInfo.xml", z.namelist())
                self.assertIn("MouFlanga", z.read("ComicInfo.xml").decode())     # la ligne « MouFlanga: … » des Notes

    def test_sans_infos(self):
        etat = self._lancer(infos=False)
        self.assertFalse(any(l.get("infos") for l in etat["rapport"]))
        f = self.root / "Serie" / "Tome 01" / "Serie - Tome 01.cbz"
        self.assertNotIn("ComicInfo.xml", zipfile.ZipFile(f).namelist())


if __name__ == "__main__":
    unittest.main()
