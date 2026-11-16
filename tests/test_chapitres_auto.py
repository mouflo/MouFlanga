"""Chapitres automatiques : confiance d'un sommaire, place confirmée par les numéros de page, titres posés seuls."""
import io
import unittest

from PIL import Image

import chapitres_auto as ca


def _tome(nb=60, doubles=(), premiere_page=1, sans_numero=()):
    """Un tome simulé : `nb` images, certaines en double page, numérotées à partir de `premiere_page` (image 0).
    Renvoie (ratios, folios) comme `relever`."""
    ratios = [1.4 if i in doubles else 0.7 for i in range(nb)]
    cum = ca.cumul(ratios)
    folios = {i: premiere_page + cum[i] for i in range(nb) if i not in doubles and i not in sans_numero}
    return ratios, folios


class NumerosDePageTest(unittest.TestCase):
    def test_une_double_page_compte_pour_deux(self):
        self.assertEqual(ca.cumul([0.7, 0.7, 1.4, 0.7]), [0, 1, 2, 4])

    def test_place_simple(self):
        ratios, folios = _tome(60, premiere_page=3)                 # image 0 = page 3
        image, n, total = ca.place_par_numeros(ratios, folios, 23)
        self.assertEqual(image, 20)
        self.assertEqual(n, total)                                  # tout le monde est d'accord
        self.assertEqual(ca.place_globale(ratios, folios, 23), 20)

    def test_place_apres_des_doubles_pages(self):
        ratios, folios = _tome(60, doubles=(10, 11), premiere_page=1)
        # images 0-9 = pages 1-10 ; image 10 = pages 11-12 ; image 11 = pages 13-14 ; image 12 = page 15
        self.assertEqual(ca.place_par_numeros(ratios, folios, 15)[0], 12)
        self.assertEqual(ca.place_par_numeros(ratios, folios, 12)[0], 10)      # page de droite d'une double page
        self.assertEqual(ca.place_globale(ratios, folios, 15), 12)

    def test_un_numero_mal_lu_ne_change_rien(self):
        ratios, folios = _tome(60)
        folios[30] = 999                                           # un chiffre lu de travers
        self.assertEqual(ca.place_par_numeros(ratios, folios, 31)[0], 30)

    def test_pas_assez_de_numeros(self):
        ratios, _ = _tome(60)
        self.assertEqual(ca.place_par_numeros(ratios, {5: 6}, 31), (None, 1, 1))
        self.assertIsNone(ca.place_globale(ratios, {5: 6, 6: 7}, 31))

    def test_page_hors_du_tome(self):
        ratios, folios = _tome(20)
        self.assertIsNone(ca.place_par_numeros(ratios, folios, 400)[0])


class ReleverTest(unittest.TestCase):
    def _image(self, w, h):
        s = io.BytesIO()
        Image.new("L", (w, h), 255).save(s, "PNG")
        return s.getvalue()

    def test_releve_les_formes_et_les_numeros(self):
        pages = [self._image(70, 100), self._image(140, 100), self._image(70, 100)]
        vus = []

        def numero(octets):
            vus.append(len(octets))
            return 12

        r = ca.relever(lambda i: pages[i], 3, numero)
        self.assertEqual(r["ratios"], [0.7, 1.4, 0.7])
        self.assertEqual(r["folios"], {0: 12, 2: 12})              # la double page n'est pas lue
        self.assertEqual(len(vus), 2)

    def test_page_illisible_et_arret(self):
        r = ca.relever(lambda i: b"pas une image", 2, lambda o: 1)
        self.assertEqual(r, {"ratios": [0, 0], "folios": {}})
        self.assertIsNone(ca.relever(lambda i: self._image(7, 10), 2, lambda o: 1, arret=lambda: True))


