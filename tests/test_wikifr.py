"""wikifr.py : lire la liste des volumes de Wikipédia en français (ISBN, titres de chapitres sous toutes leurs formes) et trouver la
page de la bonne série."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import reseau  # noqa: E402
import wikifr as W  # noqa: E402

PAGE = (Path(__file__).resolve().parent / "fixtures" / "wikifr_akame.txt").read_text(encoding="utf-8")


class ChapitresTest(unittest.TestCase):
    """Chaque ligne vient d'une vraie page Wikipédia : formes de numérotation rencontrées dans la bibliothèque."""
    CAS = [
        ("* '''Kill 1 -''' {{japonais|Les ténèbres|闇を斬る|Yami o Kiru}}", (1.0, "Les ténèbres")),
        ("* Battle 1 - {{japonais|''La lycéenne qui ressemble à un assassin''|殺し屋|Korosha}}", (1.0, "La lycéenne qui ressemble à un assassin")),
        ("* '''Précepte 1 -''' Quelqu'un qui a les cheveux ondulés ne peut pas être mauvais !", (1.0, "Quelqu'un qui a les cheveux ondulés ne peut pas être mauvais !")),
        ("* 9. {{japonais|Affaire craignos|危険な情事|Kiken'na jōji}}", (9.0, "Affaire craignos")),
        ("* '''{{10e}} chapitre''' {{japonais|''Un après-midi dans la vie''|根性なし|Konjō}}", (10.0, "Un après-midi dans la vie")),
        ("* 017. Field of Dreams", (17.0, "Field of Dreams")),
        ("* '''Retrace V :''' ''Clockwise Doom'' - {{japonais|Cauchemar mécanique|時計回り|Tokei}} -", (5.0, "Cauchemar mécanique")),
        ("* '''{{8e|geôle}}''' : {{japonais|Sous la pluie|雨中|}}", (8.0, "Sous la pluie")),
        ("* '''Clé n°8''' - {{japonais|''Visite à domicile''|ホウモン|Hōmon}}", (8.0, "Visite à domicile")),
        ("* {{Chap.|5}} : {{Japonais|''Un homme nommé Wise''|ワイズ|Waizu}}", (5.0, "Un homme nommé Wise")),
        ("* '''{{8e}} Down.''' {{japonais|''De sa propre main''|その手|Sono Te}}", (8.0, "De sa propre main")),
        ("* Premier épisode : {{japonais|Alice in Borderland|いまわ}}", (1.0, "Alice in Borderland")),
        ("* Cinquième épisode : {{japonais|Deuxième jour à Borderland|たいざい}}", (5.0, "Deuxième jour à Borderland")),
        ("* Z=26 Une alliance frivole", (26.0, "Une alliance frivole")),
        ("* code:24 - ''Prélude pour un commencement''", (24.0, "Prélude pour un commencement")),
        ("* '''Rave : 22''' {{Japonais|''Dancing Hero ?!''|ダンシング|Danshingu|}}", (22.0, "Dancing Hero ?!")),
        ("* {{langue|en|Episode 20 : The Prince of Oni}}", (20.0, "The Prince of Oni")),
        ("* Bleach-12.5. Fleurs de feu sous la lune froide", (12.5, "Fleurs de feu sous la lune froide")),
        ("* Ch.12 : Le départ", (12.0, "Le départ")),
        ("* Deuxième épisode : {{japonais|3{{ctrèfle}} - Première partie|くらぶのさん①}}", (2.0, "3♣ - Première partie")),
        ("* Trick:24 ", (24.0, "")),                                  # le numéro seul : utile pour ranger les chapitres
        ("* '''Chapitre 22 -''' {{japonais||ユリアン VS アルコス|Yurian VS Arkos}}", (22.0, "")),
    ]
    HORS = ["* Special Chapter", "* Dandelion.", "* ♭03. It's a Beautiful Day", "* code:extra1 - ''Mission : chocolat !''",
            "* Chapitre spécial : {{japonais||【番外編】勇者アバン|Bangaihen}}", "* Hors-série : La justice d’une femme"]

    def test_toutes_les_formes(self):
        for ligne, attendu in self.CAS:
            self.assertEqual(W.ligne_de_chapitre(ligne), attendu, ligne)

    def test_ce_qui_n_est_pas_un_chapitre_numerote_est_ignore(self):
        for ligne in self.HORS:
            self.assertIsNone(W.ligne_de_chapitre(ligne), ligne)

    def test_liste_a_chevrons_br(self):
        self.assertEqual(W.chapitres("Kapitel.1 {{japonais|La fuite|逃走|Tōsō}}<br />Kapitel.2 {{japonais|Le piège|罠|Wana}}"),
                         [(1.0, "La fuite"), (2.0, "Le piège")])

    def test_ordinaux_et_romains(self):
        self.assertEqual([W.ordinal(x) for x in ("Premier", "Cinquième", "Trente-deuxième", "Vingt et unième", "Seizième")], [1, 5, 32, 21, 16])
        self.assertIsNone(W.ordinal("Chapitre"))
        self.assertEqual([W.romain(x) for x in ("VI", "XIV", "IX")], [6, 14, 9])
        self.assertIsNone(W.romain("ABC"))


