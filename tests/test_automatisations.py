"""🤖 Automatisations : réglage, routes, chapitres dans « où j'en suis », tome validé jamais touché."""
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import automatisations as au
import pilote
from tests.test_etat_serie import Base


class ReglageTest(unittest.TestCase):
    def test_valeurs_fausses_remplacees(self):
        r = au.valider({"actif": False, "quand": "midi", "chapitres": "oui", "inconnu": 1})
        self.assertEqual(r, dict(au.DEFAUT, actif=False))

    def test_lire_ecrire(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a.json"
            self.assertEqual(au.lire(f), au.DEFAUT)
            au.ecrire(f, {"quand": "nuit", "uniformiser": False})
            self.assertEqual(au.lire(f), dict(au.DEFAUT, quand="nuit", uniformiser=False))
            f.write_text("{abîmé", encoding="utf-8")
            self.assertEqual(au.lire(f), au.DEFAUT)

    def test_phrase(self):
        self.assertIn("coupées", au.phrase(dict(au.DEFAUT, actif=False)))
        self.assertTrue(au.phrase(au.DEFAUT).startswith("Dès qu'un tome arrive"))
        self.assertTrue(au.phrase(dict(au.DEFAUT, quand="nuit")).startswith("La nuit"))
        self.assertIn("aucun travail", au.phrase(dict(au.DEFAUT, chapitres=False, uniformiser=False)))


class RoutesTest(Base):
    def setUp(self):
        super().setUp()
        self.donnees = tempfile.TemporaryDirectory()
        self.addCleanup(self.donnees.cleanup)
        p = unittest.mock.patch.object(self.A, "DATA_DIR", Path(self.donnees.name))
        p.start()
        self.addCleanup(p.stop)
        pilote.configurer(Path(self.donnees.name) / "pilote.json", self.A._pilote_series, self.A._pilote_tomes,
                          lambda *a: None, lambda nom: "", lambda: self.A._automatisations())
        self.addCleanup(pilote._CFG.clear)

    def _sommaires(self, sommaires):
        import edition
        infos = edition.lire(self.root / "Serie")
        infos["sommaires"] = sommaires
        edition.ecrire(self.root / "Serie", infos)

    def _lu(self, **plus):
        return dict({"chapitres": [{"num": 1.0, "titre": "Un", "page": 3, "image": 2}, {"num": 2.0, "titre": "Deux", "page": 7, "image": 6}]}, **plus)

    def test_reglage(self):
        r = self.c.get("/api/automatisations").get_json()
        self.assertEqual(r["reglage"], au.DEFAUT)
        r = self.c.post("/api/automatisations", json={"reglage": {"quand": "nuit"}}).get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["reglage"]["quand"], "nuit")
        self.assertTrue(r["reglage"]["chapitres"])                     # le reste n'a pas bougé
        self.assertEqual(self.c.post("/api/automatisations", json={"action": "n'importe quoi"}).status_code, 400)

    def test_rattraper_seulement_les_sommaires_imprimes_non_valides(self):
        self._sommaires({"1": self._lu(), "2": self._lu(valide_le="2026-11-01"), "3": self._lu(confirmation={"date": "x"})})
        r = self.c.post("/api/automatisations", json={"action": "rattraper"}).get_json()
        self.assertEqual([(e["tome"], e["quoi"], e["nuit"]) for e in pilote.en_file()], [("1", "chapitres", True)], r)
        r = self.c.post("/api/automatisations", json={"action": "arreter"}).get_json()
        self.assertEqual(pilote.en_file(), [])
        self.assertIn("1 tome", r["message"])

    def test_automatiser_une_serie(self):
        self.assertEqual(self.c.post("/api/series/automatiser", json={"series": "Inconnue"}).status_code, 404)
        r = self.c.post("/api/series/automatiser", json={"series": "Serie", "quoi": "chapitres"}).get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["file"], 3)
        self.assertTrue(all(e["manuel"] and e["quoi"] == "chapitres" for e in pilote.en_file("Serie")))
        self.assertIn("déjà", self.c.post("/api/series/automatiser", json={"series": "Serie"}).get_json()["message"])

    def test_chapitres_dans_l_etat_de_la_serie(self):
        self._sommaires({"1": self._lu(valide_le="2026-11-01"), "2": self._lu(source="pages d'ouverture")})
        ch = self.etat()["chapitres"]
        self.assertEqual(ch["par_tome"]["1"]["niveau"], "valide")
        self.assertEqual([t["tome"] for t in ch["a_verifier"]], [2])
        self.assertTrue(ch["a_verifier"][0]["fichier"].endswith("Serie - Tome 02.cbz"))
        self.assertIn("à vérifier", ch["phrase"])
        self.assertEqual(ch["en_cours"], "")

    def test_tome_valide_jamais_touche(self):
        self._sommaires({"1": self._lu(valide_le="2026-11-01")})
        avant = json.dumps(self.infos(), sort_keys=True)
        with unittest.mock.patch.object(self.A, "_lire_sommaire") as lire:
            self.assertIsNone(self.A._pilote_chapitres("Serie", 1, True, lambda m: None, remplace=True))
        lire.assert_not_called()
        self.assertEqual(json.dumps(self.infos(), sort_keys=True), avant)

    def test_uniformiser_les_prochains_tomes(self):
        r = self.c.post("/api/uniformite", json={"series": "Serie", "action": "auto", "actif": True}).get_json()
        self.assertTrue(r["ok"], r)
        self.assertTrue(self.infos().get("uniformiser_auto"))
        self.assertTrue(self.c.get("/api/uniformite", query_string={"series": "Serie"}).get_json()["auto"])
        self.c.post("/api/uniformite", json={"series": "Serie", "action": "auto", "actif": False})
        self.assertFalse(self.infos().get("uniformiser_auto"))

    def test_tout_uniformiser_d_un_coup(self):
        self.assertEqual(self.c.post("/api/uniformite/tout", json={"series": "Inconnue"}).status_code, 404)
        with unittest.mock.patch.object(self.A, "_uniformiser_tout") as tout:
            r = self.c.post("/api/uniformite/tout", json={"series": "Serie"})
            self.assertTrue(r.get_json()["ok"])
            tout.assert_called_once_with("Serie")
            self.assertEqual(self.c.post("/api/uniformite/tout", json={"series": "Serie"}).status_code, 409)   # déjà en cours
        self.A._UNIF_TOUT.clear()


if __name__ == "__main__":
    unittest.main()
