"""Un faux Internet pour essayer toute l'identification sans réseau : AniList, Wikipédia (en et fr), MangaDex, MangaUpdates, BnF et
Google Books répondent avec des réponses réelles (tests/fixtures) ; on peut en faire tomber un, ou tous, ou au hasard."""
import json
import random
import re
from pathlib import Path
from unittest import mock

import requests

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MEDIA_AKAME = {"id": 55132, "title": {"romaji": "Akame ga Kill!", "english": "Akame ga KILL!", "native": "アカメが斬る！"},
               "synonyms": ["Akame ga Kiru!", "Red Eyes Sword"], "status": "FINISHED", "volumes": 15, "chapters": 78, "format": "MANGA",
               "description": "A young fighter joins an assassin group.", "startDate": {"year": 2010, "month": 8},
               "endDate": {"year": 2016, "month": 6}, "genres": ["Action"],
               "staff": {"edges": [{"role": "Story", "node": {"name": {"full": "Takahiro"}}},
                                   {"role": "Art", "node": {"name": {"full": "Tetsuya Tashiro"}}}]}}
GOOGLE_AKAME = {"items": [
    {"volumeInfo": {"title": "Red Eyes Sword - Akame ga Kill ! - Tome 5", "language": "fr", "publisher": "Kurokawa", "publishedDate": "2015",
                    "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9782368520543"}],
                    "description": "Akame et ses compagnons du Night Raid affrontent un nouvel ennemi redoutable dans la capitale impériale."}},
    {"volumeInfo": {"title": "Red Eyes Sword - Akame ga Kill ! Zero - Tome 10", "language": "fr",
                    "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9782368527276"}], "description": "x" * 80}}]}


class Reponse:
    def __init__(self, statut=200, corps=None, texte=None, entetes=None):
        self.status_code = statut
        self.text = texte if texte is not None else json.dumps(corps if corps is not None else {})
        self.headers = entetes or {}

    def json(self):
        return json.loads(self.text)


