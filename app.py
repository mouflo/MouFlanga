#!/usr/bin/env python3
"""
MouFlanga · bibliothèque et lecteur de BD / mangas (fichiers .cbz et .cbr) pour la suite MouFl.

- Parcourt le dossier des mangas : un sous-dossier = une série, un fichier = un chapitre (ou un tome)
- Lecteur intégré : une page à la fois ou défilement, sens manga ou occidental, reprise là où tu t'es arrêté
- Suivi de lecture (chapitres lus, page en cours), enregistré sur le serveur
- Connexion, Journal de diagnostic et ⚙️ Réglages identiques aux autres applis
"""
import functools
import hashlib
import io
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import uuid
import zlib
from datetime import datetime
import zipfile
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, redirect, render_template, request, send_file
from urllib.parse import quote

BASE_DIR = Path(__file__).parent
import reseau                                   # sait si on est dans les tests automatiques (reseau.EN_TEST)
if reseau.EN_TEST:
    # Les tests ne touchent JAMAIS aux vraies données : dossier jetable pour tout ce que app.py range dans data/, et les réglages du serveur
    # (secrets.env : clés, dossier de la bibliothèque…) ne sont pas chargés.
    import tempfile
    DATA_DIR = Path(tempfile.mkdtemp(prefix="mouflanga-test-"))
    os.environ.setdefault("MANGA_DIR", str(DATA_DIR / "mangas"))
else:
    DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
_SECRETS_FILE = DATA_DIR / "secrets.env"

try:
    from dotenv import load_dotenv
    for _f in (() if reseau.EN_TEST else (BASE_DIR / ".env", _SECRETS_FILE)):
        if _f.exists():
            load_dotenv(_f, override=True)
except ImportError:
    pass  # python-dotenv absent : variables d'environnement du système seulement

import archives
import reseau
import tomes
import tomes_cbz
import importer
import deux_tomes
import diag
import japscan_scraper

_VERROU_SOMMAIRES = __import__("edition").VERROU      # le même verrou que la validation à la main, l'assemblage… (voir edition.VERROU)


def _sous_verrou_infos(f):
    """La fonction lit, modifie puis réécrit le fichier d'infos d'une série : jamais en même temps qu'une autre (edition.VERROU)."""
    @functools.wraps(f)
    def g(*a, **k):
        with _VERROU_SOMMAIRES:
            return f(*a, **k)
    return g


BASE_VERSION = "2.0"
DEPART_VERSION = 120          # nombre de commits au passage en 2.0 : la version repart de 2.0.0


def get_version():
    """Version = base manuelle + nombre de commits (numéro de déploiement) + hash court."""
    try:
        import subprocess
        cwd = str(BASE_DIR)
        count = subprocess.check_output(["git", "rev-list", "--count", "HEAD"], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
        short = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
        return f"v{BASE_VERSION}.{max(0, int(count) - DEPART_VERSION)} ({short})"
    except Exception:
        return f"v{BASE_VERSION}"


APP_VERSION = get_version()
MANGA_DIR = Path(os.getenv("MANGA_DIR", "/mnt/mouflosyno/Manga"))

diag.setup_logging()
logger = logging.getLogger("mouflanga")

app = Flask(__name__)
app.json.ensure_ascii = False

import auth
auth.init_app(app, APP_VERSION)
import compression   # réponses texte compressées (gzip) : beaucoup moins de données au téléphone
compression.init_app(app)
import apparence
apparence.init_app(app)

PROGRESS_FILE = DATA_DIR / "progress.json"


def _fichier_progression():
    """Progression de la personne connectée : l'admin garde data/progress.json, chaque lecteur a son fichier."""
    from flask import has_request_context
    if has_request_context():
        import auth as _auth
        if _auth.role() == "lecteur":
            nom = re.sub(r"[^A-Za-z0-9._@+-]", "_", _auth.utilisateur() or "inconnu")
            return PROGRESS_FILE.parent / "progression" / f"{nom}.json"
    return PROGRESS_FILE


def _fichiers_progression():
    """Toutes les progressions (renommage, suppression, rangement : chaque lecteur suit aussi)."""
    d = PROGRESS_FILE.parent / "progression"
    return [PROGRESS_FILE] + (sorted(d.glob("*.json")) if d.is_dir() else [])
COVER_DIR = DATA_DIR / "covers"
_progress_lock = threading.Lock()


# ----------------------------------------------------------------------------
# Outils
# ----------------------------------------------------------------------------

def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)      # ex. data/progression/ au 1er lecteur
    tmp = Path(path).with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")      # un nom par fil : écritures simultanées
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _safe_path(rel):
    """Chemin relatif (donné par la page) -> chemin réel, uniquement À L'INTÉRIEUR du dossier des mangas."""
    root = MANGA_DIR.resolve()
    try:
        full = (root / rel).resolve()
        if any(x.startswith(".") for x in full.relative_to(root).parts):
            return None                                  # corbeille, versions en cours d'écriture, dossiers cachés
    except (ValueError, OSError, RuntimeError):
        return None
    return full if full.is_file() and full.suffix.lower() in archives.ARCHIVE_EXT else None


def _is_archive(p: Path):
    return p.suffix.lower() in archives.ARCHIVE_EXT and not p.name.startswith(".")


LOT_MIN = 400 * 1048576        # une archive .rar/.zip/.7z plus grosse que ça regroupe plusieurs tomes


def _a_importer(p: Path):
    """PDF, ou grosse archive qui regroupe plusieurs tomes : à convertir par « Organiser » avant de pouvoir être lue."""
    if p.name.startswith(".") or p.name.endswith(".tmp"):
        return False
    if p.suffix.lower() in (".pdf", ".7z"):
        return True
    try:
        return importer.est_lot(p) and p.stat().st_size > LOT_MIN
    except OSError:
        return False


_INDEX = {"series": None, "stats": {}, "racine": None, "date": 0.0, "perime": True, "en_cours": False, "dossiers": {},
          "fichiers": {}, "vrac": []}
_INDEX_VERROU = threading.Lock()
INDEX_DUREE = 20                 # secondes avant qu'un parcours du NAS soit relancé en arrière-plan
INDEX_BASE = DATA_DIR / "index.sqlite"
_RACINE_REELLE = MANGA_DIR      # seul le vrai dossier est gardé dans data/index.sqlite (pas ceux des tests)


def _scan_invalider():
    """Un fichier vient de changer (import, suppression, remplacement…) : le prochain _scan() reparcourt tout de suite."""
    _INDEX["perime"] = True


def _parcours(complet=False):
    """Parcourt le dossier des mangas (seuls les dossiers modifiés sont relus ; complet=True relit aussi la taille et la
    date de chaque fichier) et met l'index à jour."""
    import indexation
    racine = MANGA_DIR
    if not racine.is_dir():
        return {}
    garder = lambda p: _is_archive(p) or _a_importer(p)
    garder_vrac = lambda p: _is_archive(p) and not importer.est_lot(p)
    fichiers, dossiers, vrac = indexation.parcourir(racine, garder, garder_vrac, {} if complet else _INDEX["fichiers"],
                                                    {} if complet else _INDEX["dossiers"])
    return _appliquer_index(racine, fichiers, dossiers, vrac)


def _appliquer_index(racine, fichiers, dossiers, vrac):
    stats, series = {}, {}
    for nom in sorted(fichiers, key=archives.natural_key):
        lst = []
        for ch, taille, mtime in sorted(fichiers[nom], key=lambda x: archives.natural_key(x[0].split("/", 1)[1] if "/" in x[0] else x[0])):
            p = racine / ch
            lst.append(p)
            stats[p] = (taille, mtime)
        if lst:
            series[nom] = lst
    if vrac:
        lst = []
        for ch, taille, mtime in sorted(vrac, key=lambda x: archives.natural_key(x[0])):
            p = racine / ch
            lst.append(p)
            stats[p] = (taille, mtime)
        series["(Sans série)"] = lst
    maintenant = time.time()
    _INDEX.update(series=series, stats=stats, racine=str(racine), date=maintenant, perime=False,
                  fichiers=fichiers, dossiers=dossiers, vrac=vrac,
                  recent=any(m > maintenant - 2 for m in dossiers.values()))      # horloge du disque à quelques ms : on revérifie
    return series


def _reparcourir_en_arriere_plan():
    if _INDEX["en_cours"]:
        return
    _INDEX["en_cours"] = True

    def travail():
        try:
            import indexation
            avant = (_INDEX["fichiers"], _INDEX["vrac"])
            complet = time.time() - _INDEX.get("complet", 0) > 600       # de temps en temps : tailles et dates relues partout
            _parcours(complet)
            if complet:
                _INDEX["complet"] = time.time()
            if MANGA_DIR == _RACINE_REELLE and (_INDEX["fichiers"], _INDEX["vrac"]) != avant:
                indexation.enregistrer(INDEX_BASE, MANGA_DIR, _INDEX["fichiers"], _INDEX["dossiers"])
        except Exception as e:
            logger.warning("Index de la bibliothèque : %s", e)
        finally:
            _INDEX["en_cours"] = False
    threading.Thread(target=travail, daemon=True).start()


def _index_a_jour() -> bool:
    """Les dossiers connus ont-ils la même date qu'au dernier parcours ? (un stat par dossier : ≈ 10 ms pour toute la
    bibliothèque, au plus une fois par demande)."""
    from flask import g, has_request_context
    if _INDEX.get("recent") and time.time() - _INDEX["date"] < 3:
        return False                                         # dossier modifié à l'instant : sa date n'est pas encore fiable
    if has_request_context() and g.get("_index_verifie"):
        return True
    for rel, mtime in _INDEX["dossiers"].items():
        try:
            if os.stat(MANGA_DIR / rel if rel else MANGA_DIR).st_mtime != mtime:
                return False
        except OSError:
            return False
    if has_request_context():
        g._index_verifie = True
    return True


def _scan():
    """{série: [fichiers]} — chaque sous-dossier est une série ; les fichiers posés à la racine forment « (Sans série) ».
    Lu dans l'index (mémoire + data/index.sqlite) : le NAS n'est parcouru qu'après une modification ou toutes les
    INDEX_DUREE secondes, en arrière-plan (l'ancien résultat est servi pendant ce temps)."""
    if not MANGA_DIR.is_dir():
        return {}
    with _INDEX_VERROU:
        if _INDEX["racine"] != str(MANGA_DIR):                 # premier appel (ou autre dossier)
            import indexation
            _INDEX.update(series=None, perime=True, fichiers={}, dossiers={}, vrac=[], stats={}, date=0.0)
            garde = indexation.charger(INDEX_BASE, MANGA_DIR) if MANGA_DIR == _RACINE_REELLE else None
            if garde and garde[0]:                             # l'index du dernier arrêt : servi tout de suite, relu en arrière-plan
                _appliquer_index(MANGA_DIR, garde[0], garde[1], [])
                _INDEX["date"] = 0.0
        if _INDEX["series"] is not None and not _INDEX["perime"] and not _index_a_jour():
            _INDEX["perime"] = True                            # un dossier a changé de date : fichier ajouté, retiré, renommé
        if _INDEX["series"] is None or _INDEX["perime"]:
            _parcours()
            if MANGA_DIR == _RACINE_REELLE:
                import indexation
                indexation.enregistrer(INDEX_BASE, MANGA_DIR, _INDEX["fichiers"], _INDEX["dossiers"])
        elif time.time() - _INDEX["date"] > INDEX_DUREE:
            _reparcourir_en_arriere_plan()
        return {k: list(v) for k, v in _INDEX["series"].items()}


def _stat_index(p: Path):
    """(taille, date de modification) d'un fichier connu de l'index, sinon d'après le disque ; None si absent."""
    s = _INDEX["stats"].get(p)
    if s is not None:
        return s
    try:
        st = p.stat()
        return st.st_size, st.st_mtime
    except OSError:
        return None


def _rel(p: Path):
    return str(p.relative_to(MANGA_DIR))


def _numero_tome(nom):
    """Numéro de tome d'après un nom de fichier (« Gintama T01 (…) », « Toriko.Tome.38 », « Vol. 3 ») ; None pour un chapitre."""
    return importer.numero_tome(nom)


_CACHE_EDITION = {}


def _edition_vue(serie):
    """Infos d'édition de la série (relues seulement si le fichier a changé : appelé pour chaque tome d'une liste)."""
    import edition
    f = MANGA_DIR / serie / edition.FICHIER
    try:
        cle = f.stat().st_mtime_ns
    except OSError:
        return {}
    c = _CACHE_EDITION.get(serie)
    if not c or c[0] != cle:
        if len(_CACHE_EDITION) > 500:
            _CACHE_EDITION.clear()
        c = _CACHE_EDITION[serie] = (cle, edition.lire(MANGA_DIR / serie))
    return c[1]


def _edition_differente(serie):
    """Édition importée (Perfect, deluxe…) qui n'a pas le même nombre de tomes que l'édition standard connue :
    la répartition des chapitres par tome de Wikipédia ne s'applique alors pas."""
    v = _edition_vue(serie).get("volumes_attendus") or max(
        [n for n in (__import__("edition").volumes_du_titre(a) for a in _edition_vue(serie).get("archives", [])) if n] or [0]) or None
    if not v and any(re.search(r"int[ée]gral|deluxe", a, re.I) for a in _edition_vue(serie).get("archives", [])):
        # intégrale sans nombre dans son nom (« 20th Century Boys [Intégrale] ») : le nombre de tomes reçus fait foi
        v = len({m.group(1) for f in (_scan().get(serie) or [])
                 for m in [re.match(r"Tome (\d+)$", f.parent.name)] if m}) or None
    officiel = ((tomes._charger(serie) or {}).get("statut_officiel") or {}).get("volumes")
    return bool(v and officiel and int(v) != int(officiel))


_MOIS_FR = {m: i for i, m in enumerate(["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
                                          "octobre", "novembre", "décembre"], 1)}


def _date_sortie(texte):
    """« 7 janvier 2020 », « janvier 2020 » ou « 2020 » → (année, mois, jour) en texte, ou ()."""
    t = (texte or "").lower()
    a = re.search(r"\b(1[89]\d\d|20\d\d)\b", t)
    if not a:
        return ()
    mois = next((n for m, n in _MOIS_FR.items() if re.search(r"\b" + m + r"\b", t.replace("fevrier", "février").replace("aout", "août").replace("decembre", "décembre"))), 0)
    j = re.search(r"\b(\d{1,2})(?:er)?\s+[a-zéûè]+\s+" + a.group(1), t) if mois else None
    return (a.group(1), str(mois) if mois else "", j.group(1) if j else "")


def _fichier_du_tome(name, tome):
    """Chemin (relatif) du fichier du tome : tome complet ou fichier de tome assemblé par l'appli ; "" sinon."""
    groupe = tomes_cbz.dossier_tome(tome)
    for e in _entrees(_scan().get(name) or []):
        if e.get("tome") == tome or e.get("hs") == tome or e.get("groupe") == groupe:
            return e.get("path") or ""
    return ""


def _infos_tome(name, tome):
    """Tout ce que l'appli sait du tome, en balises ComicInfo.xml (écrites DANS le fichier pour qu'elles suivent quand il est
    transmis) : titre, résumé, sortie, nombre de tomes, auteur… et, dans Notes, la ligne « MouFlanga: {…} » (source du résumé,
    provenance, statut du sommaire). Mémoire seulement : aucun appel Internet."""
    import edition
    import signets
    ed = edition.lire(MANGA_DIR / name)
    if tome is None:
        return {}
    tome = int(tome)
    hs = _entree_hs(name, tome) if _est_numero_hs(tome) else None
    differente = _edition_differente(name)           # autre édition que celle de Wikipédia : titres et dates ne valent pas
    det = {"titre": hs["title"], "resume": hs.get("descriptif", "")} if hs else {} if differente else tomes.details_tome(name, tome)
    perso = (ed.get("resumes_tomes") or {}).get(str(tome)) or ""
    resume = perso or det.get("resume") or ("" if hs else tomes.resume_tome_memoire(name, tome))
    prov = provenance.lire(ed).get(str(tome)) or {}
    lu = (ed.get("sommaires") or {}).get(str(tome)) or {}
    notes = {"v": 1, "resume": "manuel" if perso else ("web" if resume else ""),
             "equipe": prov.get("equipe", ""), "origine": prov.get("origine", ""), "provenance_manuelle": bool(prov.get("manuel")),
             "sommaire": "manuel" if lu.get("manuel") else ("lu" if lu.get("chapitres") else ""), "valide_le": lu.get("valide_le", ""),
             "sortie": det.get("sortie", "")}
    isbn = _isbn_connus(ed, serie=name).get(str(tome), "")
    if ed.get("edition"):
        notes["edition"] = ed["edition"]
    if ed.get("volumes_attendus"):
        notes["volumes_attendus"] = ed["volumes_attendus"]
    st = (tomes._charger(name) or {}).get("statut_officiel") or {}
    if st.get("anilist"):                            # fiche de la série : retrouvée telle quelle depuis n'importe quel tome
        notes["serie"] = {k: v for k, v in {"anilist": st["anilist"], "choisi": bool(ed.get("anilist_choisi")),
                                            "titre": st.get("titre", ""), "titre_en": st.get("titre_en", ""),
                                            "resume": (_read_json(RESUMES, {}).get(name) or "")}.items() if v not in ("", None, False)}
    notes = {k: v for k, v in notes.items() if v not in ("", False)}
    infos = {"Title": det.get("titre", ""), "Summary": resume, "Number": "" if hs else str(tome), "Volume": "" if hs else str(tome),
             "GTIN": isbn, "Format": ed.get("edition", ""),
             "Notes": signets.MARQUE + " " + json.dumps(notes, ensure_ascii=False, separators=(",", ":"))}
    for balise, v in zip(("Year", "Month", "Day"), _date_sortie(det.get("sortie", ""))):
        infos[balise] = v
    serie = _infos_comicinfo(name) or {}
    for balise, cle in tomes_cbz._CHAMPS_COMICINFO:
        if serie.get(cle) and balise not in infos:
            infos[balise] = str(serie[cle])
    nb = _volumes_edition(name)
    if nb and not hs:
        infos["Count"] = str(nb)
    return {k: v for k, v in infos.items() if v}


tomes_cbz.INFOS_TOME = lambda serie, tome: _infos_tome(serie, tome)


def _sommaire_connu(serie, tome):
    """Les chapitres de ce tome sont connus par un sommaire : lu dans le tome, validé ou corrigé à la main, ou écrit dans le fichier."""
    if tome is None:
        return False
    return bool(((_edition_vue(serie).get("sommaires") or {}).get(str(int(tome))) or {}).get("chapitres"))


def _plage_chapitres(serie, tome):
    """« chapitres 1 à 8 » pour un tome complet : d'abord le sommaire lu dans le tome (ou corrigé à la main), sinon la
    répartition de la série si elle est déjà connue (sans aller sur Internet) et si l'édition est l'édition standard."""
    lu = ((_edition_vue(serie).get("sommaires") or {}).get(str(tome)) or {}).get("chapitres") or []
    nums = sorted(c["num"] for c in lu if c.get("num") is not None)
    if not nums:
        info = tomes._charger(serie)
        if not info or not info.get("tomes") or _edition_differente(serie):
            return [], ""
        nums = sorted(n for n, t in info["tomes"].items() if t == tome)
    if not nums:
        return [], ""
    return nums, (f"chapitre {nums[0]:g}" if len(nums) == 1 else f"chapitres {nums[0]:g} à {nums[-1]:g}")


def _tome_de_entree(e):
    if e.get("tome") is not None:
        return int(e["tome"])
    g = e.get("groupe") or ""
    return int(g.split()[1]) if g.startswith("Tome ") else None


HORS_SERIE = "Hors-série"
_MOTS_HORS_SERIE = re.compile(r"\bHS\d*\b|hors[ -]?s[ée]rie|data[ -]?book|art[ -]?book|one[ -]?shot|\bgaiden\b|side[ -]?stor(?:y|ies)", re.I)


_HS_EXPLICITE = re.compile(r"\bHS\d*\b|hors[ -]?s[ée]rie", re.I)


def _hs_du_nom(titre):
    """Hors-série d'après le nom : un mot de hors-série sans numéro de tome, ou « HS » écrit même avec un numéro."""
    return _est_hors_serie(titre) and (_numero_tome(titre) is None or bool(_HS_EXPLICITE.search(titre or "")))


def _est_hors_serie(titre):
    """« One Piece HS - Blue (Oda) (2005) … » : un hors-série, Data Book, artbook ou one-shot (nom du fichier)."""
    return bool(_MOTS_HORS_SERIE.search((titre or "").replace("_", " ")))


def _titre_hors_serie(titre):
    """« One Piece HS - Blue (Oda) (2005) [Digital-1920] (PRiNTER-PapriKa+) » → « Blue (Oda) »."""
    titre = (titre or "").replace("_", " ")
    if re.search(r"\bgaiden\b|side[ -]?stor", titre, re.I) and not re.search(r"\bHS\d*\b|hors[ -]?s[ée]rie", titre, re.I):
        court = re.sub(r"\s*\[[^\]]*\]", "", titre).strip()          # « Naruto Gaiden » : le nom entier est le titre
        return court or titre
    court = re.sub(r"^.*?(?:\bHS\d*\b|hors[ -]?s[ée]rie|data[ -]?book|art[ -]?book|one[ -]?shot)\s*[-–:]?\s*", "", titre, count=1, flags=re.I)
    court = re.sub(r"\s*\[[^\]]*\]", "", court)                                             # [Digital-1920] [Manga FR]
    court = re.sub(r"\s*\([^)]*(?:papri|printer|digital|manga fr|scan)[^)]*\)", "", court, flags=re.I)  # (PRiNTER-PapriKa+)
    court = court.strip()
    return court or titre


# Un hors-série a un numéro à lui (1000 et plus, jamais celui d'un vrai tome) : couverture, fiche ⓘ, résumé, provenance,
# sommaire… passent par les mêmes fonctions que les tomes. Tiré du nom du fichier, il ne bouge pas quand on en ajoute un.
HS_BASE = 1000


def _numeros_hs(files):
    """{chemin du fichier: numéro} pour les hors-série de la liste (deux noms qui tombent sur le même numéro : le suivant libre)."""
    out, pris = {}, set()
    hs = sorted((f for f in files if _hs_du_nom(_title_of(f))), key=lambda f: f.name.lower())
    for f in hs:
        n = HS_BASE + zlib.crc32(f.name.lower().encode()) % 8999
        while n in pris:
            n = HS_BASE + (n - HS_BASE + 1) % 8999
        pris.add(n)
        out[str(f)] = n
    return out


def _est_numero_hs(tome):
    return tome is not None and int(tome) >= HS_BASE


def _entree_hs(name, numero):
    """Entrée (liste des chapitres) du hors-série portant ce numéro, ou None."""
    return next((e for e in _entrees(_scan().get(name) or []) if e.get("hs") == int(numero)), None)


def _nom_tome(name, tome):
    """« Tome 3 » ou « Hors-série « Blue » » pour les messages."""
    if _est_numero_hs(tome):
        e = _entree_hs(name, tome)
        return f"Hors-série « {e['title']} »" if e else "Hors-série"
    return f"Tome {tome}"


def _chapitre_de_tome(e):
    """Vrai pour un chapitre à l'intérieur d'un tome (« Tome 02 »). Un hors-série est un fichier entier, pas un chapitre."""
    return bool(e.get("groupe")) and e.get("groupe") != HORS_SERIE


def _infos_serie(name):
    """Fichier d'infos d'une série (une lecture par série et par liste)."""
    import edition
    return edition.lire(MANGA_DIR / name)


def _ordre_entree(e):
    """Hors-série en premier, puis tomes dans l'ordre (tome complet ou tome à chapitres), puis chapitres « hors tome », puis le reste."""
    if e.get("groupe") == HORS_SERIE:                    # dans l'ordre de lecture : Blue (après le tome 24) avant Yellow (46)
        if e.get("apres_tome"):                          # « à lire après le tome 72 » : rangé juste après ce tome
            return (0, float(e["apres_tome"]) + 0.5, e.get("title") or "")
        return (-1, 9999, e.get("title") or "")
    t = _tome_de_entree(e)
    if t is not None:
        return (0, t, e.get("num") or 0)
    return (1 if e.get("num") is not None else 2, 0, e.get("num") or 0)


def _compte(entrees):
    """« 50 tomes », « 43 tomes + 12 chapitres », « 20 chapitres », « 43 tomes + 1 hors-série »."""
    tomes = {_tome_de_entree(e) for e in entrees} - {None}
    hs = sum(1 for e in entrees if e.get("groupe") == HORS_SERIE)
    autres = sum(1 for e in entrees if _tome_de_entree(e) is None and e.get("groupe") != HORS_SERIE)
    morceaux = []
    if tomes:
        morceaux.append(f"{len(tomes)} tome{'s' if len(tomes) > 1 else ''}")
    if autres or not (tomes or hs):
        morceaux.append(f"{autres} chapitre{'s' if autres > 1 else ''}")
    if hs:
        morceaux.append(f"{hs} hors-série")
    return " + ".join(morceaux)


_MEMO_FICHIERS = {}


def _memo_fichier(genre, f, fonction):
    """fonction(f) pour un fichier de tome, gardé tant que sa taille et sa date ne changent pas (ouvrir l'archive sur
    le NAS coûte cher : la liste de la bibliothèque le faisait pour chaque tome à chaque affichage)."""
    st = _stat_index(f)
    cle = (genre, str(f))
    c = _MEMO_FICHIERS.get(cle)
    if c and st and c[0] == st:
        return c[1]
    r = fonction(f)
    if st:
        if len(_MEMO_FICHIERS) > 20000:
            _MEMO_FICHIERS.clear()
        _MEMO_FICHIERS[cle] = (st, r)
    return r


_MEMO_ENTREES = {}


def _signature_entrees(files):
    """Ce dont dépend la liste des chapitres d'une série : ses fichiers (taille, date), son fichier d'infos et sa fiche
    de tomes. None si la liste mélange plusieurs séries (fichiers à la racine) : on ne la garde pas."""
    if not files:
        return None
    try:
        serie = files[0].relative_to(MANGA_DIR).parts[0]
        if any(f.relative_to(MANGA_DIR).parts[0] != serie for f in files):
            return None
        sig = []
        for p in (MANGA_DIR / serie / ".mouflanga-infos.json", tomes._fichier(serie)):
            try:
                st = p.stat()
                sig.append((st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append(None)
        return serie, (tuple((str(f), _stat_index(f)) for f in files), tuple(sig))
    except (ValueError, IndexError):
        return None


def _entrees(files):
    """Chapitres d'une série (gardés en mémoire tant que ses fichiers, ses infos et sa fiche ne changent pas : la liste
    de la bibliothèque les demandait plusieurs fois par série à chaque ouverture)."""
    cle = _signature_entrees(files)
    if cle is None:
        return _entrees_calculees(files)
    serie, sig = cle
    c = _MEMO_ENTREES.get(serie)
    if not c or c[0] != sig:
        if len(_MEMO_ENTREES) > 1000:
            _MEMO_ENTREES.clear()
        c = _MEMO_ENTREES[serie] = (sig, _entrees_calculees(files))
    return [dict(e) for e in c[1]]


def _entrees_calculees(files):
    """Chapitres d'une série, dans l'ordre de lecture.
    Fichier ordinaire = un chapitre (clé : son chemin). Fichier de tome = plusieurs chapitres (clé : « #12 »),
    repérés par leur première page et leur nombre de pages dans le fichier."""
    out, titres_de = [], {}
    numeros_hs = _numeros_hs(files)

    connus_de = {}

    def wiki_fr(serie, t):                       # des titres de chapitres sont-ils connus pour ce tome ? (mémoire seulement)
        if t is None or _edition_differente(serie):
            return False
        if serie not in connus_de:
            info = tomes._charger(serie) or {}
            ok = {int(k) for k, v in (((info.get("titres_tomes") or {}).get("details")) or {}).items() if v.get("chapitres")}
            titres = info.get("titres") or {}
            ok |= {int(v) for n, v in (info.get("tomes") or {}).items() if v is not None and titres.get(n)}
            connus_de[serie] = ok
        return int(t) in connus_de[serie]

    def titre_tome(serie, t):                    # « Romance Dawn » (mémoire de tomes.titres_tomes, sans aller sur Internet)
        if serie not in titres_de:
            titres_de[serie] = ((tomes._charger(serie) or {}).get("titres_tomes") or {}).get("titres") or {}
        return titres_de[serie].get(str(int(t))) if t is not None else None
    for f in files:
        rel = _rel(f)
        st = _stat_index(f)
        taille = st[0] if st else 0
        if _a_importer(f):
            out.append({"key": rel, "path": rel, "title": f"📦 {f.name}", "num": None, "groupe": None, "debut": 0,
                        "nb": None, "a_importer": True, "size_mb": round(taille / 1048576, 1)})
            continue
        info = _memo_fichier("info", f, tomes_cbz.lire_info) if f.suffix.lower() == ".cbz" else None
        if info is None:
            titre = _title_of(f)
            entree = {"key": rel, "path": rel, "title": titre, "num": _numero_chapitre(titre), "groupe": None,
                      "debut": 0, "nb": None, "size_mb": round(taille / 1048576, 1)}
            tome = _numero_tome(titre)
            if _hs_du_nom(titre):
                entree.update(groupe=HORS_SERIE, title=_titre_hors_serie(titre), hs=numeros_hs.get(str(f)))
                ident = hors_serie.lire(_infos_serie(f.relative_to(MANGA_DIR).parts[0])).get(rel)
                if ident:                                 # identifié à la main ou sur AniList/MangaDex
                    entree.update(title=ident.get("titre") or entree["title"], identifie=True, apres_tome=ident.get("apres_tome"),
                                  descriptif=ident.get("descriptif", ""),
                                  sous=" · ".join(str(x) for x in (ident.get("type"), ident.get("annee"), ident.get("auteur"), ident.get("source"),
                                                                   f"à lire après le tome {ident['apres_tome']}" if ident.get("apres_tome") else "") if x))
                if not entree.get("apres_tome"):          # place trouvée toute seule (date de sortie au Japon, AniList)
                    place = (_infos_serie(f.relative_to(MANGA_DIR).parts[0]).get("places_hs") or {}).get(f.name)
                    if place:
                        entree["apres_tome"] = place
                        entree["sous"] = " · ".join(x for x in (entree.get("sous"), f"à lire après le tome {place}") if x)
            elif tome is not None:
                # Tome complet (un fichier = un tome) : affiché « Tome 03 · chapitres 17 à 25 »
                couverts, plage = _plage_chapitres(f.relative_to(MANGA_DIR).parts[0], tome)
                nom_tome = titre_tome(f.relative_to(MANGA_DIR).parts[0], tome)
                sous = " · ".join(x for x in (f"« {nom_tome} »" if nom_tome else "", plage[:1].upper() + plage[1:] if plage else "") if x)
                entree.update(num=None, tome=tome, couverts=couverts, title=tomes_cbz.dossier_tome(tome), sous=sous,   # 2e ligne
                              titres_ch=wiki_fr(f.relative_to(MANGA_DIR).parts[0], tome)
                              or _sommaire_connu(f.relative_to(MANGA_DIR).parts[0], tome))
            out.append(entree)
            continue
        try:
            chapitres = _memo_fichier("chapitres", f, tomes_cbz.chapitres)
        except archives.ArchiveError:
            continue
        total = sum(c["nb"] for c in chapitres) or 1
        for c in chapitres:
            out.append({"key": f"#{c['num']:g}", "path": rel, "num": c["num"],
                        "title": f"Chapitre {c['num']:g}" + (f" : {c['titre']}" if c["titre"] else ""),
                        "groupe": tomes_cbz.dossier_tome(info.get("tome")), "debut": c["debut"], "nb": c["nb"],
                        "groupe_titre": titre_tome(f.relative_to(MANGA_DIR).parts[0], info.get("tome")) or "",
                        "titre_ch": c["titre"],
                        "titres_ch": bool(c["titre"]) or wiki_fr(f.relative_to(MANGA_DIR).parts[0], info.get("tome"))
                                      or _sommaire_connu(f.relative_to(MANGA_DIR).parts[0], info.get("tome")),
                        "size_mb": round(taille * c["nb"] / total / 1048576, 1)})
    dernier = max((e["tome"] for e in out if e.get("tome") is not None), default=None)
    for e in out:                                        # « Naruto Gaiden » sans autre indication : épilogue, après le dernier tome
        if e.get("groupe") == HORS_SERIE and not e.get("apres_tome") and dernier and re.search(r"\bgaiden\b", e.get("path") or "", re.I):
            e["apres_tome"] = dernier
    if any(e["groupe"] or e.get("tome") is not None for e in out):
        out.sort(key=_ordre_entree)
    return out


def _title_of(p: Path):
    return p.stem.replace("_", " ").strip()


# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", version=APP_VERSION, role=auth.role(), moi=auth.utilisateur())


@app.route("/lire")
def reader():
    return render_template("lecteur.html", version=APP_VERSION, role=auth.role())


# ----------------------------------------------------------------------------
# Bibliothèque
# ----------------------------------------------------------------------------

# ---------------------------------------------------------------- Fini / en cours / incomplet

_STATUTS = {"en_cours": False, "dernier": 0.0}


def _il_en_manque(name, entrees, etat):
    """Filtre « Il en manque » : série finie incomplète, ou en cours de parution avec des tomes déjà sortis absents
    (ex. 18 tomes sortis, on a 1 à 10 avec des trous) ; pour une série en chapitres, des trous dans les numéros."""
    if etat == "incomplet":
        return True
    if etat not in ("en_cours", "pause"):
        return False
    tomes_locaux = {int(e["tome"]) for e in entrees if e.get("tome") is not None}
    tomes_locaux |= {int(e["groupe"].split()[1]) for e in entrees if (e.get("groupe") or "").startswith("Tome ")}
    st = (tomes._charger(name) or {}).get("statut_officiel") or {}
    vol = _volumes_attendus(name)
    if tomes_locaux:
        fin = max(vol or 0, max(tomes_locaux))
        return any(t not in tomes_locaux for t in range(1, fin + 1))
    nums = [e["num"] for e in entrees if e.get("num") is not None]
    return bool(nums) and bool(_manquants([], nums)[0])


def _volumes_attendus(name):
    """Nombre de tomes de l'édition importée (torrent « Intégrale N tomes ») ; sinon celui d'AniList."""
    import edition
    infos = edition.lire(MANGA_DIR / name)
    v = infos.get("volumes_attendus")
    if not v:                                           # séries importées avant : lu dans le nom des archives gardées (« … (01-18) »)
        v = max([n for n in (edition.volumes_du_titre(a) for a in infos.get("archives", [])) if n] or [0]) or None
    return v or ((tomes._charger(name) or {}).get("statut_officiel") or {}).get("volumes")


def _volumes_edition(name):
    """Nombre de tomes de l'édition importée (nom de l'archive « … (01-18) », « Intégrale 15 tomes »), ou None."""
    import edition
    infos = edition.lire(MANGA_DIR / name)
    return infos.get("volumes_attendus") or max(
        [n for n in (edition.volumes_du_titre(a) for a in infos.get("archives", [])) if n] or [0]) or None


def _texte_volumes(name, officiel):
    """« 18 tomes dans ton édition (AniList en annonce 27) » : l'édition importée prime sur l'édition standard."""
    ed = _volumes_edition(name)
    if ed and officiel and int(ed) != int(officiel):
        return f" · {ed} tomes dans ton édition (AniList en annonce {officiel} pour l'édition standard)"
    if ed:
        return f" · {ed} tomes"
    return f" · {officiel} tome(s) annoncés" if officiel else ""


def _etat_serie(name, entrees):
    """Marque de la couverture : fini (et tout est là), incomplet (fini officiellement mais il manque des tomes ou
    chapitres), en_cours, pause, arrete ; None si inconnu. Avec un résumé lisible pour la page de la série."""
    st = (tomes._charger(name) or {}).get("statut_officiel") or {}
    statut = st.get("statut")
    if not statut:
        return None, ""
    tomes_locaux = set()
    for e in entrees:
        if e.get("tome") is not None:
            tomes_locaux.add(int(e["tome"]))
        elif e.get("groupe", "") and e["groupe"].startswith("Tome "):
            tomes_locaux.add(int(e["groupe"].split()[1]))
    chapitres = [e["num"] for e in entrees if e.get("num") is not None]
    info = tomes._charger(name) or {}
    vol = _volumes_attendus(name) or max([t for t in (info.get("tomes") or {}).values() if t is not None] or [0]) or None
    chap = st.get("chapitres") or max(info.get("tomes") or {0: None}) or None
    if statut in ("RELEASING", "NOT_YET_RELEASED"):
        return "en_cours", "En cours" + (f" · {vol} tomes sortis" if vol else "")
    if statut == "HIATUS":
        return "pause", "En pause"
    manquants = []
    if vol and tomes_locaux:
        manquants = [t for t in range(1, vol + 1) if t not in tomes_locaux]
        complet = not manquants
    elif chap and chapitres:
        complet = max(chapitres) >= chap and not _manquants([], chapitres)[0]
    else:
        complet = False
    total = f"{vol} tomes" if vol else (f"{chap} chapitres" if chap else "")
    debut = "Arrêtée" if statut == "CANCELLED" else "Terminée"
    if complet:
        return "fini", f"{debut}{f' · {total}' if total else ''} · tout est là ✅"
    if manquants:
        txt = ", ".join(_plages(manquants))
        return "incomplet", f"{debut}{f' · {total}' if total else ''} · il te manque {'le tome' if len(manquants) == 1 else 'les tomes'} {txt}"
    return "incomplet", f"{debut}{f' · {total}' if total else ''} · il manque des chapitres"


def _plages(nums):
    out, debut = [], None
    nums = sorted(nums)
    for i, n in enumerate(nums):
        if debut is None:
            debut = n
        if i == len(nums) - 1 or nums[i + 1] != n + 1:
            out.append(str(debut) if debut == n else f"{debut}–{n}")
            debut = None
    return out


def _remplir_statuts(series):
    """En arrière-plan : statut officiel (AniList) des séries qui ne l'ont pas encore, une toutes les 1,5 s."""
    if _STATUTS["en_cours"] or time.time() - _STATUTS["dernier"] < 600:
        return
    _STATUTS.update(en_cours=True, dernier=time.time())

    def travail():
        try:
            for name, tome_max in series:
                garde = tomes._charger(name) or {}
                st = garde.get("statut_officiel") or {}
                if not tomes.statut_a_jour(st):
                    tomes.statut_officiel(name, tome_max)
                    time.sleep(1.5)
                # chapitres en « Hors tome » : la répartition est recherchée de nouveau (cache passé) et ils sont rangés tout seuls
                if time.time() - garde.get("date", 0) >= tomes.DUREE and _a_ranger(name) and not _en_telechargement(name) \
                        and not (_RANGEMENTS.get(name) or {}).get("en_cours"):
                    n = _rangement_complet(name)
                    if n:
                        logger.info("Rangement automatique de « %s » : %d chapitre(s)", name, n)
                    time.sleep(1.5)
        except Exception as e:
            logger.warning("Statuts officiels : %s", e)
        finally:
            _STATUTS["en_cours"] = False
    threading.Thread(target=travail, daemon=True).start()


# Demandes fréquentes qui ne touchent à aucun fichier de la bibliothèque (page tournée, favori, lu/non lu, connexion…)
_SANS_EFFET_SUR_FICHIERS = ("/api/progress", "/api/favori", "/api/mark", "/api/login", "/api/logout", "/login", "/logout",
                            "/api/tome/resume", "/api/tome/provenance", "/api/resume", "/api/push", "/api/demande")


@app.after_request
def _index_apres_ecriture(reponse):
    """Une demande qui modifie quelque chose (envoi, suppression, import, réglage…) : l'index est reparcouru au prochain appel."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and reponse.status_code < 400 \
            and not request.path.startswith(_SANS_EFFET_SUR_FICHIERS):
        _scan_invalider()
    return reponse


TRAVAIL = [("resumes", "Résumé des tomes"), ("titres", "Titres des chapitres"), ("liens", "Liens des chapitres"),
           ("isbn", "ISBN des tomes"),
           ("doubles", "Pages simples et doubles"), ("allegement", "Allègement"), ("couvertures", "Couverture des tomes"), ("reecriture", "Réécriture des fichiers")]


def _travail_de(name, entrees=None):
    """Pense-bête de ce qui est déjà fait à la main sur une série (cases cochées, gardées dans ses infos).
    « entrees » : les chapitres de la série, si l'appelant les a déjà (évite de les recalculer)."""
    if name == "(Sans série)":
        return {"fait": [], "total": len(TRAVAIL), "complet": False}
    infos = _edition_vue(name)
    fait = [k for k, _ in TRAVAIL if (infos.get("travail") or {}).get(k)]
    suggere = [k for k in ("allegement",) if infos.get("allegement") and k not in fait]
    connus = _isbn_connus(infos, serie=name)
    numeros = _tomes_de(name, entrees) if connus else set()
    if "isbn" not in fait and numeros and all(str(t) in connus for t in numeros):
        suggere.append("isbn")                               # tous les tomes ont leur ISBN : la case peut être cochée
    return {"fait": fait, "total": len(TRAVAIL), "complet": len(fait) == len(TRAVAIL), "suggere": suggere}


def _isbn_connus(infos, google=True, serie=None):
    """{numéro de tome (texte): ISBN} déjà notés pour une série : collés à la main ou lus dans les pages d'abord, puis (google=True)
    ceux trouvés sur Internet (Wikipédia, BnF, Google Books : « serie » = le nom de la série dont on lit la mémoire), moins sûrs
    (l'édition du fichier peut être une autre)."""
    out = {str(t): c for t, c in (infos.get("isbn") or {}).items() if c}
    lus = {str(t): v["isbn"] for t, v in (infos.get("sommaires") or {}).items() if isinstance(v, dict) and v.get("isbn")}
    for t, c in lus.items():
        # Un ISBN noté qui est aussi celui d'un autre tome est faux pour l'un des deux : si la lecture des pages de ce tome
        # a trouvé un ISBN différent, qui n'est celui d'aucun autre tome, c'est lui qui est le bon.
        if t in out and out[t] != c and sum(1 for x in out.values() if x == out[t]) > 1 and c not in out.values():
            out[t] = c
        out.setdefault(t, c)
    if google:
        if serie:
            import notices
            for t, c in notices.isbn_web(serie).items():
                out.setdefault(str(t), c)
        for t, c in (infos.get("isbn_google") or {}).items():
            if c:
                out.setdefault(str(t), c)
    return out


def _contexte_identification(nom):
    """Ce que l'identification doit savoir de la série : ses tomes présents, et si ses tomes sont d'une édition particulière
    (Perfect, Deluxe… : les ISBN et résumés de l'édition standard ne valent pas, on ne cherche que cette édition)."""
    import edition
    differente = _edition_differente(nom)
    return {"tomes": _tomes_de(nom), "edition_differente": differente,
            "edition": (edition.lire(MANGA_DIR / nom).get("edition") or "") if differente else ""}


import identification
identification.CONTEXTE = _contexte_identification


def _isbn_internet_serie(nom, forcer=False):
    """ISBN et résumés des tomes cherchés sur Internet pour toute la série d'un coup (Wikipédia, BnF, puis Google Books pour ce qui
    manque encore) : bien plus rapide et léger que de lire les pages. Gardés dans la mémoire de la série (data/tomes), jamais dans
    ses fichiers : un ISBN noté à la main ou lu dans le tome passe devant. Renvoie le bilan de l'étape."""
    return identification.identifier(nom, forcer=forcer, etapes=("notices",))["notices"]


def _isbn_en_double(infos):
    """Tomes (textes) dont l'ISBN lu dans les pages est aussi celui d'un autre tome de la série : un des deux est faux
    (page de publicité ou « à suivre » lue à la place). Un ISBN noté à la main n'est jamais mis en doute."""
    from collections import Counter
    lus = {str(t): v["isbn"] for t, v in (infos.get("sommaires") or {}).items() if isinstance(v, dict) and v.get("isbn")}
    notes = infos.get("isbn") or {}
    nb = Counter(c for c in notes.values() if c)
    return {t for t, c in lus.items() if notes.get(t) == c and nb[c] > 1}


def _tomes_sans_isbn(nom, tout=False, auto=False):
    """[(tome, fichier)] des tomes complets dont l'ISBN n'est pas connu (tout=True : tous), pour les lire dans les pages.
    Un ISBN partagé par deux tomes de la série compte comme inconnu : ces tomes sont relus. auto=True (préparation de fond,
    identification) : sans les tomes dont la lecture a déjà échoué depuis moins de 90 jours (on ne relit pas pour rien)."""
    import edition
    infos = edition.lire(MANGA_DIR / nom)
    connus = {t: c for t, c in _isbn_connus(infos, serie=nom).items() if t not in _isbn_en_double(infos)}
    essais = infos.get("isbn_pages_essai") or {}
    return [(e["tome"], MANGA_DIR / e["path"])
            for e in sorted((x for x in _entrees(_scan().get(nom) or []) if x.get("tome") is not None and x.get("key") == x.get("path")
                             and not x.get("a_importer")), key=lambda x: x["tome"])
            if tout or (str(e["tome"]) not in connus and not (auto and time.time() - float(essais.get(str(e["tome"])) or 0) < 90 * 86400))]


def _lire_isbn_pages(name, a_lire):
    """Lit par OCR l'ISBN imprimé de chaque tome de la liste (dernières pages, puis premières). Avancement dans _ISBN_SERIE."""
    import edition
    import sommaire
    _ISBN_SERIE[name] = {"en_cours": True, "fait": 0, "message": f"Lecture de {len(a_lire)} tome(s)…"}
    trouves, rates = 0, []
    try:
        for tome, chemin in a_lire:
            try:
                pages = archives.pages(chemin)
                isbn = sommaire.lire_isbn(lambda i, c=chemin: archives.read_page(c, i)[0], len(pages))
            except Exception as ex:
                logger.info("ISBN du tome %s de %s : %s", tome, name, ex.__class__.__name__)
                isbn = None
            if isbn:
                infos = edition.lire(MANGA_DIR / name)           # relu à chaque tome : rien n'est écrasé
                infos.setdefault("isbn", {})[str(tome)] = isbn
                edition.ecrire(MANGA_DIR / name, infos)
                trouves += 1
            else:
                rates.append(tome)
                infos = edition.lire(MANGA_DIR / name)
                infos.setdefault("isbn_pages_essai", {})[str(tome)] = time.time()      # lu pour rien : pas relu avant 90 jours (hors bouton 🔍)
                edition.ecrire(MANGA_DIR / name, infos)
            _ISBN_SERIE[name]["fait"] += 1
        edition.invalider(MANGA_DIR / name)
        msg = f"{trouves} ISBN lu(s) sur {len(a_lire)} tome(s)." + (
            " Introuvables : tome " + ", ".join(str(t) for t in rates) + " (« 📚 Noter les ISBN de la série » pour les ajouter à la main)." if rates else "")
    except Exception as ex:
        msg = f"Échec : {ex}"
    _ISBN_SERIE[name] = {"en_cours": False, "fait": _ISBN_SERIE[name].get("fait", 0), "message": msg}


@app.route("/api/series/travail", methods=["POST"])
def api_series_travail():
    """Coche ou décoche une étape du pense-bête d'une série : {series, cle, fait}."""
    import edition
    body = request.get_json(silent=True) or {}
    name, cle = str(body.get("series", "")), str(body.get("cle", ""))
    if name not in _scan() or name == "(Sans série)" or cle not in dict(TRAVAIL):
        return jsonify({"ok": False, "error": "Série ou étape inconnue"}), 404
    d = edition.lire(MANGA_DIR / name)
    t = d.setdefault("travail", {})
    if body.get("fait"):
        t[cle] = time.strftime("%Y-%m-%d")
    else:
        t.pop(cle, None)
    edition.ecrire(MANGA_DIR / name, d)
    _CACHE_EDITION.pop(name, None)
    return jsonify({"ok": True, **_travail_de(name)})


@app.route("/api/library")
def api_library():
    if not MANGA_DIR.is_dir():
        return jsonify({"error": f"Dossier des mangas introuvable : {MANGA_DIR} (le partage est-il monté ? voir ⚙️ Réglages)", "series": []}), 200
    _organiser_auto()
    progress = _read_json(_fichier_progression(), {})
    admin = auth.role() != "lecteur"
    out, a_remplir = [], []
    for name, files in _scan().items():
        p = progress.get(name, {})
        read = set(p.get("read", []))
        total_size = 0
        newest = 0
        for f in files:
            st = _stat_index(f)
            if st:
                total_size += st[0]
                newest = max(newest, st[1])
        entrees = _entrees(files)
        etat, _ = _etat_serie(name, entrees) if name != "(Sans série)" else (None, "")
        manque = name != "(Sans série)" and _il_en_manque(name, entrees, etat)
        a_remplir.append((name, max([e["tome"] for e in entrees if e.get("tome") is not None] +
                                    [int(e["groupe"].split()[1]) for e in entrees if (e.get("groupe") or "").startswith("Tome ")] or [0]) or None))
        out.append({
            "etat": etat, "manque": manque,
            "id": name, "title": name, "chapters": len(entrees), "compte": _compte(entrees),
            "unite": "tome" if entrees and sum(e.get("tome") is not None for e in entrees) * 2 >= len(entrees) else "chapitre",
            "read": len([e for e in entrees if e["key"] in read]),
            "size_mb": round(total_size / 1048576, 1),
            "last_read": p.get("last", ""), "added": newest, "favori": bool(p.get("favori")),
            "cover": f"/api/cover?id={_q(name)}&v={int(max(newest, _couverture_mtime(name)))}",
            **_auteur_editeur(name), **_univers_de(name), **_note_de(name),
            "travail_complet": admin and _travail_de(name, entrees)["complet"],      # pense-bête : l'administrateur seul
        })
    presentes = {x["id"] for x in out}
    for nom, x in suivi.lire()["series"].items():          # ➕ séries ajoutées mais encore vides : grisées
        if nom not in presentes and auth.role() != "lecteur":
            out.append({"id": nom, "title": nom, "recherchee": True, "chapters": 0, "read": 0, "compte": "📥 Recherchée",
                        "unite": "tome", "size_mb": 0, "last_read": "", "added": time.time(), "etat": None, "manque": False,
                        "cover": (f"/api/cover?id={_q(nom)}&v={int(_couverture_mtime(nom))}" if (MANGA_DIR / nom / COUVERTURE_PERSO).is_file()
                                  else x.get("couverture") or ""), "propositions": sum(p["statut"] == "attente" for p in x.get("propositions", []))})
    _remplir_statuts([x for x in a_remplir if x[0] != "(Sans série)"])
    try:
        faites = _read_json(DATA_DIR / "archives-importees.json", {})
        racine = sum(1 for f in MANGA_DIR.iterdir() if f.is_file() and importer.est_lot(f) and not f.name.startswith(".") and f.name not in faites)
    except OSError:
        racine = 0
    return jsonify({"series": out, "a_importer": racine, "import_en_cours": _FILE_IMPORT["en_cours"]})


def _note_de(name):
    """Note de la série (sur 10) déjà enregistrée dans data/notes.json : aucun appel Internet ici."""
    import notes
    n = None if name == "(Sans série)" else notes.note(name)
    return {"note": n[0], "note_source": n[1]} if n else {"note": None, "note_source": ""}


def _identifiants_note(serie):
    """(identifiant AniList, titres à essayer) d'une série d'après sa fiche déjà en mémoire."""
    st = (tomes._charger(serie) or {}).get("statut_officiel") or {}
    titres = [t for t in (st.get("titre"), st.get("titre_en")) if t]
    try:                                               # « Kurokos Basket » → « Kuroko's Basket » : variantes du nom du dossier
        titres += [v for v in tomes._variantes(serie) if v not in titres and v != serie]
    except Exception:
        pass
    return st.get("anilist"), titres


def _auteur_editeur(name):
    """Auteur et éditeur d'après la fiche déjà en cache (aucun appel réseau ici) : pour le tri et la recherche."""
    if name == "(Sans série)":
        return {"auteur": "", "editeur": ""}
    f = (tomes._charger(name) or {}).get("fiche") or {}
    s = suivi.lire()["series"].get(name) or {}          # série ajoutée à la main : ses infos sont dans le suivi
    return {"auteur": f.get("scenario") or f.get("dessin") or s.get("auteur") or "",
            "editeur": f.get("editeur_fr") or f.get("editeur_jp") or s.get("editeur") or ""}


def _univers_de(name):
    """Univers d'une série (ex. « Seven Deadly Sins ») et son rang de lecture : dans le fichier d'infos de la série."""
    if name == "(Sans série)":
        return {"univers": "", "ordre_univers": None}
    import edition
    d = edition.lire(MANGA_DIR / name)
    return {"univers": d.get("univers") or "", "ordre_univers": d.get("ordre_univers")}


UNIVERS_FICHIER = DATA_DIR / "univers.json"          # description de chaque univers (une seule fois par univers)


@app.route("/api/univers", methods=["GET", "POST"])
def api_univers():
    """🌌 Univers : GET liste les univers et leurs séries (ordre de lecture) ; POST rattache une série à un univers
    (univers vide = la détacher). Admin seulement."""
    import edition
    if request.method == "GET":
        descriptions = _read_json(UNIVERS_FICHIER, {})
        groupes = {}
        for name in _scan():
            if name == "(Sans série)":
                continue
            u = _univers_de(name)
            if u["univers"]:
                groupes.setdefault(u["univers"], []).append({"id": name, "title": name, "ordre": u["ordre_univers"]})
        return jsonify({"univers": [{"nom": n, "description": descriptions.get(n, ""),
                                     "series": sorted(v, key=lambda x: (x["ordre"] is None, x["ordre"] or 0, x["title"]))}
                                    for n, v in sorted(groupes.items())]})
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    univers = str(body.get("univers", "")).strip()
    dossier = MANGA_DIR / name
    d = edition.lire(dossier)
    if not univers:
        d.pop("univers", None)
        d.pop("ordre_univers", None)
        edition.ecrire(dossier, d)
        return jsonify({"ok": True, "message": f"« {name} » n'est plus dans un univers."})
    if any(c in univers for c in '"$`\\\n\r'):
        return jsonify({"ok": False, "error": "Nom d'univers : caractères interdits (\" $ ` \\)."}), 400
    try:
        ordre = int(str(body.get("ordre") or "0").strip() or 0) or None
    except ValueError:
        return jsonify({"ok": False, "error": "L'ordre de lecture doit être un nombre entier (1, 2, 3…)."}), 400
    d["univers"], d["ordre_univers"] = univers, ordre
    edition.ecrire(dossier, d)
    descriptions = _read_json(UNIVERS_FICHIER, {})
    description = str(body.get("description") or "").strip()
    if description:
        descriptions[univers] = description
        UNIVERS_FICHIER.write_text(json.dumps(descriptions, ensure_ascii=False, indent=1), encoding="utf-8")
    return jsonify({"ok": True, "message": f"« {name} » est dans l'univers « {univers} »" + (f", tome {ordre} de la lecture." if ordre else ".")})


def _q(text):
    from urllib.parse import quote
    return quote(text, safe="")


COUVERTURES = ("cover.jpg", "folder.jpg", "poster.jpg", "cover.png", "folder.png", "poster.png")
COUVERTURE_PERSO = "cover.jpg"      # celle que l'utilisateur choisit depuis la page de la série


def _couverture_mtime(name):
    if name == "(Sans série)":
        return 0
    for cand in COUVERTURES:
        try:
            return (MANGA_DIR / name / cand).stat().st_mtime
        except OSError:
            continue
    return 0


_NUM_CHAPITRE = re.compile(r"chap(?:itre|ter)?\.?\s*(\d+(?:[.,]\d+)?)", re.I)
_NUM_DEBUT = re.compile(r"^\s*(\d+(?:[.,]\d+)?)")


def _numero_chapitre(titre):
    """Numéro d'un chapitre d'après son nom (« 012 - Chapitre 12 … », « Chap. 12 », « 12 - … ») ou None."""
    m = _NUM_CHAPITRE.search(titre) or _NUM_DEBUT.search(titre)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _manquants(titres, nums=None):
    """Trous dans la numérotation (chapitres, ou tomes, entiers absents entre le premier et le dernier) : « 7 », « 12–14 »."""
    if nums is None:
        nums = [_numero_chapitre(t) for t in titres]
    nums = {int(n) for n in nums if n is not None and n == int(n)}
    if len(nums) < 2:
        return [], (min(nums) if nums else None), (max(nums) if nums else None)
    trous = [n for n in range(min(nums), max(nums) + 1) if n not in nums]
    plages, debut = [], None
    for i, n in enumerate(trous):
        if debut is None:
            debut = n
        if i == len(trous) - 1 or trous[i + 1] != n + 1:
            plages.append(str(debut) if debut == n else f"{debut}–{n}")
            debut = None
    return plages, min(nums), max(nums)


_TITRES_EN_COURS = set()


def _titres_tomes_en_fond(name, chapters):
    """Titres des tomes (« Romance Dawn ») cherchés une fois, en arrière-plan ; ils s'affichent au rechargement."""
    if "unittest" in sys.modules or name in _TITRES_EN_COURS or not any(c.get("tome") is not None or c.get("groupe") for c in chapters):
        return
    garde = (tomes._charger(name) or {}).get("titres_tomes") or {}
    if "details" in garde and garde.get("v") == tomes.VERSION_TITRES:
        return
    _TITRES_EN_COURS.add(name)

    def travail():
        try:
            tomes.titres_tomes(name)
        except Exception as e:
            logger.info("Titres des tomes de %s : %s", name, e)
    threading.Thread(target=travail, daemon=True).start()


def _infos_edition(name, files):
    """Résolution, source (Digital, Scan, web), NFO : voir edition.py (analyse des pages faite une fois, en fond)."""
    if name == "(Sans série)" or not files:
        return {}
    import edition
    d = edition.infos(MANGA_DIR / name, sorted(files, key=lambda f: f.name), lancer="unittest" not in sys.modules)
    a = d.get("analyse") or {}
    source, devine = (d["source_manuelle"], False) if d.get("source_manuelle") else (a.get("source") or "", a.get("devine", True))
    return {"resolution": a.get("resolution", ""), "source": source, "devine": devine, "pourquoi": a.get("pourquoi", ""),
            "nfo": d.get("nfo", ""), "archives": d.get("archives", []), "analyse_faite": "analyse" in d,
            "edition": d.get("edition", ""), "sources_tomes": _resume_sources_tomes(d.get("sources_tomes") or {})}


def _resume_sources_tomes(st):
    """{"1": "Scantrad", "11": "Digital"} → « T1 Scantrad · T11 Digital » (tomes de même source regroupés en plages)."""
    par = {}
    for t, s in sorted(((int(k), v) for k, v in (st or {}).items() if str(k).isdigit() and v), key=lambda x: x[0]):
        par.setdefault(s, []).append(t)
    return " · ".join(f"{suivi.plage(ts)} {s}" for s, ts in sorted(par.items(), key=lambda x: x[1][0]))


def _parse_tomes(texte, presents):
    """« 1-10 », « 1,3,5-7 », « tous » → numéros de tomes présents. ValueError si le texte est incompréhensible."""
    t = str(texte or "").strip().lower()
    if t in ("tous", "tout", "*"):
        return set(presents)
    t = re.sub(r"\s*(?:-|à|a)\s*", "-", t)
    out = set()
    for part in re.split(r"[,;\s]+", t):
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,3})-(\d{1,3})", part)
        if m:
            out |= set(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            out.add(int(part))
        else:
            raise ValueError("Écris les tomes comme « 1-10 » ou « 1,3,5 » (ou « tous »).")
    return out & set(presents)


def _recalcul_source(infos, presents):
    """Quand TOUS les tomes de la série ont une source : identique partout → c'est la source de la série ; sinon « Mixte ».
    Tant qu'il en manque, la source de la série ne change pas (sauf un « Mixte » devenu faux)."""
    st = infos.get("sources_tomes") or {}
    vals = {st.get(str(t)) for t in presents}
    if presents and None not in vals:
        infos["source_manuelle"] = next(iter(vals)) if len(vals) == 1 else "Mixte"
    elif infos.get("source_manuelle") == "Mixte":
        infos.pop("source_manuelle", None)


@app.route("/api/tome/source", methods=["POST"])
def api_tome_source():
    """Source (Scantrad, Scan, Digital…) PAR TOME : {series, tomes: « 1-10 », source} ; source vide = effacer. Quand tous les tomes
    sont renseignés, la source de la série suit toute seule (identique partout, sinon « Mixte »)."""
    import edition
    body = request.get_json(silent=True) or {}
    name, source = str(body.get("series", "")), str(body.get("source", "")).strip()[:40]
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    if any(c in source for c in '"$`\\\n\r'):
        return jsonify({"ok": False, "error": "Caractères interdits."}), 400
    presents = _tomes_presents(name)
    try:
        tomes_visees = _parse_tomes(body.get("tomes", ""), presents)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    if not tomes_visees:
        return jsonify({"ok": False, "error": "Aucun de ces tomes n'est dans la série."}), 400
    infos = edition.lire(MANGA_DIR / name)
    st = infos.setdefault("sources_tomes", {})
    for t in tomes_visees:
        if source:
            st[str(t)] = source
        else:
            st.pop(str(t), None)
    if not st:
        infos.pop("sources_tomes", None)
    _recalcul_source(infos, presents)
    edition.ecrire(MANGA_DIR / name, infos)
    n = len(tomes_visees)
    msg = f"{n} tome{'s' if n > 1 else ''} : source « {source} »." if source else f"{n} tome{'s' if n > 1 else ''} : source effacée."
    if infos.get("source_manuelle") and source and all(st.get(str(t)) for t in presents):
        msg += f" Tous les tomes sont renseignés : la série est « {infos['source_manuelle']} »."
    return jsonify({"ok": True, "message": msg, "source_serie": infos.get("source_manuelle", "")})


@app.route("/api/edition", methods=["POST"])
def api_edition():
    """Corriger à la main la source d'une série (Digital, Scan, Web…) ; vide = revenir à la détection."""
    import edition
    body = request.get_json(silent=True) or {}
    name, source = str(body.get("series", "")), str(body.get("source", "")).strip()[:40]
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    d = edition.lire(MANGA_DIR / name)
    if source:
        d["source_manuelle"] = source
    else:
        d.pop("source_manuelle", None)
    edition.ecrire(MANGA_DIR / name, d)
    return jsonify({"ok": True, "message": f"Source : {source}." if source else "Source : détection automatique."})


def _infos_anime(name):
    """Anime correspondant (pour le lien vers MouFlopening et le bouton 🎵) ; rien si aucun anime n'est trouvé."""
    if name == "(Sans série)":
        return {}
    d = _anime_de(name)
    if not d:                                    # pas d'anime dans Emby : générique trouvé par generiques.py ?
        if (MANGA_DIR / name / generiques.FICHIER_SON).is_file():
            return {"anime": {"dossier": None, "nom": (generiques.lire().get(name) or {}).get("anime", ""), "generique": True}}
        return {}
    return {"anime": {"dossier": str(d), "nom": d.name, "generique": _theme_de(d) is not None},
            "mouflopening": os.getenv("MOUFLOPENING_URL", "").strip(),
            "mouflopening_externe": os.getenv("MOUFLOPENING_URL_EXTERNE", "").strip()}


@app.route("/api/series")
def api_series():
    name = request.args.get("id", "")
    files = _scan().get(name)
    vide = None                      # série ajoutée (➕) mais encore sans fichier : sa fiche s'ouvre quand même (infos, poster)
    if files is None and auth.role() != "lecteur":
        vide = suivi.lire()["series"].get(name)
        if vide is not None:
            files = []
    if files is None:
        return jsonify({"error": "Série introuvable"}), 404
    p = _read_json(_fichier_progression(), {}).get(name, {})
    read = set(p.get("read", []))
    chapters = [{**e, "read": e["key"] in read} for e in _entrees(files)]
    nums_tomes = [c.get("tome") for c in chapters if c.get("tome") is not None]
    if nums_tomes and len(nums_tomes) >= len(chapters) / 2:          # série en tomes complets
        trous, premier, dernier = _manquants([], nums_tomes)
        type_manquants = "tomes"
    else:
        trous, premier, dernier = _manquants([c["title"] for c in chapters])
        type_manquants = "chapitres"
    en_tomes = any(_chapitre_de_tome(c) for c in chapters)
    etat, etat_texte = _etat_serie(name, chapters) if name != "(Sans série)" else (None, "")
    st = (tomes._charger(name) or {}).get("statut_officiel") or {}
    perso = _read_json(RESUMES, {}).get(name)
    if perso:
        st = dict(st, resume=perso, resume_langue="perso")
    elif st.get("resume_langue") != "fr" and name != "(Sans série)":
        synopsis_nfo = (_infos_serie(name).get("nfo_infos") or {}).get("synopsis")
        suivie = suivi.lire()["series"].get(name) or {}
        du_tracker = (suivie.get("tracker") or {}).get("synopsis")
        if synopsis_nfo:                                         # synopsis français du NFO du torrent, faute d'un résumé français trouvé
            st = dict(st, resume=synopsis_nfo, resume_langue="fr")
        elif du_tracker:                                         # sinon celui de la présentation du torrent sur son tracker
            st = dict(st, resume=du_tracker, resume_langue="fr",
                      resume_source="présentation du torrent sur " + ((suivie["tracker"].get("synopsis_de") or {}).get("tracker") or "son tracker"))
    a_ranger = name != "(Sans série)" and any(not c["groupe"] and c["num"] is not None for c in chapters)
    rep = {"id": name, "title": name, "chapters": chapters,
                    "current": p.get("current", ""), "page": p.get("page", 0),
                    "rar": archives.rar_available(),
                    "en_tomes": en_tomes, "a_ranger": a_ranger, "rangement": _etat_rangement(name),
                    "etat": etat, "etat_texte": etat_texte, "etat_source": st.get("titre"),
                    "compte": _compte(chapters), "resume": st.get("resume") or "", "resume_langue": st.get("resume_langue") or "",
                    "resume_source": st.get("resume_source") if st.get("resume_langue") == "fr" and st.get("resume_source", "").startswith("présentation") else "",
                    "anilist": st.get("anilist"), "anilist_choisi": _anilist_choisi(name), "rattacher_a": _serie_mere(name),
                    "manquants": trous, "premier": premier, "dernier": dernier, "type_manquants": type_manquants,
                    "organiser": _plan_organiser(name, files) if name != "(Sans série)" else None,
                    "cover_perso": name != "(Sans série)" and (MANGA_DIR / name / COUVERTURE_PERSO).is_file(),
                    "cover_v": int(_couverture_mtime(name)),
                    "moufloster": os.getenv("MOUFLOSTER_URL", "").strip(),
                    "moufloster_externe": os.getenv("MOUFLOSTER_URL_EXTERNE", "").strip(),
                    **_infos_anime(name), "edition": _infos_edition(name, files), "_t": _titres_tomes_en_fond(name, chapters),
                    **({"travail": _travail_de(name), "travail_liste": [{"cle": k, "nom": n} for k, n in TRAVAIL]}
                       if auth.role() != "lecteur" else {}),
                    "suivi": suivi.sans_liens(suivi.lire()["series"].get(name)),
                    **({"recherchee": True, "cover_externe": vide.get("couverture") or "",
                        "compte": " · ".join(str(x) for x in ("📥 Pas encore de tomes", vide.get("annee"), vide.get("auteur") or (vide.get("tracker") or {}).get("auteur"),
                                                              vide.get("editeur") or (vide.get("tracker") or {}).get("editeur"), vide.get("source")) if x),
                        "lien": vide.get("lien") or ""} if vide is not None else {})}
    if auth.role() == "lecteur":                         # adresses des autres applis et chemins du NAS : pas pour un lecteur
        for k in ("moufloster", "moufloster_externe", "mouflopening", "mouflopening_externe"):
            rep[k] = ""
        if rep.get("anime") and rep["anime"].get("dossier"):
            rep["anime"] = dict(rep["anime"], dossier="emby")
        rep["organiser"], rep["rangement"], rep["suivi"] = None, None, None
    return jsonify(rep)


@app.route("/api/cover")
def api_cover():
    name = request.args.get("id", "")
    files = _scan().get(name)
    if not files:
        perso = MANGA_DIR / name / COUVERTURE_PERSO
        if name in suivi.lire()["series"] and perso.is_file() and name != "(Sans série)":
            return send_file(perso, max_age=3600)           # poster choisi pour une série encore vide
        return Response(status=404)
    # image « cover.jpg » / « folder.jpg » posée dans le dossier de la série : prioritaire
    sub = MANGA_DIR / name
    for cand in COUVERTURES:
        if name != "(Sans série)" and (sub / cand).is_file():
            return send_file(sub / cand, max_age=3600)
    lisibles = [e for e in _entrees(files) if not e.get("a_importer")]
    if not lisibles:
        return Response(status=404)                      # seulement des archives à importer : rien à montrer encore
    premiere = lisibles[0]
    return _vignette(MANGA_DIR / premiere["path"], premiere["debut"], name)


def _vignette(first, debut, nom, grand=False):
    """Première page d'un fichier (ou d'un chapitre de tome) en vignette JPEG gardée dans data/covers."""
    try:
        st = first.stat()
        key = hashlib.sha1(f"{first}|{st.st_mtime_ns}|{st.st_size}|{debut}|{'g' if grand else 'p'}".encode()).hexdigest()[:20]
        cached = COVER_DIR / f"{key}.jpg"
        if not cached.is_file():
            from PIL import Image
            names = archives.pages(first)
            if not names:
                return Response(status=404)
            data, _ = archives.read_page(first, debut)
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.thumbnail((1000, 1500) if grand else (360, 540))
            COVER_DIR.mkdir(parents=True, exist_ok=True)
            tmp = cached.with_suffix(".tmp")
            img.save(tmp, format="JPEG", quality=85 if grand else 82)
            os.replace(tmp, cached)
        return send_file(cached, max_age=86400)
    except archives.ArchiveError as e:
        logger.warning("Couverture impossible pour %s : %s", nom, e)
    except Exception as e:  # image abîmée, format exotique...
        logger.warning("Couverture impossible pour %s : %s: %s", nom, e.__class__.__name__, e)
    return Response(status=404)


@app.route("/api/tome/provenance", methods=["POST"])
def api_tome_provenance():
    """Note à la main d'où vient un tome (équipe, origine) : elle ne sera plus remplacée par une déduction."""
    import edition
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    try:
        tome = int(float(body.get("tome", "")))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Tome inconnu"}), 400
    equipe, origine = provenance.analyser_saisie(str(body.get("equipe", "")), str(body.get("origine", "")))
    if any(c in equipe + origine for c in '"$`\\\n\r'):
        return jsonify({"ok": False, "error": "Caractères interdits (\" $ ` \\)."}), 400
    if not equipe and not origine:
        return jsonify({"ok": False, "error": "Indique l'équipe ou l'origine."}), 400
    dossier = MANGA_DIR / name
    infos = edition.lire(dossier)
    provenance.noter(infos, tome, equipe, origine or "Saisie à la main", manuel=True, ecrase=True)
    edition.ecrire(dossier, infos)
    return jsonify({"ok": True, "message": f"{_nom_tome(name, tome)} : provenance enregistrée."})


@app.route("/api/serie/provenance", methods=["POST"])
def api_serie_provenance():
    """Provenance de TOUS les tomes de la série d'un coup : {series, texte} où texte est le nom du torrent (l'équipe qu'il
    contient en est tirée) ou seulement l'équipe. Remplace aussi les provenances déduites ; écrase une saisie à la main."""
    import edition
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    equipe, origine = provenance.analyser_saisie(str(body.get("texte", "")), str(body.get("origine", "")))
    if any(c in equipe + origine for c in '"$`\\\n\r'):
        return jsonify({"ok": False, "error": "Caractères interdits (\" $ ` \\)."}), 400
    if not equipe and not origine:
        return jsonify({"ok": False, "error": "Indique le nom du torrent ou l'équipe."}), 400
    numeros = sorted(_tomes_de(name))
    if not numeros:
        return jsonify({"ok": False, "error": "Aucun tome dans cette série."}), 400
    dossier = MANGA_DIR / name
    infos = edition.lire(dossier)
    for t in numeros:
        provenance.noter(infos, t, equipe, origine or "Saisie à la main", manuel=True, ecrase=True)
    if origine.startswith("Torrent : "):            # « Archive d'origine » des infos de l'édition : le même nom, corrigé
        infos["archives"] = [origine[len("Torrent : "):]]
    edition.ecrire(dossier, infos)
    _CACHE_EDITION.pop(name, None)
    return jsonify({"ok": True, "equipe": equipe, "origine": origine or "Saisie à la main", "tomes": len(numeros),
                    "message": f"Provenance enregistrée pour {len(numeros)} tome(s) : équipe « {equipe or '—'} », origine « {origine or 'Saisie à la main'} »"
                               + (" ; archive d'origine de l'édition mise à jour." if origine.startswith("Torrent : ") else ".")})


@app.route("/api/serie/isbn", methods=["POST"])
def api_serie_isbn():
    """Enregistre des ISBN collés à la main : « Tome 01 : 9782756058061 » (un par tome, même sur une seule ligne)."""
    import edition
    import sommaire
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    texte = str(body.get("texte", ""))
    trouves = {}
    for m in re.finditer(r"(?:tome|t|vol(?:ume)?\.?)?\s*0*(\d{1,3})\s*[:=\-–]?\s*(97[89][\d\- ]{10,16})", texte, re.I):
        c = re.sub(r"\D", "", m.group(2))[:13]
        trouves[str(int(m.group(1)))] = c
    if not trouves:
        return jsonify({"ok": False, "error": "Aucun ISBN reconnu (ex. « Tome 01 : 9782756058061 »)."}), 400
    mauvais = [t for t, c in trouves.items() if not sommaire.isbn_valide(c)]
    dossier = MANGA_DIR / name
    infos = edition.lire(dossier)
    infos.setdefault("isbn", {}).update({t: c for t, c in trouves.items() if t not in mauvais})
    edition.ecrire(dossier, infos)
    msg = f"{len(trouves) - len(mauvais)} ISBN enregistrés."
    if mauvais:
        msg += " Refusés (somme de contrôle fausse) : tome " + ", ".join(sorted(mauvais, key=int)) + "."
    return jsonify({"ok": True, "message": msg})


@app.route("/api/serie/nfo", methods=["POST"])
def api_serie_nfo():
    """Importe un NFO reçu à part (texte collé ou fichier .nfo/.txt) : titres, auteur, synopsis et ISBN des tomes."""
    import edition
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    texte = str(body.get("texte", ""))[:200_000]
    dossier = MANGA_DIR / name
    avant = len(edition.lire(dossier).get("isbn") or {})
    nfo = edition.noter_nfo(dossier, texte)
    if not nfo:
        return jsonify({"ok": False, "error": "Rien d'utile trouvé dans ce NFO (titre, auteur, synopsis ou « Tome 01 -- ISBN : 978… »)."}), 400
    apres = len(edition.lire(dossier).get("isbn") or {})
    morceaux = []
    if nfo.get("isbn"):
        morceaux.append(f"{apres - avant} ISBN ajouté(s) sur {len(nfo['isbn'])} lus" + (" (les autres étaient déjà notés)" if apres - avant < len(nfo["isbn"]) else ""))
    if nfo.get("synopsis"):
        morceaux.append("synopsis")
    morceaux += [n for c, n in (("titre_fr", "titre français"), ("auteur", "auteur")) if nfo.get(c)]
    logger.info("NFO importé pour « %s » : %s", name, ", ".join(morceaux))
    return jsonify({"ok": True, "message": "NFO importé : " + ", ".join(morceaux) + "."})


_CACHE_RESUME_FICHIER = {}                              # (chemin, date, taille) → le fichier porte-t-il un résumé ?
_CACHE_ECRIT = {}                                        # (chemin, date, taille) → le fichier porte-t-il les infos écrites par MouFlanga ?


@app.route("/api/series/travail/comptes")
def api_series_travail_comptes():
    """Pour la fenêtre « 📋 Où j'en suis » : combien de tomes sont déjà faits, étape par étape, sans ouvrir les tomes un par un.
    {total: nombre de tomes, comptes: {étape: nombre de tomes faits}}. Les étapes qui ne se comptent pas par tome sont absentes."""
    import edition
    import signets
    name = request.args.get("series", "")
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"error": "Série introuvable"}), 404
    numeros = sorted(_tomes_de(name))
    infos = edition.lire(MANGA_DIR / name)
    brut = tomes._charger(name) or {}
    details = (brut.get("titres_tomes") or {}).get("details") or {}
    manuels = infos.get("resumes_tomes") or {}
    sommaires = infos.get("sommaires") or {}
    comptes = {}
    chap = lambda t: (sommaires.get(str(t)) or {}).get("chapitres") or []
    # « fait » = sommaire VALIDÉ (bouton ✅), pas seulement lu automatiquement ni enregistré en cours de saisie
    valide = lambda t: bool((sommaires.get(str(t)) or {}).get("valide_le"))
    comptes["titres"] = sum(1 for t in numeros if chap(t) and valide(t))
    comptes["liens"] = sum(1 for t in numeros if chap(t) and valide(t) and signets.nb_signets(chap(t)) == len(chap(t)))
    comptes["isbn"] = sum(1 for t in numeros if str(t) in _isbn_connus(infos, serie=name))
    comptes["couvertures"] = sum(1 for t in numeros if couvertures_tomes.remplacement(MANGA_DIR / name, t))
    ecrits = 0
    resume_fichier = set()                                # tomes dont le fichier porte un résumé (balise Summary)
    for t in numeros:
        rel = _fichier_du_tome(name, t)
        if not rel or not rel.lower().endswith((".cbz", ".zip")):
            continue
        chemin = MANGA_DIR / rel
        try:
            st = chemin.stat()
        except OSError:
            continue
        cle = (str(chemin), st.st_mtime_ns, st.st_size)
        if cle not in _CACHE_ECRIT or cle not in _CACHE_RESUME_FICHIER:
            if len(_CACHE_ECRIT) > 5000:
                _CACHE_ECRIT.clear()
                _CACHE_RESUME_FICHIER.clear()
            du = signets.lire_infos(chemin) or {}
            _CACHE_ECRIT[cle] = bool(du.get("notes"))
            _CACHE_RESUME_FICHIER[cle] = bool((du.get("resume") or "").strip())
        ecrits += 1 if _CACHE_ECRIT[cle] else 0
        if _CACHE_RESUME_FICHIER[cle]:
            resume_fichier.add(t)
    # un résumé écrit dans le fichier du tome compte comme un résumé trouvé (comme dans la fiche du tome)
    import notices
    memoire = notices.resumes_de(name, numeros)                # tous les tomes d'un coup (Wikipédia, BnF, Google Books déjà gardés)
    comptes["resumes"] = sum(1 for t in numeros if t in resume_fichier or manuels.get(str(t)) or (details.get(str(t)) or {}).get("resume")
                             or memoire.get(int(t), ("", ""))[0])
    comptes["reecriture"] = ecrits
    return jsonify({"total": len(numeros), "comptes": comptes})


_ISBN_SERIE = {}                                         # série → avancement de « lire les ISBN de toute la série »


@app.route("/api/serie/isbn/lire", methods=["GET", "POST"])
def api_serie_isbn_lire():
    """🔍 Lit par OCR l'ISBN de chaque tome complet de la série (dernières pages, puis premières), sans toucher au sommaire.
    GET : tomes à lire et avancement. POST {series, tout} : lance en arrière-plan (tout : relire aussi les tomes qui ont déjà un ISBN)."""
    import edition
    import sommaire
    donnees = request.get_json(silent=True) or {} if request.method == "POST" else request.args
    name = str(donnees.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    connus = _isbn_connus(edition.lire(MANGA_DIR / name), serie=name)
    a_lire = _tomes_sans_isbn(name, tout=bool(donnees.get("tout")))
    if request.method == "GET":
        st = _ISBN_SERIE.get(name) or {}
        return jsonify({"total": len(a_lire), "deja": len(connus), "en_cours": bool(st.get("en_cours")), "fait": st.get("fait", 0),
                        "message": st.get("message", ""), "disponible": sommaire.disponible()})
    if (_ISBN_SERIE.get(name) or {}).get("en_cours"):
        return jsonify({"ok": False, "error": "Lecture des ISBN déjà en cours pour cette série."}), 409
    if not a_lire:
        return jsonify({"ok": False, "error": "Tous les tomes ont déjà leur ISBN."}), 400
    _ISBN_SERIE[name] = {"en_cours": True, "fait": 0, "message": "Recherche sur Internet (Wikipédia, BnF, Google Books)…"}

    def travail():
        bilan = None
        try:
            if not donnees.get("tout"):
                bilan = _isbn_internet_serie(name, forcer=True)    # Internet d'abord : bien plus rapide et léger que les pages
        except Exception as ex:
            logger.info("ISBN sur Internet de %s : %s", name, ex.__class__.__name__)
        reste = _tomes_sans_isbn(name, tout=bool(donnees.get("tout")))
        attente = bool(bilan and bilan.extra.get("attente"))        # un service n'a pas répondu : le reste viendra tout seul
        if reste and sommaire.disponible() and (donnees.get("tout") or not attente):
            _lire_isbn_pages(name, reste)                # les pages seulement pour ceux qu'Internet n'a pas
        else:
            nb = len(a_lire) - len(reste)
            _ISBN_SERIE[name] = {"en_cours": False, "fait": nb, "message": f"{nb} ISBN trouvé(s) sur Internet."
                                 + (f" {len(reste)} tome(s) sans ISBN : " + (bilan.detail if attente and bilan else "lecteur de texte absent du serveur") + "." if reste else "")}
    threading.Thread(target=travail, daemon=True).start()
    return jsonify({"ok": True, "message": "Lecture des ISBN lancée…"})


@app.route("/api/tome/couverture")
def api_tome_couverture():
    """Couverture d'un tome = première page de son fichier (déjà sur le NAS), petite ou grande (?grand=1)."""
    name = request.args.get("id", "")
    files = _scan().get(name)
    try:
        tome = int(float(request.args.get("tome", "")))
    except ValueError:
        return Response(status=400)
    if not files:
        return Response(status=404)
    remplace = couvertures_tomes.remplacement(MANGA_DIR / name, tome)
    if remplace:                                    # image choisie à la main ou trouvée en ligne (le fichier CBZ n'est pas touché)
        r = Response(remplace.read_bytes(), mimetype="image/jpeg")
        r.headers["Cache-Control"] = "no-cache"
        return r
    groupe = tomes_cbz.dossier_tome(tome)
    for e in _entrees(files):
        if not e.get("a_importer") and (e.get("tome") == tome or e.get("hs") == tome or e.get("groupe") == groupe):
            return _vignette(MANGA_DIR / e["path"], e["debut"], f"{name} tome {tome}", request.args.get("grand") == "1")
    return Response(status=404)


# ---------------- 🖼 Couvertures des tomes : images trouvées en ligne ou envoyées à la main (admin) ----------------
def _titres_serie(name):
    cache = tomes._charger(name) or {}
    st, fi = cache.get("statut_officiel") or {}, cache.get("fiche") or {}
    return [name, st.get("titre"), st.get("titre_en"), fi.get("romaji"), fi.get("titre_original")]


def _tomes_presents(name):
    return sorted({int(e["tome"]) for e in _entrees(_scan().get(name) or []) if e.get("tome") is not None and not e.get("a_importer")})


def _hs_presents(name):
    """[(numéro, titre)] des hors-série de la série, dans l'ordre de la liste."""
    return [(e["hs"], e["title"]) for e in _entrees(_scan().get(name) or []) if e.get("hs") is not None and not e.get("a_importer")]


def _preferees(candidates):
    """Français d'abord, puis anglais, puis japonais."""
    ordre = {"fr": 0, "en": 1, "ja": 2}
    return sorted(candidates, key=lambda c: ordre.get(c.get("langue"), 3))


def _retour_couvertures(name, ok="", erreur=""):
    return redirect("/couvertures?id=" + quote(name) + "&trouvees=oui" + ("&ok=" + quote(ok) if ok else "") + ("&erreur=" + quote(erreur) if erreur else ""))


# ---------------- ✂️ Découper un gros fichier (intégrale en un seul .cbz) en tomes : admin ----------------
import decoupage


def _gros_fichiers(name):
    """Fichiers de la série qui regroupent sans doute plusieurs tomes (pas des fichiers de tome de l'appli)."""
    out = []
    for f in _scan().get(name) or []:
        if f.suffix.lower() not in (".cbz", ".zip") or tomes_cbz.lire_info(f) is not None:
            continue
        try:
            if f.stat().st_size >= 300 * 1048576 or len(archives.pages(f)) >= 400:
                out.append(f)
        except (OSError, archives.ArchiveError):
            continue
    return out


def _fichier_a_decouper(name, rel):
    f = _safe_path(rel)
    return f if f is not None and name in _scan() and f in _gros_fichiers(name) else None


@app.route("/decouper")
def page_decouper():
    name = request.args.get("id", "")
    if name not in _scan() or name == "(Sans série)":
        return Response("Série introuvable", status=404)
    return render_template("decouper.html", version=APP_VERSION, nom=name,
                           fichiers=[{"rel": _rel(f), "nom": f.name} for f in _gros_fichiers(name)], choisi=request.args.get("f", ""))


@app.route("/api/decouper/infos")
def api_decouper_infos():
    name, f = request.args.get("id", ""), _fichier_a_decouper(request.args.get("id", ""), request.args.get("f", ""))
    if f is None:
        return jsonify({"error": "Fichier introuvable (ou déjà rangé en tomes)"}), 404
    plan = decoupage.plan_index(f)
    return jsonify({"pages": len(archives.pages(f)), "debuts": decoupage.debuts_depuis_plan(plan) if plan else {},
                    "chapitres": len(plan or []), "existants": sorted(_tomes_presents(name)), "partage": f.stat().st_nlink > 1,
                    "etat": decoupage.etat(f)})


@app.route("/api/miniature")
def api_miniature():
    full = _safe_path(request.args.get("path", ""))
    if full is None:
        return Response("Introuvable", status=404)
    try:
        data = decoupage.miniature(full, int(request.args.get("n", "0")))
    except (ValueError, archives.ArchiveError, OSError):
        return Response("Page introuvable", status=404)
    resp = Response(data, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


@app.route("/api/decouper", methods=["POST"])
def api_decouper():
    """Lance le découpage : {id, f, debuts: {tome: première page}, remplacer: les tomes déjà là vont à la corbeille}."""
    body = request.get_json(silent=True) or {}
    name = str(body.get("id", ""))
    f = _fichier_a_decouper(name, str(body.get("f", "")))
    if f is None:
        return jsonify({"ok": False, "error": "Fichier introuvable (ou déjà rangé en tomes)"}), 404
    try:
        debuts = {int(t): int(p) for t, p in (body.get("debuts") or {}).items()}
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Découpage invalide"}), 400
    nb = len(archives.pages(f))
    if not debuts or any(not (0 <= p < nb) or t < 1 for t, p in debuts.items()) or len(set(debuts.values())) != len(debuts):
        return jsonify({"ok": False, "error": "Indique la première page de chaque tome (pages différentes)."}), 400
    if _en_telechargement(name) or (_RANGEMENTS.get(name) or {}).get("en_cours"):
        return jsonify({"ok": False, "error": "Cette série est en cours de traitement : attends la fin."}), 409
    deja = sorted(set(debuts) & set(_tomes_presents(name)))
    if deja and not body.get("remplacer"):
        return jsonify({"ok": False, "existants": deja, "error": f"Les tomes {', '.join(map(str, deja))} existent déjà."}), 409
    try:
        for t in deja:                                   # anciens tomes : dossier entier à la corbeille (30 jours)
            d = (MANGA_DIR / name / tomes_cbz.dossier_tome(t))
            if d.is_dir():
                _vers_corbeille(d)
    except OSError as e:
        return jsonify({"ok": False, "error": f"Anciens tomes non déplacés : {e}"}), 500
    plan = decoupage.plan_index(f)
    plan = plan if plan and decoupage.debuts_depuis_plan(plan) == debuts else None     # modifié à la main : pages seulement

    def fini(ok, msg):
        if not ok:
            return ""
        import edition
        edition.invalider(MANGA_DIR / name)
        try:
            _vers_corbeille(f)
            return "Le fichier d'origine est dans la corbeille (30 jours)."
        except OSError:
            return ("Le fichier d'origine est encore partagé par qBittorrent : supprime le torrent dans qBittorrent, "
                    "puis supprime-le ici avec 🗑.")
    decoupage.decouper(f, MANGA_DIR / name, name, debuts, plan, fini)
    return jsonify({"ok": True, "message": f"Découpage en {len(debuts)} tome(s) lancé…"})


@app.route("/api/decouper/etat")
def api_decouper_etat():
    rel = request.args.get("f", "")
    if ".." in Path(rel).parts:
        return jsonify({})
    return jsonify(decoupage.etat((MANGA_DIR.resolve() / rel).resolve()))


# ---------------- 🪶 Alléger / 🧼 éclaircir les tomes d'une série : admin ----------------
import optimiser


def _fichiers_a_alleger(name):
    return [f for f in (_scan().get(name) or []) if f.suffix.lower() in (".cbz", ".zip") and not _a_importer(f)]


@app.route("/api/optimiser/fichiers")
def api_optimiser_fichiers():
    """Fichiers de la série qu'on peut alléger (un par tome), pour choisir lesquels traiter. Les hors-série (autre qualité)
    ne sont pas cochés d'avance."""
    name = request.args.get("series", "")
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"fichiers": []})
    out = []
    for f in _fichiers_a_alleger(name):
        try:
            taille = round(f.stat().st_size / 1048576, 1)
        except OSError:
            taille = 0
        m = re.match(r"Tome (\d+)$", f.parent.name)
        hors = bool(re.search(r"hors[\s_.-]*(?:s[ée]rie|tome)|\bHS\b|\bomake\b|\bartbook\b|\bbonus\b", f.parent.name + " " + f.name, re.I)) \
            or (f.parent.name != name and not m)
        out.append({"nom": f.name, "tome": int(m.group(1)) if m else None, "hors": hors, "taille_mo": taille,
                    "libelle": f"Tome {int(m.group(1)):02d}" if m else (f.parent.name if f.parent.name != name else f.stem)})
    out.sort(key=lambda x: (x["tome"] is None, x["tome"] or 0, x["nom"]))
    return jsonify({"fichiers": out})


@app.route("/api/optimiser", methods=["GET", "POST"])
def api_optimiser():
    """GET : où en est l'analyse ou l'allègement. POST {series, appliquer, amelio (« 2,2,1,1,1 »), largeur} : lance l'un ou l'autre."""
    if request.method == "GET":
        return jsonify(optimiser.etat(request.args.get("series", "")))
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    if _en_telechargement(name) or (_RANGEMENTS.get(name) or {}).get("en_cours"):
        return jsonify({"ok": False, "error": "Cette série est en cours de traitement : attends la fin."}), 409
    largeur = int(body["largeur"]) if str(body.get("largeur", "")).isdigit() and int(body["largeur"]) >= 800 else None
    appliquer = bool(body.get("appliquer"))
    eclairer = optimiser.reglages_amelioration(str(body.get("amelio", ""))) or optimiser.reglages_amelioration(bool(body.get("eclairer")))
    q = str(body.get("qualite", ""))
    manuelle = int(q) if q.isdigit() and 30 <= int(q) <= 98 else None        # réglage manuel ; vide = automatique

    def fini():
        if appliquer:
            tomes_cbz._CACHE.clear()
            import edition
            infos = edition.lire(MANGA_DIR / name)
            infos["allegement"] = {"date": datetime.now().strftime("%Y-%m-%d"), "largeur": largeur, "eclairci": bool(eclairer), "amelioration": eclairer}
            edition.ecrire(MANGA_DIR / name, infos)
            edition.invalider(MANGA_DIR / name)              # résolution et source refaites d'après les nouveaux fichiers
        try:                                                 # Telegram + notification du téléphone : on n'a pas à rester sur la page
            import notifier
            ok, msg = notifier.envoyer(f"🪶 MouFlanga : {'allègement terminé' if appliquer else 'analyse terminée'} pour « {name} » : "
                                       f"{optimiser.etat(name).get('message', '')}" + ("" if appliquer else " Ouvre la série : la ligne 🪶 en haut permet de comparer avant / après puis d'appliquer."))
            if not ok:
                logger.info("Telegram (fin d'allègement) : %s", msg)
        except Exception as e:
            logger.info("Notification de fin d'allègement : %s", e)
    fichiers = _fichiers_a_alleger(name)
    choisis = body.get("fichiers")
    if isinstance(choisis, list):                            # seulement les tomes cochés
        noms = {str(x) for x in choisis}
        fichiers = [f for f in fichiers if f.name in noms]
        if not fichiers:
            return jsonify({"ok": False, "error": "Aucun tome coché."}), 400
    infos_de = None
    if appliquer and body.get("infos"):                       # 📝 les infos du tome écrites dans la même passe que l'allègement
        import edition
        import signets
        par_chemin = {Path(c[1]): c[0] for c in _tomes_a_ecrire(name) if c[2]}     # mêmes tomes et mêmes règles que « Réécrire les infos »
        edition_infos = edition.lire(MANGA_DIR / name)

        def infos_de(f):
            tome = par_chemin.get(Path(f))
            if tome is None:
                return None
            chapitres = ((edition_infos.get("sommaires") or {}).get(str(tome)) or {}).get("chapitres") or []
            if not signets.nb_signets(chapitres):
                chapitres = None
            infos = _infos_tome(name, tome)
            return lambda ancien: signets._xml(ancien, chapitres, infos)
    if not optimiser.lancer(name, fichiers, appliquer, _vers_corbeille, eclairer, fini, largeur, manuelle, infos_de):
        return jsonify({"ok": False, "error": "Déjà en cours pour cette série."}), 409
    return jsonify({"ok": True, "message": "Allègement lancé…" if appliquer else "Analyse lancée…"})


_QUALITE_AUTO = {}
_VERROU_QUALITE_AUTO = threading.Lock()


@app.route("/api/optimiser/comparer")
def api_optimiser_comparer():
    """Une page d'un tome avant / après, avec les réglages demandés (largeur, éclaircir, qualité manuelle ou automatique).
    Sert d'aperçu en direct : aucune analyse préalable n'est nécessaire. cote = avant | apres | info."""
    name = request.args.get("series", "")
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"error": "Série introuvable."}), 404
    tomes = [f for f in _fichiers_a_alleger(name) if zipfile.is_zipfile(f)]
    if not tomes:
        if any(c[1] for c in _cbr_de(name)):
            return jsonify({"error": "Ces tomes sont des RAR (ou .cbr) : convertis-les d'abord en .cbz avec le bouton de conversion de la série."}), 404
        return jsonify({"error": "Aucun tome .cbz à comparer."}), 404
    chemin = next((f for f in tomes if f.name == request.args.get("fichier", "")), tomes[0])
    try:
        page = int(request.args.get("page", 5))
    except ValueError:
        page = 5
    zoom = None
    if request.args.get("fx") and request.args.get("fy"):
        try:
            zoom = (min(1.0, max(0.0, float(request.args["fx"]))), min(1.0, max(0.0, float(request.args["fy"]))))
        except ValueError:
            zoom = None
    largeur = int(request.args["largeur"]) if request.args.get("largeur", "").isdigit() and int(request.args["largeur"]) >= 800 else None
    eclairer = optimiser.reglages_amelioration(request.args.get("am", "")) or optimiser.reglages_amelioration(request.args.get("eclairer") == "1")
    q = request.args.get("q", "")
    try:
        if q.isdigit() and 30 <= int(q) <= 98:
            qualite, auto = int(q), False
        else:                                                # automatique : même choix que l'analyse (mis en mémoire)
            cle = (str(chemin), chemin.stat().st_mtime_ns, tuple((eclairer or {}).values()), largeur)
            with _VERROU_QUALITE_AUTO:                       # avant, après et infos arrivent ensemble : un seul calcul
                if cle not in _QUALITE_AUTO:
                    if len(_QUALITE_AUTO) > 64:
                        _QUALITE_AUTO.clear()
                    # 3 pages d'essai suffisent pour l'aperçu (l'analyse de la série en prend 8)
                    _QUALITE_AUTO[cle] = optimiser.analyser(chemin, nb_essai=3, eclairer=eclairer, largeur_max=largeur)["qualite"]
            qualite, auto = _QUALITE_AUTO[cle], True
        r = optimiser.comparer(chemin, page, qualite, eclairer, largeur, zoom)
    except Exception as e:
        logger.warning("Comparaison %s : %s", chemin.name, e)
        return jsonify({"error": f"Comparaison impossible : {e}"}), 500
    cote = request.args.get("cote", "info")
    if cote in ("avant", "apres"):
        return Response(r[cote], mimetype="image/jpeg", headers={"Cache-Control": "private, max-age=600"})
    info = {k: v for k, v in r.items() if k not in ("avant", "apres")}
    info.update(fichier=chemin.name, tomes=[f.name for f in tomes], qualite=qualite, auto=auto)
    return jsonify(info)


# ---------------- 📖 Doubles pages : découpe en simples pages (admin) ----------------
def _recaler_progression(name, rel, carte):
    """Après une découpe, la page où l'on était devient celle de la moitié qui la remplace (chaque lecteur)."""
    with _progress_lock:
        for _pf in _fichiers_progression():
            data = _read_json(_pf, {})
            p = data.get(name)
            if p and p.get("current") == rel and p.get("page") is not None:
                p["page"] = carte.get(int(p["page"]), p["page"])
                _write_json(_pf, data)


@app.route("/api/doubles")
def api_doubles():
    """Doubles pages de chaque tome de la série (vignettes à choisir) : {"tomes": [{"fichier", "pages": [{"index", "nom"}]}]}."""
    name = request.args.get("series", "")
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"error": "Série introuvable."}), 404
    import edition
    marques = edition.lire(MANGA_DIR / name).get("doubles_coupees") or {}
    tomes_ = []
    for f in _fichiers_a_alleger(name):
        if not zipfile.is_zipfile(f) or (f.stat().st_nlink > 1 and not optimiser._dossier_a_lui(f, name)):
            continue
        pages_ = optimiser.reperer_doubles(f)
        m = marques.get(f.name) or {}
        fait = m.get("taille") == f.stat().st_size             # le fichier n'a pas changé depuis la découpe : point vert
        if pages_ or fait:
            tomes_.append({"fichier": f.name, "pages": pages_, "fait": fait, "date": m.get("date", "") if fait else ""})
    return jsonify({"tomes": tomes_, "total": sum(len(t["pages"]) for t in tomes_)})


@app.route("/api/doubles/image")
def api_doubles_image():
    name = request.args.get("series", "")
    f = next((x for x in _fichiers_a_alleger(name) if x.name == request.args.get("fichier", "")), None) if name in _scan() else None
    if f is None:
        return Response("Introuvable", status=404)
    try:
        largeur = max(150, min(900, int(request.args.get("w", "300"))))
        jpeg = optimiser.apercu_page(f, int(request.args.get("n", "0")), largeur)
    except (ValueError, archives.ArchiveError) as e:
        return Response(str(e), status=404)
    return Response(jpeg, mimetype="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


@app.route("/api/doubles/paire")
def api_doubles_paire():
    """Prévisualisation d'une paire : les pages n et n+1 collées exactement comme le fera l'assemblage."""
    name = request.args.get("series", "")
    f = next((x for x in _fichiers_a_alleger(name) if x.name == request.args.get("fichier", "")), None) if name in _scan() else None
    if f is None:
        return Response("Introuvable", status=404)
    try:
        largeur = max(300, min(1400, int(request.args.get("w", "900"))))
        jpeg = optimiser.apercu_paire(f, int(request.args.get("n", "0")), request.args.get("sens", "manga") != "occidental", largeur,
                                     max(-80, min(80, int(request.args.get("a", "0")))))
    except (ValueError, archives.ArchiveError) as e:
        return Response(str(e), status=404)
    return Response(jpeg, mimetype="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


@app.route("/api/doubles/etat")
def api_doubles_etat():
    return jsonify(optimiser.coupes_etat(request.args.get("series", "")))


@app.route("/api/doubles/couper", methods=["POST"])
def api_doubles_couper():
    """POST {series, sens: "manga"|"occidental", plan: [{fichier, indices: [numéros de page à couper]}]} : découpe en arrière-plan."""
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    if _en_telechargement(name) or (_RANGEMENTS.get(name) or {}).get("en_cours") or optimiser.etat(name).get("en_cours"):
        return jsonify({"ok": False, "error": "Cette série est en cours de traitement : attends la fin."}), 409
    fichiers = {f.name: f for f in _fichiers_a_alleger(name) if zipfile.is_zipfile(f)}
    travaux = []
    for t in body.get("plan") or []:
        f = fichiers.get(str(t.get("fichier", "")))
        indices = {int(i) for i in t.get("indices") or [] if str(i).isdigit()}
        if f and indices:
            travaux.append((f, indices))
    if not travaux:
        return jsonify({"ok": False, "error": "Aucune double page à couper."}), 400
    sens = str(body.get("sens", "manga")) != "occidental"

    @_sous_verrou_infos
    def apres(chemin, carte):
        _recaler_progression(name, _rel(chemin), carte)
        import edition                                       # retenu pour le point vert de la liste des tomes
        infos = edition.lire(MANGA_DIR / name)
        _suivre_sommaire(infos, chemin, carte)
        infos.setdefault("doubles_coupees", {})[chemin.name] = {"date": datetime.now().strftime("%d/%m/%Y"), "taille": chemin.stat().st_size}
        edition.ecrire(MANGA_DIR / name, infos)
        edition.invalider(MANGA_DIR / name)
    if not optimiser.lancer_coupes(name, travaux, sens, _vers_corbeille, apres):
        return jsonify({"ok": False, "error": "Déjà en cours pour cette série."}), 409
    return jsonify({"ok": True, "message": "Découpe lancée…"})


def _assembles_chemin():
    return Path(DATA_DIR) / "assembles.json"


def _assembles_lire() -> dict:
    try:
        return json.loads(_assembles_chemin().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _marquer_assemble(name, f):
    """Retient qu'un tome a été assemblé (avec la date du fichier : un tome remis à son état d'origine n'est plus coché)."""
    try:
        d = _assembles_lire()
        st = Path(f).stat()
        d.setdefault(name, {})[Path(f).name] = [st.st_mtime_ns, st.st_size]
        _assembles_chemin().write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _est_assemble(name, f) -> bool:
    try:
        st = Path(f).stat()
        return (_assembles_lire().get(name) or {}).get(Path(f).name) == [st.st_mtime_ns, st.st_size]
    except OSError:
        return False


@app.route("/api/doubles/tomes")
def api_doubles_tomes():
    """Tomes de la série qu'on peut assembler (pages simples → doubles) : {"tomes": [{"fichier", "pages"}]}."""
    name = request.args.get("series", "")
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"error": "Série introuvable."}), 404
    out = []
    for f in _fichiers_a_alleger(name):
        if not zipfile.is_zipfile(f) or (f.stat().st_nlink > 1 and not optimiser._dossier_a_lui(f, name)):
            continue
        try:
            out.append({"fichier": f.name, "pages": len(archives.pages(f)), "fait": _est_assemble(name, f)})
        except archives.ArchiveError:
            continue
    return jsonify({"tomes": out})


@app.route("/api/doubles/assembler", methods=["POST"])
def api_doubles_assembler():
    """POST {series, sens: "manga"|"occidental", plan: [{fichier, indices: [numéro de la 1re page de chaque paire]}]} : colle chaque
    page à la suivante pour en faire une vraie double page (l'inverse de la découpe), en arrière-plan."""
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    if _en_telechargement(name) or (_RANGEMENTS.get(name) or {}).get("en_cours") or optimiser.etat(name).get("en_cours"):
        return jsonify({"ok": False, "error": "Cette série est en cours de traitement : attends la fin."}), 409
    fichiers = {f.name: f for f in _fichiers_a_alleger(name) if zipfile.is_zipfile(f)}
    travaux = []
    for t in body.get("plan") or []:
        f = fichiers.get(str(t.get("fichier", "")))
        indices = sorted({int(i) for i in t.get("indices") or [] if str(i).isdigit()})
        if f and indices:
            if any(b - a < 2 for a, b in zip(indices, indices[1:])):
                return jsonify({"ok": False, "error": "Une page ne peut être que dans une seule paire."}), 400
            ajust = {int(k): max(-80, min(80, int(v))) for k, v in (t.get("ajust") or {}).items() if str(k).isdigit() and isinstance(v, (int, float))}
            travaux.append((f, set(indices), ajust))
    if not travaux:
        return jsonify({"ok": False, "error": "Aucune paire de pages à assembler."}), 400
    sens = str(body.get("sens", "manga")) != "occidental"

    @_sous_verrou_infos
    def apres(chemin, carte):
        _recaler_progression(name, _rel(chemin), carte)
        import edition
        infos = edition.lire(MANGA_DIR / name)
        _suivre_sommaire(infos, chemin, carte)                # chapitres et sommaire gardent leur page
        edition.ecrire(MANGA_DIR / name, infos)
        edition.invalider(MANGA_DIR / name)
        _marquer_assemble(name, chemin)
    if not optimiser.lancer_coupes(name, travaux, sens, _vers_corbeille, apres, operation=optimiser.assembler):
        return jsonify({"ok": False, "error": "Déjà en cours pour cette série."}), 409
    return jsonify({"ok": True, "message": "Assemblage lancé…"})


# ---------------- 🧹 Pages parasites des scans d'équipe (crédits, recrutement, pubs) ----------------
import parasites


def _serie_occupee(name):
    return bool(_en_telechargement(name) or (_RANGEMENTS.get(name) or {}).get("en_cours") or optimiser.etat(name).get("en_cours")
                or optimiser.coupes_etat(name).get("en_cours") or parasites.etat(name).get("en_cours"))


@_sous_verrou_infos
def _chapitres_par_parasites(name, chemin, reperes):
    """Avant le retrait : la place des pages d'équipe donne les débuts de chapitres du tome (voir
    parasites.chapitres_par_reperes). Seulement pour un tome dont les chapitres ne sont pas encore connus ; le sommaire
    imprimé, s'il est lu plus tard, reste prioritaire."""
    import edition
    import sommaire
    tome = _numero_tome(chemin.name)
    if tome is None:
        tome = _numero_tome(chemin.parent.name)
    if tome is None:
        return
    t = str(int(tome))
    infos = edition.lire(MANGA_DIR / name)
    if (((infos.get("sommaires") or {}).get(t)) or {}).get("chapitres"):
        return
    try:
        fiche = tomes._charger(name) or {}
        numeros = [] if _edition_differente(name) else \
            sorted(n for n, x in (fiche.get("tomes") or {}).items() if x is not None and int(x) == int(tome))
    except Exception:
        numeros = []
    prec = [c.get("num") for c in (((infos.get("sommaires") or {}).get(str(int(tome) - 1))) or {}).get("chapitres") or []
            if c.get("num") is not None]
    chap = parasites.chapitres_par_reperes(reperes, len(archives.pages(chemin)), numeros, max(prec) if prec else None)
    if not chap:
        logger.info("Pages d'équipe de %s : chapitres non déduits (compte incertain)", chemin.name)
        return
    infos.setdefault("sommaires", {})[t] = {"chapitres": chap, "page_sommaire": None, "decalage": None,
                                            "source": "pages d'équipe", "date": datetime.now().strftime("%Y-%m-%d"),
                                            "version": sommaire.VERSION}
    edition.ecrire(MANGA_DIR / name, infos)
    logger.info("Pages d'équipe de %s : %d chapitres déduits (%g à %g)", chemin.name, len(chap), chap[0]["num"], chap[-1]["num"])


def _suivre_sommaire(infos, chemin, carte):
    """Les chapitres lus d'un tome suivent le changement de numérotation des pages (voir `edition.suivre_pages`)."""
    import edition
    tome = _numero_tome(chemin.name)
    if tome is None:
        tome = _numero_tome(chemin.parent.name)
    if tome is not None:
        edition.suivre_pages(infos, int(tome), carte)


@_sous_verrou_infos
def _apres_nettoyage(name, chemin, carte):
    """Position de lecture recalée et tome noté comme vérifié (il ne sera pas réexaminé tant qu'il ne change pas)."""
    import edition
    _recaler_progression(name, _rel(chemin), carte)
    infos = edition.lire(MANGA_DIR / name)
    infos.setdefault("parasites_verifies", {})[chemin.name] = chemin.stat().st_size
    _suivre_sommaire(infos, chemin, carte)
    edition.ecrire(MANGA_DIR / name, infos)
    edition.invalider(MANGA_DIR / name)


@app.route("/api/parasites")
def api_parasites():
    """Avancement et résultat de la recherche : groupes de pages qui se répètent, avec quelques exemples à montrer."""
    import edition
    name = request.args.get("series", "")
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"error": "Série introuvable."}), 404
    e = parasites.etat(name)
    groupes = []
    for g in e.pop("groupes", None) or []:
        p = g["pages"]
        ex = [p[0], p[len(p) // 2], p[-1]] if len(p) >= 3 else p
        groupes.append({"empreinte": g["empreinte"], "nb": len(p), "tomes": g["tomes"], "unie": g["unie"],
                        "refusee": g["refusee"], "exemples": [{"fichier": f, "index": i} for f, i in ex]})
    refusees = edition.lire(MANGA_DIR / name).get("pages_parasites") or []
    return jsonify({**e, "groupes": groupes, "refusees": len(refusees),
                    "cbr": sum(1 for f in (_scan().get(name) or []) if f.suffix.lower() == ".cbr")})


@app.route("/api/parasites/analyser", methods=["POST"])
def api_parasites_analyser():
    import edition
    name = str((request.get_json(silent=True) or {}).get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    fichiers = [f for f in _fichiers_a_alleger(name) if zipfile.is_zipfile(f)]
    if not fichiers:
        return jsonify({"ok": False, "error": "Aucun tome en .cbz à examiner (convertis d'abord les .cbr)."}), 400
    if _serie_occupee(name):
        return jsonify({"ok": False, "error": "Cette série est en cours de traitement : attends la fin."}), 409
    parasites.analyser(name, fichiers, edition.lire(MANGA_DIR / name).get("pages_parasites") or [])
    return jsonify({"ok": True, "message": "Comparaison des pages lancée…"})


@app.route("/api/parasites/retirer", methods=["POST"])
def api_parasites_retirer():
    """POST {series, empreintes: [groupes cochés]} : retire ces pages de tous les tomes ; les empreintes sont retenues
    pour nettoyer tout seuls les prochains tomes de la série."""
    import edition
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    choisies = {str(x) for x in body.get("empreintes") or []}
    groupes = [g for g in (parasites.etat(name).get("groupes") or []) if g["empreinte"] in choisies]
    if not groupes:
        return jsonify({"ok": False, "error": "Aucun groupe coché (ou la recherche est à refaire)."}), 400
    if _serie_occupee(name):
        return jsonify({"ok": False, "error": "Cette série est en cours de traitement : attends la fin."}), 409
    fichiers = {f.name: f for f in _fichiers_a_alleger(name) if zipfile.is_zipfile(f)}
    plan = {}
    for g in groupes:
        for f, i in g["pages"]:
            if f in fichiers:
                plan.setdefault(f, set()).add(i)
    infos = edition.lire(MANGA_DIR / name)
    infos["pages_parasites"] = sorted(set(infos.get("pages_parasites") or []) | {g["empreinte"] for g in groupes})
    edition.ecrire(MANGA_DIR / name, infos)
    for f in sorted(plan, key=lambda x: _numero_tome(x) or 0):   # dans l'ordre : un tome continue la suite du précédent
        try:
            _chapitres_par_parasites(name, fichiers[f], plan[f])
        except Exception as e:
            logger.warning("Chapitres d'après les pages d'équipe de %s : %s", f, e)
    edition.invalider(MANGA_DIR / name)
    parasites.lancer_nettoyage(name, [(fichiers[f], ind) for f, ind in sorted(plan.items())], _vers_corbeille,
                               lambda chemin, carte: _apres_nettoyage(name, chemin, carte))
    logger.info("Pages parasites de « %s » : %d groupe(s) refusé(s), %d tome(s) à nettoyer", name, len(groupes), len(plan))
    return jsonify({"ok": True, "message": "Nettoyage lancé…"})


@app.route("/api/parasites/page", methods=["POST"])
def api_parasites_page():
    """🗑 du lecteur : retire UNE page d'un tome (parasite isolée). POST {series, fichier: chemin relatif, index}."""
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    f = next((x for x in _fichiers_a_alleger(name) if _rel(x) == str(body.get("fichier", ""))), None)
    try:
        index = int(body.get("index"))
    except (TypeError, ValueError):
        index = -1
    if f is None or not zipfile.is_zipfile(f) or index < 0:
        return jsonify({"ok": False, "error": "Seules les pages d'un tome en .cbz peuvent être retirées."}), 400
    if _serie_occupee(name):
        return jsonify({"ok": False, "error": "Cette série est en cours de traitement : attends la fin."}), 409
    try:
        res = parasites.nettoyer_tome(f, {index}, name, _vers_corbeille)
    except Exception as e:
        logger.warning("Page %d retirée de %s : %s", index, f, e)
        return jsonify({"ok": False, "error": f"Échec : {e}"}), 500
    if "carte" not in res:
        return jsonify({"ok": False, "error": res.get("note", "Fichier non modifié.")}), 409
    _apres_nettoyage(name, f, res["carte"])
    logger.info("Page %d retirée à la main de %s", index + 1, f)
    return jsonify({"ok": True, "pages": res["pages"], "message": "Page retirée (l'ancien fichier est dans la corbeille 30 jours)."})


def _nettoyer_nouveaux_tomes():
    """Tomes arrivés depuis le dernier passage, dans les séries où des pages parasites ont été refusées : nettoyés seuls."""
    import edition
    for name in list(_scan()):
        if name == "(Sans série)":
            continue
        infos = edition.lire(MANGA_DIR / name)
        refusees, vus = infos.get("pages_parasites") or [], infos.get("parasites_verifies") or {}
        if not refusees or _serie_occupee(name):
            continue
        for f in _fichiers_a_alleger(name):
            try:
                if vus.get(f.name) == f.stat().st_size or not zipfile.is_zipfile(f):
                    continue
                indices = parasites.a_retirer(f, refusees)
                if indices:
                    _chapitres_par_parasites(name, f, indices)
                    res = parasites.nettoyer_tome(f, set(indices), name, _vers_corbeille)
                    if "carte" in res:
                        _apres_nettoyage(name, f, res["carte"])
                        logger.info("Pages parasites : %d retirée(s) toutes seules de %s", len(indices), f)
                        continue
                infos = edition.lire(MANGA_DIR / name)
                infos.setdefault("parasites_verifies", {})[f.name] = f.stat().st_size
                edition.ecrire(MANGA_DIR / name, infos)
            except Exception as e:
                logger.warning("Pages parasites de %s : %s", f, e)


def _boucle_parasites():
    """20 minutes après le démarrage, puis toutes les 6 heures."""
    time.sleep(1200)
    while True:
        try:
            _nettoyer_nouveaux_tomes()
        except Exception as e:
            logger.warning("Nettoyage automatique des pages parasites : %s", e)
        time.sleep(6 * 3600)


# ---------------- 📱 Notifications sur le téléphone (Web Push) ----------------
import notifier
import push
push._ETAT["dossier"] = DATA_DIR


def _compte_push():
    return "admin" if auth.role() == "admin" else f"lecteur:{auth.utilisateur()}"


notifier.RELAIS.append(lambda texte: push.envoyer(["admin"], "alertes", "MouFlanga", texte, "/"))


def _prevenir_demande(x, action):
    push.envoyer([f"lecteur:{x.get('par')}"], "demandes", "📮 Ta demande",
                 f"« {x.get('titre')} » : " + ("acceptée, elle sera bientôt dans la bibliothèque." if action == "accepter" else "refusée."
                                              + (f" ({x['motif']})" if x.get("motif") else "")), "/#demandes")



def _prevenir_lecteurs(nom):
    """Nouveaux tomes de « nom » : les lecteurs qui la lisent (progression) et ceux qui l'avaient demandée sont prévenus."""
    try:
        lecteurs = {f"lecteur:{f.stem}" for f in _fichiers_progression()[1:] if nom in _read_json(f, {})}
        demandeurs = {f"lecteur:{x['par']}" for x in demandes._lire()["demandes"]
                      if x.get("statut") == "accepte" and _cle_nom(x.get("titre", "")) == _cle_nom(nom)}
        url = "/#" + _q(nom)
        if demandeurs:
            push.envoyer(demandeurs, "demandes", "📚 Disponible", f"« {nom} » est dans la bibliothèque.", url)
        if lecteurs - demandeurs:
            push.envoyer(lecteurs - demandeurs, "nouveaux", "🆕 Nouveaux tomes", f"Du nouveau dans « {nom} ».", url)
    except Exception as e:
        logger.info("Notifications des lecteurs (%s) : %s", nom, e)


@app.route("/sw.js")
def service_worker():
    """Service worker (appli installée, lecture hors ligne, notifications) : servi depuis la racine pour tout couvrir."""
    from flask import send_from_directory
    resp = send_from_directory(BASE_DIR / "ui", "sw.js", max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    resp.mimetype = "application/javascript"
    return resp


@app.route("/api/push", methods=["GET", "POST"])
def api_push():
    """GET ?endpoint= : clé publique, sujets possibles et sujets choisis sur cet appareil. POST : abonner, desabonner, essai."""
    compte = _compte_push()
    sujets = push.SUJETS_ADMIN if auth.role() == "admin" else push.SUJETS_LECTEUR
    if request.method == "GET":
        a = push.abonnement(compte, request.args.get("endpoint", ""))
        try:
            cle = push.cle_publique()
        except Exception as e:
            return jsonify({"error": f"Notifications indisponibles sur le serveur : {e}"}), 500
        return jsonify({"cle": cle, "sujets": [{"id": s, "nom": push.SUJETS[s]} for s in sujets],
                        "choisis": (a or {}).get("sujets", []), "abonne": bool(a)})
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if action == "abonner":
        try:
            push.abonner(compte, body.get("abonnement"), [s for s in body.get("sujets", []) if s in sujets],
                         request.headers.get("User-Agent", ""))
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "message": "Notifications activées sur ce téléphone."})
    if action == "desabonner":
        push.desabonner(compte, str(body.get("endpoint", "")))
        return jsonify({"ok": True, "message": "Notifications coupées sur ce téléphone."})
    if action == "essai":
        push.envoyer([compte], next(iter(body.get("sujets") or sujets)), "MouFlanga", "Ceci est un essai : les notifications marchent ✅", "/")
        return jsonify({"ok": True, "message": "Notification d'essai envoyée."})
    return jsonify({"ok": False, "error": "Action inconnue"}), 400


@app.route("/couvertures")
def page_couvertures():
    name = request.args.get("id", "")
    if name not in _scan() or name == "(Sans série)":
        return Response("Série introuvable", status=404)
    trouvees = {}
    try:
        trouvees = couvertures_tomes.couvertures_en_ligne(name, _titres_serie(name), forcer=request.args.get("chercher") == "1")
    except Exception as e:
        logger.warning("Couvertures en ligne de %s : %s", name, e)
    dossier = MANGA_DIR / name
    lignes = [{"tome": n, "nom": f"Tome {n:02d}", "remplacee": bool(couvertures_tomes.remplacement(dossier, n)),
               "candidates": _preferees(trouvees.get(n, []))[:3]} for n in _tomes_presents(name)]
    lignes += [{"tome": n, "nom": f"Hors-série : {titre}", "remplacee": bool(couvertures_tomes.remplacement(dossier, n)), "candidates": []}
               for n, titre in _hs_presents(name)]                # pas de recherche en ligne : MangaDex ne range que les tomes
    return render_template("couvertures.html", version=APP_VERSION, nom=name, lignes=lignes,
                           total_trouvees=sum(1 for x in lignes if x["candidates"]),
                           ok=request.args.get("ok", ""), erreur=request.args.get("erreur", ""))


@app.route("/couvertures/envoyer", methods=["POST"])
def couvertures_envoyer():
    name = request.form.get("id", "")
    if name not in _scan():
        return Response("Série introuvable", status=404)
    try:
        tome = int(request.form.get("tome", ""))
        image = request.files.get("image")
        if not image:
            raise ValueError("Choisis une image.")
        couvertures_tomes.enregistrer_image(MANGA_DIR / name, tome, image.read())
    except ValueError as e:
        return _retour_couvertures(name, erreur=str(e))
    return _retour_couvertures(name, ok=f"{_nom_tome(name, tome)} : couverture remplacée (l'ancienne est gardée).")


@app.route("/couvertures/retirer", methods=["POST"])
def couvertures_retirer():
    name = request.form.get("id", "")
    if name not in _scan():
        return Response("Série introuvable", status=404)
    try:
        tome = int(request.form.get("tome", ""))
    except ValueError:
        return _retour_couvertures(name, erreur="Tome inconnu.")
    if couvertures_tomes.retirer(MANGA_DIR / name, tome):
        return _retour_couvertures(name, ok=f"{_nom_tome(name, tome)} : retour à la première page du fichier.")
    return _retour_couvertures(name, erreur="Ce tome n'a pas de remplacement.")


@app.route("/couvertures/appliquer", methods=["POST"])
def couvertures_appliquer():
    """Remplace la couverture d'un tome (tome + adresse trouvée), ou de tous les tomes ayant une couverture trouvée (tout=1)."""
    name = request.form.get("id", "")
    if name not in _scan():
        return Response("Série introuvable", status=404)
    dossier = MANGA_DIR / name
    if request.form.get("tout") == "1":
        trouvees = couvertures_tomes.couvertures_en_ligne(name, _titres_serie(name))
        presents = set(_tomes_presents(name))
        langue = request.form.get("langue", "auto")             # auto : français, sinon anglais, sinon japonais ; sinon seulement cette langue
        cibles, sans_langue = [], 0
        for n, c in trouvees.items():
            if not c or n not in presents:
                continue
            choix = _preferees(c) if langue == "auto" else [x for x in _preferees(c) if x.get("langue") == langue]
            if choix:
                cibles.append((n, choix[0]["url"]))
            else:
                sans_langue += 1
    else:
        try:
            cibles = [(int(request.form.get("tome", "")), request.form.get("url", ""))]
        except ValueError:
            return _retour_couvertures(name, erreur="Tome inconnu.")
    faits, echecs = 0, 0
    for n, url in cibles:
        try:
            couvertures_tomes.enregistrer_image(dossier, n, couvertures_tomes.telecharger(url))
            faits += 1
        except (ValueError, requests.RequestException, OSError) as e:
            logger.warning("Couverture du tome %s de %s : %s", n, name, e)
            echecs += 1
    if not faits:
        return _retour_couvertures(name, erreur="Aucune couverture remplacée" + (f" ({echecs} échec(s))." if echecs else ".")
                                   + (f" {sans_langue} tome(s) sans couverture dans cette langue." if request.form.get("tout") == "1" and sans_langue else ""))
    msg = f"{faits} couverture(s) remplacée(s)" + (f" · {echecs} échec(s)" if echecs else "") + " (les anciennes sont gardées)."
    if request.form.get("tout") == "1" and sans_langue:
        msg += f" {sans_langue} tome(s) sans couverture dans la langue choisie : laissés tels quels."
    return _retour_couvertures(name, ok=msg)



@app.route("/couvertures/lot", methods=["POST"])
def couvertures_lot():
    """Envoi groupé : lit le numéro de chaque image et montre l'aperçu (rien n'est enregistré avant la validation)."""
    name = request.form.get("id", "")
    if name not in _scan():
        return Response("Série introuvable", status=404)
    fichiers = [f for f in request.files.getlist("images") if f and f.filename]
    if not fichiers:
        return _retour_couvertures(name, erreur="Choisis au moins une image.")
    images, refusees = [], []
    for f in fichiers:
        octets = f.read()
        try:
            couvertures_tomes.verifier_image(octets)
            images.append(octets)
        except ValueError as e:
            refusees.append(f"{f.filename} : {e}")
    if not images:
        return _retour_couvertures(name, erreur="Aucune image utilisable dans l'envoi.")
    import sommaire
    jeton = couvertures_tomes.attente_creer(images)
    presents = _tomes_presents(name)
    lignes = []
    for i, octets in enumerate(images):
        lu = couvertures_tomes.numero_lu(octets)
        lignes.append({"index": i, "lu": lu, "suggere": lu if lu in presents else None})
    return render_template("couvertures_lot.html", version=APP_VERSION, nom=name, jeton=jeton, lignes=lignes,
                           presents=presents, hors_series=_hs_presents(name), refusees=refusees, ocr=sommaire.disponible())


@app.route("/couvertures/lot/image/<jeton>/<int:index>")
def couvertures_lot_image(jeton, index):
    octets = couvertures_tomes.attente_image(jeton, index)
    if octets is None:
        return Response("Image introuvable", status=404)
    return Response(octets, mimetype="image/jpeg")


@app.route("/couvertures/lot/valider", methods=["POST"])
def couvertures_lot_valider():
    """Enregistre les couvertures de l'aperçu : une image par tome, chaque tome une seule fois."""
    name = request.form.get("id", "")
    jeton = request.form.get("jeton", "")
    if name not in _scan():
        return Response("Série introuvable", status=404)
    presents = set(_tomes_presents(name)) | {n for n, _ in _hs_presents(name)}
    choix = {}
    for cle, valeur in request.form.items():
        if not cle.startswith("tome_") or not valeur:
            continue
        try:
            index, tome = int(cle[5:]), int(valeur)
        except ValueError:
            continue
        if tome not in presents:
            return _retour_couvertures(name, erreur=f"Le tome {tome} n'est pas dans la série.")
        if tome in choix:
            return _retour_couvertures(name, erreur=f"{_nom_tome(name, tome)} : choisi pour deux images, corrige l'aperçu.")
        choix[tome] = index
    if not choix:
        return _retour_couvertures(name, erreur="Aucune image affectée à un tome.")
    dossier = MANGA_DIR / name
    faits, echecs = 0, 0
    for tome, index in sorted(choix.items()):
        octets = couvertures_tomes.attente_image(jeton, index)
        try:
            if octets is None:
                raise ValueError("image absente (aperçu périmé ?)")
            couvertures_tomes.enregistrer_image(dossier, tome, octets)
            faits += 1
        except (ValueError, OSError) as e:
            logger.warning("Envoi groupé, tome %s de %s : %s", tome, name, e)
            echecs += 1
    couvertures_tomes.attente_supprimer(jeton)
    msg = f"{faits} couverture(s) enregistrée(s) (les anciennes sont gardées)."
    if echecs:
        return _retour_couvertures(name, erreur=f"{echecs} échec(s). " + msg)
    return _retour_couvertures(name, ok=msg)

# ---------------- 🔎 Identification des hors-série (admin) ----------------
def _hors_serie_du_fichier(name, key):
    files = _scan().get(name) or []
    return next((f for f in files if _rel(f) == key and _est_hors_serie(f.stem)), None)


@app.route("/api/hors-serie/candidats")
def api_hors_serie_candidats():
    """Résultats AniList / MangaDex pour un hors-série, d'après le titre du fichier et le nom de la série."""
    name, key = request.args.get("id", ""), request.args.get("key", "")
    if name not in _scan() or not _hors_serie_du_fichier(name, key):
        return jsonify({"error": "Hors-série introuvable"}), 404
    titre = _titre_hors_serie(_hors_serie_du_fichier(name, key).stem)
    titre = re.sub(r"\s*\([^)]*\)", "", titre).strip() or titre        # « Blue (Oda) (2005) » → « Blue »
    return jsonify({"titre": titre, "candidats": hors_serie.candidats(name, titre),
                    "identifie": hors_serie.lire(_infos_serie(name)).get(key)})


@app.route("/api/hors-serie/lien")
def api_hors_serie_lien():
    """Lit une page de fiche donnée par l'utilisatrice (Glénat, éditeur, boutique…) : titre, auteur, année, éditeur."""
    name, key = request.args.get("id", ""), request.args.get("key", "")
    if name not in _scan() or not _hors_serie_du_fichier(name, key):
        return jsonify({"error": "Hors-série introuvable"}), 404
    try:
        return jsonify({"candidat": hors_serie.lire_page((request.args.get("url") or "").strip())})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/hors-serie", methods=["POST"])
def api_hors_serie_enregistrer():
    """Garde (ou retire) l'identification d'un hors-série : titre, année, auteur, source et lien."""
    body = request.get_json(silent=True) or {}
    name, key = str(body.get("series", "")), str(body.get("key", ""))
    if name not in _scan() or not _hors_serie_du_fichier(name, key):
        return jsonify({"ok": False, "error": "Hors-série introuvable"}), 404
    import edition
    dossier = MANGA_DIR / name
    d = edition.lire(dossier)
    hs = d.get("hors_series") if isinstance(d.get("hors_series"), dict) else {}
    if body.get("action") == "retirer":
        hs.pop(key, None)
        msg = "Identification retirée."
    elif body.get("action") == "renommer":           # seul le titre affiché change : l'année, l'auteur et la source restent
        titre = str(body.get("titre", "")).strip()
        if not titre or any(c in titre for c in '"$`\\\n\r'):
            return jsonify({"ok": False, "error": "Nouveau nom : texte simple, sans guillemets ni dollar."}), 400
        garde = dict(hs.get(key) or {"source": "Renommé à la main"})
        garde["titre"] = titre
        hs[key] = garde
        msg = f"Hors-série renommé : « {titre} »."
    else:
        titre = str(body.get("titre", "")).strip()
        if not titre:
            return jsonify({"ok": False, "error": "Le titre est obligatoire."}), 400
        if any(c in titre for c in '"$`\\\n\r'):
            return jsonify({"ok": False, "error": "Titre : caractères interdits (\" $ ` \\)."}), 400
        annee = str(body.get("annee", "")).strip()
        hs[key] = {"titre": titre, "annee": int(annee) if annee.isdigit() else None,
                   "auteur": str(body.get("auteur", "")).strip()[:200], "source": str(body.get("source", "Saisie manuelle"))[:40],
                   "editeur": str(body.get("editeur", "")).strip()[:80],
                   "descriptif": str(body.get("descriptif", "")).strip()[:600], "type": str(body.get("type", "")).strip()[:30],
                   "sortie": str(body.get("sortie", "")).strip()[:40], "pages": str(body.get("pages", "")).strip()[:10],
                   "apres_tome": int(body["apres_tome"]) if str(body.get("apres_tome", "")).isdigit() else None,
                   "lien": str(body.get("lien", "")).strip() if str(body.get("lien", "")).strip().startswith(("http://", "https://")) else ""}
        msg = f"Hors-série identifié : « {titre} »."
    d["hors_series"] = hs
    edition.ecrire(dossier, d)
    return jsonify({"ok": True, "message": msg})


@app.route("/api/cover/choisir", methods=["POST"])
def api_cover_choisir():
    """Couverture choisie par l'utilisateur : image envoyée depuis le téléphone, enregistrée en cover.jpg
    dans le dossier de la série (l'ancienne cover.jpg va à la corbeille)."""
    rep, code = _enregistrer_couverture(request.form.get("id", ""), request.files.get("image"))
    return jsonify(rep), code


def _enregistrer_couverture(name, envoi):
    """Enregistre l'image envoyée (fichier de formulaire) comme couverture de la série. Renvoie (réponse, code)."""
    if (name not in _scan() and name not in suivi.lire()["series"]) or name == "(Sans série)":
        return {"ok": False, "error": "Série introuvable"}, 404
    if envoi is None:
        return {"ok": False, "error": "Aucune image reçue"}, 400
    donnees = envoi.read(25 * 1048576 + 1)
    if len(donnees) > 25 * 1048576:
        return {"ok": False, "error": "Image trop lourde (25 Mo au plus)"}, 400
    try:
        from PIL import Image, ImageOps
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(donnees))).convert("RGB")
        img.thumbnail((1200, 1800))
    except Exception:
        return {"ok": False, "error": "Ce fichier n'est pas une image lisible (JPEG, PNG, WebP…)"}, 400
    cible = MANGA_DIR / name / COUVERTURE_PERSO
    try:
        cible.parent.mkdir(parents=True, exist_ok=True)      # série ajoutée, encore sans dossier
        if cible.exists():
            _vers_corbeille(cible)
        tmp = cible.with_suffix(".tmp")
        img.save(tmp, format="JPEG", quality=88)
        os.replace(tmp, cible)
    except OSError as e:
        logger.warning("Couverture impossible à enregistrer pour %s : %s", name, e)
        return {"ok": False, "error": f"Enregistrement impossible : {e.strerror or e}"}, 500
    logger.info("Nouvelle couverture pour %s", name)
    return {"ok": True, "v": int(cible.stat().st_mtime)}, 200


@app.route("/api/cover/automatique", methods=["POST"])
def api_cover_automatique():
    """Revenir à la couverture automatique (1re page du 1er chapitre) : cover.jpg va à la corbeille."""
    name = str((request.get_json(silent=True) or {}).get("id", ""))
    if (name not in _scan() and name not in suivi.lire()["series"]) or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    cible = MANGA_DIR / name / COUVERTURE_PERSO
    if cible.exists():
        try:
            _vers_corbeille(cible)
        except OSError as e:
            return jsonify({"ok": False, "error": f"Impossible : {e.strerror or e}"}), 500
        logger.info("Couverture automatique rétablie pour %s", name)
    return jsonify({"ok": True})


# ----------------------------------------------------------------------------
# Lecteur
# ----------------------------------------------------------------------------

@app.route("/api/pages")
def api_pages():
    full = _safe_path(request.args.get("path", ""))
    if full is None:
        return jsonify({"error": "Chapitre introuvable"}), 404
    try:
        n = len(archives.pages(full))
    except archives.ArchiveError as e:
        logger.warning("Lecture impossible de %s : %s", full.name, e)
        return jsonify({"error": str(e)}), 422
    if n == 0:
        return jsonify({"error": "Aucune image dans ce fichier"}), 422
    return jsonify({"count": n, "title": _title_of(full)})


@app.route("/api/page")
def api_page():
    full = _safe_path(request.args.get("path", ""))
    if full is None:
        return Response("Chapitre introuvable", status=404)
    try:
        index = int(request.args.get("n", "0"))
        data, mime = archives.read_page(full, index)
    except ValueError:
        return Response("Numéro de page invalide", status=400)
    except archives.ArchiveError as e:
        return Response(str(e), status=404)
    resp = Response(data, mimetype=mime)
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@app.route("/api/progress", methods=["POST"])
def api_progress():
    body = request.get_json(silent=True) or {}
    series, rel = str(body.get("series", "")), str(body.get("path", ""))
    # « #12 » : chapitre d'un fichier de tome (la position reste juste quand le tome est recomplété)
    chapitre_tome = bool(re.fullmatch(r"#\d+(\.\d+)?", rel)) and (MANGA_DIR / series).is_dir() and "/" not in series
    if not series or not (chapitre_tome or _safe_path(rel) is not None):
        return jsonify({"ok": False, "error": "Chapitre inconnu"}), 400
    try:
        page = max(0, int(body.get("page", 0)))
    except (TypeError, ValueError):
        page = 0
    with _progress_lock:
        data = _read_json(_fichier_progression(), {})
        p = data.setdefault(series, {})
        p["current"], p["page"], p["last"] = rel, page, datetime.now().strftime("%Y-%m-%d %H:%M")
        read = set(p.get("read", []))
        if body.get("finished"):
            read.add(rel)
        p["read"] = sorted(read)
        _write_json(_fichier_progression(), data)
    return jsonify({"ok": True})


@app.route("/api/favori", methods=["POST"])
def api_favori():
    """⭐ Mettre une série en favori (ou l'en retirer) : propre à chaque compte, rangé avec sa progression."""
    body = request.get_json(silent=True) or {}
    series = str(body.get("series", ""))
    if series not in _scan() and series not in suivi.lire()["series"]:
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    with _progress_lock:
        data = _read_json(_fichier_progression(), {})
        p = data.setdefault(series, {})
        if body.get("favori", True):
            p["favori"] = True
        else:
            p.pop("favori", None)
            if not p:
                data.pop(series, None)
        _write_json(_fichier_progression(), data)
    return jsonify({"ok": True, "favori": bool(body.get("favori", True))})


@app.route("/api/mark", methods=["POST"])
def api_mark():
    """Marquer des chapitres comme lus / non lus : un seul (path) ou toute la série (all)."""
    body = request.get_json(silent=True) or {}
    series = str(body.get("series", ""))
    files = _scan().get(series)
    if files is None:
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    value = bool(body.get("read", True))
    valid = {e["key"] for e in _entrees(files)}
    targets = list(valid) if body.get("all") else [str(body.get("path", ""))]
    with _progress_lock:
        data = _read_json(_fichier_progression(), {})
        p = data.setdefault(series, {})
        read = set(p.get("read", []))
        for t in targets:
            if t in valid:
                (read.add if value else read.discard)(t)
        p["read"] = sorted(read)
        if not value and body.get("all"):
            p.pop("current", None)
            p["page"] = 0
        _write_json(_fichier_progression(), data)
    return jsonify({"ok": True})


CORBEILLE = ".corbeille"        # dans le dossier des mangas ; ignorée par la bibliothèque (commence par un point)
CORBEILLE_JOURS = 30            # ce qui est mis à la corbeille est effacé pour de bon au bout de 30 jours


def _vers_corbeille(p: Path):
    """Déplace un fichier ou un dossier de série dans .corbeille/<date>/ (même chemin relatif)."""
    import shutil
    dest = MANGA_DIR / CORBEILLE / datetime.now().strftime("%Y-%m-%d") / p.relative_to(MANGA_DIR)
    if dest.exists():
        dest = dest.with_name(f"{dest.stem} ({int(time.time())}){dest.suffix}" if p.is_file()
                              else f"{dest.name} ({int(time.time())})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(dest))


def _vider_corbeille():
    """Efface les jours de corbeille plus vieux que CORBEILLE_JOURS."""
    import shutil
    racine = MANGA_DIR / CORBEILLE
    if not racine.is_dir():
        return
    limite = time.time() - CORBEILLE_JOURS * 86400
    for d in racine.iterdir():
        try:
            if d.is_dir() and datetime.strptime(d.name, "%Y-%m-%d").timestamp() < limite:
                shutil.rmtree(d, ignore_errors=True)
        except ValueError:
            continue


@app.route("/api/delete", methods=["POST"])
def api_delete():
    """Met à la corbeille un chapitre (path) ou toute une série (all)."""
    body = request.get_json(silent=True) or {}
    series = str(body.get("series", ""))
    files = _scan().get(series)
    if files is None:
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    for j in list(japscan_scraper.download_jobs.values()):
        if j.get("status") == "running" and japscan_scraper.nom_sur(japscan_scraper.titre_serie(j.get("title") or "")) == series:
            return jsonify({"ok": False, "error": "Cette série est en cours de téléchargement : annule-le d'abord (onglet « En cours »)."}), 409
    if body.get("all"):
        cibles = files if series == "(Sans série)" else [MANGA_DIR / series]
        retires = {_rel(f) for f in files}
    else:
        rel = str(body.get("path", ""))
        entree = next((e for e in _entrees(files) if e["key"] == rel), None)
        if entree is None:
            return jsonify({"ok": False, "error": "Chapitre introuvable"}), 404
        retires = {rel}
        if _chapitre_de_tome(entree):
            # Chapitre d'un fichier de tome : ses pages partent à la corbeille dans un .cbz à part
            try:
                fichier = MANGA_DIR / entree["path"]
                pages = tomes_cbz.extraire(fichier, entree["num"])
                copie = MANGA_DIR / series / f"Chapitre {entree['num']:g}.cbz"
                japscan_scraper.JapscanScraper(MANGA_DIR).create_cbz(pages, copie)
                _vers_corbeille(copie)
                tomes_cbz.retirer(fichier, {entree["num"]})
            except (OSError, archives.ArchiveError) as e:
                logger.warning("Suppression impossible dans %s : %s", series, e)
                return jsonify({"ok": False, "error": f"Suppression impossible : {e}"}), 500
        cibles = [] if _chapitre_de_tome(entree) else [MANGA_DIR / entree["path"]]
    try:
        for c in cibles:
            _vers_corbeille(c)
    except OSError as e:
        logger.warning("Suppression impossible dans %s : %s", series, e)
        return jsonify({"ok": False, "error": f"Suppression impossible : {e.strerror or e}"}), 500
    logger.info("Mis à la corbeille : %s (%d fichier(s))", series if body.get("all") else next(iter(retires)), len(retires))
    if body.get("all") and suivi.retirer(series):
        logger.info("« %s » n'est plus suivie (série supprimée)", series)

    with _progress_lock:
        for _pf in _fichiers_progression():          # admin et chaque lecteur
            data = _read_json(_pf, {})
            p = data.get(series)
            if p is not None:
                if body.get("all"):
                    data.pop(series)
                else:
                    p["read"] = [r for r in p.get("read", []) if r not in retires]
                    if p.get("current") in retires:
                        p.pop("current", None)
                        p["page"] = 0
                _write_json(_pf, data)
    _vider_corbeille()
    return jsonify({"ok": True, "supprimes": len(retires), "jours": CORBEILLE_JOURS})


# ============================================================================
# Japscan - Scraper et téléchargement
# ============================================================================

LISTE_CACHE = DATA_DIR / "mangas-japscan.json"
LISTE_DUREE = 6 * 3600          # la liste des mangas change peu : on la garde 6 heures
CHAPITRES_DUREE = 3600          # les chapitres d'une série : 1 heure
_LISTE_VERROU = threading.Lock()
_CHAPITRES_VERROU = threading.Lock()
_CHAPITRES_CACHE = {}


def _dossier_serie(titre):
    """Dossier d'une série téléchargée. Un ancien dossier « Titre 247 » (nommé d'après le dernier chapitre,
    ancien fonctionnement) est renommé « Titre », avec la progression de lecture."""
    nom = japscan_scraper.nom_sur(japscan_scraper.titre_serie(titre))
    cible = MANGA_DIR / nom
    if cible.exists() or not MANGA_DIR.is_dir():
        return cible
    try:
        anciens = [d for d in MANGA_DIR.iterdir()
                   if d.is_dir() and re.fullmatch(re.escape(nom) + r" \d+(\.\d+)?", d.name)]
    except OSError:
        return cible
    if len(anciens) != 1:
        return cible
    try:
        anciens[0].rename(cible)
    except OSError as e:
        logger.warning("Renommage de %s impossible : %s", anciens[0].name, e)
        return anciens[0]
    logger.info("Dossier « %s » renommé « %s »", anciens[0].name, nom)
    with _progress_lock:
        for _pf in _fichiers_progression():          # admin et chaque lecteur
            data = _read_json(_pf, {})
            if anciens[0].name in data:
                p = data.pop(anciens[0].name)
                avant = anciens[0].name + "/"
                p["read"] = [nom + "/" + r[len(avant):] if r.startswith(avant) else r for r in p.get("read", [])]
                if str(p.get("current", "")).startswith(avant):
                    p["current"] = nom + "/" + p["current"][len(avant):]
                data[nom] = p
                _write_json(_pf, data)
    return cible


def _deja_telecharges(titre):
    """Numéros des chapitres déjà présents dans la série (fichiers de tome ou un fichier par chapitre)."""
    nom = _dossier_serie(titre).name
    deja = set()
    for e in _entrees(_scan().get(nom) or []):
        if e["num"] is not None:
            deja.add(e["num"])
        deja.update(e.get("couverts") or [])
    return deja


# ---------------------------------------------------------------- Tomes

_RANGEMENTS = {}               # série -> état du rangement en cours (pour la page de la série)
_RANGEMENT_VERROU = threading.Lock()


def _preparer_tomes(nom):
    """Avant un téléchargement : cherche la répartition en tomes et range ce qui est déjà là."""
    info = tomes.chercher(nom)
    if info:
        _ranger_en_tomes(nom, info)
    return info


def _ranger_en_tomes(name, info, garder_en_cours=False):
    """Range une série en tomes : les anciens fichiers « un par chapitre » rejoignent le fichier de leur tome,
    et les chapitres « Hors tome » passent dans leur tome quand il est sorti. Les originaux vont à la corbeille ;
    la progression de lecture suit. Renvoie le nombre de chapitres rangés."""
    dossier = MANGA_DIR / name
    etat = _RANGEMENTS.setdefault(name, {})
    etat.update(en_cours=True, fait=0, total=0, erreur=None)
    try:
        files = _scan().get(name) or []
        par_tome, anciens, depuis_hors = {}, [], {}
        for f in files:
            info_f = tomes_cbz.lire_info(f) if f.suffix.lower() == ".cbz" else None
            if info_f is None:
                if _numero_tome(_title_of(f)) is not None or _a_importer(f):
                    continue                      # tome complet (« 20th Century Boys - Tome 01 ») : jamais pris pour un chapitre
                num = _numero_chapitre(_title_of(f))
                if num is not None:
                    par_tome.setdefault(tomes.tome_de(num, info), []).append((num, f))
            else:
                # « Hors tome » → son tome s'il est sorti ; tome fait par l'appli d'après une ancienne répartition fausse
                # (The Breaker : mauvaise fiche MangaDex) → le chapitre change de tome
                actuel = info_f.get("tome")
                for c in tomes_cbz.chapitres(f):
                    t = tomes.tome_de(c["num"], info)
                    if t is not None and (actuel is None or int(t) != int(actuel)):
                        depuis_hors.setdefault(f, []).append((t, c))
        for t in list(par_tome):                 # deux fichiers avec le même numéro : on ne fusionne rien, on les laisse
            vus = {}
            for num, f in par_tome[t]:
                vus.setdefault(num, []).append(f)
            doublons = {n for n, fs in vus.items() if len(fs) > 1}
            if doublons:
                logger.warning("Rangement de %s : numéros en double %s laissés tels quels", name, sorted(doublons))
                par_tome[t] = [(n, f) for n, f in par_tome[t] if n not in doublons]
        etat["total"] = sum(len(v) for v in par_tome.values()) + sum(len(v) for v in depuis_hors.values())
        renommes = {}
        for t, liste in par_tome.items():          # un tome à la fois (mémoire raisonnable)
            ajouts, titres = {}, {}
            for num, f in liste:
                ajouts[num] = [archives.read_page(f, i)[0] for i in range(len(archives.pages(f)))]
                titres[num] = tomes_cbz.nettoyer_titre(_title_of(f)) or info.get("titres", {}).get(num, "")
                renommes[_rel(f)] = f"#{num:g}"
                anciens.append(f)
            cible = tomes_cbz.fichier_tome(dossier, name, t)
            if cible.exists() and tomes_cbz.lire_info(cible) is None:
                logger.info("Tome %s déjà présent en entier : ses chapitres séparés sont laissés tels quels", t)
                anciens = [a for a in anciens if a not in {f for _, f in liste}]
                renommes = {k: v for k, v in renommes.items() if k not in {_rel(f) for _, f in liste}}
                continue
            tomes_cbz._reecrire(cible, name, t, set(), ajouts, titres)
            etat["fait"] += len(liste)
        for f in anciens:
            _vers_corbeille(f)
        for f, liste in depuis_hors.items():
            for t, c in liste:
                tomes_cbz.ajouter(dossier, name, t, c["num"], c["titre"], tomes_cbz.extraire(f, c["num"]))
                etat["fait"] += 1
            tomes_cbz.retirer(f, {c["num"] for _, c in liste})
        if renommes:
            with _progress_lock:
                for _pf in _fichiers_progression():          # admin et chaque lecteur
                    data = _read_json(_pf, {})
                    p = data.get(name)
                    if p:
                        p["read"] = sorted({renommes.get(r, r) for r in p.get("read", [])})
                        if p.get("current") in renommes:
                            p["current"], p["page"] = renommes[p["current"]], p.get("page", 0)
                        _write_json(_pf, data)
        if etat["total"]:
            logger.info("Série « %s » rangée en tomes : %d chapitre(s) (%s)", name, etat["total"], info.get("source"))
        return etat["total"]
    except Exception as e:
        etat["erreur"] = str(e)
        logger.warning("Rangement en tomes impossible pour %s : %s", name, e)
        raise
    finally:
        if not garder_en_cours:
            etat["en_cours"] = False


def _etat_rangement(name):
    """État du rangement pour la page ; le message de fin n'est montré qu'une fois."""
    etat = _RANGEMENTS.get(name)
    if not etat:
        return None
    copie = dict(etat)
    if not etat.get("en_cours"):
        etat.pop("message", None)
    return copie


_CROCHETS = re.compile(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}")
_MARQUE = re.compile(r"(?:^|[\s_\-.])(?:t|tome|vol(?:ume)?\.?|v|chap(?:itre|ter)?\.?|ch\.?|#)\s*\d{1,4}\b.*$", re.I)
_BRUIT = re.compile(r"\b(?:int[ée]grale?|complete|complet|fr|vf|vostfr|cbz|cbr|e-?books?|officiels?|digital|scans?|manga|no-?tags?|hybrid)\b", re.I)


_PARTICULES = {"no", "wa", "ga", "ni", "to", "wo", "de", "na", "e", "of", "the", "a", "an", "and", "in", "on", "de", "du", "des", "la", "le", "les", "et"}
CHOIX = DATA_DIR / "organiser-choix.json"
RESUMES = DATA_DIR / "resumes.json"              # résumés écrits ou corrigés à la main : prioritaires sur Internet


def _deplacer_resume(name, nouveau):
    """Le résumé écrit à la main suit la série renommée (en cas de fusion, celui de la série d'arrivée reste)."""
    perso = _read_json(RESUMES, {})
    if name in perso and nouveau != name:
        texte = perso.pop(name)
        perso.setdefault(nouveau, texte)
        _write_json(RESUMES, perso)


def _majuscules(nom):
    """« nanatsu no taizai » → « Nanatsu no Taizai » (seulement si le nom est tout en minuscules)."""
    if nom != nom.lower():
        return nom
    mots = nom.split(" ")
    return " ".join(m if (i and m in _PARTICULES) else m[:1].upper() + m[1:] for i, m in enumerate(mots))


def _appris(dossier, propose):
    """Applique ce que tu as choisi les fois précédentes : même dossier → même nom ; mots que tu retires toujours."""
    choix = _read_json(CHOIX, [])
    for c in reversed(choix):
        if c.get("dossier") == dossier:
            return c["choisi"]
    retires = {}
    for c in choix:
        if len(c["choisi"].split()) >= len(c["propose"].split()):      # réécriture (ex. « Code » → « CØDE »), pas un mot retiré
            continue
        garde = set(c["choisi"].lower().split())
        for mot in set(c["propose"].lower().split()) - garde:
            retires[mot] = retires.get(mot, 0) + 1
    # Jamais un tiret ni une mention d'édition : « Cat's Eye Édition de luxe » → « Cat's Eye » faisait perdre « Édition »
    # (et le tiret d'un autre choix) à « Gantz - Perfect Édition », devenu « Gantz Perfect » puis « Gantz : Perfect »
    proteges = {"-", "–", ":", "de", "édition", "edition", "perfect", "deluxe", "luxe", "ultimate", "collector", "kanzenban"}
    # Un mot n'est retiré partout que s'il est technique (« scan », « fr »…) ou retiré au moins deux fois : une seule
    # correction (« … IMMORTAL REGIS » → « Cavalier of the Abyss ») ne doit pas effacer « Regis » d'un autre titre.
    def retire(m):
        n = retires.get(m.lower(), 0)
        return n >= 2 or (n >= 1 and (bool(_BRUIT.fullmatch(m)) or bool(re.fullmatch(r"\d+|t\d+|tomes?", m, re.I))))
    mots = [m for m in propose.split(" ") if m.lower() in proteges or not retire(m)]
    return " ".join(mots) if mots else propose


def _nettoyer_nom(texte):
    if " " not in texte and texte.count(".") >= 2:          # noms « Gamaran.T01.FRENCH.HYBRiD… »
        texte = texte.replace(".", " ")
    t = _CROCHETS.sub(" ", texte.replace("_", " "))
    t = _MARQUE.sub(" ", t)
    t = _BRUIT.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" -–—.,")
    return t


def _plan_organiser(name, files):
    """Ce que ferait « Organiser » (sans rien toucher), ou None si la série est déjà bien rangée.
    Série ajoutée à la main : nom du dossier encombré (« Gintama Integrale T01-77 [FR][CBZ] »),
    tomes complets hors de leur dossier « Tome NN », ou chapitres pas encore rangés en tomes."""
    from collections import Counter
    lots = [f for f in files if _a_importer(f)]
    files = [f for f in files if f not in lots]
    noms = [_nettoyer_nom(f.stem) for f in files if f.parent != MANGA_DIR]
    noms = [n for n in noms if n]
    commun = Counter(noms).most_common(1)
    propose = commun[0][0] if commun and commun[0][1] >= max(2, len(files) * 0.6) else (_nettoyer_nom(name) or name)
    propose = _nom_serie(_appris(name, _majuscules(propose)))
    if _cle_nom(propose) == _cle_nom(name) and propose.lower() != name.lower():   # seule la ponctuation diffère (« : ») : on garde
        propose = name
    if any(c.get("choisi") == name for c in _read_json(CHOIX, [])):               # un nom que tu as déjà validé n'est plus remis en cause
        propose = name                                                             # (les fichiers du torrent gardent leur nom d'origine)
    tomes_fichiers, a_deplacer, chapitres = [], 0, 0
    for f in files:
        if tomes_cbz.lire_info(f) is not None:
            continue
        t = _numero_tome(f.stem)
        if t is not None:
            tomes_fichiers.append(t)
            if f.relative_to(MANGA_DIR / name).parent != Path(tomes_cbz.dossier_tome(t)):   # seul le dossier compte : le nom du fichier peut garder celui du torrent
                a_deplacer += 1
        elif f.suffix.lower() == ".cbz" and deux_tomes.numeros(f.stem):
            a_deplacer += 1                                  # « T45-46 » : à couper en deux tomes
        elif _numero_chapitre(f.stem) is not None:
            chapitres += 1
    if propose == name and not a_deplacer and not chapitres and not lots:
        return None
    return {"nom": propose, "tomes": len(tomes_fichiers), "a_deplacer": a_deplacer, "chapitres": chapitres,
            "archives": sum(1 for f in lots if f.suffix.lower() != ".pdf"), "pdf": sum(1 for f in lots if f.suffix.lower() == ".pdf"),
            "taille_go": round(sum(f.stat().st_size for f in lots) / 1073741824, 1),
            "premier_tome": min(tomes_fichiers) if tomes_fichiers else None,
            "dernier_tome": max(tomes_fichiers) if tomes_fichiers else None}


def _nom_serie(texte, defaut="sans-titre"):
    """Nom de série choisi à la main : comme nom_sur, mais garde « : » (« L'Attaque des Titans : Before the Fall »),
    que le NAS accepte (partage NFS). Les noms venant de Japscan gardent l'ancienne règle (dossiers déjà créés)."""
    texte = re.sub(r'[\\/*?"<>|\x00-\x1f]', " ", texte or "")
    texte = re.sub(r"\s+", " ", texte).strip(" .:")
    return texte[:120] or defaut


def _fichiers_partages(name):
    """Fichiers liés à une autre copie (torrent qBittorrent) : le NAS refuse de les renommer ou de les déplacer."""
    racine = MANGA_DIR / name
    if not racine.is_dir():
        return []
    return [f for f in racine.rglob("*") if f.is_file() and f.stat().st_nlink > 1]


def _renommer_dossier_seul(name, nouveau):
    """Renomme seulement le dossier (le NAS l'accepte) : les fichiers gardent leur nom, la progression suit les chemins."""
    ancien, dossier = MANGA_DIR / name, MANGA_DIR / nouveau
    if dossier.exists():
        raise ValueError(f"« {nouveau} » existe déjà")
    ancien.rename(dossier)
    deplaces = {_rel(ancien / f.relative_to(dossier)): _rel(f) for f in dossier.rglob("*") if f.is_file()}
    _suivre_renommage(name, nouveau, deplaces)
    logger.info("Série renommée (dossier seul, fichiers liés au torrent gardés) : « %s » → « %s »", name, nouveau)
    return nouveau


def _suivre_renommage(name, nouveau, deplaces):
    """La progression de lecture et les séries de reprise suivent le nouveau nom et les nouveaux chemins."""
    with _progress_lock:
        for _pf in _fichiers_progression():          # admin et chaque lecteur
            data = _read_json(_pf, {})
            p = data.pop(name, None) if nouveau != name else data.get(name)
            if p is not None:
                conv = lambda r: deplaces.get(r, r)
                p["read"] = sorted({conv(r) for r in p.get("read", [])})
                if p.get("current"):
                    p["current"] = conv(p["current"])
                autre = data.get(nouveau) if nouveau != name else None
                if autre:                                    # fusion avec une série existante : lus réunis, lecture la plus récente
                    p["read"] = sorted(set(p["read"]) | set(autre.get("read", [])))
                    if (autre.get("last") or "") > (p.get("last") or ""):
                        p.update({k: autre[k] for k in ("current", "page", "last") if k in autre})
                data[nouveau] = p
                _write_json(_pf, data)
    _deplacer_resume(name, nouveau)


def _organiser(name, nouveau):
    """Renomme la série et range ses fichiers : tomes complets dans « Tome NN/<Série> - Tome NN.cbz » (simples
    déplacements), chapitres regroupés en tomes ensuite. La progression de lecture suit. Renvoie le nouveau nom."""
    files = _scan().get(name) or []
    ancien_dossier, dossier = MANGA_DIR / name, MANGA_DIR / nouveau
    if nouveau != name and dossier.exists() and not dossier.is_dir():
        raise ValueError(f"« {nouveau} » existe déjà et n'est pas un dossier")
    if nouveau != name and _fichiers_partages(name):
        return _renommer_dossier_seul(name, nouveau)
    deplaces, en_double, doublons = {}, set(), []
    a_noter_prov = []                                    # (tome, nom d'origine) : pour la provenance
    for f in files:
        t = None
        if _a_importer(f) or tomes_cbz.lire_info(f) is not None:
            cible = dossier / f.relative_to(ancien_dossier)
        else:
            t = _numero_tome(f.stem)
            if t is None:
                cible = dossier / f.relative_to(ancien_dossier)       # chapitres et fichiers inconnus : même place
            else:
                cible = dossier / tomes_cbz.dossier_tome(t) / f"{nouveau} - {tomes_cbz.dossier_tome(t)}{f.suffix.lower()}"
        if t is not None:
            a_noter_prov.append((t, f.name))
        if cible == f:
            continue
        if cible.exists():
            logger.warning("Organiser : %s existe déjà, %s laissé en place", cible, f.name)
            en_double.add(f)
            if t is not None and not _meme_fichier(f, cible):
                doublons.append((f, cible, t))
            continue
        cible.parent.mkdir(parents=True, exist_ok=True)
        f.rename(cible)
        deplaces[_rel(f)] = _rel(cible)
    # Le reste du dossier (couverture, images…) suit, puis les dossiers vidés disparaissent
    if nouveau != name and ancien_dossier.is_dir():
        for reste in sorted(ancien_dossier.rglob("*"), key=lambda p: -len(p.parts)):
            if reste.is_file() and reste not in en_double:
                cible = dossier / reste.relative_to(ancien_dossier)
                if not cible.exists():
                    cible.parent.mkdir(parents=True, exist_ok=True)
                    reste.rename(cible)
    for d in sorted((p for p in ancien_dossier.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)) if ancien_dossier.is_dir() else []:
        try:
            d.rmdir()
        except OSError:
            pass
    if nouveau != name:
        try:
            ancien_dossier.rmdir()
        except OSError:
            pass
    _suivre_renommage(name, nouveau, deplaces)
    _noter_provenances(dossier, a_noter_prov, "Rangé depuis le fichier")
    if doublons:
        if nouveau != name:
            doublons = [(dossier / f.relative_to(ancien_dossier) if f.is_relative_to(ancien_dossier) else f, c, t) for f, c, t in doublons]
        _signaler_doublons(nouveau, doublons)
    logger.info("Série organisée : « %s » → « %s » (%d fichier(s) déplacé(s))", name, nouveau, len(deplaces))
    return nouveau


def _meme_fichier(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


DOUBLONS_IGNORES = DATA_DIR / "doublons-ignores.json"


def _retenir_doublons_ignores(paires):
    """« Ne rien faire » : ces paires (source, cible) ne sont plus signalées."""
    deja = set(_lire_json_liste(DOUBLONS_IGNORES))
    deja |= {f"{p[0]}|{p[1]}" for p in paires}
    DOUBLONS_IGNORES.write_text(json.dumps(sorted(deja), ensure_ascii=False, indent=1), encoding="utf-8")


def _lire_json_liste(f):
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _signaler_doublons(serie, paires):
    """Tomes rangés à la main alors qu'un tome identique existe déjà : une tâche « à valider » dans Télécharger.
    Ne signale que les vrais doublons nouveaux : ni fichiers disparus, ni paires déjà refusées (« ne rien faire »)."""
    maintenant = datetime.now().strftime("%Y-%m-%d %H:%M")
    ignores = set(_lire_json_liste(DOUBLONS_IGNORES))
    with torrents._verrou:
        d = [j for j in torrents._lire() if not (j.get("manuel") and j.get("serie") == serie and j.get("etat") == "a_valider")]
        anciennes = [p for j in torrents._lire() if j.get("manuel") and j.get("serie") == serie and j.get("etat") == "a_valider"
                     for p in j.get("paires", [])]
        anciennes = [p for p in anciennes if (MANGA_DIR / p[0]).is_file() and f"{p[0]}|{p[1]}" not in ignores]
        vus = {tuple(p[:2]) for p in anciennes}
        nouvelles = [[_rel(f), _rel(c), t] for f, c, t in paires
                     if (_rel(f), _rel(c)) not in vus and f"{_rel(f)}|{_rel(c)}" not in ignores and f.is_file()]
        paires_tout = anciennes + nouvelles
        if not paires_tout:
            torrents._ecrire(d)
            return
        tomes = {p[2] for p in paires_tout}
        d.append({"id": uuid.uuid4().hex[:10], "titre": "Rangé à la main", "serie": serie, "remplacer": None, "etat": "a_valider",
                  "manuel": True, "paires": paires_tout, "progression": 100, "debut": maintenant, "rappel_le": maintenant,
                  "message": torrents.demander_choix(None, tomes)})
        torrents._ecrire(d)
    regle = _regle_import(serie)
    if regle and nouvelles:                 # choix retenu pour cette série : appliqué tout seul
        jid = next((x["id"] for x in torrents._lire() if x.get("manuel") and x.get("serie") == serie and x.get("etat") == "a_valider"), None)
        if jid:
            r, _c = _appliquer_choix(jid, {"remplacer": True, "manquants": False, "ignorer": "ignorer"}[regle])
            logger.info("Doublons de « %s » : règle « %s » appliquée toute seule (%s)", serie, regle, r.get("message") or r.get("error"))
            import notifier
            notifier.envoyer(f"📚 MouFlanga : « {serie} » : tomes en double, ton choix retenu « {regle} » a été appliqué tout seul.")
            return
    if not nouvelles:                       # rien de neuf : pas de nouvelle notification
        return
    import notifier
    notifier.envoyer(f"📚 MouFlanga : « {serie} » contient déjà des tomes. Choisis dans Télécharger : remplacer tout, ajouter les manquants ou ne rien faire.")


def _appliquer_rangement(j, remplacer):
    """Décision sur un rangement à la main : remplacer met les anciens tomes à la corbeille puis place les nouveaux."""
    if not remplacer:
        return "Tomes déjà présents conservés : les doublons restent dans le dossier."
    n = 0
    for src, cible, t in j["paires"]:
        s, c = MANGA_DIR / src, MANGA_DIR / cible
        if not s.is_file():
            continue
        n += _remplacer_tomes(j["serie"], {t})
        c.parent.mkdir(parents=True, exist_ok=True)
        s.rename(c)
    return f"{n} tome(s) remplacé(s) ; les anciens sont dans la corbeille (30 jours)."


REGLES_IMPORT = DATA_DIR / "regles-import.json"     # choix retenus par série : remplacer / manquants / ignorer


def _regle_import(serie):
    r = _read_json(REGLES_IMPORT, {}).get(serie) or {}
    return r.get("choix") if r.get("choix") in ("remplacer", "manquants", "ignorer") else None


@app.route("/api/regles-import", methods=["GET", "POST"])
def api_regles_import():
    """Choix retenus (« toujours faire ça pour cette série ») : liste, et suppression d'une règle (⚙️ Réglages)."""
    regles = _read_json(REGLES_IMPORT, {})
    if request.method == "POST":
        serie = str((request.get_json(silent=True) or {}).get("serie", ""))
        if regles.pop(serie, None) is not None:
            _write_json(REGLES_IMPORT, regles)
        return jsonify({"ok": True, "message": f"Règle de « {serie} » supprimée : l'appli te redemandera."})
    return jsonify({"regles": [{"serie": k, **v} for k, v in sorted(regles.items())]})


@app.route("/api/torrents/decider", methods=["POST"])
def api_torrents_decider():
    body = request.get_json(silent=True) or {}
    jid = str(body.get("id", ""))
    j = next((x for x in torrents._lire() if x.get("id") == jid and x.get("etat") == "a_valider"), None)
    if j is not None and body.get("toujours"):
        choix = "ignorer" if body.get("remplacer") == "ignorer" else ("remplacer" if body.get("remplacer") else "manquants")
        regles = _read_json(REGLES_IMPORT, {})
        regles[j["serie"]] = {"choix": choix, "date": datetime.now().strftime("%Y-%m-%d %H:%M")}
        _write_json(REGLES_IMPORT, regles)
    r, code = _appliquer_choix(jid, body.get("remplacer"))
    return jsonify(r), code


def _appliquer_choix(jid, valeur):
    """Applique « remplacer » (valeur vraie), « ajouter les manquants » (fausse) ou « ignorer » à une tâche à valider."""
    ignorer = valeur == "ignorer"
    remplacer = bool(valeur) and not ignorer
    j = next((x for x in torrents._lire() if x.get("id") == jid and x.get("etat") == "a_valider"), None)
    if j is None:
        return {"ok": False, "error": "Rien à valider ici (déjà traité ?)."}, 404
    if ignorer:
        # Ne rien faire : la tâche est fermée, les doublons restent tels quels et ne sont plus signalés
        if j.get("manuel"):
            _retenir_doublons_ignores(j.get("paires", []))
        torrents._maj(jid, remplacer=None, etat="fini", message="Choix : ne rien faire. Les doublons restent tels quels.")
        return {"ok": True, "message": "Rien n'a été changé. Cette demande ne reviendra plus."}, 200
    if j.get("manuel") and not any((MANGA_DIR / src).is_file() for src, _c, _t in j.get("paires", [])):
        torrents._maj(jid, etat="erreur", message="Fichiers introuvables (dossier renommé ou supprimé) : relance le rangement.")
        return {"ok": False, "error": "Ces fichiers ne sont plus à leur place : relance le rangement."}, 409
    if not j.get("manuel"):
        torrents.decider_torrent(jid, remplacer)
        return {"ok": True, "message": "Choix enregistré : l'import reprend."}, 200
    try:
        fin = _appliquer_rangement(j, remplacer)
    except OSError as e:
        logger.warning("Choix sur « %s » impossible : %s", j["serie"], e)
        return {"ok": False, "error": f"Impossible d'appliquer le choix : {e}"}, 500
    torrents._maj(jid, remplacer=remplacer, etat="fini", message=fin)
    return {"ok": True, "message": fin}, 200


_AUTO = {"dernier": 0.0}


def _organiser_auto():
    """Réglage « Organiser tout seul » : à l'ouverture de la bibliothèque (au plus toutes les 5 minutes), chaque série
    ajoutée à la main est organisée avec le nom proposé (qui tient compte de tes choix précédents)."""
    if os.getenv("ORGANISER_AUTO", "") != "1" or time.time() - _AUTO["dernier"] < 300:
        return
    _AUTO["dernier"] = time.time()
    if any(e.get("en_cours") for e in _RANGEMENTS.values()) or any(j.get("status") == "running" for j in japscan_scraper.download_jobs.values()):
        return
    series = _scan()
    for name, files in series.items():
        if name == "(Sans série)":
            continue
        plan = _plan_organiser(name, files)
        if not plan or (plan["nom"] != name and plan["nom"] in series):
            continue
        try:
            nouveau = _organiser(name, plan["nom"])
            _noter_choix(name, plan["nom"], nouveau)
            _lancer_import(nouveau)
            logger.info("Organisation automatique : « %s » → « %s »", name, nouveau)
        except Exception as e:
            logger.warning("Organisation automatique de %s impossible : %s", name, e)
        return                                           # une série à la fois


@app.route("/api/settings/organiser-auto", methods=["GET", "POST"])
def api_organiser_auto():
    if request.method == "POST":
        actif = bool((request.get_json(silent=True) or {}).get("actif"))
        from secrets_store import write_secret
        write_secret(DATA_DIR / "secrets.env", "ORGANISER_AUTO", "1" if actif else "0")
        os.environ["ORGANISER_AUTO"] = "1" if actif else "0"
        return jsonify({"ok": True, "message": "Les séries ajoutées à la main seront organisées toutes seules." if actif
                        else "Organisation automatique coupée : un bandeau te le proposera sur chaque série."})
    return jsonify({"actif": os.getenv("ORGANISER_AUTO", "") == "1", "choix": len(_read_json(CHOIX, []))})


@app.route("/api/organiser", methods=["POST"])
def api_organiser():
    """Bouton « Organiser » d'une série ajoutée à la main."""
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    files = _scan().get(name)
    if files is None or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    nouveau = _nom_serie(str(body.get("nom", "")).strip())
    if not nouveau or nouveau.startswith(".") or nouveau in (".corbeille", "(Sans série)"):
        return jsonify({"ok": False, "error": "Nom de série invalide"}), 400
    if nouveau != name and nouveau in _scan():
        return jsonify({"ok": False, "error": f"Une série « {nouveau} » existe déjà : choisis un autre nom."}), 409
    for j in list(japscan_scraper.download_jobs.values()):
        if j.get("status") == "running" and japscan_scraper.nom_sur(japscan_scraper.titre_serie(j.get("title") or "")) == name:
            return jsonify({"ok": False, "error": "Cette série est en cours de téléchargement : attends la fin."}), 409
    plan = _plan_organiser(name, files)
    try:
        nouveau = _organiser(name, nouveau)
    except (OSError, ValueError) as e:
        logger.warning("Organiser %s impossible : %s", name, e)
        return jsonify({"ok": False, "error": f"Impossible d'organiser : {e}"}), 500
    _noter_choix(name, plan.get("nom") if plan else nouveau, nouveau)
    _lancer_import(nouveau)
    return jsonify({"ok": True, "id": nouveau})


def _noter_choix(dossier, propose, choisi):
    """Garde ton choix de nom pour proposer mieux la prochaine fois."""
    choix = _read_json(CHOIX, [])
    choix.append({"dossier": dossier, "propose": propose, "choisi": choisi, "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
    _write_json(CHOIX, choix[-200:])


def _separer_doubles(nom, info, etat=None):
    """Fichiers « Série T45-46 » (deux tomes dans un seul .cbz) : coupés en deux tomes ; l'original va à la corbeille.
    Un fichier dont on ne trouve pas la coupure reste tel quel. Renvoie le nombre de fichiers coupés."""
    dossier, faits = MANGA_DIR / nom, 0
    for f in list(_scan().get(nom) or []):
        paire = deux_tomes.numeros(f.stem) if f.suffix.lower() == ".cbz" and tomes_cbz.lire_info(f) is None else None
        if not paire:
            continue
        cibles = [tomes_cbz.fichier_tome(dossier, nom, n) for n in paire]
        if any(c.exists() for c in cibles):
            continue                                      # un tome déjà là (peut-être validé) : jamais touché
        if etat is not None:
            etat["message"] = f"Coupure de {f.name}…"
        if deux_tomes.separer(f, cibles, deux_tomes.premier_chapitre(info, paire[1])):
            _vers_corbeille(f)
            _noter_provenances(dossier, [(n, f.name) for n in paire], "Coupé depuis le fichier")
            faits += 1
    if faits:
        _scan_invalider()
    return faits


def _lancer_import(nouveau, attendre=False, lots_forces=None):
    """Archives de tomes et PDF convertis, puis chapitres regroupés en tomes : en arrière-plan,
    ou tout de suite si « attendre » (file d'import). « lots_forces » : archives à extraire quelle que soit leur taille.
    Renvoie le message de fin quand « attendre »."""
    lots_forces = [Path(x) for x in (lots_forces or [])]
    files = _scan().get(nouveau) or []
    lots = [f for f in files if _a_importer(f) or f in lots_forces] + [f for f in lots_forces if f not in files and f.exists()]
    chapitres = any(f not in lots and tomes_cbz.lire_info(f) is None and _numero_tome(f.stem) is None
                    and _numero_chapitre(f.stem) is not None for f in files)
    _RANGEMENTS[nouveau] = {"en_cours": True, "fait": 0, "total": len(lots), "erreur": None, "message": "Préparation…"}

    def travail():
        etat = _RANGEMENTS[nouveau]
        erreurs, crees = [], 0
        for k, lot in enumerate(lots):
            try:
                if lot.suffix.lower() == ".pdf":
                    t = _numero_tome(lot.stem) or 1
                    cible = tomes_cbz.fichier_tome(MANGA_DIR / nouveau, nouveau, t)
                    etat["message"] = f"Conversion de {lot.name}…"
                    if cible.exists():
                        raise importer.ErreurImport(f"{cible.name} existe déjà")
                    importer.pdf_vers_cbz(lot, cible)
                    crees += 1
                else:
                    crees += len(importer.importer_lot(lot, MANGA_DIR / nouveau, nouveau, etat))
                try:
                    _vers_corbeille(lot)                 # l'original est gardé 30 jours
                except OSError as e:                     # fichier encore partagé par qBittorrent : le NAS refuse
                    logger.info("%s laissé en place (%s)", lot.name, e.strerror or e)
            except Exception as e:
                logger.warning("Import de %s impossible : %s", lot.name, e)
                erreurs.append(f"{lot.name} : {e}")
            etat["fait"] = k + 1
        if lots:
            logger.info("Import de « %s » : %d tome(s) créé(s) depuis %d archive(s)/PDF", nouveau, crees, len(lots))
            for d in sorted((x for x in (MANGA_DIR / nouveau).rglob("*") if x.is_dir()), key=lambda x: -len(x.parts)):
                try:
                    d.rmdir()                            # dossiers vidés (ex. « Gamaran.T01.FRENCH… »)
                except OSError:
                    pass
        try:                                         # .cbr reçus : convertis en .cbz tout de suite (pages identiques, vérifiées)
            _scan_invalider()
            etat["message"] = "Conversion des .cbr…"
            a_convertir = _cbr_de(nouveau)
            if any(c[1] for c in a_convertir):
                n_conv, err_conv = _convertir_cbr_serie(nouveau, a_convertir)
                logger.info("Import de « %s » : %d .cbr converti(s) en .cbz", nouveau, n_conv)
                erreurs += [f"conversion {e}" for e in err_conv]
        except Exception as e:
            logger.warning("Conversion automatique des .cbr de « %s » : %s", nouveau, e)
        etat["message"] = "Recherche des tomes…"
        try:
            info = tomes.chercher(nouveau, forcer=True)
            msg = "✅ Série organisée" + (f" : {crees} tome(s) importé(s)" if lots else "")
            try:
                coupes = _separer_doubles(nouveau, info, etat)
                if coupes:
                    msg += f" ; {coupes} fichier(s) de deux tomes coupé(s)"
            except Exception as e:
                logger.warning("Coupure des fichiers à deux tomes de « %s » : %s", nouveau, e)
            if info:                                  # chapitres séparés ou « hors tome » : rangés d'après Internet
                n = _ranger_en_tomes(nouveau, info, garder_en_cours=True)
                if n:
                    msg += f" ; {n} chapitre(s) rangé(s) en tomes"
            msg += f" (tomes d'après {info['source']})." if info else "."
        except Exception as e:
            msg = f"Série organisée, mais rangement des chapitres impossible : {e}"
        if erreurs:
            msg += " ⚠ Non importé : " + " · ".join(erreurs)
        if "unittest" not in sys.modules:           # générique de l'anime (OP1) cherché tout de suite pour la série importée
            try:
                if not _theme_de(_anime_de(nouveau)):
                    generiques.pour_serie(nouveau, MANGA_DIR / nouveau, _manga_id(nouveau))
            except Exception as e:
                logger.info("Générique de %s après import : %s", nouveau, e)
        etat.update(en_cours=False, message=msg)
        return msg
    if attendre:
        return travail()
    threading.Thread(target=travail, daemon=True).start()


# ---------------------------------------------------------------- Archives déposées à la racine

_FILE_IMPORT = {"en_cours": None, "attente": [], "faits": [], "erreurs": [], "message": ""}
_FILE_VERROU = threading.Lock()
_EDITION = re.compile(r"\s*[-–:,]?\s*\b(?:[ée]dition\s+(?:de\s+)?luxe|deluxe|de\s+luxe|collector|kanzenban|perfect\s+[ée]dition|ultimate\s+[ée]dition)\b", re.I)
_NOMBRE_TOMES = re.compile(r"\b(?:int[ée]grale\s*)?\d+\s*tomes?\b|\b(?:tomes?|t)\s*\d+\s*(?:[-àa]|a)\s*\d+\b|\bfinal\b", re.I)


def _cle_nom(nom):
    import unicodedata
    t = unicodedata.normalize("NFKD", nom.replace("Ø", "O").replace("ø", "o")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", t)


_COUPURE = re.compile(r"\s(?:\d{1,3}\s*tomes?|t\d{1,3}\b|tomes?\s*\d|vol(?:ume)?s?\s*\d|int[ée]grale?|complete|fr|french|vf|cbz|cbr|"
                      r"digital|scans?|no-?tags?|hybrid|(?:19|20)\d\d|\d{3,4}p?|e-?books?)\b", re.I)
_NOMS_ANILIST = {}


def _latin(c):
    """Titre écrit en alphabet latin (accents compris) : « คำอธิษฐาน… Frieren » ou un titre en japonais ne sont jamais un nom de dossier."""
    return all(ord(ch) < 0x250 or not ch.isalpha() for ch in c)


def _titre_anilist(t):
    """Écriture officielle du titre d'après AniList (« AirGear » → « Air Gear », « 20th Century boys » → « 20th Century Boys »),
    seulement si c'est bien la même suite de lettres ; sinon « ». Gardé en mémoire et dans data/noms-anilist.json."""
    f = DATA_DIR / "noms-anilist.json"
    if not _NOMS_ANILIST:
        _NOMS_ANILIST.update(_read_json(f, {}) or {"": ""})
    if t in _NOMS_ANILIST and _latin(_NOMS_ANILIST[t]):         # une ancienne réponse en thaï ou en japonais est refaite
        return _NOMS_ANILIST[t]
    trouve = ""
    try:
        q = "query($s:String){Page(perPage:6){media(search:$s,type:MANGA){title{romaji english} synonyms}}}"
        for m in ((reseau.anilist(q, {"s": t}) or {}).get("Page") or {}).get("media") or []:
            egaux = [c.rstrip(" .。") for c in (m["title"].get("english"), m["title"].get("romaji"), *(m.get("synonyms") or []))
                     if c and _latin(c) and _cle_nom(c.rstrip(" .!。")) == _cle_nom(t)]
            if egaux:                                        # « Akame ga Kill! Zero » plutôt que « Akame ga KILL! ZERO »
                trouve = min(egaux, key=lambda c: sum(x.isupper() for x in c) / max(1, sum(x.isalpha() for x in c)))
                break
    except Exception as e:
        logger.info("AniList (nom officiel) : %s", e.__class__.__name__)
        return ""
    _NOMS_ANILIST[t] = trouve
    _write_json(f, _NOMS_ANILIST)
    return trouve


def _titre_officiel(t):
    return _titre_anilist(t) or t


_MOTS_SUITE = {"extra", "game", "replace", "plus", "zero", "gaiden", "side", "story", "stories", "special", "spécial", "hors",
               "série", "serie", "ova", "omake", "artbook", "fanbook", "databook", "origin", "origins", "next", "after", "new",
               "returns", "season", "saison", "final", "last", "ex", "bonus", "memories", "chronicle", "chronicles", "revival",
               "reboot", "remake", "prologue", "épilogue", "epilogue", "sequel", "generation", "generations", "next", "re"}


def _nom_depuis_archive(nom_fichier, existantes):
    """Nom de série d'une archive (voir _nom_sans_edition). Une autre édition d'une série déjà là (« Gantz - Perfect Édition »
    alors que « Gantz » existe) a son propre dossier « Gantz : Perfect Édition » : les deux éditions ne se mélangent pas."""
    nom = _nom_sans_edition(nom_fichier, existantes)
    mention = tomes.mention_edition(_CROCHETS.sub(" ", Path(nom_fichier).stem.replace("_", " ").replace(".", " ")))
    if mention and nom in existantes and tomes._simple(mention) not in tomes._simple(nom):
        return _nom_serie(f"{nom} : {mention}")
    return nom


def _nom_sans_edition(nom_fichier, existantes):
    """« jojo's bizarre adventure tome 13 a 28 » → « Jojo's Bizarre Adventure » ; « AirGear.37.Tomes.Integral._FR__CBZ_-Digital-1417 »
    → « Air Gear » (tout ce qui suit le premier mot technique est coupé, puis écriture officielle d'AniList) ;
    une série déjà présente garde son nom."""
    stem = Path(nom_fichier).stem
    t = stem.replace("_", " ")
    if t.count(".") >= 2 or (re.search(r"[A-Za-z]\.[A-Za-z]", t) and t.count(" ") <= 1):   # « Docteur.Slump », « AirGear.37.Tomes… »
        t = t.replace(".", " ")
    t = _EDITION.sub(" ", _CROCHETS.sub(" ", t))
    m = _COUPURE.search(" " + t)
    if m and m.start() > 1:                                   # le titre est avant le premier mot technique
        t = (" " + t)[:m.start()]
    t = _NOMBRE_TOMES.sub(" ", t)
    t = _nettoyer_nom(t) or stem
    if " " not in t and re.search(r"[a-z][A-Z]", t):           # « AirGear » → « Air Gear »
        t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)
    if t == t.lower() or (t[:1].isupper() and t[1:] == t[1:].lower() and " " in t):
        t = _majuscules(t.lower())
    appris = _appris(nom_fichier, t)
    if appris != t:
        t = _nom_serie(appris)
    else:
        # « Red Eyes Sword - Akame Ga Kill » : chaque partie est essayée, d'abord contre les séries déjà là, puis sur AniList
        parties = [t] + [x.strip() for x in re.split(r"\s+-\s+", t) if len(x.strip()) > 2] if " - " in t else [t]
        deja = next((e for c in parties for e in existantes if _cle_nom(e) == _cle_nom(c)), None)
        if deja:
            return deja
        officiel = next((o for c in parties for o in [_titre_officiel(c)] if o != c), None)
        if not officiel and not _titre_anilist(t) and len(t.split()) >= 4:
            # « Jujutsu Kaisen Gege Akutami » : si le nom entier est inconnu, les deux derniers mots sont peut-être l'auteur
            mots_t = t.split()
            avant = " ".join(mots_t[:-2])
            # « Kurokos Basket Extra Game » : « Extra Game » est une suite (spin-off), pas des noms d'auteur
            suite = any(m.lower().strip(":-–") in _MOTS_SUITE for m in mots_t[-2:])
            deja = next((e for e in existantes if _cle_nom(e) == _cle_nom(avant)), None)
            if deja and not suite:
                return deja
            officiel = (_titre_anilist(avant) or None) if not suite else None
        t = _nom_serie(officiel or t)
    # Suite d'une série déjà là (« Akame ga Kill! Zero » et « Akame ga Kill ! ») → « Akame ga Kill ! : Zero »
    mots = t.split()
    for e in sorted(existantes, key=len, reverse=True):
        for k in range(1, len(mots)):
            if _cle_nom(" ".join(mots[:k])) == _cle_nom(e) and _cle_nom(" ".join(mots[k:])):
                reste = mots[k:]
                while len(reste) >= 3 and all(m.isupper() and len(m) >= 3 for m in reste[-2:]) and not reste[-3].isupper():
                    reste = reste[:-2]                         # « Replace Plus TAKAHASHI FUJIMAKI » : noms d'auteurs en fin de nom
                if not any(m.lower().strip(":-–") in _MOTS_SUITE for m in reste) and tomes.meme_serie_sous_titre(e, " ".join(reste)):
                    return e                                   # « Kenichi Le Disciple Ultime Matsuena » : le titre complet de « Kenichi », pas une suite
                return _nom_serie(f"{e} : {' '.join(reste).lstrip(':-– ')}")
    for e in existantes:                                   # série déjà dans la bibliothèque (ex. Gamaran)
        if _cle_nom(e) == _cle_nom(t):
            return e
    return t


def _archives_racine():
    """Archives (.rar/.zip/.7z) posées directement dans le dossier des mangas, regroupées par série proposée."""
    try:
        faites = _read_json(DATA_DIR / "archives-importees.json", {})          # déjà importées, gardées par le NAS
        fichiers = sorted((f for f in MANGA_DIR.iterdir() if f.is_file() and importer.est_lot(f) and not f.name.startswith(".") and f.name not in faites),
                          key=lambda f: archives.natural_key(f.name))
    except OSError:
        return []
    existantes = [d.name for d in MANGA_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")]
    groupes = {}
    for f in fichiers:
        nom = _nom_depuis_archive(f.name, existantes)
        g = groupes.setdefault(nom, {"nom": nom, "existe": nom in existantes, "archives": []})
        g["archives"].append({"nom": f.name, "taille_go": round(f.stat().st_size / 1e9, 2)})
    return sorted(groupes.values(), key=lambda g: _cle_nom(g["nom"]))


def _travail_file():
    """Importe les séries de la file, une à la fois ; message Telegram à la fin."""
    while True:
        with _FILE_VERROU:
            if not _FILE_IMPORT["attente"]:
                _FILE_IMPORT["en_cours"] = None
                break
            g = _FILE_IMPORT["attente"].pop(0)
            _FILE_IMPORT["en_cours"] = g["nom"]
        nom = _nom_serie(g["nom"])
        try:
            dossier = MANGA_DIR / nom
            dossier.mkdir(exist_ok=True)
            deplaces = []
            for a in g["archives"]:
                src = MANGA_DIR / Path(a).name
                if not src.is_file():
                    continue
                cible = dossier / src.name
                try:
                    src.rename(cible)
                except OSError as e:                 # le NAS refuse parfois de déplacer un gros fichier : extrait sur place
                    logger.info("%s laissé à la racine (%s) : extraction sur place", src.name, e.strerror or e)
                    cible = src
                deplaces.append(cible)
                _noter_choix(src.name, g.get("propose", nom), nom)
            msg = _lancer_import(nom, attendre=True, lots_forces=deplaces)
            _prevenir_lecteurs(nom)
            if "⚠" not in msg and "unittest" not in sys.modules:   # compte rendu complet de la série, comme pour un torrent
                try:
                    import notifier
                    notifier.envoyer(_rapport_serie(nom, ", ".join(Path(a).name for a in g["archives"]), origine="📦 Archive"))
                except Exception as e:
                    logger.warning("Compte rendu de %s : %s", nom, e)
            restes = [x.name for x in deplaces if x.parent == MANGA_DIR and x.exists()]
            if restes:                               # pas effaçable par le serveur : retenue comme « déjà importée »
                faites = _read_json(DATA_DIR / "archives-importees.json", {})
                faites.update({x: datetime.now().strftime("%Y-%m-%d") for x in restes})
                _write_json(DATA_DIR / "archives-importees.json", faites)
                msg += f" (archive{'s' if len(restes) > 1 else ''} d'origine à supprimer à la main depuis le NAS : {', '.join(restes)})"
            with _FILE_VERROU:
                (_FILE_IMPORT["erreurs"] if "⚠" in msg else _FILE_IMPORT["faits"]).append(f"{nom} : {msg}")
        except Exception as e:
            logger.warning("Import de %s impossible : %s", nom, e)
            with _FILE_VERROU:
                _FILE_IMPORT["erreurs"].append(f"{nom} : {e}")
    faits, erreurs = len(_FILE_IMPORT["faits"]), len(_FILE_IMPORT["erreurs"])
    _FILE_IMPORT["message"] = f"Import terminé : {faits} série(s) importée(s)" + (f", {erreurs} avec un problème" if erreurs else "") + "."
    logger.info(_FILE_IMPORT["message"])
    try:
        import notifier
        notifier.envoyer("📚 MouFlanga : " + _FILE_IMPORT["message"] + ("\n⚠ " + "\n⚠ ".join(e[:150] for e in _FILE_IMPORT["erreurs"][-5:]) if erreurs else ""))
    except Exception as e:
        logger.warning("Message de fin d'import impossible : %s", e)


@app.route("/api/import/racine", methods=["GET", "POST"])
def api_import_racine():
    """GET : archives à importer et état de la file. POST {groupes: [{nom, propose, archives: [noms]}]} : ajout à la file."""
    if request.method == "POST":
        groupes = (request.get_json(silent=True) or {}).get("groupes") or []
        ajout = []
        for g in groupes:
            nom = _nom_serie(str(g.get("nom", "")).strip())
            arch = [Path(str(a)).name for a in g.get("archives") or [] if (MANGA_DIR / Path(str(a)).name).is_file()]
            if nom and not nom.startswith(".") and arch:
                ajout.append({"nom": nom, "propose": str(g.get("propose") or nom), "archives": arch})
        if not ajout:
            return jsonify({"ok": False, "error": "Rien à importer."}), 400
        with _FILE_VERROU:
            deja = {a for x in _FILE_IMPORT["attente"] for a in x["archives"]}
            _FILE_IMPORT["attente"] += [g for g in ajout if not set(g["archives"]) & deja]
            demarrer = _FILE_IMPORT["en_cours"] is None
            if demarrer:
                _FILE_IMPORT.update(faits=[], erreurs=[], message="", en_cours="(démarrage)")
        if demarrer:
            threading.Thread(target=_travail_file, daemon=True).start()
        return jsonify({"ok": True, "message": f"{len(ajout)} série(s) ajoutée(s) à la file d'import."})
    with _FILE_VERROU:
        file = {"en_cours": _FILE_IMPORT["en_cours"], "attente": [g["nom"] for g in _FILE_IMPORT["attente"]],
                "faits": _FILE_IMPORT["faits"][-50:], "erreurs": _FILE_IMPORT["erreurs"][-50:], "message": _FILE_IMPORT["message"]}
    etat = _RANGEMENTS.get(file["en_cours"] or "", {}) if file["en_cours"] else {}
    en_file = {a for g in _FILE_IMPORT["attente"] for a in g["archives"]}
    groupes = [g for g in _archives_racine() if not {a["nom"] for a in g["archives"]} <= en_file]
    return jsonify({"groupes": groupes, "file": file, "detail": etat.get("message", "")})


# ---------------- 🔄 Rescanner le dossier des torrents (NOK) : même traitement qu'un vrai téléchargement ----------------
_RESCAN = {"en_cours": None, "attente": [], "faits": [], "erreurs": [], "message": ""}
_RESCAN_VERROU = threading.Lock()


def _elements_torrents(avec_ok=False):
    """Éléments du dossier d'arrivée des torrents (TORRENTS_NOK) : dossiers et fichiers de manga, avec le nom de série deviné
    par le MÊME code que pour un torrent ajouté à la main. avec_ok : aussi ceux déjà rangés dans le dossier OK
    (pour réimporter une série supprimée ou à refaire)."""
    reg = torrents.reglages()
    racine = reg["nok"]
    if not racine or not Path(racine).is_dir():
        return None, []
    existantes = sorted(n for n in _scan() if n != "(Sans série)")
    out = []
    bases = [("nok", racine)] + ([("ok", reg["ok"])] if avec_ok and reg.get("ok") and Path(reg["ok"]).is_dir() else [])
    for base, dossier in bases:
        for d in sorted(Path(dossier).iterdir(), key=lambda x: archives.natural_key(x.name)):
            if d.name.startswith((".", "@")):
                continue
            try:
                fichiers = torrents.fichiers_du_torrent(d)
            except OSError:
                continue
            # archives, PDF, mais aussi des dossiers d'images (« Arago Tome 01/001.jpg ») : importés comme un vrai torrent
            if not any(torrents.suffixe(f) in (".cbz", ".cbr", ".zip", ".rar", ".7z", ".pdf", ".jpg", ".jpeg", ".png", ".webp") for f in fichiers):
                continue
            serie = _nom_depuis_archive(d.name + ".zip", existantes)
            out.append({"nom": d.name, "base": base, "serie": serie, "existe": serie in existantes, "fichiers": len(fichiers),
                        "taille_go": round(sum(f.stat().st_size for f in fichiers) / 1e9, 2),
                        **_doublons_torrent(serie, d, fichiers)})
    return racine, out


def _doublons_torrent(serie, source, fichiers=None):
    """Tomes que le torrent apporte : déjà dans la bibliothèque (« deja »), pas encore là (« nouveaux »), et le choix
    retenu pour cette série (« regle »). Sert à décider DANS la fenêtre d'import, sans aller dans une autre page."""
    try:
        fichiers = fichiers if fichiers is not None else torrents.fichiers_du_torrent(Path(source))
        numeros = sorted({_numero_tome(torrents.nom_sans_ext(f)) for f in fichiers
                          if torrents.suffixe(f) in (".cbz", ".cbr") and _numero_tome(torrents.nom_sans_ext(f)) is not None})
        deja = sorted(_tomes_deja_la(serie, source))
    except OSError:
        numeros, deja = [], []
    return {"deja": deja, "nouveaux": [t for t in numeros if t not in deja], "regle": _regle_import(serie)}


@app.route("/api/import/torrents/doublons")
def api_import_torrents_doublons():
    """Recalcule les doublons quand le nom de série est corrigé à la main dans la fenêtre d'import."""
    reg = torrents.reglages()
    racine = reg["ok"] if request.args.get("base") == "ok" else reg["nok"]
    nom, serie = Path(request.args.get("nom", "")).name, _nom_serie(request.args.get("serie", "").strip())
    source = Path(racine) / nom if racine and nom else None
    if source is None or not source.exists() or not serie:
        return jsonify({"deja": [], "nouveaux": [], "regle": None})
    return jsonify(_doublons_torrent(serie, source))


def _travail_rescan():
    """Un élément à la fois : rangement, identification, fiche, compte rendu Telegram (comme un torrent fini)."""
    import notifier
    while True:
        with _RESCAN_VERROU:
            if not _RESCAN["attente"]:
                _RESCAN["en_cours"] = None
                break
            g = _RESCAN["attente"].pop(0)
            _RESCAN["en_cours"] = g["serie"]
        try:
            source = Path(torrents.reglages()["ok" if g.get("base") == "ok" else "nok"]) / g["nom"]
            info = _doublons_torrent(g["serie"], source)
            deja, nouveaux = info["deja"], info["nouveaux"]
            choix = g.get("choix") or info["regle"]
            if deja and choix not in ("remplacer", "manquants", "ignorer"):
                raise RuntimeError(f"{len(deja)} tome(s) déjà dans la bibliothèque : choisis remplacer, ajouter les manquants ou ne rien faire")
            if deja and choix == "ignorer":
                with _RESCAN_VERROU:
                    _RESCAN["faits"].append(f"⏭ {g['serie']} : ignoré à ta demande ({len(deja)} tome(s) déjà là, rien n'a été changé)")
                continue
            if deja and choix == "manquants" and not nouveaux:
                with _RESCAN_VERROU:
                    _RESCAN["faits"].append(f"⏭ {g['serie']} : rien de nouveau, les {len(deja)} tome(s) sont déjà là (rien n'a été changé)")
                continue
            remplacer = bool(deja) and choix == "remplacer"
            fin = _importer_torrent(g["serie"], source, remplacer)
            _noter_volumes_torrent(g["serie"], g["nom"])
            try:
                rapport = _rapport_serie(g["serie"], g["nom"], "🔄 Rescan")
            except Exception as e:
                logger.warning("Compte rendu de %s : %s", g["serie"], e)
                rapport = None
            notifier.envoyer(rapport or f"🔄 MouFlanga : « {g['serie']} » importé depuis {g['nom'][:80]}\n{fin or ''}".strip())
            resume = ", ".join(x for x in (f"{len(nouveaux)} tome(s) ajouté(s)" if nouveaux else "",
                                           f"{len(deja)} remplacé(s) (anciens à la corbeille 30 jours)" if remplacer else "") if x)
            with _RESCAN_VERROU:
                _RESCAN["faits"].append(f"✅ {g['serie']} ← {g['nom']}" + (f" : {resume}" if resume else ""))
        except Exception as e:
            logger.warning("Rescan de %s : %s", g["nom"], e)
            with _RESCAN_VERROU:
                _RESCAN["erreurs"].append(f"{g['nom']} : {str(e)[:200]}")
    with _RESCAN_VERROU:
        _RESCAN["message"] = f"Terminé : {len(_RESCAN['faits'])} importée(s)" + (f", {len(_RESCAN['erreurs'])} avec un problème." if _RESCAN["erreurs"] else ".")
    try:
        import notifier
        notifier.envoyer("🔄 MouFlanga : " + _RESCAN["message"])
    except Exception:
        pass


@app.route("/api/import/torrents", methods=["GET", "POST"])
def api_import_torrents():
    """GET : éléments du dossier des torrents et état de la file. POST {elements: [{nom, serie}]} : ajout à la file."""
    if request.method == "POST":
        racine, presents = _elements_torrents(avec_ok=True)
        if racine is None:
            return jsonify({"ok": False, "error": "Dossier des torrents introuvable (⚙️ Réglages → Torrents)."}), 400
        connus = {(x["nom"], x["base"]) for x in presents}
        ajout = []
        for g in (request.get_json(silent=True) or {}).get("elements") or []:
            nom = Path(str(g.get("nom", ""))).name
            base = "ok" if g.get("base") == "ok" else "nok"
            serie = _nom_serie(str(g.get("serie", "")).strip())
            if (nom, base) in connus and serie and not serie.startswith("."):
                choix = str(g.get("choix", ""))
                choix = choix if choix in ("remplacer", "manquants", "ignorer") else ""
                ajout.append({"nom": nom, "base": base, "serie": serie, "choix": choix})
                if choix and g.get("toujours"):             # « retenir ce choix pour cette série » (⚙️ Réglages → règles d'import)
                    regles = _read_json(REGLES_IMPORT, {})
                    regles[serie] = {"choix": choix, "date": datetime.now().strftime("%Y-%m-%d %H:%M")}
                    _write_json(REGLES_IMPORT, regles)
        if not ajout:
            return jsonify({"ok": False, "error": "Rien à importer."}), 400
        with _RESCAN_VERROU:
            deja = {x["nom"] for x in _RESCAN["attente"]} | ({_RESCAN["en_cours"]} if _RESCAN["en_cours"] else set())
            _RESCAN["attente"] += [g for g in ajout if g["nom"] not in deja]
            demarrer = _RESCAN["en_cours"] is None
            if demarrer:
                _RESCAN.update(faits=[], erreurs=[], message="", en_cours="(démarrage)")
        if demarrer:
            threading.Thread(target=_travail_rescan, daemon=True).start()
        return jsonify({"ok": True, "message": f"{len(ajout)} élément(s) ajouté(s) à la file."})
    racine, elements = _elements_torrents(avec_ok=request.args.get("ok") == "1")
    with _RESCAN_VERROU:
        file = {"en_cours": _RESCAN["en_cours"], "attente": [g["serie"] for g in _RESCAN["attente"]],
                "faits": list(_RESCAN["faits"]), "erreurs": list(_RESCAN["erreurs"]), "message": _RESCAN["message"]}
        en_file = {g["nom"] for g in _RESCAN["attente"]}
    etat = _RANGEMENTS.get(file["en_cours"] or "", {}) if file["en_cours"] else {}
    return jsonify({"dossier": racine, "elements": [x for x in elements if x["nom"] not in en_file], "file": file,
                    "detail": etat.get("message", "")})


@app.route("/api/occupe")
def api_occupe():
    """L'appli fait-elle un travail long ? (lu par deploy.sh avant de redémarrer : seulement depuis le serveur lui-même)"""
    if not auth.appel_local():
        return jsonify({"error": "réservé au serveur"}), 403
    raisons = _travaux_en_cours()
    return jsonify({"occupe": bool(raisons), "raisons": raisons})


def _travaux_en_cours():
    """Travaux longs en cours (téléchargement, import, rangement, découpage…) : ne pas redémarrer pendant ce temps."""
    raisons = []
    if any(j.get("status") == "running" for j in japscan_scraper.download_jobs.values()):
        raisons.append("téléchargement")
    if _FILE_IMPORT["en_cours"] or _FILE_IMPORT["attente"]:
        raisons.append("import d'archives")
    if _RESCAN["en_cours"] or _RESCAN["attente"]:
        raisons.append("rescan des torrents")
    if _CATALOGUE_ETAT["en_cours"]:
        raisons.append("chargement du catalogue")
    raisons += [f"rangement de {n}" for n, e in _RANGEMENTS.items() if e.get("en_cours")]
    import torrents
    raisons += [f"import du torrent {j['titre'][:40]}" for j in torrents.liste() if j.get("etat") == "import"]
    import decoupage
    with decoupage._VERROU:
        raisons += ["découpage en tomes" for e in decoupage._ETAT.values() if e.get("en_cours")][:1]
    # la lecture d'un sommaire n'est pas comptée : rien n'est écrit avant la fin, elle est refaite toute seule après un redémarrage
    raisons += ["écriture des chapitres dans un tome" for e in list(_SIGNETS.values()) if e.get("en_cours")][:1]
    import optimiser
    with optimiser._VERROU:
        raisons += [f"allègement de {n}" for n, e in optimiser._ETAT.items() if e.get("en_cours")]
    raisons += [f"conversion de {n}" for n, e in list(_CONVERSION.items()) if e.get("en_cours")]
    raisons += [f"lecture des ISBN de {n}" for n, e in list(_ISBN_SERIE.items()) if e.get("en_cours")]
    return raisons


# ---------------- 🧲 Torrents (Prowlarr → qBittorrent → import) : admin seulement ----------------
import couvertures_tomes
import hors_serie
import provenance
import regles
import torrents
torrents._ETAT["fichier"] = DATA_DIR / "torrents.json"


def _tomes_de(nom, entrees=None):
    """Numéros des tomes présents d'une série."""
    if entrees is None:
        entrees = _entrees(_scan().get(nom) or [])
    return {e["tome"] for e in entrees if e.get("tome") is not None}


def _remplacer_tomes(nom, numeros):
    """Meilleure version : les tomes déjà présents que le torrent apporte vont à la corbeille (30 jours) ; un tome
    lu (en entier, ou tous ses chapitres « #n ») reste marqué lu pour chaque personne. Renvoie le nombre remplacé."""
    dossier, n = MANGA_DIR / nom, 0
    for t in sorted(numeros):
        ancien = tomes_cbz.fichier_tome(dossier, nom, t)
        if not ancien.exists():
            continue
        chap = {"#" + (str(int(x["num"])) if float(x["num"]).is_integer() else str(x["num"])) for x in tomes_cbz.chapitres(ancien)} \
            if tomes_cbz.lire_info(ancien) is not None else set()
        cle = _rel(ancien)
        with _progress_lock:
            for _pf in _fichiers_progression():
                data = _read_json(_pf, {})
                p = data.get(nom)
                if p and (cle in p.get("read", []) or (chap and chap <= set(p.get("read", [])))):
                    p["read"] = sorted(set(p["read"]) - chap | {cle})
                    _write_json(_pf, data)
        _vers_corbeille(ancien)
        try:
            ancien.parent.rmdir()                       # « Tome NN » vidé par le remplacement : pas de dossier vide qui traîne
        except OSError:
            pass
        n += 1
    if n:
        import edition
        edition.invalider(dossier)
    return n


_MOT_INTEGRALE = re.compile(r"int[ée]grale|perfect|deluxe|omnibus|kanzenban|ultimate|collector", re.I)


def _tomes_hors_integrale(nom, titre, nouveaux):
    """Remplacer par une intégrale (« Perfect INTEGRALE », « Perfect Édition (01-18) »…) : les tomes qu'elle ne contient pas
    (ex. les tomes 19 à 27 de l'ancienne édition) sont retirés aussi. Seulement si elle annonce N tomes et les apporte tous
    (1 à N) : sinon, rien de plus n'est retiré. Renvoie l'ensemble des numéros à mettre à la corbeille."""
    import edition
    titre_plat = re.sub(r"[._]+", " ", titre or "")
    n = edition.volumes_du_titre(titre_plat)
    if not n or not (_MOT_INTEGRALE.search(titre_plat) or edition.edition_du_titre(titre_plat)):
        return set()
    if not set(range(1, n + 1)) <= set(nouveaux):
        return set()
    presents = {_tome_de_entree(e) for e in _entrees(_scan().get(nom) or [])} - {None}
    return {t for t in presents if t not in nouveaux and t > 0}


def _zip_images_du_torrent(source, fichiers, dest):
    """Torrent fait seulement de dossiers d'images (« Arago Tome 01/001.jpg ») : les images sont rangées, avec leurs dossiers,
    dans un zip caché de « <série>/.torrent/ », que l'import traite comme n'importe quelle archive. None si le torrent
    contient aussi des archives ou des PDF (les images éventuelles ne sont alors que des couvertures)."""
    images = [f for f in fichiers if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    if not images or len(images) != sum(1 for f in fichiers if f.suffix.lower() not in (".nfo", ".txt")) or not source.is_dir():
        return None
    cible = dest / (source.name + ".zip")
    if cible.exists():
        return cible
    dest.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_name("." + cible.name + ".copie")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
            for f in images:
                z.write(f, f.relative_to(source).as_posix())
        os.replace(tmp, cible)
    finally:
        if tmp.exists():
            tmp.unlink()
    return cible


_TOMES_DU_TORRENT = {}          # série → tomes vraiment arrivés avec le dernier torrent (nouveaux ou remplacés)


def _empreintes_tomes(nom):
    """{tome: (taille, date, inode)} des fichiers de tome de la série, pour savoir après un import lesquels ont changé."""
    out = {}
    for e in _entrees(_scan().get(nom) or []):
        t = _tome_de_entree(e)
        if t is None or e.get("a_importer") or t in out:
            continue
        try:
            st = os.stat(MANGA_DIR / e["path"])
            out[t] = (st.st_size, st.st_mtime_ns, st.st_ino)
        except OSError:
            continue
    return out


# ---------------- Œuvres dérivées (spin-off, histoires annexes, gaiden) : reconnues d'après AniList ----------------
_RELATIONS_DERIVEES = ("SIDE_STORY", "SPIN_OFF", "SEQUEL", "PREQUEL", "ALTERNATIVE", "OTHER")


def _titre_derive(nom, rel):
    """« A Letter from Keisuke Baji » : titre de l'œuvre liée sans le nom de la série mère."""
    titre = next((t for t in rel.get("titres") or [] if re.search(r"[a-z]", t)), (rel.get("titres") or ["Hors-série"])[0])
    simple_serie = tomes._simple(nom)
    mots = titre.replace("卍", " ").split()
    while mots and tomes._simple(mots[0]).strip() and tomes._simple(mots[0]) in simple_serie.split():
        mots.pop(0)
    return re.sub(r"^[\s:–-]+", "", " ".join(mots)).strip() or titre


def _relier_univers(mere, fille):
    """Met la série dérivée dans l'univers de la série mère (créé au nom de la mère s'il n'existe pas). Un univers choisi
    à la main n'est jamais changé."""
    import edition
    dm, df = edition.lire(MANGA_DIR / mere), edition.lire(MANGA_DIR / fille)
    univers = dm.get("univers") or df.get("univers") or mere
    if df.get("univers") and df["univers"] != univers:
        return
    ordres = [_univers_de(x)["ordre_univers"] or 0 for x in _scan() if _univers_de(x)["univers"] == univers]
    if not dm.get("univers"):
        dm.update(univers=univers, ordre_univers=dm.get("ordre_univers") or 1)
        edition.ecrire(MANGA_DIR / mere, dm)
    if not df.get("univers"):
        df.update(univers=univers, ordre_univers=max(ordres + [1]) + 1)
        edition.ecrire(MANGA_DIR / fille, df)
        logger.info("Univers « %s » : « %s » relié à « %s »", univers, fille, mere)


def _serie_derivee(nom, rel):
    """Série de la bibliothèque qui EST déjà cette œuvre dérivée (même titre), ou un nom neuf « Mère - Titre »."""
    for x in _scan():
        if x not in (nom, "(Sans série)") and (tomes.classer(nom, x, [rel]) or {}).get("id") == rel["id"]:
            return x
    return f"{nom} - {_titre_derive(nom, rel)}"


def _ranger_oeuvres_derivees(nom, fichiers):
    """Fichiers d'un torrent qui sont une œuvre liée à la série (AniList) : un spin-off de plusieurs tomes va dans SA
    série (reliée par univers), une histoire annexe d'un seul livre devient un hors-série de la série. Renvoie les
    fichiers qui restent pour la série elle-même."""
    try:
        if not ((tomes._charger(nom) or {}).get("statut_officiel") or {}).get("anilist"):
            tomes.statut_officiel(nom)                   # série neuve : sa fiche AniList d'abord (ses œuvres liées en dépendent)
        liste = [r for r in tomes.relations(nom) if r["relation"] in _RELATIONS_DERIVEES]
    except Exception:
        liste = []
    par_rel = {}
    for f in fichiers:
        if torrents.suffixe(f) not in (".cbz", ".cbr", ".pdf"):
            continue
        rel = tomes.classer(nom, torrents.nom_sans_ext(f), liste)
        if not rel and tomes.reste_du_nom(nom, torrents.nom_sans_ext(f)):     # titre inconnu : une œuvre nouvelle sur AniList ?
            liste = [r for r in tomes.relations(nom, forcer=True) if r["relation"] in _RELATIONS_DERIVEES]
            rel = tomes.classer(nom, torrents.nom_sans_ext(f), liste) or tomes.chercher_oeuvre(nom, torrents.nom_sans_ext(f))
        rel = rel or _derive_par_mot(nom, torrents.nom_sans_ext(f))
        if rel:
            par_rel.setdefault(rel["id"], (rel, []))[1].append(f)
    if not par_rel:
        return fichiers
    import edition
    restent = [f for f in fichiers if not any(f in fs for _, fs in par_rel.values())]
    for rel, fs in par_rel.values():
        if (rel.get("volumes") or 0) >= 2 or len(fs) >= 2:              # spin-off en plusieurs tomes : sa propre série
            fille = _serie_derivee(nom, rel)
            dossier = MANGA_DIR / fille
            for f in fs:
                ext, t = torrents.suffixe(f), _numero_tome(torrents.nom_sans_ext(f))
                cible = tomes_cbz.fichier_tome(dossier, fille, t).with_suffix(ext) if t is not None else dossier / (torrents.nom_sans_ext(f) + ext)
                if not cible.exists():
                    torrents.lier(f, cible)
            _scan_invalider()
            _relier_univers(nom, fille)
            logger.info("Torrent → « %s » : %d fichier(s) de « %s » (spin-off) placés dans sa série « %s »", nom, len(fs), rel["titres"][0], fille)
            try:
                _lancer_import(fille, attendre=True)
            except Exception as e:
                logger.warning("Import de la série dérivée « %s » : %s", fille, e)
        else:                                                           # un seul livre : hors-série de la série
            titre = _titre_derive(nom, rel)
            infos = edition.lire(MANGA_DIR / nom)
            for f in fs:
                cible = MANGA_DIR / nom / f"{nom} HS - {titre}{torrents.suffixe(f)}"
                if not cible.exists():
                    torrents.lier(f, cible)
                place = tomes.place_par_date(nom, rel.get("debut"), max(_tomes_de(nom) or [0]))
                if place:
                    infos.setdefault("places_hs", {})[cible.name] = place
            edition.ecrire(MANGA_DIR / nom, infos)
            logger.info("Torrent → « %s » : « %s » rangé en hors-série", nom, titre)
    return restent


_MOT_DERIVE = re.compile(r"\bgaiden\b|side[ -]?stor(?:y|ies)|spin[ -]?off|\bbangai|\bextras?\b", re.I)


def _derive_par_mot(nom, nom_fichier):
    """Secours quand AniList ne connaît pas l'œuvre : « Tokyo.Revengers.Side.Stories.T01 » (mot de récit dérivé après le
    nom de la série) → œuvre « Side Stories ». Jamais sur le seul nom d'un auteur ou d'une équipe (il faut un de ces mots)."""
    reste = tomes.reste_du_nom(nom, nom_fichier)
    plat = re.sub(r"[._]+", " ", re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", nom_fichier))
    if not reste or not _MOT_DERIVE.search(" ".join(reste) if len(reste) > 1 else plat):
        return None
    if not _MOT_DERIVE.search(plat):
        return None
    mots = [m for m in plat.split() if tomes._simple(m) in reste]
    titre = " ".join(dict.fromkeys(mots)) or " ".join(reste)
    return {"id": "mot:" + " ".join(reste), "relation": "SIDE_STORY", "volumes": None, "debut": "", "titres": [titre]}


def _placer_hors_series(nom):
    """Préparation : chaque hors-série sans place connue est placé dans l'ordre de lecture d'après sa date de sortie au
    Japon (œuvre liée sur AniList), et les séries dérivées de la bibliothèque sont reliées par univers."""
    import edition
    try:
        liste = tomes.relations(nom)
    except Exception:
        return
    if not liste:
        return
    infos = edition.lire(MANGA_DIR / nom)
    places = infos.get("places_hs") or {}
    change = False
    for e in _entrees(_scan().get(nom) or []):
        if e.get("groupe") != HORS_SERIE or e.get("identifie") or Path(e["path"]).name in places:
            continue
        rel = tomes.classer(nom, Path(e["path"]).stem, liste) or tomes.chercher_oeuvre(nom, Path(e["path"]).stem)
        place = tomes.place_par_date(nom, rel.get("debut"), max(_tomes_de(nom) or [0])) if rel else None
        if place:
            places[Path(e["path"]).name] = place
            change = True
    if change:
        infos = edition.lire(MANGA_DIR / nom)
        infos["places_hs"] = places
        edition.ecrire(MANGA_DIR / nom, infos)
    for rel in liste:                                    # séries de la bibliothèque qui sont des œuvres dérivées de celle-ci
        if rel["relation"] not in ("SPIN_OFF", "SIDE_STORY"):
            continue
        for x in _scan():
            if x not in (nom, "(Sans série)") and (tomes.classer(nom, x, [rel]) or {}).get("id") == rel["id"]:
                _relier_univers(nom, x)


def _importer_torrent(nom, source, remplacer=False):
    """Contenu d'un torrent → bibliothèque, sans jamais renommer ni effacer ses fichiers (le NAS le refuse tant que
    qBittorrent partage) : un tome complet est placé directement sous « Tome NN/<série> - Tome NN.cbz », un chapitre
    à la racine de la série, une archive ou un PDF dans « <série>/.torrent/ » (caché) puis extrait comme un import."""
    dossier = MANGA_DIR / nom
    fichiers = torrents.fichiers_du_torrent(Path(source))
    if not fichiers:
        raise RuntimeError("aucun fichier de manga dans le torrent")
    import edition
    fichiers = _ranger_oeuvres_derivees(nom, fichiers)  # spin-off → sa propre série ; histoire annexe d'un livre → hors-série
    empreintes_avant = _empreintes_tomes(nom)
    deja_note = Path(source).name in (edition.lire(dossier).get("archives") or [])
    a_tomes = {}
    for f in fichiers:
        if torrents.suffixe(f) in (".cbz", ".cbr") and _numero_tome(torrents.nom_sans_ext(f)) is not None:
            a_tomes.setdefault(_numero_tome(torrents.nom_sans_ext(f)), f)
    if remplacer:
        hors = _tomes_hors_integrale(nom, Path(source).name, set(a_tomes))
        if hors:
            logger.info("Intégrale « %s » : tomes absents de cette édition mis à la corbeille : %s", nom, sorted(hors))
        avant = _tomes_de(nom)
        logger.info("Meilleure version de « %s » : %d tome(s) remplacé(s)", nom, _remplacer_tomes(nom, set(a_tomes) | hors))
        if avant and avant <= (set(a_tomes) | hors):        # plus aucun ancien tome : l'ancienne source ne reste pas à côté de la nouvelle
            import edition
            edition.oublier_source(dossier)
    lots, places = [], 0
    for f in fichiers:
        ext = torrents.suffixe(f)                        # « .cbz.part » complet : placé en « .cbz »
        nom_f = torrents.nom_sans_ext(f) + ext
        if ext in (".cbz", ".cbr"):
            t = _numero_tome(torrents.nom_sans_ext(f))
            cible = tomes_cbz.fichier_tome(dossier, nom, t).with_suffix(ext) if t is not None and a_tomes.get(t) == f else dossier / nom_f
        elif ext in (".zip", ".rar", ".7z", ".pdf"):
            cible = dossier / ".torrent" / nom_f
            lots.append(cible)
        elif ext in (".nfo", ".txt"):
            cible = dossier / ".torrent" / f.name
        else:
            continue
        if cible.exists():
            continue
        torrents.lier(f, cible)
        places += 1
    try:
        import edition
        edition.noter_import(dossier, Path(source).name, dossier / ".torrent")
    except Exception as e:
        logger.warning("Infos de l'édition du torrent (%s) : %s", nom, e)
    zip_images = _zip_images_du_torrent(Path(source), fichiers, dossier / ".torrent")
    if zip_images:                                   # torrent fait de dossiers d'images : un zip, importé comme une archive
        lots.append(zip_images)
        places += 1
    logger.info("Torrent → « %s » : %d fichier(s) placé(s), %d archive(s) à extraire", nom, places, len(lots))
    fin = _lancer_import(nom, attendre=True, lots_forces=lots)
    apres = _empreintes_tomes(nom)
    venus = {t for t, v in apres.items() if empreintes_avant.get(t) != v}
    _TOMES_DU_TORRENT[nom] = venus
    if not venus and not deja_note:
        # aucun tome n'est venu de ce torrent (tous déjà là, rien remplacé) : il n'est pas noté comme source de la série,
        # sinon la fiche laisserait croire que les anciens tomes ont été remplacés
        infos = edition.lire(dossier)
        if Path(source).name in (infos.get("archives") or []):
            infos["archives"].remove(Path(source).name)
            edition.ecrire(dossier, infos)
        logger.info("Torrent → « %s » : aucun tome nouveau ni remplacé, la source de la série reste la même", nom)
    _prevenir_lecteurs(nom)
    return fin


# ---------------- ➕ Séries suivies (ajout comme Sonarr, surveillance, surclassement) : admin ----------------
import suivi
suivi._ETAT["fichier"] = DATA_DIR / "suivies.json"
import lecture_pages
import page_tracker
page_tracker.FICHIER = DATA_DIR / "torrent-pages.json"
lecture_pages.NOMS = lambda nom: tomes.noms_de_recherche(nom)[0]
suivi.AUTRES_SERIES = lambda nom: [n for n in _scan() if n not in (nom, "(Sans série)")]


def _infos_suivi(nom):
    """Tomes présents et source de l'édition d'une série (pour juger les propositions de torrents)."""
    files = _scan().get(nom) or []
    entrees = _entrees(files) if files else []
    t = {int(e["tome"]) for e in entrees if e.get("tome") is not None}
    t |= {int(e["groupe"].split()[1]) for e in entrees if (e.get("groupe") or "").startswith("Tome ")}
    import edition
    d = edition.lire(MANGA_DIR / nom) if files else {}
    source = d.get("source_manuelle") or (d.get("analyse") or {}).get("source", "")
    attendus = _volumes_attendus(nom) if files else None
    complete = bool(attendus) and all(i in t for i in range(1, int(attendus) + 1))
    # Torrents pas encore finis : ils ne bloquent que leurs propres tomes ; un torrent dont le nom ne dit pas les tomes (intégrale
    # « 10 tomes »…) bloque toute la série tant qu'il n'est pas fini ou raté
    tomes_en_cours, en_cours = set(), False
    for j in torrents.en_cours_de(nom):
        tj = suivi.tomes_du_titre(j.get("titre") or "")
        if tj:
            tomes_en_cours |= tj
        else:
            en_cours = True
    # Équipe de chaque tome (provenance) et équipe principale de la série (la plus fréquente, sinon celle de l'archive d'origine)
    from collections import Counter
    equipe_tomes = {int(k): v.get("equipe") for k, v in provenance.lire(d).items() if v.get("equipe") and str(k).isdigit()}
    principale = Counter(equipe_tomes.values()).most_common(1)
    equipe = principale[0][0] if principale else next((provenance.equipe_torrent(a) for a in d.get("archives", []) if provenance.equipe_torrent(a)), "")
    # Qualité de ce qu'on possède d'après le profil de la série : points du nom du torrent d'où vient chaque tome
    profil = regles.profil_pour(nom)
    origines = {int(k): v["origine"].split(" : ", 1)[1] for k, v in provenance.lire(d).items()
                if str(k).isdigit() and str(v.get("origine") or "").startswith("Torrent : ")}
    scores = {tome: regles.score_titre(titre, nom) for tome, titre in origines.items()} if profil else {}
    return {"tomes": t, "source": source, "complete": complete, "en_cours": en_cours, "tomes_en_cours": tomes_en_cours,
            "attendus": attendus or _volumes_attendus(nom),       # série encore vide : nombre de tomes d'AniList (série finie)
            "deja_pris": torrents.deja_pris(), "equipe": equipe, "equipe_tomes": equipe_tomes,
            "profil": profil is not None, "scores_tomes": scores, "arret": (profil or {}).get("score_arret"),
            "sources_tomes": d.get("sources_tomes") or {}}


def _lancer_torrent(lien, titre, nom, remplacer=True, page=""):
    """Envoi d'un torrent choisi par la surveillance (🤖 Auto, même équipe) à qBittorrent."""
    return torrents.lancer(lien, titre, nom, remplacer, str(page or "")[:600])


def _verifier_serie(nom):
    """Vérification complète d'une série suivie, avec son message Telegram (flux des nouveautés, torrent raté, interrupteur 🤖)."""
    import notifier
    return suivi.verifier_et_prevenir(nom, torrents.chercher, _infos_suivi, lambda t: notifier.envoyer(t),
                                      lambda: os.getenv("APP_URL", "").strip(), _lancer_torrent, lecture_pages.lire_en_fond)


def _apres_rate(rates):
    """Téléchargements ratés (bloqués ou supprimés de qBittorrent) : un seul message ; pour une série surveillée, une autre version est
    cherchée tout de suite (le torrent raté ne sera plus jamais proposé ; en 🤖 Auto, le suivant part tout seul)."""
    import notifier
    suivies = suivi.lire()["series"]
    a_chercher = sorted({j["serie"] for j in rates if j.get("chercher") and (suivies.get(j["serie"]) or {}).get("surveiller")})
    lignes = [f"• {j['serie']} : « {suivi._sans_point(j['titre'][:80])} » ({j['raison']})" for j in rates]
    suite = []
    if a_chercher:
        suite.append("🔎 Autre version cherchée pour : " + ", ".join(a_chercher))
    if any(j.get("chercher") and j["serie"] not in a_chercher for j in rates):
        suite.append("Pour les autres séries : cherche une autre version dans Télécharger → Torrents.")
    notifier.envoyer("⛔ MouFlanga : téléchargement" + ("s" if len(rates) > 1 else "") + " raté" + ("s" if len(rates) > 1 else "")
                     + ", retiré" + ("s" if len(rates) > 1 else "") + " de qBittorrent\n" + "\n".join(lignes + suite))

    def chercher_encore():
        for nom in a_chercher:
            try:
                _verifier_serie(nom)
            except Exception as e:
                logger.warning("Autre version pour %s : %s", nom, e)
            time.sleep(20)
    if a_chercher:
        threading.Thread(target=chercher_encore, daemon=True).start()


torrents._ETAT["apres_rate"] = _apres_rate


def _accepter_demande(x):
    nom = _nom_serie(x.get("titre", ""))
    suivi.ajouter(nom, x, surveiller=True)




@app.route("/api/suivies", methods=["GET", "POST"])
def api_suivies():
    if request.method == "GET":
        return jsonify({"series": {n: suivi.sans_liens(x) for n, x in suivi.lire()["series"].items()}})
    body = request.get_json(silent=True) or {}
    action, nom = str(body.get("action", "")), _nom_serie(str(body.get("nom", "")).strip())
    if action == "ajouter":
        if not nom or nom == "sans-titre":
            return jsonify({"ok": False, "error": "Nom de série manquant"}), 400
        suivi.ajouter(nom, body.get("serie") or {}, surveiller=body.get("surveiller", True), qualite=body.get("qualite", "Digital"))
        return jsonify({"ok": True, "nom": nom, "message": f"« {nom} » ajoutée : elle apparaît grisée dans la bibliothèque tant qu'elle est vide."})
    d = suivi.lire()
    if nom not in d["series"]:
        if action == "surveiller" and nom in _scan():
            st = (tomes._charger(nom) or {}).get("statut_officiel") or {}
            suivi.ajouter(nom, {"titre": st.get("titre") or ""}, surveiller=bool(body.get("actif", True)))
            return jsonify({"ok": True, "message": f"« {nom} » est surveillée : vérification chaque jour."})
        return jsonify({"ok": False, "error": "Série non suivie"}), 404
    if action == "surveiller":
        with suivi._verrou:
            d = suivi.lire(); d["series"][nom]["surveiller"] = bool(body.get("actif"))
            if not body.get("actif"):                       # plus surveillée : les propositions en attente disparaissent avec la surveillance
                d["series"][nom]["propositions"] = [p for p in d["series"][nom].get("propositions", []) if p.get("statut") != "attente"]
            suivi.ecrire(d)
        return jsonify({"ok": True, "message": "Surveillance activée : vérification chaque jour." if body.get("actif") else "Surveillance coupée."})
    if action == "auto":
        actif = bool(body.get("actif"))
        with suivi._verrou:
            d = suivi.lire(); d["series"][nom]["auto"] = actif
            if actif:
                d["series"][nom]["surveiller"] = True            # le mode automatique passe par la surveillance
            suivi.ecrire(d)
        if not actif:
            return jsonify({"ok": True, "message": "🤖 Téléchargement automatique coupé : les torrents trouvés restent des propositions."})
        if torrents.configure():
            threading.Thread(target=_verifier_serie, args=(nom,), daemon=True).start()
        return jsonify({"ok": True, "message": "🤖 Téléchargement automatique activé : les tomes manquants partent tout seuls dès qu'un torrent "
                                               "accepté par ton profil est trouvé (un seul par tome, le mieux noté). Vérification lancée."})
    if action == "qualite":
        with suivi._verrou:
            d = suivi.lire(); d["series"][nom]["qualite"] = "Digital" if body.get("qualite") == "Digital" else "Indifférente"; suivi.ecrire(d)
        return jsonify({"ok": True, "message": "Qualité visée enregistrée."})
    if action == "retirer":
        with suivi._verrou:
            d = suivi.lire(); d["series"].pop(nom, None); suivi.ecrire(d)
        if not _scan().get(nom):                       # série sans fichier : ce qu'on avait appris sur elle part avec elle
            tomes.oublier(nom)
        return jsonify({"ok": True, "message": f"« {nom} » n'est plus suivie."})
    if action == "ignorer":
        with suivi._verrou:
            d = suivi.lire()
            for p in d["series"][nom].get("propositions", []):
                if p["id"] == body.get("id"):
                    p["statut"] = "ignore"
            suivi.ecrire(d)
        return jsonify({"ok": True, "message": "Proposition ignorée."})
    if action == "telecharger":
        # ⬇️ d'une proposition : un clic, ça part. Le lien de Prowlarr n'est jamais gardé : on retrouve le torrent par son nom.
        if not torrents.configure():
            return jsonify({"ok": False, "error": "Prowlarr et qBittorrent ne sont pas encore réglés (⚙️ Réglages → Connexions)."}), 400
        p = suivi.proposition(nom, str(body.get("id", "")))
        if not p or p.get("statut") != "attente":
            return jsonify({"ok": False, "error": "Cette proposition n'existe plus."}), 404
        trouve = None
        try:
            for t in list(dict.fromkeys([p["titre"], nom] + (d["series"][nom].get("titres") or [])))[:3]:
                trouve = next((x for x in torrents.chercher(t, serie=nom, avec_rejets=True) if x["titre"] == p["titre"] and x.get("lien")), None)
                if trouve:
                    break
        except Exception as e:
            return jsonify({"ok": False, "error": f"Recherche impossible : {e}"}), 502
        if not trouve:
            return jsonify({"ok": False, "error": "Prowlarr ne propose plus ce torrent : relance « Vérifier maintenant »."}), 404
        if "anglais" in (trouve.get("rejet") or ""):
            return jsonify({"ok": False, "error": "Ce torrent est marqué en anglais : jamais pris."}), 400
        try:
            torrents.lancer(trouve["lien"], trouve["titre"], nom, p["type"] in ("meilleur", "equipe"), str(trouve.get("page", ""))[:600])
        except Exception as e:
            return jsonify({"ok": False, "error": f"qBittorrent : {e}"}), 502
        with suivi._verrou:
            d = suivi.lire()
            for q in (d["series"].get(nom) or {}).get("propositions", []):
                if q["id"] == p["id"]:
                    q["statut"] = "telecharge"
            suivi.ecrire(d)
        suite = "les tomes remplacés iront à la corbeille" if p["type"] in ("meilleur", "equipe") else "seuls les tomes manquants seront ajoutés"
        return jsonify({"ok": True, "message": f"Envoyé à qBittorrent : {suite}. Suivi dans Télécharger → Torrents."})
    if action == "verifier":
        if not torrents.configure():
            return jsonify({"ok": False, "error": "Prowlarr n'est pas réglé."}), 400
        try:
            nouv = suivi.verifier(nom, torrents.chercher, _infos_suivi, _lancer_torrent, apres=lecture_pages.lire_en_fond)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Recherche impossible : {e}"}), 502
        partis = [p for p in nouv if p.get("auto")]
        reste = len(nouv) - len(partis)
        morceaux = ([f"🤖 {len(partis)} torrent(s) envoyé(s) tout seul(s) ({suivi.plage([t for p in partis for t in p.get('tomes') or []])})"] if partis else []) \
            + ([f"{reste} nouvelle(s) proposition(s)"] if reste else [])
        return jsonify({"ok": True, "message": " · ".join(morceaux) + "." if morceaux else "Rien de nouveau pour l'instant."})
    return jsonify({"ok": False, "error": "Action inconnue"}), 400


def _message_court_nouveaux_tomes(nom, titre_torrent, numeros):
    """Série qui existait déjà : une ligne « tomes ajoutés » suffit (le compte rendu complet est pour l'arrivée d'une série neuve).
    Les tomes arrivés sont ceux dont la provenance est ce torrent ; si tous les tomes de la série en viennent, ou si on ne sait pas, « » (rapport complet)."""
    import edition
    try:
        prov = provenance.lire(edition.lire(MANGA_DIR / nom))
    except Exception:
        return ""
    arrives = sorted(int(k) for k, v in prov.items() if str(k).isdigit() and str(v.get("origine") or "").endswith(" : " + titre_torrent))
    if not arrives or not (set(numeros) - set(arrives)):
        return ""
    n = len(arrives)
    return f"📗 {nom} : {'tome' if n == 1 else 'tomes'} {suivi.plage(arrives).replace('T', '')} ajouté{'' if n == 1 else 's'}"


def _rapport_serie(nom, titre_torrent, origine="🧲 Torrent"):
    """Compte rendu Telegram d'une série arrivée par torrent : import, édition, parution, auteurs, éditeurs, générique,
    synopsis, demande d'un lecteur, surveillance. Les infos manquantes sont cherchées tout de suite."""
    import edition
    files = _scan().get(nom) or []
    entrees = _entrees(files)
    numeros = sorted({int(_tome_de_entree(e)) for e in entrees if _tome_de_entree(e) is not None})
    court = _message_court_nouveaux_tomes(nom, titre_torrent, numeros)
    if court:
        return court
    taille = sum(f.stat().st_size for f in files if f.exists()) / 1073741824
    tome_max = max(numeros) if numeros else None
    st = tomes.statut_officiel(nom, tome_max=tome_max) or {}
    fi = tomes.fiche(nom) if st else {}
    try:
        a = edition.analyser(sorted(files, key=lambda f: f.name), " ".join(edition.lire(MANGA_DIR / nom).get("archives", [])) + " " + titre_torrent)
        d = edition.lire(MANGA_DIR / nom); d["analyse"] = a; edition.ecrire(MANGA_DIR / nom, d)
    except Exception:
        a = {}
    etat, etat_texte = _etat_serie(nom, entrees)
    gen = ""
    if _theme_de(_anime_de(nom)):
        gen = f"générique de l'anime « {_anime_de(nom).name} » (Emby)"
    else:
        try:
            r = generiques.pour_serie(nom, MANGA_DIR / nom, st.get("anilist"))
            g = generiques.lire().get(nom) or {}
            gen = {"ok": f"OP1 de « {g.get('anime', '')} » ajouté", "deja": "déjà présent", "aucun_anime": "pas d'adaptation animée connue",
                   "aucun_theme": f"anime « {g.get('anime', '')} » sans générique connu"}.get(r, "introuvable")
        except Exception as e:
            gen = f"recherche impossible ({e.__class__.__name__})"
    demandeurs = []
    with demandes._verrou:                          # demande d'un lecteur pour cette série : marquée disponible
        dd = demandes._lire()
        for x in dd["demandes"]:
            if x["statut"] in ("attente", "accepte") and (x.get("anilist") == st.get("anilist") or _cle_nom(x.get("titre", "")) == _cle_nom(nom)):
                x["statut"], x["traitee"] = "dispo", datetime.now().strftime("%Y-%m-%d %H:%M")
                demandeurs.append(x["par"])
        if demandeurs:
            demandes._ecrire(dd)
    sv = suivi.lire()["series"].get(nom) or {}
    plage = f" ({numeros[0]} à {numeros[-1]})" if len(numeros) > 1 else ""
    resume = (_read_json(RESUMES, {}).get(nom) or st.get("resume") or "").strip()
    connus = [int(t) for t in ((tomes._charger(nom) or {}).get("tomes") or {}).values() if t]
    vol = _volumes_attendus(nom) or (max(connus) if connus else None)
    manquants = [t for t in range(1, (vol or tome_max or 0) + 1) if numeros and t not in numeros]
    lignes = [f"📗 MouFlanga : nouvelle série prête — {nom}", "§",
              f"{origine} : {titre_torrent[:100]}",
              f"📚 {_compte(entrees)}{plage} · {taille:.1f} Go".replace(".", ","),
              ("🏷 " + " · ".join(x for x in (a.get("source"), a.get("resolution")) if x)) if a.get("source") or a.get("resolution") else "",
              f"📅 Parution : {fi.get('debut', '?')} → {fi.get('fin') or 'en cours'}" if fi.get("debut") else "",
              ("✅ " if etat == "fini" else "⚠️ " if etat == "incomplet" else "🔄 ") + etat_texte if etat_texte else "",
              f"⚠️ Il manque : tome{'s' if len(manquants) > 1 else ''} {', '.join(map(str, manquants[:20]))}" if manquants else "",
              f"✍️ Scénario : {fi['scenario']}" if fi.get("scenario") else "",
              f"🎨 Dessin : {fi['dessin']}" if fi.get("dessin") and fi.get("dessin") != fi.get("scenario") else "",
              f"🏢 Éditeur : {fi['editeur_fr']} (VF)" + (f" · {fi['editeur_jp']} (Japon)" if fi.get("editeur_jp") else "") if fi.get("editeur_fr") else "",
              f"🎭 Genres : {fi['genres']}" if fi.get("genres") else "",
              f"🎵 Générique : {gen}" if gen else "",
              f"📮 Demandée par : {', '.join(demandeurs)} (marquée disponible)" if demandeurs else "",
              "👁 Surveillée : nouveaux tomes vérifiés chaque jour" if sv.get("surveiller") else "",
              "§", f"📖 {resume[:280].rstrip(' .…')}{'…' if len(resume) > 280 else ''}" if resume else "",
              (os.getenv("APP_URL", "").rstrip("/") + "/#" + __import__("urllib.parse").parse.quote(nom)) if os.getenv("APP_URL") else ""]
    return "\n".join("" if l == "§" else l for l in lignes if l).strip()


torrents._ETAT["rapport"] = _rapport_serie
torrents._ETAT["existantes"] = lambda: sorted(n for n in _scan() if n != "(Sans série)")
torrents._ETAT["nom_serie"] = lambda nom: _nom_depuis_archive(nom + ".zip", sorted(n for n in _scan() if n != "(Sans série)"))


def _remplacer_auto(nom, titre):
    """Torrent ajouté à la main dans une série déjà là : il remplace les tomes s'il est Digital et la série ne l'est pas."""
    if nom not in _scan() or "Digital" not in torrents.badges(titre):
        return False
    return (_infos_suivi(nom).get("source") or "") != "Digital"


torrents._ETAT["remplacer_auto"] = _remplacer_auto


def _tomes_deja_la(nom, source):
    """Numéros des tomes du torrent qui existent déjà dans la série (un même fichier, lien physique, ne compte pas)."""
    dossier, deja = MANGA_DIR / nom, set()
    for f in torrents.fichiers_du_torrent(Path(source)):
        t = _numero_tome(torrents.nom_sans_ext(f)) if torrents.suffixe(f) in (".cbz", ".cbr") else None
        if t is not None:
            ancien = tomes_cbz.fichier_tome(dossier, nom, t)
            if ancien.is_file() and not _meme_fichier(ancien, f):
                deja.add(t)
    return deja


torrents._ETAT["doublons"] = _tomes_deja_la
torrents._ETAT["regle"] = _regle_import
def _noter_volumes_torrent(serie, titre):
    """Fin d'un torrent : son nom devient la provenance des tomes qu'il a VRAIMENT apportés (nouveaux ou remplacés),
    jamais celle des anciens tomes restés en place."""
    import edition
    venus = _TOMES_DU_TORRENT.pop(serie, None)
    if venus is not None and not venus:
        return                                           # rien d'arrivé : ni nombre de tomes ni provenance tirés de ce torrent
    edition.noter_volumes(MANGA_DIR / serie, titre)
    equipe = provenance.equipe_du_nom(titre)
    presents = [(e["tome"], titre) for e in _entrees(_scan().get(serie) or []) if e.get("tome") is not None
                and (venus is None or e["tome"] in venus)]
    if venus:                                            # tome remplacé : l'ancienne provenance décrivait l'ancien fichier
        infos = edition.lire(MANGA_DIR / serie)
        prov = infos.get("provenance") or {}
        if any(prov.pop(str(t), None) for t in venus):
            edition.ecrire(MANGA_DIR / serie, infos)
    _noter_provenances(MANGA_DIR / serie, presents, "Torrent", equipe=equipe)


def _noter_provenances(dossier, paires, origine, equipe=None):
    """Garde l'origine des tomes qui n'en ont pas encore : équipe lue dans le nom d'origine (ou le titre du torrent)."""
    if not paires or not Path(dossier).is_dir():
        return
    import edition
    infos = edition.lire(dossier)
    change = False
    for tome, nom in paires:
        eq = equipe if equipe is not None else provenance.equipe_du_nom(nom)
        change |= provenance.noter(infos, tome, eq, f"{origine} : {nom}")
    if change:
        edition.ecrire(dossier, infos)


torrents._ETAT["volumes"] = _noter_volumes_torrent
tomes.SERIES_EXISTANTES = lambda: [n for n in _scan() if n != "(Sans série)"]


regles.SERIES_CONNUES = lambda: [n for n in _scan() if n != "(Sans série)"] + list(suivi.lire()["series"])


def _equipes_par_serie():
    """{série: équipe dominante} d'après la provenance des tomes de la bibliothèque (au moins 60 % des tomes d'une même équipe)."""
    import edition
    from collections import Counter
    out = {}
    for nom in _scan():
        if nom == "(Sans série)":
            continue
        try:
            c = Counter((v.get("equipe") or "").strip() for v in provenance.lire(edition.lire(MANGA_DIR / nom)).values() if isinstance(v, dict))
        except Exception:
            continue
        c.pop("", None)
        if c:
            eq, n = c.most_common(1)[0]
            if n / sum(c.values()) >= 0.6:
                out[nom] = eq
    return out


def _boucle_equipes():
    """Profils « Manga · <Équipe> » tenus à jour tout seuls (au démarrage, puis toutes les 6 heures)."""
    time.sleep(120)
    while True:
        try:
            b = regles.synchroniser_equipes(_equipes_par_serie())
            if any(b.values()):
                logger.info("Profils d'équipe : %s", b)
        except Exception as e:
            logger.warning("Profils d'équipe : %s", e)
        time.sleep(6 * 3600)


def _annoter_possession(resultats, requete, serie=""):
    """Compare chaque résultat à la bibliothèque : `tomes` (ceux que son nom annonce), `nouveaux` (ceux qu'on n'a pas) et `deja`
    (rien de nouveau). Renvoie {serie, possedes} si la recherche vise une série de la bibliothèque, sinon None. Ne casse jamais la recherche."""
    try:
        cle = regles._resolue(serie or requete)
        nom = next((n for n in _scan() if n != "(Sans série)" and regles._cle(n) == cle), None)
        if not nom:
            return None
        i = _infos_suivi(nom)
        possedes = i["tomes"]
        for x in resultats:
            t = suivi.tomes_couverts(x, i.get("attendus"))
            if t:
                x["tomes"], x["nouveaux"] = sorted(t), sorted(t - possedes)
                x["deja"] = not x["nouveaux"]
        return {"serie": nom, "possedes": len(possedes)}
    except Exception as e:
        logger.warning("Comparaison avec la bibliothèque impossible : %s", e)
        return None


@app.route("/api/torrents/chercher")
def api_torrents_chercher():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"resultats": []})
    if not torrents.configure():
        return jsonify({"error": "Prowlarr et qBittorrent ne sont pas encore réglés (⚙️ Réglages → Connexions)."}), 400
    try:
        # les refusés par le profil sont rendus aussi (marqués `rejet`, en fin de liste) : la page les cache ou les montre
        res = torrents.chercher(q[:100], request.args.get("tout") == "1", serie=(request.args.get("serie") or "").strip()[:100], avec_rejets=True)
        comparaison = _annoter_possession(res, q, (request.args.get("serie") or "").strip())
        return jsonify({"resultats": torrents.publier(res), "bibliotheque": comparaison})
    except Exception as e:
        logger.warning("Recherche Prowlarr impossible : %s", e)
        return jsonify({"error": f"Recherche impossible : {e}"}), 502


@app.route("/api/torrents/auto", methods=["POST"])
def api_torrents_auto():
    """🤖 Téléchargement automatique d'une série. {serie} : montre ce qui serait téléchargé (rien n'est envoyé) ;
    {serie, lancer: true} : l'envoie à qBittorrent (tomes manquants seulement, jamais de remplacement)."""
    import auto_telechargement
    body = request.get_json(silent=True) or {}
    nom = _nom_serie(str(body.get("serie", "")).strip())
    if not nom or nom == "sans-titre":
        return jsonify({"ok": False, "error": "Choisis le nom de la série."}), 400
    if not torrents.configure():
        return jsonify({"ok": False, "error": "Prowlarr et qBittorrent ne sont pas encore réglés (⚙️ Réglages → Connexions)."}), 400
    info = _infos_suivi(nom)
    if info["en_cours"]:
        return jsonify({"ok": True, "torrents": [], "message": "Un téléchargement de toute la série (intégrale) est déjà en cours : attends qu'il soit fini ou raté."})
    attendus = info["attendus"]                     # aussi pour une série encore vide (AniList) : une intégrale peut tout apporter
    titres = list(dict.fromkeys([nom] + (suivi.lire()["series"].get(nom, {}).get("titres") or [])))[:2]
    resultats, vus = [], set()
    try:
        for t in titres:
            for r in torrents.chercher(t, serie=nom):
                if r["titre"] not in vus:
                    vus.add(r["titre"])
                    resultats.append(r)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Recherche impossible : {e}"}), 502
    resultats = [r for r in resultats if r["titre"] not in info["deja_pris"]]          # déjà envoyé (fini, en cours ou raté) : jamais repris
    p = auto_telechargement.plan(resultats, info["tomes"] | info["tomes_en_cours"], attendus, info)
    profil = regles.profil_pour(nom)
    res = [{k: v for k, v in x.items() if k != "lien"} for x in p["torrents"]]
    base = {"ok": True, "profil": profil["nom"] if profil else "", "manquants": p["manquants"], "attendus": attendus, "possedes": len(info["tomes"])}
    if not p["torrents"]:
        return jsonify({**base, "torrents": [], "message": "Rien à télécharger : aucun torrent accepté n'apporte de tome manquant."})
    if not body.get("lancer"):
        return jsonify({**base, "torrents": res})
    envoyes = []
    for x in p["torrents"]:
        try:
            torrents.lancer(x["lien"], x["titre"], nom, x.get("type") == "meilleur", x.get("page", "")[:600])
            envoyes.append(x["titre"])
        except Exception as e:
            logger.warning("Téléchargement automatique de %s : %s", nom, e)
            return jsonify({**base, "ok": False, "torrents": res, "error": f"{len(envoyes)} envoyé(s), puis : {e}"}), 502
    logger.info("Téléchargement automatique lancé à la main pour « %s » : %d torrent(s)", nom, len(envoyes))
    return jsonify({**base, "torrents": res, "message": f"{len(envoyes)} torrent(s) envoyé(s) à qBittorrent : ils seront importés dans « {nom} » à la fin."})


@app.route("/api/regles/tester")
def api_regles_tester():
    """🧪 Page de test des règles : la recherche habituelle, jugée par le profil choisi (`profil` = identifiant, « auto » = celui de la
    série, « aucun » = sans profil). Les refusés sont rendus avec leur raison."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"resultats": []})
    if not torrents.configure():
        return jsonify({"error": "Prowlarr et qBittorrent ne sont pas encore réglés (⚙️ Réglages → Connexions)."}), 400
    choix = request.args.get("profil") or "auto"
    profil = "auto" if choix == "auto" else None if choix == "aucun" else next((x for x in regles.profils() if x["id"] == choix), None)
    if choix not in ("auto", "aucun") and profil is None:
        return jsonify({"error": "Profil introuvable."}), 404
    try:
        res = torrents.chercher(q[:100], False, serie=(request.args.get("serie") or "").strip()[:100], avec_rejets=True, profil=profil)
        comparaison = _annoter_possession(res, q, (request.args.get("serie") or "").strip())
        return jsonify({"resultats": [{k: v for k, v in x.items() if k != "lien"} for x in res], "bibliotheque": comparaison})
    except Exception as e:
        logger.warning("Test des règles impossible : %s", e)
        return jsonify({"error": f"Recherche impossible : {e}"}), 502


@app.route("/api/torrents/page", methods=["POST"])
def api_torrents_page():
    """Lit la page d'un torrent sur son tracker (présentation, NFO) et complète la fiche de la série suivie.
    {serie, proposition} pour une proposition de la surveillance ; {page, titre[, serie]} pour un résultat de recherche."""
    body = request.get_json(silent=True) or {}
    serie, force = _nom_serie(str(body.get("serie", "")).strip(), ""), bool(body.get("force"))
    if body.get("proposition"):
        r = lecture_pages.lire_proposition(serie, str(body["proposition"]), force)
    elif body.get("page"):
        r = lecture_pages.lire_page(serie, str(body["page"]), str(body.get("titre", ""))[:250], None, force)
    else:
        return jsonify({"ok": False, "error": "Page manquante."}), 400
    return jsonify(r)


def _serie_proche(nom):
    """Série déjà là dont le nom ressemble à « nom » sans être le même (édition retirée, un nom contenu dans l'autre)."""
    series = [n for n in _scan() if n != "(Sans série)"]
    if nom in series:
        return ""
    cle = _cle_nom(tomes.sans_edition(nom))
    if len(cle) < 4:
        return ""
    for n in sorted(series, key=len):
        c = _cle_nom(tomes.sans_edition(n))
        if len(c) >= 4 and (c == cle or c.endswith(cle) or cle.endswith(c) or c.startswith(cle) or cle.startswith(c)):
            return n
    return ""


@app.route("/api/torrents", methods=["GET", "POST"])
def api_torrents():
    if request.method == "GET":
        return jsonify({"configure": torrents.configure(), "torrents": torrents.liste()[:30],
                        "series": [] if request.args.get("leger") else sorted(n for n in _scan() if n != "(Sans série)")})
    body = request.get_json(silent=True) or {}
    titre, serie = str(body.get("titre", ""))[:200], _nom_serie(str(body.get("serie", "")).strip())
    lien = torrents.lien_de(body.get("resultat")) or (str(body.get("lien", "")) if str(body.get("lien", "")).startswith("magnet:") else "")
    remplacer = body["remplacer"] if isinstance(body.get("remplacer"), bool) else None
    if not serie or serie == "sans-titre":
        return jsonify({"ok": False, "error": "Choisis le nom de la série."}), 400
    if not lien:
        return jsonify({"ok": False, "error": "Ce résultat n'est plus disponible : relance la recherche."}), 400
    proche = _serie_proche(serie)
    if proche and not body.get("confirme"):       # « Breaker » alors que « CØDE BREAKER » existe : on demande
        return jsonify({"ok": False, "proche": proche, "error": f"Une série au nom proche existe déjà : « {proche} »."}), 409
    try:
        torrents.lancer(lien, titre, serie, remplacer, str(body.get("page", ""))[:600])
        if body.get("proposition"):               # proposition de la surveillance : marquée « vue »
            with suivi._verrou:
                d = suivi.lire()
                for p in (d["series"].get(serie) or {}).get("propositions", []):
                    if p["id"] == body["proposition"]:
                        p["statut"] = "telecharge"
                suivi.ecrire(d)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    return jsonify({"ok": True, "message": f"Envoyé à qBittorrent : il sera importé dans « {serie} » à la fin du téléchargement."})


@app.route("/api/settings/torrents", methods=["GET", "POST"])
def api_settings_torrents():
    from secrets_store import write_secret
    r = torrents.reglages()
    if request.method == "GET":
        return jsonify({"prowlarr": r["prowlarr"], "prowlarr_cle": ("…" + r["prowlarr_cle"][-4:]) if r["prowlarr_cle"] else "",
                        "qbit": r["qbit"], "qbit_user": r["qbit_user"], "qbit_mdp": bool(r["qbit_mdp"]),
                        "nok": r["nok"], "ok": r["ok"], "chemins": r["chemins"], "copie": r["copie"]})
    body = request.get_json(silent=True) or {}
    if body.get("tester"):
        return jsonify({"ok": True, "lignes": torrents.tester()})
    champs = {"PROWLARR_URL": "prowlarr", "QBIT_URL": "qbit", "QBIT_USER": "qbit_user", "TORRENTS_NOK": "nok",
              "TORRENTS_OK": "ok", "TORRENTS_CHEMINS": "chemins", "PROWLARR_API_KEY": "prowlarr_cle", "QBIT_PASSWORD": "qbit_mdp"}
    if "copie" in body:
        write_secret(DATA_DIR / "secrets.env", "TORRENTS_COPIE", "1" if body.get("copie") else "0")
        os.environ["TORRENTS_COPIE"] = "1" if body.get("copie") else "0"
    for env, cle in champs.items():
        if cle not in body:
            continue
        v = str(body[cle]).strip().rstrip("/") if cle not in ("qbit_mdp",) else str(body[cle])
        if cle in ("prowlarr_cle", "qbit_mdp") and not v:
            continue                              # champ secret laissé vide : on garde l'ancien
        if cle == "qbit_mdp":                     # tous les caractères acceptés : rangé codé (base64)
            import base64
            env, v = "QBIT_PASSWORD_B64", base64.b64encode(v.encode("utf-8")).decode("ascii")
            write_secret(DATA_DIR / "secrets.env", "QBIT_PASSWORD", "")
        if set('"$`\\\n\r') & set(v):
            return jsonify({"ok": False, "error": "Caractère interdit (\" $ ` \\) dans un champ."}), 400
        if cle in ("prowlarr", "qbit") and v and not v.startswith(("http://", "https://")):
            return jsonify({"ok": False, "error": "Les adresses commencent par http:// ou https://"}), 400
        write_secret(DATA_DIR / "secrets.env", env, v)
        os.environ[env] = v
    return jsonify({"ok": True, "message": "Réglages des torrents enregistrés."})


@app.route("/importer")
def page_importer():
    return render_template("importer.html", version=APP_VERSION)


_IDENTIFICATIONS = {}          # série -> {"etapes": [...], "fini": bool, "debut": timestamp}
_IDENT_VERROU = threading.Lock()


def _etape(serie, index, etat, detail=""):
    with _IDENT_VERROU:
        e = _IDENTIFICATIONS[serie]["etapes"][index]
        e["etat"], e["detail"] = etat, detail


def _relancer_identification(serie, relire_fichiers=True, nouvelle_identite=False):
    """En arrière-plan : refait toute la recherche de la série (identification.identifier). Rien n'est effacé : chaque source complète
    ou corrige ce qu'on savait, et une source qui ne répond pas ne fait rien perdre (elle est reprise plus tard toute seule).
    nouvelle_identite : une autre fiche AniList vient d'être choisie, ce qu'on savait de l'ancienne ne vaut plus : tout repart de zéro.
    Chaque étape est notée (en cours, réussie, en attente d'un service, ou en échec, avec son résultat) pour l'écran
    (/api/identifier/etat)."""
    noms = [nom for _, nom in identification.ETAPES]
    etapes = [{"nom": nom, "etat": "attente", "detail": ""} for nom in noms] + [
        {"nom": "Rangement des chapitres dans leurs tomes", "etat": "attente", "detail": ""},
        {"nom": "ISBN imprimés dans les tomes (seulement ceux qu'Internet n'a pas)", "etat": "attente", "detail": ""}]
    nb = len(noms)
    with _IDENT_VERROU:
        _IDENTIFICATIONS[serie] = {"etapes": etapes, "fini": False, "debut": time.time()}

    def travail():
        if relire_fichiers:                          # le ComicInfo.xml des tomes est relu aussi (édition, fiche, ISBN, chapitres)
            try:
                import edition
                infos = edition.lire(MANGA_DIR / serie)
                infos.pop("fichiers_relus", None)
                _relire_fichiers_serie(serie, infos)
            except Exception as e:
                logger.info("Relecture des fichiers de « %s » : %s", serie, e.__class__.__name__)
        if nouvelle_identite:
            tomes.oublier(serie)

        indices = {cle: i for i, (cle, _) in enumerate(identification.ETAPES)}

        def rapport(cle, etat, detail):
            _etape(serie, indices[cle], etat, detail)
        bilans = identification.identifier(serie, forcer=True, rapport=rapport)
        # Rangement des chapitres dans leurs tomes
        info = tomes._charger(serie)
        if not (info or {}).get("tomes"):
            _etape(serie, nb, "ok", "rien à ranger (répartition inconnue)")
        elif _en_telechargement(serie):
            _etape(serie, nb, "ok", "série en cours de téléchargement : rangée à la fin")
        else:
            _etape(serie, nb, "en_cours")
            n = _rangement_complet(serie)
            _etape(serie, nb, "echec" if n is None else "ok", (_RANGEMENTS.get(serie) or {}).get("message", ""))
        # ISBN : dernier recours seulement, quand Internet a répondu partout et ne les a pas
        _etape(serie, nb + 1, "en_cours")
        try:
            import sommaire
            reste = _tomes_sans_isbn(serie, auto=True)
            notices_bilan = bilans.get("notices")
            attente = bool(notices_bilan and notices_bilan.extra.get("attente"))
            if not reste:
                _etape(serie, nb + 1, "ok", "tous les tomes ont leur ISBN")
            elif attente:
                _etape(serie, nb + 1, "reprise", f"{len(reste)} tome(s) sans ISBN : on attend qu'Internet réponde plutôt que de lire les pages")
            elif not sommaire.disponible():
                _etape(serie, nb + 1, "ok", f"{len(reste)} tome(s) sans ISBN (lecteur de texte absent du serveur)")
            elif (_ISBN_SERIE.get(serie) or {}).get("en_cours"):
                _etape(serie, nb + 1, "ok", "lecture déjà en cours")
            else:
                threading.Thread(target=_lire_isbn_pages, args=(serie, reste), daemon=True).start()
                _etape(serie, nb + 1, "ok", f"{len(reste)} tome(s) lus dans les pages, en arrière-plan (Internet ne les a pas)")
        except Exception as e:
            _etape(serie, nb + 1, "echec", f"erreur : {e.__class__.__name__}")
        with _IDENT_VERROU:
            _IDENTIFICATIONS[serie]["fini"] = True
        logger.info("Identification relancée : « %s »", serie)
    threading.Thread(target=travail, daemon=True).start()


def _identifier_en_fond(serie, **kw):
    """Lance l'identification d'une série en arrière-plan. Pendant les tests automatiques elle ne part pas toute seule : un fil oublié
    d'un test précédent (qui lit les chapitres de la série) fausserait les tests suivants ; test_avancement_identification appelle
    _relancer_identification directement."""
    if reseau.EN_TEST:
        return
    _relancer_identification(serie, **kw)


def _etapes_etat(serie, index):
    with _IDENT_VERROU:
        return _IDENTIFICATIONS.get(serie, {"etapes": [{}] * 6})["etapes"][index].get("etat")


@app.route("/api/identifier/etat")
def api_identifier_etat():
    """Où en est la ré-identification de la série : étapes, résultat et fin."""
    name = request.args.get("series", "")
    with _IDENT_VERROU:
        etat = _IDENTIFICATIONS.get(name)
        if not etat:
            return jsonify({"presente": False, "etapes": [], "fini": True})
        return jsonify({"presente": True, "etapes": [dict(e) for e in etat["etapes"]], "fini": etat["fini"]})


def _serie_mere(name):
    """« Artbook Kenshin » (série à part) ressemble à un hors-série de « Kenshin le Vagabond » : nom de la série mère, ou ""."""
    if not _est_hors_serie(name):
        return ""
    reste = _cle_nom(_MOTS_HORS_SERIE.sub(" ", name))
    if len(reste) < 3:
        return ""
    meres = [n for n in _scan() if n not in (name, "(Sans série)") and not _est_hors_serie(n)
             and (_cle_nom(n).startswith(reste) or reste.startswith(_cle_nom(n)))]
    return min(meres, key=len) if meres else ""


@app.route("/api/rattacher", methods=["POST"])
def api_rattacher():
    """« 📎 Rattacher comme hors-série » : les fichiers de la série rejoignent une autre série (groupe Hors-série),
    sous le nom « <Série mère> HS - <nom> » ; le dossier vidé va à la corbeille, la progression suit."""
    body = request.get_json(silent=True) or {}
    name, cible = str(body.get("series", "")), str(body.get("cible", ""))
    series = _scan()
    if name not in series or name == "(Sans série)" or cible not in series or cible in (name, "(Sans série)"):
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    if _fichiers_partages(name):
        return jsonify({"ok": False, "error": "Fichiers encore partagés par qBittorrent : retire d'abord le torrent (sans effacer les fichiers)."}), 409
    files = sorted(series[name], key=lambda f: f.name)
    deplaces = {}
    try:
        for i, f in enumerate(files, 1):
            suffixe = f" - {i:02d}" if len(files) > 1 else ""
            dest = MANGA_DIR / cible / (_nom_serie(f"{cible} HS - {name}{suffixe}") + f.suffix.lower())
            if dest.exists():
                return jsonify({"ok": False, "error": f"« {dest.name} » existe déjà dans « {cible} »."}), 409
            f.rename(dest)
            deplaces[_rel(f)] = _rel(dest)
        _vers_corbeille(MANGA_DIR / name)                 # reste : infos, dossiers vides
    except OSError as e:
        return jsonify({"ok": False, "error": f"Déplacement impossible : {e}"}), 500
    with _progress_lock:
        for _pf in _fichiers_progression():
            data = _read_json(_pf, {})
            p = data.pop(name, None)
            if p:
                autre = data.setdefault(cible, {"read": []})
                autre["read"] = sorted(set(autre.get("read", [])) | {deplaces.get(r, r) for r in p.get("read", [])})
                _write_json(_pf, data)
    tomes.oublier(name)
    logger.info("« %s » rattachée comme hors-série de « %s » (%d fichier(s))", name, cible, len(deplaces))
    return jsonify({"ok": True, "id": cible, "message": f"« {name} » est maintenant un hors-série de « {cible} »."})


def _relire_fichiers_serie(serie, infos):
    """Relit le ComicInfo.xml des tomes de la série et reprend ce qui manque ici (réinstallation à zéro, série reçue,
    ré-identification) : fiche AniList et résumé de série écrit à la main, édition (Perfect, colossale…), nombre de tomes,
    ISBN, chapitres avec leurs pages (« liens ») et leur verrou « saisi à la main », titre de série de l'équipe.
    Ne remplace jamais ce qui est déjà noté ici."""
    import edition
    import signets
    dossier = MANGA_DIR / serie
    if not dossier.is_dir():
        return infos
    try:
        fichiers = sorted(dossier.rglob("*.cbz"))[:300]
    except OSError:
        return infos
    vus, titres = 0, []
    for f in fichiers:
        du_fichier = signets.lire_infos(f)
        if not du_fichier:
            continue
        vus += 1
        notes = du_fichier.get("notes") or {}
        if not infos.get("edition"):              # « Perfect », « Édition colossale » : notée par MouFlanga, sinon lue chez l'équipe
            ed = notes.get("edition") or edition.edition_du_titre(
                " ".join((du_fichier.get("format", ""), du_fichier.get("serie", ""), du_fichier.get("titre", ""))))
            if ed:
                infos["edition"] = ed
        if notes.get("volumes_attendus") and not infos.get("volumes_attendus"):
            infos["volumes_attendus"] = int(notes["volumes_attendus"])
        nom_equipe = du_fichier.get("serie", "")
        if nom_equipe and nom_equipe != serie and nom_equipe not in titres:
            titres.append(nom_equipe)             # nom de la série chez l'équipe : une variante de plus pour la recherche
        fiche = notes.get("serie")
        if isinstance(fiche, dict) and fiche.get("anilist") and not (infos.get("anilist_choisi") or infos.get("anilist_indice")):
            try:
                infos["anilist_choisi" if fiche.get("choisi") else "anilist_indice"] = int(fiche["anilist"])
            except (TypeError, ValueError):
                pass
            if fiche.get("resume") and serie not in _read_json(RESUMES, {}):
                perso = _read_json(RESUMES, {})
                perso[serie] = str(fiche["resume"])[:4000]
                _write_json(RESUMES, perso)
        tome = du_fichier.get("tome")
        if tome is None:
            continue
        t = str(int(tome))
        if du_fichier.get("isbn") and not (infos.get("isbn") or {}).get(t):
            infos.setdefault("isbn", {})[t] = du_fichier["isbn"]
        if not ((infos.get("sommaires") or {}).get(t) or {}).get("chapitres"):
            chapitres = signets.lire(f)           # les « liens » : chaque chapitre avec la page de lecture où il commence
            if chapitres:
                rec = {"chapitres": chapitres, "fichier": True}
                if notes.get("sommaire") == "manuel":          # saisi à la main : jamais relu automatiquement
                    rec.update(manuel=True)
                    if notes.get("valide_le"):
                        rec["valide_le"] = notes["valide_le"]  # validé : verrouillé
                    else:
                        rec["saisie"] = True                   # saisie pas encore validée
                infos.setdefault("sommaires", {})[t] = rec
    if titres:
        infos["titres_fichiers"] = titres[:5]
    if vus:
        infos["fichiers_relus"] = True
        try:
            edition.ecrire(dossier, infos)
        except OSError:
            pass
    return infos


def _anilist_infos(serie):
    import edition
    infos = edition.lire(MANGA_DIR / serie)
    if not infos.get("fichiers_relus") and not infos.get("anilist_choisi"):
        infos = _relire_fichiers_serie(serie, infos)
    return infos


def _anilist_choisi(serie):
    """Fiche AniList retenue pour la série : celle de « 🔎 Choisir la fiche » ; sinon, pour une série suivie, celle choisie en l'ajoutant
    (une série suivie encore vide n'a pas de fichier d'où deviner la fiche)."""
    choisi = _anilist_infos(serie).get("anilist_choisi")
    if choisi:
        return choisi
    try:
        return int((suivi.lire()["series"].get(serie) or {}).get("anilist") or 0) or None
    except (TypeError, ValueError):
        return None


tomes.ID_CHOISI = _anilist_choisi
tomes.ID_INDICE = lambda serie: _anilist_infos(serie).get("anilist_indice")
tomes.TITRES_FICHIERS = lambda serie: _anilist_infos(serie).get("titres_fichiers") or []


def _infos_comicinfo(serie):
    """Fiche de la série pour le ComicInfo.xml des tomes (auteur, éditeur, année…) : seulement si la série est
    identifiée (fiche AniList trouvée ou choisie), d'après le cache, sans appel réseau."""
    garde = tomes._charger(serie) or {}
    st, f = garde.get("statut_officiel") or {}, garde.get("fiche") or {}
    if not st.get("anilist"):
        return {}
    annee = re.search(r"(\d{4})", f.get("debut") or "")
    return {"auteur": f.get("scenario", ""), "dessin": f.get("dessin", ""), "editeur": f.get("editeur_fr") or f.get("editeur_jp", ""),
            "annee": annee.group(1) if annee else "", "tomes": _volumes_edition(serie) or st.get("volumes") or "", "genres": f.get("genres", ""),
            "lien": f"https://anilist.co/manga/{st['anilist']}"}


tomes_cbz.INFOS_SERIE = _infos_comicinfo


@app.route("/api/identifier/chercher")
def api_identifier_chercher():
    """« 🔎 Choisir la fiche » : résultats AniList pour les mots tapés (titre japonais, anglais, auteur…)."""
    texte = request.args.get("q", "").strip()[:150]
    if not texte:
        return jsonify({"resultats": []})
    try:
        return jsonify({"resultats": tomes.chercher_anilist(texte)})
    except Exception as e:
        return jsonify({"error": f"Recherche AniList impossible : {e}"}), 502


@app.route("/api/identifier/choisir", methods=["POST"])
def api_identifier_choisir():
    """Retient la fiche AniList choisie (ou l'oublie : retour à la recherche automatique), puis relance l'identification."""
    import edition
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    ident = body.get("anilist")
    infos = edition.lire(MANGA_DIR / name)
    if ident:
        try:
            infos["anilist_choisi"] = int(ident)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Fiche inconnue"}), 400
    else:
        infos.pop("anilist_choisi", None)
    infos.pop("anilist_indice", None)
    infos["fichiers_relus"] = True                    # ton choix l'emporte : les Notes des fichiers ne le remettent pas en cause
    edition.ecrire(MANGA_DIR / name, infos)
    _identifier_en_fond(name, relire_fichiers=False, nouvelle_identite=True)
    return jsonify({"ok": True, "message": "Fiche retenue : identification relancée." if ident else "Retour à la recherche automatique : identification relancée."})


@app.route("/api/identifier", methods=["POST"])
def api_identifier():
    """« 🔄 Relancer l'identification » : refait la recherche avec le nom actuel (rien n'est effacé : on complète et on corrige)."""
    name = str((request.get_json(silent=True) or {}).get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    _identifier_en_fond(name)
    return jsonify({"ok": True, "message": "Identification relancée : les infos se mettent à jour dans quelques instants."})


@app.route("/api/renommer", methods=["POST"])
def api_renommer():
    """« ✏️ Renommer la série » : dossier, fichiers de tome, progression, couverture et infos gardées suivent."""
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    nouveau = _nom_serie(str(body.get("nom", "")).strip())
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    if not nouveau or nouveau.startswith(".") or nouveau == name:
        return jsonify({"ok": False, "error": "Nouveau nom invalide ou identique."}), 400
    fusion = nouveau in _scan() or (MANGA_DIR / nouveau).exists()
    mode = {"remplacer": "remplacer", "manquants": "manquants", "serie": "serie", True: "manquants"}.get(body.get("fusionner"))
    if fusion and not mode:
        a, b = _tomes_de(name), _tomes_de(nouveau)
        return jsonify({"ok": False, "existe": True, "error": f"Une série « {nouveau} » existe déjà.",
                        "communs": len(a & b), "manquants": len(a - b), "tomes_source": len(a), "tomes_cible": len(b),
                        "partage": bool(_fichiers_partages(name))}), 409
    if fusion and not (MANGA_DIR / nouveau).is_dir():
        return jsonify({"ok": False, "error": f"« {nouveau} » existe déjà et n'est pas un dossier."}), 409
    if any((_RANGEMENTS.get(n) or {}).get("en_cours") or any(
            j.get("status") == "running" and japscan_scraper.nom_sur(japscan_scraper.titre_serie(j.get("title") or "")) == n
            for j in japscan_scraper.download_jobs.values()) for n in (name, nouveau)):
        return jsonify({"ok": False, "error": "Cette série est en cours de traitement : attends la fin."}), 409
    if fusion and mode == "serie":
        # « Remplacer toute la série » : l'ancienne part entière à la corbeille (un dossier se déplace même si ses fichiers
        # sont partagés par qBittorrent), puis c'est un simple renommage ; sa progression de lecture est oubliée
        try:
            _vers_corbeille(MANGA_DIR / nouveau)
        except OSError as e:
            return jsonify({"ok": False, "error": f"L'ancienne série « {nouveau} » n'a pas pu aller à la corbeille : {e}"}), 500
        with _progress_lock:
            for _pf in _fichiers_progression():
                data = _read_json(_pf, {})
                if data.pop(nouveau, None) is not None:
                    _write_json(_pf, data)
        tomes.oublier(nouveau)
        logger.info("« %s » remplacée entièrement par « %s » (ancienne à la corbeille)", nouveau, name)
        fusion, mode = False, "serie"
    partage = bool(_fichiers_partages(name))
    if fusion and partage:            # le NAS refuse de déplacer un fichier encore partagé par qBittorrent
        return jsonify({"ok": False, "error": f"Fusion impossible pour l'instant : les fichiers de « {name} » sont encore partagés par "
                        "qBittorrent (le NAS refuse de les déplacer). Retire le torrent de qBittorrent (sans effacer les fichiers), puis recommence."}), 409
    remplaces = 0
    try:
        if fusion and mode == "remplacer":            # les tomes de l'autre série prennent la place des siens (anciens : corbeille)
            avant = _tomes_de(nouveau)
            remplaces = _remplacer_tomes(nouveau, _tomes_de(name))
            if avant and avant <= _tomes_de(name):         # tous les tomes remplacés : l'ancienne source ne reste pas
                import edition
                edition.oublier_source(MANGA_DIR / nouveau)
        nouveau = _organiser(name, nouveau)
        for f in ((MANGA_DIR / nouveau).rglob("*.cbz") if not partage else []):        # « Ancien nom - Tome 03.cbz » → « Nouveau nom - Tome 03.cbz »
            if f.name.startswith(name + " - ") and not f.with_name(nouveau + f.name[len(name):]).exists():
                f.rename(f.with_name(nouveau + f.name[len(name):]))
        tomes.deplacer(name, nouveau)                  # ce qu'on a appris suit la série renommée (jamais perdu)
        doublons = 0
        if fusion and (MANGA_DIR / name).is_dir():     # restent les fichiers déjà présents dans l'autre série : corbeille
            doublons = sum(1 for f in (MANGA_DIR / name).rglob("*") if f.is_file())
            _vers_corbeille(MANGA_DIR / name)
        _noter_choix(name, name, nouveau)
        suivi.renommer(name, nouveau)
    except (OSError, ValueError) as e:
        return jsonify({"ok": False, "error": f"Renommage impossible : {e}"}), 500
    _identifier_en_fond(nouveau)
    if fusion:
        logger.info("Série fusionnée (%s) : « %s » → « %s » (%d remplacé(s), %d doublon(s) à la corbeille)", mode, name, nouveau, remplaces, doublons)
        return jsonify({"ok": True, "id": nouveau, "message": f"Séries fusionnées dans « {nouveau} »."
                        + (f" {remplaces} tome(s) remplacé(s) (anciens à la corbeille)." if remplaces else "")
                        + (f" {doublons} fichier(s) déjà présents mis à la corbeille." if doublons else "")})
    logger.info("Série renommée : « %s » → « %s »", name, nouveau)
    if mode == "serie":
        return jsonify({"ok": True, "id": nouveau, "message": f"« {nouveau} » remplacée par « {name} » (l'ancienne est dans la corbeille 30 jours)."})
    return jsonify({"ok": True, "id": nouveau, "message": "Série renommée."})


# ---------------- Générique de l'anime (MouFlopening) ----------------
_ANIMES = {"date": 0.0, "dossiers": []}
_EXTS_THEME = (".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac")


def _dossier_animes():
    """Dossier des animes d'Emby : réglage MOUFLOPENING_ANIMES, sinon celui de MouFlopening (même serveur)."""
    d = os.getenv("MOUFLOPENING_ANIMES", "").strip()
    if not d:
        try:
            d = (json.loads(Path("/opt/mouflopening/config.json").read_text(encoding="utf-8")).get("library") or {}).get("paths", [""])[0]
        except (OSError, ValueError, IndexError, AttributeError):
            d = ""
    return Path(d) if d else None


def _cle_titre(t):
    """« DAN DA DAN (2024) » et « Dandadan » donnent la même clé : sans année, accents, espaces ni ponctuation."""
    import unicodedata
    t = re.sub(r"\(\d{4}\)|\[[^\]]*\]", "", t or "")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _anime_de(name):
    """Dossier de l'anime qui correspond à la série (même titre, ou titre officiel AniList), ou None."""
    racine = _dossier_animes()
    if not racine:
        return None
    if time.time() - _ANIMES["date"] > 600:
        try:
            _ANIMES["dossiers"] = [d for d in racine.iterdir() if d.is_dir() and not d.name.startswith((".", "@"))]
        except OSError:
            _ANIMES["dossiers"] = []
        _ANIMES["date"] = time.time()
    st = (tomes._charger(name) or {}).get("statut_officiel") or {}
    cles = {k for k in (_cle_titre(name), _cle_titre(st.get("titre") or ""), _cle_titre(st.get("titre_en") or ""),
                        *(_cle_titre(x) for x in name.split(" : "))) if len(k) >= 3}
    exacts = [d for d in _ANIMES["dossiers"] if _cle_titre(d.name) in cles]
    return min(exacts, key=lambda d: len(d.name)) if exacts else None


def _theme_de(dossier):
    """Fichier du générique d'un dossier d'anime (theme.mp3… ou 1er fichier de theme-music/)."""
    if not dossier:
        return None
    for ext in _EXTS_THEME:
        if (dossier / f"theme{ext}").is_file():
            return dossier / f"theme{ext}"
    try:
        sons = sorted(f for f in (dossier / "theme-music").iterdir() if f.suffix.lower() in _EXTS_THEME)
        return sons[0] if sons else None
    except OSError:
        return None


# ---------------- Comptes « lecteur » (admin seulement : les lecteurs n'ont pas accès à ces routes) ----------------
_ID_LECTEUR = re.compile(r"[A-Za-z0-9@+-][A-Za-z0-9._@+-]{1,63}")     # jamais « _admin » (styles de l'admin) ni « . » au début


@app.route("/api/utilisateurs", methods=["GET", "POST"])
def api_utilisateurs():
    from werkzeug.security import generate_password_hash
    if request.method == "GET":
        d = auth.lire_utilisateurs()
        return jsonify({"utilisateurs": [{"id": k, "actif": v.get("actif", True), "cree": v.get("cree", ""), "derniere": v.get("derniere", "")}
                                         for k, v in sorted(d.items(), key=lambda x: x[0].lower())]})
    body = request.get_json(silent=True) or {}
    action, uid, mdp = str(body.get("action", "")), str(body.get("id", "")).strip(), str(body.get("mdp", ""))
    d = auth.lire_utilisateurs()
    if action == "ajouter":
        if not _ID_LECTEUR.fullmatch(uid):
            return jsonify({"ok": False, "error": "Identifiant : 2 à 64 caractères (lettres, chiffres, . _ @ + -), sans espace ni accent, sans « . » ni « _ » au début."}), 400
        if uid in d or uid == os.getenv("APP_USER", ""):
            return jsonify({"ok": False, "error": f"L'identifiant « {uid} » est déjà pris."}), 409
    elif uid not in d:
        return jsonify({"ok": False, "error": "Compte introuvable"}), 404
    if action in ("ajouter", "motdepasse"):
        if len(mdp) < 8:
            return jsonify({"ok": False, "error": "Mot de passe trop court (8 caractères minimum)."}), 400
        d.setdefault(uid, {"actif": True, "cree": datetime.now().strftime("%Y-%m-%d")})["hash"] = generate_password_hash(mdp)
        message = f"Compte « {uid} » créé : il peut se connecter et lire." if action == "ajouter" else \
                  f"Mot de passe de « {uid} » changé (ses anciennes connexions sont fermées)."
    elif action == "activer":
        d[uid]["actif"] = bool(body.get("actif"))
        message = f"Compte « {uid} » " + ("réactivé." if d[uid]["actif"] else "désactivé : il ne peut plus se connecter.")
    elif action == "supprimer":
        d.pop(uid)
        message = f"Compte « {uid} » supprimé (sa progression de lecture est gardée au cas où)."
    else:
        return jsonify({"ok": False, "error": "Action inconnue"}), 400
    auth.ecrire_utilisateurs(d)
    logger.info("Utilisateurs : %s « %s »", action, uid)
    return jsonify({"ok": True, "message": message})


_EDITIONS = [("colossale", "Édition colossale"), ("collector", "Collector"), ("perfect", "Perfect Edition"), ("deluxe", "Deluxe"),
             ("kanzenban", "Kanzenban"), ("ultimate", "Ultimate"), ("double", "Édition double"), ("originale", "Édition originale"),
             ("intégrale", "Intégrale"), ("integrale", "Intégrale")]


@app.route("/api/fiche")
def api_fiche():
    """Bouton ℹ️ : dates de parution, auteurs, genres, éditeurs (AniList + Wikipédia), version de l'édition et source."""
    name = request.args.get("id", "")
    files = _scan().get(name)
    if files is None or name == "(Sans série)":
        return jsonify({"error": "Série introuvable"}), 404
    try:
        f = tomes.fiche(name)
    except Exception as e:
        logger.warning("Fiche de %s : %s", name, e)
        f = {}
    import edition
    ed = edition.lire(MANGA_DIR / name)
    texte = (name + " " + " ".join(ed.get("archives", [])) + " " + " ".join(x.name for x in files[:30])).lower()
    versions = list(dict.fromkeys(v for k, v in _EDITIONS if k in texte))
    s = suivi.lire()["series"].get(name) or {}
    u = _univers_de(name)
    membres = sorted((x for x in _scan() if x != name and _univers_de(x)["univers"] == u["univers"]), key=lambda x: (_univers_de(x)["ordre_univers"] or 0, x)) if u["univers"] else []
    return jsonify({**{k: v for k, v in f.items() if k != "date"}, "versions": versions,
                    "edition": _infos_edition(name, files),
                    "source_suivi": s.get("source", ""), "lien_source": s.get("lien", ""), "volumes_edition": _volumes_edition(name) or "",
                    "univers": u["univers"], "ordre_univers": u["ordre_univers"], "membres_univers": membres, **_note_de(name)})


@app.route("/api/tome")
def api_tome():
    """Bouton ⓘ d'un tome : titre, sortie en France, personnages en couverture, résumé, chapitres (Wikipédia)."""
    name = request.args.get("id", "")
    if name not in _scan():
        return jsonify({"error": "Série introuvable"}), 404
    try:
        tome = float(request.args.get("tome", "0"))
    except (TypeError, ValueError):
        return jsonify({"error": "Tome inconnu"}), 400
    hs = _entree_hs(name, tome) if _est_numero_hs(tome) else None
    if _est_numero_hs(tome) and not hs:
        return jsonify({"error": "Hors-série introuvable"}), 404
    d = tomes.details_tome(name, tome) if not hs else {"titre": hs["title"], "hors_serie": True, "infos_hs": hs.get("sous", "")}
    differente = _edition_differente(name) and not hs    # Deluxe, Perfect… : le tome 1 n'est pas le tome 1 de Wikipédia
    if differente:
        d = {k: v for k, v in d.items() if k == "couverture"}
        d["edition_differente"] = True
    import edition
    prov = provenance.lire(edition.lire(MANGA_DIR / name)).get(str(int(tome))) or {}
    if not prov:                                         # pas encore notée : d'après le nom du fichier du tome
        nom_fichier = next((Path(e["path"]).name for e in _entrees(_scan().get(name) or []) if int(tome) in (e.get("tome"), e.get("hs"))), "")
        if provenance.equipe_du_nom(nom_fichier):
            prov = {"equipe": provenance.equipe_du_nom(nom_fichier), "origine": f"Nom du fichier : {nom_fichier}", "manuel": False}
    import signets
    fic = _fichier_du_tome(name, int(tome))
    du_fichier = signets.lire_infos(MANGA_DIR / fic) if fic else {}
    nf = du_fichier.get("notes") or {}
    if not prov and (nf.get("equipe") or nf.get("origine")):     # série reçue sans ses infos : la provenance est dans le fichier
        prov = {"equipe": nf.get("equipe", ""), "origine": nf.get("origine", ""), "manuel": bool(nf.get("provenance_manuelle"))}
    d["provenance"] = prov
    d["source_tome"] = (edition.lire(MANGA_DIR / name).get("sources_tomes") or {}).get(str(int(tome)), "")
    isbn_infos = edition.lire(MANGA_DIR / name)
    d["isbn"] = _isbn_connus(isbn_infos, google=False).get(str(int(tome))) or du_fichier.get("isbn", "")   # puis celui écrit dans le fichier
    if d["isbn"]:
        d["isbn_source"] = "saisi à la main ou lu dans le tome"
    else:
        import notices
        web = notices.isbn_details(name, tome)             # en dernier : Internet (Wikipédia, BnF, Google Books : l'accord de deux sources compte)
        if web:
            d["isbn"], d["isbn_source"] = web["isbn"], " + ".join(web["sources"])
            if web["autres"]:
                d["isbn_autres"] = web["autres"]               # une réimpression, une autre édition ou une erreur d'une des sources
        elif isbn_infos.get("isbn_google", {}).get(str(int(tome))):
            d["isbn"], d["isbn_source"] = isbn_infos["isbn_google"][str(int(tome))], "Google Books"
    d["ecriture_possible"] = bool(_tome_complet(name, int(tome))) and not fic.lower().endswith(".cbr") and tomes_cbz.lire_info(MANGA_DIR / fic) is None
    perso = (edition.lire(MANGA_DIR / name).get("resumes_tomes") or {}).get(str(int(tome)))
    if perso:                                            # résumé écrit à la main : prioritaire sur Internet
        d["resume"], d["resume_source"], d["resume_manuel"] = perso, "écrit à la main", True
    if du_fichier.get("resume") and not d.get("resume_manuel") and nf.get("resume") == "manuel":
        d["resume"], d["resume_source"], d["resume_manuel"] = du_fichier["resume"], "écrit dans le fichier", True
    if not d.get("resume") and hs and hs.get("descriptif"):       # hors-série identifié : son petit descriptif
        d["resume"], d["resume_source"] = hs["descriptif"], "fiche du hors-série"
    if not d.get("resume") and not differente and not hs:  # Wikipédia n'a pas de résumé de ce tome : la BnF, puis Google Books
        import notices
        try:
            d["resume"], libelle = notices.resume_du_tome(name, tome)
            if d["resume"]:
                d["resume_source"] = libelle
        except Exception as e:
            logger.info("Résumé du tome %s de %s : %s", tome, name, e.__class__.__name__)
            d["resume"] = ""
        if not d["resume"] and not ((tomes._charger(name) or {}).get("recherches") or {}).get("notices"):
            d["en_preparation"] = True                        # pas encore cherché : la préparation s'en charge, devant les autres
            prechauffage.demander([name], devant=True)
    if not d.get("resume") and du_fichier.get("resume"):          # rien sur Internet : celui écrit dans le fichier du tome
        propre = tomes.resume_propre_du_fichier(name, tome, du_fichier["resume"], _resumes_des_fichiers(name, int(tome)))
        if propre:                                       # la présentation générale de la série, la même partout, ne sert à rien ici
            d["resume"], d["resume_source"] = propre, "écrit dans le fichier"
    _sommaire_du_tome(name, int(tome), d)
    if d.get("chapitres_langue") == "en" or not d.get("chapitres"):      # Wikipédia FR n'a rien : titres FR du tome local avant l'anglais
        groupe = tomes_cbz.dossier_tome(int(tome))
        locaux = [f"{e['num']:g}. {e['titre_ch']}" for e in _entrees(_scan().get(name) or [])
                  if e.get("groupe") == groupe and e.get("titre_ch")]
        if locaux:
            d["chapitres"], d["chapitres_langue"] = locaux[:60], ""
    return jsonify(d)


def _tome_complet(name, tome):
    """Entrée du fichier « tome complet » (un fichier = un tome, pas un fichier de tome fait par l'appli), ou None."""
    for e in _entrees(_scan().get(name) or []):
        if tome in (e.get("tome"), e.get("hs")) and e.get("key") == e.get("path") and not e.get("a_importer"):
            return e
    return None


def _numeros_manquants(nums):
    """Numéros entiers absents de la suite des chapitres d'un tome (55, 56, 57, 60 → [58, 59]) : le sommaire a été mal
    lu ou la liste a perdu des chapitres. Seulement les trous d'au plus 5 chapitres (au-delà : autre découpage)."""
    entiers = sorted({int(n) for n in nums if n is not None and float(n) == int(n)})
    trous = []
    for a, b in zip(entiers, entiers[1:]):
        if 1 < b - a <= 6:
            trous += range(a + 1, b)
    return trous


_RESUMES_FICHIERS = {}


def _resumes_des_fichiers(name, sauf):
    """{tome: résumé écrit dans le fichier} des autres tomes complets de la série (lu une fois par fichier, gardé en mémoire)."""
    import signets
    out = {}
    for t in _tomes_de(name):
        if int(t) == sauf:
            continue
        e = _tome_complet(name, int(t))
        if not e:
            continue
        chemin = MANGA_DIR / e["path"]
        try:
            cle = (str(chemin), chemin.stat().st_mtime_ns)
        except OSError:
            continue
        if cle not in _RESUMES_FICHIERS:
            if len(_RESUMES_FICHIERS) > 3000:
                _RESUMES_FICHIERS.clear()
            try:
                _RESUMES_FICHIERS[cle] = (signets.lire_infos(chemin) or {}).get("resume") or ""
            except Exception:
                _RESUMES_FICHIERS[cle] = ""
        if _RESUMES_FICHIERS[cle]:
            out[t] = _RESUMES_FICHIERS[cle]
    return out


def _sommaire_du_tome(name, tome, d, fond=False):
    """Chapitres lus dans le sommaire imprimé du tome (OCR). Pas encore lu : lecture lancée toute seule en arrière-plan
    quand aucune source n'a les chapitres en français."""
    import sommaire
    import edition
    lu = (edition.lire(MANGA_DIR / name).get("sommaires") or {}).get(str(tome))
    e = _tome_complet(name, tome)
    if not lu and e:                                     # chapitres déjà écrits dans le fichier (série reçue d'un partage)
        import signets
        notes = signets.lire(MANGA_DIR / e["path"])
        if notes:
            lu = {"chapitres": notes, "fichier": True}
    differente = _edition_differente(name)               # autre édition que celle de Wikipédia : ses chapitres par tome ne valent pas
    if differente and not lu:
        d["chapitres"], d["chapitres_langue"] = [], ""
    sans_titres = bool(d.get("chapitres")) and sum(                 # liste de numéros seuls (« 3. 3 », « 4. 0 ») : pas de titre à garder
        1 for c in d["chapitres"] if re.search(r"[^\W\d_]{3,}", re.sub(r"^\d+(?:[.,]\d)?\.?\s*", "", c))) < len(d["chapitres"]) / 2
    besoin = not d.get("chapitres") or d.get("chapitres_langue") == "en" or differente or sans_titres
    if lu and lu.get("chapitres") and (besoin or lu.get("manuel")):
        d["chapitres"] = [f"{c['num']:g}. {c['titre']}" if c.get("titre") else f"{c['num']:g}." for c in lu["chapitres"]]
        d["chapitres_langue"], d["chapitres_source"] = "", "validés à la main" if lu.get("valide_le") else "saisis à la main" if lu.get("manuel") else "écrits dans le fichier" if lu.get("fichier") else "pages d'ouverture des chapitres, lues automatiquement" if lu.get("source") == "pages d'ouverture" else "sommaire du tome, lu automatiquement"
        if e:
            d["chapitres_pages"] = [c.get("image") for c in lu["chapitres"]]
            d["fichier"] = e["key"]
    elif lu and lu.get("chapitres") and e and d.get("chapitres") and d.get("chapitres_langue") != "en":
        # Wikipédia donne déjà des titres : ceux du sommaire du tome (son édition) les remplacent, et les chapitres
        # sont reliés à leur page de lecture ; Wikipédia ne sert que pour un chapitre absent du sommaire.
        par_num = {float(c["num"]): c for c in lu["chapitres"] if c.get("num") is not None}
        titres, pages, ok = [], [], 0
        for ligne in d["chapitres"]:
            m = re.match(r"^(\d+(?:[.,]\d)?)\.?\s*(.*)$", ligne)
            c = par_num.get(float(m.group(1).replace(",", "."))) if m else None
            if c is not None:
                ok += 1
                ocr = (c.get("titre") or "").strip()
                generique = bool(re.fullmatch(r"[^\W\d_]{1,15}\s*[:.\-–—]?\s*\d+(?:[.,]\d)?", ocr))   # « Kill 5 » : un mot et un numéro, pas un titre
                if len(ocr) >= 3 and not (generique and m.group(2).strip()):      # le sommaire imprimé de SON édition fait foi
                    ligne = f"{m.group(1)}. {ocr}"
            titres.append(ligne)
            pages.append(c.get("image") if c is not None else None)
        if ok:
            d["chapitres"], d["chapitres_pages"], d["fichier"] = titres, pages, e["key"]
    # lu par une version plus ancienne du lecteur : relu, sauf si tu y as touché (saisie en cours ou tome validé)
    ancien = _lecture_perimee(lu, name, tome)
    # liste venue d'Internet avec des titres mais sans pages : le sommaire imprimé sert à relever les numéros de page
    if e and sommaire.disponible() and (not lu or ancien) and (besoin or ancien or d.get("chapitres")) and auth.role() != "lecteur":
        _lire_sommaire(name, tome, e, urgent=not fond)
    et = sommaire.etat(name, tome)
    d["sommaire"] = {"possible": bool(e) and sommaire.disponible(), "en_cours": bool(et.get("en_cours")),
                     "message": et.get("message", ""), "secondes": et.get("secondes", 0), "pages": et.get("pages", 0),
                     "attente": str(et.get("message", "")).startswith("En attente"), "fond": _avancement_fond(name), "lu": bool(lu), "manuel": bool(lu and lu.get("manuel")),
                     "valide_le": (lu or {}).get("valide_le", ""), "saisie": bool(lu and lu.get("saisie")), "fichier": bool(lu and lu.get("fichier")),
                     "manquants": _numeros_manquants([c.get("num") for c in (lu or {}).get("chapitres", [])])}


def _numeros_fiables(name, tome) -> list:
    """Numéros des chapitres que ce tome devrait contenir d'après Internet (Wikipédia, fiche), seulement s'ils valent pour NOTRE
    édition. Édition spéciale reconnue par l'appli (Perfect, deluxe, intégrale… : autre nombre de tomes que l'édition standard) :
    la répartition d'Internet est celle de l'édition standard et ne vaut pas ; on se fie alors à la seule lecture des tomes
    eux-mêmes (liste vide : les numéros sont ceux imprimés dans le tome)."""
    try:
        if _edition_differente(name):
            return []
        return tomes.numeros_du_tome(name, tome)
    except Exception:
        return []


def _suite_de(name, tome):
    """Dernier chapitre lu du tome précédent (ou None) : le tome suivant reprend juste après."""
    import edition
    prec = (((edition.lire(MANGA_DIR / name).get("sommaires") or {}).get(str(int(tome) - 1))) or {}).get("chapitres") or []
    nums = [float(c["num"]) for c in prec if c.get("num") is not None]
    return max(nums) if nums else None


def _lecture_perimee(lu, name, tome) -> bool:
    """Lecture automatique faite par une version plus ancienne du lecteur et restée incomplète : à relire. Jamais une lecture saisie
    ou validée à la main, ni des chapitres écrits dans le fichier."""
    import sommaire
    return bool(lu and not lu.get("fichier") and lu.get("version", 1) < sommaire.VERSION
                and not (lu.get("saisie") or lu.get("manuel") or lu.get("valide_le")) and _a_relire(lu, name, tome))


def _relire_sommaires_perimes(nom) -> int:
    """Tomes de la série dont la lecture est périmée (voir _lecture_perimee) : relus en fond, un tome par cœur libre, sans rien
    demander à Internet. Rend le nombre de tomes relus."""
    import sommaire
    import edition
    lus = edition.lire(MANGA_DIR / nom).get("sommaires") or {}
    a_faire = [t for t in sorted(_tomes_de(nom)) if _lecture_perimee(lus.get(str(t)), nom, t)]
    en_lecture = []
    for t in a_faire:
        e = _tome_complet(nom, t)
        if not e:
            continue
        _lire_sommaire(nom, t, e, urgent=False)
        if sommaire.etat(nom, t).get("en_cours"):
            en_lecture.append(t)
        _attendre_lectures(sommaire, nom, en_lecture, sommaire.SIMULTANES - 1)
    _attendre_lectures(sommaire, nom, en_lecture, 0)
    return len(a_faire)


def _boucle_relecture_sommaires():
    """30 minutes après le démarrage, puis toutes les 6 heures : les sommaires lus par un lecteur plus ancien et restés incomplets
    (rien trouvé, pages estimées, chapitres manquants) sont relus avec le lecteur actuel, série par série, quand l'appli n'a rien
    d'autre à faire (ni préparation de fond, ni import, ni téléchargement). Une lecture complète n'est jamais relue."""
    try:
        os.nice(10)                  # discret, comme la préparation de fond : les lectures lancées d'ici héritent de la priorité basse
    except (OSError, AttributeError):
        pass
    time.sleep(1800)
    while True:
        total = 0
        try:
            for nom in sorted(_scan()):
                if nom == "(Sans série)":
                    continue
                while _travaux_en_cours() or prechauffage._ETAT.get("en_cours"):
                    time.sleep(60)
                n = _relire_sommaires_perimes(nom)
                if n:
                    logger.info("Sommaires de « %s » : %d tome(s) relu(s) par le lecteur version %d", nom, n, __import__("sommaire").VERSION)
                total += n
            if total:
                logger.info("Relecture des sommaires périmés terminée : %d tome(s)", total)
        except Exception as e:
            logger.warning("Relecture des sommaires périmés : %s", e)
        time.sleep(6 * 3600)


def _a_relire(lu, name, tome) -> bool:
    """Lecture automatique qui mérite d'être refaite par un lecteur plus récent : rien trouvé, des pages estimées ou sans image,
    ou moins de chapitres que le tome n'en contient. Une lecture complète et sûre n'est jamais relue (ça coûtait des heures pour rien)."""
    ch = (lu or {}).get("chapitres") or []
    if not ch or any(c.get("estimee") or c.get("image") is None for c in ch):
        return True
    numeros = _numeros_fiables(name, tome)
    return bool(numeros) and len(ch) < len(numeros)


def _richesse(lecture):
    """Ce qu'une lecture de sommaire apporte : chapitres, titres lus, pages de lecture trouvées (pour ne jamais remplacer
    une lecture par une plus pauvre)."""
    ch = lecture.get("chapitres") or []
    titres = sum(1 for c in ch if (c.get("titre") or "").strip())
    pages = sum(1 for c in ch if c.get("image") is not None)          # une page de lecture trouvée vaut plus qu'un titre
    return (titres + 2 * pages, len(ch))


def _avancement_fond(name):
    """Où en est la préparation en arrière-plan pour cette série : texte court, ou '' si elle n'est ni en cours ni en file."""
    with prechauffage._VERROU:
        if prechauffage._ETAT["serie"] == name:
            return "Préparation de cette série en cours : " + (prechauffage._ETAT["detail"] or "démarrage…")
        if name in prechauffage._FILE:
            return f"Cette série attend son tour dans la préparation de fond (n° {prechauffage._FILE.index(name) + 1} sur {len(prechauffage._FILE)})."
    return ""


def _lire_sommaire(name, tome, e, forcer=False, urgent=True):
    """forcer : relecture demandée par la personne (bouton) ; sinon une liste saisie à la main n'est jamais remplacée."""
    import sommaire
    import edition
    chemin = MANGA_DIR / e["path"]

    def enregistrer(r):
        with _VERROU_SOMMAIRES:                          # plusieurs tomes lus en même temps : une écriture à la fois
            _enregistrer(r)

    def _enregistrer(r):
        infos = edition.lire(MANGA_DIR / name)
        if any(c.get("relatif") for c in r.get("chapitres", [])):             # leçons comptées depuis 1 dans chaque tome
            prec = ((infos.get("sommaires") or {}).get(str(int(tome) - 1)) or {}).get("chapitres") or []
            reguliers = [c["num"] for c in prec if c.get("num") is not None and float(c["num"]) == int(c["num"])]
            decal = int(max(reguliers)) if reguliers and int(tome) > 1 else 0
            for c in r["chapitres"]:
                c["num"] = round(c["num"] + decal, 1)
                c.pop("relatif", None)
        if r.get("isbn") and not (infos.get("isbn") or {}).get(str(tome)):        # ISBN imprimé dans le tome : gardé comme info
            infos.setdefault("isbn", {})[str(tome)] = r["isbn"]
        avant = (infos.get("sommaires") or {}).get(str(tome)) or {}
        if (avant.get("saisie") or avant.get("manuel") or avant.get("valide_le")) and avant.get("chapitres") and not forcer:
            return                                       # tome validé ou saisi à la main : intouchable sans demande explicite
        if avant.get("source") == "pages d'équipe" and avant.get("chapitres") and not r.get("chapitres"):
            # rien de lisible dans le tome : les chapitres déduits restent, mais marqués relus par cette version (sinon chaque
            # ouverture de la fiche relançait plusieurs minutes de lecture)
            infos.setdefault("sommaires", {})[str(tome)] = dict(avant, version=r["version"])
            edition.ecrire(MANGA_DIR / name, infos)
            return
        if not forcer and avant.get("chapitres") and _richesse(avant) > _richesse(r):
            # relecture automatique moins bonne que ce qu'on avait (moins de titres, de pages de lecture) : on garde l'ancienne
            logger.info("Sommaire de « %s » tome %s : la nouvelle lecture est moins complète, l'ancienne est gardée", name, tome)
            r = dict(avant, version=r["version"])
        if avant.get("manuel") or avant.get("valide_le"):
            # fiche déjà validée avec des titres d'avant (souvent ceux de Wikipédia) : relue une fois avec le lecteur
            # amélioré ; les titres du sommaire imprimé la remplacent si ce sont les mêmes chapitres, sinon on la garde
            if [c.get("num") for c in r.get("chapitres", [])] == [c.get("num") for c in avant.get("chapitres", [])] and r.get("chapitres"):
                r["manuel"], r["valide_le"] = avant.get("manuel", False), avant.get("valide_le", "")
            else:
                r = dict(avant, version=r["version"])
        appris = int(infos.get("decalage_chapitres") or 0)
        if appris and _lecture_automatique(r) and not r.get("decalage_appris"):
            _decaler_lecture(r, appris)                  # décalage appris de tes vérifications de cette série (voir _decalage_de_serie)
        infos.setdefault("sommaires", {})[str(tome)] = r
        edition.ecrire(MANGA_DIR / name, infos)
    numeros = _numeros_fiables(name, tome)               # chapitres du tome d'après Internet, s'ils valent pour cette édition
    try:
        suite = _suite_de(name, tome)
    except Exception:
        suite = None
    return sommaire.lancer(name, tome, chemin, lambda i: archives.read_page(chemin, i)[0], len(archives.pages(chemin)), enregistrer,
                         noms=archives.pages(chemin), numeros=numeros, urgent=urgent, suite_de=suite)


@app.route("/api/tome/sommaire", methods=["POST"])
def api_tome_sommaire():
    """Bouton « 🔍 Lire le sommaire » d'un tome : relit ses premières pages (OCR), même s'il a déjà été lu."""
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    try:
        tome = int(float(body.get("tome")))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Tome inconnu"}), 400
    import sommaire
    if name not in _scan():
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    if not sommaire.disponible():
        return jsonify({"ok": False, "error": "Lecteur de texte (tesseract) absent du serveur"}), 400
    e = _tome_complet(name, tome)
    if not e:
        return jsonify({"ok": False, "error": "Ce tome n'est pas un fichier de tome complet (ses chapitres sont déjà séparés)."}), 400
    import edition
    deja = (edition.lire(MANGA_DIR / name).get("sommaires") or {}).get(str(tome)) or {}
    if deja.get("manuel") and not body.get("force"):
        return jsonify({"ok": False, "error": "Les chapitres de ce tome ont été corrigés à la main : confirme pour les remplacer."}), 409
    _lire_sommaire(name, tome, e, forcer=True)
    return jsonify({"ok": True, "message": "Lecture du sommaire en cours (environ une minute)…"})


def _titres_officiels(name):
    """{numéro entier de chapitre: titre français} d'après la fiche de la série (Wikipédia français, liste des volumes)."""
    out = {}
    details = (((tomes._charger(name) or {}).get("titres_tomes") or {}).get("details")) or {}
    for det in details.values():
        for ligne in det.get("chapitres") or []:
            m = re.match(r"^(\d+)\.\s*(\S.*)$", ligne)
            if m:
                out.setdefault(int(m.group(1)), m.group(2).strip())
    return out


@app.route("/api/titres-chapitres", methods=["GET", "POST"])
@_sous_verrou_infos
def api_titres_chapitres():
    """🏷 Titres des chapitres sur le modèle régulier de la série (« Trick 12 »). GET : aperçu seul.
    POST {series, confirmer: true} : écrit les titres proposés dans les infos du tome (rien n'est touché sans confirmation)."""
    import edition
    import titres_chapitres
    donnees = request.get_json(silent=True) or {} if request.method == "POST" else request.args
    name = str(donnees.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    dossier = MANGA_DIR / name
    infos = edition.lire(dossier)
    sommaires = infos.get("sommaires") or {}
    if request.method == "GET":
        return jsonify({"ok": True, **titres_chapitres.proposer(sommaires, str(donnees.get("prefixe", "")), _titres_officiels(name), bool(donnees.get("retirer")))})
    if not donnees.get("confirmer"):
        return jsonify({"ok": False, "error": "Confirme l'écriture pour appliquer les titres."}), 400
    ecrits = titres_chapitres.appliquer(sommaires, titres_chapitres.proposer(sommaires, str(donnees.get("prefixe", "")), _titres_officiels(name), bool(donnees.get("retirer")))["changements"])
    infos["sommaires"] = sommaires
    edition.ecrire(dossier, infos)
    logger.info("Titres des chapitres de « %s » : %d écrit(s)", name, ecrits)
    return jsonify({"ok": True, "ecrits": ecrits})


@app.route("/api/tome/chapitres", methods=["POST"])
@_sous_verrou_infos
def api_tome_chapitres():
    """Correction à la main de la liste des chapitres d'un tome : une ligne « 2. La valeur de la vie » par chapitre.
    La page de chaque chapitre (lien de lecture) est gardée quand son numéro existait déjà. Remplace la lecture automatique."""
    import edition
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    try:
        tome = int(float(body.get("tome", "")))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Tome inconnu"}), 400
    infos = edition.lire(MANGA_DIR / name)
    ancien = (infos.get("sommaires") or {}).get(str(tome)) or {}
    pages = {float(c["num"]): c for c in ancien.get("chapitres", []) if c.get("num") is not None}
    chapitres, vus = [], set()
    for i, ligne in enumerate(str(body.get("texte", "")).splitlines(), 1):
        ligne = ligne.strip()
        if not ligne:
            continue
        ligne = re.sub(r"\s*@\s*$", "", ligne)                            # « @ » laissé vide : page non précisée
        page_lecteur = re.search(r"\s*@\s*(\d{1,5})\s*$", ligne)          # « @64 » : page affichée par le lecteur où commence le chapitre
        if page_lecteur:
            ligne = ligne[:page_lecteur.start()].strip()
        m = re.match(r"^(\d{1,4}(?:[.,]\d)?)\s*[.)\-:–]*\s*(.*)$", ligne)
        if m:
            texte_num, texte_titre = m.group(1), m.group(2)
        else:                                                             # « Kill 12 : La nuit » : le numéro est dans le mot du début
            mm = re.match(r"^[^\W\d_]{1,15}\s*[:.\-–—]?\s*0*(\d{1,4}(?:[.,]\d)?)\b", ligne)
            if not mm:
                return jsonify({"ok": False, "error": f"Ligne {i} : elle doit commencer par le numéro du chapitre (ex. « 2. La valeur de la vie » ou « Kill 2 : La valeur de la vie »)."}), 400
            texte_num, texte_titre = mm.group(1), ligne                   # le titre garde son mot devant le numéro
        num = float(texte_num.replace(",", "."))
        if num in vus:
            return jsonify({"ok": False, "error": f"Ligne {i} : le chapitre {num:g} est écrit deux fois."}), 400
        vus.add(num)
        titre = re.sub(r"\s+", " ", texte_titre).strip()[:120]
        c = {"num": num, "titre": titre}
        if num in pages:
            c.update({k: pages[num][k] for k in ("page", "image") if k in pages[num]})
        if page_lecteur:
            c["image"] = max(0, int(page_lecteur.group(1)) - 1)             # position dans le fichier (0 = première page)
        chapitres.append(c)
    if not chapitres:
        return jsonify({"ok": False, "error": "Aucun chapitre : ajoute au moins une ligne."}), 400
    chapitres.sort(key=lambda c: c["num"])
    nouveau = dict(ancien)
    nouveau.update(chapitres=chapitres, manuel=True, saisie=True)
    nouveau.pop("valide_le", None)                       # enregistré, pas validé : le bouton ✅ Valider verrouille le tome
    infos.setdefault("sommaires", {})[str(tome)] = nouveau
    edition.ecrire(MANGA_DIR / name, infos)
    try:
        _apprendre_chiffres(name, tome)
    except Exception as e:
        logger.info("Chiffres du sommaire de %s : %s", name, e.__class__.__name__)
    return jsonify({"ok": True, "message": f"{_nom_tome(name, tome)} : {len(chapitres)} chapitres enregistrés (pas encore validés)."})


def _apprendre_chiffres(name, tome):
    """Après une correction ou une validation à la main : les chiffres de la police des numéros de page du sommaire
    sont appris (positions des chapitres que tu as confirmées), pour que les prochains tomes soient lus justes."""
    import edition
    import sommaire
    from PIL import Image
    infos = edition.lire(MANGA_DIR / name)
    rec = (infos.get("sommaires") or {}).get(str(tome)) or {}
    e = _tome_complet(name, int(tome))
    ch = rec.get("chapitres") or []
    if not e or rec.get("page_sommaire") is None or len(ch) < 3:
        return 0
    chemin = MANGA_DIR / e["path"]
    octets = archives.read_page(chemin, int(rec["page_sommaire"]))[0]
    boites = []
    lues = sommaire.analyser_rangees_titrees(octets, None, boites)
    if not lues or len(boites) != len(lues):
        return 0
    par_num = {float(c["num"]): c for c in ch if c.get("num") is not None}
    # on n'apprend que les nombres sur lesquels la page imprimée et la position confirmée par toi s'accordent
    valeurs = []
    for x, boite in zip(lues, boites):
        c = par_num.get(float(x["num"]))
        if c and c.get("page") is not None and c.get("image") is not None and int(c["page"]) == int(c["image"]):
            valeurs.append((boite, int(c["page"])))
    if not valeurs:
        return 0
    return sommaire.apprendre_chiffres(name, Image.open(io.BytesIO(octets)).convert("RGB"), valeurs)


@app.route("/api/tome/valider", methods=["POST"])
@_sous_verrou_infos
def api_tome_valider():
    """✅ Valider : la liste des chapitres et leurs pages sont complètes et justes (lue automatiquement ou saisie à la
    main). Le tome est verrouillé : plus jamais relu ni modifié automatiquement, plus signalé « à vérifier »."""
    import edition
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    try:
        tome = int(float(body.get("tome", "")))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Tome inconnu"}), 400
    infos = edition.lire(MANGA_DIR / name)
    lu = (infos.get("sommaires") or {}).get(str(tome))
    if not lu or not lu.get("chapitres"):
        return jsonify({"ok": False, "error": "Pas de chapitres lus pour ce tome : lis le sommaire d'abord."}), 400
    lu.update(manuel=True, valide_le=time.strftime("%Y-%m-%d"))
    edition.ecrire(MANGA_DIR / name, infos)
    try:
        _apprendre_chiffres(name, tome)
    except Exception as e:
        logger.info("Chiffres du sommaire de %s : %s", name, e.__class__.__name__)
    return jsonify({"ok": True, "message": f"{_nom_tome(name, tome)} : chapitres validés, l'appli n'y touchera plus."})


# ---------------- 📖 Chapitres d'un tome complet dans le lecteur, et 🎯 vérification des pages au lecteur ----------------

def _chapitres_pour_lecteur(name, tome, lu):
    """[{num, titre, image, verifie}] d'un tome complet, dans l'ordre des chapitres. Titre : celui du sommaire, sinon celui de
    Wikipédia pour ce tome (si la fiche vaut pour cette édition)."""
    wiki = {}
    if not _edition_differente(name):
        det = ((((tomes._charger(name) or {}).get("titres_tomes") or {}).get("details") or {}).get(str(int(tome))) or {})
        for ligne in det.get("chapitres") or []:
            m = re.match(r"^(\d+(?:[.,]\d)?)\.?\s*(.*)$", str(ligne))
            if m and m.group(2).strip():
                wiki[float(m.group(1).replace(",", "."))] = m.group(2).strip()
    out = []
    for c in (lu or {}).get("chapitres") or []:
        if c.get("num") is None:
            continue
        out.append({"num": c["num"], "titre": (c.get("titre") or "").strip() or wiki.get(float(c["num"]), ""),
                    "image": c.get("image"), "verifie": bool(c.get("verifie"))})
    return out


@app.route("/api/lecteur/chapitres")
def api_lecteur_chapitres():
    """Chapitres d'un tome complet (un fichier = un tome) pour le lecteur : sauter d'un chapitre à l'autre, liste ☰, titre du
    chapitre en cours. Rien n'est lancé ni écrit."""
    import edition
    name = request.args.get("s", "")
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"error": "Série introuvable"}), 404
    try:
        tome = int(float(request.args.get("tome", "")))
    except (TypeError, ValueError):
        return jsonify({"error": "Tome inconnu"}), 400
    lu = (edition.lire(MANGA_DIR / name).get("sommaires") or {}).get(str(tome)) or {}
    return jsonify({"chapitres": _chapitres_pour_lecteur(name, tome, lu), "valide": bool(lu.get("valide_le")),
                    "saisie": bool(lu.get("saisie"))})


def _garder_places_auto(lu):
    """Première correction à la main d'un tome lu automatiquement : la place trouvée par l'appli est gardée à côté de chaque
    chapitre (« auto_image »), pour apprendre de tes corrections le décalage propre à la série (voir _decalage_de_serie)."""
    if lu.get("saisie") or lu.get("manuel") or lu.get("valide_le") or lu.get("fichier"):
        return
    for c in lu.get("chapitres") or []:
        if c.get("image") is not None:
            c.setdefault("auto_image", c["image"])


def _decalage_de_serie(infos) -> int:
    """Décalage que tes vérifications au lecteur montrent pour la série : la page trouvée par l'appli est celle du titre, le
    chapitre commence 1 ou 2 pages avant (ou après). Appris s'il y a au moins 5 chapitres vérifiés et que 70 % d'entre eux ont
    le même écart (non nul, de 3 pages au plus) ; 0 sinon."""
    from collections import Counter
    ecarts = [c["image"] - c["auto_image"] for lu in (infos.get("sommaires") or {}).values() for c in lu.get("chapitres") or []
              if c.get("verifie") and c.get("auto_image") is not None and c.get("image") is not None]
    if len(ecarts) < 5:
        return 0
    d, n = Counter(ecarts).most_common(1)[0]
    return d if d != 0 and abs(d) <= 3 and n >= 0.7 * len(ecarts) else 0


def _lecture_automatique(lu) -> bool:
    return bool(lu and lu.get("chapitres")) and not (lu.get("saisie") or lu.get("manuel") or lu.get("valide_le") or lu.get("fichier")) \
        and lu.get("source") != "noms des images"


def _decaler_lecture(lu, d):
    """Applique à une lecture automatique le décalage appris d (en tenant compte de celui déjà appliqué)."""
    deja = int(lu.get("decalage_appris") or 0)
    if d == deja:
        return False
    for c in lu.get("chapitres") or []:
        if c.get("image") is not None:
            c["image"] = max(0, c["image"] + d - deja)
    lu["decalage_appris"] = d
    return True


def _appliquer_decalage_appris(name, infos) -> tuple:
    """Décalage appris de la série appliqué aux tomes lus automatiquement (jamais à un tome saisi ou validé à la main).
    Rend (décalage, nombre de tomes recalés). infos est modifié ; à écrire par l'appelant."""
    d = _decalage_de_serie(infos)
    if d != int(infos.get("decalage_chapitres") or 0):
        infos["decalage_chapitres"] = d
    n = sum(1 for lu in (infos.get("sommaires") or {}).values() if _lecture_automatique(lu) and _decaler_lecture(lu, d))
    return d, n


def _tome_pour_verif(name, tome):
    import edition
    infos = edition.lire(MANGA_DIR / name)
    lu = (infos.get("sommaires") or {}).get(str(tome))
    e = _tome_complet(name, tome)
    return infos, lu, (len(archives.pages(MANGA_DIR / e["path"])) if e else None)


@app.route("/api/tome/chapitre_page", methods=["POST"])
@_sous_verrou_infos
def api_tome_chapitre_page():
    """🎯 Vérification au lecteur, un chapitre à la fois : {series, tome, num, image?}. Avec image : le chapitre commence à cette
    page (position dans le fichier) ; sans : la page enregistrée est la bonne. Enregistré tout de suite (« saisi, pas encore
    validé ») : rien n'est perdu si tu t'arrêtes au milieu."""
    import edition
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    try:
        tome, num = int(float(body.get("tome", ""))), float(body.get("num", ""))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Tome ou chapitre inconnu"}), 400
    infos, lu, nb = _tome_pour_verif(name, tome)
    c = next((x for x in (lu or {}).get("chapitres") or [] if x.get("num") is not None and float(x["num"]) == num), None)
    if c is None:
        return jsonify({"ok": False, "error": "Chapitre inconnu dans ce tome."}), 400
    _garder_places_auto(lu)
    if body.get("image") is not None:
        try:
            image = int(body["image"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Page invalide"}), 400
        if image < 0 or (nb and image >= nb):
            return jsonify({"ok": False, "error": "Cette page n'existe pas dans le tome."}), 400
        c["image"] = image
    elif c.get("image") is None:
        return jsonify({"ok": False, "error": "Ce chapitre n'a pas encore de page : place-toi sur sa première page."}), 400
    c["verifie"] = True
    c.pop("estimee", None)
    lu.update(manuel=True, saisie=True)
    lu.pop("valide_le", None)
    d, n = _appliquer_decalage_appris(name, infos)
    edition.ecrire(MANGA_DIR / name, infos)
    return jsonify({"ok": True, "chapitres": _chapitres_pour_lecteur(name, tome, lu), "decalage": d, "tomes_recales": n})


@app.route("/api/tome/chapitres_decaler", methods=["POST"])
@_sous_verrou_infos
def api_tome_chapitres_decaler():
    """🎯 Vérification au lecteur : {series, tome, apres, decalage} : les chapitres pas encore vérifiés après le chapitre « apres »
    sont décalés d'autant de pages (le même écart revient souvent dans tout un tome)."""
    import edition
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    try:
        tome, apres, delta = int(float(body.get("tome", ""))), float(body.get("apres", "")), int(body.get("decalage", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Données invalides"}), 400
    if not delta or abs(delta) > 20:
        return jsonify({"ok": False, "error": "Décalage invalide"}), 400
    infos, lu, nb = _tome_pour_verif(name, tome)
    if not lu or not lu.get("chapitres"):
        return jsonify({"ok": False, "error": "Pas de chapitres pour ce tome."}), 400
    _garder_places_auto(lu)
    n = 0
    for c in lu["chapitres"]:
        if c.get("num") is not None and float(c["num"]) > apres and not c.get("verifie") and c.get("image") is not None:
            c["image"] = max(0, min((nb or 10 ** 6) - 1, c["image"] + delta))
            n += 1
    lu.update(manuel=True, saisie=True)
    lu.pop("valide_le", None)
    edition.ecrire(MANGA_DIR / name, infos)
    return jsonify({"ok": True, "decales": n, "chapitres": _chapitres_pour_lecteur(name, tome, lu)})


_SIGNETS = {}              # (série, tome) → {"en_cours", "message", "ok"} : écriture des chapitres dans le .cbz


def _ecrire_fichier_tome(name, tome, chemin, chapitres, infos, partage):
    """Écrit chapitres et infos DANS le fichier du tome (fichier partagé : version à part et échange de dossiers)."""
    import optimiser
    import signets
    if partage:
        optimiser.echanger_dossier(chemin, lambda dest: bool(signets.ecrire(chemin, chapitres, dest, infos)), _vers_corbeille)
    else:
        tmp = chemin.with_name("." + chemin.name + ".signets")
        signets.ecrire(chemin, chapitres, tmp, infos)
        ancien = chemin.with_name(chemin.name + ".avant")
        chemin.rename(ancien)
        tmp.rename(chemin)
        _vers_corbeille(ancien)
    tomes_cbz._CACHE.clear()


_ECRITURE_SERIE = {}                                     # série → avancement de « réécrire les infos de tous les tomes »


def _tomes_a_ecrire(name):
    """Tomes complets en .cbz que l'appli peut écrire : (tome, chemin, partage_ok, raison_si_non)."""
    import optimiser
    out = []
    for e in sorted((x for x in _entrees(_scan().get(name) or []) if x.get("tome") is not None and x.get("key") == x.get("path")
                     and not x.get("a_importer")), key=lambda x: x["tome"]):
        chemin = MANGA_DIR / e["path"]
        if e["path"].lower().endswith(".cbr"):
            out.append((e["tome"], chemin, False, "format .cbr"))
        elif tomes_cbz.lire_info(chemin) is not None:
            out.append((e["tome"], chemin, False, "fichier assemblé par MouFlanga (déjà à jour)"))
        elif chemin.stat().st_nlink > 1 and not optimiser._dossier_a_lui(chemin, name):
            out.append((e["tome"], chemin, False, "partagé par qBittorrent, hors d'un dossier de tome : jamais modifié"))
        else:
            out.append((e["tome"], chemin, True, ""))
    return out


@app.route("/api/tomes/infos-ecrire", methods=["GET", "POST"])
def api_tomes_infos_ecrire():
    """Réécrit les infos (résumé, provenance, sommaire, chapitres lus) dans le fichier de CHAQUE tome complet de la série.
    GET : combien de tomes seront réécrits, et l'avancement. POST : lance la réécriture en arrière-plan."""
    import edition
    import signets
    name = str((request.get_json(silent=True) or {}).get("series", "") if request.method == "POST" else request.args.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    cibles = _tomes_a_ecrire(name)
    ok_cibles = [c for c in cibles if c[2]]
    if request.method == "GET":
        st = _ECRITURE_SERIE.get(name) or {}
        return jsonify({"total": len(ok_cibles), "exclus": [{"tome": c[0], "raison": c[3]} for c in cibles if not c[2]],
                        "en_cours": bool(st.get("en_cours")), "fait": st.get("fait", 0), "message": st.get("message", "")})
    if (_ECRITURE_SERIE.get(name) or {}).get("en_cours"):
        return jsonify({"ok": False, "error": "Réécriture déjà en cours pour cette série."}), 409
    if not ok_cibles:
        return jsonify({"ok": False, "error": "Aucun tome à réécrire (il faut des tomes complets en .cbz)."}), 400
    edition_infos = edition.lire(MANGA_DIR / name)
    _ECRITURE_SERIE[name] = {"en_cours": True, "fait": 0, "message": f"Réécriture de {len(ok_cibles)} tome(s)…"}

    def travail():
        erreurs = []
        try:
            for tome, chemin, _, _ in ok_cibles:
                try:
                    lu = (edition_infos.get("sommaires") or {}).get(str(tome)) or {}
                    chapitres = lu.get("chapitres") or []
                    if not signets.nb_signets(chapitres):
                        chapitres = None
                    _ecrire_fichier_tome(name, tome, chemin, chapitres, _infos_tome(name, tome), chemin.stat().st_nlink > 1)
                    _ECRITURE_SERIE[name]["fait"] += 1
                except Exception as ex:
                    logger.warning("Infos écrites dans %s : %s", chemin, ex)
                    erreurs.append(f"tome {tome} : {ex}")
            msg = f"{len(ok_cibles) - len(erreurs)} tome(s) réécrit(s) sur {len(ok_cibles)}." + (" Erreurs : " + " ; ".join(erreurs) if erreurs else "")
        except Exception as ex:
            msg = f"Échec : {ex}"
        _ECRITURE_SERIE[name] = {"en_cours": False, "fait": _ECRITURE_SERIE[name].get("fait", 0), "message": msg, "ok": not erreurs}
    threading.Thread(target=travail, daemon=True).start()
    return jsonify({"ok": True, "message": "Réécriture lancée…"})


_CONVERSION = {}                                       # série → avancement de « convertir les .cbr en .cbz »


def _cbr_de(name):
    """.cbr de la série (et .cbz qui sont en réalité des RAR) : (chemin, convertible, raison_si_non)."""
    import optimiser
    out = []
    for e in _entrees(_scan().get(name) or []):
        p = e.get("path") or ""
        if e.get("key") != p or e.get("a_importer"):
            continue
        chemin = MANGA_DIR / p
        faux_cbz = False                                 # « .cbz » dont le contenu est un vrai RAR : lisible, mais pas modifiable
        if p.lower().endswith((".cbz", ".zip")):
            try:
                faux_cbz = archives._kind(chemin) == "rar"
            except Exception:
                continue
        if not faux_cbz and not p.lower().endswith(".cbr"):
            continue
        try:
            partage = chemin.stat().st_nlink > 1
        except OSError:
            continue
        if not faux_cbz and chemin.with_suffix(".cbz").exists():
            out.append((chemin, False, "un .cbz du même nom existe déjà"))
        elif partage and not optimiser._dossier_a_lui(chemin, name):
            out.append((chemin, False, "partagé par qBittorrent, hors d'un dossier de tome : jamais modifié"))
        else:
            out.append((chemin, True, ""))
    return out


def _convertir_un_cbr(chemin):
    """Remplace un .cbr par son .cbz (mêmes pages, vérifiées). Renvoie le nouveau chemin."""
    import convertir
    import optimiser
    cible = chemin.with_suffix(".cbz")
    if chemin.stat().st_nlink > 1:                       # partagé par qBittorrent : copie à part, dossiers échangés
        optimiser.echanger_dossier(chemin, lambda dest: bool(convertir.vers_cbz(chemin, dest.with_suffix(".cbz"))), _vers_corbeille)
    else:
        tmp = chemin.with_name("." + cible.name + ".conv")
        convertir.vers_cbz(chemin, tmp)
        try:
            _vers_corbeille(chemin)                      # l'ancien d'abord : s'il ne part pas, rien n'est changé
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        tmp.rename(cible)
    return cible


def _convertir_cbr_serie(name, cibles, etat=None):
    """Convertit les .cbr « cibles » [(chemin, ok, raison)] de la série. Renvoie (nombre converti, erreurs)."""
    erreurs, deplaces = [], {}
    for chemin, ok, _ in cibles:
        if not ok:
            continue
        try:
            ancien = _rel(chemin)
            deplaces[ancien] = _rel(_convertir_un_cbr(chemin))
            if etat is not None:
                etat["fait"] = etat.get("fait", 0) + 1
        except Exception as ex:
            logger.warning("Conversion de %s : %s", chemin, ex)
            erreurs.append(f"{chemin.name} : {ex}")
    if deplaces:
        _suivre_renommage(name, name, deplaces)           # la progression de lecture suit les nouveaux chemins
        tomes_cbz._CACHE.clear()
        _scan_invalider()
    return len(deplaces), erreurs


@app.route("/api/serie/convertir", methods=["GET", "POST"])
def api_serie_convertir():
    """Convertit les .cbr de la série en .cbz (pages identiques, vérifiées) pour pouvoir y écrire les infos.
    GET : combien, et l'avancement. POST : lance en arrière-plan. La progression de lecture suit."""
    name = str((request.get_json(silent=True) or {}).get("series", "") if request.method == "POST" else request.args.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    cibles = _cbr_de(name)
    ok_cibles = [c for c in cibles if c[1]]
    if request.method == "GET":
        st = _CONVERSION.get(name) or {}
        return jsonify({"total": len(ok_cibles), "exclus": [{"fichier": c[0].name, "raison": c[2]} for c in cibles if not c[1]],
                        "en_cours": bool(st.get("en_cours")), "fait": st.get("fait", 0), "message": st.get("message", "")})
    if (_CONVERSION.get(name) or {}).get("en_cours"):
        return jsonify({"ok": False, "error": "Conversion déjà en cours pour cette série."}), 409
    if not ok_cibles:
        return jsonify({"ok": False, "error": "Aucun .cbr à convertir dans cette série."}), 400
    _CONVERSION[name] = {"en_cours": True, "fait": 0, "message": f"Conversion de {len(ok_cibles)} fichier(s)…"}

    def travail():
        try:
            fait, erreurs = _convertir_cbr_serie(name, ok_cibles, _CONVERSION[name])
            msg = f"{fait} fichier(s) converti(s) en .cbz sur {len(ok_cibles)}." + (" Erreurs : " + " ; ".join(erreurs) if erreurs else "")
        except Exception as ex:
            fait, erreurs, msg = 0, [str(ex)], f"Échec : {ex}"
        _CONVERSION[name] = {"en_cours": False, "fait": fait, "message": msg, "ok": not erreurs}
    threading.Thread(target=travail, daemon=True).start()
    return jsonify({"ok": True, "message": "Conversion lancée…"})


@app.route("/api/tome/chapitres/ecrire", methods=["GET", "POST"])
def api_tome_chapitres_ecrire():
    """📝 Écrit les chapitres (et leurs pages) et les infos du tome (résumé, provenance…) DANS son fichier .cbz (ComicInfo.xml), pour le partage.
    Fichier partagé par qBittorrent : version à part et échange de dossiers, le torrent n'est pas touché."""
    import edition
    import signets
    donnees = request.get_json(silent=True) or {} if request.method == "POST" else request.args
    name = str(donnees.get("series", ""))
    try:
        tome = int(float(donnees.get("tome", "")))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Tome inconnu"}), 400
    cle = (name, tome)
    if request.method == "GET":
        return jsonify(_SIGNETS.get(cle) or {})
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    e = _tome_complet(name, tome)
    if not e or e.get("path", "").lower().endswith(".cbr"):
        return jsonify({"ok": False, "error": "Seuls les tomes complets en .cbz peuvent recevoir leurs chapitres."}), 400
    chemin = MANGA_DIR / e["path"]
    if tomes_cbz.lire_info(chemin) is not None:
        return jsonify({"ok": False, "error": "Ce tome est un fichier assemblé par MouFlanga : ses chapitres y sont déjà."}), 400
    lu = (edition.lire(MANGA_DIR / name).get("sommaires") or {}).get(str(tome)) or {}
    chapitres = lu.get("chapitres") or []
    if not signets.nb_signets(chapitres):
        chapitres = None                                 # pas de chapitres avec page : seules les infos du tome sont écrites
    infos = _infos_tome(name, tome)
    partage = chemin.stat().st_nlink > 1
    import optimiser
    if partage and not optimiser._dossier_a_lui(chemin, name):
        return jsonify({"ok": False, "error": "Fichier partagé par qBittorrent et posé hors d'un dossier de tome : jamais modifié."}), 400
    if (_SIGNETS.get(cle) or {}).get("en_cours"):
        return jsonify({"ok": False, "error": "Écriture déjà en cours."}), 409
    _SIGNETS[cle] = {"en_cours": True, "message": "Écriture dans le fichier…"}

    def travail():
        try:
            _ecrire_fichier_tome(name, tome, chemin, chapitres, infos, partage)
            n = signets.nb_signets(chapitres or [])
            _SIGNETS[cle] = {"en_cours": False, "ok": True, "message": f"{_nom_tome(name, tome)} : infos écrites dans le fichier" + (f" ({n} chapitres)." if n else ".")
                             + (" Le fichier du torrent n'est pas touché." if partage else "")}
        except Exception as ex:
            logger.warning("Chapitres écrits dans %s : %s", chemin, ex)
            _SIGNETS[cle] = {"en_cours": False, "ok": False, "message": f"Échec : {ex}"}
    threading.Thread(target=travail, daemon=True).start()
    return jsonify({"ok": True, "message": "Écriture lancée…"})


# ---------------- 🎵 Génériques des mangas (OP1 de l'anime, même sans l'anime dans Emby) : admin ----------------
import generiques
generiques._ETAT["fichier"] = DATA_DIR / "generiques.json"


def _manga_id(n):
    st = (tomes._charger(n) or {}).get("statut_officiel") or {}
    if not st.get("anilist"):
        st = tomes.statut_officiel(n, forcer=True) or {}
    return st.get("anilist")


def _lancer_generiques(forcer=False):
    import notifier
    series = sorted(n for n in _scan() if n != "(Sans série)")
    return generiques.tout(series, MANGA_DIR, _manga_id, lambda n: _theme_de(_anime_de(n)) is not None,
                           lambda t: notifier.envoyer(t), forcer)


@app.route("/api/generiques", methods=["GET", "POST"])
def api_generiques():
    if request.method == "POST":
        ok = _lancer_generiques(bool((request.get_json(silent=True) or {}).get("forcer")))
        return jsonify({"ok": True, "message": "Recherche lancée en arrière-plan." if ok else "Une recherche est déjà en cours."})
    d = generiques.lire()
    e = {k: v for k, v in generiques._ETAT.items() if k != "fichier"}
    return jsonify({**e, "avec": sum(1 for v in d.values() if v.get("statut") == "ok"),
                    "sans": sum(1 for v in d.values() if v.get("statut") in ("aucun_anime", "aucun_theme"))})


def _boucle_generiques():
    """5 minutes après le démarrage, puis toutes les 6 heures : les séries jamais vérifiées reçoivent leur générique."""
    time.sleep(300)
    while True:
        try:
            _lancer_generiques()
        except Exception as e:
            logger.warning("Génériques automatiques : %s", e)
        time.sleep(6 * 3600)


def _anime_pour_generique(name):
    """(identifiant AniList, titre) de l'anime de la série, gardé dans generiques.json une fois trouvé."""
    v = generiques.lire().get(name) or {}
    if v.get("anime_id"):
        return v["anime_id"], v.get("anime", "")
    mid = _manga_id(name)
    return generiques.anime_du_manga(mid) if mid else None


@app.route("/api/generique/liste")
def api_generique_liste():
    """Tous les génériques de l'anime (AnimeThemes), à écouter avant d'en choisir un pour la série."""
    name = request.args.get("id", "")
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"error": "Série introuvable"}), 404
    try:
        a = _anime_pour_generique(name)
        if not a:
            return jsonify({"error": "Aucun anime connu pour ce manga (fiche AniList sans adaptation)."})
        themes = generiques.themes_de_l_anime(a[0])
    except Exception as e:
        logger.warning("Liste des génériques de %s : %s", name, e)
        return jsonify({"error": "AnimeThemes ou AniList ne répond pas, réessaie dans un moment."})
    v = generiques.lire().get(name) or {}
    actuel = "aucun" if v.get("statut") == "muet" else next((t["slug"] for t in themes if t["lien"] == v.get("source")), v.get("choix"))
    return jsonify({"anime": a[1], "themes": themes, "actuel": actuel, "manuel": bool(v.get("manuel"))})


@app.route("/api/generique/choisir", methods=["POST"])
def api_generique_choisir():
    """Générique choisi dans la liste (slug), « aucun » pour le silence, ou vide pour revenir au choix automatique."""
    body = request.get_json(silent=True) or {}
    name, slug = str(body.get("series", "")), str(body.get("slug") or "")
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    try:
        a = _anime_pour_generique(name)
        if not a:
            return jsonify({"ok": False, "error": "Aucun anime connu pour ce manga."})
        if slug == "aucun":
            generiques.choisir(name, MANGA_DIR / name, None, a[1], a[0])
            return jsonify({"ok": True, "message": "Plus de générique pour cette série."})
        if not slug:                                     # retour à l'automatique : OP1 reposé
            generiques._noter(name, statut="a_revoir")
            generiques.pour_serie(name, MANGA_DIR / name, _manga_id(name), forcer=True)
            return jsonify({"ok": True, "message": "Générique automatique (premier opening) rétabli."})
        theme = next((t for t in generiques.themes_de_l_anime(a[0]) if t["slug"] == slug), None)
        if not theme:
            return jsonify({"ok": False, "error": "Générique introuvable dans la liste."})
        generiques.choisir(name, MANGA_DIR / name, theme, a[1], a[0])
    except Exception as e:
        logger.warning("Choix du générique de %s : %s", name, e)
        return jsonify({"ok": False, "error": f"Échec : {e}"})
    return jsonify({"ok": True, "message": f"Générique {slug} enregistré, au même volume que ceux de MouFlopening."})


@app.route("/api/generiques/harmoniser", methods=["GET", "POST"])
def api_generiques_harmoniser():
    """Ramène une fois tous les génériques des mangas au niveau sonore réglé dans MouFlopening."""
    if request.method == "POST":
        fichiers = [MANGA_DIR / n / generiques.FICHIER_SON for n in _scan() if (MANGA_DIR / n / generiques.FICHIER_SON).is_file()]
        ok = generiques.renormaliser(fichiers)
        return jsonify({"ok": True, "message": "Harmonisation lancée en arrière-plan." if ok else "Une harmonisation est déjà en cours."})
    return jsonify(dict(generiques._NORMAL))


@app.route("/api/generique")
def api_generique():
    """Écouter le générique de l'anime de la série (fichier rangé par MouFlopening dans la médiathèque Emby)."""
    name = request.args.get("id", "")
    if name not in _scan():
        return jsonify({"error": "Série introuvable"}), 404
    f = _theme_de(_anime_de(name))
    if not f and (MANGA_DIR / name / generiques.FICHIER_SON).is_file():
        f = MANGA_DIR / name / generiques.FICHIER_SON          # OP1 de l'anime, posé par generiques.py
    if not f:
        return jsonify({"error": "Pas de générique"}), 404
    return send_file(f, conditional=True, max_age=3600)


@app.route("/api/resume", methods=["POST"])
def api_resume():
    """Résumé modifié à la main ; texte vide = revenir au résumé trouvé sur Internet."""
    body = request.get_json(silent=True) or {}
    name, texte = str(body.get("series", "")), str(body.get("texte", "")).strip()
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    if len(texte) > 5000:
        return jsonify({"ok": False, "error": "Résumé trop long (5 000 caractères au plus)."}), 400
    perso = _read_json(RESUMES, {})
    if texte:
        perso[name] = texte
    else:
        perso.pop(name, None)
    _write_json(RESUMES, perso)
    logger.info("Résumé de « %s » %s", name, "modifié à la main" if texte else "remis en automatique")
    return jsonify({"ok": True, "message": "Résumé enregistré." if texte else "Résumé automatique rétabli."})


@app.route("/api/tome/resume", methods=["POST"])
def api_tome_resume():
    """Résumé d'un tome écrit à la main (gardé avec la série) ; texte vide = revenir au résumé trouvé sur Internet."""
    body = request.get_json(silent=True) or {}
    name, texte = str(body.get("series", "")), str(body.get("texte", "")).strip()
    try:
        tome = int(float(body.get("tome")))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Tome inconnu"}), 400
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    if len(texte) > 5000:
        return jsonify({"ok": False, "error": "Résumé trop long (5 000 caractères au plus)."}), 400
    import edition
    infos = edition.lire(MANGA_DIR / name)
    rt = infos.setdefault("resumes_tomes", {})
    if texte:
        rt[str(tome)] = texte
    else:
        rt.pop(str(tome), None)
    edition.ecrire(MANGA_DIR / name, infos)
    logger.info("Résumé du tome %s de « %s » %s", tome, name, "écrit à la main" if texte else "remis en automatique")
    return jsonify({"ok": True, "message": "Résumé du tome enregistré." if texte else "Résumé automatique rétabli."})


@app.route("/api/tomes/ranger", methods=["POST"])
def api_tomes_ranger():
    """Bouton « Ranger en tomes » : cherche les tomes sur Internet puis range la série (en arrière-plan)."""
    name = str((request.get_json(silent=True) or {}).get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    for j in list(japscan_scraper.download_jobs.values()):
        if j.get("status") == "running" and japscan_scraper.nom_sur(japscan_scraper.titre_serie(j.get("title") or "")) == name:
            return jsonify({"ok": False, "error": "Cette série est en cours de téléchargement : elle sera rangée à la fin."}), 409
    with _RANGEMENT_VERROU:
        if (_RANGEMENTS.get(name) or {}).get("en_cours"):
            return jsonify({"ok": True, "message": "Rangement déjà en cours."})
        _RANGEMENTS[name] = {"en_cours": True, "fait": 0, "total": 0, "erreur": None, "message": "Recherche des tomes…"}

    threading.Thread(target=_rangement_complet, args=(name, True), daemon=True).start()
    return jsonify({"ok": True, "message": "Recherche des tomes…"})


def _rangement_complet(name, forcer=False):
    """Cherche la répartition en tomes puis range la série ; le message de fin est montré sur la page de la série."""
    etat = _RANGEMENTS.setdefault(name, {})
    etat.update(en_cours=True, message="Recherche des tomes…")
    try:
        info = tomes.chercher(name, forcer=forcer)
        if not info:
            etat.update(en_cours=False, message="Aucune source (Wikipédia, MangaDex) ne connaît les tomes de cette série : les chapitres restent un fichier chacun.")
            return 0
        try:
            _separer_doubles(name, info, etat)
        except Exception as e:
            logger.warning("Coupure des fichiers à deux tomes de « %s » : %s", name, e)
        n = _ranger_en_tomes(name, info, garder_en_cours=True)
        etat.update(en_cours=False, message=f"✅ {n} chapitre(s) rangé(s) en tomes (d'après {info['source']})." if n
                    else f"Déjà rangée (d'après {info['source']}).")
        return n
    except Exception as e:
        etat.update(en_cours=False, message=f"Rangement impossible : {e}")
        return None


def _en_telechargement(name):
    return any(j.get("status") == "running" and japscan_scraper.nom_sur(japscan_scraper.titre_serie(j.get("title") or "")) == name
               for j in list(japscan_scraper.download_jobs.values()))


def _a_ranger(name):
    """La série a-t-elle des chapitres « Hors tome » (fichier de l'appli) ? Ils attendent que leur tome soit connu."""
    return any(e.get("tome") is None and e.get("groupe") == tomes_cbz.dossier_tome(None) for e in _entrees(_scan().get(name) or []))


TROUVES = DATA_DIR / "mangas-trouves.json"        # séries trouvées par recherche : restent dans la liste
CATALOGUE = DATA_DIR / "catalogue-japscan.json"    # tout le catalogue, chargé sur demande (gardé un mois)
_CATALOGUE_ETAT = {"en_cours": False, "page": 0, "pages": 0, "series": 0, "message": ""}


@app.route("/api/japscan/catalogue", methods=["POST"])
def japscan_catalogue():
    """Charge tout le catalogue de Japscan en arrière-plan (20 à 30 minutes)."""
    if _CATALOGUE_ETAT["en_cours"]:
        return jsonify({"ok": True, "message": "Chargement déjà en cours."})
    if any(j.get("status") == "running" for j in japscan_scraper.download_jobs.values()):
        return jsonify({"ok": False, "error": "Un téléchargement est en cours : attends sa fin (le navigateur du serveur est pris)."}), 409
    _CATALOGUE_ETAT.update(en_cours=True, page=0, pages=0, series=0, message="Ouverture de Japscan…")

    def travail():
        try:
            liste = japscan_scraper.JapscanScraper(MANGA_DIR).catalogue_sync(_CATALOGUE_ETAT)
            if liste:
                CATALOGUE.write_text(json.dumps({"date": time.time(), "mangas": liste}, ensure_ascii=False), encoding="utf-8")
            n = len({m["url"] for m in liste})
            _CATALOGUE_ETAT["message"] = f"✅ Catalogue chargé : {n} séries."
            logger.info("Catalogue Japscan chargé : %d séries", n)
            try:
                import notifier
                notifier.envoyer(f"📚 MouFlanga : catalogue Japscan chargé ({n} séries).")
            except Exception:
                pass
        except Exception as e:
            _CATALOGUE_ETAT["message"] = f"Chargement du catalogue interrompu : {e}"
            logger.warning(_CATALOGUE_ETAT["message"])
        finally:
            _CATALOGUE_ETAT["en_cours"] = False
    threading.Thread(target=travail, daemon=True).start()
    return jsonify({"ok": True, "message": "Chargement du catalogue lancé (20 à 30 minutes)."})


@app.route("/api/japscan/catalogue")
def japscan_catalogue_etat():
    return jsonify({**_CATALOGUE_ETAT, "catalogue": _info_catalogue()})


def _sources_en_plus():
    """Séries trouvées par recherche (gardées pour toujours) et catalogue complet (s'il a été chargé)."""
    en_plus = []
    for f in (TROUVES, CATALOGUE):
        try:
            en_plus += json.loads(f.read_text(encoding="utf-8")).get("mangas", [])
        except (OSError, ValueError):
            pass
    return en_plus


def _info_catalogue():
    try:
        c = json.loads(CATALOGUE.read_text(encoding="utf-8"))
        return {"date": c.get("date"), "nombre": len(c.get("mangas", []))}
    except (OSError, ValueError):
        return None


@app.route("/api/japscan/list")
def japscan_list():
    """Liste les mangas : dernières sorties (gardées 6 h) + séries trouvées par recherche + catalogue complet si chargé."""
    forcer = request.args.get("rafraichir") == "1"
    en_plus = _sources_en_plus()
    infos = {"catalogue": _info_catalogue(), "chargement_catalogue": _CATALOGUE_ETAT}
    try:
        with _LISTE_VERROU:
            if not forcer:
                try:
                    cache = json.loads(LISTE_CACHE.read_text(encoding="utf-8"))
                    age = time.time() - cache.get("date", 0)
                    if cache.get("mangas") and age < LISTE_DUREE:
                        mangas = japscan_scraper.regrouper_series(cache["mangas"] + en_plus)
                        return jsonify({"ok": True, "mangas": mangas, "cache_minutes": int(age // 60), **infos})
                except Exception:
                    pass
            scraper = japscan_scraper.JapscanScraper(MANGA_DIR)
            mangas = scraper.list_manga_sync()
            if mangas:
                try:
                    LISTE_CACHE.write_text(json.dumps({"date": time.time(), "mangas": mangas}, ensure_ascii=False),
                                           encoding="utf-8")
                except Exception as e:
                    logger.warning(f"Liste des mangas non gardée en mémoire : {e}")
        return jsonify({"ok": True, "mangas": japscan_scraper.regrouper_series(mangas + en_plus), "cache_minutes": 0, **infos})
    except Exception as e:
        logger.error(f"Erreur liste Japscan: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


def _marquer_deja(chapters, titre):
    """Ajoute « deja » (déjà dans la bibliothèque) à chaque chapitre, d'après les fichiers du dossier de la série."""
    if not titre:
        return chapters
    deja = _deja_telecharges(titre)
    nom = _dossier_serie(titre).name
    tomes_la = {e.get("tome") for e in _entrees(_scan().get(nom) or []) if e.get("tome") is not None}
    tomes_la |= {int(e["groupe"].split()[1]) for e in _entrees(_scan().get(nom) or []) if (e.get("groupe") or "").startswith("Tome ")}
    return [{**c, "deja": (c["volume"] in tomes_la) if c.get("volume") is not None else japscan_scraper._numero(c) in deja}
            for c in chapters]


_RECHERCHES = {}                # texte -> (heure, résultats) : gardés 1 heure


@app.route("/api/japscan/recherche", methods=["POST"])
def japscan_recherche():
    """Recherche dans tout le catalogue de Japscan (ouvre le navigateur : 10 à 30 secondes)."""
    texte = str((request.get_json(silent=True) or {}).get("q", "")).strip()[:80]
    if len(texte) < 2:
        return jsonify({"ok": False, "error": "Tape au moins 2 lettres."}), 400
    cle = texte.lower()
    ancien = _RECHERCHES.get(cle)
    if ancien and time.time() - ancien[0] < 3600:
        return jsonify({"ok": True, "mangas": ancien[1]})
    try:
        resultats = japscan_scraper.JapscanScraper(MANGA_DIR).rechercher_sync(texte)
    except Exception as e:
        logger.error(f"Recherche Japscan impossible : {e}")
        return jsonify({"ok": False, "error": f"Recherche impossible : {e}"}), 500
    _RECHERCHES[cle] = (time.time(), resultats)
    if resultats:                                          # elles restent ensuite dans la liste
        try:
            gardees = json.loads(TROUVES.read_text(encoding="utf-8")).get("mangas", []) if TROUVES.exists() else []
        except (OSError, ValueError):
            gardees = []
        connues = {m["url"] for m in gardees}
        gardees += [{"title": m["title"], "url": m["url"]} for m in resultats if m["url"] not in connues]
        TROUVES.write_text(json.dumps({"mangas": gardees}, ensure_ascii=False), encoding="utf-8")
    return jsonify({"ok": True, "mangas": resultats})


@app.route("/api/japscan/chapters/<manga_id>", methods=["POST"])
def japscan_chapters(manga_id: str):
    """Récupère les chapitres d'un manga (gardés 1 heure en mémoire)."""
    try:
        body = request.get_json() or {}
        manga_url = body.get("url")
        if not manga_url:
            return jsonify({"ok": False, "error": "URL manquante"}), 400

        with _CHAPITRES_VERROU:
            ancien = _CHAPITRES_CACHE.get(manga_url)
            if ancien and time.time() - ancien[0] < CHAPITRES_DUREE and not body.get("rafraichir"):
                return jsonify({"ok": True, "chapters": _marquer_deja(ancien[1], body.get("title"))})
            scraper = japscan_scraper.JapscanScraper(MANGA_DIR)
            chapters = scraper.get_chapters_sync(manga_url)
            if chapters:
                _CHAPITRES_CACHE[manga_url] = (time.time(), chapters)
        return jsonify({"ok": True, "chapters": _marquer_deja(chapters, body.get("title"))})
    except Exception as e:
        logger.error(f"Erreur chapitres Japscan: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/japscan/download", methods=["POST"])
def japscan_download():
    """Lance le téléchargement d'un manga."""
    try:
        body = request.get_json() or {}
        manga_title = body.get("title")
        chapters = body.get("chapters", [])

        if not manga_title or not chapters:
            return jsonify({"ok": False, "error": "Données manquantes"}), 400

        import uuid

        job_id = str(uuid.uuid4())[:12]
        output_dir = _dossier_serie(manga_title)

        # Lance le téléchargement en arrière-plan
        thread = threading.Thread(
            target=japscan_scraper.download_manga_background,
            args=(job_id, manga_title, chapters, output_dir),
            kwargs={"preparer": lambda: _preparer_tomes(output_dir.name)},
            daemon=True
        )
        thread.start()

        return jsonify({"ok": True, "job_id": job_id})
    except Exception as e:
        logger.error(f"Erreur lancement téléchargement: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/japscan/job/<job_id>")
def japscan_job(job_id: str):
    """Récupère l'état d'un job de téléchargement."""
    job = japscan_scraper.download_jobs.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Job introuvable"}), 404
    return jsonify({"ok": True, "job": job})


@app.route("/api/japscan/jobs")
def japscan_jobs():
    """Liste des téléchargements (en cours et terminés depuis le démarrage de l'appli)."""
    jobs = []
    for j in list(japscan_scraper.download_jobs.values()):
        jobs.append({
            "id": j.get("id"), "title": j.get("title"), "status": j.get("status"),
            "progress": j.get("progress", 0), "total": j.get("total", 0),
            "downloaded": len(j.get("downloaded", [])), "failed": len(j.get("failed", [])),
            "en_cours": j.get("en_cours"), "error": j.get("error"),
            "started": j.get("started"), "ended": j.get("ended"),
            "en_attente_captcha": j.get("en_attente_captcha", 0), "captchas": j.get("captchas"),
        })
    jobs.sort(key=lambda j: j.get("started") or "", reverse=True)
    return jsonify({"ok": True, "jobs": jobs})


@app.route("/api/japscan/job/<job_id>/annuler", methods=["POST"])
def japscan_job_annuler(job_id: str):
    """Demande l'arrêt d'un téléchargement (il s'arrête à la fin du chapitre en cours)."""
    job = japscan_scraper.download_jobs.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Job introuvable"}), 404
    job["annule"] = True
    return jsonify({"ok": True})


@app.route("/api/japscan/verif/etat")
def japscan_verif_etat():
    """Une vérification Cloudflare attend-elle l'utilisateur ?"""
    return jsonify({"ok": True, **japscan_scraper.verif_etat()})


@app.route("/api/japscan/verif/capture")
def japscan_verif_capture():
    """Capture d'écran du navigateur du serveur (pour passer la vérification à la main)."""
    try:
        png, zone = japscan_scraper.verif_capture_zoom()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e) or "Capture impossible"}), 409
    resp = Response(png, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store"
    # Si la capture est recadrée (captcha), l'interface a besoin du décalage pour renvoyer les clics au bon endroit
    resp.headers["X-Zone"] = f"{zone['x']},{zone['y']},{zone['width']},{zone['height']}" if zone else ""
    return resp


@app.route("/api/japscan/verif/defiler", methods=["POST"])
def japscan_verif_defiler():
    """Fait défiler la page du navigateur du serveur."""
    body = request.get_json(silent=True) or {}
    try:
        dy = max(-3000.0, min(3000.0, float(body.get("dy"))))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Valeur invalide"}), 400
    try:
        japscan_scraper.verif_defiler(dy)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e) or "Défilement impossible"}), 409
    return jsonify({"ok": True})


@app.route("/api/japscan/verif/glisser", methods=["POST"])
def japscan_verif_glisser():
    """Relaie un glissement du doigt (captcha à remettre en ordre) dans le navigateur du serveur."""
    body = request.get_json(silent=True) or {}
    try:
        points = [(float(x), float(y)) for x, y in (body.get("points") or [])]
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Trajet invalide"}), 400
    if not (2 <= len(points) <= 120) or any(not (0 <= x <= 5000 and 0 <= y <= 5000) for x, y in points):
        return jsonify({"ok": False, "error": "Trajet invalide"}), 400
    try:
        info = japscan_scraper.verif_glisser(points)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e) or "Glissement impossible"}), 409
    return jsonify({"ok": True, "info": info})


@app.route("/api/japscan/verif/clic", methods=["POST"])
def japscan_verif_clic():
    """Relaie un clic de l'utilisateur dans le navigateur du serveur."""
    body = request.get_json(silent=True) or {}
    try:
        x, y = float(body.get("x")), float(body.get("y"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Coordonnées invalides"}), 400
    if not (0 <= x <= 5000 and 0 <= y <= 5000):
        return jsonify({"ok": False, "error": "Coordonnées hors de la page"}), 400
    try:
        info = japscan_scraper.verif_clic(x, y)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e) or "Clic impossible"}), 409
    return jsonify({"ok": True, "info": info})


@app.route("/verification")
def verification():
    """Page pour passer la vérification Cloudflare à la main."""
    return render_template("verification.html", version=APP_VERSION)


@app.route("/regles")
def page_regles():
    """📏 Règles de recherche (admin) : profils de version et formats personnalisés, comme dans Sonarr."""
    onglet = request.args.get("onglet") if request.args.get("onglet") in ("formats", "tester", "sources") else "profils"
    edit = request.args.get("edit", "")
    cle = "profils" if onglet == "profils" else "formats"
    modif = next((x for x in regles.profils() if x["id"] == edit), None) if edit and cle == "profils" else None
    if edit and cle == "formats":
        modif = next((x for x in regles.formats() if x["id"] == edit), None)
    cle = tomes.cle_google_books()
    return render_template("regles.html", version=APP_VERSION, onglet=onglet, profils=regles.profils(),
                           formats=regles.formats(), modif=modif, types_conditions=regles.TYPES, toutes_series=sorted((n for n in _scan() if n != "(Sans série)"), key=str.lower),
                           cle_gb=("…" + cle[-4:]) if len(cle) >= 8 else "",
                           cle_claude=("…" + os.getenv("CLAUDE_API_KEY", "").strip()[-4:]) if len(os.getenv("CLAUDE_API_KEY", "").strip()) >= 8 else "",
                           ok=request.args.get("ok", ""), erreur=request.args.get("erreur", ""))


_CLE_GOOGLE_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


@app.route("/regles/google-books", methods=["POST"])
def regles_google_books():
    """Clé API Google Books : « Tester » vérifie auprès de Google ; « Enregistrer » ne garde que une clé acceptée."""
    from secrets_store import write_secret
    f = request.form
    cle = f.get("cle", "").strip()
    retour = "/regles?onglet=sources"
    if f.get("action") == "retirer":
        write_secret(DATA_DIR / "secrets.env", "GOOGLE_BOOKS_API_KEY", "")
        os.environ["GOOGLE_BOOKS_API_KEY"] = ""
        return redirect(retour + "&ok=" + quote("Clé retirée : Google Books n'est plus interrogé."))
    if not _CLE_GOOGLE_RE.match(cle):
        return redirect(retour + "&erreur=" + quote("Clé invalide : lettres, chiffres, tirets et tirets bas seulement (colle-la sans espace)."))
    ok, msg = tomes.verifier_cle_google(cle)
    if f.get("action") == "tester":
        return redirect(retour + ("&ok=" if ok else "&erreur=") + quote(msg))
    if not ok:
        return redirect(retour + "&erreur=" + quote(msg + ". Rien n'a été enregistré."))
    write_secret(DATA_DIR / "secrets.env", "GOOGLE_BOOKS_API_KEY", cle)
    os.environ["GOOGLE_BOOKS_API_KEY"] = cle
    logger.info("Clé API Google Books enregistrée depuis la page Règles")
    return redirect(retour + "&ok=" + quote("Clé enregistrée. " + msg + "."))


_CLE_CLAUDE_RE = re.compile(r"^sk-ant-[A-Za-z0-9_-]{20,200}$")


@app.route("/regles/claude", methods=["POST"])
def regles_claude():
    """Clé API de Claude (facultative, payante) : lecture des sommaires stylisés que l'OCR ne lit pas."""
    import sommaire
    from secrets_store import write_secret
    f = request.form
    cle = f.get("cle", "").strip()
    retour = "/regles?onglet=sources"
    if f.get("action") == "retirer":
        write_secret(DATA_DIR / "secrets.env", "CLAUDE_API_KEY", "")
        os.environ["CLAUDE_API_KEY"] = ""
        return redirect(retour + "&ok=" + quote("Clé de Claude retirée : seuls les sommaires lisibles par l'OCR sont lus."))
    if not _CLE_CLAUDE_RE.match(cle):
        return redirect(retour + "&erreur=" + quote("Clé invalide : elle commence par « sk-ant- » (colle-la sans espace)."))
    ok, msg = sommaire.verifier_cle_claude(cle)
    if f.get("action") == "tester" or not ok:
        return redirect(retour + ("&ok=" if ok else "&erreur=") + quote(msg + ("" if ok or f.get("action") == "tester" else ". Rien n'a été enregistré.")))
    write_secret(DATA_DIR / "secrets.env", "CLAUDE_API_KEY", cle)
    os.environ["CLAUDE_API_KEY"] = cle
    logger.info("Clé API de Claude enregistrée depuis la page Règles")
    return redirect(retour + "&ok=" + quote("Clé enregistrée. " + msg + "."))


@app.route("/regles/enregistrer", methods=["POST"])
def regles_enregistrer():
    f = request.form
    quoi = "format" if f.get("quoi") == "format" else "profil"
    onglet = "formats" if quoi == "format" else "profils"
    try:
        if f.get("supprimer"):
            regles.supprimer(quoi, f.get("id", ""))
            msg = "Supprimé."
        elif quoi == "profil":
            points = {fm["id"]: f.get("score_" + fm["id"], "") for fm in regles.formats()}      # vide = points par défaut du format
            regles.enregistrer_profil(f.get("id", ""), f.get("nom", ""), bool(f.get("actif")), f.get("doit", ""),
                                      f.get("ne_doit_pas", ""), f.getlist("series"), f.get("taille_max_go", ""),
                                      scores=points, score_min=f.get("score_min", ""), score_arret=f.get("score_arret", ""),
                                      sources_min=f.get("sources_min", ""))
            msg = "Profil enregistré. Les prochaines recherches en tiennent compte."
        else:
            try:
                conditions = json.loads(f.get("conditions") or "[]")
            except ValueError:
                raise ValueError("Les conditions n'ont pas pu être lues : recharge la page et recommence.")
            if not isinstance(conditions, list):
                raise ValueError("Les conditions n'ont pas pu être lues : recharge la page et recommence.")
            regles.enregistrer_format(f.get("id", ""), f.get("nom", ""), "", f.get("score", "0"), conditions)
            msg = "Format enregistré. Les prochaines recherches en tiennent compte."
        return redirect("/regles?onglet=" + onglet + "&ok=" + quote(msg))
    except ValueError as e:
        return redirect("/regles?onglet=" + onglet + "&erreur=" + quote(str(e)))


@app.route("/regles/equipes", methods=["POST"])
def regles_equipes():
    """Met à jour tout de suite les profils d'équipe (sinon ils le sont toutes les 6 heures)."""
    b = regles.synchroniser_equipes(_equipes_par_serie())
    msg = ("Profils d'équipe à jour : " + ", ".join(f"{len(v)} {k.replace('_', ' ')}" for k, v in b.items() if v)) if any(b.values()) else "Les profils d'équipe étaient déjà à jour."
    return redirect("/regles?onglet=profils&ok=" + quote(msg))


@app.route("/regles/modeles", methods=["POST"])
def regles_modeles():
    """Ajoute les formats de départ et un profil « Manga VF numérique » (désactivé) sans rien toucher à l'existant."""
    n = regles.ajouter_modeles()
    msg = f"{n} élément(s) ajouté(s). Le profil « Manga VF numérique » est désactivé : active-le quand il te convient." if n else "Les modèles de départ sont déjà là."
    return redirect("/regles?onglet=profils&ok=" + quote(msg))


@app.route("/telecharger")
def telecharger():
    """Page de téléchargement de mangas depuis Japscan."""
    return render_template("telecharger.html", version=APP_VERSION)


# ----------------------------------------------------------------------------
# Journal, Réglages
# ----------------------------------------------------------------------------

def _diag_extra():
    n_series, n_files = 0, 0
    try:
        sc = _scan()
        n_series, n_files = len(sc), sum(len(v) for v in sc.values())
    except Exception as e:
        return [f"Bibliothèque : analyse impossible ({e.__class__.__name__})"]
    rar = "oui" if archives.rar_available() else "NON (les vrais .cbr en RAR ne s'ouvriront pas)"
    lignes = [f"Bibliothèque : {n_series} série(s), {n_files} fichier(s)", f"Lecture des RAR possible : {rar}"]
    try:
        import notifier
        lignes += ["", "--- Telegram ---"] + notifier.diagnostic()
        lignes.append(f"Vérification Cloudflare en attente : {'OUI' if japscan_scraper.verif_etat()['actif'] else 'non'}")
        hist = japscan_scraper.verif_historique()
        if hist:
            lignes += ["", "--- Vérification Cloudflare (derniers événements) ---"] + ["  " + h for h in hist]
    except Exception as e:
        lignes.append(f"Telegram : diagnostic impossible ({e.__class__.__name__})")
    lignes += ["", "--- Sources Internet de l'identification (état de chacune) ---"] + _diag_sources()
    lignes += ["", "--- Noms de domaine (DNS du serveur) ---"] + _diag_dns()
    lignes += ["", "--- Carte graphique (accès du serveur) ---"] + _diag_gpu()
    return lignes


def _diag_sources():
    """Une ligne par service (AniList, Wikipédia, BnF, Google Books…) : répond-il ? en pause jusqu'à quand et pourquoi ? requêtes du jour
    (Google Books : sur 1 000) ; ses dernières pannes ; puis les séries dont une recherche attend un service."""
    lignes = []
    for e in reseau.etat():
        ligne = f"{e['libelle']} : "
        if e["pause_jusqua"]:
            ligne += f"EN PAUSE jusqu'à {identification.heure_fr(e['pause_jusqua'])} ({e['pause_raison']})"
        else:
            ligne += "répond normalement"
        if e["quota_jour"]:
            ligne += f" · {e['requetes_du_jour']} requête(s) aujourd'hui sur {e['quota_jour']}"
        elif e["requetes_du_jour"]:
            ligne += f" · {e['requetes_du_jour']} requête(s) aujourd'hui"
        lignes.append(ligne)
        for quand, texte in e["dernieres_pannes"][-2:]:
            lignes.append(f"    dernière panne {time.strftime('%d/%m %H:%M', time.localtime(quand))} : {texte}")
    try:
        noms = [n for n in _scan() if n != "(Sans série)"]
        attente = identification.a_reprendre(noms, maintenant=time.time() + 30 * 86400)
        if attente:
            lignes.append(f"Séries dont une recherche attend un service ou un nouvel essai : {len(attente)}"
                          + " (" + ", ".join(attente[:8]) + ("…" if len(attente) > 8 else "") + ")")
    except Exception as e:
        lignes.append(f"Reprises : lecture impossible ({e.__class__.__name__})")
    return lignes


def _diag_gpu():
    """Le serveur voit-il la carte graphique (/dev/dri) et les outils pour s'en servir ?"""
    import grp
    import shutil
    import subprocess
    lignes = []
    try:
        dri = Path("/dev/dri")
        if not dri.exists():
            lignes.append("/dev/dri : ABSENT (la carte graphique n'est pas donnée à ce conteneur)")
        else:
            for f in sorted(dri.iterdir()):
                st = f.stat()
                try:
                    groupe = grp.getgrgid(st.st_gid).gr_name
                except KeyError:
                    groupe = str(st.st_gid)
                lignes.append(f"  /dev/dri/{f.name} : droits {oct(st.st_mode)[-3:]}, groupe {groupe}, lisible {'oui' if os.access(f, os.R_OK | os.W_OK) else 'NON'}")
        noms = []
        for g in os.getgroups():
            try:
                noms.append(grp.getgrgid(g).gr_name)
            except KeyError:
                noms.append(str(g))
        lignes.append(f"Groupes de l'appli : {', '.join(noms)} · DISPLAY={os.environ.get('DISPLAY', '(aucun)')}")
        outils = {n: bool(shutil.which(n)) for n in ("vainfo", "glxinfo", "eglinfo", "Xorg", "Xvfb", "weston", "cage", "intel_gpu_top")}
        lignes.append("Outils présents : " + ", ".join(f"{n} {'oui' if ok else 'non'}" for n, ok in outils.items()))
        if outils["vainfo"]:
            r = subprocess.run(["vainfo"], capture_output=True, text=True, timeout=8)
            lignes += ["  vainfo : " + l.strip() for l in (r.stdout + r.stderr).splitlines()[:6] if l.strip()]
    except Exception as e:
        lignes.append(f"Diagnostic de la carte graphique impossible : {e.__class__.__name__}")
    return lignes


def _diag_dns():
    """Vérifie que le serveur sait joindre les adresses dont Cloudflare a besoin pour valider la vérification."""
    lignes = []
    try:
        serveurs = [l.split()[1] for l in open("/etc/resolv.conf", encoding="utf-8") if l.startswith("nameserver")]
        lignes.append("Serveur(s) DNS utilisé(s) : " + (", ".join(serveurs) or "aucun"))
    except OSError:
        pass
    try:
        c = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        c.settimeout(4)
        c.connect(("2606:4700:4700::1111", 443))
        c.close()
        lignes.append("IPv6 du serveur : oui")
    except OSError:
        lignes.append("IPv6 du serveur : NON (brunhild.challenges.cloudflare.com n'existe qu'en IPv6 : redirigé vers IPv4 par l'appli)")
    for nom in ("www.japscan.foo", "challenges.cloudflare.com", "brunhild.challenges.cloudflare.com",
                "turnstile.cloudflare.com", "cloudflare.com"):
        try:
            ip = socket.getaddrinfo(nom, 443)[0][4][0]
            lignes.append(f"  ✅ {nom} → {ip}")
        except OSError as e:
            lignes.append(f"  ❌ {nom} : introuvable ({e.__class__.__name__})")
    return lignes


diag.init_app(app, APP_VERSION, lambda: MANGA_DIR, _diag_extra)
import settings_page
settings_page.init_app(app, BASE_DIR, lambda: APP_VERSION, lambda: {"manga": str(MANGA_DIR)})


def _series_externes():
    return [{"name": n, "cover": (MANGA_DIR / n / COUVERTURE_PERSO).is_file()} for n in _scan() if n != "(Sans série)"]


def _couverture_choisie(nom):
    if nom not in _scan() or nom == "(Sans série)":
        return None
    c = MANGA_DIR / nom / COUVERTURE_PERSO
    return c if c.is_file() else None


import api_externe
api_externe.init_app(app, BASE_DIR, lambda: APP_VERSION, _series_externes, _couverture_choisie, _enregistrer_couverture)

import redemarrage      # alerte Telegram après un plantage ou un redémarrage du serveur
redemarrage.init_app(app, BASE_DIR)
import redemarrer
redemarrer.init_app(app, lambda: _travaux_en_cours())

import demandes         # 📮 demandes de mangas des lecteurs, rappels Telegram
demandes._ETAT["prevenir"] = _prevenir_demande
demandes.init_app(app, DATA_DIR, lambda t: __import__("notifier").envoyer(t), auth.role, auth.utilisateur,
                  lambda: os.getenv("APP_URL", "").strip(), demarrer=False)
demandes._ETAT["accepte"] = _accepter_demande
demandes._ETAT["autres"] = lambda: [f"• {n} : {p['titre'][:80]}" for n, p in suivi.en_attente()]


# ---------------- ⚡ Préparation de la bibliothèque en arrière-plan (prechauffage.py) ----------------
import prechauffage


def _signature_serie(nom):
    fichiers = _scan().get(nom) or []
    if not fichiers:                       # série suivie encore vide : refaite si sa fiche ou ses titres changent
        x = suivi.lire()["series"].get(nom) or {}
        return prechauffage.signature_fichiers([(f"suivie|{x.get('anilist') or ''}|{'|'.join(x.get('titres', []))}", 0, 0)])
    return prechauffage.signature_fichiers([(str(p.relative_to(MANGA_DIR)) if MANGA_DIR in p.parents else str(p),
                                             *(_stat_index(p) or (0, 0))) for p in fichiers])


def _series_preparables():
    """Séries à préparer en fond : celles de la bibliothèque, et les séries suivies encore vides (leur synopsis, leur fiche et leurs noms
    français se cherchent aussi : sans eux, la fiche reste vide et les torrents proposés ne sont pas reconnus)."""
    return {**{n: [] for n in suivi.lire()["series"]}, **_scan()}


def _attendre_lectures(sommaire, nom, en_lecture, garder):
    """Attend que les sommaires en cours de lecture ne soient plus que « garder » (15 min au plus par tome)."""
    debut = time.time()
    while True:
        en_lecture[:] = [t for t in en_lecture if sommaire.etat(nom, t).get("en_cours")]
        if len(en_lecture) <= garder or time.time() - debut > 900:
            return
        time.sleep(2)


def _preparer_serie_suivie(nom, progression):
    """Série suivie encore sans fichier : statut, synopsis et fiche se cherchent quand même (ses synonymes, dont le titre français, servent
    ensuite à reconnaître ses torrents). Rend l'heure de reprise d'une étape qui attend un service."""
    if nom not in suivi.lire()["series"]:
        return None
    progression(f"{nom} : fiche de la série suivie")
    try:
        bilans = identification.identifier(nom, etapes=("statut", "fiche"))
    except Exception as e:
        logger.info("Préparation de la série suivie %s : %s", nom, e.__class__.__name__)
        return None
    reprises = [b.prochain for b in bilans.values() if b.prochain]
    return min(reprises) if reprises else None


def _preparer_serie(nom, progression):
    """Tout ce que la fiche d'un tome irait chercher, fait d'avance : identification (statut, liste des volumes de Wikipédia, répartition
    en tomes, fiche, ISBN et résumés des tomes), analyse de l'édition, hors-série, sommaire imprimé des tomes (un par un, après les
    vrais travaux). Ce qu'un service n'a pas pu donner (quota de Google Books, Wikipédia qui demande de patienter…) est refait plus tard
    toute seule : la série revient dans la file à l'heure indiquée (valeur rendue)."""
    import sommaire
    fichiers = _scan().get(nom) or []
    if not fichiers:
        return _preparer_serie_suivie(nom, progression)
    progression(f"{nom} : identification")
    bilans = {}
    try:
        def etape_en_cours(cle, etat, detail):
            if etat == "en_cours":
                progression(f"{nom} : " + dict(identification.ETAPES)[cle].split(" (")[0].lower())
        bilans = identification.identifier(nom, rapport=etape_en_cours)
    except Exception as e:
        logger.info("Préparation de %s, identification : %s", nom, e.__class__.__name__)
    _infos_edition(nom, fichiers)                          # lance l'analyse des pages (en fond) si elle n'est pas faite
    progression(f"{nom} : hors-série et séries dérivées")
    try:
        _placer_hors_series(nom)
    except Exception as e:
        logger.info("Préparation de %s, hors-série : %s", nom, e.__class__.__name__)
    numeros = sorted(_tomes_de(nom))
    en_lecture = []
    with app.test_request_context():                       # _sommaire_du_tome lit le rôle de la session
        for i, t in enumerate(numeros, 1):
            progression(f"{nom} : tome {t} ({i}/{len(numeros)})")
            try:
                d = tomes.details_tome(nom, t)
                _sommaire_du_tome(nom, t, d, fond=True)    # lance la lecture du sommaire si elle est utile
                if sommaire.etat(nom, t).get("en_cours"):
                    en_lecture.append(t)
                _attendre_lectures(sommaire, nom, en_lecture, sommaire.SIMULTANES - 1)   # un tome par cœur libre
            except Exception as e:
                logger.info("Préparation de %s tome %s : %s", nom, t, e.__class__.__name__)
        _attendre_lectures(sommaire, nom, en_lecture, 0)
    # Les ISBN imprimés dans les pages : dernier recours, seulement si Internet a répondu partout et ne les a pas
    attente = bool(bilans.get("notices") and bilans["notices"].extra.get("attente"))
    reste = [] if attente else _tomes_sans_isbn(nom, auto=True)
    if reste and sommaire.disponible() and not (_ISBN_SERIE.get(nom) or {}).get("en_cours"):
        progression(f"{nom} : ISBN lus dans les pages ({len(reste)} tome(s))")
        _lire_isbn_pages(nom, reste)
    try:
        _detecter_edition(nom)
    except Exception as e:
        logger.info("Détection de l'édition de %s : %s", nom, e.__class__.__name__)
    reprises = [b.prochain for b in bilans.values() if b.prochain]            # un service à attendre, ou une recherche sans résultat à retenter
    return min(reprises) if reprises else None


def _edition_dans_les_fichiers(nom):
    """(édition, nombre de tomes) d'après les noms DANS les fichiers des tomes (« 20th Century Boys - Perfect Edition - T10
    (URASAWA) [Scan SP-1920]/0001.jpg ») : l'archive d'origine ne le dit pas, mais le dossier d'images à l'intérieur, si.
    Seuls comptent les tomes dont ce dossier porte le nom de la série (« 21st Century Boys » n'est pas le même manga)."""
    import edition
    editions, numeros, nb = {}, [], 0
    simple = tomes._simple(nom)
    for e in _entrees(_scan().get(nom) or []):
        if e.get("tome") is None or e.get("key") != e.get("path") or not str(e["path"]).lower().endswith(".cbz"):
            continue
        try:
            with zipfile.ZipFile(MANGA_DIR / e["path"]) as z:
                noms = z.namelist()[:8]
        except (OSError, zipfile.BadZipFile):
            continue
        haut = next((n.split("/", 1)[0] for n in noms if "/" in n), "")
        ed = edition.edition_du_titre(haut) if haut else None
        if not haut or (simple not in tomes._simple(haut) and not ed):
            continue                                      # autre manga, sans mention d'édition
        nb += 1
        if ed:                                            # « 21st Century Boys - Perfect Edition » rangé dans la série : un tome de plus
            editions[ed] = editions.get(ed, 0) + 1
        numeros.append(int(e["tome"]))
    if not editions or sum(editions.values()) * 2 < nb:          # la plupart des tomes doivent le dire
        return None, None
    return max(editions, key=editions.get), max(numeros)


def _detecter_edition(nom):
    """Édition qui regroupe les tomes autrement que Wikipédia (Perfect Édition en 11 tomes au lieu de 22…) alors que le nom
    de l'archive ne le dit pas. Deux preuves, dans l'ordre : (1) le nom du dossier d'images DANS chaque tome (« … Perfect
    Edition - T10 … ») ; (2) des chapitres de plusieurs tomes standard consécutifs dans le sommaire d'un même tome.
    Le nombre de tomes de l'édition devient celui des tomes de la série ; les chapitres affichés sont alors ceux du sommaire
    du tome, pas ceux de Wikipédia. Jamais si le nombre de tomes a été indiqué (à la main ou par le nom de l'archive) ;
    une détection d'avant est recalculée."""
    import edition
    infos = edition.lire(MANGA_DIR / nom)
    if infos.get("volumes_manuel") or (infos.get("volumes_attendus") and not infos.get("edition_detectee")):
        return None
    present = _tomes_de(nom)
    if not present:
        return None
    ed, n = _edition_dans_les_fichiers(nom)
    preuve = {"source": "noms dans les fichiers", "exemple": f"les tomes s'appellent « … {ed} … »"} if ed else None
    if not ed:
        t = (tomes._charger(nom) or {}).get("titres_tomes") or {}
        standard = {}
        for k, d in (t.get("details") or {}).items():
            nums = [float(m.group(1).replace(",", ".")) for c in d.get("chapitres", []) for m in [re.match(r"^(\d+(?:[.,]\d)?)\.", c)] if m]
            if nums:
                standard[k] = nums
        r = edition.detecter_regroupement(infos.get("sommaires") or {}, standard)
        if r:
            ed, n = "Édition regroupée (repérée d'après les chapitres)", max(present)
            preuve = {"source": "chapitres du sommaire", "tomes": r["tomes"],
                      "exemple": f"le tome {r['exemple'][0]} contient des chapitres des tomes standard {', '.join(r['exemple'][1])}"}
    if not ed:
        if infos.pop("edition_detectee", None) is not None:           # détection d'avant qui ne tient plus : oubliée
            infos.pop("volumes_attendus", None)
            if infos.get("edition", "").startswith("Édition regroupée"):
                infos.pop("edition", None)
            edition.ecrire(MANGA_DIR / nom, infos)
        return None
    if infos.get("volumes_attendus") == n and infos.get("edition") == ed:
        return n
    infos["volumes_attendus"], infos["edition"] = n, ed
    infos["edition_detectee"] = dict(preuve, date=time.strftime("%Y-%m-%d"))
    edition.ecrire(MANGA_DIR / nom, infos)
    logger.info("Édition de « %s » : %s en %d tomes (%s)", nom, ed, n, preuve["exemple"])
    return n


@app.route("/api/edition/volumes", methods=["POST"])
def api_edition_volumes():
    """Indiquer à la main le nombre de tomes de SON édition (Perfect, deluxe…) ; vide = laisser l'appli le détecter."""
    import edition
    body = request.get_json(silent=True) or {}
    name = str(body.get("series", ""))
    if name not in _scan() or name == "(Sans série)":
        return jsonify({"ok": False, "error": "Série introuvable"}), 404
    d = edition.lire(MANGA_DIR / name)
    brut = str(body.get("volumes", "")).strip()
    if brut:
        if not brut.isdigit() or not 1 <= int(brut) <= 999:
            return jsonify({"ok": False, "error": "Indique un nombre de tomes (ex. 11)."}), 400
        d["volumes_attendus"], d["volumes_manuel"] = int(brut), True
        d["edition"] = d.get("edition") or f"Édition en {int(brut)} tomes (indiquée à la main)"
        msg = f"Ton édition compte {int(brut)} tomes."
    else:                                                 # retour à la détection : ce qui venait de là ou de la main est oublié
        for k in ("volumes_manuel", "edition_detectee", "volumes_attendus"):
            d.pop(k, None)
        if d.get("edition", "").startswith(("Édition en ", "Édition regroupée")):
            d.pop("edition", None)
        msg = "Nombre de tomes : détection automatique."
    edition.ecrire(MANGA_DIR / name, d)
    _CACHE_EDITION.pop(name, None)
    return jsonify({"ok": True, "message": msg})


# Pendant les tests, la préparation de fond ne fait rien : un fil lancé par un test écrirait dans le dossier du test suivant.
prechauffage.configurer(DATA_DIR / "prechauffage.json", _series_preparables, _signature_serie,
                        (lambda nom, progression: None) if reseau.EN_TEST else _preparer_serie, lambda: _travaux_en_cours())


@app.route("/api/prechauffage", methods=["GET", "POST"])
def api_prechauffage():
    """GET : avancement de la préparation. POST : « 🚀 Préparer toute la bibliothèque » (lancé en arrière-plan)."""
    if request.method == "POST":
        n = prechauffage.tout(forcer=True)
        return jsonify({"ok": True, "message": f"Préparation lancée pour {n} série(s)." if n else "Une préparation est déjà en cours."})
    return jsonify(prechauffage.etat())


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": APP_VERSION})


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", "5002"))
    print(f"MouFlanga {APP_VERSION} : http://0.0.0.0:{port}", file=sys.stderr)
    import notifier
    redemarrage.verifier(BASE_DIR, "MouFlanga", DATA_DIR / "mouflanga.log", lambda t: notifier.envoyer(t))
    threading.Thread(target=_boucle_generiques, daemon=True).start()
    threading.Thread(target=_boucle_parasites, daemon=True).start()
    threading.Thread(target=_boucle_relecture_sommaires, daemon=True, name="relecture-sommaires").start()
    threading.Thread(target=_boucle_equipes, daemon=True).start()
    threading.Thread(target=suivi.boucle, args=(torrents.chercher, _infos_suivi, lambda t: notifier.envoyer(t),
                                                lambda: os.getenv("APP_URL", "").strip(), torrents.configure,
                                                _lancer_torrent, lecture_pages.lire_en_fond), daemon=True).start()
    threading.Thread(target=suivi.boucle_flux, args=(torrents.flux, _verifier_serie, torrents.configure, torrents.deja_pris),
                     daemon=True, name="flux-nouveautes").start()      # 📡 nouveautés de Prowlarr toutes les 15 minutes
    threading.Timer(150, suivi.nettoyer, args=(_infos_suivi,)).start()   # propositions en doublon ou périmées, une fois au démarrage
    suivi.nettoyer_liens()                         # anciennes propositions : plus de lien de Prowlarr (il contient sa clé)
    threading.Timer(90, lecture_pages.rattrapage).start()      # pages des propositions déjà gardées, lues sans bousculer le démarrage
    threading.Thread(target=torrents.surveiller, args=(_importer_torrent, lambda t: notifier.envoyer(t), MANGA_DIR), daemon=True).start()
    threading.Thread(target=demandes._boucle_rappels, args=(lambda t: notifier.envoyer(t), lambda: os.getenv("APP_URL", "").strip()),
                     daemon=True).start()
    def _chauffer_liste():                         # la 1re ouverture de la liste ne recalcule plus tout : chapitres préparés au démarrage
        try:
            for _nom, _fichiers in _scan().items():
                _entrees(_fichiers)
        except Exception as e:
            logger.info("Préparation de la liste : %s", e)
    threading.Thread(target=_chauffer_liste, daemon=True).start()
    prechauffage.surveiller()                      # séries nouvelles ou modifiées : préparées toutes seules
    import notes
    threading.Thread(target=notes.boucle, args=(lambda: [s for s in _scan() if s != "(Sans série)"], _identifiants_note),
                     daemon=True).start()          # notes des séries : une mise à jour par jour, en arrière-plan
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
