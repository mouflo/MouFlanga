import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

import prechauffage as P


class PrechauffageTest(unittest.TestCase):
    def setUp(self):
        # la préparation automatique ne tourne que de minuit à 6 h : ces tests vérifient la logique, pas l'heure
        patch = unittest.mock.patch.object(P.plage, "dans_la_plage", return_value=True)
        patch.start()
        self.addCleanup(patch.stop)
        with P._VERROU:                                  # un test précédent peut avoir laissé une préparation en cours
            P._FILE.clear()
            P._ETAT.update(en_cours=False, manuel=False)

    def test_preparation_automatique_attend_hors_plage(self):
        with tempfile.TemporaryDirectory() as t:
            faits = []
            P.configurer(Path(t) / "p.json", lambda: {"A": [], "(Sans série)": []}, lambda n: "1",
                         lambda n, prog: faits.append(n), lambda: [])
            # hors plage deux fois de suite, puis dans la plage : la série n'est préparée qu'à la troisième vérification
            heures = iter([False, False])
            with unittest.mock.patch.object(P.plage, "dans_la_plage", side_effect=lambda: next(heures, True)), \
                    unittest.mock.patch.object(P.time, "sleep", lambda s: None):
                P._ETAT["manuel"] = False
                P.demander(["A"])
                for _ in range(100):
                    if not P.etat()["en_cours"]:
                        break
                    time.sleep(0.05)
            self.assertEqual(faits, ["A"])

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
