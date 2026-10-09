"""Après un remplacement de tomes, l'analyse de résolution est à refaire (point 3.33)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edition  # noqa: E402


class InvaliderTest(unittest.TestCase):
    def test_analyse_retiree_et_nfo_gardé(self):
        with tempfile.TemporaryDirectory() as tmp:
            dossier = Path(tmp)
            edition.ecrire(dossier, {"analyse": {"source": "Scan", "resolution": "756 × 1100"}, "nfo": "texte"})
            edition.invalider(dossier)
            d = edition.lire(dossier)
            self.assertNotIn("analyse", d)
            self.assertEqual(d.get("nfo"), "texte")

    def test_sans_analyse_rien_a_faire(self):
        with tempfile.TemporaryDirectory() as tmp:
            dossier = Path(tmp)
            edition.invalider(dossier)
            self.assertFalse((dossier / edition.FICHIER).exists())


if __name__ == "__main__":
    unittest.main()
