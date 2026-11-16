"""Sites d'éditeurs : éditeur d'un ISBN, page acceptée seulement si elle prouve son ISBN, résumés coupés refusés, plans de site gardés,
un éditeur en panne ou cassé n'arrête pas les autres, couvertures proposées."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import editeurs  # noqa: E402
import reseau  # noqa: E402

RESUME = "Noritaka Sawamura est un collégien timide et maigrichon souvent chahuté par ses camarades de classe."
PAGE_PIKA = ('<html><head><script type="application/ld+json">{"@graph":[{"@type":"Organization","name":"Pika"},'
             '{"@type":"Book","name":"Four Knights T09","isbn":"9782811678920","numberOfPages":192,"datePublished":"2023-06-21",'
             f'"description":"{RESUME}..."}},{{"@type":"Book","name":"Four Knights T10","isbn":"9782811678999"}}]}}</script>'
             '<meta property="og:image" content="https://media.hachette.fr/fit-in/500x500/imgArticle/PIKA/2023/9782811678920-001-X.jpeg?v=1"></head>'
             '<body>Voir aussi 9782811648756</body></html>')
PAGE_KANA = ('<html><head><script type="application/ld+json">{"@type":"Product","name":"Buster Keel&nbsp;! T10",'
             '"description":"L\'affrontement reprend après soixante ans de trêve ! La toute dernière relique est ..."}</script>'
             '<meta property="og:image" content="https://bdi.dlpdomain.com/album/9782505060093-couv-M480x676.jpg"></head><body>'
             '<div class="hero-area__description"><p>' + RESUME + ' Suite de l\'histoire.</p></div>'
             '<table><tr><td class="col-0" >Parution</td><td class="col-1" >21 mars 2014</td></tr>'
             '<tr><td class="col-0" >ISBN&nbsp;/&nbsp;EAN</td><td class="col-1" >9782505060093</td></tr>'
             '<tr><td class="col-0" >Nb de pages</td><td class="col-1" >192</td></tr></table>'
             '<a href="/produit/buster-keel-t11/">9782505060109</a></body></html>')


def page(texte, statut=200):
    return mock.Mock(statut=statut, texte=texte)


class EditeurDeTest(unittest.TestCase):
    def test_par_prefixe_puis_par_nom(self):
        self.assertEqual(editeurs.editeur_de("9782811678920"), "pika")
        self.assertEqual(editeurs.editeur_de("9782505060093"), "kana")
        self.assertEqual(editeurs.editeur_de("9782820332233"), "kaze")
        self.assertEqual(editeurs.editeur_de("9782000000000", "Pika éd."), "pika")
        self.assertEqual(editeurs.editeur_de("9782000000000", "Crunchyroll"), "kaze")
        self.assertEqual(editeurs.editeur_de("9782000000000", "Éditions Delcourt"), "")      # pas de lecteur : refusé
        self.assertEqual(editeurs.editeur_de("", ""), "")


class AnalyserTest(unittest.TestCase):
    def test_page_qui_prouve_son_isbn(self):
        o = editeurs.analyser(PAGE_PIKA, "https://www.pika.fr/livre/four-knights-t09-9782811678920/", "9782811678920", "Pika")
        self.assertEqual(o["pages"], 192)
        self.assertEqual(o["date"], "2023-06-21")
        self.assertTrue(o["resume"].endswith("..."))           # un résumé complet qui finit par des points n'est pas « coupé »
        self.assertEqual(o["couverture"], "https://www.images.hachette-livre.fr/media/imgArticle/PIKA/2023/9782811678920-001-X.jpeg")

    def test_isbn_seulement_cite_dans_la_page_est_refuse(self):
        self.assertIsNone(editeurs.analyser(PAGE_PIKA, "https://www.pika.fr/livre/x/", "9782811648756", "Pika"))
        self.assertIsNone(editeurs.analyser("<html>9782811678920</html>", "https://x/", "9782811678920", "Pika"))      # écrit, mais pas prouvé

    def test_kana_resume_complet_date_et_pages_du_tableau(self):
        o = editeurs.analyser(PAGE_KANA, "https://www.kana.fr/produit/buster-keel-t10/", "9782505060093", "Kana")
        self.assertTrue(o["resume"].startswith("Noritaka Sawamura"))      # le texte du bloc, pas celui, coupé, des données structurées
        self.assertEqual((o["date"], o["pages"], o["titre"]), ("2014-03-21", 192, "Buster Keel ! T10"))
        self.assertIsNone(editeurs.analyser(PAGE_KANA, "https://www.kana.fr/produit/buster-keel-t10/", "9782505060109", "Kana"))

    def test_resume_toujours_coupe_est_ecarte(self):
        coupe = PAGE_KANA.replace('<div class="hero-area__description"><p>' + RESUME + " Suite de l'histoire.</p></div>", "")
        o = editeurs.analyser(coupe, "https://www.kana.fr/produit/buster-keel-t10/", "9782505060093", "Kana")
        self.assertNotIn("resume", o)
        self.assertIn("couverture", o)


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ancien = (editeurs.DOSSIER, dict(editeurs._MEMOIRE))
        editeurs.DOSSIER = Path(self.tmp.name)
        editeurs._MEMOIRE.clear()

    def tearDown(self):
        editeurs.DOSSIER = self.ancien[0]
        editeurs._MEMOIRE.clear()
        editeurs._MEMOIRE.update(self.ancien[1])
        self.tmp.cleanup()

    PLAN = ("<urlset><url><loc>https://www.pika.fr/livre/a-t01-9782811678920/</loc></url>"
            "<url><loc>https://www.pika.fr/category/x</loc></url></urlset>")

    def test_index_garde_sur_disque_et_ne_redemande_pas(self):
        with mock.patch.object(editeurs.reseau, "get", return_value=page(self.PLAN)) as g:
            self.assertEqual(editeurs.index("pika", "https://www.pika.fr/products.xml"),
                             {"9782811678920": "https://www.pika.fr/livre/a-t01-9782811678920/"})
            editeurs._MEMOIRE.clear()                            # un redémarrage : relu du disque
            editeurs.index("pika", "https://www.pika.fr/products.xml")
        self.assertEqual(g.call_count, 1)

    def test_panne_garde_l_ancien_plan_ou_la_rend(self):
        with mock.patch.object(editeurs.reseau, "get", side_effect=reseau.Panne("pika", "coupé")):
            with self.assertRaises(reseau.Panne):
                editeurs.index("pika", "https://www.pika.fr/products.xml")
        editeurs.DOSSIER.mkdir(exist_ok=True)
        editeurs._fichier_index("pika").write_text(json.dumps({"date": time.time() - 9 * 86400, "urls": {"9782811678920": "https://u/"}}))
        with mock.patch.object(editeurs.reseau, "get", side_effect=reseau.Panne("pika", "coupé")):
            self.assertEqual(editeurs.index("pika", "https://www.pika.fr/products.xml"), {"9782811678920": "https://u/"})

    def test_plan_de_plans_et_filtre_des_prefixes(self):
        racine = "<sitemapindex><sitemap><loc>https://www.lisez.com/sitemap.xml?page=1</loc></sitemap></sitemapindex>"
        sous = ("<urlset><url><loc>https://www.lisez.com/livres/soul-eater-tome-25/9782368520215</loc></url>"
                "<url><loc>https://www.lisez.com/livres/autre/9782412051030</loc></url></urlset>")
        with mock.patch.object(editeurs.reseau, "get", side_effect=[page(racine), page(sous)]):
            r = editeurs.index("lisez", "https://www.lisez.com/sitemap.xml", {"97823685"})
        self.assertEqual(list(r), ["9782368520215"])


class ChercherTest(unittest.TestCase):
    def test_un_editeur_en_panne_ou_casse_n_arrete_pas_les_autres(self):
        def faux(cle, isbn, noms, tome):
            if cle == "pika":
                raise reseau.Panne("Pika", "coupé")
            if cle == "kaze":
                raise KeyError("le site a changé")
            return {"isbn": isbn, "editeur": cle} if tome != 4 else None
        cibles = {1: ("9782811678920", "pika"), 2: ("9782811678921", "pika"), 3: ("9782505060093", "kana"),
                  4: ("9782505060109", "kana"), 5: ("9782820332233", "kaze")}
        with mock.patch.object(editeurs, "trouver", side_effect=faux) as t:
            trouves, cherches, pannes = editeurs.chercher(["Série"], cibles)
        self.assertEqual(sorted(trouves), [3])
        self.assertEqual(cherches, {3, 4})                      # les tomes des éditeurs muets ne comptent pas comme « cherchés »
        self.assertEqual(len(pannes), 1)
        self.assertEqual(t.call_count, 4)                       # Pika : un seul essai puis laissé de côté

    def test_kana_essaie_le_nom_puis_se_rabat_sur_la_couverture_par_isbn(self):
        reponses = {"https://www.kana.fr/produit/buster-keel-t10/": page(PAGE_KANA),
                    "https://bdi.dlpdomain.com/album/9782505009054-couv-M480x676.jpg": page("img")}
        sortie = lambda url, **kw: reponses.get(url, page("", 404))
        with mock.patch.object(editeurs.reseau, "get", side_effect=sortie):
            self.assertEqual(editeurs.trouver("kana", "9782505060093", ["Buster Keel !"], 10)["pages"], 192)
            autre = editeurs.trouver("kana", "9782505009054", ["Death Note"], 1)      # pas de page à ce nom : la couverture seule
            self.assertEqual(autre, {"isbn": "9782505009054", "editeur": "Kana",
                                     "couverture": "https://bdi.dlpdomain.com/album/9782505009054-couv-M480x676.jpg"})
            self.assertIsNone(editeurs.trouver("kana", "9782505099999", ["Inconnu"], 3))

    def test_kaze_par_la_suggestion_du_site(self):
        sugg = mock.Mock(statut=200)
        sugg.json.return_value = {"resources": {"results": {"products": [{"url": "/products/the-promised-neverland-t01?_pos=1"}]}}}
        fiche = ('<script type="application/ld+json">{"@type":"Book","isbn":"9782820332233","name":"TPN T01"}</script>'
                 f'<script type="application/ld+json">{{"@type":"Product","gtin13":"9782820332233","description":"{RESUME}",'
                 '"image":"http://kazemanga.fr/cdn/shop/files/9782820332233.jpg"}</script>')
        with mock.patch.object(editeurs.reseau, "get", side_effect=[sugg, page(fiche)]):
            o = editeurs.trouver("kaze", "9782820332233", ["The Promised Neverland"], 1)
        self.assertEqual(o["resume"], RESUME)
        self.assertTrue(o["couverture"].startswith("https://kazemanga.fr/cdn/shop/"))


class SerieTest(unittest.TestCase):
    def test_couvertures_des_editeurs(self):
        obs = {"1": {"editeur": {"couverture": "https://bdi.dlpdomain.com/album/1-couv-M480x676.jpg", "editeur": "Kana"}},
               "2": {"editeur": {"couverture": "https://exemple.org/x.jpg", "editeur": "Kana"}},          # adresse inconnue : refusée
               "3": {"google": {"isbn": "9782505060093"}}}
        with mock.patch("notices.observations", return_value=obs):
            c = editeurs.couvertures("Série")
        self.assertEqual(list(c), [1])
        self.assertEqual(c[1][0]["source"], "Kana")
        self.assertTrue(editeurs.image_autorisee("https://api.ki-oon.com/images/volumes/9782355924057.webp"))
        self.assertFalse(editeurs.image_autorisee("https://exemple.org/a.jpg"))


if __name__ == "__main__":
    unittest.main()
