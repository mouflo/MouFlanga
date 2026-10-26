"""🎯 Vérification des pages des chapitres au lecteur : un chapitre enregistré à la fois, décalage des suivants, décalage appris
de la série (jamais appliqué à un tome saisi ou validé à la main), chapitres d'un tome complet pour le lecteur."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402
import edition  # noqa: E402


def lecture_auto(images, nums=None):
    nums = nums or list(range(1, len(images) + 1))
    return {"chapitres": [{"num": float(n), "titre": f"Titre {n}", "page": im, "image": im} for n, im in zip(nums, images)],
            "page_sommaire": 3, "version": 10}


class Base(unittest.TestCase):
    def setUp(self):
        self.infos = {"sommaires": {"1": lecture_auto([8, 30, 52, 74]), "2": lecture_auto([6, 27, 50], [5, 6, 7]),
                                    "3": dict(lecture_auto([5, 25]), valide_le="2026-10-20", manuel=True)}}
        self.ecrit = []
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()
        self.patches = [
            mock.patch.object(edition, "lire", lambda d: self.infos),
            mock.patch.object(edition, "ecrire", lambda d, x: self.ecrit.append(copy.deepcopy(x))),
            mock.patch.object(app, "_scan", lambda: {"Série": []}),
            mock.patch.object(app, "_tome_complet", lambda n, t: {"path": "Série/Tome 01/t.cbz", "key": "Série/Tome 01/t.cbz"}),
            mock.patch.object(app.archives, "pages", lambda c: [f"{i}.jpg" for i in range(120)]),
            mock.patch.object(app.auth, "role", lambda: "admin"),
            mock.patch.object(app, "_edition_differente", lambda n: False),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def post(self, url, corps):
        return self.client.post(url, data=json.dumps(corps), content_type="application/json").get_json()


class UnChapitreALaFois(Base):
    def test_page_corrigee_enregistree_tout_de_suite(self):
        r = self.post("/api/tome/chapitre_page", {"series": "Série", "tome": 1, "num": 2, "image": 29})
        self.assertTrue(r["ok"])
        lu = self.infos["sommaires"]["1"]
        c = lu["chapitres"][1]
        self.assertEqual((c["image"], c["auto_image"], c["verifie"]), (29, 30, True))
        self.assertTrue(lu["saisie"] and lu["manuel"])
        self.assertNotIn("valide_le", lu)
        self.assertEqual(lu["chapitres"][0]["auto_image"], 8)            # places automatiques gardées pour apprendre
        self.assertEqual(len(self.ecrit), 1)

    def test_bonne_page(self):
        r = self.post("/api/tome/chapitre_page", {"series": "Série", "tome": 1, "num": 1})
        self.assertTrue(r["ok"])
        self.assertEqual(self.infos["sommaires"]["1"]["chapitres"][0]["image"], 8)
        self.assertTrue(self.infos["sommaires"]["1"]["chapitres"][0]["verifie"])

    def test_revoir_sans_changement_rien_ecrit(self):
        # ↺ Revoir un tome validé : « C'est la bonne page » ou la même page posée ne touchent à rien, il reste validé
        lu = self.infos["sommaires"]["3"]
        lu["chapitres"][0]["verifie"] = True
        for corps in ({"num": 1}, {"num": 1, "image": 5}):
            r = self.post("/api/tome/chapitre_page", dict(corps, series="Série", tome=3))
            self.assertTrue(r["ok"] and r["valide"])
        self.assertEqual(self.ecrit, [])
        self.assertEqual(lu["valide_le"], "2026-10-20")
        # Une vraie correction, elle, est enregistrée (et le tome est à revalider)
        r = self.post("/api/tome/chapitre_page", {"series": "Série", "tome": 3, "num": 1, "image": 6})
        self.assertTrue(r["ok"] and not r["valide"])
        self.assertEqual((len(self.ecrit), lu["chapitres"][0]["image"]), (1, 6))
        self.assertNotIn("valide_le", lu)

    def test_page_hors_du_tome_refusee(self):
        r = self.post("/api/tome/chapitre_page", {"series": "Série", "tome": 1, "num": 1, "image": 500})
        self.assertFalse(r["ok"])
        self.assertEqual(self.ecrit, [])

    def test_decaler_les_suivants_non_verifies(self):
        self.post("/api/tome/chapitre_page", {"series": "Série", "tome": 1, "num": 2, "image": 29})
        r = self.post("/api/tome/chapitres_decaler", {"series": "Série", "tome": 1, "apres": 2, "decalage": -1})
        self.assertEqual(r["decales"], 2)
        self.assertEqual([c["image"] for c in self.infos["sommaires"]["1"]["chapitres"]], [8, 29, 51, 73])


class DecalageAppris(Base):
    def test_appris_et_applique_aux_lectures_automatiques_seulement(self):
        for num, image in ((1, 7), (2, 29), (3, 51), (4, 73)):
            self.post("/api/tome/chapitre_page", {"series": "Série", "tome": 1, "num": num, "image": image})
        self.assertEqual(app._decalage_de_serie(self.infos), 0)          # 4 chapitres vérifiés : pas encore assez
        self.infos["sommaires"]["4"] = lecture_auto([4, 24, 44], [8, 9, 10])
        reponses = [self.post("/api/tome/chapitre_page", {"series": "Série", "tome": 4, "num": num, "image": image})
                    for num, image in ((8, 3), (9, 24))]
        # 5e chapitre vérifié (encore −1) : −1 appris, appliqué au tome 2 (automatique), jamais au tome 3 (validé) ;
        # le 6e (bonne page) ne change pas l'apprentissage (5 sur 6)
        self.assertEqual([(r["decalage"], r["tomes_recales"]) for r in reponses], [(-1, 1), (-1, 0)])
        self.assertEqual([c["image"] for c in self.infos["sommaires"]["2"]["chapitres"]], [5, 26, 49])
        self.assertEqual(self.infos["sommaires"]["2"]["decalage_appris"], -1)
        self.assertEqual([c["image"] for c in self.infos["sommaires"]["3"]["chapitres"]], [5, 25])
        self.assertEqual(self.infos["decalage_chapitres"], -1)
        # une seule fois : rejouer ne décale pas encore
        app._appliquer_decalage_appris("Série", self.infos)
        self.assertEqual([c["image"] for c in self.infos["sommaires"]["2"]["chapitres"]], [5, 26, 49])

    def test_ecarts_disperses_rien_appris(self):
        self.infos["sommaires"]["1"]["chapitres"] = [{"num": float(n), "image": im + d, "auto_image": im, "verifie": True}
                                                    for n, im, d in ((1, 8, -1), (2, 30, 1), (3, 52, 0), (4, 74, -2), (5, 90, 2))]
        self.assertEqual(app._decalage_de_serie(self.infos), 0)


class ChapitresPourLeLecteur(Base):
    def test_liste(self):
        self.patches.append(mock.patch.object(app.tomes, "_charger", lambda n: {"titres_tomes": {"details": {"1": {"chapitres": ["1. Venu de Wikipédia"]}}}}))
        self.patches[-1].start()
        self.infos["sommaires"]["1"]["chapitres"][0]["titre"] = ""
        d = self.client.get("/api/lecteur/chapitres?s=S%C3%A9rie&tome=1").get_json()
        self.assertEqual([(c["num"], c["image"], c["titre"]) for c in d["chapitres"]][:2], [(1.0, 8, "Venu de Wikipédia"), (2.0, 30, "Titre 2")])
        self.assertEqual(self.ecrit, [])                                   # rien n'est écrit


class NouvelleLectureDecalee(Base):
    def test_lecture_automatique_recoit_le_decalage_appris(self):
        import sommaire
        self.infos["decalage_chapitres"] = -1
        pris = {}
        with mock.patch.object(sommaire, "lancer", lambda *a, **k: pris.update(enregistrer=a[5])), \
                mock.patch.object(app, "_numeros_fiables", lambda n, t: []), mock.patch.object(app, "_suite_de", lambda n, t: None):
            app._lire_sommaire("Série", 5, {"path": "Série/Tome 05/t.cbz"})
            pris["enregistrer"](dict(lecture_auto([9, 31]), version=sommaire.VERSION))
        lu = self.infos["sommaires"]["5"]
        self.assertEqual([c["image"] for c in lu["chapitres"]], [8, 30])
        self.assertEqual(lu["decalage_appris"], -1)


if __name__ == "__main__":
    unittest.main()
