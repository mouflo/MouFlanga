"""Rangement d'un tome à scans par chapitre (pages renommées + chapitres.json) : rien n'est perdu, le tome se déroule en chapitres."""
import tempfile
import unittest
import zipfile
from pathlib import Path

import signets
import tomes_cbz

CHAPITRES = [{"num": 1.0, "titre": "Un", "image": 2}, {"num": 2.0, "titre": "Deux", "image": 5}, {"num": 3.0, "titre": "", "image": 7}]


def _cbz(dossier: Path, nb=9) -> Path:
    f = dossier / "Serie - Tome 01.cbz"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("Serie 01/", b"")
        for i in range(1, nb + 1):
            z.writestr(f"Serie 01/{i:05d}.jpg", f"page{i}".encode())
    return f


class TestRanger(unittest.TestCase):
    def test_plan(self):
        noms = [f"p{i}.jpg" for i in range(9)]
        plan = signets.plan_chapitres(noms, CHAPITRES)
        self.assertEqual([(n, k) for _, n, k in plan][:4], [(0.0, 1), (0.0, 2), (1.0, 1), (1.0, 2)])
        self.assertEqual(sum(1 for _, n, _ in plan if n == 3.0), 2)          # les dernières pages restent au dernier chapitre

    def test_plan_refuse_ce_qui_n_est_pas_sur(self):
        noms = [f"p{i}.jpg" for i in range(9)]
        self.assertIsNone(signets.plan_chapitres(noms, [{"num": 1.0, "titre": "", "image": None}]))
        self.assertIsNone(signets.plan_chapitres(noms, [{"num": 1.0, "image": 4}, {"num": 2.0, "image": 4}]))
        self.assertIsNone(signets.plan_chapitres(noms, [{"num": 2.0, "image": 1}, {"num": 1.0, "image": 5}]))
        self.assertIsNone(signets.plan_chapitres(noms, [{"num": 1.0, "image": 40}]))
        self.assertIsNone(signets.plan_chapitres(noms, []))

    def test_ecrire_range_par_chapitre(self):
        with tempfile.TemporaryDirectory() as d:
            src = _cbz(Path(d))
            dest = Path(d) / "sortie.cbz"
            signets.ecrire(src, CHAPITRES, dest, {"Title": "Tome 1"}, ranger=("Serie", 1))
            self.assertEqual([(c["num"], c["nb"], c["titre"]) for c in tomes_cbz.chapitres(dest)],
                             [(0.0, 2, "Couverture et début"), (1.0, 3, "Un"), (2.0, 2, "Deux"), (3.0, 2, "")])
            with zipfile.ZipFile(dest) as z, zipfile.ZipFile(src) as o:
                self.assertEqual(z.read("c0001.00-p001.jpg"), o.read("Serie 01/00003.jpg"))
                self.assertEqual(z.read("c0003.00-p002.jpg"), o.read("Serie 01/00009.jpg"))
                self.assertIn("ComicInfo.xml", z.namelist())
            self.assertEqual(tomes_cbz.lire_info(dest)["tome"], 1)

    def test_sans_ranger_rien_ne_change(self):
        with tempfile.TemporaryDirectory() as d:
            src = _cbz(Path(d))
            dest = Path(d) / "sortie.cbz"
            signets.ecrire(src, CHAPITRES, dest, {"Title": "Tome 1"})
            self.assertIsNone(tomes_cbz.lire_info(dest))
            with zipfile.ZipFile(dest) as z:
                self.assertIn("Serie 01/00001.jpg", z.namelist())

    def test_ranger_refuse_un_plan_douteux(self):
        with tempfile.TemporaryDirectory() as d:
            src = _cbz(Path(d))
            with self.assertRaises(RuntimeError):
                signets.ecrire(src, [{"num": 1.0, "titre": "", "image": 99}], Path(d) / "x.cbz", None, ranger=("Serie", 1))
            self.assertFalse((Path(d) / "x.cbz").exists())


if __name__ == "__main__":
    unittest.main()
