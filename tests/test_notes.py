"""Notes des séries : sources dans l'ordre, une demande par jour, jamais d'appel à l'affichage."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notes  # noqa: E402


class NotesTest(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self.avant = notes.FICHIER
        notes.FICHIER = self.dossier / "notes.json"
        notes._CACHE.update(cle=None, notes={})

    def tearDown(self):
        notes.FICHIER = self.avant
        notes._CACHE.update(cle=None, notes={})

    def test_anilist_en_premier(self):
        with mock.patch.object(notes, "_anilist", return_value=(7.3, 111)), mock.patch.object(notes, "_kitsu") as k:
            self.assertEqual(notes.chercher("S", 5, []), (7.3, "AniList"))
            k.assert_not_called()

    def test_kitsu_puis_myanimelist(self):
        with mock.patch.object(notes, "_anilist", return_value=(None, 222)), mock.patch.object(notes, "_kitsu", return_value=None), \
                mock.patch.object(notes, "_jikan", return_value=8.1) as j:
            self.assertEqual(notes.chercher("S", 5, []), (8.1, "MyAnimeList"))
            j.assert_called_with(222, ["S"])

    def test_source_en_panne_ne_bloque_pas(self):
        with mock.patch.object(notes, "_anilist", side_effect=RuntimeError("429")), mock.patch.object(notes, "_kitsu", return_value=7.8):
            self.assertEqual(notes.chercher("S"), (7.8, "Kitsu"))

    def test_enregistrement_et_lecture(self):
        with mock.patch.object(notes, "chercher", return_value=(7.8, "Kitsu")):
            self.assertTrue(notes.mettre_a_jour("Serie"))
        self.assertEqual(notes.note("Serie"), (7.8, "Kitsu"))
        self.assertIsNone(notes.note("Autre"))

    def test_un_echec_nefface_pas_la_note(self):
        with mock.patch.object(notes, "chercher", return_value=(7.8, "AniList")):
            notes.mettre_a_jour("Serie")
        with mock.patch.object(notes, "chercher", return_value=(None, "")):
            self.assertFalse(notes.mettre_a_jour("Serie"))
        self.assertEqual(notes.note("Serie"), (7.8, "AniList"))

    def test_une_demande_par_jour(self):
        self.assertTrue(notes.a_rafraichir("Neuve"))                          # jamais notée
        with mock.patch.object(notes, "chercher", return_value=(None, "")):
            notes.mettre_a_jour("Neuve")                                      # essayée, sans note
        self.assertFalse(notes.a_rafraichir("Neuve"))                         # pas avant demain
        self.assertTrue(notes.a_rafraichir("Neuve", time.time() + 86500))
        with mock.patch.object(notes, "chercher", return_value=(8.0, "AniList")):
            notes.mettre_a_jour("Vieille")
        self.assertFalse(notes.a_rafraichir("Vieille"))
        self.assertTrue(notes.a_rafraichir("Vieille", time.time() + 86500))

    def test_lancer_ne_demande_que_ce_qui_manque(self):
        with mock.patch.object(notes, "chercher", return_value=(7.0, "AniList")):
            notes.mettre_a_jour("Deja")
        appels = []
        with mock.patch.object(notes, "mettre_a_jour", side_effect=lambda s, *a: appels.append(s)):
            self.assertTrue(notes.lancer(["Deja", "Neuve"], lambda s: (None, []), pause=0))
            for _ in range(50):
                if not notes._EN_COURS["actif"]:
                    break
                time.sleep(0.05)
        self.assertEqual(appels, ["Neuve"])


if __name__ == "__main__":
    unittest.main()
