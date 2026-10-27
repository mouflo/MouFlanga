"""Plage horaire des lectures de fond : minuit à 6 h, heure de Paris."""
import datetime
import unittest
import unittest.mock
import zoneinfo

import plage

PARIS = zoneinfo.ZoneInfo("Europe/Paris")


def a_paris(h, m=0):
    return datetime.datetime(2026, 10, 27, h, m, tzinfo=PARIS)


class DansLaPlage(unittest.TestCase):
    def test_minuit_a_six_heures(self):
        self.assertTrue(plage.dans_la_plage(a_paris(0, 0)))
        self.assertTrue(plage.dans_la_plage(a_paris(3, 30)))
        self.assertTrue(plage.dans_la_plage(a_paris(5, 59)))

    def test_hors_plage(self):
        self.assertFalse(plage.dans_la_plage(a_paris(6, 0)))
        self.assertFalse(plage.dans_la_plage(a_paris(15, 53)))
        self.assertFalse(plage.dans_la_plage(a_paris(23, 59)))

    def test_heure_utc_convertie_en_paris(self):
        # 23 h UTC le 26 octobre = 0 h (heure de Paris, après le changement d'heure du 25 octobre)
        utc = datetime.datetime(2026, 10, 26, 23, 30, tzinfo=datetime.timezone.utc)
        self.assertTrue(plage.dans_la_plage(utc))
        # 6 h 30 UTC = 7 h 30 à Paris : hors plage
        self.assertFalse(plage.dans_la_plage(datetime.datetime(2026, 10, 27, 6, 30, tzinfo=datetime.timezone.utc)))


class AttendreLaPlage(unittest.TestCase):
    def test_deja_dans_la_plage_ne_attend_pas(self):
        with unittest.mock.patch.object(plage, "dans_la_plage", return_value=True), \
                unittest.mock.patch.object(plage.time, "sleep") as dodo:
            self.assertTrue(plage.attendre_la_plage())
            dodo.assert_not_called()

    def test_arret_demande_pendant_l_attente(self):
        with unittest.mock.patch.object(plage, "dans_la_plage", return_value=False), \
                unittest.mock.patch.object(plage.time, "sleep"):
            self.assertFalse(plage.attendre_la_plage(arret=lambda: True))

    def test_attend_puis_reprend_a_la_plage(self):
        reponses = iter([False, False, True])
        with unittest.mock.patch.object(plage, "dans_la_plage", side_effect=lambda *a, **k: next(reponses)), \
                unittest.mock.patch.object(plage.time, "sleep") as dodo:
            self.assertTrue(plage.attendre_la_plage(pas=60))
            self.assertEqual(dodo.call_count, 2)


if __name__ == "__main__":
    unittest.main()
