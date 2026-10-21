import threading
import time
import unittest

import sommaire


class PrioriteSommaire(unittest.TestCase):
    def test_lecture_demandee_passe_devant_la_file_de_fond(self):
        pris = [sommaire._FILE.acquire(blocking=False) for _ in range(sommaire.SIMULTANES)]   # toutes les places de fond prises
        lu = threading.Event()
        vrai_lire = sommaire.lire
        sommaire.lire = lambda *a, **k: (lu.set() or {"chapitres": []})
        try:
            self.assertTrue(sommaire.lancer("T-prio", 1, "x", lambda i: b"", 1, lambda r: None, urgent=True))
            self.assertTrue(lu.wait(5), "la lecture demandée aurait dû démarrer sans attendre")
            self.assertTrue(sommaire.lancer("T-fond", 1, "x", lambda i: b"", 1, lambda r: None))
            time.sleep(0.3)
            e = sommaire.etat("T-fond", 1)
            self.assertTrue(e["en_cours"])
            self.assertTrue(e["message"].startswith("En attente"))       # la lecture de fond attend, et le dit
        finally:
            sommaire.lire = vrai_lire
            for p in pris:
                if p:
                    sommaire._FILE.release()
            time.sleep(0.5)

    def test_page_comptee_pendant_la_lecture(self):
        sommaire._ETAT[("T-pages", 1)] = {"en_cours": True, "message": "", "pages": 0}
        sommaire._LOCAL.cle = ("T-pages", 1)
        try:
            sommaire._avancer()
            sommaire._avancer()
        finally:
            sommaire._LOCAL.cle = None
        self.assertEqual(sommaire.etat("T-pages", 1)["pages"], 2)


if __name__ == "__main__":
    unittest.main()
