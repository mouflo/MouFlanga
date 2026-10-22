"""Page d'un torrent sur son tracker : lue par l'API du tracker avec la clé de Prowlarr, jamais ailleurs, jamais la clé gardée ni montrée."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import page_tracker  # noqa: E402
import reseau  # noqa: E402
from faux_internet import Reponse  # noqa: E402

CLES = {"C411": "CLE-C411-SECRETE", "TR4KER": "CLE-TR4KER-SECRETE", "The Old School (API)": "CLE-TOS-SECRETE", "Abnormal (API)": "CLE-ABN-SECRETE"}
HASH = "2dacfd425ce554b776795592dd9f78418b855600"
NFO = """╔════════════════════════════╗
║  Wind Breaker T07          ║
╚════════════════════════════╝
 INFORMATIONS
────────────────────────────
   Titre...............: Wind Breaker T07
   Auteur..............: Nii Satoru
   Éditeur (FR)........: Pika
   Nombre de pages.....: 191
   Résolution..........: 1499x2250 px
   ISBN................: 9782811686901
 DESCRIPTION
────────────────────────────
   Afin de venir en aide à un camarade de classe, Sakura et les élèves de Seconde ont décidé de se battre contre les Keel.
 SOURCE
────────────────────────────
   * Source : Epub webrip
