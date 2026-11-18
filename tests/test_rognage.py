"""✂️ Rognage à la main : rendu sans déformation à la taille finale, papier ajouté, pages inchangées recopiées octet pour octet,
pages d'origine gardées, réglages remis d'accord quand le tome change par ailleurs."""
import io
import json
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
import rognage  # noqa: E402


def page_png(w=300, h=500, fond=235, marque=None):
    a = np.full((h, w), fond, np.uint8)
    if marque:
        x, y, mw, mh = marque
        a[y:y + mh, x:x + mw] = 10
    out = io.BytesIO()
    Image.fromarray(a).save(out, "PNG")
    return out.getvalue()


def faire_cbz(chemin, pages, info=True):
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_STORED) as z:
        for i, data in enumerate(pages, 1):
            z.writestr(f"{i:04d}.png", data)
        if info:
            z.writestr("ComicInfo.xml", "<ComicInfo><PageCount>%d</PageCount></ComicInfo>" % len(pages))


def lire(chemin, n):
    with zipfile.ZipFile(chemin) as z:
        noms = sorted(x for x in z.namelist() if x.endswith(".png"))
        return z.read(noms[n])


class RenduTest(unittest.TestCase):
    def test_taille_exacte_sans_deformation_et_papier_autour(self):
        a = np.full((400, 400), 240, np.uint8)
        a[100:300, 100:300] = 0                                             # un carré noir de 200 px
        im = Image.fromarray(a)
        s = np.array(rognage.rendre_page(im, {"x": 90, "y": 90, "w": 220, "h": 220, "a": 0}, (300, 600)))
        self.assertEqual(s.shape, (600, 300))
        noir = np.argwhere(s < 60)
        hauteur, largeur = np.ptp(noir[:, 0]) + 1, np.ptp(noir[:, 1]) + 1
        self.assertAlmostEqual(hauteur / largeur, 1.0, delta=0.02)          # le carré reste un carré (agrandi de 300/220)
        self.assertAlmostEqual(largeur, 200 * 300 / 220, delta=3)
        self.assertTrue((s[:140] >= 230).all() and (s[-140:] >= 230).all())  # papier ajouté en haut et en bas, centré

    def test_cadre_plus_grand_que_la_cible_est_reduit(self):
        im = Image.fromarray(np.full((1000, 600), 200, np.uint8))
        s = rognage.rendre_page(im, {"x": 0, "y": 0, "w": 600, "h": 1000, "a": 0}, (300, 500))
        self.assertEqual(s.size, (300, 500))

    def test_cadre_qui_deborde_de_la_page_est_complete_de_papier(self):
        a = np.full((300, 200), 236, np.uint8)
        a[50:250, 20:180] = 20
        s = np.array(rognage.rendre_page(Image.fromarray(a), {"x": -20, "y": 0, "w": 240, "h": 300, "a": 0}, (240, 300)))
        self.assertTrue((s[:, :20] >= 230).all())

    def test_couverture_coloree_complétée_de_blanc_jamais_d_une_couleur_du_dessin(self):
        a = np.zeros((300, 200, 3), np.uint8)
        a[:] = (200, 30, 40)
        a[40:260, 30:170] = (240, 170, 180)                                 # rose au milieu
        s = np.array(rognage.rendre_page(Image.fromarray(a), {"x": 0, "y": 0, "w": 200, "h": 300, "a": 0}, (300, 300)))
        self.assertEqual(s.shape, (300, 300, 3))
        self.assertTrue((s[:, :40] == 255).all())

    def test_flash_back_sur_fond_noir_complete_de_noir(self):
        a = np.full((400, 300), 35, np.uint8)                                # fond noir tout autour
        a[40:360, 30:270] = 240                                              # une case claire au milieu
        s = np.array(rognage.rendre_page(Image.fromarray(a), {"x": 0, "y": 0, "w": 300, "h": 400, "a": 0}, (300, 500)))
        self.assertLess(s[:30].mean(), 60)                                   # le papier ajouté continue le fond noir
        couleur = np.dstack([a, a, a]).copy()
        self.assertEqual(rognage.ton_papier(couleur), (35, 35, 35))           # même en RVB tant que la page est grise
        self.assertEqual(rognage.ton_papier(np.full((100, 100), 240, np.uint8)), 240)

    def test_angle_et_couleurs(self):
        im = Image.new("RGB", (200, 300), (230, 230, 230))
        s = rognage.rendre_page(im, {"x": 0, "y": 0, "w": 200, "h": 300, "a": 1.5}, (210, 310))
        self.assertEqual(s.size, (210, 310))
        self.assertEqual(s.mode, "RGB")


