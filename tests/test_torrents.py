"""🧲 Torrents : badges, chemins, copie par lien physique, suivi jusqu'à l'import (qBittorrent simulé)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import torrents  # noqa: E402


class FauxQbit:
    def __init__(self, infos): self.infos, self.appels = infos, []
    def info(self, **p): return self.infos
    def appel(self, chemin, **data): self.appels.append((chemin, data))


class TorrentsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.t = Path(self.tmp.name)
        torrents._ETAT["fichier"] = self.t / "torrents.json"
        torrents._ETAT["rapport"] = None            # pas de compte rendu complet (il interroge Internet)
        self._env = dict(os.environ)
        os.environ.update(TORRENTS_OK="/ok", TORRENTS_CHEMINS="")

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env); self.tmp.cleanup()

    def test_mot_de_passe_avec_caracteres_speciaux(self):
        import base64
        os.environ["QBIT_PASSWORD_B64"] = base64.b64encode('a"b$c`d\\e'.encode()).decode()
        self.assertEqual(torrents.reglages()["qbit_mdp"], 'a"b$c`d\\e')

    def test_adoption_d_un_torrent_ajoute_a_la_main(self):
        class Q(FauxQbit):
            def info(self, **p): return [{"hash": "h9", "name": "Bakuman.20.Tomes.FR.CBZ", "progress": 0.4, "tags": ""},
                                         {"hash": "h8", "name": "Deja suivi", "tags": "mouflanga, mf-abc"}]
        torrents._ETAT["nom_serie"] = lambda n: "Bakuman"
        q = Q([]); torrents.adopter(q)
        j = torrents._lire()
        self.assertEqual([(x["serie"], x["progression"]) for x in j], [("Bakuman", 40)])
        self.assertEqual(q.appels[0][0], "torrents/addTags")
        torrents.adopter(Q([]))                         # pas de double reprise (l'étiquette est posée côté qBittorrent)
        torrents._ETAT["nom_serie"] = None

    def test_badges_et_chemins(self):
        b = torrents.badges("Air Gear T01-T37 Integrale FRENCH CBZ Digital")
        self.assertEqual(b, ["🇫🇷 FR", "Digital", "Intégrale", "T1–37"])
        os.environ["TORRENTS_CHEMINS"] = "/downloads=>/mnt/nas/Downloads"
        self.assertEqual(torrents.chemin_local("/downloads/Mouflanga.NOK/x"), Path("/mnt/nas/Downloads/Mouflanga.NOK/x"))

    def test_suivi_jusqu_a_l_import(self):
        nok = self.t / "NOK" / "Air Gear [FR]"; (nok / "sub").mkdir(parents=True)
        (nok / "sub" / "Air Gear T01.cbz").write_bytes(b"x"); (nok / "lisezmoi.exe").write_bytes(b"x")
        torrents._ecrire([{"id": "abc", "titre": "Air Gear FR", "serie": "Air Gear", "etat": "telechargement"}])
        biblio, importes, messages = self.t / "mangas", [], []
        q = FauxQbit([{"progress": 0.5, "state": "downloading"}])
        torrents.traiter(q, torrents._lire(), None, messages.append, biblio)
        self.assertEqual(torrents._lire()[0]["progression"], 50)
        q = FauxQbit([{"progress": 1, "hash": "h1", "content_path": str(nok), "state": "uploading"}])
        torrents.traiter(q, torrents._lire(), lambda s, src, r=False: importes.append((s, src)) or "1 tome", messages.append, biblio)
        self.assertEqual(importes[0], ("Air Gear", nok))
        self.assertEqual([f.name for f in torrents.fichiers_du_torrent(nok)], ["Air Gear T01.cbz"])
        torrents.lier(nok / "sub" / "Air Gear T01.cbz", biblio / "x" / "T01.cbz")
        self.assertEqual(os.stat(biblio / "x" / "T01.cbz").st_ino, os.stat(nok / "sub" / "Air Gear T01.cbz").st_ino)   # lien physique
        self.assertEqual(q.appels, [("torrents/setLocation", {"hashes": "h1", "location": "/ok"})])
        self.assertEqual(torrents._lire()[0]["etat"], "fini"); self.assertIn("importé", messages[0])



class SuiviTest(unittest.TestCase):
    def test_tomes_et_propositions(self):
        import suivi
        self.assertEqual(suivi.tomes_du_titre("Frieren.[T01.T14].FR.[CBZ]"), set(range(1, 15)))
        self.assertEqual(suivi.tomes_du_titre("Dandadan Tome 19 FR"), {19})
        self.assertEqual(suivi.tomes_du_titre("Air Gear Tomes 1 à 37 FRENCH"), set(range(1, 38)))
        res = [{"titre": "Dandadan T19 FR Digital", "badges": ["🇫🇷 FR", "Digital"]},
               {"titre": "Dandadan T01-T18 FR Digital", "badges": ["🇫🇷 FR", "Digital", "T1–18"]},
               {"titre": "Dandadan T01-T18 VO", "badges": []}]
        p = suivi.propositions_pour("Dandadan", {"tomes": set(range(1, 19)), "source": "Web (chapitres)", "qualite": "Digital"}, res, [])
        self.assertEqual([(x["type"], x["tomes"]) for x in p], [("nouveau", [19]), ("meilleur", [])])
        self.assertEqual(suivi.propositions_pour("Dandadan", {"tomes": set(range(1, 19)), "source": "Digital", "qualite": "Digital"},
                                                 res, ["Dandadan T19 FR Digital"]), [])


if __name__ == "__main__":
    unittest.main()
