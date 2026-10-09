"""
Identification des hors-série (HS, Data Book, artbook, one-shot) : on cherche sur AniList et MangaDex, tu choisis
le bon résultat dans la liste, et le titre, l'année et l'auteur sont rangés dans le fichier d'infos de la série
(« .mouflanga-infos.json », clé « hors_series »). Le fichier du hors-série n'est pas renommé.
"""
import logging
import re

import requests

logger = logging.getLogger(__name__)
_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "MouFlanga/2.0 (bibliotheque de mangas personnelle)"
STATUT_ANILIST = {"FINISHED": "terminé", "RELEASING": "en cours"}


def cle(rel: str) -> str:
    """Clé d'un hors-série dans les infos : son chemin relatif à la bibliothèque."""
    return rel


def lire(infos: dict) -> dict:
    """Les identifications déjà faites : {chemin relatif: {titre, annee, auteur, source, lien}}."""
    d = infos.get("hors_series") or {}
    return d if isinstance(d, dict) else {}


def _chercher_anilist(requete: str) -> list[dict]:
    q = ("query($s:String){Page(perPage:6){media(search:$s,type:MANGA,sort:SEARCH_MATCH){id title{romaji english native} "
         "startDate{year} status staff(perPage:2){edges{role node{name{full}}}}}}}")
    r = _SESSION.post("https://graphql.anilist.co", json={"query": q, "variables": {"s": requete}}, timeout=15)
    r.raise_for_status()
    out = []
    for m in ((r.json().get("data") or {}).get("Page") or {}).get("media") or []:
        t = m.get("title") or {}
        auteurs = [e["node"]["name"]["full"] for e in (m.get("staff") or {}).get("edges") or [] if e.get("node")]
        out.append({"titre": t.get("english") or t.get("romaji") or t.get("native") or "?",
                    "annee": (m.get("startDate") or {}).get("year"), "auteur": ", ".join(dict.fromkeys(auteurs)),
                    "source": "AniList", "lien": f"https://anilist.co/manga/{m['id']}",
                    "statut": STATUT_ANILIST.get(m.get("status"), "")})
    return out


def _chercher_mangadex(requete: str) -> list[dict]:
    r = _SESSION.get("https://api.mangadex.org/manga", params={"title": requete, "limit": 6}, timeout=15)
    r.raise_for_status()
    out = []
    for m in r.json().get("data") or []:
        a = m.get("attributes") or {}
        titres = a.get("title") or {}
        out.append({"titre": titres.get("en") or next(iter(titres.values()), "?"), "annee": a.get("year"), "auteur": "",
                    "source": "MangaDex", "lien": f"https://mangadex.org/title/{m['id']}", "statut": ""})
    return out


def _chercher_google(requete: str) -> list[dict]:
    """Google Books (clé réglée dans Réglages → Règles de recherche) : éditions, toutes langues."""
    import tomes
    cle = tomes.cle_google_books()
    if not cle:
        return []
    r = _SESSION.get(tomes.GOOGLE_BOOKS, params={"q": requete, "maxResults": 8, "key": cle}, timeout=15)
    r.raise_for_status()
    out = []
    for it in r.json().get("items") or []:
        v = it.get("volumeInfo") or {}
        titre = v.get("title") or "?"
        if v.get("subtitle"):
            titre = f"{titre} — {v['subtitle']}"
        annee = (v.get("publishedDate") or "")[:4]
        out.append({"titre": titre, "annee": int(annee) if annee.isdigit() else None,
                    "auteur": ", ".join(v.get("authors") or []),
                    "source": "Google Books", "lien": v.get("infoLink") or "",
                    "statut": " · ".join(x for x in (v.get("publisher"), v.get("language")) if x)})
    return out


def candidats(serie: str, titre: str) -> list[dict]:
    """Résultats possibles pour un hors-série : « <série> <titre> » d'abord, puis le titre seul."""
    import tomes
    scenariste = (((tomes._charger(serie) or {}).get("fiche") or {}).get("scenario") or "").split(",")[0].strip()
    requetes = list(dict.fromkeys(x for x in (f"{serie} {scenariste} {titre}".strip(), f"{serie} {titre}".strip(), titre.strip()) if x))
    resultat = []
    for nom, chercher in (("AniList", _chercher_anilist), ("MangaDex", _chercher_mangadex), ("Google Books", _chercher_google)):
        par_source, vus = [], set()
        for requete in requetes:
            try:
                for c in chercher(requete):
                    cle_ = re.sub(r"[\W_]+", "", (c["titre"] or "").lower()) + str(c.get("annee") or "")
                    if cle_ not in vus and len(par_source) < 5:
                        vus.add(cle_)
                        par_source.append(c)
            except Exception as e:
                logger.info("Hors-série : recherche %s impossible : %s", nom, e.__class__.__name__)
        resultat += par_source
    return resultat
