#!/usr/bin/env python3
"""
MouFlanga · bibliothèque et lecteur de BD / mangas (fichiers .cbz et .cbr) pour la suite MouFl.

- Parcourt le dossier des mangas : un sous-dossier = une série, un fichier = un chapitre (ou un tome)
- Lecteur intégré : une page à la fois ou défilement, sens manga ou occidental, reprise là où tu t'es arrêté
- Suivi de lecture (chapitres lus, page en cours), enregistré sur le serveur
- Connexion, Journal de diagnostic et ⚙️ Réglages identiques aux autres applis
"""
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
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
_SECRETS_FILE = DATA_DIR / "secrets.env"

try:
    from dotenv import load_dotenv
    for _f in (BASE_DIR / ".env", _SECRETS_FILE):
        if _f.exists():
            load_dotenv(_f, override=True)
except ImportError:
    pass  # python-dotenv absent : variables d'environnement du système seulement

import archives
import tomes
import tomes_cbz
import importer
import diag
import japscan_scraper

BASE_VERSION = "1.0"


def get_version():
    """Version = base manuelle + nombre de commits (numéro de déploiement) + hash court."""
    try:
        import subprocess
        cwd = str(BASE_DIR)
        count = subprocess.check_output(["git", "rev-list", "--count", "HEAD"], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
        short = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
        return f"v{BASE_VERSION}.{count} ({short})"
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

PROGRESS_FILE = DATA_DIR / "progress.json"
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
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _safe_path(rel):
    """Chemin relatif (donné par la page) -> chemin réel, uniquement À L'INTÉRIEUR du dossier des mangas."""
    root = MANGA_DIR.resolve()
    try:
        full = (root / rel).resolve()
        full.relative_to(root)
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


def _scan():
    """{série: [fichiers]} — chaque sous-dossier est une série ; les fichiers posés à la racine forment « (Sans série) »."""
    series = {}
    if not MANGA_DIR.is_dir():
        return series
    loose = []
    try:
        entries = sorted(MANGA_DIR.iterdir(), key=lambda p: archives.natural_key(p.name))
    except OSError:
        return series
    for entry in entries:
        try:
            if entry.name.startswith((".", "@", "#")):
                continue
            if entry.is_dir():
                files = []
                for dirpath, dirnames, filenames in os.walk(entry, onerror=lambda e: None):
                    dirnames[:] = [d for d in dirnames if not d.startswith((".", "@"))]
                    files += [Path(dirpath) / n for n in filenames if _is_archive(Path(n)) or _a_importer(Path(dirpath) / n)]
                if files:
                    series[entry.name] = sorted(files, key=lambda p: archives.natural_key(p.relative_to(entry)))
            elif _is_archive(entry) and not importer.est_lot(entry):     # les .rar/.zip/.7z vont dans la page d'import
                loose.append(entry)
        except OSError:
            continue
    if loose:
        series["(Sans série)"] = loose
    return series


def _rel(p: Path):
    return str(p.relative_to(MANGA_DIR))


def _numero_tome(nom):
    """Numéro de tome d'après un nom de fichier (« Gintama T01 (…) », « Toriko.Tome.38 », « Vol. 3 ») ; None pour un chapitre."""
    return importer.numero_tome(nom)


def _plage_chapitres(serie, tome):
    """« chapitres 1 à 8 » pour un tome complet, si la répartition de la série est déjà connue (sans aller sur Internet)."""
    info = tomes._charger(serie)
    if not info or not info.get("tomes"):
        return [], ""
    nums = sorted(n for n, t in info["tomes"].items() if t == tome)
    if not nums:
        return [], ""
    return nums, (f"chapitre {nums[0]:g}" if len(nums) == 1 else f"chapitres {nums[0]:g} à {nums[-1]:g}")


def _entrees(files):
    """Chapitres d'une série, dans l'ordre de lecture.
    Fichier ordinaire = un chapitre (clé : son chemin). Fichier de tome = plusieurs chapitres (clé : « #12 »),
    repérés par leur première page et leur nombre de pages dans le fichier."""
    out = []
    for f in files:
        rel = _rel(f)
        try:
            taille = f.stat().st_size
        except OSError:
            taille = 0
        if _a_importer(f):
            out.append({"key": rel, "path": rel, "title": f"📦 {f.name}", "num": None, "groupe": None, "debut": 0,
                        "nb": None, "a_importer": True, "size_mb": round(taille / 1048576, 1)})
            continue
        info = tomes_cbz.lire_info(f) if f.suffix.lower() == ".cbz" else None
        if info is None:
            titre = _title_of(f)
            entree = {"key": rel, "path": rel, "title": titre, "num": _numero_chapitre(titre), "groupe": None,
                      "debut": 0, "nb": None, "size_mb": round(taille / 1048576, 1)}
            tome = _numero_tome(titre)
            if tome is not None:
                # Tome complet (un fichier = un tome) : affiché « Tome 03 · chapitres 17 à 25 »
                couverts, plage = _plage_chapitres(f.relative_to(MANGA_DIR).parts[0], tome)
                entree.update(num=None, tome=tome, couverts=couverts,
                              title=tomes_cbz.dossier_tome(tome) + (f" · {plage}" if plage else ""))
            out.append(entree)
            continue
        try:
            chapitres = tomes_cbz.chapitres(f)
        except archives.ArchiveError:
            continue
        total = sum(c["nb"] for c in chapitres) or 1
        for c in chapitres:
            out.append({"key": f"#{c['num']:g}", "path": rel, "num": c["num"],
                        "title": f"Chapitre {c['num']:g}" + (f" : {c['titre']}" if c["titre"] else ""),
                        "groupe": tomes_cbz.dossier_tome(info.get("tome")), "debut": c["debut"], "nb": c["nb"],
                        "size_mb": round(taille * c["nb"] / total / 1048576, 1)})
    if any(e["groupe"] for e in out):
        out.sort(key=lambda e: (e["num"] is None, e["num"] or 0))
    return out


def _title_of(p: Path):
    return p.stem.replace("_", " ").strip()


# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", version=APP_VERSION)


@app.route("/lire")
def reader():
    return render_template("lecteur.html", version=APP_VERSION)


# ----------------------------------------------------------------------------
# Bibliothèque
# ----------------------------------------------------------------------------

# ---------------------------------------------------------------- Fini / en cours / incomplet

_STATUTS = {"en_cours": False, "dernier": 0.0}


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
    vol = st.get("volumes") or max([t for t in (info.get("tomes") or {}).values() if t is not None] or [0]) or None
    chap = st.get("chapitres") or max(info.get("tomes") or {0: None}) or None
    if statut in ("RELEASING", "NOT_YET_RELEASED"):
        return "en_cours", "En cours de parution" + (f" ({vol} tomes sortis)" if vol else "") + "."
    if statut == "HIATUS":
        return "pause", "Parution en pause."
    manquants = []
    if vol and tomes_locaux:
        manquants = [t for t in range(1, vol + 1) if t not in tomes_locaux]
        complet = not manquants
    elif chap and chapitres:
        complet = max(chapitres) >= chap and not _manquants([], chapitres)[0]
    else:
        complet = False
    total = f"{vol} tomes" if vol else (f"{chap} chapitres" if chap else "")
    debut = "Série arrêtée" if statut == "CANCELLED" else "Série terminée"
    if complet:
        return "fini", f"{debut}{f' ({total})' if total else ''} : tout est là ✅"
    if manquants:
        txt = ", ".join(_plages(manquants))
        return "incomplet", f"{debut} ({total}) : il te manque {'le tome' if len(manquants) == 1 else 'les tomes'} {txt}."
    return "incomplet", f"{debut}{f' ({total})' if total else ''} : il manque des chapitres."


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
                st = (tomes._charger(name) or {}).get("statut_officiel") or {}
                if st and time.time() - st.get("date", 0) < tomes.STATUT_DUREE:
                    continue
                tomes.statut_officiel(name, tome_max)
                time.sleep(1.5)
        except Exception as e:
            logger.warning("Statuts officiels : %s", e)
        finally:
            _STATUTS["en_cours"] = False
    threading.Thread(target=travail, daemon=True).start()


@app.route("/api/library")
def api_library():
    if not MANGA_DIR.is_dir():
        return jsonify({"error": f"Dossier des mangas introuvable : {MANGA_DIR} (le partage est-il monté ? voir ⚙️ Réglages)", "series": []}), 200
    _organiser_auto()
    progress = _read_json(PROGRESS_FILE, {})
    out, a_remplir = [], []
    for name, files in _scan().items():
        p = progress.get(name, {})
        read = set(p.get("read", []))
        total_size = 0
        newest = 0
        for f in files:
            try:
                st = f.stat()
                total_size += st.st_size
                newest = max(newest, st.st_mtime)
            except OSError:
                pass
        entrees = _entrees(files)
        etat, _ = _etat_serie(name, entrees) if name != "(Sans série)" else (None, "")
        a_remplir.append((name, max([e["tome"] for e in entrees if e.get("tome") is not None] +
                                    [int(e["groupe"].split()[1]) for e in entrees if (e.get("groupe") or "").startswith("Tome ")] or [0]) or None))
        out.append({
            "etat": etat,
            "id": name, "title": name, "chapters": len(entrees),
            "unite": "tome" if entrees and sum(e.get("tome") is not None for e in entrees) * 2 >= len(entrees) else "chapitre",
            "read": len([e for e in entrees if e["key"] in read]),
            "size_mb": round(total_size / 1048576, 1),
            "last_read": p.get("last", ""), "added": newest,
            "cover": f"/api/cover?id={_q(name)}&v={int(max(newest, _couverture_mtime(name)))}",
        })
    _remplir_statuts([x for x in a_remplir if x[0] != "(Sans série)"])
    try:
        racine = sum(1 for f in MANGA_DIR.iterdir() if f.is_file() and importer.est_lot(f) and not f.name.startswith("."))
    except OSError:
        racine = 0
    return jsonify({"series": out, "a_importer": racine, "import_en_cours": _FILE_IMPORT["en_cours"]})


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


@app.route("/api/series")
def api_series():
    name = request.args.get("id", "")
    files = _scan().get(name)
    if files is None:
        return jsonify({"error": "Série introuvable"}), 404
    p = _read_json(PROGRESS_FILE, {}).get(name, {})
    read = set(p.get("read", []))
    chapters = [{**e, "read": e["key"] in read} for e in _entrees(files)]
    nums_tomes = [c.get("tome") for c in chapters if c.get("tome") is not None]
    if nums_tomes and len(nums_tomes) >= len(chapters) / 2:          # série en tomes complets
        trous, premier, dernier = _manquants([], nums_tomes)
        type_manquants = "tomes"
    else:
        trous, premier, dernier = _manquants([c["title"] for c in chapters])
        type_manquants = "chapitres"
    en_tomes = any(c["groupe"] for c in chapters)
    etat, etat_texte = _etat_serie(name, chapters) if name != "(Sans série)" else (None, "")
    st = (tomes._charger(name) or {}).get("statut_officiel") or {}
    a_ranger = name != "(Sans série)" and any(not c["groupe"] and c["num"] is not None for c in chapters)
    return jsonify({"id": name, "title": name, "chapters": chapters,
                    "current": p.get("current", ""), "page": p.get("page", 0),
                    "rar": archives.rar_available(),
                    "en_tomes": en_tomes, "a_ranger": a_ranger, "rangement": _etat_rangement(name),
                    "etat": etat, "etat_texte": etat_texte, "etat_source": st.get("titre"),
                    "manquants": trous, "premier": premier, "dernier": dernier, "type_manquants": type_manquants,
                    "organiser": _plan_organiser(name, files) if name != "(Sans série)" else None,
                    "cover_perso": name != "(Sans série)" and (MANGA_DIR / name / COUVERTURE_PERSO).is_file(),
                    "cover_v": int(_couverture_mtime(name)),
                    "moufloster": os.getenv("MOUFLOSTER_URL", "").strip(),
                    "moufloster_externe": os.getenv("MOUFLOSTER_URL_EXTERNE", "").strip()})


@app.route("/api/cover")
def api_cover():
    name = request.args.get("id", "")
    files = _scan().get(name)
    if not files:
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
    first, debut = MANGA_DIR / premiere["path"], premiere["debut"]
    try:
        st = first.stat()
        key = hashlib.sha1(f"{first}|{st.st_mtime_ns}|{st.st_size}|{debut}".encode()).hexdigest()[:20]
        cached = COVER_DIR / f"{key}.jpg"
        if not cached.is_file():
            from PIL import Image
            names = archives.pages(first)
            if not names:
                return Response(status=404)
            data, _ = archives.read_page(first, debut)
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.thumbnail((360, 540))
            COVER_DIR.mkdir(parents=True, exist_ok=True)
            tmp = cached.with_suffix(".tmp")
            img.save(tmp, format="JPEG", quality=82)
            os.replace(tmp, cached)
        return send_file(cached, max_age=86400)
    except archives.ArchiveError as e:
        logger.warning("Couverture impossible pour %s : %s", name, e)
    except Exception as e:  # image abîmée, format exotique...
        logger.warning("Couverture impossible pour %s : %s: %s", name, e.__class__.__name__, e)
    return Response(status=404)


@app.route("/api/cover/choisir", methods=["POST"])
def api_cover_choisir():
    """Couverture choisie par l'utilisateur : image envoyée depuis le téléphone, enregistrée en cover.jpg
    dans le dossier de la série (l'ancienne cover.jpg va à la corbeille)."""
    rep, code = _enregistrer_couverture(request.form.get("id", ""), request.files.get("image"))
    return jsonify(rep), code


def _enregistrer_couverture(name, envoi):
    """Enregistre l'image envoyée (fichier de formulaire) comme couverture de la série. Renvoie (réponse, code)."""
    if name not in _scan() or name == "(Sans série)":
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
    if name not in _scan() or name == "(Sans série)":
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
        data = _read_json(PROGRESS_FILE, {})
        p = data.setdefault(series, {})
        p["current"], p["page"], p["last"] = rel, page, datetime.now().strftime("%Y-%m-%d %H:%M")
        read = set(p.get("read", []))
        if body.get("finished"):
            read.add(rel)
        p["read"] = sorted(read)
        _write_json(PROGRESS_FILE, data)
    return jsonify({"ok": True})


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
        data = _read_json(PROGRESS_FILE, {})
        p = data.setdefault(series, {})
        read = set(p.get("read", []))
        for t in targets:
            if t in valid:
                (read.add if value else read.discard)(t)
        p["read"] = sorted(read)
        if not value and body.get("all"):
            p.pop("current", None)
            p["page"] = 0
        _write_json(PROGRESS_FILE, data)
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
        if entree["groupe"]:
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
        cibles = [] if entree["groupe"] else [MANGA_DIR / entree["path"]]
    try:
        for c in cibles:
            _vers_corbeille(c)
    except OSError as e:
        logger.warning("Suppression impossible dans %s : %s", series, e)
        return jsonify({"ok": False, "error": f"Suppression impossible : {e.strerror or e}"}), 500
    logger.info("Mis à la corbeille : %s (%d fichier(s))", series if body.get("all") else next(iter(retires)), len(retires))

    with _progress_lock:
        data = _read_json(PROGRESS_FILE, {})
        p = data.get(series)
        if p is not None:
            if body.get("all"):
                data.pop(series)
            else:
                p["read"] = [r for r in p.get("read", []) if r not in retires]
                if p.get("current") in retires:
                    p.pop("current", None)
                    p["page"] = 0
            _write_json(PROGRESS_FILE, data)
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
        data = _read_json(PROGRESS_FILE, {})
        if anciens[0].name in data:
            p = data.pop(anciens[0].name)
            avant = anciens[0].name + "/"
            p["read"] = [nom + "/" + r[len(avant):] if r.startswith(avant) else r for r in p.get("read", [])]
            if str(p.get("current", "")).startswith(avant):
                p["current"] = nom + "/" + p["current"][len(avant):]
            data[nom] = p
            _write_json(PROGRESS_FILE, data)
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
                num = _numero_chapitre(_title_of(f))
                if num is not None:
                    par_tome.setdefault(tomes.tome_de(num, info), []).append((num, f))
            elif info_f.get("tome") is None:
                for c in tomes_cbz.chapitres(f):
                    t = tomes.tome_de(c["num"], info)
                    if t is not None:
                        depuis_hors.setdefault(f, []).append((t, c))
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
                data = _read_json(PROGRESS_FILE, {})
                p = data.get(name)
                if p:
                    p["read"] = sorted({renommes.get(r, r) for r in p.get("read", [])})
                    if p.get("current") in renommes:
                        p["current"], p["page"] = renommes[p["current"]], p.get("page", 0)
                    _write_json(PROGRESS_FILE, data)
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
_BRUIT = re.compile(r"\b(?:int[ée]grale?|complete|complet|fr|vf|vostfr|cbz|cbr|e-?books?|officiels?|digital|scans?|manga)\b", re.I)


_PARTICULES = {"no", "wa", "ga", "ni", "to", "wo", "de", "na", "e", "of", "the", "a", "an", "and", "in", "on", "de", "du", "des", "la", "le", "les", "et"}
CHOIX = DATA_DIR / "organiser-choix.json"


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
        garde = set(c["choisi"].lower().split())
        for mot in set(c["propose"].lower().split()) - garde:
            retires[mot] = retires.get(mot, 0) + 1
    mots = [m for m in propose.split(" ") if retires.get(m.lower(), 0) < 1]
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
    propose = japscan_scraper.nom_sur(_appris(name, _majuscules(propose)))
    tomes_fichiers, a_deplacer, chapitres = [], 0, 0
    for f in files:
        if tomes_cbz.lire_info(f) is not None:
            continue
        t = _numero_tome(f.stem)
        if t is not None:
            tomes_fichiers.append(t)
            attendu = Path(tomes_cbz.dossier_tome(t)) / f"{propose} - {tomes_cbz.dossier_tome(t)}{f.suffix.lower()}"
            if f.relative_to(MANGA_DIR / name) != attendu:
                a_deplacer += 1
        elif _numero_chapitre(f.stem) is not None:
            chapitres += 1
    if propose == name and not a_deplacer and not chapitres and not lots:
        return None
    return {"nom": propose, "tomes": len(tomes_fichiers), "a_deplacer": a_deplacer, "chapitres": chapitres,
            "archives": sum(1 for f in lots if f.suffix.lower() != ".pdf"), "pdf": sum(1 for f in lots if f.suffix.lower() == ".pdf"),
            "taille_go": round(sum(f.stat().st_size for f in lots) / 1073741824, 1),
            "premier_tome": min(tomes_fichiers) if tomes_fichiers else None,
            "dernier_tome": max(tomes_fichiers) if tomes_fichiers else None}


def _organiser(name, nouveau):
    """Renomme la série et range ses fichiers : tomes complets dans « Tome NN/<Série> - Tome NN.cbz » (simples
    déplacements), chapitres regroupés en tomes ensuite. La progression de lecture suit. Renvoie le nouveau nom."""
    files = _scan().get(name) or []
    ancien_dossier, dossier = MANGA_DIR / name, MANGA_DIR / nouveau
    if nouveau != name and dossier.exists() and not dossier.is_dir():
        raise ValueError(f"« {nouveau} » existe déjà et n'est pas un dossier")
    deplaces = {}
    for f in files:
        if _a_importer(f) or tomes_cbz.lire_info(f) is not None:
            cible = dossier / f.relative_to(ancien_dossier)
        else:
            t = _numero_tome(f.stem)
            if t is None:
                cible = dossier / f.relative_to(ancien_dossier)       # chapitres et fichiers inconnus : même place
            else:
                cible = dossier / tomes_cbz.dossier_tome(t) / f"{nouveau} - {tomes_cbz.dossier_tome(t)}{f.suffix.lower()}"
        if cible == f:
            continue
        if cible.exists():
            logger.warning("Organiser : %s existe déjà, %s laissé en place", cible, f.name)
            continue
        cible.parent.mkdir(parents=True, exist_ok=True)
        f.rename(cible)
        deplaces[_rel(f)] = _rel(cible)
    # Le reste du dossier (couverture, images…) suit, puis les dossiers vidés disparaissent
    if nouveau != name and ancien_dossier.is_dir():
        for reste in sorted(ancien_dossier.rglob("*"), key=lambda p: -len(p.parts)):
            if reste.is_file():
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
    with _progress_lock:
        data = _read_json(PROGRESS_FILE, {})
        p = data.pop(name, None) if nouveau != name else data.get(name)
        if p is not None:
            conv = lambda r: deplaces.get(r, r)
            p["read"] = sorted({conv(r) for r in p.get("read", [])})
            if p.get("current"):
                p["current"] = conv(p["current"])
            data[nouveau] = p
            _write_json(PROGRESS_FILE, data)
    logger.info("Série organisée : « %s » → « %s » (%d fichier(s) déplacé(s))", name, nouveau, len(deplaces))
    return nouveau


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
    nouveau = japscan_scraper.nom_sur(str(body.get("nom", "")).strip())
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


def _lancer_import(nouveau, attendre=False, lots_forces=None):
    """Archives de tomes et PDF convertis, puis chapitres regroupés en tomes : en arrière-plan,
    ou tout de suite si « attendre » (file d'import). « lots_forces » : archives à extraire quelle que soit leur taille.
    Renvoie le message de fin quand « attendre »."""
    lots_forces = [Path(x) for x in (lots_forces or [])]
    files = _scan().get(nouveau) or []
    lots = [f for f in files if _a_importer(f) or f in lots_forces]
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
                _vers_corbeille(lot)                     # l'original est gardé 30 jours
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
        etat["message"] = "Recherche des tomes…"
        try:
            info = tomes.chercher(nouveau, forcer=True)
            msg = "✅ Série organisée" + (f" : {crees} tome(s) importé(s)" if lots else "")
            if info:                                  # chapitres séparés ou « hors tome » : rangés d'après Internet
                n = _ranger_en_tomes(nouveau, info, garder_en_cours=True)
                if n:
                    msg += f" ; {n} chapitre(s) rangé(s) en tomes"
            msg += f" (tomes d'après {info['source']})." if info else "."
        except Exception as e:
            msg = f"Série organisée, mais rangement des chapitres impossible : {e}"
        if erreurs:
            msg += " ⚠ Non importé : " + " · ".join(erreurs)
        etat.update(en_cours=False, message=msg)
        return msg
    if attendre:
        return travail()
    threading.Thread(target=travail, daemon=True).start()


# ---------------------------------------------------------------- Archives déposées à la racine

_FILE_IMPORT = {"en_cours": None, "attente": [], "faits": [], "erreurs": [], "message": ""}
_FILE_VERROU = threading.Lock()
_NOMBRE_TOMES = re.compile(r"\b(?:int[ée]grale\s*)?\d+\s*tomes?\b|\b(?:tomes?|t)\s*\d+\s*(?:[-àa]|a)\s*\d+\b|\bfinal\b", re.I)


def _cle_nom(nom):
    import unicodedata
    t = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", t)


def _nom_depuis_archive(nom_fichier, existantes):
    """« jojo's bizarre adventure tome 13 a 28 » → « Jojo's Bizarre Adventure » ; une série déjà présente garde son nom."""
    stem = Path(nom_fichier).stem
    t = stem.replace("_", " ")
    if re.search(r"[A-Za-z]\.[A-Za-z]", t) and t.count(" ") <= 1:     # « Docteur.Slump », « Magi.the.labyrinth.of.magic »
        t = t.replace(".", " ")
    t = _NOMBRE_TOMES.sub(" ", _CROCHETS.sub(" ", t))
    t = _nettoyer_nom(t) or stem
    if t == t.lower() or (t[:1].isupper() and t[1:] == t[1:].lower() and " " in t):
        t = _majuscules(t.lower())
    t = japscan_scraper.nom_sur(_appris(nom_fichier, t))
    for e in existantes:                                   # série déjà dans la bibliothèque (ex. Gamaran)
        if _cle_nom(e) == _cle_nom(t):
            return e
    return t


def _archives_racine():
    """Archives (.rar/.zip/.7z) posées directement dans le dossier des mangas, regroupées par série proposée."""
    try:
        fichiers = sorted((f for f in MANGA_DIR.iterdir() if f.is_file() and importer.est_lot(f) and not f.name.startswith(".")),
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
        nom = japscan_scraper.nom_sur(g["nom"])
        try:
            dossier = MANGA_DIR / nom
            dossier.mkdir(exist_ok=True)
            deplaces = []
            for a in g["archives"]:
                src = MANGA_DIR / Path(a).name
                if not src.is_file():
                    continue
                cible = dossier / src.name
                src.rename(cible)
                deplaces.append(cible)
                _noter_choix(src.name, g.get("propose", nom), nom)
            msg = _lancer_import(nom, attendre=True, lots_forces=deplaces)
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
            nom = japscan_scraper.nom_sur(str(g.get("nom", "")).strip())
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


@app.route("/importer")
def page_importer():
    return render_template("importer.html", version=APP_VERSION)


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

    def travail():
        etat = _RANGEMENTS[name]
        try:
            info = tomes.chercher(name, forcer=True)
            if not info:
                etat.update(en_cours=False, message="Aucune source (Wikipédia, MangaDex) ne connaît les tomes de cette série : les chapitres restent un fichier chacun.")
                return
            n = _ranger_en_tomes(name, info, garder_en_cours=True)
            etat.update(en_cours=False, message=f"✅ {n} chapitre(s) rangé(s) en tomes (d'après {info['source']})." if n
                        else f"Déjà rangée (d'après {info['source']}).")
        except Exception as e:
            etat.update(en_cours=False, message=f"Rangement impossible : {e}")
    threading.Thread(target=travail, daemon=True).start()
    return jsonify({"ok": True, "message": "Recherche des tomes…"})


@app.route("/api/japscan/list")
def japscan_list():
    """Liste les mangas disponibles sur Japscan (gardée en mémoire : un rechargement de la page est instantané)."""
    forcer = request.args.get("rafraichir") == "1"
    try:
        with _LISTE_VERROU:
            if not forcer:
                try:
                    cache = json.loads(LISTE_CACHE.read_text(encoding="utf-8"))
                    age = time.time() - cache.get("date", 0)
                    if cache.get("mangas") and age < LISTE_DUREE:
                        mangas = japscan_scraper.regrouper_series(cache["mangas"])
                        return jsonify({"ok": True, "mangas": mangas, "cache_minutes": int(age // 60)})
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
        return jsonify({"ok": True, "mangas": japscan_scraper.regrouper_series(mangas), "cache_minutes": 0})
    except Exception as e:
        logger.error(f"Erreur liste Japscan: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


def _marquer_deja(chapters, titre):
    """Ajoute « deja » (déjà dans la bibliothèque) à chaque chapitre, d'après les fichiers du dossier de la série."""
    if not titre:
        return chapters
    deja = _deja_telecharges(titre)
    return [{**c, "deja": japscan_scraper._numero(c) in deja} for c in chapters]


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
    lignes += ["", "--- Noms de domaine (DNS du serveur) ---"] + _diag_dns()
    lignes += ["", "--- Carte graphique (accès du serveur) ---"] + _diag_gpu()
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


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": APP_VERSION})


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", "5002"))
    print(f"MouFlanga {APP_VERSION} : http://0.0.0.0:{port}", file=sys.stderr)
    import notifier
    redemarrage.verifier(BASE_DIR, "MouFlanga", DATA_DIR / "mouflanga.log", lambda t: notifier.envoyer(t))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
