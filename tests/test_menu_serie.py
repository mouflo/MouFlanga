"""Le menu d'une série : « ⋯ » court, tout le reste rangé par onglets dans « 🛠 Gérer la série » (aucune action perdue)."""
import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
HTML = (RACINE / "templates" / "index.html").read_text(encoding="utf-8")
JS = (RACINE / "ui" / "mouflanga.js").read_text(encoding="utf-8")

# les 24 entrées de l'ancien menu « ⋯ » : aucune ne doit disparaître
ANCIENNES = ("sAllRead", "sAllUnread", "sTomes", "sTitres", "sUnivers", "sCouvertures", "sRenommer", "sIdentifier", "sChoisirFiche",
             "sRattacher", "sDecouper", "sAlleger", "sParasites", "sSurveiller", "sSource", "sVolumes", "sConvertir", "sNfoImport",
             "sIsbnLire", "sProvenance", "sInfosTous", "sGenerique", "sGeneriqueListe", "sDelete")


def bloc(identifiant):
    """Le texte HTML de l'élément `identifiant` (jusqu'à la balise fermante de même niveau, repérée par son indentation)."""
    debut = HTML.index(f'id="{identifiant}"')
    debut = HTML.rfind("\n", 0, debut) + 1
    indent = len(HTML[debut:]) - len(HTML[debut:].lstrip(" "))
    fin = HTML.index("\n" + " " * indent + "</div>", debut)
    return HTML[debut:fin]


class MenuSerieTest(unittest.TestCase):
    def test_aucune_action_perdue(self):
        for i in ANCIENNES:
            self.assertEqual(HTML.count(f'id="{i}"'), 1, i)
            self.assertIn(f"$('{i}')", JS, f"{i} n'a plus de code")

    def test_menu_court(self):
        menu = bloc("menuMore")
        entrees = re.findall(r'<(?:button|a)\b[^>]*\bid="(\w+)"', menu)
        self.assertLessEqual(len(entrees), 7, entrees)
        self.assertIn("sGerer", entrees)
        for gardee in ("sAllRead", "sAllUnread", "sSurveiller", "sDelete"):
            self.assertIn(gardee, entrees)

    def test_les_autres_actions_sont_dans_gerer(self):
        gerer = bloc("gererVue")
        dans_menu = set(re.findall(r'<(?:button|a)\b[^>]*\bid="(\w+)"', bloc("menuMore")))
        for i in ANCIENNES:
            if i not in dans_menu:
                self.assertIn(f'id="{i}"', gerer, f"{i} n'est ni dans le menu ni dans « Gérer »")

    def test_onglets_et_panneaux(self):
        onglets = re.findall(r'data-gerer="(\w+)"', HTML)
        panneaux = re.findall(r'data-gerer-panneau="(\w+)"', HTML)
        self.assertEqual(onglets, ["etat", "identite", "tomes", "images"])
        self.assertEqual(sorted(onglets), sorted(panneaux))

    def test_chaque_action_est_dans_le_bon_onglet(self):
        def panneau(nom):
            debut = HTML.index(f'data-gerer-panneau="{nom}"')
            fin = HTML.find('data-gerer-panneau="', debut + 10)
            return HTML[debut:fin if fin > 0 else len(HTML)]
        identite, tomes, images = panneau("identite"), panneau("tomes"), panneau("images")
        for i in ("sRenommer", "sIdentifier", "sChoisirFiche", "sVolumes", "sRattacher", "sSource", "sProvenance", "sNfoImport"):
            self.assertIn(f'id="{i}"', identite, i)
        for i in ("sTomes", "sDecouper", "sConvertir", "sTitres", "sIsbnLire", "sInfosTous"):
            self.assertIn(f'id="{i}"', tomes, i)
        for i in ("sAlleger", "sParasites", "sCouvertures"):
            self.assertIn(f'id="{i}"', images, i)
        # l'amélioration des images et l'identification ne se mélangent pas
        for i in ("sAlleger", "sParasites"):
            self.assertNotIn(f'id="{i}"', identite)

    def test_les_pages_parasites_sont_un_onglet_du_module_image(self):
        self.assertIn("['parasites', '🧹 Parasites']", JS)
        self.assertIn('data-panneau="parasites"', JS)

    def test_le_retour_du_telephone_ferme_la_fenetre(self):
        self.assertGreaterEqual(JS.count("'gererVue', 'infosVue', 'affVue'"), 2)

    def test_lecteur_ne_voit_pas_l_etat(self):
        css = (RACINE / "ui" / "mouflanga.css").read_text(encoding="utf-8")
        self.assertIn("body.lecteur .trt-ligne", css)
        self.assertIn('class="trt-ligne admin-seul"', HTML)
        self.assertIn('id="sGerer" class="admin-seul"', HTML)


if __name__ == "__main__":
    unittest.main()
