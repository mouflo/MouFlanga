"""correspondance.py : ce titre est-il celui de la série ? Cas réels rencontrés (Akame ga Kill, Kenichi, Golden Kamui…)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import correspondance as C  # noqa: E402

AKAME = ["Akame ga Kill !", "Akame ga Kill!", "Akame ga KILL!", "Red Eyes Sword", "Akame ga Kiru!"]
ZERO = ["Akame ga Kill ! : Zero", "Akame ga Kill! Zero", "Red Eyes Sword Zero"]


class MotsTest(unittest.TestCase):
    def test_ecritures_differentes_du_meme_mot(self):
        self.assertTrue(C.jetons_equivalents("kamuy", "kamui"))
        self.assertTrue(C.jetons_equivalents("ghost", "ghosts"))
        self.assertTrue(C.jetons_equivalents("kill", "kill"))
        self.assertFalse(C.jetons_equivalents("kill", "kiss"))            # trop court pour être souple
        self.assertFalse(C.jetons_equivalents("21st", "20th"))
        self.assertFalse(C.jetons_equivalents("tome12", "tome13"))
        self.assertFalse(C.jetons_equivalents("naruto", "boruto"))        # deux lettres de différence

    def test_abreviations(self):
        self.assertTrue(C.jetons_equivalents("dr", "docteur"))
        self.assertTrue(C.titre_de_la_serie("Dr Slump", ["Docteur Slump"]))
        self.assertFalse(C.jetons_equivalents("dr", "drame"))

    def test_mots_colles(self):
        self.assertTrue(C.contient_nom("Ken-Ichi : le disciple ultime", "Kenichi"))
        self.assertTrue(C.contient_nom("Golden Kamui", "Golden Kamuy"))
        self.assertFalse(C.contient_nom("Golden Boy", "Golden Kamuy"))


class TitreTest(unittest.TestCase):
    def verifier(self, titre, noms, attendu, **kw):
        self.assertEqual(C.titre_de_la_serie(titre, noms, **kw), attendu, f"{titre!r} pour {noms[0]!r}")

    def test_akame_et_zero_ne_se_melangent_pas(self):
        self.verifier("Red eyes sword : akame ga kill !", AKAME, True)
        self.verifier("Akame ga Kill !", AKAME, True)
        self.verifier("Red eyes sword : Akame ga kill ! Zero", AKAME, False)
        self.verifier("Akame ga Kill ! Zero", AKAME, False)
        self.verifier("Red eyes sword : Akame ga kill ! Zero", ZERO, True)
        self.verifier("Red eyes sword : akame ga kill !", ZERO, False)
        self.verifier("Blue eyes sword : Hinowa ga crush !", AKAME, False)

    def test_titre_francais_plus_long_sans_synonyme_connu(self):
        self.verifier("Red eyes sword : akame ga kill !", ["Akame ga Kill !"], True)     # le nom est une partie du titre

    def test_kenichi(self):
        noms = ["Kenichi : Le Disciple Ultime", "Le Disciple Ultime", "Kenichi"]
        self.verifier("Ken-Ichi : le disciple ultime", noms, True)
        self.verifier("Ken-Ichi, saison 2 : les disciples de l'ombre", noms, False)
        self.verifier("Kimono, by Kenichi Kawakatsu", noms, False)

    def test_golden_kamui(self):
        self.verifier("Golden kamui", ["Golden Kamuy", "Golden Kamui"], True)
        self.verifier("Golden kamui", ["Golden Kamuy"], True)

    def test_siecles(self):
        self.verifier("21st Century Boys", ["20th Century Boys"], False)
        self.verifier("20th Century Boys", ["20th Century Boys"], True)

    def test_autre_serie_de_la_bibliotheque_plus_precise(self):
        self.verifier("Gantz : Osaka", ["Gantz"], False, autres_series=["Gantz : Osaka", "Gantz"])
        self.verifier("Gantz", ["Gantz"], True, autres_series=["Gantz : Osaka", "Gantz"])

    def test_editions(self):
        self.verifier("Kenshin le vagabond - Perfect edition", ["Kenshin le vagabond"], False)
        self.verifier("Kenshin le vagabond - Perfect edition", ["Kenshin le vagabond : Perfect Edition"], True)
        self.verifier("One Piece - Édition originale", ["One Piece"], True)
        self.verifier("Kenshin le vagabond", ["Kenshin le vagabond : Perfect"], False)

    def test_derives(self):
        self.verifier("Naruto Gaiden", ["Naruto"], False)
        self.verifier("One Piece Party", ["One Piece"], False)
        self.verifier("Dandadan", ["Dandadan"], True)


if __name__ == "__main__":
    unittest.main()
