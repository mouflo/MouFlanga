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


class MentionACoteDeLaPastille(unittest.TestCase):
    def test_page_avant_la_mention_du_createur_du_logo(self):
        """Air Gear tome 29 : « TRICK:267   7   KEI MACHIDA » est bien le chapitre 267, page 7 ; Kei Machida signe le logo."""
        texte = "SOMMAIRE\nDESIGN DE L'INSIGNE :\nTRICK:267 7 KEI MACHIDA\n" + "\n".join(
            f"TRICK:{n} {p}" for n, p in zip(range(268, 278), (31, 47, 65, 83, 99, 113, 127, 143, 157, 171)))
        r = sommaire._reparer_lignes(texte)
        self.assertEqual([c["num"] for c in r], [float(n) for n in range(267, 278)])
        self.assertEqual((r[0]["titre"], r[0]["page"], r[0].get("estimee")), ("", 7, None))
