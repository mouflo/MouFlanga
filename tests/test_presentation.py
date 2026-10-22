"""Présentation d'un torrent (page du tracker, NFO) : du HTML / BBCode / texte vers ce qu'elle dit. Cas réels de C411, TR4KER, The Old School."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import presentation  # noqa: E402

NFO_C411 = """╔══════════════════════════════════════════════════════════════════╗
║  Wind Breaker T07                                                ║
╚══════════════════════════════════════════════════════════════════╝

 INFORMATIONS
─────────────────────────────────────────────────────────────────────
   Titre...............: Wind Breaker T07
   Auteur..............: Nii Satoru
   Éditeur (FR)........: Pika
   Nombre de pages.....: 191
   Résolution..........: 1499x2250 px
   ISBN................: 9782811686901

 DESCRIPTION
─────────────────────────────────────────────────────────────────────
   Afin de venir en aide à un camarade de classe, Sakura et les élèves de Seconde ont décidé de se battre contre les Keel.

 CONTENU
─────────────────────────────────────────────────────────────────────
   1 fichier CBZ — 191 pages

 SOURCE
─────────────────────────────────────────────────────────────────────
   * Source : Epub webrip
"""

BBCODE_TR4KER = """[center][b][color=#e74c3c][size=3]Dogsred - Tome 04[/size][/color][/b]

[img]https://i.imgur.com/zNnPX3V.png[/img]

[b][color=#e74c3c]Auteur(s) :[/color][/b] [i]Noda Satoru[/i]
[b][color=#e74c3c]Genres :[/color][/b] Sports, Action, Drama
[b][color=#e74c3c]Année :[/color][/b] [i]2025[/i]

[size=3]Après une journée cauchemardesque entre exercices d'endurance, déshydratation et attaque d'ours, seules neuf des 17 nouvelles recrues de l'équipe de hockey d'Oinokami sont prêtes à rempiler... Qu'à cela ne tienne, Rou, lui, est gonflé à bloc ![/size]

[b][color=#e74c3c]Format :[/color][/b] [i]CBZ[/i]
[b][color=#e74c3c]Qualité :[/color][/b] [i]Scan[/i][/center]"""

HTML_TR4KER = ("<p><b>Auteur(s)</b> : Takeru Hokazono<br /><b>Date Sortie</b> : 2023<br /><br /><b>Résumé</b> :<br />Dans un monde où l'art de la "
               "forge d'armes magiques est essentiel, Chihiro Rokuhira, un forgeron de lames enchantées, part en quête de vengeance après la "
               "perte tragique de sa famille.<br />Son objectif : traquer ceux qui ont tué son père.<br /><br /><b><font color=\"#9900ff\">"
               "Tome 01 (Scan)</font></b><br /><b>Format</b> : CBZ<br /><b>Dimensions</b> : 1313x1920px<br /></p>")

TEXTE_TOS = ("Date de sortie: 21 Octobre 2015\r\nISBN: 9782820321992\r\n\r\nRésumé:\r\nExiste-t-il être plus effrayant et caractériel que le "
             "Diable Suprême himself ? Sa mère !! Oga &amp; Cie vivent de dernières aventures où il est question d'île déserte, d'héroïsme, "
             "d'amour et de retour vers le futur !!!")


class EnTexteTest(unittest.TestCase):
    def test_bbcode_sans_balises_mais_avec_les_crochets_des_noms_de_fichiers(self):
        t = presentation.en_texte("[b]Liste[/b]\n[img]http://x/y.png[/img]\nWind Breaker T01 (2023) [Digital-1500] [Manga FR].cbz", "bbcode")
        self.assertNotIn("[b]", t)
        self.assertNotIn("y.png", t)
        self.assertIn("[Digital-1500]", t)

    def test_un_script_n_est_jamais_gardé(self):
        t = presentation.en_texte("<p>Bonjour</p><script>alert(1)</script><style>p{}</style>", "html")
        self.assertEqual(t, "Bonjour")

    def test_texte_echappe(self):
        self.assertEqual(presentation.en_texte("Oga &amp; Cie", ""), "Oga & Cie")


class AnalyserTest(unittest.TestCase):
    def test_nfo_c411(self):
        a = presentation.analyser(presentation.en_texte(NFO_C411, "texte"))
        self.assertEqual((a["auteur"], a["editeur"], a["pages"], a["resolution"]), ("Nii Satoru", "Pika", 191, "1499x2250"))
        self.assertEqual(a["isbn_unique"], "9782811686901")
        self.assertEqual(a["qualite"], "Digital")
        self.assertTrue(a["synopsis"].startswith("Afin de venir en aide"))
        self.assertNotIn("CONTENU", a["synopsis"])

    def test_bbcode_tr4ker(self):
        a = presentation.analyser(presentation.en_texte(BBCODE_TR4KER, "bbcode"))
        self.assertEqual((a["auteur"], a["genre"], a["date"], a["qualite"], a["format"]), ("Noda Satoru", "Sports, Action, Drama", "2025", "Scan", "CBZ"))
        self.assertTrue(a["synopsis"].startswith("Après une journée"))

    def test_html_tr4ker_le_resume_s_arrete_au_bloc_du_tome(self):
        a = presentation.analyser(presentation.en_texte(HTML_TR4KER, "html"))
        self.assertTrue(a["synopsis"].endswith("tué son père."))
        self.assertNotIn("Tome 01", a["synopsis"])
        self.assertEqual((a["auteur"], a["resolution"]), ("Takeru Hokazono", "1313x1920"))

    def test_texte_the_old_school(self):
        a = presentation.analyser(presentation.en_texte(TEXTE_TOS, ""))
        self.assertEqual((a["date"], a["isbn_unique"]), ("21 Octobre 2015", "9782820321992"))
        self.assertIn("Oga & Cie", a["synopsis"])

    def test_isbn_par_tome_et_somme_de_controle(self):
        a = presentation.analyser("Tome 01 -- ISBN : 978-2351422700\nTome 03 -- ISBN : 978-2351423049\nISBN : 9782811686902")
        self.assertEqual(a["isbn"], {"1": "9782351422700"})                  # le tome 3 et l'ISBN seul ont une somme fausse
        self.assertNotIn("isbn_unique", a)

    def test_resume_anglais_signale(self):
        a = presentation.analyser("Synopsis\n-----\nThe story follows a young boy who is looking for his lost brother and the world that is "
                                  "against him in every way.\n")
        self.assertEqual(a["synopsis_langue"], "en")

    def test_manga_n_est_pas_un_genre(self):
        self.assertNotIn("genre", presentation.analyser("Genre : Manga\nAuteur : Nii Satoru"))
        self.assertEqual(presentation.analyser("Genre : Action, Comédie")["genre"], "Action, Comédie")

    def test_rien_d_utile(self):
        self.assertEqual(presentation.analyser("rien d'utile ici"), {})


if __name__ == "__main__":
    unittest.main()
