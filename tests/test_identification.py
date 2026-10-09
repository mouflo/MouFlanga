"""« Relancer l'identification » : le cache d'une série est effacé (point 3.30)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tomes  # noqa: E402


class OublierTest(unittest.TestCase):
    def test_cache_efface_et_autres_series_gardees(self):
        with tempfile.TemporaryDirectory() as tmp:
            ancien = tomes.DOSSIER
            tomes.DOSSIER = Path(tmp)
            try:
                tomes._fichier("Crows").write_text("{}", encoding="utf-8")
                tomes._fichier("Breaker").write_text("{}", encoding="utf-8")
                tomes.oublier("Crows")
                self.assertFalse(tomes._fichier("Crows").exists())
                self.assertTrue(tomes._fichier("Breaker").exists())
                tomes.oublier("Inconnue")                      # sans cache : aucune erreur
            finally:
                tomes.DOSSIER = ancien


if __name__ == "__main__":
    unittest.main()
