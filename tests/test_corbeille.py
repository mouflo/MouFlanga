"""🗑 Corbeille : durée de conservation réglable (jours, mois, jamais), nettoyage selon ce réglage, jamais d'effacement si « jamais »."""
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as m  # noqa: E402


def _jour(racine, il_y_a_jours, contenu=b"x" * 1000):
    nom = (datetime.now() - timedelta(days=il_y_a_jours)).strftime("%Y-%m-%d")
    d = Path(racine) / m.CORBEILLE / nom / "Serie"
    d.mkdir(parents=True, exist_ok=True)
    (d / "Tome 01.cbz.avant").write_bytes(contenu)
    return d.parent


class CorbeilleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self.tmp.name)
        self.patchs = [mock.patch.object(m, "MANGA_DIR", self.racine), mock.patch.object(m, "_fichier_corbeille", return_value=self.racine / "corbeille.json")]
        for p in self.patchs:
            p.start()
        self.c = m.app.test_client()

    def tearDown(self):
        for p in self.patchs:
            p.stop()
        self.tmp.cleanup()

    def _regler(self, **r):
        m._write_json(self.racine / "corbeille.json", r)

    def test_par_defaut_trente_jours(self):
        self.assertEqual(m._corbeille_reglage(), {"mode": "duree", "valeur": 30, "unite": "jours"})
        self.assertEqual(m._corbeille_jours(), 30)
        self.assertEqual(m._corbeille_phrase(), "gardé 30 jours, puis effacé")

    def test_mois_jamais_et_zero(self):
        self._regler(mode="duree", valeur=2, unite="mois")
        self.assertEqual(m._corbeille_jours(), 60)
        self.assertEqual(m._corbeille_phrase(), "gardé 2 mois, puis effacé")
        self._regler(mode="jamais", valeur=7, unite="jours")
        self.assertIsNone(m._corbeille_jours())
        self.assertIn("sans limite", m._corbeille_phrase())
        self._regler(mode="duree", valeur=0, unite="jours")
        self.assertEqual(m._corbeille_jours(), 0)
        self.assertIn("aussitôt", m._corbeille_phrase())
        self._regler(mode="duree", valeur=1, unite="jours")
        self.assertEqual(m._corbeille_phrase(), "gardé 1 jour, puis effacé")

    def test_fichier_abime_ou_valeurs_absurdes_reviennent_au_defaut(self):
        (self.racine / "corbeille.json").write_text("pas du json", encoding="utf-8")
        self.assertEqual(m._corbeille_jours(), 30)
        self._regler(mode="n'importe quoi", valeur="abc", unite="années")
        self.assertEqual(m._corbeille_reglage(), {"mode": "duree", "valeur": 30, "unite": "jours"})

    def test_nettoyage_efface_seulement_ce_qui_depasse_la_duree(self):
        vieux, recent = _jour(self.racine, 45), _jour(self.racine, 5)
        self._regler(mode="duree", valeur=30, unite="jours")
        b = m._vider_corbeille(mesurer=True)
        self.assertEqual(b["jours"], 1)
        self.assertEqual(b["octets"], 1000)
        self.assertFalse(vieux.exists())
        self.assertTrue(recent.exists())

    def test_jamais_n_efface_rien(self):
        vieux = _jour(self.racine, 400)
        self._regler(mode="jamais")
        self.assertEqual(m._vider_corbeille()["jours"], 0)
        self.assertTrue(vieux.exists())

    def test_les_mois_comptent_trente_jours(self):
        _jour(self.racine, 50)
        self._regler(mode="duree", valeur=2, unite="mois")
        self.assertEqual(m._vider_corbeille()["jours"], 0)                       # 50 jours < 2 mois
        self._regler(mode="duree", valeur=1, unite="mois")
        self.assertEqual(m._vider_corbeille()["jours"], 1)

    def test_dossier_qui_n_est_pas_un_jour_jamais_touche(self):
        autre = self.racine / m.CORBEILLE / "pas-une-date"
        autre.mkdir(parents=True)
        self._regler(mode="duree", valeur=0, unite="jours")
        m._vider_corbeille()
        self.assertTrue(autre.exists())

    def test_route_enregistre_et_refuse_les_valeurs_invalides(self):
        with mock.patch.object(m.auth, "role", return_value="admin"):
            r = self.c.post("/api/corbeille", json={"mode": "duree", "valeur": 3, "unite": "mois"})
            self.assertTrue(r.get_json()["ok"], r.get_json())
            self.assertEqual(m._corbeille_jours(), 90)
            for mauvais in ({"mode": "duree", "valeur": -1, "unite": "jours"}, {"mode": "duree", "valeur": "x", "unite": "jours"},
                            {"mode": "duree", "valeur": 5, "unite": "années"}, {"mode": "supprimer", "valeur": 5, "unite": "jours"},
                            {"mode": "duree", "valeur": 99999, "unite": "jours"}):
                rep = self.c.post("/api/corbeille", json=mauvais)
                self.assertEqual(rep.status_code, 400, mauvais)
            self.assertEqual(m._corbeille_jours(), 90)                           # rien n'a changé

    def test_route_taille_et_nettoyage_manuel(self):
        _jour(self.racine, 45, b"y" * 2000)
        _jour(self.racine, 2, b"z" * 500)
        with mock.patch.object(m.auth, "role", return_value="admin"):
            d = self.c.get("/api/corbeille?taille=1").get_json()
            self.assertEqual(d["octets"], 2500)
            self.assertEqual(d["a_effacer"], 2000)
            self.assertEqual(len(d["jours_gardes"]), 2)
            self.assertEqual(d["duree_texte"], "gardé 30 jours, puis effacé")
            self._regler(mode="jamais")
            r = self.c.post("/api/corbeille", json={"action": "vider"}).get_json()
            self.assertIn("rien n'a été effacé", r["message"])
            self.assertEqual(self.c.get("/api/corbeille?taille=1").get_json()["octets"], 2500)
            self._regler(mode="duree", valeur=30, unite="jours")
            r = self.c.post("/api/corbeille", json={"action": "vider"}).get_json()
            self.assertIn("1 jour(s)", r["message"])
            self.assertEqual(self.c.get("/api/corbeille?taille=1").get_json()["octets"], 500)

    def test_un_lecteur_n_a_pas_acces(self):
        with mock.patch.object(m.auth, "role", return_value="lecteur"):
            self.assertIn(self.c.get("/api/corbeille").status_code, (401, 403))
            self.assertIn(self.c.post("/api/corbeille", json={"action": "vider"}).status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
