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
            sommaire._avancer(b"a")
            sommaire._avancer(b"b")
            sommaire._avancer(b"a")                              # même page relue : comptée une fois
        finally:
            sommaire._LOCAL.cle = None
        self.assertEqual(sommaire.etat("T-pages", 1)["pages"], 2)


if __name__ == "__main__":
    unittest.main()


class Richesse(unittest.TestCase):
    def test_lecture_plus_pauvre_moins_riche(self):
        import app
        riche = {"chapitres": [{"num": 1, "titre": "Trick 1", "image": 8}, {"num": 2, "titre": "Trick 2", "image": 26}]}
        pauvre = {"chapitres": [{"num": 1, "titre": "", "image": None}, {"num": 2, "titre": "", "image": None}]}
        self.assertGreater(app._richesse(riche), app._richesse(pauvre))
        onze_sans_pages = {"chapitres": [{"num": n, "titre": "Trick %d" % n, "image": None} for n in range(11)]}
        dix_avec_pages = {"chapitres": [{"num": n, "titre": "", "image": 30 + n} for n in range(10)]}
        self.assertGreater(app._richesse(dix_avec_pages), app._richesse(onze_sans_pages))


class HorsTome(unittest.TestCase):
    def _rangees(self, nums):
        return [{"num": float(n), "titre": "", "page": 10 + 16 * i} for i, n in enumerate(nums)]

    def test_ligne_de_bord_hors_liste_ecartee(self):
        lignes = self._rangees(range(267, 278))                    # 267 : design de l'insigne, pas un chapitre du tome
        r = sommaire._ecarter_hors_tome(lignes, [float(n) for n in range(268, 278)])
        self.assertEqual([c["num"] for c in r], [float(n) for n in range(268, 278)])

    def test_rien_ecarte_si_le_reste_ne_colle_pas(self):
        lignes = self._rangees([267, 270, 271, 272, 273])           # liste du tome incomplète : on ne devine pas
        self.assertEqual(sommaire._ecarter_hors_tome(lignes, [268.0, 269.0, 270.0, 271.0, 272.0, 273.0]), lignes)
