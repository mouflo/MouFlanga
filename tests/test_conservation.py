"""Conservation des infos de série : terminée = pour toujours, en cours = périodique, rien trouvé = réessais espacés."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tomes  # noqa: E402

J = 86400


class RegleTest(unittest.TestCase):
    def test_statut_serie_terminee_jamais_perime(self):
        st = {"date": time.time() - 400 * J, "statut": "FINISHED", "resume": "x" * 60, "resume_v": tomes.RESUME_VERSION, "synonymes": []}
        self.assertTrue(tomes.statut_a_jour(st))

    def test_statut_serie_en_cours_une_semaine(self):
        st = {"statut": "RELEASING", "resume": "x" * 60, "resume_v": tomes.RESUME_VERSION, "synonymes": []}
        self.assertTrue(tomes.statut_a_jour(dict(st, date=time.time() - 3 * J)))
        self.assertFalse(tomes.statut_a_jour(dict(st, date=time.time() - 8 * J)))

    def test_statut_vide_reessais_espaces(self):
        base = {"statut": None, "resume": "", "resume_v": tomes.RESUME_VERSION}
        self.assertFalse(tomes.statut_a_jour(dict(base, date=time.time() - 2 * J, essais=0)))     # 1er essai : demain
        self.assertTrue(tomes.statut_a_jour(dict(base, date=time.time() - 2 * J, essais=1)))      # 2e : 3 jours
        self.assertTrue(tomes.statut_a_jour(dict(base, date=time.time() - 20 * J, essais=3)))     # ensuite : 30 jours
        self.assertFalse(tomes.statut_a_jour(dict(base, date=time.time() - 31 * J, essais=9)))

    def test_garde_a_jour(self):
        fini = {"statut_officiel": {"statut": "FINISHED"}}
        en_cours = {"statut_officiel": {"statut": "RELEASING"}}
        vieux = {"date": time.time() - 100 * J}
        self.assertTrue(tomes.garde_a_jour(vieux, fini, 30 * J))
        self.assertFalse(tomes.garde_a_jour(vieux, en_cours, 30 * J))
        self.assertFalse(tomes.garde_a_jour(None, fini, 30 * J))


class EnregistrerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._d = tomes.DOSSIER
        tomes.DOSSIER = Path(self.tmp.name)

    def tearDown(self):
        tomes.DOSSIER = self._d
        self.tmp.cleanup()

    def test_la_repartition_n_efface_plus_la_fiche_ni_les_titres(self):
        tomes._fichier("S").write_text(json.dumps({
            "date": 1, "tomes": {"1": 1}, "fiche": {"date": 5, "auteurs": ["A"]},
            "titres_tomes": {"date": 5, "titres": {"1": "T"}, "details": {}, "v": 1},
            "resumes_tomes": {"1": {"texte": "r"}}, "statut_officiel": {"statut": "FINISHED"}, "intros": ["i"]}), encoding="utf-8")
        tomes._enregistrer("S", {"source": "wikipedia", "tomes": {1.0: 1}, "titres": {}})
        d = json.loads(tomes._fichier("S").read_text(encoding="utf-8"))
        for k in ("fiche", "titres_tomes", "resumes_tomes", "statut_officiel", "intros"):
            self.assertIn(k, d)
        self.assertNotIn("essais", d)

    def test_recherche_vide_compte_les_echecs(self):
        tomes._enregistrer("V", {"source": None})
        tomes._enregistrer("V", {"source": None})
        self.assertEqual(json.loads(tomes._fichier("V").read_text(encoding="utf-8"))["essais"], 2)


if __name__ == "__main__":
    unittest.main()
