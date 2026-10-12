"""✂️ Découpage d'une intégrale en un seul fichier : à la main (premières pages) ou d'après le sommaire index.json."""
import io
import json
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import decoupage  # noqa: E402
import tomes_cbz  # noqa: E402
from PIL import Image  # noqa: E402


def _jpeg(c):
    b = io.BytesIO()
    Image.new("RGB", (20, 30), (c, 0, 0)).save(b, "JPEG")
    return b.getvalue()


class DecoupageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self.tmp.name) / "Buyuden"
        self.dossier.mkdir()
        self.f = self.dossier / "Buyuden.cbz"
        index = {"chapters": {
            "a": {"name": "Tome 1 - Chapitre 1 : Début", "entries": "00000000_0001\\d{4}"},
            "b": {"name": "Tome 1 - Chapitre 2 : Suite", "entries": "00000000_0002\\d{4}"},
            "c": {"name": "Tome 2 - Chapitre 3 : Fin", "entries": "00000000_0003\\d{4}"}}}
        with zipfile.ZipFile(self.f, "w") as z:
            z.writestr("00000000_00000000.jpg", _jpeg(1))
            for ch in (1, 2, 3):
                for p in range(2):
                    z.writestr(f"00000000_000{ch}000{p}.jpg", _jpeg(10 * ch + p))
            z.writestr("index.json", json.dumps(index))

    def tearDown(self):
        self.tmp.cleanup()

    def _attendre(self):
        for _ in range(200):
            if not decoupage.etat(self.f).get("en_cours"):
                return
            time.sleep(0.02)

    def test_plan_index(self):
        plan = decoupage.plan_index(self.f)
        self.assertEqual([(c["tome"], c["num"], c["titre"], c["pages"]) for c in plan],
                         [(1, 1.0, "Début", [1, 2]), (1, 2.0, "Suite", [3, 4]), (2, 3.0, "Fin", [5, 6])])
        self.assertEqual(decoupage.debuts_depuis_plan(plan), {1: 1, 2: 5})

    def test_decoupage_avec_chapitres(self):
        plan = decoupage.plan_index(self.f)
        decoupage.decouper(self.f, self.dossier, "Buyuden", {1: 1, 2: 5}, plan)
        self._attendre()
        t1 = tomes_cbz.fichier_tome(self.dossier, "Buyuden", 1)
        self.assertEqual([(c["num"], c["titre"]) for c in tomes_cbz.chapitres(t1)], [(1.0, "Début"), (2.0, "Suite")])
        self.assertTrue(self.f.exists())                       # l'original n'est jamais modifié

    def test_decoupage_a_la_main(self):
        decoupage.decouper(self.f, self.dossier, "Buyuden", {1: 0, 2: 4})
        self._attendre()
        with zipfile.ZipFile(tomes_cbz.fichier_tome(self.dossier, "Buyuden", 2)) as z:
            self.assertEqual(len(z.namelist()), 3)
        with zipfile.ZipFile(tomes_cbz.fichier_tome(self.dossier, "Buyuden", 1)) as z:
            self.assertEqual(len(z.namelist()), 4)


if __name__ == "__main__":
    unittest.main()
