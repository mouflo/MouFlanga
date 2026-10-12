"""Suivi des tomes : la même équipe que la série passe en premier, et remplace toute seule un tome d'une autre équipe."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import provenance  # noqa: E402
import suivi  # noqa: E402

FR = ["🇫🇷 FR"]


class MemeEquipeTest(unittest.TestCase):
    def test_equipes(self):
        self.assertEqual(provenance.equipe_torrent("One.Piece.T101.Oda.FR.[CBZ]-TONER-Paprika"), "TONER-Paprika")
        self.assertTrue(provenance.meme_equipe("PRiNTER-PapriKa+", "TONER-Paprika"))
        self.assertFalse(provenance.meme_equipe("NoFace696", "TONER-Paprika"))

    def test_meme_equipe_en_premier(self):
        info = {"tomes": set(range(1, 101)), "equipe": "PRiNTER-PapriKa+", "equipe_tomes": {}}
        res = [{"titre": "One Piece T101 (NoFace696)", "badges": FR}, {"titre": "One.Piece.T101.FR.[CBZ]-TONER-Paprika", "badges": FR}]
        p = suivi.propositions_pour("One Piece", info, res, [])
        self.assertEqual(p[0]["titre"], "One.Piece.T101.FR.[CBZ]-TONER-Paprika")
        self.assertTrue(p[0]["meme_equipe"])
        self.assertIn("⭐ même équipe", p[0]["badges"])

    def test_remplacement_automatique(self):
        info = {"tomes": set(range(1, 107)), "equipe": "PRiNTER-PapriKa+", "equipe_tomes": {106: "NoFace696", 105: "PRiNTER-PapriKa+"}}
        res = [{"titre": "One.Piece.T106.FR.[CBZ]-TONER-Paprika", "badges": FR, "lien": "magnet:x"}]
        lances, messages = [], []
        with mock.patch.object(suivi, "lire", return_value={"series": {"One Piece": {"surveiller": True}}}), \
                mock.patch.object(suivi, "ecrire"):
            nouv = suivi.verifier("One Piece", lambda t: res, lambda n: dict(info), lambda *a: lances.append(a), messages.append)
        self.assertEqual(nouv[0]["type"], "equipe")
        self.assertEqual(nouv[0]["tomes"], [106])
        self.assertEqual(lances, [("magnet:x", "One.Piece.T106.FR.[CBZ]-TONER-Paprika", "One Piece")])
        self.assertIn("NoFace696 → PRiNTER-PapriKa+", messages[0])


if __name__ == "__main__":
    unittest.main()
