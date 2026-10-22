"""BnF (catalogue général, API SRU) : lecture des notices, tomes de la bonne série, une notice par tome, panne sans perte."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bnf  # noqa: E402
import reseau  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
AKAME = ["Akame ga Kill !", "Akame ga KILL!", "Red Eyes Sword"]
ZERO = ["Akame ga Kill ! : Zero", "Akame ga Kill! Zero", "Red Eyes Sword Zero"]


def lire(nom):
    return bnf.lire_notices((FIXTURES / nom).read_text(encoding="utf-8"))


class IsbnTest(unittest.TestCase):
    def test_isbn13_avec_tirets_et_isbn10_converti(self):
        self.assertEqual(bnf.isbn13("978-2-36852-245-5"), "9782368522455")
        self.assertEqual(bnf.isbn13("2-84599-668-3"), "9782845996687")          # ISBN-10 des vieux tomes
        self.assertEqual(bnf.isbn13("978-2-36852-245-4"), "")                  # somme de contrôle fausse
        self.assertEqual(bnf.isbn13(""), "")
        self.assertEqual(bnf.isbn13("12345"), "")

    def test_numero_de_tome(self):
        self.assertEqual([bnf._numero(x) for x in ("11", "Vol. 10", "T. 3", "II", "XIV")], [11, 10, 3, 2, 14])
        self.assertIsNone(bnf._numero("1-3"))                                   # un coffret
        self.assertIsNone(bnf._numero(""))


class LectureTest(unittest.TestCase):
    def test_notices_de_akame(self):
        total, notices = lire("bnf_akame.xml")
        self.assertEqual((total, len(notices)), (27, 7))
        par = {(n["sous_titre"], n["tome"]): n for n in notices}
        n11 = par[("akame ga kill !", 11)]
        self.assertEqual((n11["isbn"], n11["editeur"], n11["date"], n11["pages"]), ("9782368522455", "Kurokawa", "2016", 227))
        self.assertIn("Après avoir survécu", par[("akame ga kill !", 10)]["resume"])        # le résumé (330) est lu
        self.assertEqual(par[("Akame ga kill ! Zero", 4)]["isbn"], "9782368524510")
        self.assertIsNone(par[("Akame ga kill ! Zero", None)]["tome"] if ("Akame ga kill ! Zero", None) in par else None)

    def test_tome_en_chiffres_romains_lu(self):
        _, notices = lire("bnf_akame.xml")
        self.assertIn(("9782368522141", 2), [(n["isbn"], n["tome"]) for n in notices])             # « II » = tome 2 de Zero

    def test_resume_sans_balises_ni_codes_html(self):
        self.assertEqual(bnf._resume_propre("<p>Le combat de Takemichi&comma; opposant les deux clans&excl;&NewLine;Le chaos règne.</p>"),
                         "Le combat de Takemichi, opposant les deux clans! Le chaos règne.")
        self.assertEqual(bnf._resume_propre("  deux \xa0 espaces  "), "deux espaces")
        self.assertEqual(bnf._resume_propre("Momo comprend qu il s agit d un jeu dans l intérieur de la malle."),
                         "Momo comprend qu'il s'agit d'un jeu dans l'intérieur de la malle.")          # apostrophes perdues par la notice
        self.assertEqual(bnf._resume_propre("Cat's Eye retrouve l'ancienne piste de son père."), "Cat's Eye retrouve l'ancienne piste de son père.")

    def test_isbn10_converti_et_reimpression(self):
        _, notices = lire("bnf_air_gear.xml")
        tome1 = [n for n in notices if n["tome"] == 1]
        self.assertEqual(sorted(n["isbn"] for n in tome1), ["9782811605117", "9782845996687"])


class SerieTest(unittest.TestCase):
    def test_akame_et_zero_ne_se_melangent_pas(self):
        _, notices = lire("bnf_akame.xml")
        akame = bnf.de_la_serie(notices, AKAME)
        zero = bnf.de_la_serie(notices, ZERO)
        self.assertEqual(sorted(n["tome"] for n in akame), [1, 10, 11])
        self.assertEqual(sorted(n["tome"] for n in zero), [2, 4, 10])
        self.assertTrue(all("Zero" not in n["sous_titre"] for n in akame))

    def test_notice_de_la_serie_sans_numero_et_autre_livre_ecartes(self):
        _, notices = lire("bnf_air_gear.xml")
        gardees = bnf.de_la_serie(notices, ["Air Gear"])
        self.assertEqual(sorted(n["tome"] for n in gardees), [1, 1, 3, 22])             # ni « Air Gear unlimited » ni la collection

    def test_une_notice_par_tome_la_plus_ancienne(self):
        _, notices = lire("bnf_air_gear.xml")
        par_tome = bnf.meilleure_par_tome(bnf.de_la_serie(notices, ["Air Gear"]))
        self.assertEqual(par_tome[1]["isbn"], "9782845996687")                          # 2006, pas la réimpression de 2011
        self.assertIn("9782811605117", par_tome[1]["autres_isbn"])
        self.assertIn("Dans un monde", par_tome[1]["resume"])

    def test_edition_speciale_refusee_pour_la_serie_ordinaire(self):
        notice = {"tome": 3, "isbn": "9782723412346", "titre": "Kenshin le vagabond", "sous_titre": "Perfect edition", "partie": "",
                  "editeur": "Glénat", "date": "2013", "pages": 200, "resume": "", "edition": "", "ark": "x"}
        self.assertEqual(bnf.de_la_serie([notice], ["Kenshin le vagabond"]), [])
        self.assertEqual(len(bnf.de_la_serie([notice], ["Kenshin le vagabond"], edition="Perfect edition")), 1)

    def test_isbn_etranger_refuse(self):
        notice = {"tome": 3, "isbn": "9781421500034", "titre": "Naruto", "sous_titre": "", "partie": "", "editeur": "Viz", "date": "2005",
                  "pages": 190, "resume": "", "edition": "", "ark": "x"}
        self.assertEqual(bnf.de_la_serie([notice], ["Naruto"]), [])


class RechercheTest(unittest.TestCase):
    def test_requete(self):
        self.assertEqual(bnf.requete("Akame ga Kill ! : Zero"), 'bib.title all "akame ga kill zero" and bib.doctype any "a"')
        self.assertEqual(bnf.requete("Gantz : Perfect"), 'bib.title all "gantz" and bib.doctype any "a"')

    def test_chercher_pagine_et_s_arrete_quand_tout_est_trouve(self):
        _, notices = lire("bnf_akame.xml")
        pages = [(120, notices[:4]), (120, notices[4:]), (120, [])]
        with mock.patch.object(bnf, "interroger", side_effect=lambda cql, debut=1, reserve=0: pages.pop(0)) as q:
            trouves = bnf.chercher(AKAME, voulus={1, 10, 11})
        self.assertEqual(sorted(trouves), [1, 10, 11])
        self.assertEqual(q.call_count, 2)                                  # la 3e page n'est pas demandée : tout est trouvé

    def test_requete_de_secours_sans_le_premier_mot_quand_rien_n_est_retenu(self):
        _, notices = lire("bnf_air_gear.xml")
        demandees = []

        def faux(cql, debut=1, reserve=0):
            demandees.append(cql)
            return (50, notices) if "deeper kyo" in cql and "samourai" not in cql else (0, [])
        with mock.patch.object(bnf, "interroger", side_effect=faux):
            trouves = bnf.chercher(["Samouraï Deeper Kyo"] + [], voulus={1})
        self.assertEqual(demandees, ['bib.title all "samourai deeper kyo" and bib.doctype any "a"',
                                      'bib.title all "deeper kyo" and bib.doctype any "a"'])
        self.assertEqual(trouves, {})                                         # le secours a cherché, mais ces notices ne sont pas celles de la série

    def test_panne_avant_toute_notice_remonte(self):
        with mock.patch.object(bnf, "interroger", side_effect=reseau.Panne("BnF (catalogue)", "pas de réponse")):
            with self.assertRaises(reseau.Panne):
                bnf.chercher(AKAME)

    def test_panne_apres_des_notices_garde_ce_qu_on_a(self):
        _, notices = lire("bnf_akame.xml")
        suite = [(200, notices), reseau.Panne("BnF (catalogue)", "pas de réponse")]

        def faux(cql, debut=1, reserve=0):
            r = suite.pop(0) if suite else reseau.Panne("BnF (catalogue)", "pas de réponse")
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(bnf, "interroger", side_effect=faux):
            trouves = bnf.chercher(AKAME, voulus={1, 2, 3, 99})
        self.assertEqual(sorted(trouves), [1, 10, 11])

    def test_reponse_illisible_est_une_panne(self):
        rep = mock.Mock(statut=200, texte="<pas du xml")
        with mock.patch.object(bnf.reseau, "get", return_value=rep):
            with self.assertRaises(reseau.Panne):
                bnf.interroger("x")


if __name__ == "__main__":
    unittest.main()