class PlanTest(unittest.TestCase):
    TAILLES = [[300, 500], [300, 500], [600, 500], [310, 505]]

    def test_taille_automatique_cadre_median_des_pages_simples(self):
        e = {"boites": {"0": {"x": 0, "y": 0, "w": 280, "h": 480, "a": 0}, "1": {"x": 0, "y": 0, "w": 290, "h": 470, "a": 0},
                        "2": {"x": 0, "y": 0, "w": 590, "h": 480, "a": 0}, "3": {"x": 0, "y": 0, "w": 270, "h": 490, "a": 0}}}
        self.assertEqual(rognage.taille_finale(e, self.TAILLES), (280, 480))
        p = rognage.plan(e, self.TAILLES)
        self.assertEqual(p["pages"][2]["taille"], [560, 480])                # double page : 2W × H
        self.assertTrue(all(not x["garder"] for x in p["pages"]))

    def test_page_non_reglee_page_entiere_et_taille_fixee(self):
        p = rognage.plan({"boites": {}, "W": 250, "H": 400}, self.TAILLES)
        self.assertEqual(p["pages"][3]["boite"], {"x": 0, "y": 0, "w": 310, "h": 505, "a": 0.0})
        self.assertFalse(p["pages"][3]["reglee"])
        self.assertEqual(p["pages"][0]["taille"], [250, 400])

    def test_seules_les_pages_changees_sont_a_ecrire(self):
        b = {"x": 5, "y": 6, "w": 280, "h": 480, "a": 0.0}
        e = {"W": 280, "H": 480, "boites": {"0": dict(b), "1": dict(b, x=9)},
             "produit": {"W": 280, "H": 480, "boites": {"0": b, "1": b, "2": rognage.boite_entiere([600, 500]), "3": rognage.boite_entiere([310, 505])}}}
        p = rognage.plan(e, self.TAILLES)
        self.assertEqual([x["garder"] for x in p["pages"]], [True, False, True, True])
        e["W"] = 281                                                        # autre taille finale : tout est à réécrire
        self.assertTrue(all(not x["garder"] for x in rognage.plan(e, self.TAILLES)["pages"]))

    def test_cadres_bornes(self):
        self.assertIsNone(rognage.nettoyer_boite({"x": 0, "y": 0, "w": 5, "h": 300}))
        self.assertIsNone(rognage.nettoyer_boite({"x": "a", "y": 0, "w": 50, "h": 300}))
        self.assertEqual(rognage.nettoyer_boite({"x": 1.4, "y": 2.6, "w": 50, "h": 300, "a": 42, "c": 1}), {"x": 1, "y": 3, "w": 50, "h": 300, "a": 10.0, "c": 1})


class _Tome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self.tmp.name)
        (self.racine / "Serie" / "Tome 01").mkdir(parents=True)
        self.cbz = self.racine / "Serie" / "Tome 01" / "Serie - Tome 01.cbz"
        faire_cbz(self.cbz, [page_png(marque=(50, 60, 100, 100)), page_png(marque=(10, 10, 30, 30)), page_png(w=600, h=500), page_png(w=320, h=520)])
        self.reglages = self.racine / "rognage.json"

    def tearDown(self):
        self.tmp.cleanup()

    def appliquer(self):
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", self.cbz)
        p = rognage.plan(etat["entree"], etat["tailles"])
        copier = not etat["entree"].get("source")
        travail = {"source": str(rognage.chemin_source(self.racine, "Serie", self.cbz.name) if copier else etat["source"]), "copier_source": copier,
                   "pages": p["pages"], "W": p["W"], "H": p["H"], "retouches": etat["entree"].get("retouches")}       # comme /api/rogner/appliquer
        ecrire = {i for i, x in enumerate(p["pages"]) if not x["garder"]}
        res = rognage.ecrire_tome(self.cbz, ecrire, travail=travail)
        res["avant"].unlink()
        rognage.noter_application(self.racine, self.reglages, "Serie", self.cbz, travail)
        return ecrire

    def sauver(self, boites, W=None, H=None):
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", self.cbz)
        rognage.sauver(self.reglages, "Serie", self.cbz.name, etat, W, H, boites)

    def tailles(self):
        with zipfile.ZipFile(self.cbz) as z:
            out = []
            for n in sorted(x for x in z.namelist() if x.endswith(".png")):
                with Image.open(io.BytesIO(z.read(n))) as im:
                    out.append(im.size)
            return out



