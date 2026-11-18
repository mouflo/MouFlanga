"""
✂️ Rognage à la main (refait le 18/11/2026).

Un cadre par page, de taille libre (et un petit angle), réglé sur la page D'ORIGINE. À l'application, chaque cadre est agrandi ou réduit sans
déformation pour tenir dans la taille finale du tome (W × H, la même pour toutes les pages ; une double page : 2W × H), centré, et ce qui manque
autour est complété avec le ton du papier : toutes les pages du tome ont exactement la même taille et la même position.

Les pages d'origine sont gardées dans <mangas>/.rognage/<série>/<fichier> dès la première application, et le cadre de chaque page reste
enregistré (data/rognage.json) : on peut toujours revenir sur une page, même pour agrandir le cadre, sans rien perdre. Une page dont le cadre et
la taille finale n'ont pas changé depuis la dernière application est recopiée telle quelle, octet pour octet : seules les pages modifiées sont
réécrites. Si une page du tome est changée par autre chose (couverture remplacée…), elle devient la nouvelle page d'origine de ce numéro.
"""
import hashlib
import io
import json
import os
import shutil
import threading
import zipfile
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import archives

DOSSIER = ".rognage"            # dans le dossier des mangas : ignoré par la bibliothèque (commence par un point)
MINI = 20                       # px : plus petit cadre accepté
RETOUCHES = ("debruit", "trames", "papier", "noirs", "taches", "lisser", "nettete", "ia")   # ✨ retouches refaites sur une page réécrite (jamais ce qui change sa taille)
_VERROU = threading.RLock()
_TAILLES = {}


def est_double(t) -> bool:
    return t[0] > 1.1 * t[1]


