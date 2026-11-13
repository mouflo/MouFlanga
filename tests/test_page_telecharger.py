"""Page Télécharger : en-tête MouFlanga cliquable (retour à l'accueil), choix « à valider » dans l'onglet ⏳ En cours."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class PageTelechargerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MANGA_DIR"] = str(Path(self.tmp.name) / "mangas")
        sys.modules.pop("app", None)
        import app as A
        import auth
        self.A = A
        A.torrents._ETAT["fichier"] = Path(self.tmp.name) / "torrents.json"
        os.environ.update(APP_USER="test", APP_PASSWORD_HASH="x")
        self.client = A.app.test_client()
        with self.client.session_transaction() as sess:
            sess["u"], sess["f"] = "test", auth._fingerprint()
        self.role = mock.patch.object(A.auth, "role", return_value="admin")
        self.role.start()

    def tearDown(self):
        self.role.stop()
        self.tmp.cleanup()

    def test_le_titre_ramene_a_l_accueil(self):
        html = self.client.get("/telecharger").get_data(as_text=True)
        self.assertIn('id="mou-header"', html)                     # l'en-tête du kit : logo « MouFlanga » cliquable vers /
        self.assertIn('data-sub="📥 Télécharger des mangas"', html)
        self.assertIn('<a href="/" class="back">← Retour</a>', html)

    def test_les_choix_a_valider_ont_leur_place_dans_en_cours(self):
        html = self.client.get("/telecharger").get_data(as_text=True)
        jobs = html.split('id="jobs-tab"')[1]
        self.assertIn('id="jobs-choix"', jobs)
        self.assertIn('id="jobs-choix-msg"', jobs)

    def test_une_demande_a_valider_ancienne_n_est_jamais_cachee(self):
        def tor(i, etat):
            return {"id": f"t{i}", "titre": f"S.T{i}", "serie": "S", "etat": etat, "debut": "2026-11-01 00:00", "message": "x"}
        # la plus ancienne (en queue de liste) attend un choix, derrière 40 torrents plus récents
        self.A.torrents._ecrire([tor(0, "a_valider")] + [tor(i, "fini") for i in range(1, 41)])
        rep = self.client.get("/api/torrents?leger=1").get_json()
        etats = [j["etat"] for j in rep["torrents"]]
        self.assertIn("a_valider", etats)
        self.assertEqual(len(rep["torrents"]), 31)                  # 30 récents + la demande en attente
