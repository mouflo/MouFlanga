"""Remplacement progressif d'une édition par une autre (Rave, 13/11/2026) : garde-fou « autre découpage » et édition de chaque tome."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mon_edition  # noqa: E402
import suivi  # noqa: E402
import torrents  # noqa: E402


def cbz(chemin: Path, pages: int):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(chemin, "w") as z:
        for i in range(pages):
            z.writestr(f"{i:03d}.jpg", b"x")
        z.writestr("ComicInfo.xml", "<ComicInfo/>")
    return chemin


class TestPages(unittest.TestCase):
    def test_nombre_de_pages_sans_compter_le_comicinfo(self):
        with tempfile.TemporaryDirectory() as t:
            f = cbz(Path(t) / "a.cbz", 12)
            self.assertEqual(mon_edition.nb_pages(f), 12)
            (Path(t) / "b.cbz").write_bytes(b"pas une archive")
            self.assertIsNone(mon_edition.nb_pages(Path(t) / "b.cbz"))
            self.assertIsNone(mon_edition.nb_pages(Path(t) / "absent.cbz"))

    def test_decoupage_different(self):
        self.assertTrue(mon_edition.decoupage_different(384, 95))          # Rave : édition originale contre ancienne édition
        self.assertTrue(mon_edition.decoupage_different(95, 384))
        self.assertFalse(mon_edition.decoupage_different(200, 190))        # scan et ebook du même tome
        self.assertFalse(mon_edition.decoupage_different(200, 140))        # scan aux doubles pages assemblées : 1,43
        self.assertFalse(mon_edition.decoupage_different(None, 95))        # illisible : pas de verdict

    REF = mon_edition.reference({"1": {"glenat": {"isbn": "9782344060414", "pages": 384}}, "2": {"glenat": {"isbn": "9782344060421", "pages": 370}},
                                 "3": {"wikipedia": {"isbn": "x"}}})

    def test_reference_de_l_edition(self):
        self.assertEqual(self.REF["isbn"], {1: {"9782344060414"}, 2: {"9782344060421"}})
        self.assertEqual((self.REF["pages"], self.REF["mediane"]), ({1: 384, 2: 370}, 384))

    def test_quelle_edition_est_ce_fichier(self):
        c = mon_edition.classer
        self.assertEqual(c(1, self.REF, 90, ["9782344060414"]), "edition")        # l'ISBN dit tout, même avec peu de pages
        self.assertEqual(c(1, self.REF, 384, ["9782723457972"]), "autre")
        self.assertEqual(c(2, self.REF, 354, []), "edition")                        # sans ISBN : le nombre de pages
        self.assertEqual(c(13, self.REF, 88, []), "autre")                          # tome 13 : pages de l'édition = la médiane (384)
        self.assertEqual(c(13, self.REF, None, []), "?")
        self.assertEqual(c(1, {}, 384, []), "?")                                    # pas d'édition de référence : jamais de verdict


class TestGardeFouDansLeSuivi(unittest.TestCase):
    """torrents.traiter : un autre découpage n'est jamais remplacé tout seul, même avec une règle retenue ou un « ⬆️ »."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ancien = dict(torrents._ETAT)
        torrents._ETAT["fichier"] = Path(self.tmp.name) / "torrents.json"
        self.importes, self.messages = [], []
        torrents._ETAT["decoupage"] = lambda serie, source, job=None: self.diff
        self.diff = [(5, 384, 95)]
        self.q = FauxQbit([{"hash": "h1", "progress": 1, "state": "stalledUP", "content_path": self.tmp.name, "save_path": self.tmp.name,
                            "name": "x", "category": "mouflanga"}])

    def tearDown(self):
        torrents._ETAT.clear(); torrents._ETAT.update(self.ancien)
        self.tmp.cleanup()

    def job(self, **kw):
        torrents._ecrire([{"id": "j1", "titre": "Rave.T05.FR-NRC", "serie": "Rave", "etat": "telechargement", "remplacer": True,
                           "debut": datetime.now().strftime("%Y-%m-%d %H:%M"), **kw}])

    def traiter(self):
        torrents.traiter(self.q, torrents._lire(), lambda s, src, r=False: self.importes.append((s, r)) or "ok", self.messages.append, None)

    def test_remplacer_un_autre_decoupage_demande(self):
        self.job()
        self.traiter()
        j = torrents._lire()[0]
        self.assertEqual((j["etat"], j["decoupage"]), ("a_valider", True))
        self.assertIn("T05 : 384 pages dans le torrent, 95 dans ton tome", j["message"])
        self.assertEqual(self.importes, [])
        self.assertIn("découpage", self.messages[0])

    def test_remplacer_quand_meme_n_est_plus_redemande(self):
        self.job()
        self.traiter()
        torrents.decider_torrent("j1", True)
        self.assertTrue(torrents._lire()[0]["decoupage_confirme"])
        self.traiter()
        self.assertEqual(self.importes, [("Rave", True)])
        self.assertEqual(torrents._lire()[0]["etat"], "fini")

    def test_sans_remplacement_pas_de_question(self):
        self.job(remplacer=False)
        self.traiter()
        self.assertEqual(self.importes, [("Rave", False)])

    def test_meme_decoupage_importe_comme_avant(self):
        self.diff = []
        self.job()
        self.traiter()
        self.assertEqual(self.importes, [("Rave", True)])

    def test_un_controle_qui_plante_ne_bloque_pas_l_import(self):
        torrents._ETAT["decoupage"] = mock.Mock(side_effect=RuntimeError("boum"))
        self.job()
        self.traiter()
        self.assertEqual(self.importes, [("Rave", True)])