def _mediane(v):
    v = sorted(v)
    return v[len(v) // 2] if v else 0


def empreinte(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


# --- Rendu d'une page --------------------------------------------------------------------------------------------------------------------

def ton_papier(a):
    """Couleur ajoutée autour de la page : le ton du papier (page au bord clair), sinon du blanc (couverture, dessin pleine page : jamais une
    couleur tirée du dessin, c'était la bande rose des couvertures)."""
    h, w = a.shape[:2]
    bande = max(2, min(h, w) // 100)
    plat = lambda x: x.reshape(-1, *a.shape[2:])
    bord = np.concatenate([plat(a[:bande]), plat(a[-bande:]), plat(a[:, :bande]), plat(a[:, -bande:])])
    if float(np.median(bord.mean(axis=-1) if a.ndim == 3 else bord)) >= 190:
        p = np.percentile(plat(a[::4, ::4]).reshape(-1, 1 if a.ndim == 2 else a.shape[2]), 90, axis=0)
        return int(p[0]) if a.ndim == 2 else tuple(int(x) for x in p)
    return 255 if a.ndim == 2 else (255, 255, 255)


def rendre_page(im, boite, taille):
    """La page tournée de `a` degrés (sens horaire, autour de son centre), coupée au cadre x, y, w, h (ce qui sort de la page : papier), puis mise
    à l'échelle SANS déformation pour tenir dans taille = (largeur, hauteur), centrée, papier autour. La sortie fait exactement `taille`."""
    if im.mode not in ("L", "RGB"):
        im = im.convert("RGB")
    a = np.array(im)
    h, w = a.shape[:2]
    papier = ton_papier(a)
    angle = float(boite.get("a") or 0)
    if abs(angle) > 0.005:
        m = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)                 # OpenCV : positif = sens inverse des aiguilles ; ici positif = sens horaire
        a = cv2.warpAffine(a, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=papier)
    x, y, bw, bh = (int(round(float(boite[k]))) for k in ("x", "y", "w", "h"))
    bw, bh = max(1, bw), max(1, bh)
    cadre = np.empty((bh, bw) + a.shape[2:], np.uint8)
    cadre[...] = papier
    x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + bw), min(h, y + bh)
    if x1 > x0 and y1 > y0:
        cadre[y0 - y:y1 - y, x0 - x:x1 - x] = a[y0:y1, x0:x1]
    tw, th = int(taille[0]), int(taille[1])
    s = min(tw / bw, th / bh)
    nw, nh = min(tw, max(1, round(bw * s))), min(th, max(1, round(bh * s)))
    if (nw, nh) != (bw, bh):
        cadre = cv2.resize(cadre, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    sortie = np.empty((th, tw) + a.shape[2:], np.uint8)
    sortie[...] = papier
    ox, oy = (tw - nw) // 2, (th - nh) // 2
    sortie[oy:oy + nh, ox:ox + nw] = cadre
    return Image.fromarray(sortie)


# --- Réglages enregistrés ----------------------------------------------------------------------------------------------------------------

def _lire(fichier) -> dict:
    try:
        d = json.loads(Path(fichier).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("tomes", {})
    d.setdefault("series", {})
    return d


def _ecrire(fichier, d):
    fichier = Path(fichier)
    tmp = fichier.with_name(fichier.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, fichier)


def tailles_pages(chemin) -> list:
    """[[largeur, hauteur], …] de chaque page (en-têtes seulement), gardé tant que le fichier ne change pas."""
    chemin = Path(chemin)
    st = chemin.stat()
    cle = (str(chemin), st.st_size, st.st_mtime_ns)
    with _VERROU:
        if cle in _TAILLES:
            return _TAILLES[cle]
    out = []
    with zipfile.ZipFile(chemin) as z:
        for nom in archives.pages(chemin):
            with z.open(nom) as f, Image.open(f) as im:
                out.append([im.width, im.height])
    with _VERROU:
        if len(_TAILLES) > 20:
            _TAILLES.clear()
        _TAILLES[cle] = out
    return out


def boite_entiere(t) -> dict:
    return {"x": 0, "y": 0, "w": int(t[0]), "h": int(t[1]), "a": 0.0}


def nettoyer_boite(b):
    """Cadre borné aux valeurs raisonnables (entiers, angle au centième), ou None s'il n'a pas la bonne forme."""
    if not isinstance(b, dict):
        return None
    try:
        x, y, w, h = (int(round(float(b[k]))) for k in ("x", "y", "w", "h"))
        a = round(float(b.get("a") or 0), 2)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if w < MINI or h < MINI or abs(x) > 20000 or abs(y) > 20000 or w > 20000 or h > 20000 or a != a:
        return None
    out = {"x": x, "y": y, "w": w, "h": h, "a": max(-10.0, min(10.0, a))}
    if b.get("c"):
        out["c"] = 1                                     # cadre copié d'une autre page (pas encore revu)
    elif b.get("d"):
        out["d"] = 1                                     # 🪄 cadre proposé d'après les bords détectés (pas encore revu)
    return out


def _cinq(b):
    return {k: b[k] for k in ("x", "y", "w", "h", "a")}


def chemin_source(manga_dir, serie, fichier) -> Path:
    return Path(manga_dir) / DOSSIER / serie / fichier


def source_de(manga_dir, fichier_reglages, serie, chemin) -> Path:
    """Le fichier des pages d'origine du tome : sa copie gardée, sinon le tome lui-même."""
    e = (_lire(fichier_reglages)["tomes"].get(serie) or {}).get(Path(chemin).name) or {}
    s = Path(manga_dir) / e["source"] if e.get("source") else None
    return s if s and s.is_file() else Path(chemin)


def taille_finale(entree, tailles):
    """(W, H) : fixée, sinon automatique = cadre médian des pages simples réglées (sinon page médiane du tome)."""
    if entree.get("W") and entree.get("H"):
        return int(entree["W"]), int(entree["H"])
    b = [v for k, v in entree.get("boites", {}).items() if int(k) < len(tailles) and not est_double(tailles[int(k)])]
    if b:
        return _mediane(x["w"] for x in b), _mediane(x["h"] for x in b)
    s = [t for t in tailles if not est_double(t)] or tailles
    return _mediane(t[0] for t in s), _mediane(t[1] for t in s)


def cible(t, W, H):
    return (2 * W, H) if est_double(t) else (W, H)


def plan(entree, tailles) -> dict:
    """Ce que l'application écrirait : {"W", "H", "pages": [{"boite", "taille", "garder", "reglee"}]}. « garder » : cadre et taille finale identiques à
    la dernière application, la page actuelle est recopiée telle quelle."""
    W, H = taille_finale(entree, tailles)
    produit = entree.get("produit") or {}
    meme = produit.get("W") == W and produit.get("H") == H
    deja = produit.get("boites") or {}
    pages = []
    for i, t in enumerate(tailles):
        b = entree.get("boites", {}).get(str(i))
        b = _cinq(b) if b else boite_entiere(t)
        pages.append({"boite": b, "taille": list(cible(t, W, H)), "garder": bool(meme and deja.get(str(i)) == b), "reglee": str(i) in entree.get("boites", {})})
    return {"W": W, "H": H, "pages": pages}


def _pages_octets(chemin):
    with zipfile.ZipFile(chemin) as z:
        for nom in archives.pages(chemin):
            yield nom, z.read(nom)


def _remplacer_pages_source(source, chemin, indices):
    """Les pages `indices` du tome actuel deviennent les pages d'origine de ces numéros (copie de la source réécrite à côté puis mise en place)."""
    ordre_s, ordre_c = archives.pages(source), archives.pages(chemin)
    tmp = source.with_name(source.name + ".part")
    with zipfile.ZipFile(source) as zs, zipfile.ZipFile(chemin) as zc, zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        rang = {n: i for i, n in enumerate(ordre_s)}
        for info in zs.infolist():
            i = rang.get(info.filename)
            data = zc.read(ordre_c[i]) if i in indices else zs.read(info.filename)
            nom = info.filename if i not in indices or Path(ordre_c[i]).suffix.lower() == Path(info.filename).suffix.lower() else str(Path(info.filename).with_suffix(Path(ordre_c[i]).suffix))
            dst.writestr(zipfile.ZipInfo(nom, date_time=info.date_time), data)
    with zipfile.ZipFile(tmp) as z:
        if z.testzip() is not None or len(archives._names(z)) != len(ordre_s):
            tmp.unlink()
            raise RuntimeError("copie des pages d'origine illisible")
    os.replace(tmp, source)


def ouvrir(manga_dir, fichier_reglages, serie, chemin) -> dict:
    """État du rognage d'un tome : {"entree", "source" (fichier des pages d'origine), "tailles", "message", "jeter" (ancienne source à mettre à la
    corbeille ou None)}. Remet les réglages d'accord avec le fichier actuel s'il a changé par ailleurs depuis (voir l'en-tête du module)."""
    chemin = Path(chemin)
    with _VERROU:
        d = _lire(fichier_reglages)
        e = (d["tomes"].get(serie) or {}).get(chemin.name)
        taille_tome = chemin.stat().st_size
        message, jeter, change = "", None, False
        if e:
            source = Path(manga_dir) / e["source"] if e.get("source") else chemin
            try:
                ok_source = source.is_file() and (source == chemin or source.stat().st_size == e.get("source_octets"))
                n_tome = len(archives.pages(chemin))
                n_source = len(archives.pages(source)) if ok_source else -1
            except (archives.ArchiveError, zipfile.BadZipFile, OSError):
                ok_source, n_tome, n_source = False, 0, -1
            if not ok_source or n_tome != n_source:
                message = ("Ce tome a changé depuis (autre traitement, retour en arrière…) et n'a plus les mêmes pages : les cadres enregistrés ne "
                           "correspondent plus, le rognage repart du fichier actuel.")
                jeter = source if e.get("source") and source.is_file() else None
                e, change = None, True
            elif e.get("produit") and e["produit"].get("octets") != taille_tome:
                vues = e["produit"].get("empreintes") or {}
                autres = [i for i, (_, data) in enumerate(_pages_octets(chemin)) if vues.get(str(i)) != empreinte(data)]
                if autres:                                  # changées par autre chose (couverture remplacée…) : nouvelles pages d'origine de ces numéros
                    _remplacer_pages_source(source, chemin, set(autres))
                    tailles = tailles_pages(source)
                    e["source_octets"] = source.stat().st_size
                    octets = dict(_pages_octets(chemin))
                    ordre = archives.pages(chemin)
                    for i in autres:
                        e["boites"].pop(str(i), None)
                        e["produit"].setdefault("boites", {})[str(i)] = boite_entiere(tailles[i])
                        e["produit"].setdefault("empreintes", {})[str(i)] = empreinte(octets[ordre[i]])
                    message = (f"{len(autres)} page(s) changée(s) depuis le dernier rognage par autre chose (page {', '.join(str(i + 1) for i in autres[:8])}"
                               f"{'…' if len(autres) > 8 else ''}) : reprises telles quelles comme nouvelles pages d'origine.")
                e["produit"]["octets"] = taille_tome
                change = True
            elif not e.get("source") and e.get("source_octets") != taille_tome:
                tailles = tailles_pages(chemin)               # pas encore appliqué : on garde les cadres des pages qui ont gardé leur taille
                avant = e.get("tailles") or []
                perdus = [k for k in list(e["boites"]) if int(k) >= len(tailles) or int(k) >= len(avant) or avant[int(k)] != tailles[int(k)]]
                for k in perdus:
                    e["boites"].pop(k)
                e.update(source_octets=taille_tome, tailles=tailles)
                if perdus:
                    message = f"Le tome a changé depuis : {len(perdus)} cadre(s) de pages qui n'ont plus la même taille sont oubliés."
                change = True
        if not e:
            e = {"source": None, "source_octets": taille_tome, "W": None, "H": None, "boites": {}, "produit": None}
            ref = d["series"].get(serie)
            if ref and ref.get("W") and ref.get("H"):
                e["W"], e["H"] = int(ref["W"]), int(ref["H"])
        source = Path(manga_dir) / e["source"] if e.get("source") else chemin
        tailles = tailles_pages(source)
        e["tailles"] = tailles
        if change:
            d["tomes"].setdefault(serie, {})[chemin.name] = e
            _ecrire(fichier_reglages, d)
        return {"entree": e, "source": source, "tailles": tailles, "message": message, "jeter": jeter, "reference": d["series"].get(serie)}


def sauver(fichier_reglages, serie, fichier, etat, W, H, boites):
    """Enregistre la taille finale (None : automatique) et les cadres réglés. `etat` : ce que `ouvrir` vient de rendre."""
    e, tailles = etat["entree"], etat["tailles"]
    propres = {}
    for k, v in (boites or {}).items():
        if str(k).isdigit() and int(k) < len(tailles):
            b = nettoyer_boite(v)
            if b:
                propres[str(int(k))] = b
    try:
        W, H = (int(W), int(H)) if W and H else (None, None)
    except (TypeError, ValueError):
        W, H = None, None
    if W is not None and not (MINI <= W <= 20000 and MINI <= H <= 20000):
        W, H = None, None
    with _VERROU:
        d = _lire(fichier_reglages)
        e = dict(e, W=W, H=H, boites=propres, maj=datetime.now().strftime("%d/%m/%Y %H:%M"))
        d["tomes"].setdefault(serie, {})[fichier] = e
        _ecrire(fichier_reglages, d)
    return e


def oublier(fichier_reglages, serie, fichier):
    with _VERROU:
        d = _lire(fichier_reglages)
        (d["tomes"].get(serie) or {}).pop(fichier, None)
        _ecrire(fichier_reglages, d)


def noter_application(manga_dir, fichier_reglages, serie, chemin, travail):
    """Après l'écriture : la source gardée, ce que contient maintenant le tome (cadres, taille, empreinte de chaque page) et la taille de la série."""
    chemin = Path(chemin)
    with _VERROU:
        d = _lire(fichier_reglages)
        e = (d["tomes"].get(serie) or {}).get(chemin.name) or {"boites": {}}
        if travail.get("copier_source"):
            e["source"] = str(Path(travail["source"]).relative_to(Path(manga_dir)))
            e["source_octets"] = Path(travail["source"]).stat().st_size
        e["W"], e["H"] = travail["W"], travail["H"]                 # la taille est figée : modifier une page ne change plus les autres
        e["produit"] = {"octets": chemin.stat().st_size, "W": travail["W"], "H": travail["H"],
                        "boites": {str(i): p["boite"] for i, p in enumerate(travail["pages"])}, "empreintes": travail["empreintes"],
                        "date": datetime.now().strftime("%d/%m/%Y %H:%M")}
        d["tomes"].setdefault(serie, {})[chemin.name] = e
        d["series"][serie] = {"W": travail["W"], "H": travail["H"], "tome": chemin.name}
        _ecrire(fichier_reglages, d)


def _entree_produite(d, chemin):
    """(série, entrée) du tome dont le fichier est exactement celui écrit par le rognage, sinon (None, None)."""
    chemin = Path(chemin)
    try:
        octets = chemin.stat().st_size
    except OSError:
        return None, None
    for serie, tomes in d["tomes"].items():
        e = tomes.get(chemin.name)
        if e and (e.get("produit") or {}).get("octets") == octets:
            return serie, e
    return None, None


def facteur(boite, taille) -> float:
    """Agrandissement d'une page : cadre → taille de sortie."""
    return min(int(taille[0]) / max(1, int(boite["w"])), int(taille[1]) / max(1, int(boite["h"])))


def echelle_source(fichier_reglages, chemin) -> float | None:
    """Agrandissement médian des pages simples d'un tome rogné ici (la restauration IA travaille à la résolution d'origine), None si le fichier n'est
    pas celui écrit par le rognage."""
    _, e = _entree_produite(_lire(fichier_reglages), chemin)
    if not e:
        return None
    p, tailles = e["produit"], e.get("tailles") or []
    f = [facteur(b, (p["W"], p["H"])) for k, b in (p.get("boites") or {}).items() if int(k) < len(tailles) and not est_double(tailles[int(k)])]
    return round(float(np.median(f)), 3) if f else None


def noter_retouches(fichier_reglages, chemin, octets_avant, reglages):
    """Après un ✨ Améliorer appliqué à un tome rogné ici : si le tome était celui écrit par le rognage et que ses pages gardent leur taille, les retouches
    sont notées (une page refaite plus tard les reçoit aussi) et le fichier redevient « le produit » (ses pages ne passent pas pour des pages d'origine
    modifiées). Renvoie True si c'est noté."""
    chemin = Path(chemin)
    r = {k: int(v) for k, v in (reglages or {}).items() if k in RETOUCHES and v}
    with _VERROU:
        d = _lire(fichier_reglages)
        for serie, tomes in d["tomes"].items():
            e = tomes.get(chemin.name)
            if e and (e.get("produit") or {}).get("octets") == octets_avant:
                break
        else:
            return False
        p, tailles = e["produit"], e.get("tailles") or []
        attendu = [list(cible(t, p["W"], p["H"])) for t in tailles]
        with zipfile.ZipFile(chemin) as z:
            ordre = archives._names(z)
            if len(ordre) != len(attendu):
                return False
            empreintes = {}
            for i, n in enumerate(ordre):
                data = z.read(n)
                with Image.open(io.BytesIO(data)) as im:
                    if [im.width, im.height] != attendu[i]:
                        return False
                empreintes[str(i)] = empreinte(data)
        e["retouches"] = {**(e.get("retouches") or {}), **r}
        p.update(octets=chemin.stat().st_size, empreintes=empreintes)
        _ecrire(fichier_reglages, d)
        return True


def etat_liste(fichier_reglages, serie) -> dict:
    """{fichier: {"date", "octets"}} des tomes rognés ici, et ceux qui ont des réglages pas encore appliqués."""
    d = _lire(fichier_reglages)
    out = {}
    for fichier, e in (d["tomes"].get(serie) or {}).items():
        p = e.get("produit") or {}
        en_cours = bool(e.get("boites")) and (not p or any(p.get("boites", {}).get(k) != _cinq(v) for k, v in e["boites"].items())
                                              or (e.get("W"), e.get("H")) != (p.get("W"), p.get("H")))
        out[fichier] = {"date": p.get("date", ""), "octets": p.get("octets"), "en_cours": en_cours}
    return out


# --- Écriture du tome (dans le fil de travail de optimiser.lancer_coupes) ------------------------------------------------------------------

def ecrire_tome(chemin, indices, sens_manga=True, destination=None, travail=None) -> dict:
    """Réécrit le tome : chaque page à réécrire est rendue depuis sa page d'origine, les autres sont recopiées telles quelles. Version écrite à
    côté, relue (archive saine, mêmes pages, bonnes tailles), puis mise en place ; l'ancien fichier part dans « .avant ». `travail` reçoit
    « empreintes » (empreinte de chaque page écrite)."""
    import optimiser
    chemin = Path(chemin)
    source = Path(travail["source"])
    if travail.get("copier_source"):                     # première application : on garde les pages d'origine avant de toucher au tome
        source.parent.mkdir(parents=True, exist_ok=True)
        if not (source.is_file() and source.stat().st_size == chemin.stat().st_size):
            part = source.with_name(source.name + ".part")
            shutil.copyfile(chemin, part)
            if part.stat().st_size != chemin.stat().st_size:
                part.unlink()
                raise RuntimeError("copie des pages d'origine incomplète")
            os.replace(part, source)
    ordre, ordre_s, pages = archives.pages(chemin), archives.pages(source), travail["pages"]
    if not (len(ordre) == len(ordre_s) == len(pages)):
        raise RuntimeError("le tome n'a plus le même nombre de pages : rien n'a été écrit")
    rang = {n: i for i, n in enumerate(ordre)}
    retouches = optimiser.reglages_amelioration({k: v for k, v in (travail.get("retouches") or {}).items() if k in RETOUCHES})
    tmp = Path(destination) if destination is not None else chemin.with_name("." + chemin.name + ".rogne")
    attendu, empreintes = {}, {}
    with zipfile.ZipFile(chemin) as zc, zipfile.ZipFile(source) as zs, zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        for info in zc.infolist():
            i = rang.get(info.filename)
            if i is None or pages[i]["garder"]:
                data = zc.read(info.filename)
            else:
                im = Image.open(io.BytesIO(zs.read(ordre_s[i])))
                im.load()
                sortie = rendre_page(im, pages[i]["boite"], pages[i]["taille"])
                if retouches:                              # le tome avait été ✨ amélioré après le rognage : la page refaite reçoit la même retouche que ses voisines
                    sortie = optimiser.ameliorer(sortie, retouches, source=facteur(pages[i]["boite"], pages[i]["taille"]))
                    if list(sortie.size) != list(pages[i]["taille"]):
                        sortie = sortie.resize(tuple(pages[i]["taille"]), Image.LANCZOS)
                data = optimiser._octets_page(sortie, info.filename)
                attendu[info.filename] = list(pages[i]["taille"])
            if i is not None:
                empreintes[str(i)] = empreinte(data)
            info2 = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            info2.compress_type = zipfile.ZIP_STORED
            dst.writestr(info2, data)
    try:
        with zipfile.ZipFile(tmp) as z:                    # relecture : archive saine, mêmes pages, bonnes tailles
            if z.testzip() is not None:
                raise RuntimeError("archive rognée illisible")
            if archives._names(z) != ordre:
                raise RuntimeError("pages différentes après le rognage")
            for nom, taille in attendu.items():
                with z.open(nom) as f, Image.open(f) as im:
                    if [im.width, im.height] != taille:
                        raise RuntimeError("une page rognée n'a pas la taille prévue")
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    travail["empreintes"] = empreintes
    res = {"carte": {i: i for i in range(len(ordre))}, "pages_avant": len(ordre), "pages": len(ordre)}
    if destination is not None:
        return res
    avant = chemin.with_name(chemin.name + ".avant")
    chemin.rename(avant)
    tmp.rename(chemin)
    res["avant"] = avant
    return res


ecrire_tome.reglage = "travail"                        # lancer_coupes : le 3e élément d'un travail est passé sous ce nom
ecrire_tome.libelle = lambda pages, tomes: f"{pages} page(s) réécrite(s)"
