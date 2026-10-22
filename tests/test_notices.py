"""notices.py : ce qu'Internet dit de chaque tome, source par source ; l'accord de deux sources fait foi ; rien ne s'efface."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notices  # noqa: E402
import tomes  # noqa: E402

S = "Série test"


class NoticesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(tomes, "DOSSIER", Path(self.tmp.name))
        self.p.start()
        tomes._CACHE_FICHES.clear()

    def tearDown(self):
        self.p.stop()
        tomes._CACHE_FICHES.clear()
        self.tmp.cleanup()

    def test_deux_sources_d_accord_gagnent_sur_une_seule(self):
        notices.enregistrer(S, "google", {1: {"isbn": "9782000000011"}})
        notices.enregistrer(S, "bnf", {1: {"isbn": "9782000000028"}})
        notices.enregistrer(S, "wikipedia", {1: {"isbn": "9782000000028"}})
        i, sources, autres = notices.isbn_du_tome(notices.observations(S)["1"])
        self.assertEqual((i, sources, autres), ("9782000000028", ["wikipedia", "bnf"], ["9782000000011"]))

    def test_sans_accord_la_source_la_plus_sure(self):
        notices.enregistrer(S, "google", {2: {"isbn": "9782000000011"}})
        notices.enregistrer(S, "bnf", {2: {"isbn": "9782000000028"}})
        self.assertEqual(notices.isbn_du_tome(notices.observations(S)["2"])[0], "9782000000028")        # la BnF avant Google

    def test_autres_isbn_d_une_reimpression_comptent_pour_l_accord(self):
        notices.enregistrer(S, "bnf", {3: {"isbn": "9782000000011", "autres_isbn": ["9782000000028"]}})
        notices.enregistrer(S, "google", {3: {"isbn": "9782000000028"}})
        self.assertEqual(notices.isbn_du_tome(notices.observations(S)["3"])[0], "9782000000028")

    def test_une_nouvelle_recherche_ne_remplace_que_sa_source_et_ses_tomes(self):
        notices.enregistrer(S, "bnf", {1: {"isbn": "9782000000011", "resume": "Un résumé de la BnF assez long pour compter."}, 2: {"isbn": "9782000000028"}})
        notices.enregistrer(S, "bnf", {2: {"isbn": "9782000000035"}})                                   # le tome 1 n'est pas cité : il reste
        obs = notices.observations(S)
        self.assertEqual(obs["1"]["bnf"]["isbn"], "9782000000011")
        self.assertEqual(obs["2"]["bnf"]["isbn"], "9782000000035")

    def test_une_observation_vide_n_efface_rien(self):
        notices.enregistrer(S, "bnf", {1: {"isbn": "9782000000011"}})
        notices.enregistrer(S, "bnf", {1: {"isbn": "", "resume": ""}})
        self.assertEqual(notices.observations(S)["1"]["bnf"]["isbn"], "9782000000011")

    def test_sources_d_avant_lues_comme_des_observations(self):
        tomes.modifier(S, lambda b: b.update(
            titres_tomes={"details": {"1": {"isbn": "9782000000011", "titre": "Un"}}},
            resumes_tomes={"2": {"texte": "Un résumé Google Books trouvé avant, assez long pour compter comme résumé.", "date": 1}}))
        obs = notices.observations(S)
        self.assertEqual(obs["1"]["wikipedia"]["isbn"], "9782000000011")
        self.assertIn("Google Books trouvé avant", obs["2"]["google"]["resume"])

    def test_resume_wikipedia_puis_bnf_puis_google(self):
        notices.enregistrer(S, "google", {1: {"resume": "Le résumé de Google Books, assez long pour être gardé dans la liste."}})
        self.assertEqual(notices.resume_du_tome(S, 1)[1], "Google Books")
        notices.enregistrer(S, "bnf", {1: {"resume": "Le résumé de la BnF, lui aussi assez long pour être gardé dans la liste."}})
        self.assertEqual(notices.resume_du_tome(S, 1)[1], "BnF")
        tomes.modifier(S, lambda b: b.update(titres_tomes={"details": {"1": {"resume": "Le résumé de Wikipédia, assez long pour être gardé aussi."}}}))
        self.assertEqual(notices.resume_du_tome(S, 1)[1], "Wikipédia")

    def test_presentation_de_la_serie_repetee_n_est_pas_un_resume(self):
        intro = "Présentation générale de la série qui se répète sur chaque tome de la même façon. "
        for t in (1, 2, 3):
            notices.enregistrer(S, "google", {t: {"resume": intro + f"Dans ce tome {t}, le héros affronte un adversaire très particulier."}})
        texte, _ = notices.resume_du_tome(S, 2)
        self.assertIn("adversaire", texte)
        self.assertNotIn("Présentation générale", texte)

    def test_edition_differente_ignore_wikipedia_et_les_anciens_resumes(self):
        tomes.modifier(S, lambda b: b.update(titres_tomes={"details": {"1": {"isbn": "9782000000011"}}}, edition_differente=True))
        notices.enregistrer(S, "bnf", {1: {"isbn": "9782000000028"}})
        self.assertEqual(notices.isbn_du_tome(notices.observations(S)["1"])[0], "9782000000028")        # la BnF, d'après le nom de l'édition

    def test_manquants(self):
        notices.enregistrer(S, "bnf", {1: {"isbn": "9782000000011"}})
        self.assertEqual(notices.manquants(S, [1, 2, 3], "isbn"), [2, 3])
        self.assertEqual(notices.manquants(S, [1], "resume"), [1])


if __name__ == "__main__":
    unittest.main()
