"""Une série suivie renommée pour une autre œuvre oublie la fiche de l'ancienne (Basilisk : Ouka ↔ Kouga)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import suivi


class RenommageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(suivi._ETAT, {"fichier": Path(self.tmp.name) / "suivies.json"})
        p.start()
        self.addCleanup(p.stop)

    def test_autre_oeuvre_la_fiche_est_oubliee_mais_gardee(self):
        suivi.ajouter("Basilisk: Ouka Ninpouchou", {"anilist": 110644, "annee": 2017, "couverture": "http://x/ouka.jpg", "titre": "Basilisk: Ouka Ninpouchou"})
        d = suivi.lire()
        d["series"]["Basilisk: Ouka Ninpouchou"]["propositions"] = [{"titre": "Ouka T1", "statut": "attente"}, {"titre": "Ouka T2", "statut": "telecharge"}]
        suivi.ecrire(d)
        suivi.renommer("Basilisk: Ouka Ninpouchou", "Basilisk: Kouga Ninpou-chou")
        x = suivi.lire()["series"]["Basilisk: Kouga Ninpou-chou"]
        self.assertNotIn("anilist", x)
        self.assertNotIn("couverture", x)
        self.assertEqual(x["titres"], ["Basilisk: Kouga Ninpou-chou"])
        self.assertEqual(x["avant_renommage"]["anilist"], 110644)
        self.assertEqual([p["titre"] for p in x["propositions"]], ["Ouka T2"])

    def test_simple_changement_d_ecriture_garde_tout(self):
        suivi.ajouter("Gashiakuta", {"anilist": 1, "titre": "Gachiakuta Deluxe"})
        suivi.renommer("Gashiakuta", "Gachiakuta")
        x = suivi.lire()["series"]["Gachiakuta"]
        self.assertEqual(x["anilist"], 1)
        self.assertEqual(x["titres"][0], "Gachiakuta")
        self.assertNotIn("avant_renommage", x)

    def test_reparation_au_demarrage_une_seule_fois(self):
        suivi.ajouter("Kouga", {"anilist": 5})
        d = suivi.lire()
        d["series"]["Kouga"]["titres"] = ["Basilisk Ouka", "バジリスク"]
        suivi.ecrire(d)
        self.assertEqual(suivi.recaler_tout(), ["Kouga"])
        self.assertEqual(suivi.recaler_tout(), [])
        self.assertNotIn("anilist", suivi.lire()["series"]["Kouga"])

    def test_serie_normale_jamais_touchee(self):
        suivi.ajouter("Rave", {"anilist": 9, "titre": "Rave Master", "original": "レイヴ"})
        avant = suivi.lire()
        self.assertEqual(suivi.recaler_tout(), [])
        self.assertEqual(suivi.lire(), avant)


if __name__ == "__main__":
    unittest.main()
