"""Sommaires, octobre 2026 : format « 88º punch », pages d'ouverture des tomes sans sommaire, mémoire des lectures d'un tome,
relectures limitées aux lectures incomplètes, éditions spéciales lues sans les numéros d'Internet."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sommaire  # noqa: E402

ONE_PUNCH_18 = """CO NUS1
ONE-PUNCHMANVOL.18
ŒUVRE ORIGINALE ONE MANGA YUSUKE MURATA
My name is SAITAMA. I am a hero. Being a hero is my hobby. But I became too strong.
88º punch
Part de monstre 7
89º punch
Limiteurs 25
90º punch
Fondue 57"""


class NumeroAvantLeMot(unittest.TestCase):
    def test_one_punch_man(self):
        l = sommaire.analyser_numero_avant(ONE_PUNCH_18)
        self.assertEqual([(x["num"], x["titre"], x["page"]) for x in l],
                         [(88, "Part de monstre", 7), (89, "Limiteurs", 25), (90, "Fondue", 57)])
        self.assertEqual([x["num"] for x in sommaire._meilleure_lecture(ONE_PUNCH_18)], [88, 89, 90])

    def test_titre_puis_page_seule(self):
        l = sommaire.analyser_numero_avant("12e nuit\nLe retour\n45\n13e nuit\nUn autre jour\n60\n14e nuit\nFin 81")
        self.assertEqual([(x["num"], x["titre"], x["page"]) for x in l], [(12, "Le retour", 45), (13, "Un autre jour", 60), (14, "Fin", 81)])

    def test_un_seul_mot_ne_suffit_pas(self):
        self.assertEqual(sommaire.analyser_numero_avant("3 pommes\nUne recette 12"), [])


class Mentions(unittest.TestCase):
    def test_formes(self):
        self.assertEqual(sommaire._mentions("CHAPITRE 36 TROIS CLÉS"), {36})
        self.assertEqual(sommaire._mentions("88° punch Part de monstre"), {88})
        self.assertEqual(sommaire._mentions("NISEKOI #37"), {37})
        self.assertEqual(sommaire._mentions("TU AS DONC SURVÉCU.\n0333\nMOYENS EXTREMES"), {333})
        self.assertEqual(sommaire._mentions("Trick:166"), {166})
        self.assertEqual(sommaire._mentions("IL SUFFIT DE REGARDER 14 FOIS"), set())
        self.assertEqual(sommaire._mentions("CHAPITRE 36 - FIN"), set())             # Nisekoi : la dernière page rappelle le numéro
        self.assertEqual(sommaire._mentions("fin du chapitre 36"), set())
        self.assertEqual(sommaire._mentions("Suite au chapitre 37 !"), set())

    def test_longueurs_aberrantes_retirees(self):
        chaine = [(19, 36), (37, 37), (59, 38), (76, 39), (156, 40), (170, 44)]
        self.assertEqual(sommaire._reguliere(chaine), [(19, 36), (37, 37), (59, 38), (76, 39), (170, 44)])

    def test_chaine_garde_la_page_d_ouverture(self):
        # Nisekoi : le numéro est rappelé sur la dernière page du chapitre ; c'est la première mention qui compte
        vus = {0: {35}, 18: {35}, 19: {36}, 36: {36}, 37: {37}, 55: {37}, 56: {38}, 70: {12}}
        self.assertEqual(sommaire._chaine(vus, []), [(0, 35), (19, 36), (37, 37), (56, 38)])
        self.assertEqual(sommaire._chaine(vus, [36, 37, 38]), [(19, 36), (37, 37), (56, 38)])


class Ouvertures(unittest.TestCase):
    def _lire(self, pages, numeros, suite_de=None, lent=None):
        """pages : {image: texte lu vite} ; lent : {image: texte du lecteur moderne}."""
        def texte(octets, moderne=False):
            i = int(octets)
            return (lent or {}).get(i, "") if moderne else pages.get(i, "")
        import numpy as np
        with mock.patch.object(sommaire, "_texte_rapide", texte), \
                mock.patch.object(sommaire, "_empreinte", lambda o: np.full((24, 16), int(o) % 200, dtype=np.int16)), \
                mock.patch.object(sommaire, "_moteur", lambda: object() if lent else None):
            return sommaire.chapitres_par_ouvertures(lambda i: str(i).encode(), 120, numeros, suite_de)

    def test_numeros_d_internet_et_trou_estime(self):
        pages = {3: "CHAPITRE 13 Le bruit de la pluie", 49: "CHAPITRE 14", 50: "CHAPITRE 14", 88: "fin"}
        r = self._lire(pages, [12, 13, 14, 15, 16], lent={88: "CHAPITRE 15 S! GO!"})
        self.assertEqual([(x["num"], x["image"], bool(x.get("estimee"))) for x in r], [(13, 3, False), (14, 49, False), (15, 88, False)])

    def test_trou_comble_par_estimation(self):
        pages = {2: "CHAPITRE 40", 20: "CHAPITRE 41", 60: "CHAPITRE 43", 80: "#44"}      # « #44 » lu vite : pas cru
        r = self._lire(pages, [40, 41, 42, 43])
        self.assertEqual([(x["num"], x["image"], bool(x.get("estimee"))) for x in r], [(40, 2, False), (41, 20, False), (42, 40, True), (43, 60, False)])

    def test_edition_speciale_sans_numeros_d_internet(self):
        # Gantz Perfect : la liste d'Internet ne vaut pas ; « 0333 », « 0334 »… imprimés font foi
        pages = {5: "0333\nMOYENS EXTREMES", 24: "0334\nIRRÉVERSIBLE", 48: "0335", 70: "0336\nDU NOMBRE"}
        r = self._lire(pages, [])
        self.assertEqual([(x["num"], x["image"]) for x in r], [(333, 5), (334, 24), (335, 48), (336, 70)])

    def test_rien_d_annonce_rien_d_invente(self):
        self.assertEqual(self._lire({10: "IL SUFFIT DE REGARDER 14 FOIS"}, []), [])

    def test_deux_mentions_sans_liste_pas_assez(self):
        self.assertEqual(self._lire({5: "CHAPITRE 3", 30: "CHAPITRE 4"}, []), [])
        self.assertEqual(len(self._lire({5: "CHAPITRE 3", 30: "CHAPITRE 4"}, [], suite_de=2)), 2)    # suite du tome précédent


class CompletEtSur(unittest.TestCase):
    def test_sans_liste(self):
        ch = [{"num": float(n), "page": p} for n, p in ((5, 3), (6, 20), (7, 41))]
        self.assertTrue(sommaire._complet_et_sur(ch, []))
        self.assertFalse(sommaire._complet_et_sur(ch[:2], []))
        self.assertFalse(sommaire._complet_et_sur([dict(ch[0], estimee=True)] + ch[1:], []))
        self.assertFalse(sommaire._complet_et_sur(ch, [5, 6, 7, 8]))


class MemoireDesLectures(unittest.TestCase):
    def test_meme_image_memes_reglages_tesseract_une_fois(self):
        lances = []
        vrai = sommaire.subprocess.run

        def faux(cmd, **k):
            lances.append(cmd)
            return sommaire.subprocess.CompletedProcess(cmd, 0, stdout=b"12", stderr=b"")
        sommaire._LOCAL.memo = {}
        try:
            with mock.patch.object(sommaire.subprocess, "run", faux):
                a = sommaire._run(["nice", "-n", "10", "tesseract", "stdin", "stdout", "--psm", "7"], input=b"image")
                b = sommaire._run(["nice", "-n", "10", "tesseract", "stdin", "stdout", "--psm", "7"], input=b"image")
                sommaire._run(["nice", "-n", "10", "tesseract", "stdin", "stdout", "--psm", "6"], input=b"image")
        finally:
            sommaire._LOCAL.memo = None
        self.assertEqual((a.stdout, b.stdout), (b"12", b"12"))
        self.assertEqual(len(lances), 2)                            # même image et mêmes réglages : une seule fois
        self.assertIs(sommaire.subprocess.run, vrai)

    def test_pages_gardees(self):
        lues = []
        lire = sommaire._pages_en_memoire(lambda i: lues.append(i) or bytes([i]))
        for i in (1, 2, 1, 2, 3):
            lire(i)
        self.assertEqual(lues, [1, 2, 3])


class RelireSeulementIncomplet(unittest.TestCase):
    def test_lecture_complete_jamais_relue(self):
        import app
        complet = {"chapitres": [{"num": 1.0, "image": 4}, {"num": 2.0, "image": 22}]}
        with mock.patch.object(app, "_numeros_fiables", lambda n, t: [1.0, 2.0]):
            self.assertFalse(app._a_relire(complet, "S", 1))
            self.assertTrue(app._a_relire({"chapitres": []}, "S", 1))
            self.assertTrue(app._a_relire({"chapitres": [{"num": 1.0, "image": 4, "estimee": True}]}, "S", 1))
            self.assertTrue(app._a_relire({"chapitres": [{"num": 1.0, "image": 4}]}, "S", 1))     # le 2 manque

    def test_edition_speciale_sans_numeros_d_internet(self):
        import app
        with mock.patch.object(app, "_edition_differente", lambda n: True), \
                mock.patch.object(app.tomes, "numeros_du_tome", lambda n, t: [179.0, 180.0]):
            self.assertEqual(app._numeros_fiables("Gantz", 16), [])
        with mock.patch.object(app, "_edition_differente", lambda n: False), \
                mock.patch.object(app.tomes, "numeros_du_tome", lambda n, t: [179.0, 180.0]):
            self.assertEqual(app._numeros_fiables("Gantz", 16), [179.0, 180.0])


class PagesDEquipeReluesUneFois(unittest.TestCase):
    def test_version_notee_meme_si_la_relecture_ne_trouve_rien(self):
        """Defense Devil : chapitres déduits des pages d'équipe, relecture sans résultat ; avant, la version n'était pas notée
        et chaque ouverture de la fiche relançait plusieurs minutes de lecture."""
        import json
        import app
        import edition
        infos = {"sommaires": {"5": {"chapitres": [{"num": 38.0, "image": 3}], "source": "pages d'équipe", "version": 6}}}
        ecrit, pris = {}, {}
        with mock.patch.object(edition, "lire", lambda d: json.loads(json.dumps(infos))), \
                mock.patch.object(edition, "ecrire", lambda d, x: ecrit.update(x)), \
                mock.patch.object(sommaire, "lancer", lambda *a, **k: pris.update(enregistrer=a[5])), \
                mock.patch.object(app.archives, "pages", lambda c: ["1.jpg"]), \
                mock.patch.object(app, "_numeros_fiables", lambda n, t: []), mock.patch.object(app, "_suite_de", lambda n, t: None):
            app._lire_sommaire("Defense Devil", 5, {"path": "Defense Devil/Tome 05/t.cbz"})
            pris["enregistrer"]({"chapitres": [], "version": sommaire.VERSION})
        lu = ecrit["sommaires"]["5"]
        self.assertEqual(lu["version"], sommaire.VERSION)
        self.assertEqual(lu["source"], "pages d'équipe")
        self.assertEqual(lu["chapitres"], [{"num": 38.0, "image": 3}])


class VerificationParLesOuvertures(unittest.TestCase):
    def test_longueurs_incoherentes_a_verifier(self):
        ch = lambda *ims: [{"num": float(88 + k), "image": im} for k, im in enumerate(ims)]
        self.assertTrue(sommaire._a_verifier(ch(11, 29, 55), 194))           # One-Punch Man 18 : le dernier ferait 140 pages
        self.assertFalse(sommaire._a_verifier(ch(7, 51, 97, 141), 194))
        self.assertTrue(sommaire._a_verifier(ch(7, 51) + [{"num": 90.0, "image": 97, "estimee": True}], 194))

    def test_sommaire_imprime_faux_recale(self):
        """« Limiteurs … 25 » au sommaire, « 89e punch » imprimé page 51 : la page d'ouverture fait foi."""
        ch = [{"num": 88.0, "image": 11}, {"num": 89.0, "image": 29}, {"num": 90.0, "image": 55}]
        pages = {7: "88e punch Part de monstre", 51: "89e punch Limiteurs", 99: "90e punch Fondue", 120: "88e punch (rappel)"}
        import numpy as np
        with mock.patch.object(sommaire, "_texte_rapide", lambda o, moderne=False: pages.get(int(o), "")), \
                mock.patch.object(sommaire, "_empreinte", lambda o: np.zeros((24, 16), dtype=np.int16)):
            n = sommaire._verifier_par_ouvertures(ch, lambda i: str(i).encode(), 194, 6)
        self.assertEqual(n, 3)
        self.assertEqual([c["image"] for c in ch], [7, 51, 99])


