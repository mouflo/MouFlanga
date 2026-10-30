"""Un torrent lancé depuis l'appli : sa page de tracker (synopsis français, auteur, genre) est gardée dans les infos de la série."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edition  # noqa: E402
import page_tracker  # noqa: E402

TITRE = "Basilisk.INTEGRALE.T01.a.T05.FRENCH.Digital.1178px.CBZ-NoTag"
LUE = {"tracker": "TR4KER", "infos": {"synopsis": "En 1614, le Japon est enfin en paix.", "auteur": "Futaro Yamada", "genre": "Seinen", "qualite": "Digital"}}


class PageDuTorrentTest(unittest.TestCase):
    def setUp(self):
        import app as m
        self.m = m
        self.dossier = Path(tempfile.mkdtemp()) / "Basilisk"
        self.dossier.mkdir()

    def lancer(self, lue=LUE, jobs=None, titre="BASILISK.integrale.T01.A.T05.french.digital.1178px.cbz-notag"):
        jobs = [{"titre": TITRE, "page": "https://tr4ker.net/torrent/x"}] if jobs is None else jobs
        with mock.patch.object(self.m.torrents, "_lire", return_value=jobs), \
                mock.patch.object(page_tracker, "lire", return_value=lue) as lire:
            return self.m._noter_page_du_torrent(self.dossier, titre), lire

    def test_synopsis_auteur_genre_gardes_sans_la_casse(self):
        ajoute, _ = self.lancer()
        self.assertEqual(set(ajoute), {"synopsis", "auteur", "genre"})
        self.assertEqual(edition.lire(self.dossier)["nfo_infos"]["synopsis"], LUE["infos"]["synopsis"])

    def test_rien_n_est_remplace(self):
        edition.ecrire(self.dossier, {"nfo_infos": {"synopsis": "Déjà là", "auteur": "Moi"}})
        ajoute, _ = self.lancer()
        self.assertEqual(set(ajoute), {"genre"})
        self.assertEqual(edition.lire(self.dossier)["nfo_infos"]["synopsis"], "Déjà là")

    def test_torrent_sans_page_ou_inconnu_ne_lit_rien(self):
        ajoute, lire = self.lancer(jobs=[{"titre": TITRE}])
        self.assertEqual(ajoute, {})
        lire.assert_not_called()
        ajoute, lire = self.lancer(titre="Autre torrent")
        lire.assert_not_called()

    def test_page_illisible_ne_bloque_rien(self):
        with mock.patch.object(self.m.torrents, "_lire", return_value=[{"titre": TITRE, "page": "https://tr4ker.net/torrent/x"}]), \
                mock.patch.object(page_tracker, "lire", side_effect=page_tracker.PageIllisible("Prowlarr n'est pas réglé")):
            self.assertEqual(self.m._noter_page_du_torrent(self.dossier, TITRE), {})
        self.assertNotIn("nfo_infos", edition.lire(self.dossier))
