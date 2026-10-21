import unittest

import tomes

PAGE = """== Manga ==
==== ''Red Eyes Sword: Akame ga Kill!'' ====
{{TomeBD/Entête | langue_1 = Japonais | langue_2 = Français }}
{{TomeBD | volume = 1 | chapitre = * Kill 1 - Les ténèbres }}
==== ''Red Eyes Sword: Akame ga Kill! Zero'' ====
{{TomeBD/Entête | langue_1 = Japonais | langue_2 = Français }}
{{TomeBD | volume = 1 | chapitre = * Kill 1 - Les deux petites filles }}
== Anime ==
texte
"""


class SectionDeSerie(unittest.TestCase):
    def test_chaque_serie_prend_sa_section(self):
        principale = tomes._section_de_serie(PAGE, "Akame ga Kill !")
        zero = tomes._section_de_serie(PAGE, "Akame ga Kill ! : Zero")
        self.assertIn("Les ténèbres", principale)
        self.assertNotIn("petites filles", principale)
        self.assertIn("petites filles", zero)
        self.assertNotIn("Anime", zero)

    def test_page_a_une_seule_liste_inchangee(self):
        seule = "{{TomeBD/Entête}}\n{{TomeBD | volume = 1}}"
        self.assertEqual(tomes._section_de_serie(seule, "Naruto"), seule)
