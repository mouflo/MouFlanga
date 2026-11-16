"""📕 Couverture dans le fichier : l'image remplace la première page ou s'ajoute avant elle, rien d'autre ne bouge, les signets suivent."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import archives  # noqa: E402
import optimiser  # noqa: E402


def jpeg(couleur, taille=(120, 180)):
    b = io.BytesIO()
    Image.new("RGB", taille, couleur).save(b, "JPEG", quality=95)
    return b.getvalue()


COMICINFO = ('<?xml version="1.0"?><ComicInfo><PageCount>3</PageCount><Pages>'
             '<Page Image="0" Type="FrontCover"/><Page Image="2" Bookmark="Chapitre 2"/></Pages></ComicInfo>')


def tome(dossier, noms=("0001.jpg", "0002.jpg", "0003.jpg")):
    chemin = Path(dossier) / "Tome 01.cbz"
    with zipfile.ZipFile(chemin, "w") as z:
        for i, nom in enumerate(noms):
            z.writestr(nom, jpeg((200, 10 * i, 10)))
        z.writestr("ComicInfo.xml", COMICINFO)
    return chemin


def couleur_page(chemin, nom):
    with zipfile.ZipFile(chemin) as z:
        return Image.open(io.BytesIO(z.read(nom))).convert("RGB").getpixel((5, 5))


class CouvertureDansFichierTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.neuve = jpeg((10, 10, 220))

    def test_remplacer_la_premiere_page(self):
        chemin = tome(self._tmp.name)
        res = optimiser.couverture_dans_fichier(chemin, self.neuve, "remplacer")
        self.assertEqual((res["pages_avant"], res["pages"]), (3, 3))
        self.assertEqual(archives.pages(chemin), ["0001.jpg", "0002.jpg", "0003.jpg"])
        r, g, b = couleur_page(chemin, "0001.jpg")
        self.assertGreater(b, 150)                                                  # c'est bien la nouvelle image
        self.assertGreater(couleur_page(chemin, "0002.jpg")[0], 150)                # les autres pages n'ont pas bougé
        self.assertTrue(res["avant"].is_file() and zipfile.is_zipfile(res["avant"]))  # l'ancien fichier est gardé (corbeille)
        self.assertNotIn(0, res["carte"])

    def test_ajouter_avant_la_premiere_page_decale_les_signets(self):
        chemin = tome(self._tmp.name)
        res = optimiser.couverture_dans_fichier(chemin, self.neuve, "ajouter")
        ordre = archives.pages(chemin)
        self.assertEqual(ordre, ["0000-couverture.jpg", "0001.jpg", "0002.jpg", "0003.jpg"])
        self.assertEqual(res["carte"], {0: 1, 1: 2, 2: 3})
        with zipfile.ZipFile(chemin) as z:
            info = z.read("ComicInfo.xml").decode()
        self.assertIn('Image="1"', info)                                            # l'ancien « 0 » est devenu « 1 »
        self.assertIn('Image="3"', info)
        self.assertIn(">4<", info)                                                  # nombre de pages

    def test_ajouter_passe_avant_les_pages_de_chapitre(self):
        chemin = tome(self._tmp.name, ("c0001.00-p001.jpg", "c0001.00-p002.jpg", "c0002.00-p001.jpg"))
        optimiser.couverture_dans_fichier(chemin, self.neuve, "ajouter")
        self.assertEqual(archives.pages(chemin)[0], "0000-couverture.jpg")

    def test_premiere_page_png_devient_jpg_sans_changer_de_place(self):
        chemin = Path(self._tmp.name) / "T.cbz"
        b = io.BytesIO()
        Image.new("RGB", (50, 80)).save(b, "PNG")
        with zipfile.ZipFile(chemin, "w") as z:
            z.writestr("001.png", b.getvalue())
            z.writestr("002.jpg", jpeg((1, 2, 3)))
        optimiser.couverture_dans_fichier(chemin, self.neuve, "remplacer")
        self.assertEqual(archives.pages(chemin), ["001.jpg", "002.jpg"])

    def test_fichier_partage_ecrit_dans_destination_sans_toucher_l_original(self):
        chemin = tome(self._tmp.name)
        octets = chemin.read_bytes()
        dest = Path(self._tmp.name) / "neuf.cbz"
        res = optimiser.couverture_dans_fichier(chemin, self.neuve, "ajouter", destination=dest)
        self.assertNotIn("avant", res)
        self.assertEqual(chemin.read_bytes(), octets)
        self.assertEqual(len(archives.pages(dest)), 4)

    def test_image_illisible_ou_mode_inconnu_ne_touche_a_rien(self):
        chemin = tome(self._tmp.name)
        octets = chemin.read_bytes()
        with self.assertRaises(Exception):
            optimiser.couverture_dans_fichier(chemin, b"pas une image", "remplacer")
        with self.assertRaises(ValueError):
            optimiser.couverture_dans_fichier(chemin, self.neuve, "autre")
        self.assertEqual(chemin.read_bytes(), octets)
        self.assertEqual([p.name for p in Path(self._tmp.name).iterdir()], ["Tome 01.cbz"])


if __name__ == "__main__":
    unittest.main()
