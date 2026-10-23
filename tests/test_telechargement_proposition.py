"""⬇️ d'une proposition de la fiche d'une série : le téléchargement part directement, sans passer par la page Télécharger."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as A  # noqa: E402
import suivi  # noqa: E402


class TelechargerPropositionTest(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.ancien = suivi._ETAT["fichier"]
        suivi._ETAT["fichier"] = Path(self.dossier.name) / "suivies.json"
        suivi.ecrire({"series": {"Kaf": {"surveiller": True, "titres": ["Kaf"], "propositions": [
            {"id": "p1", "type": "nouveau", "titre": "Kaf.T04.FR", "statut": "attente", "tomes": [4]},
            {"id": "p2", "type": "meilleur", "titre": "Kaf.T01.FR.Digital", "statut": "attente", "tomes": [1]}]}}})
        self.avant = A.app.before_request_funcs.get(None, [])
        A.app.before_request_funcs[None] = []
        self.c = A.app.test_client()
        self.res = [{"titre": "Kaf.T04.FR", "lien": "http://prowlarr/dl?apikey=secret", "page": "https://c411.org/t/1", "rejet": ""},
                    {"titre": "Kaf.T01.FR.Digital", "lien": "http://prowlarr/dl2", "page": "", "rejet": ""}]

    def tearDown(self):
        suivi._ETAT["fichier"] = self.ancien
        A.app.before_request_funcs[None] = self.avant
        self.dossier.cleanup()

    def poste(self, pid, resultats=None, lancer=None):
        with mock.patch.object(A.torrents, "configure", return_value=True), \
                mock.patch.object(A.torrents, "chercher", return_value=self.res if resultats is None else resultats), \
                mock.patch.object(A.torrents, "lancer", lancer or mock.Mock()) as l:
            r = self.c.post("/api/suivies", json={"action": "telecharger", "nom": "Kaf", "id": pid})
            return r, l

    def test_nouveau_ajoute_seulement_les_manquants_et_marque_telecharge(self):
        r, l = self.poste("p1")
        self.assertEqual(r.status_code, 200)
        l.assert_called_once_with("http://prowlarr/dl?apikey=secret", "Kaf.T04.FR", "Kaf", False, "https://c411.org/t/1")
        self.assertEqual(suivi.lire()["series"]["Kaf"]["propositions"][0]["statut"], "telecharge")
        self.assertNotIn("secret", r.get_data(as_text=True))                     # le lien de Prowlarr ne revient jamais au navigateur

    def test_meilleur_remplace(self):
        r, l = self.poste("p2")
        self.assertEqual(l.call_args[0][3], True)
        self.assertIn("corbeille", r.get_json()["message"])

    def test_torrent_disparu_ou_proposition_inconnue(self):
        r, l = self.poste("p1", resultats=[])
        self.assertEqual(r.status_code, 404)
        l.assert_not_called()
        self.assertEqual(suivi.lire()["series"]["Kaf"]["propositions"][0]["statut"], "attente")
        self.assertEqual(self.poste("zzz")[0].status_code, 404)

    def test_anglais_jamais_telecharge(self):
        r, l = self.poste("p1", resultats=[{**self.res[0], "rejet": "marqué en anglais (ENG / EN) : jamais pris"}])
        self.assertEqual(r.status_code, 400)
        l.assert_not_called()

    def test_une_proposition_deja_telechargee_ne_repart_pas(self):
        self.poste("p1")
        r, l = self.poste("p1")
        self.assertEqual(r.status_code, 404)
        l.assert_not_called()

    def test_erreur_qbittorrent_laisse_la_proposition_en_attente(self):
        r, _ = self.poste("p1", lancer=mock.Mock(side_effect=RuntimeError("qBittorrent injoignable")))
        self.assertEqual(r.status_code, 502)
        self.assertEqual(suivi.lire()["series"]["Kaf"]["propositions"][0]["statut"], "attente")


if __name__ == "__main__":
    unittest.main()
