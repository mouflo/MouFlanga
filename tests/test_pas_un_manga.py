"""Un livre audio ou une vidéo n'est jamais proposé pour une série de manga."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import regles  # noqa: E402
import suivi  # noqa: E402

AUDIO = "Genevieve Guilbault Ti Guy la puck T9 Nuit blanche a l arena 2023 FRENCH Mp3 128kbps-NoTag"


class PasUnMangaTest(unittest.TestCase):
    def test_audio_et_video_reconnus(self):
        self.assertTrue(regles.pas_un_manga(AUDIO))
        self.assertTrue(regles.pas_un_manga("Arena.S01.FRENCH.1080p.WEB-DL.x264"))
        self.assertFalse(regles.pas_un_manga("Arena.T09.FRENCH.CBZ.eBook-Paprika"))
        self.assertFalse(regles.pas_un_manga("Air Gear T01-T37 FRENCH CBZ"))

    def test_jamais_propose_a_la_surveillance(self):
        r = {"titre": AUDIO, "badges": ["🇫🇷 FR"], "score": 260, "sources": 4, "profil": "x"}
        info = {"tomes": {1, 2}, "source": "", "equipe": "", "equipe_tomes": {}}
        self.assertEqual(suivi.propositions_pour("Arena", info, [r], []), [])


if __name__ == "__main__":
    unittest.main()