class TomeTest(_Tome):
    def test_toutes_les_pages_a_la_meme_taille_et_origines_gardees(self):
        original = self.cbz.read_bytes()
        self.sauver({"0": {"x": 40, "y": 50, "w": 200, "h": 300, "a": 0}, "1": {"x": 0, "y": 0, "w": 150, "h": 300, "a": 0.5}}, 200, 300)
        self.assertEqual(self.appliquer(), {0, 1, 2, 3})
        self.assertEqual(self.tailles(), [(200, 300), (200, 300), (400, 300), (200, 300)])
        source = rognage.chemin_source(self.racine, "Serie", self.cbz.name)
        self.assertEqual(source.read_bytes(), original)                        # les pages d'origine sont gardées telles quelles
        with zipfile.ZipFile(self.cbz) as z:
            self.assertIn("ComicInfo.xml", z.namelist())
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", self.cbz)
        self.assertEqual(etat["source"], source)
        self.assertEqual(etat["tailles"][0], [300, 500])                      # on règle toujours sur les pages d'origine
        self.assertEqual(etat["entree"]["boites"]["0"]["w"], 200)               # et les cadres sont toujours là

    def test_modifier_une_page_ne_reecrit_qu_elle(self):
        self.sauver({"0": {"x": 40, "y": 50, "w": 200, "h": 300, "a": 0}}, 200, 300)
        self.appliquer()
        avant = [lire(self.cbz, i) for i in range(4)]
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", self.cbz)
        b = dict(etat["entree"]["boites"])
        b["1"] = {"x": 0, "y": 0, "w": 250, "h": 400, "a": 0}                    # on agrandit le cadre de la page 2 : possible, l'origine est gardée
        self.sauver(b, 200, 300)
        self.assertEqual(self.appliquer(), {1})
        apres = [lire(self.cbz, i) for i in range(4)]
        self.assertEqual([apres[i] == avant[i] for i in range(4)], [True, False, True, True])
        self.assertEqual(self.tailles()[1], (200, 300))

    def test_rien_ne_change_rien_a_ecrire(self):
        self.sauver({"0": {"x": 40, "y": 50, "w": 200, "h": 300, "a": 0}}, 200, 300)
        self.appliquer()
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", self.cbz)
        self.assertTrue(all(x["garder"] for x in rognage.plan(etat["entree"], etat["tailles"])["pages"]))

    def test_page_remplacee_par_ailleurs_devient_la_nouvelle_origine(self):
        self.sauver({"0": {"x": 40, "y": 50, "w": 200, "h": 300, "a": 0}}, 200, 300)
        self.appliquer()
        nouvelle = page_png(w=230, h=360, fond=120)                           # la couverture est remplacée par une autre fonction de l'appli
        with zipfile.ZipFile(self.cbz) as z:
            contenu = [(i, z.read(i.filename)) for i in z.infolist()]
        with zipfile.ZipFile(self.cbz, "w") as z:
            for info, data in contenu:
                z.writestr(info.filename, nouvelle if info.filename == "0001.png" else data)
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", self.cbz)
        self.assertIn("page 1", etat["message"])
        self.assertEqual(etat["tailles"][0], [230, 360])                      # la nouvelle couverture est la page d'origine n° 1
        self.assertEqual(etat["tailles"][1], [300, 500])                      # les autres restent les pages d'origine
        p = rognage.plan(etat["entree"], etat["tailles"])
        self.assertTrue(all(x["garder"] for x in p["pages"]))                 # rien à réécrire : la couverture reste comme elle a été mise
        self.assertEqual(lire(rognage.chemin_source(self.racine, "Serie", self.cbz.name), 0), nouvelle)

    def test_tome_avec_autre_nombre_de_pages_repart_du_fichier_actuel(self):
        self.sauver({"0": {"x": 40, "y": 50, "w": 200, "h": 300, "a": 0}}, 200, 300)
        self.appliquer()
        faire_cbz(self.cbz, [page_png()] * 6)
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", self.cbz)
        self.assertTrue(etat["message"])
        self.assertEqual(etat["source"], self.cbz)
        self.assertEqual(etat["jeter"], rognage.chemin_source(self.racine, "Serie", self.cbz.name))
        self.assertEqual(etat["entree"]["boites"], {})

    def test_pas_encore_applique_tome_change_garde_les_cadres_des_pages_de_meme_taille(self):
        self.sauver({"0": {"x": 40, "y": 50, "w": 200, "h": 300, "a": 0}, "3": {"x": 0, "y": 0, "w": 200, "h": 300, "a": 0}})
        faire_cbz(self.cbz, [page_png(marque=(1, 1, 5, 5)), page_png(), page_png(w=600, h=500), page_png(w=400, h=600)])
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", self.cbz)
        self.assertEqual(sorted(etat["entree"]["boites"]), ["0"])

    def test_taille_de_la_serie_reprise_pour_un_autre_tome(self):
        self.sauver({"0": {"x": 40, "y": 50, "w": 200, "h": 300, "a": 0}}, 200, 300)
        self.appliquer()
        autre = self.racine / "Serie" / "Tome 02" / "Serie - Tome 02.cbz"
        autre.parent.mkdir()
        faire_cbz(autre, [page_png()] * 2)
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", autre)
        self.assertEqual((etat["entree"]["W"], etat["entree"]["H"]), (200, 300))
        liste = rognage.etat_liste(self.reglages, "Serie")
        self.assertEqual(liste[self.cbz.name]["octets"], self.cbz.stat().st_size)
        self.assertFalse(liste[self.cbz.name]["en_cours"])

    def test_retouche_de_ton_refaite_sur_les_pages_reecrites(self):
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", self.cbz)
        p = rognage.plan(dict(etat["entree"], W=300, H=500), etat["tailles"])
        lum = {}
        for retouches in (None, {"noirs": 3, "agrandir": 2}):
            c = self.racine / f"essai-{bool(retouches)}.cbz"
            c.write_bytes(self.cbz.read_bytes())
            rognage.ecrire_tome(c, {1}, travail={"source": str(self.cbz), "copier_source": False, "pages": p["pages"], "W": 300, "H": 500,
                                                 "retouches": retouches})["avant"].unlink()
            with zipfile.ZipFile(c) as z, Image.open(io.BytesIO(z.read("0002.png"))) as im:
                lum[bool(retouches)] = (np.asarray(im.convert("L"), float)[10:40, 10:40].mean(), im.size)
        self.assertLess(lum[True][0], lum[False][0])                         # encre noircie comme le reste du tome
        self.assertEqual(lum[True][1], (300, 500))                           # « agrandir » n'est jamais refait : la taille ne bouge pas

    def test_echec_de_relecture_ne_touche_pas_au_tome(self):
        self.sauver({}, 200, 300)
        avant = self.cbz.read_bytes()
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", self.cbz)
        p = rognage.plan(etat["entree"], etat["tailles"])
        p["pages"].pop()                                                      # plan qui ne correspond plus au tome
        with self.assertRaises(RuntimeError):
            rognage.ecrire_tome(self.cbz, {0}, travail={"source": str(self.cbz), "copier_source": False, "pages": p["pages"], "W": 200, "H": 300})
        self.assertEqual(self.cbz.read_bytes(), avant)
        self.assertEqual(sorted(x.name for x in self.cbz.parent.iterdir()), [self.cbz.name])


