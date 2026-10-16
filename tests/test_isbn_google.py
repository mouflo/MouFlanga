"""ISBN des tomes trouvés sur Google Books : seulement « <série> Tome N » d'un éditeur français, rien d'autre."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tomes  # noqa: E402


def notice(titre, isbn):
    return {"title": titre, "industryIdentifiers": [{"type": "ISBN_13", "identifier": isbn}]}


class NoticeTest(unittest.TestCase):
    def test_tome_reconnu(self):
        self.assertEqual(tomes._isbn_de_notice(notice("One Piece - Édition originale - Tome 47", "9782331026560"), ["One Piece"]),
                         (47, "9782331026560"))
        self.assertEqual(tomes._isbn_de_notice(notice("Toriko T15", "9782820315212"), ["Toriko"]), (15, "9782820315212"))
        self.assertEqual(tomes._isbn_de_notice(notice("Dandadan - T21", "9782820355478"), ["Dandadan"]), (21, "9782820355478"))

    def test_autres_livres_refuses(self):
        self.assertIsNone(tomes._isbn_de_notice(notice("One Piece Doors - Tome 01", "9782331049934"), ["One Piece"]))
        self.assertIsNone(tomes._isbn_de_notice(notice("Dandadan Tome 18 . Edition limitée", "9782820353306"), ["Dandadan"]))
        self.assertIsNone(tomes._isbn_de_notice(notice("Toriko", "9782820332493"), ["Toriko"]))            # pas de numéro
        self.assertIsNone(tomes._isbn_de_notice(notice("Toriko - vol.38", "9786525920122"), ["Toriko"]))   # édition brésilienne
        self.assertIsNone(tomes._isbn_de_notice(notice("One Piece - Tome 47", "9782331026561"), ["One Piece"]))  # somme fausse

    def test_autre_edition(self):
        perfect = notice("Kenshin le vagabond - Perfect edition - Tome 3", "9782344012345")
        self.assertIsNone(tomes._isbn_de_notice(perfect, ["Kenshin le vagabond"]))
        normal = notice("Kenshin le vagabond - Tome 3", "9782723412346")
        self.assertIsNone(tomes._isbn_de_notice(normal, ["Kenshin le vagabond"], "Perfect edition"))


if __name__ == "__main__":
    unittest.main()


class SourceDuTorrentTest(unittest.TestCase):
    """Un torrent qui n'a apporté aucun tome (tous déjà là, rien remplacé) ne devient pas la source de la série."""

    def test_rien_d_arrive_rien_de_note(self):
        import app as A
        import edition
        appels = []
        ancien = edition.noter_volumes
        edition.noter_volumes = lambda *a: appels.append(a)
        try:
            A._TOMES_DU_TORRENT["Série test"] = set()
            A._noter_volumes_torrent("Série test", "Serie.Test.[INTEGRALE].FR-NOTAG")
        finally:
            edition.noter_volumes = ancien
        self.assertEqual(appels, [])
        self.assertNotIn("Série test", A._TOMES_DU_TORRENT)


class FichierPartTest(unittest.TestCase):
    """Torrent dont l'auteur a laissé « .cbz.part » sur des tomes complets : reconnus et placés en .cbz."""

    def test_part_complet(self):
        import tempfile, zipfile
        import torrents
        with tempfile.TemporaryDirectory() as d:
            bon = Path(d) / "Tokyo Revengers T01 - Ken Wakui.cbz.part"
            with zipfile.ZipFile(bon, "w") as z:
                z.writestr("001.jpg", b"x")
            vide = Path(d) / "Autre T02.cbz.part"
            vide.write_bytes(b"\0" * 10)                     # vraiment incomplet : pas une archive
            self.assertEqual(torrents.fichiers_du_torrent(Path(d)), [bon])
            self.assertEqual((torrents.suffixe(bon), torrents.nom_sans_ext(bon)), (".cbz", "Tokyo Revengers T01 - Ken Wakui"))
