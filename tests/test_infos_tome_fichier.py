"""Infos d'un tome écrites dans son ComicInfo.xml (résumé, notes) et relues."""
import tempfile
import unittest
import zipfile
from pathlib import Path

import signets


class InfosTomeFichierTest(unittest.TestCase):
    def test_ecrire_et_relire(self):
        t = Path(tempfile.mkdtemp())
        src = t / "a.cbz"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("001.jpg", b"x")
            z.writestr("002.jpg", b"y")
        infos = {"Title": "Romance Dawn", "Summary": "Un résumé.", "Notes": 'MouFlanga: {"v":1,"equipe":"X"}'}
        signets.ecrire(src, None, t / "b.cbz", infos)
        lu = signets.lire_infos(t / "b.cbz")
        self.assertEqual(lu["resume"], "Un résumé.")
        self.assertEqual(lu["titre"], "Romance Dawn")
        self.assertEqual(lu["notes"], {"v": 1, "equipe": "X", "ecrits": ["Summary", "Title"]})
        # chapitres ajoutés ensuite : infos gardées, signets écrits
        signets.ecrire(t / "b.cbz", [{"num": 1, "titre": "A", "image": 0}], t / "c.cbz")
        self.assertEqual(signets.lire_infos(t / "c.cbz")["resume"], "Un résumé.")
        self.assertEqual(signets.lire(t / "c.cbz")[0]["titre"], "A")

    def test_notes_etrangeres_gardees(self):
        t = Path(tempfile.mkdtemp())
        src = t / "a.cbz"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("001.jpg", b"x")
            z.writestr("ComicInfo.xml", "<ComicInfo><Notes>Scan par X</Notes></ComicInfo>")
        signets.ecrire(src, None, t / "b.cbz", {"Notes": 'MouFlanga: {"v":1}'})
        with zipfile.ZipFile(t / "b.cbz") as z:
            self.assertIn("Scan par X", z.read("ComicInfo.xml").decode())
        self.assertEqual(signets.lire_infos(t / "b.cbz")["notes"], {"v": 1})

    def _cbz(self, t, comicinfo):
        src = t / "a.cbz"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("001.jpg", b"x")
            z.writestr("ComicInfo.xml", comicinfo)
        return src

    def test_balises_de_l_equipe_jamais_ecrasees(self):
        t = Path(tempfile.mkdtemp())
        src = self._cbz(t, "<ComicInfo><Series>Defense Devil</Series><Summary>Résumé de l'équipe</Summary><Writer>Auteur</Writer></ComicInfo>")
        signets.ecrire(src, None, t / "b.cbz", {"Summary": "Résumé Internet", "Writer": "Autre", "Publisher": "Éditeur",
                                                 "Notes": 'MouFlanga: {"v":1,"resume":"web"}'})
        lu = signets.lire_infos(t / "b.cbz")
        self.assertEqual(lu["resume"], "Résumé de l'équipe")
        self.assertEqual(lu["auteur"], "Auteur")
        self.assertEqual(lu["editeur"], "Éditeur")                  # champ vide chez l'équipe : complété
        signets.ecrire(t / "b.cbz", None, t / "c.cbz", {"Publisher": "Nouvel éditeur", "Summary": "Encore",
                                                         "Notes": 'MouFlanga: {"v":1}'})
        lu = signets.lire_infos(t / "c.cbz")
        self.assertEqual(lu["editeur"], "Nouvel éditeur")           # posé par MouFlanga : mis à jour
        self.assertEqual(lu["resume"], "Résumé de l'équipe")

    def test_resume_manuel_prioritaire(self):
        t = Path(tempfile.mkdtemp())
        src = self._cbz(t, "<ComicInfo><Summary>Résumé de l'équipe</Summary></ComicInfo>")
        signets.ecrire(src, None, t / "b.cbz", {"Summary": "Le mien", "Notes": 'MouFlanga: {"v":1,"resume":"manuel"}'})
        self.assertEqual(signets.lire_infos(t / "b.cbz")["resume"], "Le mien")

    def test_isbn_lu(self):
        t = Path(tempfile.mkdtemp())
        for xml, attendu in (("<ComicInfo><GTIN>9782723488525</GTIN></ComicInfo>", "9782723488525"),
                             ("<ComicInfo><Notes>Scan par X\nISBN 978-2-7234-8852-5</Notes></ComicInfo>", "9782723488525"),
                             ("<ComicInfo><Web>https://exemple.fr/livre/2723488527</Web></ComicInfo>", "2723488527"),
                             ("<ComicInfo><Title>Rien</Title></ComicInfo>", "")):
            src = self._cbz(t, xml)
            self.assertEqual(signets.lire_infos(src)["isbn"], attendu, xml)

    def test_format_lu(self):
        t = Path(tempfile.mkdtemp())
        src = self._cbz(t, "<ComicInfo><Series>Gantz</Series><Format>Perfect Édition</Format></ComicInfo>")
        self.assertEqual(signets.lire_infos(src)["format"], "Perfect Édition")

    def test_isbn_ocr_dernieres_pages(self):
        from unittest import mock
        import sommaire
        textes = {5: "Dépôt légal. ISBN : 978-2-7234-8852-5"}
        with mock.patch.object(sommaire, "ocr", side_effect=lambda o, clair=False: textes.get(o, "")), \
                mock.patch.object(sommaire, "PAGES_MAX", 2):
            r = sommaire.lire("x.cbz", lambda i: i, 6)
        self.assertEqual(r.get("isbn"), "9782723488525")


if __name__ == "__main__":
    unittest.main()
