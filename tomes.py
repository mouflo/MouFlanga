"""
Répartition des chapitres d'une série en tomes, cherchée automatiquement sur Internet.

Sources, dans l'ordre :
1. Wikipédia (en anglais) : les pages « List of <série> chapters » donnent, pour chaque tome, les numéros
   de chapitres et leurs titres, et les chapitres « pas encore sortis en tome » ;
2. MangaDex (API publique) : en secours, la répartition connue de sa communauté.
Le nom anglais de la série est trouvé avec AniList quand le nom français ne suffit pas.

Résultat gardé dans data/tomes/<série>.json (3 jours), pour ne pas interroger Internet à chaque fois.
"""
import json
import logging
import re
import time
import unicodedata
from pathlib import Path

import requests

logger = logging.getLogger(__name__)
DOSSIER = Path(__file__).resolve().parent / "data" / "tomes"
DUREE = 3 * 86400
_SESSION = requests.Session()
# Wikipédia demande un nom d'outil et un moyen de le retrouver (règles d'usage de son API)
_SESSION.headers["User-Agent"] = "MouFlanga/1.0 (https://github.com/mouflo/MouFlanga; bibliotheque de mangas personnelle)"
WIKI = "https://en.wikipedia.org/w/api.php"


def _simple(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", texte).strip()


SERIES_EXISTANTES = lambda: ()               # noms des séries de la bibliothèque (rempli par app.py)


def _variantes(titre: str) -> list[str]:
    """Le nom tel quel, puis quelques écritures courantes (« N°8 » → « No. 8 »)."""
    out = [titre.strip()]
    v = re.sub(r"\s*n[°º]\s*", " No. ", titre, flags=re.I).strip()
    if v not in out:
        out.append(re.sub(r"\s+", " ", v))
    if " : " in titre:                          # « Frieren : Sousou no Frieren » → chaque partie (la plus longue d'abord)
        autres = {_simple(x) for x in SERIES_EXISTANTES() if x != titre}
        for part in sorted((x.strip() for x in titre.split(" : ")), key=len, reverse=True):
            if part and part not in out and _simple(part) not in autres and (len(part.split()) >= 2 or len(part) >= 6):   # « Frieren » oui, « Zero » tout seul non
                out.append(part)
    return out


def _noms_anglais(titre: str) -> list[str]:
    """Noms anglais / romaji de la série d'après AniList."""
    q = "query($s:String){Page(perPage:3){media(search:$s,type:MANGA,format_not:NOVEL){title{romaji english} synonyms}}}"
    noms = []
    for v in _variantes(titre):
        try:
            r = _SESSION.post("https://graphql.anilist.co", json={"query": q, "variables": {"s": v}}, timeout=15)
            medias = r.json()["data"]["Page"]["media"]
        except Exception as e:
            logger.info("AniList injoignable (%s)", e.__class__.__name__)
            return noms
        if medias:
            t = medias[0]["title"]
            for n in (t.get("english"), t.get("romaji")):
                if n and n not in noms:
                    noms.append(n)
            break
    return noms


# ---------------------------------------------------------------- Wikipédia

class TropDeRequetes(Exception):
    pass


def _wiki(params: dict) -> dict:
    """Une requête à Wikipédia ; si elle demande de ralentir (429), on attend une fois puis on abandonne."""
    for essai in range(2):
        r = _SESSION.get(WIKI, params={**params, "format": "json", "formatversion": 2, "maxlag": 5}, timeout=20)
        if r.status_code == 429 or "maxlag" in r.text[:200]:
            if essai == 0:
                try:
                    attente = min(30, int(r.headers.get("Retry-After", "10")))
                except ValueError:
                    attente = 10
                time.sleep(attente)
                continue
            raise TropDeRequetes("Wikipédia demande de patienter")
        r.raise_for_status()
        time.sleep(0.5)                   # requêtes espacées, comme le demande Wikipédia
        return r.json()
    return {}


def _pages_wiki(noms: list[str]) -> list[str]:
    """Pages Wikipédia de la liste des chapitres (une ou plusieurs pour les longues séries)."""
    for nom in noms:
        motif = re.compile(r"^lists? of " + re.escape(_simple(nom)) + r" chapters", re.I)
        res = _wiki({"action": "query", "list": "search", "srsearch": f"List of {nom} chapters", "srlimit": 20})
        titres = [x["title"] for x in res.get("query", {}).get("search", [])]
        pages = [t for t in titres if motif.match(_simple(t).replace(" s chapters", " chapters")) and not t.lower().startswith("lists of")]
        if pages:
            return pages
        # Série courte : la liste des tomes est dans l'article principal
        principal = [t for t in titres if _simple(t) == _simple(nom)]
        if principal:
            return principal
    return []


def _items(bloc: str) -> list[str]:
    """Éléments d'un {{Numbered list|…}} (un par ligne commençant par « | »)."""
    items, profondeur = [], 0
    for ligne in bloc.splitlines()[1:]:
        if profondeur == 0 and ligne.strip().startswith("}}"):
            break
        if profondeur == 0 and ligne.lstrip().startswith("|") and not re.match(r"\s*\|\s*start\s*=", ligne):
            items.append(ligne)
        profondeur += ligne.count("{{") - ligne.count("}}")
        profondeur = max(profondeur, 0)
    return items


def _titre_item(item: str) -> str:
    m = re.search(r'"([^"]+)"', item)
    t = m.group(1) if m else ""
    return re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", t).replace("''", "").strip()


def _lire_listes(texte: str, tome, tomes: dict, titres: dict):
    """Mises en page rencontrées sur Wikipédia :
    {{Numbered list|start=N | … }} ; « *12. "Titre" » ou « *Days 12: … » ; « * Chapter: 1–7 » (plage sans titres) ;
    « # "Titre" » (liste numérotée implicite : on continue après le dernier chapitre connu)."""
    def noter(n, item=""):
        if tome is not None or n not in tomes:
            tomes[n] = tome
        t = _titre_item(item)
        if t:
            titres.setdefault(n, t)
    trouve = False
    for m in re.finditer(r"\{\{\s*Numbered list\s*\|\s*start\s*=\s*(\d+)", texte, re.I):
        trouve = True
        debut = int(m.group(1))
        for k, item in enumerate(_items(texte[m.start():])):
            noter(float(debut + k), item)
    for m in re.finditer(r"^\*\s*(?:[A-Za-z][A-Za-z ]{0,14}?\s*)?(\d+(?:\.\d+)?)\s*[.:)]\s*(.*)$", texte, re.M):
        trouve = True
        noter(float(m.group(1)), m.group(2))
    for m in re.finditer(r"^\*\s*Chapters?\s*:?\s*(\d+)\s*(?:[–—-]\s*(\d+))?\s*$", texte, re.M | re.I):
        trouve = True
        for n in range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1):
            noter(float(n))
    if not trouve:
        lignes = re.findall(r"^#\s*(.+)$", texte, re.M)
        suivant = int(max([n for n in tomes if n == int(n)], default=0)) + 1
        for k, item in enumerate(lignes):
            noter(float(suivant + k), item)


