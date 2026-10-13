"""Notes des séries (sur 10) : AniList d'abord, puis Kitsu, puis MyAnimeList (Jikan). Aucune clé nécessaire.

Les notes sont gardées dans data/notes.json : la bibliothèque et les fiches les lisent là (aucun appel Internet à
l'affichage). Une série sans note, ou dont la note a plus d'un jour, est demandée en arrière-plan, une série à la fois
avec une pause (Jikan : environ 30 demandes par minute, AniList : 90).
"""
import json
import logging
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

import requests

logger = logging.getLogger("mouflanga")

FICHIER = Path(__file__).resolve().parent / "data" / "notes.json"
DUREE = 86400                    # une mise à jour par jour (une série sans note est réessayée aussi une fois par jour)
PAUSE = 2.5                      # secondes entre deux séries
_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "MouFlanga/2 (bibliotheque personnelle)"
_VERROU = threading.Lock()
_CACHE = {"cle": None, "notes": {}}
_JIKAN_HS = {"depuis": 0.0}      # dernière panne de connexion à Jikan


def _simple(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def toutes() -> dict:
    """{série: {"valeur", "source", "date", "essai"}} (relu seulement si le fichier a changé)."""
    try:
        st = FICHIER.stat()
        cle = (st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    if _CACHE["cle"] != cle:
        try:
            _CACHE.update(cle=cle, notes=json.loads(FICHIER.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            _CACHE.update(cle=cle, notes={})
    return _CACHE["notes"]


def note(serie: str):
    """(valeur sur 10, source) ou None."""
    n = toutes().get(serie) or {}
    return (n["valeur"], n.get("source", "")) if n.get("valeur") else None


def _ecrire(donnees: dict):
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    tmp = FICHIER.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, FICHIER)


def a_rafraichir(serie: str, maintenant=None) -> bool:
    n = toutes().get(serie)
    maintenant = maintenant or time.time()
    return not n or maintenant - max(n.get("date", 0), n.get("essai", 0)) >= DUREE


# ---------------------------------------------------------------- Sources

def _anilist(anilist_id, titres):
    """(note sur 10, identifiant MyAnimeList) d'après AniList, ou (None, mal)."""
    if anilist_id:
        q, v = "query($i:Int){Media(id:$i,type:MANGA){averageScore meanScore idMal}}", {"i": int(anilist_id)}
        m = _SESSION.post("https://graphql.anilist.co", json={"query": q, "variables": v}, timeout=15).json()["data"]["Media"]
    else:
        q = "query($s:String){Media(search:$s,type:MANGA,format_not:NOVEL){averageScore meanScore idMal title{romaji english} synonyms}}"
        m = None
        for t in [x for x in titres if x][:5]:
            r = _SESSION.post("https://graphql.anilist.co", json={"query": q, "variables": {"s": t}}, timeout=15)
            if r.status_code == 429:
                raise RuntimeError("AniList demande de ralentir")
            m = (r.json().get("data") or {}).get("Media")
            noms = [(m or {}).get("title", {}).get(k) or "" for k in ("romaji", "english")] + list((m or {}).get("synonyms") or [])
            if m and _simple(t) in {_simple(n) for n in noms if n}:
                break
            m = None
            time.sleep(0.8)
    if not m:
        return None, None
    score = m.get("averageScore") or m.get("meanScore")
    return (round(score / 10, 1) if score else None), m.get("idMal")


def _jikan(mal_id, titres):
    if not mal_id:
        for t in [x for x in titres if x][:2]:
            r = _SESSION.get("https://api.jikan.moe/v4/manga", params={"q": t, "limit": 5}, timeout=8)
            if r.status_code == 429:
                raise RuntimeError("Jikan demande de ralentir")
            for it in (r.json().get("data") or []):
                noms = [it.get("title"), it.get("title_english")] + [x.get("title") for x in it.get("titles") or []]
                if _simple(t) in {_simple(n) for n in noms if n}:
                    mal_id = it.get("mal_id")
                    break
            if mal_id:
                break
            time.sleep(1.2)
    if not mal_id:
        return None
    r = _SESSION.get(f"https://api.jikan.moe/v4/manga/{int(mal_id)}", timeout=8)
    if r.status_code == 429:
        raise RuntimeError("Jikan demande de ralentir")
    s = (r.json().get("data") or {}).get("score")
    return round(float(s), 1) if s else None


def _kitsu(titres):
    for t in [x for x in titres if x][:2]:
        r = _SESSION.get("https://kitsu.io/api/edge/manga", params={"filter[text]": t, "page[limit]": 5}, timeout=15)
        for it in (r.json().get("data") or []):
            a = it.get("attributes") or {}
            noms = [a.get("canonicalTitle")] + list((a.get("titles") or {}).values())
            if _simple(t) in {_simple(n) for n in noms if n} and a.get("averageRating"):
                return round(float(a["averageRating"]) / 10, 1)
    return None


def chercher(serie: str, anilist_id=None, titres=()) -> tuple:
    """(note sur 10, source) d'après AniList, Kitsu puis MyAnimeList ; (None, "") si aucune source n'a de note."""
    titres = [serie, *titres]
    mal = None
    try:
        v, mal = _anilist(anilist_id, titres)
        if v:
            return v, "AniList"
    except Exception as e:
        logger.info("Note de %s (AniList) : %s", serie, e.__class__.__name__)
    try:
        v = _kitsu(titres)
        if v:
            return v, "Kitsu"
    except Exception as e:
        logger.info("Note de %s (Kitsu) : %s", serie, e.__class__.__name__)
    if time.time() - _JIKAN_HS["depuis"] > 3600:      # MyAnimeList : en dernier (api.jikan.moe n'est pas toujours joignable d'ici)
        try:
            v = _jikan(mal, titres)
            if v:
                return v, "MyAnimeList"
        except requests.ConnectionError as e:
            _JIKAN_HS["depuis"] = time.time()          # injoignable : on n'insiste pas pendant une heure
            logger.info("MyAnimeList (Jikan) injoignable : %s", e.__class__.__name__)
        except Exception as e:
            logger.info("Note de %s (MyAnimeList) : %s", serie, e.__class__.__name__)
    return None, ""


def mettre_a_jour(serie: str, anilist_id=None, titres=()) -> bool:
    """Interroge les sources et enregistre. Une note déjà connue n'est jamais effacée par un échec."""
    valeur, source = chercher(serie, anilist_id, titres)
    with _VERROU:
        donnees = dict(toutes())
        ancien = donnees.get(serie) or {}
        n = {"valeur": ancien.get("valeur"), "source": ancien.get("source", ""), "date": ancien.get("date", 0),
             "essai": time.time()}
        if valeur:
            n.update(valeur=valeur, source=source, date=time.time())
        donnees[serie] = n
        _ecrire(donnees)
    return bool(valeur)


_EN_COURS = {"actif": False}


def lancer(series: list, identifiants, pause: float = PAUSE) -> bool:
    """Met à jour, en arrière-plan, les notes à rafraîchir parmi `series`. identifiants(série) → (id AniList, [titres]).
    Renvoie False si une mise à jour est déjà en cours ou s'il n'y a rien à faire."""
    a_faire = [s for s in series if a_rafraichir(s)]
    if not a_faire or _EN_COURS["actif"]:
        return False
    _EN_COURS["actif"] = True

    def travail():
        try:
            for s in a_faire:
                try:
                    anilist_id, titres = identifiants(s)
                    mettre_a_jour(s, anilist_id, titres)
                except Exception as e:
                    logger.info("Note de %s : %s", s, e.__class__.__name__)
                time.sleep(pause)
        finally:
            _EN_COURS["actif"] = False
    threading.Thread(target=travail, daemon=True).start()
    return True


def boucle(series, identifiants, intervalle: float = 3600):
    """Boucle de fond : toutes les heures, rafraîchit les notes dont la dernière mise à jour date de plus d'un jour."""
    time.sleep(60)
    while True:
        try:
            lancer(list(series()), identifiants)
        except Exception as e:
            logger.info("Boucle des notes : %s", e.__class__.__name__)
        time.sleep(intervalle)
