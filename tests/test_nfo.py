import tempfile
import unittest
from pathlib import Path

import edition

NFO = """
        Kenichi - Le disciple ultime [Intégrale 61 tomes] [CBZ FR]
Titre Original : Shijou Saikyou no Deshi Kenichi
Titre Français : Kenichi - Le disciple ultime
Auteur         : Syun Matsuena
Éditeur        : Kurokawa

Tome 01 -- ISBN : 978-2351422700
Tome 02 -- ISBN : 978-2351422717
Tome 03 -- ISBN : 978-2351423049

-------------------------------------------------------------------------------
                                   Synopsis
-------------------------------------------------------------------------------
Kenyu Shiramah est un lycéen de 15 ans, plutôt froussard, qui passe
son temps à se faire martyriser par ses camarades.

-------------------------------------------------------------------------------
                            Notes de Release
-------------------------------------------------------------------------------
"""


class NfoTest(unittest.TestCase):
    def test_titres_auteur_synopsis_et_isbn(self):
        r = edition.analyser_nfo(NFO)
        self.assertEqual(r["titre_fr"], "Kenichi - Le disciple ultime")
        self.assertEqual(r["auteur"], "Syun Matsuena")
        self.assertTrue(r["synopsis"].startswith("Kenyu Shiramah"))
        self.assertEqual(r["isbn"], {"1": "9782351422700", "2": "9782351422717"})     # le tome 3 a une somme de contrôle fausse : refusé

    def test_un_isbn_deja_note_n_est_jamais_remplace(self):
        with tempfile.TemporaryDirectory() as t:
            edition.ecrire(Path(t), {"isbn": {"1": "9782505012740"}})
            edition.noter_nfo(Path(t), NFO)
            d = edition.lire(Path(t))
            self.assertEqual(d["isbn"], {"1": "9782505012740", "2": "9782351422717"})
            self.assertEqual(d["nfo_infos"]["auteur"], "Syun Matsuena")

    def test_texte_sans_infos(self):
        self.assertEqual(edition.analyser_nfo("rien d'utile ici"), {})


if __name__ == "__main__":
    unittest.main()