class FauxInternet:
    """`pannes` : {service: « 503 » | « 429 » | « quota » | « coupe » | « html »} ; `hasard` : probabilité qu'une requête échoue
    (série reproductible avec `graine`). `requetes` : ce qui a été demandé, [(service, url)]."""

    def __init__(self, media=None, wikifr=None, bnf=None, google=None, hasard=0.0, graine=1):
        self.media = media if media is not None else MEDIA_AKAME
        self.wikifr = wikifr if wikifr is not None else (FIXTURES / "wikifr_akame.txt").read_text(encoding="utf-8")
        self.titre_wikifr = "Red Eyes Sword: Akame ga Kill!"
        self.bnf = bnf if bnf is not None else (FIXTURES / "bnf_akame.xml").read_text(encoding="utf-8")
        self.google = google if google is not None else GOOGLE_AKAME
        self.pannes, self.hasard, self.alea = {}, hasard, random.Random(graine)
        self.requetes = []

    # -- les services
    def _panne(self, service):
        mode = self.pannes.get(service)
        if not mode and self.hasard and self.alea.random() < self.hasard:
            mode = self.alea.choice(["503", "coupe", "html", "429"])
        if not mode:
            return None
        if mode == "coupe":
            raise requests.ConnectionError("réseau coupé")
        if mode == "html":
            return Reponse(200, texte="<html>Just a moment...</html>")
        if mode == "quota":
            return Reponse(429, {"error": {"code": 429, "message": "Quota exceeded for limit 'Queries per day'"}})
        return Reponse(int(mode), {"error": "panne simulée"}, entetes={"Retry-After": "120"} if mode == "429" else {})

    def anilist(self, json_):
        v, q = json_.get("variables") or {}, json_.get("query") or ""
        if "staff(" in q and "startDate" in q and "i" in v:                       # fiche détaillée
            return Reponse(200, {"data": {"Media": self.media}})
        if "relations" in q:
            return Reponse(200, {"data": {"Media": {"relations": {"edges": []}}}})
        if "Media(id" in q:
            return Reponse(200, {"data": {"Media": self.media if v.get("i") == self.media["id"] else None}})
        nom = re.sub(r"[^a-z0-9]+", "", (v.get("s") or "").lower())
        titres = [self.media["title"]["romaji"], self.media["title"]["english"], *self.media["synonyms"]]
        ok = any(re.sub(r"[^a-z0-9]+", "", (t or "").lower()) == nom for t in titres)
        return Reponse(200, {"data": {"Page": {"media": [self.media] if ok else []}}})

    def wikipedia_fr(self, p):
        if p.get("list") == "search":
            q = (p.get("srsearch") or "").lower()
            return Reponse(200, {"query": {"search": [{"title": self.titre_wikifr}] if "akame" in q else []}})
        if p.get("action") == "parse":
            ok = p.get("page") == self.titre_wikifr
            return Reponse(200, {"parse": {"title": p.get("page"), "wikitext": {"*": self.wikifr}}} if ok else {"error": {"code": "missingtitle"}})
        if p.get("prop") == "extracts":
            return Reponse(200, {"query": {"pages": [{"extract": "Red Eyes Sword: Akame ga Kill! est un manga de dark fantasy. "
                                                                  "== Synopsis ==\n" + "Tatsumi rejoint le Night Raid. " * 8}]}})
        if p.get("prop") == "links":
            return Reponse(200, {"query": {"pages": {"1": {"links": []}}}})
        return Reponse(200, {})

    def wikipedia_en(self, p):
        if p.get("list") == "search":
            return Reponse(200, {"query": {"search": []}})
        return Reponse(200, {"error": {"code": "missingtitle"}})

    def mangadex(self, url, p):
        if url.endswith("/manga"):
            return Reponse(200, {"data": [{"id": "x", "attributes": {"title": {"en": "Akame ga Kill!"}, "altTitles": [],
                                                                      "links": {"al": "55132"}, "description": {"fr": "Tatsumi " * 20}}}]})
        return Reponse(200, {"volumes": {"1": {"volume": "1", "chapters": {"1": {"chapter": "1"}, "2": {"chapter": "2"}}},
                                         "2": {"volume": "2", "chapters": {"5": {"chapter": "5"}}}}})

    def mangaupdates(self, url):
        if url.endswith("/series/search"):
            return Reponse(200, {"results": [{"record": {"series_id": 9, "title": "Akame ga Kill!"}, "hit_title": "Akame ga Kill!"}]})
        return Reponse(200, {"status": "15 Volumes (Complete)", "publishers": [{"publisher_name": "Kurokawa"}],
                             "authors": [{"name": "Takahiro"}], "description": "Story."})

    # -- l'entrée : les deux méthodes que reseau appelle
    def get(self, url, params=None, **kw):
        return self._repondre("GET", url, params or {}, None)

    def post(self, url, json=None, **kw):
        return self._repondre("POST", url, {}, json or {})

    def _repondre(self, methode, url, params, corps):
        service = {"graphql.anilist.co": "anilist", "fr.wikipedia.org": "wikipedia", "en.wikipedia.org": "wikipedia",
                   "api.mangadex.org": "mangadex", "api.mangaupdates.com": "mangaupdates", "catalogue.bnf.fr": "bnf",
                   "www.googleapis.com": "google"}.get(re.sub(r"^https?://([^/]+).*", r"\1", url), "web")
        self.requetes.append((service, url))
        r = self._panne(service)
        if r is not None:
            return r
        if service == "anilist":
            return self.anilist(corps)
        if service == "wikipedia":
            return self.wikipedia_fr(params) if "fr.wikipedia" in url else self.wikipedia_en(params)
        if service == "mangadex":
            return self.mangadex(url, params)
        if service == "mangaupdates":
            return self.mangaupdates(url)
        if service == "bnf":
            return Reponse(200, texte=self.bnf)
        if service == "google":
            return Reponse(200, self.google)
        return Reponse(404, {})

    def installer(self):
        """Contexte : toutes les requêtes de reseau.py vont au faux Internet."""
        from contextlib import ExitStack

        import reseau
        pile = ExitStack()
        pile.enter_context(mock.patch.object(reseau.SESSION, "get", side_effect=self.get))
        pile.enter_context(mock.patch.object(reseau.SESSION, "post", side_effect=self.post))
        reseau.oublier_tout()
        pile.callback(reseau.oublier_tout)
        return pile
