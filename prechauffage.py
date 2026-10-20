"""Préparation de la bibliothèque en arrière-plan : une série (ou toute la bibliothèque) est « préchauffée » pour que
l'ouvrir ne fasse plus attendre : titres des tomes (Wikipédia), résumés (Google Books), analyse de l'édition,
sommaire des tomes (lecture du texte imprimé).

Un seul travailleur, une série à la fois, qui laisse la place aux vrais travaux (import, téléchargement…).
Ce qui est déjà préparé est gardé dans data/prechauffage.json avec la « signature » des fichiers de la série : une série
n'est refaite que si ses fichiers ont changé (ou si on le demande). Rien n'est jamais effacé ni modifié dans les fichiers.
"""
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger("mouflanga")

VERSION = 6                      # monte quand la préparation fait plus de choses : les séries sont refaites une fois
_VERROU = threading.Lock()
_FILE = []                       # séries en attente (dans l'ordre)
_ETAT = {"en_cours": False, "serie": "", "fait": 0, "total": 0, "message": "", "debut": 0.0, "fin": 0.0,
         "manuel": False, "erreurs": [], "detail": ""}
_CFG = {}


def configurer(fichier: Path, series, signature, traiter, occupe):
    """series() → {nom: fichiers} ; signature(nom) → texte ; traiter(nom, progression) fait le travail d'une série ;
    occupe() → liste des raisons (vide = libre)."""
    _CFG.update(fichier=Path(fichier), series=series, signature=signature, traiter=traiter, occupe=occupe)


def _lire() -> dict:
    try:
        d = json.loads(_CFG["fichier"].read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, KeyError):
        return {}


def _ecrire(d: dict):
    f = _CFG["fichier"]
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def signature_fichiers(chemins_taille_date) -> str:
    h = hashlib.sha1()
    for p, taille, mtime in sorted(chemins_taille_date):
        h.update(f"{p}|{taille}|{int(mtime or 0)}\n".encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def etat() -> dict:
    with _VERROU:
        e = dict(_ETAT, erreurs=list(_ETAT["erreurs"]), attente=len(_FILE))
    deja = _lire()
    try:
        noms = [n for n in _CFG["series"]() if n != "(Sans série)"]
    except Exception:
        noms = []
    e["series"] = len(noms)
    e["pretes"] = sum(1 for n in noms if (deja.get(n) or {}).get("v") == VERSION)
    e["derniere"] = max([d.get("date", "") for d in deja.values() if isinstance(d, dict)] or [""])
    return e


def a_preparer(forcer=False) -> list:
    """Séries à préparer : jamais faites, fichiers changés ou version plus ancienne (toutes si forcer)."""
    deja = _lire()
    out = []
    for nom in _CFG["series"]():
        if nom == "(Sans série)":
            continue
        d = deja.get(nom) or {}
        if forcer or d.get("v") != VERSION or d.get("signature") != _CFG["signature"](nom) or time.time() >= d.get("reprendre", float("inf")):
            out.append(nom)
    return out


def demander(noms, manuel=False, devant=False) -> int:
    """Ajoute des séries à la file et démarre le travailleur. Renvoie le nombre ajouté."""
    n = 0
    with _VERROU:
        for nom in noms:
            if nom and nom not in _FILE and nom != _ETAT["serie"]:
                if devant:
                    _FILE.insert(0, nom)
                else:
                    _FILE.append(nom)
                n += 1
        if manuel:
            _ETAT["manuel"] = True
        demarrer = n and not _ETAT["en_cours"]
        if demarrer:
            _ETAT.update(en_cours=True, fait=0, total=len(_FILE), debut=time.time(), fin=0.0, message="Préparation en cours…",
                         erreurs=[], serie="")
        elif n:
            _ETAT["total"] += n
    if demarrer:
        threading.Thread(target=_travail, daemon=True, name="prechauffage").start()
    return n


def tout(forcer=True) -> int:
    return demander(a_preparer(forcer=forcer), manuel=True)


def _travail():
    try:
        os.nice(10)                  # discret : l'appli reste fluide pendant la préparation (ce fil et ses lectures de texte)
    except (OSError, AttributeError):
        pass
    while True:
        with _VERROU:
            if not _FILE:
                _ETAT.update(en_cours=False, serie="", fin=time.time(), detail="",
                             message=f"Terminé : {_ETAT['fait']} série(s) préparée(s)"
                                     + (f", {len(_ETAT['erreurs'])} avec un problème" if _ETAT["erreurs"] else "") + ".")
                _ETAT["manuel"] = False
                return
            nom = _FILE.pop(0)
            _ETAT["serie"] = nom
        erreur, reprendre = False, None
        try:
            attendu = 0
            while _CFG["occupe"]() and attendu < 3600:     # un vrai travail passe d'abord (import, téléchargement…)
                with _VERROU:
                    _ETAT["detail"] = "en attente : " + ", ".join(_CFG["occupe"]())[:80]
                time.sleep(15)
                attendu += 15
            with _VERROU:
                _ETAT["detail"] = ""

            def progression(texte):
                with _VERROU:
                    _ETAT["detail"] = str(texte)[:100]
            reprendre = _CFG["traiter"](nom, progression)     # une heure : la série est à reprendre à partir de là
        except Exception as e:
            erreur = True
            logger.warning("Préparation de « %s » : %s", nom, e)
            with _VERROU:
                _ETAT["erreurs"].append(f"{nom} : {e.__class__.__name__}")
        try:                                       # noté même en cas d'erreur : refait seulement si les fichiers changent
            deja = _lire()
            deja[nom] = {"v": VERSION, "signature": _CFG["signature"](nom), "date": time.strftime("%Y-%m-%d %H:%M"),
                         **({"erreur": True} if erreur else {}),
                         **({"reprendre": reprendre} if isinstance(reprendre, (int, float)) else {})}
            _ecrire(deja)
        except Exception as e:
            logger.info("Préparation de « %s » : état non gardé (%s)", nom, e.__class__.__name__)
        with _VERROU:
            _ETAT["fait"] += 1


def surveiller(intervalle=60, delai_depart=90):
    """Au démarrage puis toutes les minutes : les séries nouvelles ou modifiées (stables depuis une vérification)
    sont préparées toutes seules, sans rien demander."""
    def boucle():
        time.sleep(delai_depart)
        vu = {}
        while True:
            try:
                changees = []
                for nom in a_preparer():
                    sig = _CFG["signature"](nom)
                    if vu.get(nom) == sig:               # pas bougé depuis la dernière vérification : le copier est fini
                        changees.append(nom)
                    vu[nom] = sig
                if changees:
                    demander(changees)
            except Exception as e:
                logger.info("Surveillance de la préparation : %s", e.__class__.__name__)
            time.sleep(intervalle)
    threading.Thread(target=boucle, daemon=True, name="prechauffage-veille").start()
