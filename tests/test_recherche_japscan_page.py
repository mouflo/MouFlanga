"""Recherche Japscan lue dans la page /catalogue : titres propres, seulement les œuvres cherchées, une fois chacune."""
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import japscan_scraper as J  # noqa: E402


class ResultatsPageTest(unittest.TestCase):
    def test_etiquettes_du_site_ne_sont_pas_des_titres(self):
        brut = [["/manga/terra-formars/", "", ["En Cours", "Terra Formars"]], ["/manga/terra-formars/", "", ["Terminé"]],
                ["/manhua/autre-chose/", "", ["Terra"]], ["/manga/terra-formars-gaiden/", "", ["Terminé"]]]
        r = J._resultats_de_la_page(brut, "Terra formars")
        self.assertEqual([x["name"] for x in r], ["Terra Formars", "Terra Formars Gaiden"])

    def test_titre_du_lien_prefere(self):
        r = J._resultats_de_la_page([["/manga/terra-formars/", "Terra Formars", ["En Cours"]]], "terra formars")
        self.assertEqual(r[0]["name"], "Terra Formars")


if __name__ == "__main__":
    unittest.main()


class ChapitresDeLaPageTest(unittest.TestCase):
    def test_liste_de_volumes_de_la_nouvelle_presentation(self):
        from bs4 import BeautifulSoup
        html = ('<a href="/manga/terra-formars/1/1">Commencer la lecture</a>'
                '<ul><li><a data-chapter-slug="22" href="/manga/terra-formars/22/1">Volume 22 27 novembre 2021 · 208 p.</a></li>'
                '<li><a data-chapter-slug="1" href="/manga/terra-formars/1/1">Volume 1 27 novembre 2021 · 214 p.</a></li>'
                '<li><a data-chapter-slug="1" href="/manga/autre/1/1">Volume 1</a></li></ul>')
        r = J._chapitres_de_la_page(BeautifulSoup(html, "html.parser"), "terra-formars", "manga")
        self.assertEqual([(c["volume"], c["url"]) for c in r],
                         [(22, "https://japscan.st/manga/terra-formars/22/1"), (1, "https://japscan.st/manga/terra-formars/1/1")])


class _FausseReponse:
    def __init__(self, statut, corps):
        self.status, self._corps = statut, corps

    async def body(self):
        return self._corps


class _FausseRequete:
    def __init__(self, pages):
        self.pages, self.vus = pages, []

    async def get(self, url, headers=None, timeout=None):
        self.vus.append((url, (headers or {}).get("Referer")))
        return self.pages.get(url, _FausseReponse(403, b""))


class _FausseContext:
    def __init__(self, pages):
        self.request = _FausseRequete(pages)


class _FausseFenetre:
    """Une page de lecteur : liste des adresses de pages, et l'image de la page ouverte."""
    def __init__(self, adresses, images):
        self.adresses, self.images, self.url = adresses, images, adresses[0] if adresses else ""

    async def evaluate(self, js):
        if "data-page-select" in js:
            return list(self.adresses)
        if "data-page-img" in js:
            return self.images.get(self.url, "")
        return None

    async def goto(self, url, **kw):
        self.url = url


class LecteurParPagesTest(unittest.TestCase):
    def _lire(self, adresses, images, reponses):
        import asyncio
        s = J.JapscanScraper(Path("/tmp"))
        ctx, fen = _FausseContext(reponses), _FausseFenetre(adresses, images)
        with unittest.mock.patch.object(J, "attendre_captcha", new=lambda *a, **k: _vrai()), \
                unittest.mock.patch.object(J.asyncio, "sleep", new=lambda *_: _vrai()):
            return asyncio.run(s._lire_page_par_page(ctx, fen, "https://japscan.st/manga/x/1/1")), ctx

    def test_toutes_les_pages_dans_l_ordre(self):
        a = ["https://japscan.st/manga/x/1/1", "https://japscan.st/manga/x/1/2"]
        imgs = {a[0]: "https://cdn/p1.jpg", a[1]: "https://cdn/p2.jpg"}
        rep = {"https://cdn/p1.jpg": _FausseReponse(200, b"A" * 3000), "https://cdn/p2.jpg": _FausseReponse(200, b"B" * 3000)}
        res, ctx = self._lire(a, imgs, rep)
        self.assertEqual([r[:1] for r in res], [b"A", b"B"])
        self.assertEqual(ctx.request.vus[1][1], a[1])             # l'adresse de la page sert d'origine

    def test_une_page_manquante_annule_tout(self):
        a = ["https://japscan.st/manga/x/1/1", "https://japscan.st/manga/x/1/2"]
        imgs = {a[0]: "https://cdn/p1.jpg", a[1]: "https://cdn/p2.jpg"}
        rep = {"https://cdn/p1.jpg": _FausseReponse(200, b"A" * 3000)}      # la 2e est refusée (403)
        res, _ = self._lire(a, imgs, rep)
        self.assertEqual(res, [])

    def test_ancienne_presentation_rend_une_liste_vide(self):
        res, _ = self._lire([], {}, {})
        self.assertEqual(res, [])


async def _vrai():
    return True
