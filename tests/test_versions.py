"""↩️ Retour aux versions d'avant : retrouver les anciennes versions à la corbeille, la plus ancienne = l'origine, remise en place sans risque."""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import versions  # noqa: E402


def _cbz(chemin: Path, contenu: bytes, ecrit: float):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(chemin, "w") as z:
        z.writestr("001.jpg", contenu)
    os.utime(chemin, (ecrit, ecrit))
    return chemin


class VersionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.m = Path(self.tmp.name)
        self.tome = _cbz(self.m / "Nori Taka" / "Tome 01" / "Nori Taka - Tome 01.cbz", b"ACTUEL", 3000)
        c = self.m / ".corbeille"
        self.origine = _cbz(c / "2026-11-16" / "Nori Taka" / "Tome 01" / "Nori Taka - Tome 01.cbz.avant", b"ORIGINE", 1000)
        self.milieu = _cbz(c / "2026-11-16" / "Nori Taka" / "Tome 01" / "Nori Taka - Tome 01.cbz (1794829825).avant", b"MILIEU", 2000)
        _cbz(c / "2026-11-16" / "Nori Taka" / "Tome 02" / "Nori Taka - Tome 02.cbz.avant", b"AUTRE TOME", 500)      # un autre tome : ignoré
        (c / "2026-11-16" / "Nori Taka" / "Tome 01" / "Nori Taka - Tome 01.cbz (1794829999).avant").write_bytes(b"pas un zip")   # abîmé : ignoré

    def tearDown(self):
        self.tmp.cleanup()

    def test_nom_de_base(self):
        self.assertEqual(versions.nom_de_base("Tome 01.cbz.avant"), "Tome 01.cbz")
        self.assertEqual(versions.nom_de_base("Tome 01.cbz (1794829825).avant"), "Tome 01.cbz")
        self.assertEqual(versions.nom_de_base("Tome 01 (1794829825).cbz"), "Tome 01.cbz")
        self.assertEqual(versions.nom_de_base("Tome 01.cbz"), "Tome 01.cbz")
        self.assertEqual(versions.nom_de_base("Tome (2024).cbz"), "Tome (2024).cbz")       # une année entre parenthèses n'est pas un horodatage

    def test_la_plus_ancienne_est_l_origine_et_le_reste_est_ignore(self):
        vs = versions.versions_gardees(self.m, ".corbeille", self.tome)
        self.assertEqual([v["chemin"] for v in vs], [self.origine, self.milieu])
        self.assertEqual(versions.versions_gardees(self.m, ".corbeille", self.m / "Nori Taka" / "Tome 09" / "Nori Taka - Tome 09.cbz"), [])
        self.assertEqual(versions.versions_gardees(self.m, ".absente", self.tome), [])

    def test_est_meme(self):
        v = versions.versions_gardees(self.m, ".corbeille", self.tome)[0]
        self.assertFalse(versions.est_meme(self.tome, v))
        shutil.copy2(self.origine, self.tome)
        self.assertTrue(versions.est_meme(self.tome, v))

    def test_restaurer_remet_la_version_et_garde_l_actuelle_a_la_corbeille(self):
        rangees = []

        def vers_corbeille(p):
            dest = self.m / ".corbeille" / "2026-11-17" / p.relative_to(self.m)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest))
            rangees.append(dest)
        versions.restaurer(self.tome, self.origine, vers_corbeille)
        with zipfile.ZipFile(self.tome) as z:
            self.assertEqual(z.read("001.jpg"), b"ORIGINE")
        with zipfile.ZipFile(rangees[0]) as z:
            self.assertEqual(z.read("001.jpg"), b"ACTUEL")             # la version d'avant la restauration est à la corbeille
        self.assertTrue(self.origine.is_file())                       # la copie de la corbeille reste là
        self.assertEqual([p.name for p in self.tome.parent.iterdir()], [self.tome.name])      # aucun fichier temporaire oublié

    def test_version_abimee_ou_corbeille_en_panne_ne_touchent_pas_au_tome(self):
        mauvais = self.m / ".corbeille" / "2026-11-16" / "Nori Taka" / "Tome 01" / "Nori Taka - Tome 01.cbz (1794829999).avant"
        with self.assertRaises(ValueError):
            versions.restaurer(self.tome, mauvais, lambda p: self.fail("le tome ne doit pas partir à la corbeille"))
        with zipfile.ZipFile(self.tome) as z:
            self.assertEqual(z.read("001.jpg"), b"ACTUEL")

        def panne(p):
            raise OSError("corbeille pleine")
        with self.assertRaises(OSError):
            versions.restaurer(self.tome, self.origine, panne)
        with zipfile.ZipFile(self.tome) as z:
            self.assertEqual(z.read("001.jpg"), b"ACTUEL")
        self.assertEqual([p.name for p in self.tome.parent.iterdir()], [self.tome.name])


if __name__ == "__main__":
    unittest.main()