class FauxQbit:
    def __init__(self, infos):
        self.infos, self.appels = infos, []

    def info(self, **p):
        return self.infos

    def appel(self, chemin, **data):
        self.appels.append((chemin, data))


class TestAppli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        os.environ["MANGA_DIR"] = str(t / "mangas")
        sys.modules.pop("app", None)
        import app as A
        self.A = A
        A.MANGA_DIR = t / "mangas"
        A.torrents._ETAT["fichier"] = t / "torrents.json"
        A._CACHE_CLASSEMENT.clear()
        import tomes_cbz
        self.tomes_cbz = tomes_cbz
        self.ancien_tome = cbz(tomes_cbz.fichier_tome(A.MANGA_DIR / "Rave", "Rave", 5), 95)        # ancienne édition
        self.torrent = t / "dl" / "Rave - T05 [Digital] - NRC.cbz"

    def tearDown(self):
        self.tmp.cleanup()

    def declarer_edition(self, pages=384, isbn5="9782344060452"):
        import edition
        d = edition.lire(self.A.MANGA_DIR / "Rave")
        d["edition_lien"] = "https://www.glenat.com/glenat-manga/rave-edition-originale-tome-01-9782344060414/"
        edition.ecrire(self.A.MANGA_DIR / "Rave", d)
        obs = {"5": {"glenat": {"isbn": isbn5, "pages": pages}}}
        return mock.patch("notices.observations", return_value=obs)

    def test_un_autre_decoupage_est_signale(self):
        cbz(self.torrent, 384)
        self.assertEqual(self.A._decoupage_different("Rave", self.torrent.parent), [(5, 384, 95)])

    def test_meme_decoupage_rien_a_signaler(self):
        cbz(self.torrent, 100)
        self.assertEqual(self.A._decoupage_different("Rave", self.torrent.parent), [])

    def test_le_torrent_de_l_edition_voulue_est_une_migration_voulue(self):
        cbz(self.torrent, 384)
        with self.declarer_edition():
            self.assertEqual(self.A._decoupage_different("Rave", self.torrent.parent), [])          # 384 pages = l'édition choisie

    def test_un_torrent_d_une_troisieme_edition_est_quand_meme_signale(self):
        cbz(self.torrent, 200)
        with self.declarer_edition():
            self.assertEqual(self.A._decoupage_different("Rave", self.torrent.parent), [(5, 200, 95)])

    def test_classement_des_tomes_et_resume(self):
        cbz(self.tomes_cbz.fichier_tome(self.A.MANGA_DIR / "Rave", "Rave", 1), 384)
        with self.declarer_edition(), mock.patch.object(self.A, "_tomes_de", return_value={1, 5}), \
                mock.patch.object(self.A, "_pages_de_torrents", return_value=[]):
            c = self.A._classement_editions("Rave")
        self.assertEqual(c, {1: "edition", 5: "autre"})
        self.assertEqual(self.A._resume_editions(c, "Édition originale"), "T1 Édition originale · T5 autre édition (à remplacer)")
        self.assertEqual(self.A._resume_editions({1: "edition", 2: "edition"}, "X"), "")          # tout de la même édition : rien à dire

    def test_sans_page_d_editeur_aucun_classement(self):
        self.assertEqual(self.A._classement_editions("Rave"), {})

    def test_une_regle_retenue_ne_contourne_pas_le_garde_fou(self):
        self.A.torrents._ecrire([{"id": "a", "titre": "Rave.T05", "serie": "Rave", "etat": "a_valider", "decoupage": True, "manuel": True,
                                  "debut": "2026-11-13 00:44", "message": "x"}])
        self.A._write_json(self.A.REGLES_IMPORT, {"Rave": {"choix": "remplacer"}}) if hasattr(self.A, "REGLES_IMPORT") else None
        self.assertEqual(self.A._appliquer_regles_en_attente(), 0)
        self.assertEqual(self.A.torrents._lire()[0]["etat"], "a_valider")


class TestSurveillance(unittest.TestCase):
    def r(self, titre):
        return {"titre": titre, "score": 0, "sources": 5}

    def test_un_tome_d_une_autre_edition_est_a_remplacer_par_un_ebook_officiel(self):
        info = {"autre_edition": {13, 14}}
        self.assertEqual(suivi.tomes_ameliorables(self.r("Rave.T13.FR.[CBZ]-NeoRipClub"), {13, 14, 15}, info), {13, 14})
        self.assertEqual(suivi.tomes_ameliorables(self.r("Rave.T13.FR.Scan.ebdz"), {13, 14}, info), set())      # pas un ebook officiel
        self.assertEqual(suivi.tomes_ameliorables(self.r("Rave.T13.FR.[CBZ]-NeoRipClub"), {13}, {}), set())


if __name__ == "__main__":
    unittest.main()
