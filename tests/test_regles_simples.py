"""Préférences simples des torrents : des cases en clair traduites en un profil, sans rien perdre des règles déjà là."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import regles  # noqa: E402
import regles_simples as S  # noqa: E402

GO = 1024 ** 3


def r(titre, taille=GO, sources=10):
    mots = titre.replace(".", " ").upper().split()
    badges = (["FR"] if "FR" in mots or "FRENCH" in mots else []) + (["Digital"] if "DIGITAL" in mots else [])
    return {"titre": titre, "taille": taille, "sources": sources, "indexeur": "C411", "badges": badges}


class Base(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.ancien = regles.FICHIER
        regles.FICHIER = Path(self.dossier.name) / "regles.json"

    def tearDown(self):
        regles.FICHIER = self.ancien
        self.dossier.cleanup()

    def tri(self, titres, serie=""):
        res = regles.filtrer([r(t) if isinstance(t, str) else t for t in titres], serie, avec_rejets=True)
        return sorted(res, key=lambda x: (bool(x["rejet"]), -x["score"]))      # comme la page : refusés en dernier, puis le score


class PreferencesTest(Base):
    def test_rien_d_enregistre_rien_ne_change(self):
        e = S.etat()
        self.assertFalse(e["enregistre"])
        self.assertFalse(e["actif"])
        self.assertEqual(e["prefs"]["francais"], "obligatoire")
        self.assertFalse(regles.FICHIER.exists())

    def test_francais_obligatoire(self):
        S.enregistrer({})
        res = {x["titre"]: x for x in self.tri(["Kaf T01 FR CBZ", "Kaf 01 (2020)", "Kaf T02 VOSTFR"])}
        self.assertFalse(res["Kaf T01 FR CBZ"].get("rejet"))
        self.assertIn("français", res["Kaf 01 (2020)"]["rejet"])
        self.assertTrue(res["Kaf T02 VOSTFR"]["rejet"])

    def test_francais_prefere_garde_les_sans_indice(self):
        S.enregistrer({"francais": "prefere"})
        res = self.tri(["Kaf 01 (2020)", "Kaf T01 FR CBZ"])
        self.assertEqual(res[0]["titre"], "Kaf T01 FR CBZ")
        self.assertFalse(res[1].get("rejet"))

    def test_pdf_refuse_puis_accepte(self):
        S.enregistrer({})
        (x,) = self.tri(["Kaf T01 FR PDF"])
        self.assertIn("PDF", x["rejet"])
        S.enregistrer({"pdf": True})
        (x,) = self.tri(["Kaf T01 FR PDF"])
        self.assertFalse(x.get("rejet"))

    def test_sans_source(self):
        S.enregistrer({})
        (x,) = self.tri([r("Kaf T01 FR", sources=0)])
        self.assertIn("personne", x["rejet"])
        S.enregistrer({"sans_source": True})
        (x,) = self.tri([r("Kaf T01 FR", sources=0)])
        self.assertFalse(x.get("rejet"))

    def test_taille(self):
        S.enregistrer({"taille_max_go": "2"})
        (x,) = self.tri([r("Kaf T01 FR", taille=3 * GO)])
        self.assertTrue(x["rejet"])
        with self.assertRaises(ValueError):
            S.enregistrer({"taille_max_go": "beaucoup"})

    def test_equipes(self):
        S.enregistrer({"equipes_plus": "PapriKa, Neo Rip Club", "equipes_moins": "Mechant"})
        res = self.tri(["Kaf T01 FR CBZ-Autre", "Kaf.T01.FRENCH.CBZ.eBook-NEO.RIP-Club", "Kaf T01 FR CBZ-Mechant"])
        self.assertIn("NEO.RIP", res[0]["titre"])
        self.assertIn("Mechant", res[-1]["rejet"])
        self.assertEqual(S.etat()["prefs"]["equipes_plus"], ["PapriKa", "Neo Rip Club"])

    def test_equipe_refusee_en_plusieurs_mots(self):
        S.enregistrer({"equipes_moins": "Neo Rip Club"})
        (x,) = self.tri(["Kaf.T01.FRENCH.CBZ.eBook-NEO.RIP-Club"])
        self.assertIn("refuses", x["rejet"])
        self.assertEqual(S.etat()["prefs"]["equipes_moins"], ["Neo Rip Club"])

    def test_officiel_et_integrale_passent_devant(self):
        S.enregistrer({})
        res = self.tri(["Kaf T01 FR CBZ", "Kaf T01 FR Digital CBZ"])
        self.assertIn("Digital", res[0]["titre"])

    def test_l_ancien_profil_general_est_desactive_pas_supprime(self):
        regles.enregistrer_profil("", "Manga · Français", True, "", "", [], "")
        out = S.enregistrer({})
        self.assertEqual(out["desactives"], ["Manga · Français"])
        ancien = next(p for p in regles.profils() if p["nom"] == "Manga · Français")
        self.assertFalse(ancien["actif"])
        self.assertTrue(S.etat()["actif"])
        self.assertEqual(regles.profil_pour("N'importe")["nom"], S.NOM)

    def test_un_profil_de_serie_a_la_main_garde_la_main(self):
        regles.enregistrer_profil("", "Dogbanov", True, "Dogbanov", "", ["Air Gear Unlimited"], "")
        S.enregistrer({})
        self.assertEqual(regles.profil_pour("Air Gear Unlimited")["nom"], "Dogbanov")
        self.assertEqual([x["nom"] for x in S.etat()["a_la_main"]], ["Dogbanov"])
        with self.assertRaises(ValueError):
            S.regler_serie("Air Gear Unlimited", "PapriKa")

    def test_enregistrer_deux_fois_ne_double_rien(self):
        S.enregistrer({})
        S.enregistrer({"pdf": True})
        self.assertEqual(sum(1 for p in regles.profils() if p["nom"] == S.NOM), 1)
        self.assertEqual(len({f["nom"] for f in regles.formats()}), len(regles.formats()))


class SerieTest(Base):
    def test_il_faut_des_preferences(self):
        with self.assertRaises(ValueError):
            S.regler_serie("Rave", "Neo Rip Club")

    def test_equipe_preferee_pour_une_serie_seulement(self):
        S.enregistrer({})
        i = S.regler_serie("Rave", "Neo Rip Club")
        titres = ["Rave T01 FR CBZ-Autre", "Rave.T01.FRENCH.CBZ.eBook-NEO.RIP-Club"]
        res = self.tri(titres, "Rave")
        self.assertIn("NEO.RIP", res[0]["titre"])
        self.assertFalse(res[1].get("rejet"))                       # les autres restent acceptés
        self.assertGreater(res[0]["score"] - res[1]["score"], 500)
        ailleurs = self.tri(titres, "Kaf")
        self.assertLess(abs(ailleurs[0]["score"] - ailleurs[1]["score"]), 500)
        self.assertEqual(S.etat()["series"], [{"id": i, "serie": "Rave", "equipe": "Neo Rip Club"}])

    def test_les_preferences_suivent_dans_les_series(self):
        S.enregistrer({})
        S.regler_serie("Rave", "Neo Rip Club")
        (x,) = self.tri(["Rave T01 FR PDF"], "Rave")
        self.assertTrue(x["rejet"])
        S.enregistrer({"pdf": True})
        (x,) = self.tri(["Rave T01 FR PDF"], "Rave")
        self.assertFalse(x.get("rejet"))
        self.assertEqual(len(S.etat()["series"]), 1)

    def test_equipe_refusee_aussi_dans_une_serie(self):
        S.enregistrer({"equipes_moins": "Mechant"})
        S.regler_serie("Rave", "Neo Rip Club")
        (x,) = self.tri(["Rave T01 FR CBZ-Mechant"], "Rave")
        self.assertIn("Mechant", x["rejet"])

    def test_retirer(self):
        S.enregistrer({})
        i = S.regler_serie("Rave", "Neo Rip Club")
        self.assertTrue(S.retirer_serie(i))
        self.assertFalse(S.retirer_serie(i))
        self.assertEqual(S.etat()["series"], [])
        self.assertEqual(regles.profil_pour("Rave")["nom"], S.NOM)

    def test_phrase(self):
        self.assertIn("français", S.phrase(S.DEFAUT))


if __name__ == "__main__":
    unittest.main()
