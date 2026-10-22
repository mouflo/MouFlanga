"""Avancement de la ré-identification : chaque étape est notée, une étape en erreur ne bloque pas les autres, une étape qui
attend un service est « en attente » (jamais « échec »), et rien n'est effacé."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as A  # noqa: E402
import identification as I  # noqa: E402


class AvancementTest(unittest.TestCase):
    def setUp(self):
        self.anciennes = dict(I._FONCTIONS)
        self.oublier = A.tomes.oublier
        self.oubliees = []
        A.tomes.oublier = lambda s: self.oubliees.append(s)

        def fiche_en_panne(serie, forcer=False):
            raise RuntimeError("réseau")
        I._FONCTIONS.update(
            statut=lambda s, f=False: I.Bilan("ok", "en cours · 19 tome(s) annoncés · résumé en français", None),
            liste_fr=lambda s, f=False: I.Bilan("ok", "10 tome(s), 60 titre(s) de chapitres", None),
            tomes=lambda s, f=False: I.Bilan("ok", "2 tome(s), 2 chapitre(s) répartis · source : Wikipédia", None),
            fiche=fiche_en_panne,
            notices=lambda s, f=False: I.Bilan("panne", "ISBN 0/2 · Google Books n'a pas répondu", time.time() + 3600, {"attente": True, "isbn_manquants": [1, 2]}))
        self.rangement, self.sans_isbn = A._rangement_complet, A._tomes_sans_isbn
        A._rangement_complet = lambda s, forcer=False: 3
        A._tomes_sans_isbn = lambda s, tout=False, auto=False: [(1, Path("x"))]

    def tearDown(self):
        I._FONCTIONS.clear()
        I._FONCTIONS.update(self.anciennes)
        A.tomes.oublier = self.oublier
        A._rangement_complet, A._tomes_sans_isbn = self.rangement, self.sans_isbn

    def lancer(self, **kw):
        A._relancer_identification("Série test", relire_fichiers=False, **kw)
        for _ in range(200):
            if A._IDENTIFICATIONS["Série test"]["fini"]:
                break
            time.sleep(0.05)
        return A._IDENTIFICATIONS["Série test"]["etapes"]

    def test_etapes_echec_et_attente(self):
        etapes = self.lancer()
        self.assertTrue(A._IDENTIFICATIONS["Série test"]["fini"])
        self.assertEqual([e["etat"] for e in etapes], ["ok", "ok", "ok", "echec", "reprise", "ok", "reprise"])
        self.assertIn("19 tome(s) annoncés", etapes[0]["detail"])
        self.assertIn("2 tome(s), 2 chapitre(s) répartis", etapes[2]["detail"])
        self.assertIn("Google Books n'a pas répondu", etapes[4]["detail"])
        self.assertIn("on attend qu'Internet réponde", etapes[6]["detail"])        # pas de lecture des pages en attendant
        self.assertEqual(self.oubliees, [])                                       # une réidentification n'efface rien

    def test_nouvelle_identite_repart_de_zero(self):
        self.lancer(nouvelle_identite=True)
        self.assertEqual(self.oubliees, ["Série test"])


if __name__ == "__main__":
    unittest.main()
