"""Connaissances gardées pour de bon (œuvres liées, dates des tomes) : relues sans Internet, en mémoire ensuite."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import connaissances  # noqa: E402


class ConnaissancesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base, connaissances.BASE = connaissances.BASE, Path(self.tmp.name) / "c.sqlite"
        connaissances._MEMOIRE.clear()

    def tearDown(self):
        connaissances.BASE = self.base
        connaissances._MEMOIRE.clear()
        self.tmp.cleanup()

    def test_jamais_demande_puis_garde(self):
        self.assertIsNone(connaissances.oeuvres_liees("anilist:1"))
        connaissances.garder_oeuvres_liees("anilist:1", [{"id": 7, "relation": "SPIN_OFF", "volumes": 6, "debut": "2022-07-27",
                                                          "titres": ["A Letter from Keisuke Baji"]}])
        connaissances._MEMOIRE.clear()                       # comme après un redémarrage
        self.assertEqual(connaissances.oeuvres_liees("anilist:1")[0]["titres"], ["A Letter from Keisuke Baji"])
        connaissances.garder_oeuvres_liees("anilist:2", [])  # demandé, rien trouvé : liste vide, pas None
        self.assertEqual(connaissances.oeuvres_liees("anilist:2"), [])

    def test_dates_ajoutees_sans_rien_perdre(self):
        connaissances.garder_dates_tomes("anilist:1", {"1": "2017-05-17"})
        connaissances.garder_dates_tomes("anilist:1", {"2": "2017-07-14"})
        self.assertEqual(connaissances.dates_tomes("anilist:1"), {"1": "2017-05-17", "2": "2017-07-14"})


if __name__ == "__main__":
    unittest.main()