class GardeFousDeLaVerification(unittest.TestCase):
    def _avec_pages(self, pages):
        import numpy as np
        return mock.patch.object(sommaire, "_texte_rapide", lambda o, moderne=False: pages.get(int(o), "")), \
            mock.patch.object(sommaire, "_empreinte", lambda o: np.zeros((24, 16), dtype=np.int16))

    def test_verification_legere(self):
        ch = [{"num": float(n), "image": im} for n, im in ((1, 6), (2, 34), (3, 54))]
        a, b = self._avec_pages({6: "CHAPITRE 1", 34: "CHAPITRE 2", 54: "CHAPITRE 3"})
        with a, b:
            self.assertFalse(sommaire._verifier_leger(ch, lambda i: str(i).encode()))
        a, b = self._avec_pages({6: "CHAPITRE 1", 40: "CHAPITRE 2 AU KARAOKÉ", 54: "CHAPITRE 3"})
        with a, b:
            self.assertTrue(sommaire._verifier_leger(ch, lambda i: str(i).encode()))

    def test_jamais_pire_qu_avant(self):
        """20th Century Boys 3 : des « 1 », « 3 », « 4 » lus dans des bulles ne déplacent pas un placement plausible."""
        ch = [{"num": float(n), "image": im} for n, im in ((1, 3), (2, 20), (3, 37), (4, 55), (5, 73), (6, 92), (7, 111))]
        origine = [dict(c) for c in ch]
        a, b = self._avec_pages({79: "CHAPITRE 1 !", 84: "acte 3", 90: "#4", 130: "épisode 5", 92: "CHAPITRE 6", 111: "CHAPITRE 7"})
        with a, b:
            sommaire._verifier_par_ouvertures(ch, lambda i: str(i).encode(), 140, 2)
        self.assertEqual(ch, origine)

    def test_numero_isole_ne_deplace_pas_un_sommaire_coherent(self):
        """Akame ga Kill ! 11 : « 52 » lu sur la page d'ouverture du 53 ; le sommaire (52 image 102) était juste."""
        ch = [{"num": float(n), "image": im} for n, im in ((49, 4), (50, 14), (51, 62), (52, 102), (53, 144), (54, 186))]
        origine = [dict(c) for c in ch]
        a, b = self._avec_pages({4: "CHAPITRE 49", 14: "CHAPITRE 50", 62: "CHAPITRE 51", 143: "CHAPITRE 52", 186: "CHAPITRE 54"})
        with a, b:
            sommaire._verifier_par_ouvertures(ch, lambda i: str(i).encode(), 240, 3, douteux=False)
        self.assertEqual(ch, origine)

    def test_tome_entier_decale_recale(self):
        """20th Century Boys 1 : le sommaire place tout quelques pages trop tôt ; les pages d'ouverture font foi."""
        ch = [{"num": float(n), "image": im} for n, im in ((1, 6), (2, 34), (3, 54), (4, 74))]
        a, b = self._avec_pages({6: "CHAPITRE 1", 40: "CHAPITRE 2", 59: "CHAPITRE 3", 79: "CHAPITRE 4"})
        with a, b:
            sommaire._verifier_par_ouvertures(ch, lambda i: str(i).encode(), 100, 2, douteux=False)
        self.assertEqual([c["image"] for c in ch], [6, 40, 59, 79])

    def test_decalage_qui_grandit_recale(self):
        """Air Gear 5 : pages de couleur au fil du tome, le décalage du sommaire grandit (−7, −11, −13) : tout est recalé."""
        ch = [{"num": float(n), "image": im} for n, im in ((33, 12), (34, 35), (35, 54), (36, 74), (37, 94))]
        a, b = self._avec_pages({5: "TRICK 33", 26: "TRICK 34", 43: "TRICK 35", 63: "TRICK 36", 81: "TRICK 37"})
        with a, b:
            sommaire._verifier_par_ouvertures(ch, lambda i: str(i).encode(), 120, 4, douteux=False)
        self.assertEqual([c["image"] for c in ch], [5, 26, 43, 63, 81])

    def test_numero_imprime_apres_le_debut_garde_le_sommaire(self):
        """Akame ga Kill ! 9 : « CHAPITRE N » est sur la 3e ou 4e page de chaque chapitre (+2, +2, +3, +2) ; le sommaire était juste."""
        ch = [{"num": float(n), "image": im} for n, im in ((39, 4), (40, 48), (41, 86), (42, 132), (43, 178))]
        origine = [dict(c) for c in ch]
        a, b = self._avec_pages({6: "CHAPITRE 39", 50: "CHAPITRE 40", 89: "CHAPITRE 41", 134: "CHAPITRE 42", 180: "CHAPITRE 43"})
        with a, b:
            sommaire._verifier_par_ouvertures(ch, lambda i: str(i).encode(), 277, 3, douteux=False)
        self.assertEqual(ch, origine)


if __name__ == "__main__":
    unittest.main()