class ConfirmerTest(unittest.TestCase):
    def test_meme_place_confirmee(self):
        ratios, folios = _tome(60, premiere_page=1)
        ch = [{"num": 1.0, "titre": "", "page": 5, "image": 4}, {"num": 2.0, "titre": "", "page": 25, "image": 24, "estimee": True}]
        bilan = ca.confirmer(ch, ratios, folios)
        self.assertEqual(bilan, {"confirmes": 2, "corriges": 0, "sans_avis": 0, "total": 2})
        self.assertTrue(all(c["confirme"] for c in ch))
        self.assertNotIn("estimee", ch[1])                         # une page estimée mais confirmée n'est plus « estimée »

    def test_place_corrigee_quand_les_numeros_sont_nets(self):
        ratios, folios = _tome(60, doubles=(10, 11), premiere_page=1)
        ch = [{"num": 3.0, "titre": "", "page": 30, "image": 29}]   # le lecteur a oublié les deux doubles pages
        bilan = ca.confirmer(ch, ratios, folios)
        self.assertEqual(bilan["corriges"], 1)
        self.assertEqual(ch[0]["image"], 27)
        self.assertEqual(ch[0]["image_lue"], 29)
        self.assertTrue(ch[0]["corrige"])
        self.assertTrue(ch[0]["confirme"])              # les numéros de page font foi : la place n'est plus « à vérifier »
        self.assertEqual(ca.douteux({"chapitres": ch}), [])
        self.assertNotEqual(ca.confiance({"chapitres": ch})["niveau"], "a_verifier")

    def test_grand_ecart_reste_a_verifier(self):
        ratios, folios = _tome(120, premiere_page=1)
        ch = [{"num": 3.0, "titre": "", "page": 30, "image": 70}]   # 41 images d'écart : la page du sommaire est peut-être mal lue
        ca.confirmer(ch, ratios, folios)
        self.assertEqual(ch[0]["image"], 29)
        self.assertNotIn("confirme", ch[0])
        self.assertEqual(ca.confiance({"chapitres": ch})["niveau"], "a_verifier")

    def test_sans_numeros_rien_ne_change(self):
        ratios, _ = _tome(60)
        ch = [{"num": 1.0, "titre": "", "page": 5, "image": 9, "estimee": True}]
        bilan = ca.confirmer(ch, ratios, {})
        self.assertEqual(bilan["sans_avis"], 1)
        self.assertEqual(ch[0], {"num": 1.0, "titre": "", "page": 5, "image": 9, "estimee": True})

    def test_chapitre_sans_page_imprimee_ignore(self):
        ratios, folios = _tome(30)
        ch = [{"num": 1.0, "titre": ""}, {"num": 2.0, "titre": "", "page": 12, "image": 11, "special": True}]
        self.assertEqual(ca.confirmer(ch, ratios, folios)["total"], 0)


