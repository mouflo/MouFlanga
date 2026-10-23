"""Source (Scantrad, Scan, Digital…) par tome ; la source de la série suit quand tous les tomes sont renseignés."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as A  # noqa: E402


class PureTest(unittest.TestCase):
    def test_parse_tomes(self):
        p = range(1, 14)
        self.assertEqual(A._parse_tomes("1-10", p), set(range(1, 11)))
        self.assertEqual(A._parse_tomes("1 à 3, 5, 11-20", p), {1, 2, 3, 5, 11, 12, 13})
        self.assertEqual(A._parse_tomes("tous", p), set(p))
        self.assertEqual(A._parse_tomes("99", p), set())
        with self.assertRaises(ValueError):
            A._parse_tomes("les premiers", p)

    def test_serie_identique_partout_devient_la_source(self):
        i = {"sources_tomes": {"1": "Digital", "2": "Digital"}}
        A._recalcul_source(i, [1, 2])
        self.assertEqual(i["source_manuelle"], "Digital")

    def test_serie_mixte_puis_plus_mixte(self):
        i = {"sources_tomes": {"1": "Scantrad", "2": "Digital"}}
        A._recalcul_source(i, [1, 2])
        self.assertEqual(i["source_manuelle"], "Mixte")
        del i["sources_tomes"]["2"]
        A._recalcul_source(i, [1, 2])
        self.assertNotIn("source_manuelle", i)                 # il en manque un : « Mixte » ne tient plus

    def test_incomplet_ne_touche_pas_la_source_choisie(self):
        i = {"sources_tomes": {"1": "Digital"}, "source_manuelle": "Scantrad"}
        A._recalcul_source(i, [1, 2])
        self.assertEqual(i["source_manuelle"], "Scantrad")

    def test_resume(self):
        self.assertEqual(A._resume_sources_tomes({str(t): "Scantrad" for t in range(1, 11)} | {"11": "Digital", "12": "Digital", "13": "Digital"}),
                         "T1–T10 Scantrad · T11–T13 Digital")
        self.assertEqual(A._resume_sources_tomes({}), "")


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.avant = A.app.before_request_funcs.get(None, [])
        A.app.before_request_funcs[None] = []
        self.c = A.app.test_client()
        self.infos = {}
        self.ecrit = []
        import edition
        self.patches = [mock.patch.object(A, "_scan", return_value={"Gashiakuta": []}), mock.patch.object(A, "_tomes_presents", return_value=list(range(1, 14))),
                        mock.patch.object(edition, "lire", side_effect=lambda d: self.infos), mock.patch.object(edition, "ecrire", side_effect=lambda d, i: self.ecrit.append(dict(i)))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        A.app.before_request_funcs[None] = self.avant

    def poste(self, **kw):
        return self.c.post("/api/tome/source", json={"series": "Gashiakuta", **kw})

    def test_gashiakuta(self):
        r = self.poste(tomes="1-10", source="Scantrad")
        self.assertEqual(r.get_json()["ok"], True)
        self.assertEqual(self.infos["sources_tomes"]["10"], "Scantrad")
        self.assertNotIn("source_manuelle", self.infos)                       # 3 tomes sans source : la série ne change pas
        r = self.poste(tomes="11-13", source="Digital").get_json()
        self.assertEqual(self.infos["source_manuelle"], "Mixte")
        r = self.poste(tomes="1-10", source="Digital").get_json()
        self.assertEqual(self.infos["source_manuelle"], "Digital")             # tous validés pareil : la série passe en Digital
        self.assertIn("la série est « Digital »", r["message"])

    def test_erreurs(self):
        self.assertEqual(self.poste(tomes="abc", source="Digital").status_code, 400)
        self.assertEqual(self.poste(tomes="50", source="Digital").status_code, 400)
        self.assertEqual(self.c.post("/api/tome/source", json={"series": "Nope", "tomes": "1", "source": "x"}).status_code, 404)

    def test_effacer(self):
        self.poste(tomes="1-2", source="Scantrad")
        self.poste(tomes="1", source="")
        self.assertEqual(self.infos["sources_tomes"], {"2": "Scantrad"})
        self.poste(tomes="2", source="")
        self.assertNotIn("sources_tomes", self.infos)


if __name__ == "__main__":
    unittest.main()