class IaTest(_Tome):
    """✨ Restauration IA d'un tome rogné : ses pages ont été agrandies au-delà de la hauteur que l'IA accepte ; elle travaille à leur résolution d'origine."""

    def setUp(self):
        super().setUp()
        with zipfile.ZipFile(self.cbz, "w", zipfile.ZIP_STORED) as z:          # ✨ Améliorer ne retouche que les JPEG
            for i, (w, h) in enumerate([(300, 500), (300, 500), (600, 500), (320, 520)], 1):
                a = np.full((h, w), 235, np.uint8)
                a[60:160, 50:150] = 10
                out = io.BytesIO()
                Image.fromarray(a).save(out, "JPEG", quality=90)
                z.writestr(f"{i:04d}.jpg", out.getvalue())
        import ia
        import optimiser
        self.vues = []

        def faux_agrandir(g, niveau, niveaux_auto=True):                     # le vrai réseau est lent : un faux qui double et inverse la page
            self.vues.append(g.shape)
            return 255 - cv2.resize(g, (g.shape[1] * 2, g.shape[0] * 2))
        self.patches = [mock.patch.object(ia, "disponible", return_value=True), mock.patch.object(ia, "agrandir", faux_agrandir),
                        mock.patch.object(ia, "HAUTEUR_MAX", 400), mock.patch.object(optimiser, "ROGNAGE", str(self.reglages))]
        for x in self.patches:
            x.start()

    def tailles(self):
        with zipfile.ZipFile(self.cbz) as z:
            return [Image.open(io.BytesIO(z.read(n))).size for n in sorted(z.namelist())]

    def tearDown(self):
        for x in self.patches:
            x.stop()
        super().tearDown()

    def test_page_agrandie_par_le_rognage_restauree_a_sa_resolution_d_origine(self):
        import optimiser
        im = Image.fromarray(np.full((600, 360), 200, np.uint8))              # plus haute que HAUTEUR_MAX (400)
        self.assertTrue((np.asarray(optimiser.ameliorer(im, {"ia": 2})) == 200).all())     # sans rien savoir de la page : l'IA n'y touche pas (comme avant)
        r = optimiser.ameliorer(im, {"ia": 2}, source=2.0)
        self.assertEqual(self.vues, [(300, 180)])                            # ramenée à sa résolution d'origine
        self.assertEqual(r.size, (360, 600))                                 # et rendue à SA taille
        self.assertLess(np.asarray(r).mean(), 100)                           # restaurée (le faux réseau inverse)
        self.assertTrue((np.asarray(optimiser.ameliorer(im, {"ia": 2}, source=1.1)) == 200).all())    # presque pas agrandie : rien à gagner
        self.assertEqual(len(self.vues), 1)

    def test_ameliorer_un_tome_rogne_puis_refaire_une_page(self):
        import optimiser
        self.sauver({"0": {"x": 40, "y": 50, "w": 150, "h": 250, "a": 0}, "1": {"x": 0, "y": 0, "w": 150, "h": 250, "a": 0}}, 300, 500)
        self.appliquer()
        self.assertEqual(optimiser.echelle_du_tome(self.cbz, {"ia": 2}), 2.0)
        self.assertIsNone(optimiser.echelle_du_tome(self.cbz, {"noirs": 1}))
        octets = self.cbz.stat().st_size
        optimiser.reecrire(self.cbz, 90, {"ia": 2})
        self.cbz.with_name(self.cbz.name + ".avant").unlink()
        self.assertTrue(self.vues)                                           # l'IA a bien travaillé sur ce tome de pages de 500 px
        self.assertEqual(self.tailles(), [(300, 500), (300, 500), (600, 500), (300, 500)])
        self.assertTrue(rognage.noter_retouches(self.reglages, self.cbz, octets, {"ia": 2, "agrandir": 0}))
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", self.cbz)
        self.assertFalse(etat.get("message"))                                # les pages améliorées ne passent pas pour des pages d'origine changées
        self.assertEqual(etat["tailles"][0], [300, 500])                     # les pages d'origine restent les vraies
        self.assertEqual(etat["entree"]["retouches"], {"ia": 2})
        b = dict(etat["entree"]["boites"])
        b["1"] = {"x": 0, "y": 0, "w": 140, "h": 240, "a": 0}
        self.sauver(b, 300, 500)
        self.vues.clear()
        self.assertEqual(self.appliquer(), {1})
        self.assertEqual(len(self.vues), 1)                                  # la page refaite reçoit aussi la restauration IA
        self.assertEqual(self.tailles()[1], (300, 500))

    def test_retouches_pas_notees_si_le_tome_n_est_pas_celui_du_rognage_ou_change_de_taille(self):
        self.sauver({"0": {"x": 40, "y": 50, "w": 150, "h": 250, "a": 0}}, 300, 500)
        self.appliquer()
        self.assertFalse(rognage.noter_retouches(self.reglages, self.cbz, 123, {"ia": 2}))
        octets = self.cbz.stat().st_size
        faire_cbz(self.cbz, [page_png(w=600, h=1000)] * 4, info=False)                    # pages doublées (« agrandir ») : plus la taille du rognage
        self.assertFalse(rognage.noter_retouches(self.reglages, self.cbz, octets, {"agrandir": 1, "ia": 2}))


