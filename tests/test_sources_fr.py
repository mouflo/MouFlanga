import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sources_fr as S

JPEG = b"\xff\xd8\xff" + b"x" * 3000

FICHE = """<div class="eplister" id="chapterlist"><ul>
<li data-num="Volume 2"><div class="chbox"><div class="eph-num"><a href="https://exemple.test/serie-volume-2/"><span class="chapternum"> Volume 2</span></a></div></div></li>
<li data-num="Chapitre 12.5"><div class="chbox"><div class="eph-num"><a href="https://exemple.test/serie-chapitre-12-5/"><span class="chapternum">Chapitre 12.5</span></a></div></div></li>
<li data-num="Volume 1"><div class="chbox"><div class="eph-num"><a href="https://exemple.test/serie-volume-1/"><span class="chapternum"> Volume 1</span></a></div></div></li>
</ul></div>"""

RECHERCHE = """<div class="listupd"><div class="bs"><div class="bsx"><a href="https://exemple.test/catalogue/ma-serie/" title="Ma S&eacute;rie">
<span class="typename Manga">Manga</span><div class="tt">Ma Série</div></a></div></div>
<div class="bs"><div class="bsx"><a href="https://exemple.test/autre-page/" title="Pas une série"><div class="tt">X</div></a></div></div></div>"""

LECTEUR = ('<script>ts_reader.run({"post_id":1,"sources":[{"source":"Server 1","images":'
           '["https:\\/\\/img.exemple.test\\/p1.jpg","https:\\/\\/img.exemple.test\\/p2.jpg","https:\\/\\/img.exemple.test\\/p3.jpg"]}]});</script>')


class MangaThemesiaTest(unittest.TestCase):
    def setUp(self):
        self.s = S.MangaThemesia("exemple", "Exemple", "https://exemple.test")

    def test_recherche_garde_les_series_seulement(self):
        with mock.patch.object(S.CLIENT, "get", return_value=RECHERCHE):
            r = self.s.rechercher("ma série")
        self.assertEqual([m["title"] for m in r], ["Ma Série"])
        self.assertEqual(r[0]["url"], "https://exemple.test/catalogue/ma-serie/")

    def test_chapitres_et_volumes(self):
        with mock.patch.object(S.CLIENT, "get", return_value=FICHE):
            c = self.s.chapitres("https://exemple.test/catalogue/ma-serie/")
        self.assertEqual([x["chapter_id"] for x in c], ["2", "12.5", "1"])
        self.assertEqual([x.get("volume") for x in c], [2, None, 1])

    def test_pages_du_lecteur(self):
        with mock.patch.object(S.CLIENT, "get", return_value=LECTEUR):
            a = self.s.adresses_des_pages("https://exemple.test/serie-volume-1/")
        self.assertEqual(a, ["https://img.exemple.test/p1.jpg", "https://img.exemple.test/p2.jpg", "https://img.exemple.test/p3.jpg"])

    def test_pages_de_la_zone_de_lecture_a_defaut(self):
        html = '<div id="readerarea"><img src="/a.jpg"><img data-src="/b.jpg" src="data:image/gif;base64,AAA"></div>'
        with mock.patch.object(S.CLIENT, "get", return_value=html):
            a = self.s.adresses_des_pages("https://exemple.test/c/")
        self.assertEqual(a, ["https://exemple.test/a.jpg", "https://exemple.test/b.jpg"])

    def test_une_page_manquante_annule_le_chapitre(self):
        def get(url, **kw):
            if kw.get("binaire"):
                if url.endswith("p2.jpg"):
                    raise S.SourceErreur("introuvable")
                return JPEG
            return LECTEUR
        with mock.patch.object(S.CLIENT, "get", side_effect=get):
            self.assertEqual(self.s.pages("https://exemple.test/serie-volume-1/"), [])

    def test_une_page_qui_n_est_pas_une_image_annule_le_chapitre(self):
        def get(url, **kw):
            return (b"<html>un instant</html>" * 200) if kw.get("binaire") else LECTEUR
        with mock.patch.object(S.CLIENT, "get", side_effect=get):
            self.assertEqual(self.s.pages("https://exemple.test/serie-volume-1/"), [])

    def test_toutes_les_pages_lues(self):
        def get(url, **kw):
            return JPEG if kw.get("binaire") else LECTEUR
        with mock.patch.object(S.CLIENT, "get", side_effect=get):
            self.assertEqual(len(self.s.pages("https://exemple.test/serie-volume-1/")), 3)


class ClientTest(unittest.TestCase):
    def test_un_refus_met_le_site_en_pause_sans_rien_contourner(self):
        c = S._Client()
        rep = mock.Mock(status_code=403, text="", content=b"")
        with mock.patch.object(c.session, "get", return_value=rep), mock.patch.object(c, "autorise", return_value=True):
            with self.assertRaises(S.SourceErreur):
                c.get("https://ferme.test/x")
            appels = c.session.get.call_count
            with self.assertRaises(S.SourceErreur):
                c.get("https://ferme.test/y")
            self.assertEqual(c.session.get.call_count, appels)       # en pause : aucune nouvelle requête

    def test_robots_txt_interdit(self):
        c = S._Client()
        rep = mock.Mock(status_code=200, text="User-agent: *\nDisallow: /secret/\n")
        with mock.patch.object(c.session, "get", return_value=rep), mock.patch.object(S, "DELAI_PAR_SITE", 0):
            self.assertFalse(c.autorise("https://a.test/secret/page"))
            self.assertTrue(c.autorise("https://a.test/ok"))


