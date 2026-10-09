"""
Identification des hors-série (HS, Data Book, artbook, one-shot) : on cherche sur AniList et MangaDex, tu choisis
le bon résultat dans la liste, et le titre, l'année et l'auteur sont rangés dans le fichier d'infos de la série
(« .mouflanga-infos.json », clé « hors_series »). Le fichier du hors-série n'est pas renommé.
"""
import html as html_lib
import ipaddress
import logging
import re
from urllib.parse import urlparse

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


def _meta(page: str, cle: str) -> str:
    """Contenu d'une balise <meta property|name="cle" content="…"> (les deux ordres d'attributs)."""
    for motif in (r'<meta[^>]+(?:property|name)="%s"[^>]+content="([^"]*)"', r'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="%s"'):
        m = re.search(motif % re.escape(cle), page, re.I)
        if m:
            return html_lib.unescape(m.group(1)).strip()
    return ""


def lire_page_texte(page: str, adresse: str) -> dict:
    """Titre, auteur, année et éditeur d'une page de fiche (balises og: et titre de la page)."""
    titre_page = _meta(page, "og:title")
    if not titre_page:
        m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
        titre_page = html_lib.unescape(m.group(1)).strip() if m else ""
    morceaux = [x.strip() for x in titre_page.split(" | ") if x.strip()]
    principal = morceaux[0] if morceaux else ""
    editeur = _meta(page, "og:site_name") or (morceaux[1] if len(morceaux) > 1 else "")
    auteur = ""
    m = re.search(r",\s*(?:de|by|par)\s+(.+)$", principal, re.I)
    if m:
        auteur = m.group(1).strip()
        principal = principal[:m.start()]
    annee = ""
    m = re.search(r"\b(19\d{2}|20\d{2})\b", principal)
    if m:
        annee = m.group(1)
    titre = re.sub(r"\s*\([^)]*\)", "", principal).strip() or principal
    return {"titre": titre, "annee": int(annee) if annee else None, "auteur": auteur, "editeur": editeur,
            "source": urlparse(adresse).hostname or "Page web", "lien": adresse, "statut": editeur}


def _adresse_permise(adresse: str) -> bool:
    """Seulement une page web publique : pas d'adresse locale ou privée (l'appli ne lit pas le réseau de la maison)."""
    u = urlparse(adresse)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    if u.hostname in ("localhost",) or u.hostname.endswith((".local", ".lan", ".home")):
        return False
    try:
        ip = ipaddress.ip_address(u.hostname)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except ValueError:
        return True


def lire_page(adresse: str) -> dict:
    """Lit une page donnée par l'utilisatrice et en tire les infos ; lève ValueError avec un message clair."""
    if not _adresse_permise(adresse):
        raise ValueError("Cette adresse n'est pas une page web publique (il faut un lien http:// ou https:// normal).")
    try:
        r = _SESSION.get(adresse, timeout=15, headers={"Accept-Language": "fr,en;q=0.8"})
    except requests.RequestException:
        raise ValueError("Le site ne répond pas pour le moment.")
    if r.status_code in (401, 403, 429):
        raise ValueError("Le site refuse la lecture automatique (protection anti-robot). Saisis les infos à la main.")
    if r.status_code >= 400:
        raise ValueError(f"Le site a répondu {r.status_code}.")
    infos = lire_page_texte(r.text, r.url or adresse)
    if not infos["titre"]:
        raise ValueError("Je n'ai pas trouvé de titre sur cette page. Saisis les infos à la main.")
    return infos
