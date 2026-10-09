"""Provenance des tomes : équipe lue dans le nom d'origine, note à la main protégée des déductions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import provenance as p  # noqa: E402


class ProvenanceTest(unittest.TestCase):
    def test_equipe_lue_dans_le_nom(self):
        self.assertEqual(p.equipe_du_nom("One Piece HS - Blue (Oda) (2005) [Digital-1920] [Manga FR] (PRiNTER-PapriKa+).cbz"), "PRiNTER-PapriKa+")
        self.assertEqual(p.equipe_du_nom("Jojo's Bizarre Adventure - Part 01 (Araki) (2014) [Digital-1920u] (PapriKa+).cbz"), "PapriKa+")

    def test_pas_d_equipe(self):
        self.assertEqual(p.equipe_du_nom("Worst - Tome 10.cbz"), "")
        self.assertEqual(p.equipe_du_nom("Seven Deadly Sins (Univers)"), "")

    def test_deduction_ne_remplace_pas_la_note_manuelle(self):
        infos = {}
        self.assertTrue(p.noter(infos, 10, "PapriKa", "Torrent : x"))
        self.assertFalse(p.noter(infos, 10, "AutreTeam", "Torrent : y"))          # déjà connue
        self.assertTrue(p.noter(infos, 10, "Ma team", "Saisie", manuel=True, ecrase=True))
        self.assertFalse(p.noter(infos, 10, "PapriKa", "Torrent : z"))           # la note manuelle reste
        self.assertEqual(p.lire(infos)["10"]["equipe"], "Ma team")

    def test_tome_sans_info_reste_vide(self):
        self.assertFalse(p.noter({}, 3, "", ""))


if __name__ == "__main__":
    unittest.main()