class TelechargementTest(unittest.TestCase):
    def test_volume_complet_jamais_par_dessus_un_tome_present(self):
        import japscan_scraper as J
        import tomes_cbz
        src = mock.Mock(nom="Exemple")
        src.pages.return_value = [JPEG, JPEG]
        with tempfile.TemporaryDirectory() as t:
            dossier = Path(t) / "Ma Série"
            existant = tomes_cbz.fichier_tome(dossier, "Ma Série", 1)
            existant.parent.mkdir(parents=True)
            existant.write_bytes(b"ORIGINAL")
            J.download_depuis_source("jtest", "Ma Série", [{"title": "Volume 1", "url": "u1", "chapter_id": "1", "volume": 1},
                                                           {"title": "Volume 2", "url": "u2", "chapter_id": "2", "volume": 2}],
                                     dossier, src)
            self.assertEqual(existant.read_bytes(), b"ORIGINAL")
            self.assertTrue(tomes_cbz.fichier_tome(dossier, "Ma Série", 2).exists())
            job = J.download_jobs["jtest"]
            self.assertEqual(job["status"], "completed")
            self.assertIn("Volume 1 (tome déjà présent)", job["failed"])

    def test_trois_chapitres_sans_page_arretent_le_telechargement(self):
        import japscan_scraper as J
        src = mock.Mock(nom="Exemple")
        src.pages.return_value = []
        with tempfile.TemporaryDirectory() as t, mock.patch.object(J.asyncio, "sleep", mock.AsyncMock()):
            J.download_depuis_source("jtest2", "Série", [{"title": f"C{i}", "url": "u", "chapter_id": str(i)} for i in range(5)],
                                     Path(t) / "Série", src)
            self.assertEqual(J.download_jobs["jtest2"]["status"], "error")
            self.assertEqual(src.pages.call_count, 3)


if __name__ == "__main__":
    unittest.main()


LISTE_MADARA = """<ul class="main version-chap"><li class="wp-manga-chapter"><a href="https://exemple.test/manga/ma-serie/chapitre-12-5/"> Chapitre 12.5 </a></li>
<li class="wp-manga-chapter"><a href="https://exemple.test/manga/ma-serie/chapitre-12/">Chapitre 12</a></li>
<li class="wp-manga-chapter"><a href="#">Lien vide</a></li></ul>"""

RECHERCHE_MADARA = """<div class="c-tabs-item__content"><div class="post-title"><h3><a href="https://exemple.test/manga/ma-serie/">Ma S&eacute;rie</a></h3></div></div>"""

PAGES_MADARA = """<div class="reading-content">
<img id="image-0" data-src="
   https://img.exemple.test/0.jpg" class="wp-manga-chapter-img">
<img id="image-1" data-src="https://img.exemple.test/1.jpg" class="wp-manga-chapter-img">
<img src="data:image/gif;base64,AAAA"></div>"""


class MadaraTest(unittest.TestCase):
    def setUp(self):
        self.s = S.Madara("exemple", "Exemple", "https://exemple.test")

    def test_recherche(self):
        with mock.patch.object(S.CLIENT, "get", return_value=RECHERCHE_MADARA):
            r = self.s.rechercher("ma série")
        self.assertEqual([m["title"] for m in r], ["Ma Série"])
        self.assertEqual(r[0]["url"], "https://exemple.test/manga/ma-serie/")

    def test_chapitres_par_la_liste_ajax(self):
        rep = mock.Mock(status_code=200, text=LISTE_MADARA)
        with mock.patch.object(S.CLIENT, "autorise", return_value=True), mock.patch.object(S.CLIENT, "_attendre"), \
                mock.patch.object(S.CLIENT.session, "post", return_value=rep):
            c = self.s.chapitres("https://exemple.test/manga/ma-serie/")
        self.assertEqual([x["chapter_id"] for x in c], ["12.5", "12"])
        self.assertTrue(all("volume" not in x for x in c))

    def test_chapitres_repli_sur_la_fiche(self):
        rep = mock.Mock(status_code=404, text="")
        with mock.patch.object(S.CLIENT, "autorise", return_value=True), mock.patch.object(S.CLIENT, "_attendre"), \
                mock.patch.object(S.CLIENT.session, "post", return_value=rep), mock.patch.object(S.CLIENT, "get", return_value=LISTE_MADARA):
            self.assertEqual(len(self.s.chapitres("https://exemple.test/manga/ma-serie/")), 2)

    def test_pages_sans_les_images_de_remplissage(self):
        with mock.patch.object(S.CLIENT, "get", return_value=PAGES_MADARA):
            a = self.s.adresses_des_pages("https://exemple.test/manga/ma-serie/chapitre-1/")
        self.assertEqual(a, ["https://img.exemple.test/0.jpg", "https://img.exemple.test/1.jpg"])
