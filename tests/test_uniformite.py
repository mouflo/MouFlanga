"""🎨 Uniformité des tomes d'une série, calage des noirs et des blancs, alignement des doubles pages et repérage des paires."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import optimiser  # noqa: E402
import uniformite  # noqa: E402


def page_bd(encre=(4, 4, 4), papier=(255, 255, 255), taille=(500, 700), graine=1):
    """Une page noir et blanc : papier, un grand aplat d'encre et quelques bulles, avec l'encre et le papier de la teinte voulue."""
    rng = np.random.default_rng(graine)
    a = np.zeros((taille[1], taille[0], 3), np.uint8)
    a[:] = papier
    a[100:300, 80:420] = encre
    for _ in range(6):
        cv2.circle(a, (int(rng.integers(60, 440)), int(rng.integers(320, 650))), int(rng.integers(20, 50)), tuple(int(x) for x in encre), -1)
    return Image.fromarray(a)


def tome(dossier, nom, encre=(4, 4, 4), papier=(255, 255, 255), pages=12):
    chemin = Path(dossier) / nom
    with zipfile.ZipFile(chemin, "w") as z:
        for i in range(pages):
            b = io.BytesIO()
            page_bd(encre, papier, graine=i).save(b, "JPEG", quality=95)
            z.writestr(f"c0001.00-p{i:03d}.jpg", b.getvalue())
    return chemin


NOIR, VIOLACE = (5, 5, 5), (36, 31, 33)


class MesureTest(unittest.TestCase):
    def test_page_mesuree_noir_blanc_et_teinte(self):
        m = uniformite.mesurer_page(page_bd(VIOLACE))
        self.assertAlmostEqual(m["encre"], 32, delta=3)
        self.assertGreater(m["blanc"], 250)
        self.assertEqual(uniformite.nom_teinte(m["teinte_encre"]), "violacée")
        neutre = uniformite.mesurer_page(page_bd(NOIR))
        self.assertEqual(uniformite.nom_teinte(neutre["teinte_encre"]), "neutre")
        self.assertLess(neutre["encre"], 10)

    def test_page_couleur_ou_vide_ignoree(self):
        self.assertIsNone(uniformite.mesurer_page(page_bd((200, 30, 30), (255, 255, 255))))        # en couleur
        self.assertIsNone(uniformite.mesurer_page(Image.new("RGB", (300, 400), (255, 255, 255))))  # blanche : rien à mesurer

    def test_nom_de_teinte(self):
        self.assertEqual(uniformite.nom_teinte([2.0, -1.7, -0.4]), "violacée")
        self.assertEqual(uniformite.nom_teinte([2.0, 1.5, -3.5]), "jaunâtre")
        self.assertEqual(uniformite.nom_teinte([0.2, 0.1, -0.3]), "neutre")

    def test_tome_mesure_et_mis_en_memoire(self):
        with tempfile.TemporaryDirectory() as d:
            f = tome(d, "S - Tome 01.cbz", VIOLACE)
            s = uniformite.mesurer_tome(f)
            self.assertGreaterEqual(s["pages"], 8)
            self.assertAlmostEqual(s["encre"], 32, delta=3)
            cache = Path(d) / "u.json"
            uniformite._ecrire_cache(cache, {"tomes": {str(f): {"cle": uniformite._cle(f), "stats": s}}})
            self.assertEqual(uniformite.stats_en_memoire(cache, [f])[f.name]["pages"], s["pages"])
            with zipfile.ZipFile(f, "a") as z:                                  # le tome change : la mesure n'est plus reprise
                z.writestr("zz.txt", "x")
            self.assertEqual(uniformite.stats_en_memoire(cache, [f]), {})


def _s(encre, noir=None, blanc=255.0, teinte=(0, 0, 0), papier=(0, 0, 0)):
    return {"noir": float(encre if noir is None else noir), "encre": float(encre), "blanc": blanc,
            "teinte_encre": list(teinte), "teinte_papier": list(papier), "pages": 12}


class SerieTest(unittest.TestCase):
    def setUp(self):
        self.stats = {f"T{n:02d}.cbz": _s(5) for n in range(1, 5)}
        self.stats.update({f"T{n:02d}.cbz": _s(33, noir=26, teinte=(2.0, -1.7, -0.4)) for n in (5, 6)})
        self.lib = {n: n[:3] for n in self.stats}

    def test_groupes_et_tomes_a_uniformiser(self):
        r = uniformite.resumer(self.stats, self.lib)
        self.assertEqual([len(g["tomes"]) for g in r["groupes"]], [4, 2])
        self.assertEqual(r["reference"]["ref"], "groupe:A")                       # le plus nombreux
        self.assertEqual(r["a_uniformiser"], ["T05.cbz", "T06.cbz"])
        t5 = next(t for t in r["tomes"] if t["fichier"] == "T05.cbz")
        self.assertIn("noirs plus clairs", t5["ecarts"])
        self.assertIn("teinte violacée", t5["ecarts"])
        self.assertEqual(t5["teinte"], "violacée")
        self.assertTrue(t5["couleur_encre"].startswith("#") and len(t5["couleur_encre"]) == 7)
        self.assertIn("2 tomes sur 6", r["proposition"])

    def test_la_reference_peut_etre_l_autre_groupe_ou_un_tome(self):
        r = uniformite.resumer(self.stats, self.lib, "groupe:B")
        self.assertEqual(r["a_uniformiser"], ["T01.cbz", "T02.cbz", "T03.cbz", "T04.cbz"])
        self.assertIn("noirs plus profonds", next(t for t in r["tomes"] if t["fichier"] == "T01.cbz")["ecarts"])
        r = uniformite.resumer(self.stats, self.lib, "tome:T05.cbz")
        self.assertEqual(r["reference"]["libelle"], "T05")
        self.assertNotIn("T05.cbz", r["a_uniformiser"])
        r = uniformite.resumer(self.stats, self.lib, "groupe:Z")                  # référence inconnue : retour au plus nombreux
        self.assertEqual(r["reference"]["ref"], "groupe:A")

    def test_series_homogene_rien_a_signaler(self):
        r = uniformite.resumer({f"T{n}.cbz": _s(5 + n % 2) for n in range(6)}, {})
        self.assertEqual(r["a_uniformiser"], [])
        self.assertEqual(len(r["groupes"]), 1)
        self.assertEqual(r["proposition"], "")

    def test_tome_non_mesure_ou_en_couleur_laisse_de_cote(self):
        self.stats["T07.cbz"] = {"pages": 0, "couleur": 12}
        r = uniformite.resumer(self.stats, self.lib)
        self.assertNotIn("T07.cbz", [t["fichier"] for t in r["tomes"]])
        self.assertIsNone(uniformite.calage_du_tome(self.stats, "T07.cbz"))
        self.assertEqual(uniformite.resumer({}, {})["groupes"], [])

    def test_calage_ramene_plancher_noir_median_et_blanc(self):
        c = uniformite.calage_du_tome(self.stats, "T05.cbz")
        self.assertEqual((c["b0"], c["e0"], c["w0"]), (26.0, 33.0, 255.0))
        self.assertEqual((c["b1"], c["e1"], c["w1"]), (5.0, 5.0, 255.0))
        g = np.array([[26, 33, 255]], np.uint8)
        v = optimiser._caler(g, c)[0]
        self.assertLessEqual(abs(int(v[0]) - 5), 1)
        self.assertLessEqual(abs(int(v[1]) - 5), 1)
        self.assertEqual(int(v[2]), 255)
        lut = optimiser._caler(np.arange(256, dtype=np.uint8).reshape(1, 256), c)[0]
        self.assertTrue(np.all(np.diff(lut.astype(int)) >= 0))                    # une courbe, jamais de retour en arrière

    def test_reference_retenue_dans_le_cache(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "u.json"
            self.assertIsNone(uniformite.reference_choisie(cache, "S"))
            uniformite.choisir_reference(cache, "S", "groupe:B")
            self.assertEqual(uniformite.reference_choisie(cache, "S"), "groupe:B")
            uniformite.choisir_reference(cache, "S", "")
            self.assertIsNone(uniformite.reference_choisie(cache, "S"))


class AmelioreTest(unittest.TestCase):
    def test_reglage_uniformiser(self):
        r = optimiser.reglages_amelioration("0,0,0,0,0,0,0,0,1")
        self.assertEqual(r["uniformiser"], 1)
        self.assertEqual(optimiser.reglages_amelioration("0,0,0,0,0,0,0,0,7")["uniformiser"], 1)
        self.assertIsNone(optimiser.reglages_amelioration("0,0,0,0,0,0,0,0,0"))
        self.assertEqual(optimiser.reglages_amelioration("2,2,2,1,1,2,0,0")["uniformiser"], 0)       # anciens réglages à 8 valeurs

    def test_tome_teinte_ramene_au_noir_des_autres(self):
        calage = uniformite.calage(_s(33, noir=26, teinte=(2.0, -1.7, -0.4)), _s(5, noir=3))
        page = page_bd(VIOLACE)
        avant = np.asarray(page, dtype=np.float32)
        apres = optimiser.ameliorer(page, "0,0,0,0,0,0,0,0,1", calage)
        self.assertEqual(apres.mode, "L")                                       # la teinte disparaît
        a = np.asarray(apres, dtype=np.float32)
        self.assertLess(a[150:250, 150:350].mean(), 10)                         # l'encre était à 33
        self.assertGreater(avant[150:250, 150:350].mean(), 28)
        self.assertGreater(a[10:60, 10:60].mean(), 250)                         # le papier reste blanc

    def test_sans_calage_rien_n_est_deplace(self):
        apres = np.asarray(optimiser.ameliorer(page_bd(VIOLACE), "0,0,0,0,0,0,0,0,1", None), dtype=np.float32)
        self.assertGreater(apres[150:250, 150:350].mean(), 28)

    def test_page_sombre_n_est_pas_eclaircie_par_le_papier(self):
        rng = np.random.default_rng(3)
        a = np.full((600, 400), 30, np.float32) + rng.normal(0, 4, (600, 400))
        a[100:300, 50:200] = 70                                                # un aplat gris sombre
        a[400:420, 100:110] = 255                                              # un éclat : presque pas de papier sur la page
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "L")
        r = np.asarray(optimiser.ameliorer(im, "0,0,3,0,0,0,0,0,0"), dtype=np.float32)
        self.assertLess(r[100:300, 50:200].mean(), 110)                        # avant la correction : tout passait en gris clair ou blanc
        self.assertLess(r[:80, :].mean(), 60)

    def test_lancer_avec_calage_et_alerte_si_tome_non_mesure(self):
        with tempfile.TemporaryDirectory() as d:
            f1, f2 = tome(d, "S - Tome 01.cbz", VIOLACE, pages=6), tome(d, "S - Tome 02.cbz", VIOLACE, pages=6)
            calage = uniformite.calage(_s(33, noir=26, teinte=(2.0, -1.7, -0.4)), _s(5, noir=3))
            optimiser.lancer("Unif", [f1, f2], True, lambda p: None, "0,0,0,0,0,0,0,0,1", None, None, None, None, {f1.name: calage})
            import time
            for _ in range(600):
                if not optimiser.etat("Unif").get("en_cours"):
                    break
                time.sleep(0.05)
            rapport = {x["fichier"]: x for x in optimiser.etat("Unif")["rapport"]}
            self.assertNotIn("alerte", rapport[f1.name])
            self.assertIn("pas encore mesuré", rapport[f2.name]["alerte"])
            with zipfile.ZipFile(f1) as z:
                im = np.asarray(Image.open(io.BytesIO(z.read(z.namelist()[2]))).convert("L"), dtype=np.float32)
            self.assertLess(im[150:250, 150:350].mean(), 12)                    # le tome calé a les noirs de la référence


def _spectacle(h=700, l=1100, graine=5):
    """Une double page : un grand dessin dont les traits traversent le milieu."""
    rng = np.random.default_rng(graine)
    a = np.full((h, l), 245, np.uint8)
    for _ in range(40):
        p1, p2 = (int(rng.integers(0, l)), int(rng.integers(0, h))), (int(rng.integers(0, l)), int(rng.integers(0, h)))
        cv2.line(a, p1, p2, int(rng.integers(0, 90)), int(rng.integers(3, 12)))
    for _ in range(12):
        cv2.circle(a, (int(rng.integers(300, l - 300)), int(rng.integers(50, h - 50))), int(rng.integers(20, 90)), int(rng.integers(0, 60)), -1)
    cv2.rectangle(a, (l // 2 - 200, 200), (l // 2 + 200, 330), 20, -1)          # une case noire qui traverse la jointure
    return a


def _decaler(a, dy):
    if dy > 0:
        return np.concatenate([np.repeat(a[:1], dy, axis=0), a[:-dy]])
    return np.concatenate([a[-dy:], np.repeat(a[-1:], -dy, axis=0)]) if dy < 0 else a


class AlignementTest(unittest.TestCase):
    def test_decalage_sur_retrouve_et_annonce(self):
        base = _spectacle()
        m = base.shape[1] // 2
        g, d = Image.fromarray(base[:, :m]).convert("RGB"), Image.fromarray(_decaler(base[:, m:], 9)).convert("RGB")
        e = optimiser.estimer_decalage(g, d)
        self.assertLessEqual(abs(e["dy"] + 9), 2, e)
        self.assertIn(e["niveau"], ("sur", "probable"))

    def test_rien_qui_traverse_decalage_incertain_laisse_a_zero(self):
        blanc = Image.new("RGB", (500, 700), (255, 255, 255))
        e = optimiser.estimer_decalage(blanc, blanc)
        self.assertEqual((e["dy"], e["niveau"]), (0, "incertain"))

    def test_coller_renvoie_l_estimation(self):
        base = _spectacle()
        m = base.shape[1] // 2
        info = {}
        optimiser._coller(Image.fromarray(base[:, m:]).convert("RGB"), Image.fromarray(_decaler(base[:, :m], -6)).convert("RGB"), True, 0, info)
        self.assertIn(info["niveau"], ("sur", "probable", "incertain"))
        self.assertIn("dy", info)


class PairesTest(unittest.TestCase):
    def _tome(self, dossier, deux_pages_collees=True):
        """18 pages : des pages simples aux marges blanches, et au milieu les deux moitiés d'une double page (manga : la droite en premier)."""
        base = _spectacle(h=900, l=1300)
        m = base.shape[1] // 2
        pages = []
        for i in range(18):
            if i == 8 and deux_pages_collees:
                pages.append(base[:, m:])                                       # lue en premier, à droite
            elif i == 9 and deux_pages_collees:
                pages.append(base[:, :m])
            else:
                a = np.full((900, 650), 250, np.uint8)
                a[60:840, 60:590] = 235
                cv2.rectangle(a, (80 + 3 * i, 100), (300 + 3 * i, 400), 30, 3)         # un cadre, loin de la jointure
                pages.append(a)
        chemin = Path(dossier) / "T.cbz"
        with zipfile.ZipFile(chemin, "w") as z:
            for i, a in enumerate(pages):
                b = io.BytesIO()
                Image.fromarray(a).save(b, "JPEG", quality=95)
                z.writestr(f"{i:03d}.jpg", b.getvalue())
        return chemin

    def test_une_double_coupee_est_reperee(self):
        with tempfile.TemporaryDirectory() as d:
            optimiser._PAIRES_CACHE.clear()
            paires = optimiser.reperer_paires(self._tome(d), True)
            self.assertIn(8, [p["index"] for p in paires], paires)
            self.assertEqual(paires[0]["index"], 8)

    def test_tome_sans_double_aucune_paire(self):
        with tempfile.TemporaryDirectory() as d:
            optimiser._PAIRES_CACHE.clear()
            self.assertEqual(optimiser.reperer_paires(self._tome(d, False), True), [])

    def test_sens_occidental_inverse_les_moities(self):
        with tempfile.TemporaryDirectory() as d:
            optimiser._PAIRES_CACHE.clear()
            f = self._tome(d)
            self.assertEqual([p["index"] for p in optimiser.reperer_paires(f, False)], [])      # dans ce sens, les moitiés ne se touchent pas
            self.assertEqual(optimiser.reperer_paires(f, True)[0]["index"], 8)


