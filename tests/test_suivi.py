"""Séries suivies : une série supprimée n'est plus suivie."""
import tempfile
import unittest
from pathlib import Path

import suivi


class RetirerTest(unittest.TestCase):
    def test_retirer(self):
        with tempfile.TemporaryDirectory() as t:
            ancien = suivi._ETAT["fichier"]
            suivi._ETAT["fichier"] = Path(t) / "suivies.json"
            try:
                suivi.ajouter("Beelzebub Side Story")
                suivi.ajouter("Gintama")
                self.assertTrue(suivi.retirer("Beelzebub Side Story"))
                self.assertFalse(suivi.retirer("Beelzebub Side Story"))
                self.assertEqual(list(suivi.lire()["series"]), ["Gintama"])
            finally:
                suivi._ETAT["fichier"] = ancien


class AutreSerieTest(unittest.TestCase):
    """« Air Gear Unlimited » suivie, « Air Gear » aussi dans la collection : les torrents d'Air Gear ne sont pas pour Unlimited."""
    def test_les_torrents_d_une_autre_serie_ne_sont_pas_proposes(self):
        with tempfile.TemporaryDirectory() as t:
            ancien, hook = suivi._ETAT["fichier"], suivi.AUTRES_SERIES
            suivi._ETAT["fichier"] = Path(t) / "suivies.json"
            suivi.AUTRES_SERIES = lambda nom: ["Air Gear"]
            try:
                suivi.ajouter("Air Gear Unlimited")
                d = suivi.lire()
                d["series"]["Air Gear Unlimited"]["titres"] = ["Air Gear Unlimited", "Air Gear"]
                d["series"]["Air Gear Unlimited"]["propositions"] = [{"id": "x", "titre": "Air.Gear.T26.FRENCH.CBZ.eBook-ebdz", "statut": "attente", "tomes": [26]}]
                suivi.ecrire(d)
                demandes = []

                def chercher(q):
                    demandes.append(q)
                    return [{"titre": "Air Gear Unlimited T06 Oh Great FR [CBZ]-Dogbanov", "badges": ["🇫🇷 FR"]},
                            {"titre": "Air Gear T24 FRENCH CBZ eBook-ebdz", "badges": ["🇫🇷 FR"]}]
                nouv = suivi.verifier("Air Gear Unlimited", chercher, lambda n: {"tomes": {1, 2, 3, 4, 5}})
                self.assertEqual(demandes, ["Air Gear Unlimited"])
                self.assertEqual([p["titre"] for p in nouv], ["Air Gear Unlimited T06 Oh Great FR [CBZ]-Dogbanov"])
                self.assertEqual(suivi.proposition("Air Gear Unlimited", "x")["statut"], "ignore")
            finally:
                suivi._ETAT["fichier"], suivi.AUTRES_SERIES = ancien, hook


if __name__ == "__main__":
    unittest.main()
