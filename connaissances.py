"""Connaissances gardées pour de bon (data/connaissances.sqlite) : une fois apprises sur Internet, elles ne changent plus
et ne sont plus redemandées (quotas des sites, rapidité). Gardées en mémoire après la première lecture.

- œuvres liées d'une série (AniList : histoires annexes, spin-off…), par numéro AniList de la série ;
- date de sortie au Japon de chaque tome (Wikipédia anglais) ;
- date de la dernière demande faite à Internet pour chaque sujet (pour ne redemander que s'il peut y avoir du neuf).
"""
import json
import sqlite3
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent / "data" / "connaissances.sqlite"
_VERROU = threading.Lock()
_MEMOIRE = {}


def _connexion():
    BASE.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(BASE), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS oeuvres_liees (serie TEXT NOT NULL, id INTEGER NOT NULL, relation TEXT, format TEXT,"
              " volumes INTEGER, debut TEXT, titres TEXT, PRIMARY KEY (serie, id))")
    c.execute("CREATE TABLE IF NOT EXISTS dates_tomes (serie TEXT NOT NULL, tome INTEGER NOT NULL, date TEXT, PRIMARY KEY (serie, tome))")
    c.execute("CREATE TABLE IF NOT EXISTS demandes (serie TEXT NOT NULL, sujet TEXT NOT NULL, date REAL, PRIMARY KEY (serie, sujet))")
    return c


def _lire(cle, requete, args, transformer):
    if cle in _MEMOIRE:
        return _MEMOIRE[cle]
    with _VERROU:
        c = _connexion()
        try:
            v = transformer(c.execute(requete, args).fetchall())
        finally:
            c.close()
    _MEMOIRE[cle] = v
    return v


def oeuvres_liees(serie: str):
    """Liste gardée (peut être vide), ou None si jamais demandée."""
    if derniere_demande(serie, "oeuvres_liees") is None:
        return None
    return _lire(("ol", serie), "SELECT id, relation, format, volumes, debut, titres FROM oeuvres_liees WHERE serie=? ORDER BY debut", (serie,),
                 lambda rs: [{"id": i, "relation": r, "format": f, "volumes": v, "debut": d or "", "titres": json.loads(t or "[]")}
                             for i, r, f, v, d, t in rs])


def garder_oeuvres_liees(serie: str, liste: list[dict]):
    with _VERROU:
        c = _connexion()
        try:
            with c:
                for o in liste:                      # on ajoute ou complète, on n'efface jamais ce qui a été appris
                    c.execute("INSERT OR REPLACE INTO oeuvres_liees VALUES (?,?,?,?,?,?,?)",
                              (serie, o["id"], o.get("relation"), o.get("format"), o.get("volumes"), o.get("debut"),
                               json.dumps(o.get("titres") or [], ensure_ascii=False)))
                c.execute("INSERT OR REPLACE INTO demandes VALUES (?,?,?)", (serie, "oeuvres_liees", time.time()))
        finally:
            c.close()
    _MEMOIRE.pop(("ol", serie), None)
    _MEMOIRE.pop(("dem", serie, "oeuvres_liees"), None)


def dates_tomes(serie: str) -> dict:
    """{tome (texte): "AAAA-MM-JJ"} gardés."""
    return _lire(("dt", serie), "SELECT tome, date FROM dates_tomes WHERE serie=?", (serie,), lambda rs: {str(t): d for t, d in rs if d})


def garder_dates_tomes(serie: str, dates: dict):
    with _VERROU:
        c = _connexion()
        try:
            with c:
                c.executemany("INSERT OR REPLACE INTO dates_tomes VALUES (?,?,?)", [(serie, int(t), d) for t, d in dates.items() if d])
                c.execute("INSERT OR REPLACE INTO demandes VALUES (?,?,?)", (serie, "dates_tomes", time.time()))
        finally:
            c.close()
    _MEMOIRE.pop(("dt", serie), None)
    _MEMOIRE.pop(("dem", serie, "dates_tomes"), None)


def derniere_demande(serie: str, sujet: str):
    """Date (secondes) de la dernière demande faite à Internet sur ce sujet, ou None."""
    return _lire(("dem", serie, sujet), "SELECT date FROM demandes WHERE serie=? AND sujet=?", (serie, sujet),
                 lambda rs: rs[0][0] if rs else None)
