"""identification.py : heure de reprise en français, états notés sans réécrire pour rien, séries à reprendre, éditions particulières."""
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import identification as I  # noqa: E402
import reseau  # noqa: E402
import tomes  # noqa: E402

S = "Série test"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = [mock.patch.object(tomes, "DOSSIER", Path(self.tmp.name)), mock.patch.object(tomes, "SERIES_EXISTANTES", lambda: [S])]
        for p in self.p:
            p.start()
        tomes._CACHE_FICHES.clear()

    def tearDown(self):
        for p in self.p:
            p.stop()
        tomes._CACHE_FICHES.clear()
        self.tmp.cleanup()

    def cache(self):
        return json.loads(tomes._fichier(S).read_text(encoding="utf-8"))


class HeureTest(unittest.TestCase):
    def test_heure_de_paris_jamais_utc(self):
        paris = ZoneInfo("Europe/Paris")
        demain = datetime.now(paris).replace(hour=9, minute=5, second=0, microsecond=0)
        self.assertRegex(I.heure_fr((demain + timedelta(days=1)).timestamp()), r"^demain 9 h 05$")
        self.assertRegex(I.heure_fr((demain + timedelta(days=3)).timestamp()), r"^le \d\d/\d\d à 9 h 05$")     # (le changement d'heure ne décale rien)

    def test_reprise_jamais_dans_moins_de_cinq_minutes(self):
        e = reseau.Panne("Google Books", "x", time.time() + 10)
        self.assertGreaterEqual(I._reprise([e]), time.time() + 290)
        e2 = reseau.Panne("Google Books", "x", time.time() + 7200)
        self.assertAlmostEqual(I._reprise([e2, reseau.Panne("BnF", "x")]), e2.reprise, delta=2)
        self.assertGreater(I._reprise([reseau.Panne("BnF", "x")]), time.time() + 3000)               # sans heure donnée : une heure


class NoterTest(Base):
    def test_noter_n_ecrit_que_si_quelque_chose_change(self):
        b = I.Bilan("panne", "Google Books n'a pas répondu", time.time() + 3600)
        I.noter(S, "notices", b)
        premier = tomes._fichier(S).stat().st_mtime_ns
        time.sleep(0.01)
        I.noter(S, "notices", b)
        self.assertEqual(tomes._fichier(S).stat().st_mtime_ns, premier)
        I.noter(S, "notices", I.Bilan("deja", "x", None))                                           # « déjà à jour » : jamais écrit
        self.assertEqual(self.cache()["recherches"]["notices"]["etat"], "panne")

    def test_a_reprendre_et_jamais_faites(self):
        I.noter(S, "notices", I.Bilan("panne", "x", time.time() + 100))
        self.assertEqual(I.a_reprendre([S], maintenant=time.time()), [])
        self.assertEqual(I.a_reprendre([S], maintenant=time.time() + 200), [S])
        I.noter(S, "notices", I.Bilan("ok", "fini", None))
        self.assertEqual(I.a_reprendre([S], maintenant=time.time() + 10 ** 7), [])
        self.assertEqual(I.jamais_faites([S, "Autre"]), ["Autre"])


class EditionTest(Base):
    def test_edition_particuliere_sans_nom_ne_cherche_rien(self):
        with mock.patch.object(I, "CONTEXTE", lambda s: {"tomes": {1, 2}, "edition": "", "edition_differente": True}), \
                mock.patch.object(I.bnf, "chercher") as bnf_, mock.patch.object(I.googlebooks, "chercher_serie") as google:
            b = I.etape_notices(S)
        self.assertEqual(b.etat, "deja")
        self.assertEqual(b.extra["isbn_manquants"], [1, 2])
        bnf_.assert_not_called()
        google.assert_not_called()
        self.assertTrue(self.cache()["edition_differente"])

    def test_edition_particuliere_nommee_cherche_seulement_cette_edition(self):
        with mock.patch.object(I, "CONTEXTE", lambda s: {"tomes": {1}, "edition": "Perfect Edition", "edition_differente": True}), \
                mock.patch.object(I.bnf, "chercher", return_value={}) as bnf_, mock.patch.object(I.googlebooks, "cle", return_value=""):
            I.etape_notices(S)
        self.assertEqual(bnf_.call_args.kwargs["edition"], "Perfect Edition")

    def test_sans_tome_rien_a_faire(self):
        with mock.patch.object(I, "CONTEXTE", lambda s: {"tomes": set(), "edition": "", "edition_differente": False}):
            self.assertEqual(I.etape_notices(S).etat, "deja")


class IsbnConnusPourGoogleTest(Base):
    def test_les_isbn_deja_trouves_disent_a_google_de_quel_tome_il_s_agit(self):
        """Google rend « Air Gear » sans numéro : l'ISBN, trouvé par la BnF, donne le tome."""
        trouves_bnf = {1: {"tome": 1, "isbn": "9782811602680", "resume": "", "titre": "Air Gear", "editeur": "Pika", "date": "2010"}}
        with mock.patch.object(I, "CONTEXTE", lambda s: {"tomes": {1, 2}, "edition": "", "edition_differente": False}), \
                mock.patch.object(I.bnf, "chercher", return_value=trouves_bnf), mock.patch.object(I.googlebooks, "cle", return_value="CLE"), \
                mock.patch.object(I.googlebooks, "chercher_serie", return_value={}) as google, mock.patch.object(I.googlebooks, "chercher_tome", return_value=None):
            I.etape_notices(S)
        self.assertEqual(google.call_args.kwargs["isbn_tomes"], {"9782811602680": 1})


if __name__ == "__main__":
    unittest.main()
