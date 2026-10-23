"""Telegram : une ligne pour des tomes ajoutés à une série existante, le compte rendu complet seulement pour une série neuve."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as A  # noqa: E402


def prov(**tomes):
    return {k.replace("t", ""): {"equipe": "X", "origine": "Torrent : " + v} for k, v in tomes.items()}


class MessageCourtTest(unittest.TestCase):
    def court(self, provenance, numeros, titre="Kaf.T05.FR"):
        with mock.patch.object(A.provenance, "lire", return_value=provenance), mock.patch("edition.lire", return_value={}):
            return A._message_court_nouveaux_tomes("Kaf", titre, numeros)

    def test_un_tome_ajoute(self):
        self.assertEqual(self.court(prov(t1="Kaf.T01.FR", t5="Kaf.T05.FR"), [1, 2, 5]), "📗 Kaf : tome 5 ajouté")

    def test_plusieurs_tomes(self):
        p = prov(t4="Kaf.T04-T06.FR", t5="Kaf.T04-T06.FR", t6="Kaf.T04-T06.FR", t1="Kaf.T01.FR")
        self.assertEqual(self.court(p, [1, 4, 5, 6], "Kaf.T04-T06.FR"), "📗 Kaf : tomes 4–6 ajoutés")

    def test_serie_neuve_rapport_complet(self):
        self.assertEqual(self.court(prov(t1="Kaf.T01-T03.FR", t2="Kaf.T01-T03.FR", t3="Kaf.T01-T03.FR"), [1, 2, 3], "Kaf.T01-T03.FR"), "")

    def test_provenance_inconnue_rapport_complet(self):
        self.assertEqual(self.court({}, [1, 2, 5]), "")


if __name__ == "__main__":
    unittest.main()
