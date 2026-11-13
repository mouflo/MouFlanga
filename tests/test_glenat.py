"""Glénat (éditeur) : « Rave - Édition originale » (384 pages par tome), reconnue d'après la page d'un tome donnée par la personne."""
import pathlib
import re
import unittest
from unittest import mock

import glenat
import reseau

F = pathlib.Path(__file__).parent / "fixtures"
URL1 = "https://www.glenat.com/glenat-manga/rave-edition-originale-tome-01-9782344060414/"
EDITION = "9782344060"           # début des ISBN de l'édition originale


def _page(tome: int, isbn: str) -> str:
    """La page du tome 1 (réelle, allégée), refaite pour un autre tome : même édition, autre numéro et autre ISBN."""
    p = (F / "glenat_rave_tome01.html").read_text(encoding="utf-8")
    p = re.sub(r'("numero_de_tome":\s*)"?\d+"?', rf'\g<1>"{tome}"', p)
    return p.replace("9782344060414", isbn).replace("Tome 01", f"Tome {tome:02d}")


class FauxGlenat:
    """Les tomes 1 à 16 existent (le tome 1 cite les tomes 2, 5 à 16 : jamais le 3 ni le 4) ; rien d'autre."""
    def __init__(self, panne=False):
        self.vues, self.panne = [], panne

    def __call__(self, url, **kw):
        if self.panne:
            raise reseau.Panne("glenat", "pas de réponse")
        self.vues.append(url)
        m = re.search(r"-tome-(\d+)-(97\d{11})/$", url)
        if not m or not m.group(2).startswith(EDITION) or not 1 <= int(m.group(1)) <= 16 or glenat.adresse(url).get("isbn") != glenat.isbn_du_tome(glenat.adresse(URL1), int(m.group(1))):
            return reseau.Reponse(404, "", {}, url, False)
        return reseau.Reponse(200, _page(int(m.group(1)), m.group(2)), {}, url, False)


class TestAdresse(unittest.TestCase):
    def test_page_d_un_tome(self):
        a = glenat.adresse(URL1)
        self.assertEqual((a["tome"], a["isbn"], a["base"]), (1, "9782344060414", "rave-edition-originale"))

    def test_adresses_refusees(self):
        for u in ("https://www.glenat.com/glenat-manga/rave-edition-originale-tome-01-9782344060414/?utm_source=x",   # paramètres : robots.txt
                  "https://www.glenat.com/recherche/?q=rave", "https://www.glenat.com/glenat-manga/rave-edition-originale-tome-01-9782344060415/",
                  "https://exemple.org/glenat-manga/rave-edition-originale-tome-01-9782344060414/", "", None):
            self.assertEqual(glenat.adresse(u), {}, u)

    def test_les_isbn_se_suivent(self):
        a = glenat.adresse(URL1)
        self.assertEqual([glenat.isbn_du_tome(a, t) for t in (2, 3, 4, 16)], ["9782344060421", "9782344060438", "9782344060445", "9782344060568"])


class TestLecture(unittest.TestCase):
    def test_fiche_du_tome_1(self):
        with mock.patch.object(reseau, "get", FauxGlenat()):
            f = glenat.lire_page(URL1)
        self.assertEqual((f["serie"], f["edition"], f["tome"], f["isbn"]), ("Rave", "Édition originale", 1, "9782344060414"))
        self.assertEqual((f["date"], f["pages"]), ("2024-04-03", 384))
        self.assertIn("Haru", f["resume"])
        self.assertEqual(f["autres_isbn"], ["9782331080470"])                        # le même tome en numérique
        self.assertEqual(sorted(f["voisins"]), [1, 2, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])      # pas le tome 30 d'une autre édition

    def test_les_tomes_voulus_meme_non_cites(self):
        faux = FauxGlenat()
        with mock.patch.object(reseau, "get", faux):
            out = glenat.chercher(URL1, voulus={1, 3, 4, 8})
        self.assertEqual(sorted(out), [1, 3, 4, 8])
        self.assertEqual([out[t]["isbn"] for t in (1, 3, 4, 8)], ["9782344060414", "9782344060438", "9782344060445", "9782344060483"])
        self.assertTrue(all(o["editeur"] == "Glénat" and o["pages"] == 384 for o in out.values()))
        self.assertEqual(len(faux.vues), 4)                                           # une page par tome voulu, pas plus

    def test_un_tome_qui_n_existe_pas_est_simplement_absent(self):
        with mock.patch.object(reseau, "get", FauxGlenat()):
            out = glenat.chercher(URL1, voulus={1, 17, 18})
        self.assertEqual(sorted(out), [1])

    def test_une_panne_n_est_pas_rien_trouve(self):
        with mock.patch.object(reseau, "get", FauxGlenat(panne=True)), self.assertRaises(reseau.Panne):
            glenat.chercher(URL1, voulus={1, 2})

    def test_adresse_illisible_ne_donne_rien(self):
        self.assertEqual(glenat.chercher("https://www.glenat.com/recherche/?q=rave"), {})


if __name__ == "__main__":
    unittest.main()


class TestEncodage(unittest.TestCase):
    """Une page sans charset annoncé est lue par requests en latin-1 : « Édition originale » devenait « Ã\x89dition originale »."""

    def test_page_utf8_sans_charset(self):
        from types import SimpleNamespace as R
        brut = "Édition originale".encode("utf-8")
        r = R(content=brut, headers={"Content-Type": "text/html"})
        self.assertEqual(reseau._texte_utf8(r, brut.decode("latin-1")), "Édition originale")

    def test_charset_annonce_ou_pas_utf8_ne_change_rien(self):
        from types import SimpleNamespace as R
        brut = "Édition".encode("latin-1")
        self.assertEqual(reseau._texte_utf8(R(content=brut, headers={"Content-Type": "text/html"}), "Édition"), "Édition")      # pas de l'UTF-8
        annonce = "Édition".encode("utf-8")
        self.assertEqual(reseau._texte_utf8(R(content=annonce, headers={"Content-Type": "text/html; charset=iso-8859-1"}), "texte requests"),
                         "texte requests")
        self.assertEqual(reseau._texte_utf8(R(headers={}), "simulé"), "simulé")                                                  # réponse simulée
