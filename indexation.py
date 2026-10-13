"""Index de la bibliothèque : qui est dans quel dossier, avec la taille et la date de chaque fichier.

Le parcours du NAS (plusieurs secondes à froid) n'est plus refait à chaque demande : le résultat est gardé en mémoire
et dans data/index.sqlite (SQLite, mode WAL), donc prêt tout de suite après un redémarrage. Le parcours ne relit
(stat) que les dossiers dont la date a changé.
"""
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger("mouflanga")

_VERROU_BASE = threading.Lock()


def _connexion(base: Path):
    base.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(base), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("CREATE TABLE IF NOT EXISTS fichiers (serie TEXT NOT NULL, chemin TEXT NOT NULL, taille INTEGER, mtime REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS dossiers (chemin TEXT PRIMARY KEY, mtime REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS meta (cle TEXT PRIMARY KEY, valeur TEXT)")
    return c


def charger(base: Path, racine: Path):
    """(fichiers, dossiers) gardés pour cette racine, ou None : fichiers = {série: [(chemin relatif, taille, mtime)]},
    dossiers = {chemin relatif: mtime}."""
    try:
        with _VERROU_BASE:
            c = _connexion(base)
            try:
                meta = dict(c.execute("SELECT cle, valeur FROM meta"))
                if meta.get("racine") != str(racine):
                    return None
                fichiers = {}
                for serie, chemin, taille, mtime in c.execute("SELECT serie, chemin, taille, mtime FROM fichiers ORDER BY rowid"):
                    fichiers.setdefault(serie, []).append((chemin, taille, mtime))
                dossiers = dict(c.execute("SELECT chemin, mtime FROM dossiers"))
                return fichiers, dossiers
            finally:
                c.close()
    except sqlite3.Error as e:
        logger.info("Index de la bibliothèque illisible : %s", e.__class__.__name__)
        return None


def enregistrer(base: Path, racine: Path, fichiers: dict, dossiers: dict) -> None:
    try:
        with _VERROU_BASE:
            c = _connexion(base)
            try:
                with c:
                    c.execute("DELETE FROM fichiers")
                    c.execute("DELETE FROM dossiers")
                    c.executemany("INSERT INTO fichiers VALUES (?,?,?,?)",
                                  [(s, ch, t, m) for s, lst in fichiers.items() for ch, t, m in lst])
                    c.executemany("INSERT INTO dossiers VALUES (?,?)", list(dossiers.items()))
                    c.execute("INSERT OR REPLACE INTO meta VALUES ('racine', ?)", (str(racine),))
                    c.execute("INSERT OR REPLACE INTO meta VALUES ('date', ?)", (str(time.time()),))
            finally:
                c.close()
    except sqlite3.Error as e:
        logger.warning("Index de la bibliothèque non enregistré : %s", e.__class__.__name__)


def parcourir(racine: Path, garder, garder_vrac, precedent_fichiers: dict, precedent_dossiers: dict):
    """Parcourt la bibliothèque. garder(chemin) : ce fichier d'un dossier de série est-il à garder ? garder_vrac(chemin) :
    idem pour un fichier posé à la racine. Renvoie (fichiers, dossiers, vrac) ; fichiers et dossiers comme charger(). Les dossiers dont la date n'a pas changé gardent la taille et la date
    de leurs fichiers connus (pas de stat par fichier sur le NAS)."""
    connus = {}
    for serie, lst in (precedent_fichiers or {}).items():
        for ch, t, m in lst:
            connus[ch] = (t, m)
    fichiers, dossiers = {}, {}
    try:
        racine_entrees = sorted(os.scandir(racine), key=lambda e: e.name)
    except OSError:
        return {}, {}, []

    def marcher(chemin: Path, rel: str, sortie: list):
        try:
            d_mtime = os.stat(chemin).st_mtime
        except OSError:
            return
        dossiers[rel] = d_mtime
        inchange = precedent_dossiers.get(rel) == d_mtime
        try:
            entrees = list(os.scandir(chemin))
        except OSError:
            return
        for e in entrees:
            nom = e.name
            sous = f"{rel}/{nom}" if rel else nom
            try:
                est_dossier = e.is_dir()
            except OSError:
                continue
            if est_dossier:
                if not nom.startswith((".", "@")):
                    marcher(Path(e.path), sous, sortie)
                continue
            if not garder(Path(e.path)):
                continue
            if inchange and sous in connus:
                t, m = connus[sous]
            else:
                try:
                    st = e.stat()
                    t, m = st.st_size, st.st_mtime
                except OSError:
                    t, m = 0, 0.0
            sortie.append((sous, t, m))

    vrac = []
    for entry in racine_entrees:
        nom = entry.name
        if nom.startswith((".", "@", "#")):
            continue
        try:
            est_dossier = entry.is_dir()
        except OSError:
            continue
        if est_dossier:
            lst = []
            marcher(Path(entry.path), nom, lst)
            if lst:
                fichiers[nom] = lst
        elif garder_vrac(Path(entry.path)):
            try:
                st = entry.stat()
                vrac.append((nom, st.st_size, st.st_mtime))
            except OSError:
                vrac.append((nom, 0, 0.0))
    try:
        dossiers[""] = os.stat(racine).st_mtime
    except OSError:
        pass
    return fichiers, dossiers, vrac
