"""Le parcours d'identification de bout en bout, avec un faux Internet : trouvé / rien trouvé / panne ne se confondent jamais, et une
recherche (même forcée, même quand tout tombe en panne ou que Google a atteint son quota) n'efface JAMAIS ce qu'on savait."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import identification as I  # noqa: E402
import notices  # noqa: E402
import reseau  # noqa: E402
import tomes  # noqa: E402
from faux_internet import FauxInternet, Reponse  # noqa: E402

SERIE = "Akame ga Kill !"


def faits(cache: dict) -> dict:
    """Les informations utiles d'un cache, en feuilles simples : ce qu'une recherche ne doit jamais faire disparaître."""
    f = {}
    st = cache.get("statut_officiel") or {}
    for k in ("statut", "volumes", "anilist", "resume", "resume_langue", "titre"):
        if st.get(k):
            f[f"statut.{k}"] = st[k]
    for n, t in (cache.get("tomes") or {}).items():
        f[f"tomes.{n}"] = t
    for v, d in ((cache.get("titres_tomes") or {}).get("details") or {}).items():
        for k in ("isbn", "titre", "resume", "sortie", "chapitres", "numeros"):
            if d.get(k):
                f[f"liste.{v}.{k}"] = json.dumps(d[k])
    for t, par in (cache.get("notices") or {}).items():
        for s, o in par.items():
            for k in ("isbn", "resume"):
                if o.get(k):
                    f[f"notices.{t}.{s}.{k}"] = o[k]
    fi = cache.get("fiche") or {}
    for k in ("genres", "editeur_fr", "scenario", "dessin", "debut", "wikipedia", "mangaupdates"):
        if fi.get(k):
            f[f"fiche.{k}"] = fi[k]
    return f


class ParcoursTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(tomes, "DOSSIER", Path(self.tmp.name)),
                        mock.patch.object(tomes, "SERIES_EXISTANTES", lambda: [SERIE]),
                        mock.patch.dict(os.environ, {"GOOGLE_BOOKS_API_KEY": "CLE" * 10}),
                        mock.patch.object(I, "CONTEXTE", lambda s: {"tomes": {1, 10, 11}, "edition": "", "edition_differente": False})]
        for p in self.patches:
            p.start()
        tomes._CACHE_FICHES.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        tomes._CACHE_FICHES.clear()
        self.tmp.cleanup()

    def cache(self):
        return json.loads(tomes._fichier(SERIE).read_text(encoding="utf-8"))

    def lancer(self, faux, **kw):
        with faux.installer():
            return I.identifier(SERIE, **kw)

    # ------------------------------------------------------------------ le cas normal
    def test_parcours_normal(self):
        faux = FauxInternet()
        b = self.lancer(faux)
        self.assertEqual({k: v.etat for k, v in b.items()}, {"statut": "ok", "liste_fr": "ok", "tomes": "ok", "fiche": "ok", "notices": "ok"})
        c = self.cache()
        self.assertEqual(c["statut_officiel"]["anilist"], 55132)
        self.assertIn("Red Eyes Sword", c["statut_officiel"]["synonymes"])
        self.assertEqual(c["statut_officiel"]["resume_langue"], "fr")                    # MangaDex en français
        d = c["titres_tomes"]["details"]
        self.assertEqual(d["1"]["isbn"], "9782368520444")                                # ISBN français de la liste de Wikipédia
        self.assertEqual(d["1"]["chapitres"][0], "1. Les ténèbres")
        self.assertIn("Les ténèbres", " ".join(d["1"]["chapitres"]))
        # ISBN : deux sources d'accord (Wikipédia + BnF) pour le tome 1 ; la BnF seule pour les tomes 10 et 11
        self.assertEqual(notices.isbn_details(SERIE, 1)["sources"], ["Wikipédia", "BnF"])
        self.assertEqual(notices.isbn_details(SERIE, 11)["isbn"], "9782368522455")
        texte, source = notices.resume_du_tome(SERIE, 10)
        self.assertEqual(source, "BnF")
        self.assertIn("Après avoir survécu", texte)
        self.assertEqual(b["notices"].extra["isbn_manquants"], [])
        self.assertFalse(b["notices"].extra["attente"])
        self.assertTrue(all(c["recherches"][k]["etat"] == "ok" for k in ("statut", "liste_fr", "tomes", "fiche", "notices")))

    def test_deuxieme_passage_ne_refait_rien(self):
        self.lancer(FauxInternet())
        faux = FauxInternet()
        b = self.lancer(faux)
        self.assertEqual([k for k, v in b.items() if v.etat not in ("deja", "ok")], [])
        self.assertEqual(faux.requetes, [])                                               # rien à demander à Internet

    def test_zero_ne_prend_pas_la_page_de_la_serie_principale(self):
        with mock.patch.object(tomes, "SERIES_EXISTANTES", lambda: [SERIE, "Akame ga Kill ! : Zero"]):
            with mock.patch.object(I, "CONTEXTE", lambda s: {"tomes": {1, 2, 4}, "edition": "", "edition_differente": False}):
                faux = FauxInternet(media=dict(__import__("faux_internet").MEDIA_AKAME, id=85400, title={"romaji": "Akame ga Kill! Zero",
                                                                                                         "english": "Akame ga KILL! ZERO", "native": ""},
                                               synonyms=["Red Eyes Sword Zero"]))
                with faux.installer():
                    tomes.titres_tomes_bilan("Akame ga Kill ! : Zero")
        d = json.loads(tomes._fichier("Akame ga Kill ! : Zero").read_text(encoding="utf-8"))["titres_tomes"]["details"]
        self.assertNotEqual(d["1"]["isbn"], "9782368520444")                              # pas le tome 1 de la série principale

    # ------------------------------------------------------------------ les pannes : jamais « rien trouvé », jamais de perte
    def test_tout_tombe_en_panne_rien_n_est_perdu(self):
        self.lancer(FauxInternet())
        avant = faits(self.cache())
        self.assertGreater(len(avant), 20)
        faux = FauxInternet()
        faux.pannes = {s: "coupe" for s in ("anilist", "wikipedia", "mangadex", "mangaupdates", "bnf", "google")}
        b = self.lancer(faux, forcer=True)
        apres = faits(self.cache())
        self.assertEqual({k: v for k, v in avant.items() if apres.get(k) != v}, {})
        self.assertTrue(all(v.etat in ("panne", "partiel", "echec") for v in b.values()), {k: v.etat for k, v in b.items()})
        self.assertTrue(all(v.prochain and v.prochain > time.time() for v in b.values()))
        self.assertIn(SERIE, I.a_reprendre([SERIE], maintenant=time.time() + 7200))       # sera reprise toute seule

    def test_chaque_service_en_panne_a_son_tour(self):
        self.lancer(FauxInternet())
        avant = faits(self.cache())
        for service in ("anilist", "wikipedia", "mangadex", "mangaupdates", "bnf", "google"):
            for mode in ("503", "429", "html", "quota"):
                faux = FauxInternet()
                faux.pannes = {service: mode}
                self.lancer(faux, forcer=True)
                apres = faits(self.cache())
                self.assertEqual({k: v for k, v in avant.items() if apres.get(k) != v}, {}, f"{service} {mode}")

    def test_quota_google_les_autres_sources_servent_et_la_reprise_est_annoncee(self):
        faux = FauxInternet()
        faux.pannes = {"google": "quota"}
        b = self.lancer(faux)
        n = b["notices"]
        self.assertEqual(n.etat, "partiel")
        self.assertIn("Google Books n'a pas répondu", n.detail)
        self.assertIn("nouvel essai", n.detail)
        self.assertGreater(n.prochain, time.time())
        self.assertTrue(n.extra["attente"])                                               # pas de lecture des pages en attendant
        self.assertEqual(notices.isbn_details(SERIE, 11)["isbn"], "9782368522455")        # la BnF a quand même répondu

    def test_apres_la_panne_la_reprise_complete(self):
        faux = FauxInternet()
        faux.pannes = {"bnf": "coupe", "google": "quota"}
        b = self.lancer(faux)
        self.assertEqual(b["notices"].extra["isbn_manquants"], [10, 11])                  # tome 1 : Wikipédia
        reseau.oublier_tout()
        b = self.lancer(FauxInternet())
        self.assertEqual(b["notices"].extra["isbn_manquants"], [])
        self.assertEqual(b["notices"].etat, "ok")

    def test_rien_trouve_n_est_pas_une_panne(self):
        faux = FauxInternet(bnf=(Path(__file__).resolve().parent / "fixtures" / "bnf_air_gear.xml").read_text(encoding="utf-8"),
                            google={"items": []})
        b = self.lancer(faux)
        self.assertEqual(b["notices"].etat, "ok")                                         # Wikipédia a donné l'ISBN du tome 1
        self.assertFalse(b["notices"].extra["attente"])
        self.assertEqual(b["notices"].extra["isbn_manquants"], [10, 11])                  # Internet a répondu partout : pages en dernier recours

    # ------------------------------------------------------------------ l'invariant, au hasard
    def test_pannes_au_hasard_ne_font_jamais_rien_perdre(self):
        self.lancer(FauxInternet())
        avant = faits(self.cache())
        for graine in range(1, 25):
            reseau.oublier_tout()
            faux = FauxInternet(hasard=0.45, graine=graine)
            with faux.installer():
                try:
                    I.identifier(SERIE, forcer=True)
                except Exception as e:                                                    # une étape qui plante est notée, jamais propagée
                    self.fail(f"graine {graine} : {e!r}")
            apres = faits(self.cache())
            perdu = {k: v for k, v in avant.items() if apres.get(k) != v}
            self.assertEqual(perdu, {}, f"graine {graine}")

    def test_ecritures_simultanees_ne_s_ecrasent_pas(self):
        import threading
        self.lancer(FauxInternet())
        erreurs = []

        def ecrire(i):
            try:
                for k in range(15):
                    tomes.modifier(SERIE, lambda b, i=i, k=k: b.setdefault("essai", {}).__setitem__(f"{i}-{k}", 1))
            except Exception as e:
                erreurs.append(e)
        fils = [threading.Thread(target=ecrire, args=(i,)) for i in range(6)]
        [f.start() for f in fils]
        [f.join() for f in fils]
        self.assertEqual((erreurs, len(self.cache()["essai"])), ([], 90))


if __name__ == "__main__":
    unittest.main()
