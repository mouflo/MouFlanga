"""Recherche sur tous les sites à la fois : une panne chez un site ne cache jamais les autres."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class RechercheGlobaleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MANGA_DIR"] = self.tmp.name
        sys.modules.pop("app", None)
        import app as A
        import auth
        self.A, self.auth = A, auth
        self._role = auth.role
        auth.role = lambda: "admin"
        A._RECHERCHES.clear()
        self.c = A.app.test_client()

    def tearDown(self):
        self.auth.role = self._role
        self.A._RECHERCHES.clear()
        self.tmp.cleanup()

    def _chercher(self, texte="golden kamuy", faux=None):
        A = self.A

        def par_site(autre, t):
            nom = autre.id if autre else "japscan"
            if nom == "pantheon":
                raise RuntimeError("le site ne répond pas")
            return faux(nom) if faux else ([{"title": "Golden Kamuy", "url": f"https://{nom}.test/gk", "id": f"{nom}-gk"}] if nom in ("japscan", "bluesolo") else [])
        with mock.patch.object(A, "_chercher_dans", side_effect=par_site):
            return self.c.post("/api/sources/recherche", json={"q": texte})

    def test_tous_les_sites_repondent_chacun_a_part(self):
        d = self._chercher().get_json()
        noms = {r["source"]: r for r in d["resultats"]}
        self.assertEqual(set(noms), {"japscan", *self.A.sources_fr.SOURCES})
        self.assertEqual(len(noms["japscan"]["mangas"]), 1)
        self.assertEqual(noms["bluesolo"]["mangas"][0]["source"], "bluesolo")
        self.assertEqual(noms["sushiscan"]["mangas"], [])
        self.assertEqual(noms["sushiscan"]["erreur"], "")

    def test_une_panne_est_dite_et_ne_cache_pas_les_autres(self):
        d = self._chercher().get_json()
        pan = next(r for r in d["resultats"] if r["source"] == "pantheon")
        self.assertIn("ne répond pas", pan["erreur"])
        self.assertEqual(pan["mangas"], [])
        self.assertEqual(len(next(r for r in d["resultats"] if r["source"] == "japscan")["mangas"]), 1)

    def test_texte_trop_court_refuse(self):
        r = self._chercher("a")
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
