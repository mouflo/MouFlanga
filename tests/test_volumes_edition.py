"""Nombre de tomes propre à une édition, lu dans le titre du torrent (point 3.47)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edition  # noqa: E402


class VolumesDuTitreTest(unittest.TestCase):
    def test_integrale_avec_nombre(self):
        self.assertEqual(edition.volumes_du_titre("Cat's Eye - Édition de luxe [Intégrale 15 tomes] [Ebooks Officiels]"), 15)

    def test_sans_nombre(self):
        self.assertIsNone(edition.volumes_du_titre("Dandadan"))
        self.assertIsNone(edition.volumes_du_titre(""))


if __name__ == "__main__":
    unittest.main()
