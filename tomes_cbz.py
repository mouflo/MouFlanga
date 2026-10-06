"""
Fichiers de tome : un seul .cbz par tome, complété au fur et à mesure que les chapitres arrivent.

Rangement dans le dossier de la série :
    Tome 01/<Série> - Tome 01.cbz
    Tome 02/<Série> - Tome 02.cbz
    Hors tome/<Série> - Hors tome.cbz     (chapitres pas encore sortis en tome)

Dans le .cbz, chaque page porte le numéro de son chapitre : « c0012.00-p003.jpg » (chapitre 12, page 3) ;
le tri naturel des noms donne donc l'ordre de lecture, et on sait toujours où commence chaque chapitre.
Le fichier « chapitres.json » garde les titres ; « ComicInfo.xml » sert aux autres lecteurs (Komga, Kavita…).
Chaque modification réécrit le fichier à côté puis le remplace d'un coup (jamais de fichier à moitié écrit).
"""
import json
import os
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import archives

INFO = "chapitres.json"
COMICINFO = "ComicInfo.xml"
HORS_TOME = "Hors tome"
_PAGE = re.compile(r"^c(\d{4,})\.(\d{2})-p\d+\.\w+$")


def nom_page(num: float, k: int, donnees: bytes) -> str:
    ext = "jpg"
    if donnees.startswith(b"\x89PNG"):
        ext = "png"
    elif donnees.startswith(b"RIFF") and donnees[8:12] == b"WEBP":
        ext = "webp"
    entier = int(num)
    return f"c{entier:04d}.{round((num - entier) * 100):02d}-p{k:03d}.{ext}"


def num_page(nom: str):
    m = _PAGE.match(Path(nom).name)
    return int(m.group(1)) + int(m.group(2)) / 100 if m else None


def dossier_tome(tome) -> str:
    return HORS_TOME if tome is None else f"Tome {tome:02d}"


def fichier_tome(serie_dir: Path, serie: str, tome) -> Path:
    return Path(serie_dir) / dossier_tome(tome) / f"{serie} - {dossier_tome(tome)}.cbz"


_CACHE = {}


def lire_info(path: Path) -> dict | None:
    """Contenu de chapitres.json (None : fichier ordinaire, pas un fichier de tome). Gardé tant que le fichier ne change pas."""
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return None
    cle = (str(path), st.st_mtime_ns, st.st_size)
    if cle in _CACHE:
        return _CACHE[cle]
    try:
        with zipfile.ZipFile(path) as zf:
            info = json.loads(zf.read(INFO).decode("utf-8")) if INFO in zf.namelist() else None
    except (OSError, zipfile.BadZipFile, ValueError, KeyError):
        info = None
    if len(_CACHE) > 512:
        _CACHE.clear()
    _CACHE[cle] = info
    return info


def chapitres(path: Path) -> list[dict]:
    """Chapitres d'un fichier de tome : [{"num", "titre", "debut", "nb"}] dans l'ordre de lecture."""
    info = lire_info(path) or {}
    titres = {float(k): v for k, v in (info.get("titres") or {}).items()}
    out = []
    for i, nom in enumerate(archives.pages(path)):
        n = num_page(nom)
        if n is None:
            continue
        if out and out[-1]["num"] == n:
            out[-1]["nb"] += 1
        else:
            out.append({"num": n, "titre": titres.get(n, ""), "debut": i, "nb": 1})
    return out


def _comicinfo(serie: str, tome, titres: dict, nb_pages: int) -> str:
    nums = sorted(titres)
    liste = " · ".join(f"{n:g}" + (f" : {titres[n]}" if titres[n] else "") for n in nums)
    volume = f"<Volume>{tome}</Volume>" if tome is not None else ""
    return ('<?xml version="1.0" encoding="utf-8"?>\n<ComicInfo>'
            f"<Series>{escape(serie)}</Series>{volume}"
            f"<Title>{escape(dossier_tome(tome))}</Title>"
            f"<Summary>{escape('Chapitres ' + liste)}</Summary>"
            f"<PageCount>{nb_pages}</PageCount><LanguageISO>fr</LanguageISO><Manga>YesAndRightToLeft</Manga>"
            "</ComicInfo>\n")


def _reecrire(path: Path, serie: str, tome, retirer: set, ajouts: dict, titres_ajout: dict):
    """Réécrit le fichier : enlève les chapitres « retirer », ajoute « ajouts » {num: [octets]}."""
    path = Path(path)
    titres, anciennes = {}, []
    if path.exists():
        info = lire_info(path) or {}
        titres = {float(k): v for k, v in (info.get("titres") or {}).items()}
        with zipfile.ZipFile(path) as zf:
            anciennes = [n for n in zf.namelist() if num_page(n) is not None]
    remplaces = set(retirer) | set(ajouts)
    for n in remplaces:
        titres.pop(n, None)
    titres.update({n: titres_ajout.get(n, "") for n in ajouts})
    gardees = [n for n in anciennes if num_page(n) not in remplaces]
    if not gardees and not ajouts:
        path.unlink(missing_ok=True)
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    total = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:      # images déjà compressées : stockage direct
        if gardees:
            with zipfile.ZipFile(path) as src:
                for nom in gardees:
                    dst.writestr(nom, src.read(nom))
                    total += 1
        for n, pages in ajouts.items():
            for k, donnees in enumerate(pages, 1):
                dst.writestr(nom_page(n, k, donnees), donnees)
                total += 1
        dst.writestr(INFO, json.dumps({"serie": serie, "tome": tome,
                                       "titres": {f"{n:g}": t for n, t in sorted(titres.items())}},
                                      ensure_ascii=False, indent=1))
        dst.writestr(COMICINFO, _comicinfo(serie, tome, titres, total))
    os.replace(tmp, path)
    return len(titres)


def ajouter(serie_dir: Path, serie: str, tome, num: float, titre: str, pages: list[bytes]) -> Path:
    """Ajoute (ou remplace) un chapitre dans le fichier de son tome ; renvoie le fichier."""
    f = fichier_tome(serie_dir, serie, tome)
    _reecrire(f, serie, tome, set(), {num: pages}, {num: titre})
    return f


def extraire(path: Path, num: float) -> list[bytes]:
    with zipfile.ZipFile(path) as zf:
        noms = sorted((n for n in zf.namelist() if num_page(n) == num), key=archives.natural_key)
        return [zf.read(n) for n in noms]


def retirer(path: Path, nums: set) -> int:
    """Enlève des chapitres du fichier ; le fichier (et son dossier vide) disparaît s'il n'en reste aucun.
    Renvoie le nombre de chapitres restants."""
    path = Path(path)
    info = lire_info(path) or {}
    reste = _reecrire(path, info.get("serie", ""), info.get("tome"), set(nums), {}, {})
    if reste == 0:
        try:
            path.parent.rmdir()
        except OSError:
            pass
    return reste


def nettoyer_titre(titre: str, num: float | None = None) -> str:
    """« ​Chapitre 3: La vieille… » → « La vieille… » (le numéro est affiché à part)."""
    t = (titre or "").replace("​", "").replace("﻿", "").strip()
    t = re.sub(r"^\d{1,4}\s*-\s*", "", t)                                   # « 003 - » des anciens fichiers
    t = re.sub(r"^(chap(itre|ter)?\.?|ch\.?)\s*\d+(?:[.,]\d+)?\s*[:.\-–—]?\s*", "", t, flags=re.I)
    return t.strip(" :-–—")
