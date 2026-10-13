"""Index de la bibliothèque : parcours incrémental, SQLite, détection des changements, mémoire des fiches."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import indexation  # noqa: E402


def _cbz(chemin: Path, contenu=b"x"):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self.tmp.name) / "mangas"
        _cbz(self.racine / "Alpha" / "Tome 01" / "Alpha - Tome 01.cbz", b"1234")
        _cbz(self.racine / "Alpha" / "Tome 02" / "Alpha - Tome 02.cbz", b"12345")
        _cbz(self.racine / "Beta" / "Beta T01.cbz")
        _cbz(self.racine / "Beta" / ".cache" / "caché.cbz")
        _cbz(self.racine / "seul.cbz")
        self.base = Path(self.tmp.name) / "index.sqlite"
        self.garder = lambda p: p.suffix == ".cbz" and not p.name.startswith(".")

    def tearDown(self):
        self.tmp.cleanup()

    def _parcours(self, fichiers=None, dossiers=None):
        return indexation.parcourir(self.racine, self.garder, self.garder, fichiers or {}, dossiers or {})

    def test_series_tailles_et_dossiers_caches(self):
        fichiers, dossiers, vrac = self._parcours()
        self.assertEqual(sorted(fichiers), ["Alpha", "Beta"])
        self.assertEqual({c for c, _, _ in fichiers["Beta"]}, {"Beta/Beta T01.cbz"})        # le dossier « .cache » est ignoré
        self.assertEqual(dict((c, t) for c, t, _ in fichiers["Alpha"])["Alpha/Tome 02/Alpha - Tome 02.cbz"], 5)
        self.assertEqual([c for c, _, _ in vrac], ["seul.cbz"])
        self.assertIn("Alpha/Tome 01", dossiers)

    def test_dossier_inchange_ne_relit_pas_les_fichiers(self):
        fichiers, dossiers, _ = self._parcours()
        faux = {s: [(c, 999, m) for c, _, m in lst] for s, lst in fichiers.items()}      # tailles « gardées » différentes
        f2, _, _ = self._parcours(faux, dossiers)
        self.assertTrue(all(t == 999 for lst in f2.values() for _, t, _ in lst))        # réutilisées : dossiers inchangés
        f3, _, _ = self._parcours(faux, {})                                              # parcours complet : relues
        self.assertEqual(dict((c, t) for c, t, _ in f3["Alpha"])["Alpha/Tome 01/Alpha - Tome 01.cbz"], 4)

    def test_sqlite_aller_retour(self):
        fichiers, dossiers, _ = self._parcours()
        self.assertIsNone(indexation.charger(self.base, self.racine))
        indexation.enregistrer(self.base, self.racine, fichiers, dossiers)
        f, d = indexation.charger(self.base, self.racine)
        self.assertEqual(sorted(f), ["Alpha", "Beta"])
        self.assertEqual(d, dossiers)
        self.assertIsNone(indexation.charger(self.base, Path(self.tmp.name) / "autre"))   # autre dossier : index ignoré


class AppIndexTest(unittest.TestCase):
    def setUp(self):
        import app as A
        self.A = A
        self.tmp = tempfile.TemporaryDirectory()
        self.avant = A.MANGA_DIR
        A.MANGA_DIR = Path(self.tmp.name)
        _cbz(A.MANGA_DIR / "Serie" / "Serie T01.cbz")
        A._scan_invalider()

    def tearDown(self):
        self.A.MANGA_DIR = self.avant
        self.A._scan_invalider()
        self.tmp.cleanup()

    def test_nouveau_fichier_vu_tout_de_suite(self):
        self.assertEqual(len(self.A._scan()["Serie"]), 1)
        _cbz(self.A.MANGA_DIR / "Serie" / "Serie T02.cbz")
        self.assertEqual(len(self.A._scan()["Serie"]), 2)           # la date du dossier a changé : reparcours

    def test_fichier_retire_et_nouvelle_serie(self):
        self.A._scan()
        (self.A.MANGA_DIR / "Serie" / "Serie T01.cbz").unlink()
        _cbz(self.A.MANGA_DIR / "Autre" / "Autre T01.cbz")
        s = self.A._scan()
        self.assertEqual(sorted(s), ["Autre"])

    def test_la_copie_rendue_peut_etre_modifiee(self):
        s = self.A._scan()
        s["Serie"].clear()
        s["Intrus"] = []
        self.assertEqual(len(self.A._scan()["Serie"]), 1)
        self.assertNotIn("Intrus", self.A._scan())

    def test_taille_depuis_lindex(self):
        f = self.A.MANGA_DIR / "Serie" / "Serie T01.cbz"
        f.write_bytes(b"abcdef")
        self.A._scan_invalider()
        self.A._scan()
        self.assertEqual(self.A._stat_index(f)[0], 6)


class FichesEnMemoireTest(unittest.TestCase):
    def test_fiche_relue_seulement_si_le_fichier_change(self):
        import tomes
        dossier = Path(tempfile.mkdtemp())
        avant = tomes.DOSSIER
        tomes.DOSSIER = dossier
        try:
            f = tomes._fichier("Serie")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"tomes": {"1": 1}, "titres": {}}), encoding="utf-8")
            a = tomes._charger("Serie")
            a["ajout"] = 1                                     # une copie : la mémoire n'est pas touchée
            self.assertNotIn("ajout", tomes._charger("Serie"))
            time.sleep(0.01)
            f.write_text(json.dumps({"tomes": {"1": 1, "2": 2}, "titres": {}}), encoding="utf-8")
            self.assertEqual(sorted(tomes._charger("Serie")["tomes"]), [1.0, 2.0])
            f.unlink()
            self.assertIsNone(tomes._charger("Serie"))
        finally:
            tomes.DOSSIER = avant


if __name__ == "__main__":
    unittest.main()