"""
C411 = {"id": 192168, "infoHash": HASH, "name": "Wind.Breaker.T07.Nii.Satoru.FR.[CBZ]-Dogbanov", "descriptionFormat": "standard",
        "description": "<p style=\"text-align: center\"><strong>Wind Breaker T07</strong></p><p><img src=\"https://files.catbox.moe/a.jpg\"></p>"
                       "<p>Afin de venir en aide à un camarade de classe, Sakura et les élèves de Seconde ont décidé de se battre contre les Keel, "
                       "une bande sans pitié.</p><p><strong>Auteur</strong> : Nii Satoru<br><strong>Éditeur (FR)</strong> : Pika<br>"
                       "<strong>ISBN</strong> : 9782811686901</p>",
        "size": 194678416, "seeders": 9, "uploader": "Dogbanov", "createdAt": "2026-07-10T20:53:59Z",
        "files": [{"path": ["Wind.Breaker.T07.Nii.Satoru.FR.[CBZ]-Dogbanov.cbz"], "length": 194678416}],
        "metadata": {"hasNfo": True, "nfoContent": NFO}}
SLUG = "dogsred-t04-2025-fr-cbz-notag-t9-280074"
TR4KER = {"id": 1736373, "slug": SLUG, "name": "Dogsred.T04.2025.FR.CBZ-NoTag", "size_bytes": 82137013, "seeders": 17,
          "created_at": "2026-05-21T04:15:37Z", "description": None, "extra_info": None, "classic_description_format": "bbcode", "nfo": "",
          "classic_description": "[center][b]Dogsred - Tome 04[/b]\n[img]https://i.imgur.com/x.png[/img]\n[b]Auteur(s) :[/b] [i]Noda Satoru[/i]\n"
                                 "[b]Genres :[/b] Sports, Action, Drama\n\n[size=3]Après une journée cauchemardesque entre exercices d'endurance, "
                                 "déshydratation et attaque d'ours, seules neuf des 17 nouvelles recrues de l'équipe de hockey sont prêtes à "
                                 "rempiler...[/size]\n\n[b]Qualité :[/b] [i]Scan[/i][/center]", "uploader": "Intel_t9", "files": []}
TOS = {"type": "torrent", "id": "325466", "attributes": {
    "name": "Beelzebub.T28.FRENCH.CBZ.eBook-ebdz", "uploader": "Anonymous", "seeders": 4, "size": 44845817, "created_at": "2026-01-24T21:18:21Z",
    "description": "Date de sortie: 21 Octobre 2015\r\nISBN: 9782820321992\r\n\r\nRésumé:\r\nExiste-t-il être plus effrayant et caractériel que le "
                   "Diable Suprême himself ? Sa mère !! Oga &amp; Cie vivent de dernières aventures où il est question d'île déserte.",
    "files": [{"index": 1, "name": "Beelzebub.T28.FRENCH.CBZ.eBook-ebdz.cbz", "size": 44845817}],
    "download_link": "https://theoldschool.cc/torrent/download/325466.RSSKEY-DU-MEMBRE-SECRETE", "details_link": "https://theoldschool.cc/torrents/325466"}}
ABN = {"id": 26865, "name": "Beelzebub.T01-T28.FRENCH.HYBRiD.eBook-PRESSECiTRON", "infos": "", "size": 3040735960, "seeders": 0,
       "created": "2016-06-16T14:51:42", "downloadUrl": "https://api.abn.lol/api/Release/Download?id=26865&key=CLE-ABN-SECRETE"}


def indexeurs():
    def fiche(nom, definition, hote, **plus):
        champs = [{"name": "baseUrl", "value": f"https://{hote}/"}, {"name": "apikey", "value": CLES.get(nom, "")}]
        champs += [{"name": k, "value": v} for k, v in plus.items()]
        return {"name": nom, "definitionName": definition, "enable": True, "fields": champs}
    return [fiche("C411", "c411", "c411.org"), fiche("TR4KER", "tr4ker", "tr4ker.net"),
            fiche("The Old School (API)", "theoldschool-api", "theoldschool.cc"), fiche("Abnormal (API)", "abnormal-api", "abn.lol", apiurl="api.abn.lol"),
            {"name": "HD-Forever", "definitionName": "hdforever", "enable": True,
             "fields": [{"name": "baseUrl", "value": "https://hdf.world/"}, {"name": "username", "value": "membre"}, {"name": "password", "value": "MOT-DE-PASSE"}]},
            {"name": "Éteint", "definitionName": "c411", "enable": False, "fields": [{"name": "baseUrl", "value": "https://eteint.example/"}]}]


class FauxTrackers:
    """Prowlarr et les quatre trackers, avec leurs vraies formes de réponse ; `pannes` : {hôte: statut | « coupe » | « html »}."""

    def __init__(self):
        self.pannes, self.appels = {}, []

    def __call__(self, url, **kw):
        self.appels.append((url, kw))
        hote = url.split("/")[2]
        panne = self.pannes.get(hote)
        if panne == "coupe":
            raise reseau.requests.ConnectionError("coupé")
        if panne == "html":
            return Reponse(200, texte="<html>Connexion</html>")
        if panne:
            return Reponse(int(panne), {"error": "non"})
        if url.endswith("/api/v1/indexer"):
            return Reponse(200, indexeurs())
        if hote == "c411.org":
            return Reponse(200, C411) if url.endswith("/api/torrents/" + HASH) else Reponse(404, {})
        if hote == "tr4ker.net":
            return Reponse(200, TR4KER) if url.endswith("/api/torrents/" + SLUG) else Reponse(404, {})
        if hote == "theoldschool.cc":
            return Reponse(200, TOS) if url.endswith("/api/torrents/325466") else Reponse(404, {})
        if hote == "api.abn.lol":
            return Reponse(200, ABN) if url.endswith("/api/Release/26865") else Reponse(404, {})
        return Reponse(404, {})

    def vers(self, hote):
        return [(u, kw) for u, kw in self.appels if u.split("/")[2] == hote]


class PageTrackerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.avant = page_tracker.FICHIER
        page_tracker.FICHIER = Path(self.tmp) / "torrent-pages.json"
        reseau.oublier_tout()
        page_tracker.oublier_indexeurs()
        self.faux = FauxTrackers()
        self.reglages = mock.patch("torrents.reglages", return_value={"prowlarr": "http://192.168.1.133:9696", "prowlarr_cle": "CLE-PROWLARR-SECRETE"})
        self.reglages.start()
        self.session = mock.patch.object(reseau.SESSION, "get", side_effect=self.faux)
        self.session.start()

    def tearDown(self):
        self.session.stop()
        self.reglages.stop()
        page_tracker.FICHIER = self.avant
        page_tracker.oublier_indexeurs()
        reseau.oublier_tout()

    def assertSansCle(self, valeur):
        t = json.dumps(valeur, ensure_ascii=False) if not isinstance(valeur, str) else valeur
        for secret in ("SECRETE", "MOT-DE-PASSE", "RSSKEY"):
            self.assertNotIn(secret, t)

    # -- C411
    def test_c411_presentation_et_nfo(self):
        p = page_tracker.lire(f"https://c411.org/torrents/{HASH}")
        self.assertEqual((p["tracker"], p["hote"], p["tomes"]), ("C411", "c411.org", [7]))
        i = p["infos"]
        self.assertEqual((i["auteur"], i["editeur"], i["pages"], i["resolution"]), ("Nii Satoru", "Pika", 191, "1499x2250"))
        self.assertEqual(i["isbn"], {"7": "9782811686901"})               # un seul tome dans le nom, un seul ISBN : c'est le sien
        self.assertTrue(i["synopsis"].startswith("Afin de venir en aide"))
        self.assertIn("Epub webrip", p["nfo"])
        self.assertEqual(p["fichiers"], [{"nom": "Wind.Breaker.T07.Nii.Satoru.FR.[CBZ]-Dogbanov.cbz", "taille": 194678416}])
        self.assertEqual((p["taille"], p["sources"], p["date"], p["equipe"]), (194678416, 9, "2026-07-10", "Dogbanov"))
        self.assertSansCle(p)

    def test_la_cle_part_dans_l_en_tete_pas_dans_l_adresse(self):
        page_tracker.lire(f"https://c411.org/torrents/{HASH}")
        (url, kw), = self.faux.vers("c411.org")
        self.assertEqual(url, f"https://c411.org/api/torrents/{HASH}")
        self.assertEqual(kw["headers"]["Authorization"], "Bearer CLE-C411-SECRETE")
        self.assertNotIn("SECRETE", url)

    # -- TR4KER
    def test_tr4ker_bbcode(self):
        p = page_tracker.lire(f"https://tr4ker.net/torrent/{SLUG}")
        self.assertEqual((p["tracker"], p["equipe"]), ("TR4KER", "Intel_t9"))
        self.assertEqual((p["infos"]["auteur"], p["infos"]["genre"], p["infos"]["qualite"]), ("Noda Satoru", "Sports, Action, Drama", "Scan"))
        self.assertTrue(p["infos"]["synopsis"].startswith("Après une journée"))
        self.assertNotIn("[b]", p["presentation"])
        self.assertSansCle(p)
        (url, kw), = self.faux.vers("tr4ker.net")
        self.assertEqual(kw["params"], {"apikey": "CLE-TR4KER-SECRETE"})            # TR4KER la veut dans l'adresse ; elle n'est ni gardée ni journalisée

    # -- The Old School
    def test_the_old_school_ne_garde_pas_le_lien_de_telechargement(self):
        p = page_tracker.lire("https://theoldschool.cc/torrents/325466")
        self.assertEqual(p["infos"]["isbn"], {"28": "9782820321992"})
        self.assertIn("Oga & Cie", p["infos"]["synopsis"])
        self.assertEqual(p["equipe"], "")                                              # « Anonymous » n'est pas une équipe
        self.assertSansCle(p)

    # -- ABN
    def test_abn_donne_peu_mais_proprement(self):
        p = page_tracker.lire("https://abn.lol/Torrent/Details?ReleaseId=26865")
        self.assertEqual((p["tracker"], p["titre"], p["tomes"]), ("Abnormal (API)", "Beelzebub.T01-T28.FRENCH.HYBRiD.eBook-PRESSECiTRON", list(range(1, 29))))
        self.assertEqual(p["infos"], {})
        self.assertSansCle(p)

    # -- Sécurité des adresses
    def test_une_adresse_hors_prowlarr_n_est_jamais_lue(self):
        with self.assertRaises(page_tracker.PageIllisible) as c:
            page_tracker.lire("https://exemple.org/torrents/1")
        self.assertTrue(c.exception.definitif)
        self.assertEqual(self.faux.vers("exemple.org"), [])

    def test_seul_https_sans_identifiant_ni_port(self):
        for mauvaise in ("http://c411.org/torrents/" + HASH, "https://membre:mdp@c411.org/torrents/" + HASH, "https://c411.org:8443/torrents/" + HASH,
                         "ftp://c411.org/x", "", "pas une adresse"):
            with self.assertRaises(page_tracker.PageIllisible, msg=mauvaise):
                page_tracker.lire(mauvaise)
        self.assertEqual(self.faux.vers("c411.org"), [])

    def test_un_nom_de_site_qui_ressemble_n_est_pas_le_tracker(self):
        with self.assertRaises(page_tracker.PageIllisible):
            page_tracker.lire(f"https://c411.org.pirate.example/torrents/{HASH}")
        with self.assertRaises(page_tracker.PageIllisible):
            page_tracker.lire(f"https://faux-c411.org/torrents/{HASH}")

    def test_tracker_sans_lecteur_dit_pourquoi(self):
        with self.assertRaises(page_tracker.PageIllisible) as c:
            page_tracker.lire("https://hdf.world/torrents.php?id=1")
        self.assertTrue(c.exception.definitif)
        self.assertIn("HD-Forever", c.exception.message)
        self.assertSansCle(c.exception.message)

    def test_adresse_de_page_inconnue_pour_ce_tracker(self):
        with self.assertRaises(page_tracker.PageIllisible):
            page_tracker.lire("https://c411.org/user/integrations")
        with self.assertRaises(page_tracker.PageIllisible):
            page_tracker.lire("https://theoldschool.cc/torrents/abc")

    # -- Pannes : jamais « page vide »
    def test_pannes_et_refus_disent_pourquoi(self):
        for panne, mot in (("503", "n'a pas répondu"), ("coupe", "n'a pas répondu"), ("html", "n'a pas répondu"), ("401", "refuse la clé")):
            reseau.oublier_tout()
            self.faux.pannes = {"c411.org": panne}
            with self.assertRaises(page_tracker.PageIllisible, msg=panne) as c:
                page_tracker.lire(f"https://c411.org/torrents/{HASH}", force=True)
            self.assertIn(mot, c.exception.message, panne)
            self.assertFalse(c.exception.definitif, panne)
            self.assertSansCle(c.exception.message)

    def test_torrent_supprime(self):
        with self.assertRaises(page_tracker.PageIllisible) as c:
            page_tracker.lire("https://c411.org/torrents/" + "0" * 40)
        self.assertTrue(c.exception.definitif)
        self.assertIn("ne connaît plus", c.exception.message)

    def test_prowlarr_en_panne(self):
        self.faux.pannes = {"192.168.1.133:9696": "503"}
        with self.assertRaises(page_tracker.PageIllisible) as c:
            page_tracker.lire(f"https://c411.org/torrents/{HASH}")
        self.assertIn("Prowlarr n'a pas répondu", c.exception.message)

    def test_tracker_sans_cle_dans_prowlarr(self):
        with mock.patch.dict(CLES, {"C411": ""}):
            with self.assertRaises(page_tracker.PageIllisible) as c:
                page_tracker.lire(f"https://c411.org/torrents/{HASH}")
        self.assertTrue(c.exception.definitif)
        self.assertIn("pas de clé", c.exception.message)

    # -- Mémoire d'une semaine
    def test_page_gardee_une_semaine_sans_reinterroger_le_tracker(self):
        a = page_tracker.lire(f"https://c411.org/torrents/{HASH}")
        b = page_tracker.lire(f"https://c411.org/torrents/{HASH}#autre")
        self.assertEqual(a, b)
        self.assertEqual(len(self.faux.vers("c411.org")), 1)
        page_tracker.lire(f"https://c411.org/torrents/{HASH}", force=True)
        self.assertEqual(len(self.faux.vers("c411.org")), 2)
        self.assertTrue(page_tracker.lisible(f"https://c411.org/torrents/{HASH}"))
        self.assertFalse(page_tracker.lisible("https://hdf.world/x"))
        self.assertFalse(page_tracker.lisible("https://exemple.org/x"))

    def test_une_panne_ne_laisse_rien_en_memoire(self):
        self.faux.pannes = {"c411.org": "503"}
        with self.assertRaises(page_tracker.PageIllisible):
            page_tracker.lire(f"https://c411.org/torrents/{HASH}")
        self.assertFalse(page_tracker.FICHIER.exists())
        self.assertIsNone(page_tracker.en_memoire(f"https://c411.org/torrents/{HASH}"))
        self.faux.pannes = {}
        reseau.oublier_tout()
        self.assertEqual(page_tracker.lire(f"https://c411.org/torrents/{HASH}")["tracker"], "C411")

    def test_fichier_de_memoire_sans_cle(self):
        page_tracker.lire(f"https://c411.org/torrents/{HASH}")
        page_tracker.lire("https://theoldschool.cc/torrents/325466")
        self.assertSansCle(page_tracker.FICHIER.read_text(encoding="utf-8"))

    def test_memoire_limitee(self):
        with mock.patch.object(page_tracker, "GARDER", 3):
            d = {f"https://c411.org/torrents/{i:040d}": {"lu": i, "page": {}} for i in range(6)}
            page_tracker._ecrire_cache(d)
            gardees = json.loads(page_tracker.FICHIER.read_text(encoding="utf-8"))
        self.assertEqual(sorted(gardees), [f"https://c411.org/torrents/{i:040d}" for i in (3, 4, 5)])


if __name__ == "__main__":
    unittest.main()
