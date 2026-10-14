import tempfile
import time
import unittest
from pathlib import Path

import prechauffage as P


class PrechauffageTest(unittest.TestCase):
    def test_prepare_une_fois_puis_seulement_si_les_fichiers_changent(self):
        with tempfile.TemporaryDirectory() as t:
            sig = {"A": "1", "B": "1"}
            faits = []
            P.configurer(Path(t) / "p.json", lambda: {"A": [], "B": [], "(Sans série)": []}, lambda n: sig[n],
                         lambda n, prog: faits.append(n), lambda: [])
            self.assertEqual(sorted(P.a_preparer()), ["A", "B"])
            P.demander(["A", "B"])
            for _ in range(100):
                if not P.etat()["en_cours"]:
                    break
                time.sleep(0.05)
            self.assertEqual(sorted(faits), ["A", "B"])
            self.assertEqual(P.a_preparer(), [])
            sig["B"] = "2"
            self.assertEqual(P.a_preparer(), ["B"])
            self.assertEqual(sorted(P.a_preparer(forcer=True)), ["A", "B"])


if __name__ == "__main__":
    unittest.main()
