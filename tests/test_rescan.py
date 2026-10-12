"""🔄 Rescan du dossier des torrents et identification des noms de séries (cas vus le 12/10/2026)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class IdentificationTest(unittest.TestCase):
    def setUp(self):
        import app as m
        self.m = m
        self.anilist = m._titre_anilist
        self.choix = m.CHOIX

    def tearDown(self):
        self.m._titre_anilist = self.anilist
        self.m.CHOIX = self.choix

    def test_notag_nest_pas_une_suite(self):
        self.m._titre_anilist = lambda t: ""
        nom = self.m._nom_depuis_archive("20th Century boys [Intégrale] [Digital 1920] [CBZ] NOTAG.zip", ["20th Century Boys"])
        self.assertEqual(nom, "20th Century Boys")

    def test_auteur_a_la_fin(self):
        self.m._titre_anilist = lambda t: "Jujutsu Kaisen" if t == "Jujutsu Kaisen" else ""
        nom = self.m._nom_depuis_archive("Jujutsu.Kaisen.Gege.Akutami.[INTEGRALE].FR.[CBZ]-NOTAG.zip", [])
        self.assertEqual(nom, "Jujutsu Kaisen")

    def test_titre_non_latin_refuse(self):
        self.assertFalse(self.m._latin("คำอธิษฐานในวันที่จากลา Frieren"))
        self.assertTrue(self.m._latin("Sōsō no Frieren"))

    def test_un_seul_choix_nefface_pas_un_mot_du_titre(self):
        f = Path(tempfile.mkdtemp()) / "choix.json"
        f.write_text(json.dumps([{"dossier": "cavalier of the abyss - prologue -IMMORTAL REGIS", "propose": "cavalier of the abyss - prologue -IMMORTAL REGIS",
                                  "choisi": "cavalier of the abyss", "date": "2026-10-08"}]))
        self.m.CHOIX = f
        self.assertEqual(self.m._appris("autre", "Chaos Chronicle Immortal Regis"), "Chaos Chronicle Immortal Regis")

    def test_elements_du_dossier_des_torrents(self):
        m = self.m
        racine = Path(tempfile.mkdtemp())
        (racine / "Bakuman T01-T02").mkdir()
        (racine / "Bakuman T01-T02" / "Bakuman.T01.cbz").write_bytes(b"x")
        (racine / "@eaDir").mkdir()
        (racine / "main.py").write_text("print(1)")
        (racine / "Vide").mkdir()
        sauve = m.torrents.reglages
        m.torrents.reglages = lambda: {"nok": str(racine)}
        orig_scan, anil = m._scan, m._titre_anilist
        m._scan = lambda: {}
        m._titre_anilist = lambda t: ""
        try:
            dossier, elements = m._elements_torrents()
        finally:
            m.torrents.reglages, m._scan, m._titre_anilist = sauve, orig_scan, anil
        self.assertEqual(dossier, str(racine))
        self.assertEqual([e["nom"] for e in elements], ["Bakuman T01-T02"])
        self.assertEqual(elements[0]["fichiers"], 1)


if __name__ == "__main__":
    unittest.main()
