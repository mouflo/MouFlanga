"""Sommaire d'un tome lu par OCR : lignes reconnues, page du sommaire trouvée, décalage des pages calculé."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sommaire  # noqa: E402

CLAYMORE = """( PANTIORE,
Volume 1
SOMMAIRE
SCÈNE 1 La tueuse aux yeux d'argent ...................5
SCÈNE 2 Les ongles du cief...........................69
SCÈNE 3 Les souvenirs d'une sorcière ..................109
SCÈNEA Le livret noir ..............................149"""


class AnalyseTest(unittest.TestCase):
    def test_lignes_de_sommaire(self):
        l = sommaire.analyser(CLAYMORE)
        self.assertEqual([(x["num"], x["page"]) for x in l], [(1, 5), (2, 69), (3, 109), (4, 149)])
        self.assertEqual(l[0]["titre"], "La tueuse aux yeux d'argent")
        self.assertTrue(sommaire._vraisemblable(l))

    def test_autres_formes(self):
        l = sommaire.analyser("Chapitre 12 : Le retour 45\n13. Un autre jour ........ 60\nUne bulle de texte 3")
        self.assertEqual([(x["num"], x["titre"], x["page"]) for x in l], [(12, "Le retour", 45), (13, "Un autre jour", 60)])

    def test_bruit_refuse(self):
        self.assertFalse(sommaire._vraisemblable(sommaire.analyser("Voici le premier volume.\nJ'espère qu'il vous plaira.")))
        self.assertFalse(sommaire._vraisemblable([{"num": 2, "page": 50}, {"num": 3, "page": 10}]))


class LectureTest(unittest.TestCase):
    def test_sommaire_et_decalage(self):
        textes = {0: "NORIHIRO YAGI", 1: "Voici le premier volume.", 5: CLAYMORE, 6: "SCENE 1 LA TUEUSE AUX YEUX D'ARGENT"}
        with mock.patch.object(sommaire, "ocr", side_effect=lambda octets: textes.get(octets, "")):
            r = sommaire.lire("essai", lambda i: i, 189)
        self.assertEqual(r["page_sommaire"], 5)
        self.assertEqual(r["decalage"], 1)
        self.assertEqual([c["image"] for c in r["chapitres"]], [6, 70, 110, 150])

    def test_rien_trouve(self):
        with mock.patch.object(sommaire, "ocr", return_value="dessin"):
            r = sommaire.lire("essai", lambda i: i, 20)
        self.assertEqual(r["chapitres"], [])


if __name__ == "__main__":
    unittest.main()


class VisionTest(unittest.TestCase):
    """Sommaire stylisé (Bakuman) : lu par Claude seulement si une clé est enregistrée."""

    def test_sans_cle_rien_n_est_envoye(self):
        with mock.patch.object(sommaire, "ocr", return_value="dessin"), mock.patch.dict("os.environ", {"CLAUDE_API_KEY": ""}), \
                mock.patch("requests.post") as p:
            r = sommaire.lire("x", lambda i: i, 20)
        self.assertEqual(r["chapitres"], [])
        p.assert_not_called()

    def test_reponse_de_claude(self):
        import io as _io
        from PIL import Image
        b = _io.BytesIO(); Image.new("RGB", (40, 60)).save(b, "JPEG")
        texte = ('Voici : {"page_sommaire": 4, "image_chapitre_1": 6, "chapitres": [{"num": 8, "titre": "La carotte et le bâton", "page": 7},'
                 ' {"num": 9, "titre": "Conditions et capitale", "page": 29}]}')
        rep = mock.Mock(status_code=200, json=mock.Mock(return_value={"content": [{"type": "text", "text": texte}]}))
        with mock.patch.object(sommaire, "ocr", return_value="dessin"), mock.patch.dict("os.environ", {"CLAUDE_API_KEY": "sk-ant-x"}), \
                mock.patch("requests.post", return_value=rep):
            r = sommaire.lire("x", lambda i: b.getvalue(), 190)
        self.assertEqual([(c["num"], c["page"], c["image"]) for c in r["chapitres"]], [(8.0, 7, 6), (9.0, 29, 28)])
        self.assertEqual(r["source"], "Claude")