class RoutesTest(unittest.TestCase):
    def test_analyse_et_calages_d_une_serie(self):
        import app as m
        with tempfile.TemporaryDirectory() as d:
            fichiers = [tome(d, f"S - Tome {n:02d}.cbz", NOIR if n <= 3 else VIOLACE, pages=6) for n in range(1, 6)]
            cache = Path(d) / "uniformite.json"
            with mock.patch.object(m, "_fichier_uniformite", return_value=cache), mock.patch.object(m, "_tomes_mesurables", return_value=fichiers):
                analyse, _ = m._analyse_uniformite("S")
                self.assertEqual(analyse["mesures"], 0)
                for f in fichiers:
                    uniformite._ecrire_cache(cache, dict(uniformite._lire_cache(cache), tomes=dict(
                        uniformite._lire_cache(cache).get("tomes", {}), **{str(f): {"cle": uniformite._cle(f), "stats": uniformite.mesurer_tome(f)}})))
                analyse, _ = m._analyse_uniformite("S")
                self.assertEqual(analyse["mesures"], 5)
                self.assertEqual(analyse["a_uniformiser"], ["S - Tome 04.cbz", "S - Tome 05.cbz"])
                calages = m._calages_uniformite("S", fichiers)
                self.assertEqual(set(calages), {f.name for f in fichiers})
                self.assertGreater(calages["S - Tome 04.cbz"]["e0"], 25)
                uniformite.choisir_reference(cache, "S", "groupe:B")
                self.assertEqual(m._analyse_uniformite("S")[0]["a_uniformiser"], ["S - Tome 01.cbz", "S - Tome 02.cbz", "S - Tome 03.cbz"])

    def test_assemblage_en_cours_empeche_le_redemarrage(self):
        import app as m
        with mock.patch.dict(optimiser._COUPES_ETAT, {"Serie": {"en_cours": True}}):
            self.assertTrue(any("assemblage" in r for r in m._travaux_en_cours()))


if __name__ == "__main__":
    unittest.main()