class RedresserTest(_Tome):
    """✨ « redresser » sur un tome rogné ici : la page est redressée sur sa page d'origine, AVANT le cadre (les coins viennent de la vraie page)."""

    def setUp(self):
        super().setUp()
        import optimiser
        with zipfile.ZipFile(self.cbz, "w", zipfile.ZIP_STORED) as z:
            for i in range(1, 5):
                a = np.full((1000, 640), 235, np.uint8)
                for y0, y1 in ((40, 330), (360, 650), (680, 960)):
                    cv2.rectangle(a, (40, y0), (310, y1), 20, 3)
                    cv2.rectangle(a, (330, y0), (600, y1), 20, 3)
                a[:, :12] = 90                                                   # la bande de la page voisine, au bord
                m = cv2.getRotationMatrix2D((320, 500), -1.3, 1.0)                # page scannée penchée
                a = cv2.warpAffine(a, m, (640, 1000), flags=cv2.INTER_CUBIC, borderValue=235)
                out = io.BytesIO()
                Image.fromarray(a).save(out, "JPEG", quality=92)
                z.writestr(f"{i:04d}.jpg", out.getvalue())
        self.patches = [mock.patch.object(optimiser, "ROGNAGE", str(self.reglages)), mock.patch.object(optimiser, "MANGAS", self.racine)]
        for x in self.patches:
            x.start()

    def tearDown(self):
        for x in self.patches:
            x.stop()
        super().tearDown()

    def page(self, n):
        with zipfile.ZipFile(self.cbz) as z:
            return np.asarray(Image.open(io.BytesIO(z.read(sorted(z.namelist())[n]))).convert("L"))

    def test_redresse_sur_l_origine_puis_garde_pour_les_pages_refaites(self):
        import optimiser
        import reliure
        cadre = {"x": 20, "y": 10, "w": 600, "h": 980, "a": 0}
        self.sauver({str(i): dict(cadre) for i in range(4)}, 600, 980)
        self.appliquer()
        self.assertIsNotNone(reliure.redressement(self.page(0)))                  # le rognage seul laisse la page penchée
        octets = self.cbz.stat().st_size
        optimiser.reecrire(self.cbz, 90, {"redresser": 1})
        self.cbz.with_name(self.cbz.name + ".avant").unlink()
        p = self.page(0)
        self.assertEqual(p.shape, (980, 600))
        self.assertIsNone(reliure.redressement(p))                                 # droite
        self.assertLess(np.abs(p[:, :8].astype(float) - 235).mean(), 20)           # pas de coin de bande grise : redressée avant le cadre
        self.assertTrue(rognage.noter_retouches(self.reglages, self.cbz, octets, {"redresser": 1}))
        etat = rognage.ouvrir(self.racine, self.reglages, "Serie", self.cbz)
        self.assertFalse(etat.get("message"))
        b = dict(etat["entree"]["boites"])
        b["1"] = dict(cadre, w=590)
        self.sauver(b, 600, 980)
        self.assertEqual(self.appliquer(), {1})
        self.assertIsNone(reliure.redressement(self.page(1)))                       # la page refaite est redressée elle aussi
        self.assertIsNone(optimiser.cadre_du_tome(self.cbz, {"recadrer": 1}))      # « recadrer » : les cadres à la main le font déjà


if __name__ == "__main__":
    unittest.main()
