"""📋 Où j'en suis, tome par tome : ce qui est fait sur chaque tome (doubles pages, parasites, image, uniformité, allègement)."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _jpeg(c):
    b = io.BytesIO()
    Image.new("RGB", (60, 80), (c, c, c)).save(b, "JPEG")
    return b.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "mangas"
        self.fichiers = {}
        for n in (1, 2, 3):
            d = self.root / "Serie" / f"Tome {n:02d}"
            d.mkdir(parents=True)
            f = d / f"Serie - Tome {n:02d}.cbz"
            with zipfile.ZipFile(f, "w") as z:
                for i in range(10):
                    z.writestr(f"{i:03d}.jpg", _jpeg(n * 10 + i))
            self.fichiers[n] = f
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        import auth
        self.A, self.auth = A, auth
        self._role = auth.role
        auth.role = lambda: "admin"
        A.MANGA_DIR = self.root
        A._scan_invalider()
        self.c = A.app.test_client()

    def tearDown(self):
        self.auth.role = self._role
        self.tmp.cleanup()

    def etat(self, tout=False):
        r = self.c.get("/api/series/etat", query_string={"series": "Serie", **({"tout": "1"} if tout else {})})
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def case(self, etat, tome, etape):
        return next(t for t in etat["tomes"] if t["tome"] == tome)["cases"][etape]

    def infos(self):
        import edition
        return edition.lire(self.root / "Serie")

    def ecrire(self, infos):
        import edition
        edition.ecrire(self.root / "Serie", infos)
        edition.invalider(self.root / "Serie")


class EtatTest(Base):
    def test_rien_de_fait_au_depart(self):
        e = self.etat()
        self.assertEqual(e["total"], 3)
        self.assertEqual([t["tome"] for t in e["tomes"]], [1, 2, 3])
        for etape in ("doubles", "parasites", "image", "allegement"):
            self.assertEqual(self.case(e, 1, etape)["etat"], "manque", etape)
        self.assertEqual(self.case(e, 1, "uniformise")["etat"], "inconnu")      # pas encore mesuré
        self.assertEqual(e["comptes"], {})
        self.assertEqual(e["resume"], "")                                        # rien de commencé : aucune ligne sur la fiche

    def test_serie_inconnue(self):
        self.assertEqual(self.c.get("/api/series/etat", query_string={"series": "Nope"}).status_code, 404)
        self.assertEqual(self.c.post("/api/series/etat/marquer", json={"series": "Nope", "etape": "image", "tomes": [1], "fait": True}).status_code, 404)

    def test_liste_des_etapes(self):
        e = self.etat()
        cles = [x["cle"] for x in e["etapes"]]
        self.assertEqual(cles, [k for k, _ in self.A.TRAVAIL])                    # les mêmes étapes que le pense-bête à cocher
        for k in ("parasites", "image", "uniformise", "allegement", "doubles"):
            self.assertIn(k, cles)
        self.assertTrue(next(x for x in e["etapes"] if x["cle"] == "image")["cochable"])
        self.assertFalse(next(x for x in e["etapes"] if x["cle"] == "uniformise")["cochable"])

    def test_identification_seulement_a_la_demande(self):
        self.assertNotIn("isbn", self.etat()["tomes"][0]["cases"])
        e = self.etat(tout=True)
        for cle in ("resumes", "isbn", "titres", "liens", "couvertures", "reecriture"):
            self.assertIn(cle, e["tomes"][0]["cases"])
        infos = self.infos()
        infos["isbn"] = {"2": "9782505013112"}
        self.ecrire(infos)
        self.A._CACHE_EDITION.clear()
        e = self.etat(tout=True)
        self.assertEqual(self.case(e, 2, "isbn")["etat"], "fait")
        self.assertEqual(self.case(e, 1, "isbn")["etat"], "manque")
        self.assertEqual(e["comptes"]["isbn"], 1)


class TomesAssemblesTest(Base):
    """Air Gear : une entrée par chapitre, toutes du groupe « Tome NN » et du même fichier de tome."""

    def test_tomes_assembles_par_l_appli(self):
        from unittest import mock
        def entree(t, n):
            return {"key": f"#{n}", "path": f"Serie/Tome {t:02d}/Serie - Tome {t:02d}.cbz", "groupe": f"Tome {t:02d}", "num": float(n), "tome": None}
        entrees = [entree(1, 0), entree(1, 1), entree(1, 2), entree(2, 3), entree(2, 4)]
        entrees.append({"key": "Serie/Tome 03/a.cbz", "path": "Serie/Tome 03/a.cbz", "groupe": "Tome 03"})        # chapitres en fichiers séparés :
        entrees.append({"key": "Serie/Tome 03/b.cbz", "path": "Serie/Tome 03/b.cbz", "groupe": "Tome 03"})        # pas un fichier de tome
        entrees.append({"key": "Serie/hs.cbz", "path": "Serie/hs.cbz", "groupe": "Hors-série", "hs": 1001})
        with mock.patch.object(self.A, "_entrees", return_value=entrees):
            r = self.A._fichiers_des_tomes("Serie")
        self.assertEqual(sorted(r), [1, 2])
        self.assertEqual(r[1], self.root / "Serie/Tome 01/Serie - Tome 01.cbz")


class CocherAMainTest(Base):
    def marquer(self, etape, tomes, fait=True):
        return self.c.post("/api/series/etat/marquer", json={"series": "Serie", "etape": etape, "tomes": tomes, "fait": fait})

    def test_cocher_puis_decocher(self):
        r = self.marquer("image", [1, 3]).get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["changes"], 2)
        self.assertEqual(r["comptes"]["image"], 2)
        e = self.etat()
        self.assertEqual(self.case(e, 1, "image")["etat"], "fait")
        self.assertTrue(self.case(e, 1, "image")["manuel"])
        self.assertEqual(self.case(e, 2, "image")["etat"], "manque")
        self.assertEqual(e["resume"], "✨ 2/3")
        self.assertEqual(self.marquer("image", [1], fait=False).get_json()["changes"], 1)
        self.assertEqual(self.case(self.etat(), 1, "image")["etat"], "manque")

    def test_une_etape_mesuree_ne_se_coche_pas(self):
        self.assertEqual(self.marquer("uniformise", [1]).status_code, 400)
        self.assertEqual(self.marquer("isbn", [1]).status_code, 400)

    def test_tome_inconnu(self):
        self.assertEqual(self.marquer("image", [42]).status_code, 400)
        self.assertEqual(self.marquer("image", []).status_code, 400)

    def test_un_tome_remplace_perd_ses_marques(self):
        self.marquer("image", [1])
        f = self.fichiers[1]
        with zipfile.ZipFile(f, "w") as z:                    # une autre version du tome 1 : beaucoup plus grosse
            for i in range(40):
                z.writestr(f"{i:03d}.jpg", _jpeg(i) + os.urandom(3000))
        self.A._scan_invalider()
        self.assertEqual(self.case(self.etat(), 1, "image")["etat"], "manque")

    def test_remplacer_efface_la_memoire_de_l_ancien_fichier(self):
        self.marquer("image", [2])
        self.A._oublier_traitements("Serie", self.fichiers[2].name)
        self.assertEqual(self.case(self.etat(), 2, "image")["etat"], "manque")

    def test_reserve_a_l_administrateur(self):
        self.auth.role = lambda: "lecteur"
        # la liste blanche des lecteurs ne contient ni la lecture ni l'écriture de cet état
        self.assertNotIn(("GET", "/api/series/etat"), self.auth.LECTEUR_OK)
        self.assertNotIn(("POST", "/api/series/etat/marquer"), self.auth.LECTEUR_OK)


class AnciennesMarquesTest(Base):
    def test_doubles_coupees_et_parasites_verifies(self):
        infos = self.infos()
        infos["doubles_coupees"] = {self.fichiers[1].name: {"date": "05/11/2026", "taille": self.fichiers[1].stat().st_size}}
        infos["parasites_verifies"] = {self.fichiers[2].name: self.fichiers[2].stat().st_size}
        self.ecrire(infos)
        e = self.etat()
        d = self.case(e, 1, "doubles")
        self.assertEqual((d["etat"], d["date"]), ("fait", "2026-11-05"))
        self.assertEqual(self.case(e, 2, "parasites")["etat"], "fait")
        self.assertEqual(self.case(e, 3, "parasites")["etat"], "manque")
        self.assertEqual(self.case(e, 2, "doubles")["etat"], "manque")

    def test_tome_assemble(self):
        self.A._marquer_assemble("Serie", self.fichiers[3])
        self.assertEqual(self.case(self.etat(), 3, "doubles")["etat"], "fait")

    def test_historique_d_allegement(self):
        f = self.fichiers[1]
        self.A.optimiser.HISTORIQUE = str(Path(self.tmp.name) / "historique.jsonl")
        taille = f.stat().st_size
        self.A.optimiser.noter_historique("Serie", "applique", f.name, taille * 2, taille)
        self.A.optimiser.noter_historique("Serie", "analyse", self.fichiers[2].name, taille * 2, taille)      # une analyse n'est pas un travail fait
        e = self.etat()
        self.assertEqual(self.case(e, 1, "allegement")["etat"], "fait")
        self.assertEqual(self.case(e, 2, "allegement")["etat"], "manque")


class MarquesDeTravailTest(Base):
    def test_un_travail_garde_les_marques_d_avant_malgre_le_changement_de_taille(self):
        f = self.fichiers[1]
        infos = self.infos()
        infos["doubles_coupees"] = {f.name: {"date": "05/11/2026", "taille": f.stat().st_size}}
        self.ecrire(infos)
        avant = self.A._avant_travail("Serie", [f])
        with zipfile.ZipFile(f, "w") as z:                    # l'allègement a réécrit le tome : beaucoup plus petit
            z.writestr("000.jpg", _jpeg(5))
        self.A._noter_travail("Serie", f, avant[f.name], {"allegement": {"detail": "qualité 85/100"}})
        self.A._scan_invalider()
        e = self.etat()
        self.assertEqual(self.case(e, 1, "allegement")["etat"], "fait")
        self.assertEqual(self.case(e, 1, "allegement")["detail"], "qualité 85/100")
        self.assertEqual(self.case(e, 1, "doubles")["etat"], "fait")        # la découpe d'avant n'est pas oubliée

    def test_faits_de_l_allegement(self):
        ligne = {"fichier": "T.cbz", "qualite": 85, "fidele": False, "octets_avant": 140_000_000, "octets_apres": 96_000_000}
        faits = self.A._faits_de_l_allegement(ligne, {"uniformiser": 1, "debruit": 0}, 1200)
        self.assertEqual(set(faits), {"uniformise", "allegement"})
        self.assertIn("qualité 85/100", faits["allegement"]["detail"])
        self.assertIn("1200 px", faits["allegement"]["detail"])
        self.assertIn("133,5 → 91,6 Mo", faits["allegement"]["detail"])
        faits = self.A._faits_de_l_allegement(ligne, {"debruit": 2, "uniformiser": 0}, None)
        self.assertEqual(set(faits), {"image", "allegement"})

    def test_meme_qualite_n_est_pas_un_allegement(self):
        ligne = {"fichier": "T.cbz", "qualite": 70, "fidele": True, "octets_avant": 100, "octets_apres": 100}
        self.assertEqual(set(self.A._faits_de_l_allegement(ligne, {"uniformiser": 1}, None)), {"uniformise"})
        self.assertEqual(self.A._faits_de_l_allegement(ligne, None, None), {})

    def test_tome_seulement_reecrit_pour_ses_infos(self):
        ligne = {"fichier": "T.cbz", "qualite": 0, "octets_avant": 100, "octets_apres": 101, "infos": True}
        self.assertEqual(self.A._faits_de_l_allegement(ligne, {"uniformiser": 1}, 1200), {})

    def test_uniformisation_ignoree_faute_de_mesure(self):
        ligne = {"fichier": "T.cbz", "qualite": 85, "fidele": True, "octets_avant": 100, "octets_apres": 100,
                 "alerte": "uniformisation ignorée : ce tome n'est pas encore mesuré"}
        self.assertEqual(self.A._faits_de_l_allegement(ligne, {"uniformiser": 1}, None), {})


if __name__ == "__main__":
    unittest.main()
