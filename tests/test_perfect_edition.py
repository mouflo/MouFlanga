"""Édition Perfect : ses ISBN viennent du catalogue de Glénat (jamais de ceux de l'édition standard)."""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import editeurs  # noqa: E402

# Adresses telles que le plan du site Glénat les donne (extrait réel : tomes 1 et 34 de la Perfect Edition, un tome standard)
CATALOGUE = {
    "9782723467681": "https://www.glenat.com/glenat-manga/dragon-ball-perfect-edition-tome-01-9782723467681/",
    "9782344004289": "https://www.glenat.com/glenat-manga/dragon-ball-perfect-edition-tome-34-9782344004289/",
    "9782723400001": "https://www.glenat.com/glenat-manga/dragon-ball-tome-01-9782723400001/",
}


class CollectionGlenatTest(unittest.TestCase):
    def setUp(self):
        editeurs._COLLECTIONS.clear()

    def test_perfect_donne_ses_tomes_et_pas_le_standard(self):
        with mock.patch.object(editeurs, "index", return_value=CATALOGUE):
            c = editeurs.collection_isbn("Dragon Ball", "Perfect")
        self.assertEqual(c, {1: "9782723467681", 34: "9782344004289"})

    def test_edition_sans_livre_au_catalogue_rend_vide(self):
        with mock.patch.object(editeurs, "index", return_value=CATALOGUE):
            self.assertEqual(editeurs.collection_isbn("Dragon Ball", "Color Édition"), {})
            self.assertEqual(editeurs.collection_isbn("Dragon Ball", ""), {})

    def test_catalogue_muet_rend_vide_sans_inventer(self):
        def panne(*a, **k):
            raise editeurs.reseau.Panne("glenat", "hors ligne")
        with mock.patch.object(editeurs, "index", side_effect=panne):
            self.assertEqual(editeurs.collection_isbn("Dragon Ball", "Perfect"), {})

    def test_cibles_avec_edition_ignore_l_isbn_standard(self):
        # Le tome 2 n'existe pas dans la Perfect du catalogue : pas d'ISBN standard à la place
        with mock.patch.object(editeurs, "index", return_value=CATALOGUE), \
                mock.patch("notices.observations", return_value={"2": {"editeur": {"isbn": "9782876952058"}}}):
            cibles = editeurs._cibles("Dragon Ball", {1, 2, 34}, {}, False, "Perfect")
        self.assertEqual(set(cibles), {1, 34})
        self.assertEqual(cibles[1][0], "9782723467681")


if __name__ == "__main__":
    unittest.main()