class ConfianceTest(unittest.TestCase):
    def _lu(self, **plus):
        lu = {"chapitres": [{"num": 1.0, "titre": "Un", "page": 5, "image": 4}, {"num": 2.0, "titre": "Deux", "page": 25, "image": 24}]}
        lu.update(plus)
        return lu

    def test_tome_valide_ou_saisi(self):
        for cle in ("valide_le", "saisie", "manuel"):
            self.assertEqual(ca.confiance(self._lu(**{cle: "2026-11-01"}))["niveau"], "valide", cle)
        # même avec des chapitres sans page : c'est elle qui décide
        self.assertEqual(ca.confiance({"chapitres": [{"num": 1.0, "titre": ""}], "saisie": True})["niveau"], "valide")

    def test_rien(self):
        self.assertEqual(ca.confiance(None)["niveau"], "aucun")
        self.assertEqual(ca.confiance({"chapitres": []})["niveau"], "aucun")

    def test_noms_des_images_sur(self):
        self.assertEqual(ca.confiance(self._lu(source="noms des images"))["niveau"], "sur")

    def test_sommaire_imprime_probable(self):
        c = ca.confiance(self._lu())
        self.assertEqual((c["niveau"], c["pastille"]), ("probable", "🟡"))
        lu = self._lu()
        for ch in lu["chapitres"]:
            ch["confirme"] = True
        c = ca.confiance(lu)
        self.assertEqual(c["niveau"], "probable")
        self.assertIn("confirmées", c["raisons"][0])
        self.assertEqual(c["confirmes"], 2)

    def test_a_verifier(self):
        self.assertEqual(ca.confiance(self._lu(source="pages d'ouverture"))["niveau"], "a_verifier")
        self.assertEqual(ca.confiance(self._lu(source="pages d'équipe"))["niveau"], "a_verifier")
        lu = self._lu()
        lu["chapitres"][1]["estimee"] = True
        self.assertEqual(ca.confiance(lu)["niveau"], "a_verifier")
        lu = self._lu()
        del lu["chapitres"][0]["image"]
        self.assertEqual(ca.confiance(lu)["niveau"], "a_verifier")
        lu = self._lu()
        lu["chapitres"][1]["num"] = 5.0                              # 1 puis 5 : il en manque
        self.assertIn("ne se suivent pas", " ".join(ca.confiance(lu)["raisons"]))
        lu = self._lu()
        lu["chapitres"][1]["image"] = 2                              # avant le chapitre 1
        self.assertEqual(ca.confiance(lu)["niveau"], "a_verifier")
        lu = self._lu()
        lu["chapitres"][0]["corrige"] = True
        self.assertEqual(ca.confiance(lu)["niveau"], "a_verifier")

    def test_chapitres_du_fichier(self):
        self.assertEqual(ca.confiance(self._lu(fichier=True))["niveau"], "probable")

    def test_bilan_et_phrase(self):
        sommaires = {"1": self._lu(valide_le="2026-11-01"), "2": self._lu(source="noms des images"), "3": self._lu(),
                     "4": self._lu(source="pages d'ouverture"), "5": self._lu(source="pages d'ouverture")}
        b = ca.bilan_serie(sommaires, [1, 2, 3, 4, 5, 6])
        self.assertEqual(b["comptes"], {"valide": 1, "sur": 1, "probable": 1, "a_verifier": 2, "aucun": 1})
        self.assertEqual(b["a_verifier"], [4, 5])
        self.assertEqual(b["aucun"], [6])
        self.assertEqual(ca.phrase(b), "📑 Chapitres : 2 sûrs · 1 probable · 2 à vérifier (T4-5) · 1 sans chapitres")
        self.assertEqual(ca.phrase(ca.bilan_serie({}, [])), "")

    def test_plages(self):
        self.assertEqual(ca.plages([1, 2, 3, 7, 9, 10]), "T1-3, T7, T9-10")

    def test_douteux(self):
        lu = self._lu()
        lu["chapitres"][1]["estimee"] = True
        self.assertEqual(ca.douteux(lu), [2.0])


class NommerTest(unittest.TestCase):
    def _serie(self):
        return {
            "1": {"chapitres": [{"num": float(n), "titre": f"Trick {n}"} for n in (1, 2, 3, 4)]},
            "2": {"chapitres": [{"num": 5.0, "titre": ""}, {"num": 6.0, "titre": "6"}, {"num": 7.0, "titre": "La grande course"}]},
            "3": {"chapitres": [{"num": 8.0, "titre": ""}], "valide_le": "2026-11-01"},
        }

    def test_nom_regulier_appris(self):
        ch = ca.nommer(self._serie(), [2, 3])
        self.assertEqual(ch, [{"tome": "2", "num": 5, "avant": "", "apres": "Trick 5"},
                              {"tome": "2", "num": 6, "avant": "6", "apres": "Trick 6"}])

    def test_tome_valide_jamais_touche(self):
        self.assertEqual(ca.nommer(self._serie(), [3]), [])

    def test_titres_officiels_quand_rien_appris(self):
        sommaires = {"1": {"chapitres": [{"num": 1.0, "titre": ""}, {"num": 2.0, "titre": "Déjà là"}, {"num": 3.0, "titre": ""}]}}
        ch = ca.nommer(sommaires, [1], {1: "Le départ", 2: "Autre titre"})
        self.assertEqual(ch, [{"tome": "1", "num": 1, "avant": "", "apres": "Le départ"}])

    def test_applique_par_titres_chapitres(self):
        import titres_chapitres
        sommaires = self._serie()
        n = titres_chapitres.appliquer(sommaires, ca.nommer(sommaires, [2]))
        self.assertEqual(n, 2)
        self.assertEqual([c["titre"] for c in sommaires["2"]["chapitres"]], ["Trick 5", "Trick 6", "La grande course"])


if __name__ == "__main__":
    unittest.main()