def _wikipedia(noms: list[str]) -> dict | None:
    pages = _pages_wiki(noms)
    if not pages:
        return None
    tomes, titres = {}, {}
    for page in pages:
        texte = _wiki({"action": "parse", "page": page, "prop": "wikitext", "redirects": 1}).get("parse", {}).get("wikitext", "")
        texte = re.sub(r"<!--.*?-->", "", texte, flags=re.S)       # tomes « en préparation » cachés en commentaire
        blocs = re.split(r"\{\{\s*Graphic novel list", texte)
        for bloc in blocs[1:]:
            vol = re.search(r"\|\s*VolumeNumber\s*=\s*(\d+)", bloc)
            if not vol:
                continue
            fin = re.search(r"\n={2,}\s*[^=\s]", bloc)   # le bloc s'arrête au titre de section suivant
            _lire_listes(bloc[:fin.start()] if fin else bloc, int(vol.group(1)), tomes, titres)
        hors = re.search(r"=+\s*Chapters not yet in[^\n]*\n(.*?)(\n={2,}\s*[^=\s]|\Z)", texte, re.S | re.I)
        if hors:
            _lire_listes(hors.group(1), None, tomes, titres)
    if not any(v is not None for v in tomes.values()):
        return None
    return {"source": "Wikipédia (" + ", ".join(pages) + ")", "tomes": tomes, "titres": titres}


# ---------------------------------------------------------------- MangaDex

def _mangadex(noms: list[str]) -> dict | None:
    for nom in noms:
        try:
            r = _SESSION.get("https://api.mangadex.org/manga", params={"title": nom, "limit": 5}, timeout=15).json()
            if not r.get("data"):
                continue
            def titres_md(d):                       # titre principal et autres titres de la fiche MangaDex
                a = d.get("attributes") or {}
                return [*(a.get("title") or {}).values(), *(v for x in a.get("altTitles") or [] for v in x.values())]
            # « Akame ga Kill! Zero » : la fiche au titre identique, pas la série principale renvoyée en premier
            ident = next((d["id"] for d in r["data"] if any(_simple(t) == _simple(nom) for t in titres_md(d))), r["data"][0]["id"])
            ag = _SESSION.get(f"https://api.mangadex.org/manga/{ident}/aggregate", timeout=20).json()
        except Exception as e:
            logger.info("MangaDex injoignable (%s)", e.__class__.__name__)
            return None
        tomes = {}
        vols = ag.get("volumes") or {}
        # MangaDex renvoie un objet {"1": {...}} ou, parfois, une liste [{"volume": "1", "chapters": ...}]
        for d in (vols.values() if isinstance(vols, dict) else vols):
            if not isinstance(d, dict):
                continue
            vol = str(d.get("volume") or "none")
            chs = d.get("chapters") or {}
            for c in (chs.values() if isinstance(chs, dict) else chs):
                ch = c.get("chapter") if isinstance(c, dict) else c
                try:
                    tomes[float(ch)] = int(float(vol)) if vol not in ("none", "") else None
                except (TypeError, ValueError):
                    continue
        if any(v is not None for v in tomes.values()):
            return {"source": "MangaDex", "tomes": tomes, "titres": {}}
    return None


# ---------------------------------------------------------------- Interface

def _fichier(serie: str) -> Path:
    return DOSSIER / (re.sub(r"[^\w.-]+", "_", serie).strip("_")[:100] + ".json")


