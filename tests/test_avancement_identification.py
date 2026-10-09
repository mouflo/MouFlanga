"""Avancement de la ré-identification : chaque étape est notée, et une étape en erreur ne bloque pas les autres."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as A  # noqa: E402


class AvancementTest(unittest.TestCase):
    def setUp(self):
        self.anciens = (A.tomes.oublier, A.tomes.chercher, A.tomes.statut_officiel, A.tomes.fiche)
        A.tomes.oublier = lambda s: None
        A.tomes.chercher = lambda s, forcer=False: {"source": "Wikipédia", "tomes": {1.0: 1, 2.0: 2}}
        A.tomes.statut_officiel = lambda s, forcer=False: {"statut": "RELEASING", "volumes": 19}

        def fiche_en_panne(s, forcer=False):
            raise RuntimeError("réseau")
        A.tomes.fiche = fiche_en_panne

    def tearDown(self):
        A.tomes.oublier, A.tomes.chercher, A.tomes.statut_officiel, A.tomes.fiche = self.anciens

    def test_etapes_et_echec(self):
        A._relancer_identification("Série test")
        for _ in range(100):
            if A._IDENTIFICATIONS["Série test"]["fini"]:
                break
            time.sleep(0.05)
        etapes = A._IDENTIFICATIONS["Série test"]["etapes"]
        self.assertTrue(A._IDENTIFICATIONS["Série test"]["fini"])
        self.assertEqual([e["etat"] for e in etapes], ["ok", "ok", "ok", "echec"])
        self.assertIn("2 tome(s) trouvés", etapes[1]["detail"])
        self.assertIn("19 tome(s) annoncés", etapes[2]["detail"])


if __name__ == "__main__":
    unittest.main()
