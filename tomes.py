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


def _variantes(titre: str) -> list[str]:
    """Le nom tel quel, puis quelques écritures courantes (« N°8 » → « No. 8 »)."""
    out = [titre.strip()]
    v = re.sub(r"\s*n[°º]\s*", " No. ", titre, flags=re.I).strip()
    if v not in out:
        out.append(re.sub(r"\s+", " ", v))
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
            r = _SESSION.get("https://api.mangadex.org/manga", params={"title": nom, "limit": 1}, timeout=15).json()
            if not r.get("data"):
                continue
            ident = r["data"][0]["id"]
            ag = _SESSION.get(f"https://api.mangadex.org/manga/{ident}/aggregate", timeout=20).json()
        except Exception as e:
            logger.info("MangaDex injoignable (%s)", e.__class__.__name__)
            return None
        tomes = {}
        for vol, d in (ag.get("volumes") or {}).items():
            for ch in (d.get("chapters") or {}):
                try:
                    tomes[float(ch)] = int(float(vol)) if vol not in ("none", "") else None
                except ValueError:
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
    noms = _variantes(serie)
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
    cle = _simple(serie)
    def note(m):
        titres = [_simple(t) for t in (m["title"].get("romaji"), m["title"].get("english")) if t] + [_simple(x) for x in m.get("synonyms") or []]
        exact = cle in titres
        contient = any(cle and cle in t for t in titres)
        vol = m.get("volumes")
        compatible = bool(tome_max and vol and vol >= tome_max)
        proche = -abs((vol or 0) - (tome_max or 0)) if tome_max and vol else -999
        return (exact, compatible, contient, m.get("format") == "MANGA", proche)
    return max(medias, key=note) if medias else None


def _texte_propre(t):
    t = re.sub(r"<br\s*/?>", "\n", t or "", flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)              # liens au format [texte](adresse)
    t = re.sub(r"\(Source:[^)]*\)|\n---.*$", "", t, flags=re.S | re.I)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _resume(m):
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
    fr = _wikipedia_fr(m)
    if fr:
        return fr, "fr"
    return _texte_propre(m.get("description") or ""), ("en" if m.get("description") else "")


def _wikipedia_fr(m):
    """Introduction de l'article Wikipédia en français sur la série (si c'est bien un article de manga)."""
    for titre in [t for t in (m["title"].get("romaji"), m["title"].get("english")) if t]:
        try:
            r = _SESSION.get("https://fr.wikipedia.org/w/api.php", params={
                "action": "query", "list": "search", "srsearch": f"{titre} manga", "srlimit": 3,
                "format": "json", "formatversion": 2}, timeout=15).json()
            for res in r.get("query", {}).get("search", []):
                if _simple(titre).split()[0] not in _simple(res["title"]):
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
          "titre": (m["title"].get("romaji") or m["title"].get("english")) if m else None}
    st["resume"], st["resume_langue"] = _resume(m) if m else ("", "")
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
