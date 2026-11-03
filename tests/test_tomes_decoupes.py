"""Un tome découpé en chapitres (entrées sans champ « tome », seulement le dossier « Tome NN ») compte comme présent."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402


class TomesDecoupesTest(unittest.TestCase):
    def test_tomes_de_voit_le_tome_decoupe(self):
        entrees = [{"tome": None, "groupe": "Tome 01"}, {"tome": None, "groupe": "Tome 01"}, {"tome": 2, "groupe": "Tome 02"},
                   {"tome": None, "groupe": "", "a_importer": True}, {"tome": None, "groupe": "Hors-série"}]
        self.assertEqual(app._tomes_de("X", entrees), {1, 2})


if __name__ == "__main__":
    unittest.main()
