"""Pilote : ce que l'appli fait toute seule sur un tome qui arrive (file d'attente, tomes connus, journal)."""
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import pilote as P


class Base(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        self.fichier = Path(self.dossier.name) / "pilote.json"
        self.biblio = {"A": {"1": "10|1", "2": "20|1"}, "B": {"1": "30|1"}}
        self.faits = []
        self.reponse = {"fait": ["chapitres lus"]}
        self.occupe = {}
        self.reglages = {"actif": True, "quand": "arrivee"}
        self.nuit = unittest.mock.patch.object(P.plage, "dans_la_plage", return_value=False)
        self.nuit.start()
        self.addCleanup(self.nuit.stop)
        self._configurer()
        self.addCleanup(P._CFG.clear)

    def _configurer(self):
        P.configurer(self.fichier, lambda: list(self.biblio), lambda nom: self.biblio.get(nom, {}), self._traiter,
                     lambda nom: self.occupe.get(nom, ""), lambda: self.reglages)

    def _traiter(self, nom, tome, quoi, avance, element):
        self.faits.append((nom, tome, quoi))
        avance("lecture")
        if isinstance(self.reponse, Exception):
            raise self.reponse
        return self.reponse

    def _vider(self):
        while P.un_pas():
            pass


class ControleTest(Base):
    def test_premier_lancement_tout_est_connu_rien_n_est_traite(self):
        self.assertEqual(P.controler(), 0)
        self.assertEqual(P.en_file(), [])
        self.assertFalse(P.un_pas())
        self.assertEqual(self.faits, [])
        self.assertTrue(self.fichier.exists())

    def test_nouveau_tome_pris_quand_son_fichier_ne_bouge_plus(self):
        P.controler()
        self.biblio["A"]["3"] = "5|1"                       # copie en cours
        self.assertEqual(P.controler(), 0)
        self.biblio["A"]["3"] = "30|2"                      # elle a grossi : on attend encore
        self.assertEqual(P.controler(), 0)
        self.assertEqual(P.controler(), 1)                  # identique deux fois de suite
        self.assertEqual([(e["serie"], e["tome"], e["quoi"]) for e in P.en_file()], [("A", "3", "tout")])
        self.assertEqual(P.controler(), 0)                  # une seule fois
        self._vider()
        self.assertEqual(self.faits, [("A", "3", "tout")])
        self.assertEqual(P.en_file(), [])

    def test_tome_connu_reecrit_n_est_pas_repris(self):
        P.controler()
        self.biblio["A"]["1"] = "11|9"                      # l'appli a réécrit le tome (chapitres, allègement…)
        self.assertEqual(P.controler(), 0)
        self.assertEqual(P.controler(), 0)
        self.assertEqual(P.en_file(), [])

    def test_serie_renommee_reste_connue(self):
        P.controler()
        self.biblio["Nouveau nom"] = self.biblio.pop("A")
        self.assertEqual(P.controler(), 0)
        self.assertEqual(P.controler(), 0)
        self.assertEqual(P.en_file(), [])

    def test_serie_ajoutee_plus_tard_entierement_traitee(self):
        P.controler()
        self.biblio["C"] = {"1": "1|1", "2": "2|1"}
        P.controler()
        self.assertEqual(P.controler(), 2)
        self.assertEqual(sorted(e["tome"] for e in P.en_file("C")), ["1", "2"])

    def test_bibliotheque_pas_montee_on_ne_conclut_rien(self):
        P.controler()
        garde, self.biblio = self.biblio, {}
        self.assertEqual(P.controler(), 0)
        self.biblio = garde
        self.assertEqual(P.controler(), 0)                  # tout est encore connu
        self.assertEqual(P.controler(), 0)
        self.assertEqual(P.en_file(), [])

    def test_tome_qui_disparait_puis_revient_reste_connu(self):
        P.controler()
        tome = self.biblio["A"].pop("2")
        P.controler()
        self.biblio["A"]["2"] = tome
        P.controler()
        self.assertEqual(P.controler(), 0)

    def test_file_gardee_apres_un_redemarrage(self):
        P.controler()
        P.signaler("A", [1])
        self._configurer()                                   # « redémarrage » : tout est relu dans le fichier
        self.assertEqual([(e["serie"], e["tome"]) for e in P.en_file()], [("A", "1")])
        self.assertEqual(P.controler(), 0)                   # et les tomes connus aussi
        self.assertEqual(len(P.en_file()), 1)

    def test_fichier_abime_repart_de_zero_sans_planter(self):
        self.fichier.write_text("{pas du json", encoding="utf-8")
        self._configurer()
        self.assertEqual(P.controler(), 0)
        self.assertEqual(P.en_file(), [])


class SignalerTest(Base):
    def test_tome_connu_signale_et_drapeau_remplace(self):
        P.controler()
        self.assertEqual(P.signaler("A", [1, 2.0], remplaces={1}), 2)
        file = {e["tome"]: e for e in P.en_file("A")}
        self.assertTrue(file["1"]["remplace"])
        self.assertFalse(file["2"]["remplace"])

    def test_deux_demandes_pour_le_meme_tome_n_en_font_qu_une(self):
        P.signaler("A", [1], quoi="chapitres", nuit=True)
        self.assertEqual(P.signaler("A", [1], quoi="uniformiser", manuel=True, remplaces=[1]), 0)
        (e,) = P.en_file()
        self.assertEqual((e["quoi"], e["manuel"], e["nuit"], e["remplace"]), ("tout", True, False, True))

    def test_un_tome_signale_n_est_pas_repris_comme_nouveau(self):
        P.controler()
        self.biblio["A"]["3"] = "30|2"
        P.signaler("A", [3])
        self._vider()
        P.controler()
        self.assertEqual(P.controler(), 0)
        self.assertEqual(self.faits, [("A", "3", "tout")])

    def test_cle_des_tomes(self):
        self.assertEqual([P._cle(x) for x in (3, 3.0, "3", 3.5, "03")], ["3", "3", "3", "3.5", "3"])


class TraiterTest(Base):
    def test_demande_a_la_main_passe_devant(self):
        P.signaler("A", [1])
        P.signaler("B", [1], manuel=True)
        self._vider()
        self.assertEqual([f[0] for f in self.faits], ["B", "A"])

    def test_la_nuit_seulement(self):
        self.reglages["quand"] = "nuit"
        P.signaler("A", [1])
        self.assertFalse(P.un_pas())
        self.assertIn("minuit", P.etat()["attente"])
        P.signaler("B", [1], manuel=True)                   # une demande à la main n'attend pas la nuit
        self._vider()
        self.assertEqual(self.faits, [("B", "1", "tout")])
        self.nuit.stop()
        with unittest.mock.patch.object(P.plage, "dans_la_plage", return_value=True):
            self._vider()
        self.nuit.start()
        self.assertEqual(self.faits, [("B", "1", "tout"), ("A", "1", "tout")])

    def test_demande_marquee_nuit(self):
        P.signaler("A", [1], quoi="chapitres", nuit=True)   # rattrapage : la nuit, même si le réglage dit « à l'arrivée »
        self.assertFalse(P.un_pas())
        self.assertEqual(self.faits, [])

    def test_automatisations_coupees(self):
        self.reglages["actif"] = False
        P.signaler("A", [1])
        self.assertFalse(P.un_pas())
        self.assertIn("coupées", P.etat()["attente"])
        P.signaler("A", [2], manuel=True)
        self._vider()
        self.assertEqual(self.faits, [("A", "2", "tout")])

    def test_serie_occupee_les_autres_passent(self):
        self.occupe["A"] = "allègement"
        P.signaler("A", [1])
        P.signaler("B", [1])
        self._vider()
        self.assertEqual(self.faits, [("B", "1", "tout")])
        self.assertEqual([e["serie"] for e in P.en_file()], ["A"])
        self.assertIn("occupée", P.etat()["attente"])

    def test_appli_occupee_personne_ne_passe(self):
        self.occupe[""] = "import d'archives"
        P.signaler("A", [1], manuel=True)
        self.assertFalse(P.un_pas())
        self.assertEqual(self.faits, [])
        self.assertIn("import d'archives", P.etat()["attente"])

    def test_journal(self):
        self.reponse = {"fait": ["12 chapitres placés"], "attend": ["2 chapitres à vérifier"]}
        P.signaler("A", [1])
        self._vider()
        (ligne,) = P.journal()
        self.assertEqual((ligne["serie"], ligne["tome"], ligne["fait"], ligne["attend"], ligne["erreur"]),
                         ("A", "1", ["12 chapitres placés"], ["2 chapitres à vérifier"], ""))
        self.assertRegex(ligne["date"], r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertEqual(P.journal(serie="B"), [])

    def test_rien_a_dire_rien_dans_le_journal(self):
        self.reponse = None
        P.signaler("A", [1])
        self._vider()
        self.assertEqual(P.journal(), [])
        self.assertEqual(P.en_file(), [])

    def test_erreur_notee_et_tome_retire(self):
        self.reponse = ValueError("fichier illisible")
        P.signaler("A", [1])
        with self.assertLogs("mouflanga", level="WARNING"):
            self.assertTrue(P.un_pas())
        self.assertFalse(P.un_pas())
        self.assertEqual(len(self.faits), 1)                # pas de boucle
        self.assertEqual(P.journal()[0]["erreur"], "fichier illisible")

    def test_report_puis_abandon(self):
        self.reponse = {"reporter": "lecture trop longue"}
        P.signaler("A", [1])
        t = 1000.0
        self.assertTrue(P.un_pas(t))
        self.assertFalse(P.un_pas(t + 10))                  # pas avant quelques minutes
        self.assertEqual(len(self.faits), 1)
        self.assertTrue(P.un_pas(t + P.REPORT + 1))
        self.assertTrue(P.un_pas(t + 2 * P.REPORT + 2))
        self.assertEqual(len(self.faits), 3)
        self.assertEqual(P.en_file(), [])
        self.assertIn("abandonné après 3 essais", P.journal()[0]["erreur"])

    def test_redemande_pendant_le_traitement_reste_en_file(self):
        def traiter(nom, tome, quoi, avance, element):
            self.faits.append((nom, tome, quoi))
            if len(self.faits) == 1:
                P.signaler(nom, [tome], remplaces=[tome])    # le tome est remplacé pendant qu'on le traite
            return {"fait": ["ok"]}

        P._CFG["traiter"] = traiter
        P.signaler("A", [1])
        self._vider()
        self.assertEqual(len(self.faits), 2)                 # refait une fois, avec le nouveau fichier
        self.assertEqual(P.en_file(), [])

    def test_retirer(self):
        P.signaler("A", [1, 2], quoi="chapitres")
        P.signaler("B", [1], quoi="uniformiser")
        self.assertEqual(P.retirer("A"), 2)
        self.assertEqual([e["serie"] for e in P.en_file()], ["B"])
        self.assertEqual(P.retirer(quoi="chapitres"), 0)
        self.assertEqual(P.retirer(), 1)

    def test_etat(self):
        P.signaler("A", [1, 2])
        e = P.etat()
        self.assertEqual((e["en_cours"], e["file"]), (False, 2))


if __name__ == "__main__":
    unittest.main()