def _enregistrer(serie: str, info: dict):
    DOSSIER.mkdir(parents=True, exist_ok=True)
    donnees = {"date": time.time(), "source": info.get("source"),
               "tomes": {str(k): v for k, v in info.get("tomes", {}).items()},
               "titres": {str(k): v for k, v in info.get("titres", {}).items()}}
    try:                                                   # garder le statut officiel déjà connu
        ancien = json.loads(_fichier(serie).read_text(encoding="utf-8"))
        if ancien.get("statut_officiel"):
            donnees["statut_officiel"] = ancien["statut_officiel"]
    except (OSError, ValueError):
        pass
    tmp = _fichier(serie).with_suffix(".tmp")
    tmp.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_fichier(serie))


def oublier(serie: str):
    """Efface le cache d'identification d'une série : la prochaine consultation refait la recherche."""
    _fichier(serie).unlink(missing_ok=True)


def _charger(serie: str) -> dict | None:
    try:
        d = json.loads(_fichier(serie).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    d["tomes"] = {float(k): v for k, v in d.get("tomes", {}).items()}
    d["titres"] = {float(k): v for k, v in d.get("titres", {}).items()}
    return d


def chercher(serie: str, forcer: bool = False) -> dict | None:
    """Répartition des tomes de la série : {"source", "tomes": {n° chapitre: tome ou None}, "titres": {n°: titre}}.
    None si aucune source ne la connaît (les chapitres restent alors un fichier chacun)."""
    garde = _charger(serie)
    if garde and not forcer and time.time() - garde.get("date", 0) < DUREE:
        return garde if garde.get("tomes") else None
    st = (_charger(serie) or {}).get("statut_officiel") or {}
    noms = list(dict.fromkeys([x for x in (st.get("titre"), st.get("titre_en")) if x] + _variantes(serie)))   # titre AniList d'abord
    try:
        info = _wikipedia(noms)
        if info is None:
            anglais = [n for n in _noms_anglais(serie) if n not in noms]
            info = _wikipedia(anglais) if anglais else None
            noms += anglais
        dex = _mangadex(noms)
    except Exception as e:
        logger.warning("Recherche des tomes impossible pour %s : %s", serie, e)
        return garde if garde and garde.get("tomes") else None
    if info is None:
        info = dex
    elif dex:
        # MangaDex complète les chapitres que Wikipédia ne range pas (bonus, chapitres « .5 »)
        for n, t in dex["tomes"].items():
            info["tomes"].setdefault(n, t)
    _enregistrer(serie, info or {"source": None})
    if info:
        logger.info("Tomes de %s : %d tome(s), %d chapitre(s) rangés (%s)", serie,
                    len({t for t in info["tomes"].values() if t is not None}), len(info["tomes"]), info["source"])
    else:
        logger.info("Tomes de %s : aucune source ne les connaît", serie)
    return info


def tome_de(num: float, info: dict | None):
    """Tome d'un chapitre (None : pas encore sorti en tome). Un chapitre « 12.5 » suit le tome du 12."""
    if not info or num is None:
        return None
    tomes = info["tomes"]
    if num in tomes:
        return tomes[num]
    entier = float(int(num))
    if entier in tomes and tomes[entier] is not None:
        return tomes[entier]
    return None


# ---------------------------------------------------------------- Statut officiel (fini / en cours)

STATUT_DUREE = 7 * 86400


def _choisir(medias, serie, tome_max):
    """Parmi les résultats AniList, celui qui correspond le mieux : même titre, puis nombre de tomes compatible
    avec ce qu'on a (« Kenichi » 61 tomes → « Shijou Saikyou no Deshi Kenichi », pas « Kenichi Tantei Chou »)."""
    cles = [c for c in {_simple(serie), *(_simple(x) for x in serie.split(" : "))} if c]
    def note(m):
        titres = [_simple(t) for t in (m["title"].get("romaji"), m["title"].get("english")) if t] + [_simple(x) for x in m.get("synonyms") or []]
        exact = any(c in titres for c in cles)
        contient = any(c in t for c in cles for t in titres)
        vol = m.get("volumes")
        assez = not (tome_max and vol and vol < tome_max)        # 1 tome alors qu'on en a 14 : pas la bonne série
        compatible = bool(tome_max and vol and vol >= tome_max)
        proche = -abs((vol or 0) - (tome_max or 0)) if tome_max and vol else -999
        return (assez, exact, compatible, contient, m.get("format") == "MANGA", proche)
    return max(medias, key=note) if medias else None


def _texte_propre(t):
    t = re.sub(r"<br\s*/?>", "\n", t or "", flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)              # liens au format [texte](adresse)
    t = re.sub(r"\(Source:[^)]*\)|\n---.*$", "", t, flags=re.S | re.I)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _resume(m, serie=""):
    """Résumé de la série : en français d'après MangaDex (même série, reconnue par l'identifiant AniList),
    sinon en anglais d'après AniList. → (texte, langue « fr » ou « en »)."""
    titre = m["title"].get("romaji") or m["title"].get("english") or ""
    try:
        r = _SESSION.get("https://api.mangadex.org/manga", params={"title": titre, "limit": 10}, timeout=15).json()
        for d in r.get("data", []):
            a = d.get("attributes", {})
            if str((a.get("links") or {}).get("al", "")) == str(m.get("id")):
                desc = a.get("description") or {}
                if desc.get("fr"):
                    return _texte_propre(desc["fr"]), "fr"
                break
    except Exception:
        pass
    fr = _wikipedia_fr(m, serie)
    if fr:
        return fr, "fr"
    return _texte_propre(m.get("description") or ""), ("en" if m.get("description") else "")


def page_correspond(page: str, noms) -> bool:
    """La page Wikipédia est-elle bien celle de la série ? Tous les mots d'un des noms doivent figurer dans son titre
    (« Arago » → « Arago (manga) » oui ; « Akame ga Kill! Zero » → « Red Eyes Sword: Akame ga Kill! » non : c'est la
    série principale). Les parties d'un nom « Série : Suite » comptent, sauf celle qui est une autre série de la bibliothèque."""
    mots_page = set(_simple(page).split())
    autres = {_simple(x) for x in SERIES_EXISTANTES()}
    candidats = []
    for n in [x for x in noms if x]:
        candidats.append(n)
        if " : " in n:
            candidats += [x for x in n.split(" : ") if _simple(x) and _simple(x) not in autres]
    return any(_simple(c).split() and set(_simple(c).split()) <= mots_page for c in candidats)


def _wikipedia_fr(m, serie=""):
    """Introduction de l'article Wikipédia en français sur la série (si c'est bien un article de manga). Le nom du dossier
    (souvent le titre français : « Arago ») passe avant les titres d'AniList (« AR∀GO »)."""
    for titre in list(dict.fromkeys(t for t in (serie, m["title"].get("romaji"), m["title"].get("english")) if t and _simple(t))):
        try:
            r = _SESSION.get("https://fr.wikipedia.org/w/api.php", params={
                "action": "query", "list": "search", "srsearch": f"{titre} manga", "srlimit": 3,
                "format": "json", "formatversion": 2}, timeout=15).json()
            for res in r.get("query", {}).get("search", []):
                if not page_correspond(res["title"], [titre, serie]):
                    continue
                d = _SESSION.get("https://fr.wikipedia.org/w/api.php", params={
                    "action": "query", "prop": "extracts", "explaintext": 1, "titles": res["title"],
                    "format": "json", "formatversion": 2}, timeout=15).json()
                texte = ((d.get("query", {}).get("pages") or [{}])[0].get("extract") or "")
                if "manga" not in texte[:1500].lower():
                    continue
                # La section « Synopsis » (l'histoire) plutôt que l'introduction (auteur, magazine…)
                m_syn = re.search(r"\n==+\s*(Synopsis|Histoire|Résumé|Intrigue|Scénario|Univers et synopsis)\s*==+\n(.*?)(?=\n==[^=]|\Z)",
                                  texte, re.S | re.I)
                if m_syn:
                    corps = re.sub(r"\n===+[^=]+===+\n", "\n", m_syn.group(2)).strip()
                    if len(corps) > 80:
                        return corps[:1500].rsplit(" ", 1)[0] + ("…" if len(corps) > 1500 else "")
                intro = texte.split("\n==", 1)[0].strip()
                if len(intro) > 80:
                    return intro
            time.sleep(0.5)
        except Exception:
            continue
    return ""


def statut_officiel(serie: str, tome_max=None, forcer=False) -> dict | None:
    """{"statut": FINISHED | RELEASING | HIATUS | CANCELLED | NOT_YET_RELEASED, "volumes", "chapitres", "titre"}
    d'après AniList, gardé 7 jours dans data/tomes/<série>.json ; None si inconnu."""
    garde = _charger(serie) or {}
    st = garde.get("statut_officiel")
    if st and "resume" in st and not forcer and time.time() - st.get("date", 0) < STATUT_DUREE:
        return st if st.get("statut") else None
    q = ("query($s:String){Page(perPage:6){media(search:$s,type:MANGA,format_not:NOVEL)"
         "{id title{romaji english} synonyms status volumes chapters format description(asHtml:false)}}}")
    medias = []
    for v in _variantes(serie):
        try:
            r = _SESSION.post("https://graphql.anilist.co", json={"query": q, "variables": {"s": v}}, timeout=15)
            if r.status_code == 429:
                return None                                    # trop de demandes : on réessaiera plus tard
            medias = r.json()["data"]["Page"]["media"]
        except Exception as e:
            logger.info("AniList injoignable (%s)", e.__class__.__name__)
            return None
        if medias:
            break
    m = _choisir(medias, serie, tome_max)
    st = {"date": time.time(), "statut": m["status"] if m else None, "volumes": m.get("volumes") if m else None,
          "chapitres": m.get("chapters") if m else None,
          "titre": (m["title"].get("romaji") or m["title"].get("english")) if m else None,
          "titre_en": m["title"].get("english") if m else None, "anilist": m.get("id") if m else None}
    st["resume"], st["resume_langue"] = _resume(m, serie) if m else ("", "")
    # enregistrement à côté de la répartition des tomes (même fichier)
    DOSSIER.mkdir(parents=True, exist_ok=True)
    try:
        brut = json.loads(_fichier(serie).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        brut = {}
    brut["statut_officiel"] = st
    tmp = _fichier(serie).with_suffix(".tmp")
    tmp.write_text(json.dumps(brut, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_fichier(serie))
    return st if st["statut"] else None


# ---------------------------------------------------------------- Fiche détaillée (bouton ℹ️)

FICHE_DUREE = 30 * 86400
_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
_GENRES = {"Action": "action", "Adventure": "aventure", "Comedy": "comédie", "Drama": "drame", "Fantasy": "fantasy",
           "Horror": "horreur", "Mystery": "mystère", "Psychological": "psychologique", "Romance": "romance",
           "Sci-Fi": "science-fiction", "Slice of Life": "tranche de vie", "Sports": "sport", "Supernatural": "surnaturel",
           "Thriller": "thriller", "Mecha": "mecha", "Music": "musique", "Ecchi": "ecchi", "Mahou Shoujo": "magical girl"}


def _infobox(titre_page: str) -> dict:
    """Champs utiles de l'infobox Wikipédia (première occurrence = partie manga)."""
    r = _SESSION.get("https://fr.wikipedia.org/w/api.php", params={"action": "parse", "page": titre_page, "prop": "wikitext",
                                                                     "format": "json", "redirects": 1}, timeout=15).json()
    w = r.get("parse", {}).get("wikitext", {}).get("*", "")
    out = {}
    for cle in ("auteur", "scénariste", "dessinateur", "genre", "éditeur", "éditeur_francophone", "prépublication"):
        m = re.search(r"^[ \t]*\|[ \t]*" + cle + r"[ \t]*=[ \t]*(.+)$", w, re.M)      # jamais la ligne suivante
        if m:
            v = re.sub(r"\{\{[^}]*\}\}|<ref.*?(</ref>|/>)|<[^>]+>", "", m.group(1))
            v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", v).strip(" ,")
            if v:
                out[cle] = v
    return out


def _page_wikipedia(titres) -> str:
    for titre in [t for t in titres if t]:
        try:
            r = _SESSION.get("https://fr.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "srsearch": f"{titre} manga",
                                                                             "srlimit": 3, "format": "json", "formatversion": 2}, timeout=15).json()
            for res in r.get("query", {}).get("search", []):
                if page_correspond(res["title"], titres):
                    return res["title"]
        except Exception:
            continue
    return ""


# ---------------------------------------------------------------- Sources complémentaires (ré-identification)

GOOGLE_BOOKS = "https://www.googleapis.com/books/v1/volumes"


def cle_google_books() -> str:
    """Clé API Google Books (Réglages → 📏 Règles de recherche), lue à chaque appel."""
    import os
    return os.getenv("GOOGLE_BOOKS_API_KEY", "").strip()


def _mangaupdates(titres: list[str]) -> dict | None:
    """MangaUpdates (sans clé) : éditeurs (originaux, anglais…), auteurs et nombre de volumes d'après sa fiche."""
    for titre in dict.fromkeys(t for t in titres if t):
        try:
            r = _SESSION.post("https://api.mangaupdates.com/v1/series/search", json={"search": titre, "perpage": 5}, timeout=15).json()
            trouves = r.get("results") or []
            if not trouves:
                continue
            ident = next((x["record"]["series_id"] for x in trouves if _simple(x["record"].get("title") or "") == _simple(titre)),
                         trouves[0]["record"]["series_id"])
            d = _SESSION.get(f"https://api.mangaupdates.com/v1/series/{ident}", timeout=15).json()
        except Exception as e:
            logger.info("MangaUpdates pour %s : %s", titre, e.__class__.__name__)
            continue
        vol = re.search(r"(\d+)\s*Volumes?", d.get("status") or "", re.I)
        return {"id": ident, "editeurs": [p.get("publisher_name") for p in d.get("publishers") or [] if p.get("publisher_name")],
                "auteurs": list(dict.fromkeys(a.get("name") for a in (d.get("authors") or []) if a.get("name"))),
                "volumes": int(vol.group(1)) if vol else None}
    return None


def _google_books(titre: str) -> dict | None:
    """Google Books (clé requise) : éditeur et auteur d'une édition française, et le plus grand numéro de tome trouvé."""
    cle = cle_google_books()
    if not cle or not titre:
        return None
    try:
        r = _SESSION.get(GOOGLE_BOOKS, params={"q": f"{titre} tome", "langRestrict": "fr", "maxResults": 40, "key": cle}, timeout=15)
        if r.status_code != 200:
            logger.info("Google Books : réponse %s", r.status_code)
            return None
        items = r.json().get("items") or []
    except Exception as e:
        logger.info("Google Books pour %s : %s", titre, e.__class__.__name__)
        return None
    tomes, editeur, auteurs = [], "", []
    for it in items:
        v = it.get("volumeInfo") or {}
        if _simple(titre) not in _simple(v.get("title") or ""):
            continue
        m = re.search(r"\b(?:tome|t|vol\.?|band)\s*0*(\d{1,3})\b", v.get("title") or "", re.I)
        if m:
            tomes.append(int(m.group(1)))
        editeur = editeur or v.get("publisher") or ""
        auteurs = auteurs or v.get("authors") or []
    return {"editeur": editeur, "auteurs": ", ".join(auteurs), "tomes": max(tomes) if tomes else None}


def verifier_cle_google(cle: str) -> tuple[bool, str]:
    """(ok, message) : Google accepte-t-il la clé pour l'API Books ? Ne renvoie jamais la clé."""
    try:
        r = _SESSION.get(GOOGLE_BOOKS, params={"q": "one piece", "maxResults": 1, "key": cle}, timeout=10)
    except requests.exceptions.RequestException:
        return False, "Google Books injoignable depuis le serveur"
    if r.status_code == 200:
        return True, "Clé acceptée par Google Books"
    raison = ""
    try:
        erreurs = (r.json().get("error") or {}).get("errors") or []
        raison = erreurs[0].get("reason", "") if erreurs else ""
    except ValueError:
        pass
    if r.status_code == 429:
        return False, "Quota dépassé pour cette clé : réessaie plus tard"
    if raison == "accessNotConfigured":
        return False, "L'API Books n'est pas activée dans le projet Google (Google Cloud → Bibliothèque d'API → Books API)"
    if r.status_code in (400, 403):
        return False, "Google refuse cette clé (vérifie qu'elle est complète et sans espace)"
    return False, f"Google Books a répondu {r.status_code}"


def fiche(serie: str, forcer=False) -> dict:
    """Dates de parution, auteurs, genres, éditeurs (AniList + Wikipédia FR) ; gardé 30 jours dans data/tomes/<série>.json."""
    garde = _charger(serie) or {}
    f = garde.get("fiche")
    if f and not forcer and time.time() - f.get("date", 0) < FICHE_DUREE:
        return f
    st = garde.get("statut_officiel") or {}
    if st.get("statut") and not st.get("anilist"):        # fiche AniList d'avant (sans identifiant) : on la refait une fois
        st = statut_officiel(serie, forcer=True) or st
    out = {k: v for k, v in (f or {}).items()}              # un échec (AniList qui demande de ralentir…) garde l'ancien
    roles = {}
    out["date"] = time.time()
    if st.get("anilist"):
        q = ("query($i:Int){Media(id:$i){startDate{year month} endDate{year month} status genres title{native romaji english} "
             "staff(perPage:8){edges{role node{name{full}}}}}}")
        try:
            m = _SESSION.post("https://graphql.anilist.co", json={"query": q, "variables": {"i": st["anilist"]}}, timeout=15).json()["data"]["Media"]
            date = lambda d: (f"{_MOIS[d['month'] - 1]} " if d.get("month") else "") + str(d["year"]) if d and d.get("year") else ""
            out.update(debut=date(m.get("startDate")), fin=date(m.get("endDate")), statut=m.get("status"),
                       titre_original=(m.get("title") or {}).get("native") or "", romaji=(m.get("title") or {}).get("romaji") or "",
                       genres=", ".join(_GENRES.get(g, g.lower()) for g in m.get("genres") or []))
            for e in ((m.get("staff") or {}).get("edges") or []):
                role = e.get("role") or ""
                for cle, mot in (("scenario", "Story"), ("dessin", "Art")):      # « Story & Art » : les deux
                    if mot in role and "Assist" not in role:
                        roles.setdefault(cle, []).append(e["node"]["name"]["full"])
            out.update({k: ", ".join(dict.fromkeys(v)) for k, v in roles.items()})
        except Exception as e:
            logger.info("Fiche AniList de %s : %s", serie, e.__class__.__name__)
    for k in ("wikipedia", "editeur_jp", "editeur_fr", "magazine"):   # refaits d'après la bonne page (ou vides)
        out.pop(k, None)
    try:
        page = _page_wikipedia([serie, st.get("titre"), st.get("titre_en")])
        if page:
            ib = _infobox(page)
            out["wikipedia"] = page
            # AniList connaît les auteurs de CETTE série (une suite peut avoir un autre dessinateur que l'article Wikipédia)
            out["scenario"] = (", ".join(dict.fromkeys(roles.get("scenario", []))) if roles.get("scenario") else "") or ib.get("auteur") or ib.get("scénariste") or out.get("scenario", "")
            out["dessin"] = (", ".join(dict.fromkeys(roles.get("dessin", []))) if roles.get("dessin") else "") or ib.get("dessinateur") or out.get("dessin", "")
            out["genres"] = ib.get("genre") or out.get("genres", "")
            out["editeur_jp"] = ib.get("éditeur", "")
            out["editeur_fr"] = ib.get("éditeur_francophone", "")
            out["magazine"] = ib.get("prépublication", "")
    except Exception as e:
        logger.info("Fiche Wikipédia de %s : %s", serie, e.__class__.__name__)
    # Sources complémentaires : MangaUpdates (éditeurs, auteurs, volumes) et Google Books (si une clé est réglée)
    titres = [serie, st.get("titre"), st.get("titre_en"), out.get("romaji")]
    mu = _mangaupdates(titres)
    if mu:
        out["editeurs_mu"] = ", ".join(mu["editeurs"])
        out["volumes_mu"] = mu["volumes"]
        out["mangaupdates"] = mu["id"]
        if not out.get("scenario") and mu["auteurs"]:
            out["scenario"] = ", ".join(mu["auteurs"][:3])
    gb = _google_books(next((x for x in titres if x), ""))
    if gb:
        if not out.get("editeur_fr") and gb["editeur"]:
            out["editeur_fr"] = gb["editeur"]
        if not out.get("scenario") and gb["auteurs"]:
            out["scenario"] = gb["auteurs"]
        if gb["tomes"]:
            out["tomes_google"] = gb["tomes"]
    out["sources"] = [s for s, ok in (("AniList", bool(st.get("anilist"))), ("Wikipédia", bool(out.get("wikipedia"))),
                                     ("MangaUpdates", bool(mu)), ("Google Books", bool(gb))) if ok]
    try:
        brut = json.loads(_fichier(serie).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        brut = {}
    brut["fiche"] = out
    DOSSIER.mkdir(parents=True, exist_ok=True)
    tmp = _fichier(serie).with_suffix(".tmp")
    tmp.write_text(json.dumps(brut, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_fichier(serie))
    return out


# ---------------------------------------------------------------- Titres des tomes (« Romance Dawn »)

def _wiki_propre(v: str) -> str:
    v = re.sub(r"\{\{\s*(1e|1re|1er|e|er|re)\s*\|([^}]*)\}\}", lambda m: ("1re " if m.group(1).startswith("1") else "e ") + m.group(2), v or "")
    v = re.sub(r"<ref.*?(</ref>|/>)|<[^>]+>", "", v or "", flags=re.S)
    v = re.sub(r"\{\{\s*(?:nowrap|lang|nihongo|japonais)\s*\|(?:[a-z]{2}\|)?([^|}]*)[^}]*\}\}", r"\1", v, flags=re.I)
    v = re.sub(r"\{\{[^}]*\}\}", "", v)
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", v).replace("\'\'", "").replace("\'\'\'", "")
    v = v.replace("''", "")
    return re.sub(r"\s+", " ", v).strip(" .,-–—")


def _champs_tomebd(bloc: str) -> dict:
    """Paramètres d'un modèle TomeBD (valeurs sur plusieurs lignes comprises)."""
    out = {}
    for m in re.finditer(r"\n\s*\|\s*([\wé]+)\s*=(.*?)(?=\n\s*\|\s*[\wé]+\s*=|\n\}\}|\Z)", "\n" + bloc, re.S):
        out.setdefault(m.group(1), m.group(2).strip())
    return out


def _dates(v: str) -> str:
    return re.sub(r"\{\{\s*date\s*\|([^|}]*)\|([^|}]*)\|([^|}]*)[^}]*\}\}", r"\1 \2 \3", v or "", flags=re.I)


def _puces(v: str) -> str:
    return re.sub(r"^\*\s*", " • ", v or "", flags=re.M)


def _liens_listes(pages: list) -> list:
    """Pages « Liste des chapitres / volumes / tomes de … » liées depuis ces pages Wikipédia (en français)."""
    out = []
    for page in [p for p in pages if p][:4]:
        try:
            r = _SESSION.get("https://fr.wikipedia.org/w/api.php", params={"action": "query", "prop": "links", "titles": page, "pllimit": 500,
                                                                             "plnamespace": 0, "format": "json", "redirects": 1}, timeout=15).json()
            for pg in (r.get("query", {}).get("pages") or {}).values():
                out += [l["title"] for l in pg.get("links", []) if re.match(r"Liste des (chapitres|volumes|tomes) d", l["title"])
                        and "dérivé" not in l["title"] and "hors-série" not in l["title"].lower()]
        except Exception:
            continue
    return list(dict.fromkeys(out))


def details_tome(serie: str, tome) -> dict:
    """Infos d'un tome (titre, sortie en France, chapitres) d'après la mémoire de titres_tomes.
    Pas de résumé (trop long) ; les chapitres n'apparaissent que s'ils ont un titre."""
    t = ((_charger(serie) or {}).get("titres_tomes") or {})
    d = {k: v for k, v in (t.get("details") or {}).get(str(int(tome)), {}).items() if k not in ("resume", "couverture")}
    if not d.get("chapitres"):                       # pas de liste en français : titres anglais connus pour ce tome
        info = _charger(serie) or {}
        titres_ch = info.get("titres") or {}
        nums = sorted(n for n, v in (info.get("tomes") or {}).items() if v is not None and int(v) == int(tome) and titres_ch.get(n))
        if nums:
            d["chapitres"] = [f"{n:g}. {titres_ch[n]}" for n in nums][:60]
            d["chapitres_langue"] = "en"
    if d.get("chapitres"):
        d["chapitres"] = [re.sub(r"(?<=\w)''(?=\w)", "'", c) for c in d["chapitres"]]
    if not d.get("titre") and (t.get("titres") or {}).get(str(int(tome))):
        d["titre"] = t["titres"][str(int(tome))]
    return d


def titres_tomes(serie: str, forcer=False) -> dict:
    """{numéro de tome (texte): titre} : Wikipédia français (TomeBD, titre_2 = titre français) en priorité,
    sinon Wikipédia anglais (Graphic novel list : LicensedTitle, sinon TranslitTitle). Gardé 30 jours."""
    garde = _charger(serie) or {}
    t = garde.get("titres_tomes")
    if t and "details" in t and not forcer and time.time() - t.get("date", 0) < FICHE_DUREE:
        return t.get("titres", {})
    st = garde.get("statut_officiel") or {}
    if st.get("statut") and not st.get("anilist"):        # fiche AniList d'avant (sans titre anglais) : refaite une fois
        st = statut_officiel(serie, forcer=True) or st
    noms = list(dict.fromkeys(x for x in [*_variantes(serie), st.get("titre"), st.get("titre_en")] if x))
    titres = {}
    try:                                                  # anglais
        for page in (_pages_wiki(noms) or [])[:8]:
            texte = _wiki({"action": "parse", "page": page, "prop": "wikitext", "redirects": 1}).get("parse", {}).get("wikitext", "")
            for bloc in re.split(r"\{\{\s*Graphic novel list", re.sub(r"<!--.*?-->", "", texte, flags=re.S))[1:]:
                vol = re.search(r"\|\s*VolumeNumber\s*=\s*(\d+)", bloc)
                tit = re.search(r"\|\s*LicensedTitle\s*=\s*([^\n|]+)", bloc) or re.search(r"\|\s*TranslitTitle\s*=\s*([^\n|]+)", bloc)
                if vol and tit and _wiki_propre(tit.group(1)):
                    titres[vol.group(1)] = _wiki_propre(tit.group(1))
    except Exception as e:
        logger.info("Titres des tomes (anglais) de %s : %s", serie, e.__class__.__name__)
    fr, details = {}, {}
    try:                                                  # français, prioritaire
        pages = []
        for nom in noms[:3]:
            r = _SESSION.get("https://fr.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "format": "json",
                                                                             "srsearch": f'intitle:"Liste des chapitres" {nom}', "srlimit": 8}, timeout=15).json()
            for x in r.get("query", {}).get("search", []):     # « Liste des chapitres de Dragon Ball (…) », pas « … Dragon Ball Super »
                reste = re.sub(r"^Liste des (?:chapitres|volumes) de\s+", "", x["title"])
                if _simple(re.sub(r"\s*\(.*\)$", "", reste)) == _simple(nom):
                    pages.append(x["title"])
            if pages:
                break
        # Liens de la fiche Wikipédia de la série et des pages « Liste… » qui renvoient vers leurs parties (One Piece : 6 parties)
        principale = _page_wikipedia([serie, st.get("titre"), st.get("titre_en")])
        pages = list(dict.fromkeys(pages + _liens_listes([principale] if principale else []) + _liens_listes(pages)))
        for page in pages[:12]:
            r = _SESSION.get("https://fr.wikipedia.org/w/api.php", params={"action": "parse", "page": page, "prop": "wikitext",
                                                                             "format": "json", "redirects": 1}, timeout=15).json()
            w = r.get("parse", {}).get("wikitext", {}).get("*", "")
            langue_fr = "2"                               # quel champ « titre_N » est en français (d'après TomeBD/Entête)
            for bloc in re.split(r"\{\{\s*TomeBD", w)[1:]:
                if bloc.startswith("/Entête"):
                    m = re.search(r"\|\s*langue_(\d)\s*=\s*Fran", bloc)
                    langue_fr = m.group(1) if m else "1"
                    continue
                vol = re.search(r"\|\s*volume\s*=\s*(\d+)", bloc)
                if not vol or vol.group(1) in details:
                    continue                                  # 1re édition de la page (pas la « double », la « perfect »)
                champs = _champs_tomebd(bloc)
                titre = _wiki_propre(champs.get("titre_" + langue_fr, ""))
                extra = champs.get("extra", "")
                m_t = re.search(r"Titre du volume\s*:?\s*'*\s*(?:<br\s*/?>)?(.+?)(?:<br|$)", extra, re.S | re.I)
                if not titre and m_t:
                    titre = _wiki_propre(m_t.group(1))
                m_c = re.search(r"Personnages en couverture\s*:?\s*'*\s*(?:<br\s*/?>)?(.+?)(?:<br|$)", extra, re.S | re.I)
                # « * Ch.1 : … », « * [gras]Plat 1 :[/gras] … », « * Chapitre 12 : … » (le mot avant le numéro varie)
                brut = champs.get("chapitre", "").replace("'" * 3, "")
                chap = [(float(n), _wiki_propre(t)) for n, t in re.findall(r"^\*\s*[^\d:\n]{0,15}?(\d+(?:\.\d+)?)\s*:\s*(.+)$", brut, re.M)]
                resume = re.sub(r"'{3}\s*Résumé\s*:?\s*'{3}", "", champs.get("résumé", ""), flags=re.I)
                d = {"titre": titre, "sortie": _wiki_propre(_dates(champs.get("sortie_" + langue_fr, ""))),
                     "couverture": _wiki_propre(m_c.group(1)) if m_c else "",
                     "resume": _wiki_propre(_puces(resume)),
                     "chapitres": [f"{n:g}. {t}" for n, t in chap if t][:40]}
                details[vol.group(1)] = {k: v for k, v in d.items() if v}
                if titre:
                    fr[vol.group(1)] = titre
            time.sleep(0.3)
    except Exception as e:
        logger.info("Titres des tomes (français) de %s : %s", serie, e.__class__.__name__)
    titres.update(fr)
    try:
        brut = json.loads(_fichier(serie).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        brut = {}
    brut["titres_tomes"] = {"date": time.time() if titres else time.time() - FICHE_DUREE + 86400,   # rien : retenté demain
                            "titres": titres, "details": details}
    DOSSIER.mkdir(parents=True, exist_ok=True)
    tmp = _fichier(serie).with_suffix(".tmp")
    tmp.write_text(json.dumps(brut, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_fichier(serie))
    logger.info("Titres des tomes de %s : %d trouvé(s)", serie, len(titres))
    return titres