class VolumesTest(unittest.TestCase):
    def test_isbn_francais_titres_et_dates(self):
        d = W.lire_volumes(PAGE)
        self.assertEqual(sorted(d, key=int), ["1", "2"])                      # la 1re section seulement (les volumes déjà lus gagnent)
        self.assertEqual(d["1"]["isbn"], "9782368520444")                      # « 978-2-368-52044-4 » (français, pas l'ISBN japonais)
        self.assertEqual(d["1"]["sortie"], "11 septembre 2014")
        self.assertEqual(d["1"]["chapitres"][0], "1. Les ténèbres")
        self.assertEqual(d["1"]["numeros"], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(d["1"]["couverture"], "Akame")

    def test_section_de_chaque_serie_de_la_page(self):
        principale = W.lire_volumes(W.section_de_serie(PAGE, "Akame ga Kill !"))
        zero = W.lire_volumes(W.section_de_serie(PAGE, "Akame ga Kill ! : Zero"))
        self.assertEqual(principale["1"]["chapitres"][0], "1. Les ténèbres")
        self.assertNotEqual(zero["1"]["isbn"], principale["1"]["isbn"])
        self.assertEqual(zero["1"]["isbn"][:7], "9782368")

    def test_section_stricte(self):
        self.assertIsNotNone(W.section_stricte(PAGE, "Akame ga Kill ! : Zero"))
        self.assertIsNone(W.section_stricte(PAGE, "Naruto"))                    # aucune section de ce nom : c'est la page d'une autre série
        self.assertIsNone(W.section_stricte("{{TomeBD/Entête}}{{TomeBD| volume = 1}}", "Akame ga Kill !"))   # une seule liste

    def test_date_pas_encore_connue_n_est_pas_une_date(self):
        page = "{{TomeBD/Entête\n| langue_2 = Français\n}}\n{{TomeBD\n| volume = 61\n| sortie_2 = _\n| chapitre = * Chapitre 578 - Un titre\n}}"
        self.assertNotIn("sortie", W.lire_volumes(page)["61"])

    def test_isbn_faux_ou_absent(self):
        self.assertEqual(W.isbn("978-2-368-52044-9"), "")
        self.assertEqual(W.isbn(""), "")
        self.assertEqual(W.isbn("4-08-873623-0 <ref>x</ref>"), "9784088736235")


class PagesTest(unittest.TestCase):
    def test_titre_nu(self):
        self.assertEqual(W.titre_nu("Liste des chapitres de Naruto (1re partie)"), "Naruto")
        self.assertEqual(W.titre_nu("Liste des chapitres d'Air Gear"), "Air Gear")
        self.assertEqual(W.titre_nu("Arago (manga)"), "Arago")

    def test_page_de_la_serie(self):
        self.assertTrue(W.page_de_la_serie("Golden Kamui", ["Golden Kamuy"]))
        self.assertTrue(W.page_de_la_serie("Liste des chapitres de Seven Deadly Sins", ["Nanatsu no Taizai", "The Seven Deadly Sins"]))
        self.assertFalse(W.page_de_la_serie("Wind Breaker (manga)", ["The Breaker"]))
        self.assertFalse(W.page_de_la_serie("Red Eyes Sword: Akame ga Kill!", ["Akame ga Kill ! : Zero", "Akame ga Kill! Zero"]))

    def test_trouver_pages_recherche_puis_filtre(self):
        reponses = {"Golden Kamuy manga": ["Golden Kamui", "Golden Kamui (film)", "Grand prix du manga"]}
        with mock.patch.object(W, "rechercher", side_effect=lambda q, limite=5: reponses.get(q, [])):
            self.assertEqual(W.trouver_pages(["Golden Kamuy"]), ["Golden Kamui"])

    def test_l_article_passe_avant_les_listes_et_les_listes_ne_sont_pas_l_article(self):
        reponses = {"Gintama manga": ["Liste des chapitres de Gintama", "Gintama"], 'intitle:"Liste des chapitres" Gintama': ["Liste des chapitres de Gintama"]}
        with mock.patch.object(W, "rechercher", side_effect=lambda q, limite=5: reponses.get(q, [])):
            self.assertEqual(W.trouver_pages(["Gintama"]), ["Gintama"])
            self.assertEqual(W.trouver_pages(["Gintama"], liste=True), ["Liste des chapitres de Gintama"])

    def test_meres_cherchees_apres(self):
        reponses = {"Akame ga Kill ! manga": ["Red Eyes Sword: Akame ga Kill!"]}
        with mock.patch.object(W, "rechercher", side_effect=lambda q, limite=5: reponses.get(q, [])):
            self.assertEqual(W.trouver_pages(["Akame ga Kill ! : Zero"], meres=["Akame ga Kill !"]), ["Red Eyes Sword: Akame ga Kill!"])

    def test_panne_de_wikipedia_remonte(self):
        with mock.patch.object(W, "requete", side_effect=reseau.Panne("Wikipédia", "trop de demandes")):
            with self.assertRaises(reseau.Panne):
                W.trouver_pages(["Naruto"])


if __name__ == "__main__":
    unittest.main()
