"""Doublons rangés à la main : « Ne rien faire » ferme la demande, et une paire disparue ou refusée ne revient plus."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class DoublonsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root = t / "mangas"
        for chemin in ("Serie/Tome 07/Serie - Tome 07.cbz", "Serie/Tome 07/Serie-copie - Tome 07.cbz"):
            (self._fichier(chemin)).write_bytes(b"x" * 10)
        os.environ["MANGA_DIR"] = str(self.root)
        sys.modules.pop("app", None)
        import app as A
        self.A = A
        A.MANGA_DIR = self.root
        A.DOUBLONS_IGNORES = t / "ignores.json"
        A.REGLES_IMPORT = t / "regles-import.json"
        A.torrents._ETAT["fichier"] = t / "torrents.json"
        self.envois = []
        import notifier
        self.patch = mock.patch.object(notifier, "envoyer", side_effect=lambda txt, *a, **k: self.envois.append(txt))
        self.patch.start()

    def _fichier(self, chemin):
        f = self.root / chemin
        f.parent.mkdir(parents=True, exist_ok=True)
        return f

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def paire(self):
        return [(self.root / "Serie/Tome 07/Serie-copie - Tome 07.cbz", self.root / "Serie/Tome 07/Serie - Tome 07.cbz", 7)]

    def taches(self):
        return [j for j in self.A.torrents._lire() if j.get("manuel")]


class DoublonsTest(DoublonsBase):
    def test_choix_retenu_applique_tout_seul(self):
        """« Toujours faire ce choix » (ici : ne rien faire) : la fois suivante, plus de question ni de tâche en attente."""
        self.A._write_json(self.A.REGLES_IMPORT, {"Serie": {"choix": "ignorer", "date": "x"}})
        self.A._signaler_doublons("Serie", self.paire())
        self.assertEqual([j["etat"] for j in self.taches()], ["fini"])
        self.assertIn("appliqué tout seul", self.envois[0])

    def test_regle_torrent(self):
        self.A._write_json(self.A.REGLES_IMPORT, {"Serie": {"choix": "remplacer"}})
        self.assertEqual(self.A._regle_import("Serie"), "remplacer")
        self.assertIsNone(self.A._regle_import("Autre"))

    def test_signale_une_fois(self):
        self.A._signaler_doublons("Serie", self.paire())
        self.A._signaler_doublons("Serie", self.paire())
        self.assertEqual(len(self.taches()), 1)
        self.assertEqual(len(self.envois), 1)

    def test_ne_rien_faire_ferme_et_ne_revient_plus(self):
        self.A._signaler_doublons("Serie", self.paire())
        j = self.taches()[0]
        import auth
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        client = self.A.app.test_client()
        with client.session_transaction() as sess:
            sess["u"], sess["f"] = "test", auth._fingerprint()
        with mock.patch.object(self.A.auth, "role", return_value="admin"):
            rep = client.post("/api/torrents/decider", json={"id": j["id"], "remplacer": "ignorer"})
        self.assertTrue(rep.get_json()["ok"], rep.get_json())
        self.assertEqual(self.taches()[0]["etat"], "fini")
        self.A._signaler_doublons("Serie", self.paire())
        self.assertEqual(len(self.envois), 1)                 # pas de nouvelle notification
        self.assertEqual([x for x in self.taches() if x["etat"] == "a_valider"], [])

    def test_paire_disparue_ignoree(self):
        (self.root / "Serie/Tome 07/Serie-copie - Tome 07.cbz").unlink()
        self.A._signaler_doublons("Serie", self.paire())
        self.assertEqual(self.taches(), [])
        self.assertEqual(self.envois, [])


if __name__ == "__main__":
    unittest.main()


class ChoixSurUnTorrentLanceDepuisLAppliTest(DoublonsBase):
    """Un torrent lancé depuis l'appli (« manuel » = jamais retiré pour lenteur) qui tombe sur des tomes déjà là attend un choix.
    Remplacer / ajouter les manquants doit reprendre son import, pas le prendre pour un « rangement à la main » (qui a des
    fichiers à retrouver, « paires ») : avant, « Fichiers introuvables : relance le rangement » (Rave, 13/11)."""

    def torrent(self, **kw):
        j = {"id": "tor1", "titre": "Serie.Tome.09.FR.[CBZ]-NRC", "serie": "Serie", "remplacer": None, "etat": "a_valider",
             "progression": 100, "debut": "2026-11-13 00:44", "manuel": True, "message": "Tomes déjà présents : 09. À toi de choisir.", **kw}
        self.A.torrents._ecrire([j])
        return j

    def etat(self, jid="tor1"):
        return next(x for x in self.A.torrents._lire() if x["id"] == jid)

    def test_remplacer_reprend_le_telechargement(self):
        self.torrent()
        r, code = self.A._appliquer_choix("tor1", True)
        self.assertEqual(code, 200, r)
        self.assertEqual((self.etat()["etat"], self.etat()["remplacer"]), ("telechargement", True))

    def test_ajouter_les_manquants_reprend_le_telechargement(self):
        self.torrent()
        r, code = self.A._appliquer_choix("tor1", False)
        self.assertEqual(code, 200, r)
        self.assertEqual((self.etat()["etat"], self.etat()["remplacer"]), ("telechargement", False))

    def test_ne_rien_faire_ferme_la_tache(self):
        self.torrent()
        r, code = self.A._appliquer_choix("tor1", "ignorer")
        self.assertEqual(code, 200, r)
        self.assertEqual(self.etat()["etat"], "fini")

    def test_un_rangement_a_la_main_signale_ne_fait_pas_disparaitre_un_torrent_en_attente(self):
        self.torrent()
        self.A._signaler_doublons("Serie", self.paire())
        self.assertEqual(self.etat()["etat"], "a_valider")          # le torrent est toujours là
        self.assertEqual(len([j for j in self.A.torrents._lire() if j.get("paires")]), 1)

    def test_la_regle_retenue_ne_s_applique_pas_au_torrent_a_la_place_du_rangement(self):
        self.torrent()
        self.A._write_json(self.A.REGLES_IMPORT, {"Serie": {"choix": "ignorer"}})
        self.A._signaler_doublons("Serie", self.paire())
        self.assertEqual(self.etat()["etat"], "a_valider")          # seule la tâche de rangement a été close
        self.assertEqual([j["etat"] for j in self.A.torrents._lire() if j.get("paires")], ["fini"])

    def test_un_rangement_a_la_main_dont_les_fichiers_ont_disparu_reste_une_erreur(self):
        self.A.torrents._ecrire([{"id": "r1", "titre": "Rangé à la main", "serie": "Serie", "remplacer": None, "etat": "a_valider",
                                  "manuel": True, "paires": [["Serie/absent.cbz", "Serie/cible.cbz", 7]], "progression": 100,
                                  "debut": "2026-11-13 00:44", "message": "x"}])
        r, code = self.A._appliquer_choix("r1", True)
        self.assertEqual(code, 409)
        self.assertEqual(self.etat("r1")["etat"], "erreur")

    def test_les_torrents_mis_en_erreur_par_ce_defaut_reviennent_en_attente(self):
        """Réparation faite par le code : un torrent encore dans qBittorrent, mis en « erreur » à tort, retrouve son choix."""
        self.torrent(etat="erreur", message="Fichiers introuvables (dossier renommé ou supprimé) : relance le rangement.")
        self.assertEqual(self.A.torrents.reprendre_choix_perdus(), 1)
        j = self.etat()
        self.assertEqual(j["etat"], "a_valider")
        self.assertIn("À toi de choisir", j["message"])
        self.assertEqual(self.A.torrents.reprendre_choix_perdus(), 0)         # une seule fois

    def test_la_regle_retenue_regle_aussi_les_demandes_deja_en_attente(self):
        """« Toujours faire ce choix » : les autres torrents de la série qui attendaient déjà ne restent pas à valider un par un."""
        def tor(i, serie="Serie", **kw):
            return {"id": i, "titre": f"{serie}.T{i}", "serie": serie, "remplacer": None, "etat": "a_valider", "progression": 100,
                    "debut": "2026-11-13 00:44", "manuel": True, "message": "Tomes déjà présents. À toi de choisir.", **kw}
        self.A.torrents._ecrire([tor("a"), tor("b"), tor("c", serie="Autre"), tor("d", etat="fini")])
        self.A._write_json(self.A.REGLES_IMPORT, {"Serie": {"choix": "remplacer"}})
        self.assertEqual(self.A._appliquer_regles_en_attente(), 2)
        etats = {j["id"]: (j["etat"], j["remplacer"]) for j in self.A.torrents._lire()}
        self.assertEqual(etats, {"a": ("telechargement", True), "b": ("telechargement", True),
                                 "c": ("a_valider", None), "d": ("fini", None)})            # une autre série n'est pas touchée
        self.assertEqual(self.A._appliquer_regles_en_attente(), 0)                           # rien de plus à régler

    def test_la_regle_manquants_et_ne_rien_faire(self):
        self.A.torrents._ecrire([{"id": "a", "titre": "S.T1", "serie": "Serie", "remplacer": None, "etat": "a_valider", "manuel": True,
                                  "debut": "2026-11-13 00:44", "message": "x"}])
        self.A._write_json(self.A.REGLES_IMPORT, {"Serie": {"choix": "manquants"}})
        self.A._appliquer_regles_en_attente()
        self.assertEqual(self.etat("a")["remplacer"], False)
        self.A.torrents._ecrire([{"id": "b", "titre": "S.T2", "serie": "Serie", "remplacer": None, "etat": "a_valider", "manuel": True,
                                  "debut": "2026-11-13 00:44", "message": "x"}])
        self.A._write_json(self.A.REGLES_IMPORT, {"Serie": {"choix": "ignorer"}})
        self.A._appliquer_regles_en_attente()
        self.assertEqual(self.etat("b")["etat"], "fini")

    def test_cocher_toujours_dans_la_page_regle_les_autres_demandes(self):
        import auth
        def tor(i):
            return {"id": i, "titre": f"Serie.T{i}", "serie": "Serie", "remplacer": None, "etat": "a_valider", "progression": 100,
                    "debut": "2026-11-13 00:44", "manuel": True, "message": "x"}
        self.A.torrents._ecrire([tor("a"), tor("b"), tor("c")])
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        client = self.A.app.test_client()
        with client.session_transaction() as sess:
            sess["u"], sess["f"] = "test", auth._fingerprint()
        with mock.patch.object(self.A.auth, "role", return_value="admin"):
            rep = client.post("/api/torrents/decider", json={"id": "a", "remplacer": True, "toujours": True})
        self.assertTrue(rep.get_json()["ok"], rep.get_json())
        self.assertIn("2 autre(s) demande(s)", rep.get_json()["message"])
        self.assertEqual([j["etat"] for j in self.A.torrents._lire()], ["telechargement"] * 3)
