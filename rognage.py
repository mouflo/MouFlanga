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
RETOUCHES = ("debruit", "trames", "papier", "noirs", "taches", "lisser", "nettete", "ia", "redresser", "flashback")   # ✨ retouches refaites sur une page réécrite (jamais ce qui change sa taille)
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
    """Couleur ajoutée autour de la page : le ton du papier (page au bord clair) ; page noir et blanc au bord sombre (flash-back sur fond noir) : le ton
    de son bord, pour que le fond noir continue ; sinon du blanc (couverture en couleur, dessin pleine page : jamais une couleur tirée du dessin, c'était
    la bande rose des couvertures)."""
    h, w = a.shape[:2]
    bande = max(2, min(h, w) // 100)
    plat = lambda x: x.reshape(-1, *a.shape[2:])
    bord = np.concatenate([plat(a[:bande]), plat(a[-bande:]), plat(a[:, :bande]), plat(a[:, -bande:])])
    gris_bord = bord.mean(axis=-1) if a.ndim == 3 else bord
    if float(np.median(gris_bord)) >= 190:
        p = np.percentile(plat(a[::4, ::4]).reshape(-1, 1 if a.ndim == 2 else a.shape[2]), 90, axis=0)
        return int(p[0]) if a.ndim == 2 else tuple(int(x) for x in p)
    petit = a[::8, ::8].astype(np.int16)
    gris = a.ndim == 2 or float(np.mean(np.abs(petit[..., 0] - petit[..., 1]) + np.abs(petit[..., 1] - petit[..., 2]))) < 12
    if gris and float(np.median(gris_bord)) < 120:                 # fond noir (ou gris foncé) tout autour : il continue
        t = int(np.median(gris_bord))
        return t if a.ndim == 2 else (t, t, t)
    return 255 if a.ndim == 2 else (255, 255, 255)


_CORRECTIONS = {}


def rendre_redressee(im, boite, taille, traits=False):
    """rendre_page sur la page d'origine redressée. Le redressement est mesuré DANS le cadre (la tranche des pages voisines, dehors, fausserait la mesure),
    il remplace l'angle réglé à la main ; le cadre subit le même redressement et on garde le plus grand rectangle qu'il contient : on ne voit que ce que le
    cadre montrait (jamais la bande voisine qu'il laissait dehors). Page en couleur ou rien de sûr : rendre_page tel quel."""
    import optimiser
    import reliure
    if optimiser.est_couleur(im):
        return rendre_page(im, boite, taille, traits)
    if im.mode not in ("L", "RGB"):
        im = im.convert("RGB")
    a = np.array(im)
    H, W = a.shape[:2]
    x, y, w, h = (float(boite[k]) for k in ("x", "y", "w", "h"))
    cx0, cy0, cx1, cy1 = max(0, int(x)), max(0, int(y)), min(W, int(x + w)), min(H, int(y + h))
    if cx1 - cx0 < 200 or cy1 - cy0 < 200:
        return rendre_page(im, boite, taille, traits)
    gris = a if a.ndim == 2 else cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    dedans = np.ascontiguousarray(gris[cy0:cy1, cx0:cx1])
    cle = (hashlib.blake2b(dedans.tobytes(), digest_size=16).hexdigest(), dedans.shape)
    if cle not in _CORRECTIONS:
        if len(_CORRECTIONS) > 512:
            _CORRECTIONS.clear()
        _CORRECTIONS[cle] = reliure.redressement(dedans)
    c = _CORRECTIONS[cle]
    if not c:
        return rendre_page(im, boite, taille, traits)
    T = np.array([[1, 0, -cx0], [0, 1, -cy0], [0, 0, 1.]])
    M = np.linalg.inv(T) @ reliure.matrice_redressement(c, cx1 - cx0, cy1 - cy0) @ T          # mesurée dans le cadre, appliquée à toute la page
    papier = ton_papier(a)
    a2 = cv2.warpPerspective(a, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=papier)
    coins = np.array([[x, y, 1], [x + w, y, 1], [x + w, y + h, 1], [x, y + h, 1]]) @ M.T
    coins = coins[:, :2] / coins[:, 2:]
    x0, x1 = max(coins[0, 0], coins[3, 0]), min(coins[1, 0], coins[2, 0])
    y0, y1 = max(coins[0, 1], coins[1, 1]), min(coins[2, 1], coins[3, 1])
    x0, y0 = int(np.ceil(x0)), int(np.ceil(y0))
    inscrit = {"x": x0, "y": y0, "w": max(MINI, int(np.floor(x1)) - x0), "h": max(MINI, int(np.floor(y1)) - y0), "a": 0.0}
    return rendre_page(Image.fromarray(a2), inscrit, taille, traits)


def _en_couleur(a):
    if a.ndim == 2:
        return False
    petit = a[::8, ::8].astype(np.int16)
    return float(np.mean(np.abs(petit[..., 0] - petit[..., 1]) + np.abs(petit[..., 1] - petit[..., 2]))) >= 12


def traits_coupe(gris, cadre, x, y, bw, bh):
    """✏️ Cadre redessiné après un rognage à la main au ras des cases (essai voulu par l'utilisateur, 19/11/2026). Pour chaque côté du cadre, là où le
    dessin touche la coupe, un trait droit est tracé le long de la coupe, SAUF :
    - si le dessin continue jusqu'au bord du papier de ce côté (image à fond perdu : elle doit toucher le bord de la page, pas de cadre) ;
    - si un vrai trait de cadre est déjà là, juste à l'intérieur (jamais de trait doublé).
    `gris` : la page entière (tournée), `cadre` : ce que le cadre en montre. Retourne le cadre avec ses traits."""
    h, w = gris.shape
    papier = float(np.percentile(gris, 95))
    encre = gris < 0.6 * papier
    # les traits fins parallèles au bord (tranche des pages, bords du scan) ne sont pas du dessin : on les retire pour juger du « fond perdu »
    fin = (encre & ~(cv2.morphologyEx(encre.astype(np.uint8), cv2.MORPH_OPEN, np.ones((7, 7), np.uint8)) > 0)).astype(np.uint8)   # traits fins seulement
    vert = cv2.morphologyEx(fin, cv2.MORPH_OPEN, np.ones((max(25, h // 20), 1), np.uint8)) > 0
    hori = cv2.morphologyEx(fin, cv2.MORPH_OPEN, np.ones((1, max(25, w // 20)), np.uint8)) > 0
    dessin = encre & ~cv2.dilate((vert | hori).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    e = max(2, round(0.003 * min(bw, bh)))                 # épaisseur du trait
    d = max(4, round(0.006 * min(bw, bh)))                 # profondeur où le dessin « touche » la coupe
    x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + bw), min(h, y + bh)
    if x1 - x0 < 50 or y1 - y0 < 50:
        return cadre
    noir = int(np.percentile(gris[y0:y1, x0:x1][encre[y0:y1, x0:x1]], 2)) if encre[y0:y1, x0:x1].any() else 20
    sortie = cadre.copy()
    marge = max(3, round(0.004 * min(h, w)))
    for cote in ("haut", "bas", "gauche", "droite"):
        if cote == "haut":
            dedans, deja, dehors, loin = encre[y0:y0 + d, x0:x1], hori[y0:y0 + 3 * d, x0:x1], dessin[:y0, x0:x1][::-1], y0
            axe = 0
        elif cote == "bas":
            dedans, deja, dehors, loin = encre[y1 - d:y1, x0:x1][::-1], hori[y1 - 3 * d:y1, x0:x1][::-1], dessin[y1:, x0:x1], h - y1
            axe = 0
        elif cote == "gauche":
            dedans, deja, dehors, loin = encre[y0:y1, x0:x0 + d].T, vert[y0:y1, x0:x0 + 3 * d].T, dessin[y0:y1, :x0][:, ::-1].T, x0
            axe = 1
        else:
            dedans, deja, dehors, loin = encre[y0:y1, x1 - d:x1].T[::-1], vert[y0:y1, x1 - 3 * d:x1].T[::-1], dessin[y0:y1, x1:].T, w - x1
            axe = 1
        if loin <= marge:                                   # la coupe est au bord du papier : l'image touche le bord, pas de cadre
            continue
        touche = dedans.any(0)
        if deja.size and deja.mean(1).max() > 0.6:         # un vrai trait de cadre droit, parallèle à la coupe, est déjà là : rien (hachures exclues)
            continue
        # au-delà de la coupe : le dessin va-t-il jusqu'au bord du papier ? (sa dernière bande, côté papier)
        bande = dehors[max(0, dehors.shape[0] - max(4, dehors.shape[0] // 3)):] if dehors.shape[0] else dehors
        perdu = bande.mean(0) > 0.12 if bande.size else np.zeros(touche.shape, bool)
        perdu = cv2.dilate(perdu.astype(np.uint8).reshape(1, -1), np.ones((1, 31), np.uint8)).ravel() > 0
        tracer = touche & ~perdu
        tracer = cv2.morphologyEx(tracer.astype(np.uint8).reshape(1, -1), cv2.MORPH_CLOSE, np.ones((1, 25), np.uint8)).ravel() > 0
        for a_, b_ in _suites(tracer):
            if b_ - a_ < 20:
                continue
            if cote == "haut":
                sl = np.s_[y0 - y:y0 - y + e, x0 - x + a_:x0 - x + b_]
            elif cote == "bas":
                sl = np.s_[y1 - y - e:y1 - y, x0 - x + a_:x0 - x + b_]
            elif cote == "gauche":
                sl = np.s_[y0 - y + a_:y0 - y + b_, x0 - x:x0 - x + e]
            else:
                sl = np.s_[y0 - y + a_:y0 - y + b_, x1 - x - e:x1 - x]
            sortie[sl] = noir
    return sortie


def _suites(v):
    v = np.r_[False, v, False].astype(np.int8)
    dv = np.diff(v)
    return list(zip(np.where(dv == 1)[0], np.where(dv == -1)[0]))


def rendre_page(im, boite, taille, traits=False):
    """La page tournée de `a` degrés (sens horaire, autour de son centre), coupée au cadre x, y, w, h (ce qui sort de la page : papier), puis mise
    à l'échelle SANS déformation pour tenir dans taille = (largeur, hauteur), centrée, papier autour. La sortie fait exactement `taille`.
    traits : le cadre des cases coupées par le cadre est redessiné le long de la coupe (voir traits_coupe)."""
    if im.mode not in ("L", "RGB"):
        im = im.convert("RGB")
    a = np.array(im)
    h, w = a.shape[:2]
    bx, by, bw0, bh0 = (int(round(float(boite[k]))) for k in ("x", "y", "w", "h"))
    vu = a[max(0, by):min(h, by + bh0), max(0, bx):min(w, bx + bw0)]
    papier = ton_papier(vu if min(vu.shape[:2]) >= 20 else a)        # le ton du bord de ce que le cadre montre (pas de la tranche des pages voisines, dehors)
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
    if traits and a.ndim == 2 or (traits and not _en_couleur(a)):
        cadre = traits_coupe(a if a.ndim == 2 else cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), cadre, x, y, bw, bh)
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
    meme = produit.get("W") == W and produit.get("H") == H and bool(produit.get("traits")) == bool(entree.get("traits"))   # ✏️ changé : tout est réécrit
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


def retouches_effectives(fichier_reglages, serie, entree):
    """(retouches, d'où elles viennent) : celles du tome ; sinon celles de la série (le dernier tome rogné de la série qui en a), pour que
    « Appliquer au tome » fasse tout en une étape (coupe + IA + noirs…) même sur un tome qui n'a jamais reçu ✨ (Nori Taka tome 4)."""
    if entree.get("retouches"):
        return dict(entree["retouches"]), "tome"
    d = _lire(fichier_reglages)
    tomes = d["tomes"].get(serie) or {}
    ref = (d["series"].get(serie) or {}).get("retouches")
    if ref:
        return dict(ref), "série"
    avec = [(n, e) for n, e in tomes.items() if e.get("retouches")]
    if not avec:
        return None, None
    n, e = max(avec, key=lambda x: (len(x[1]["retouches"]), (x[1].get("produit") or {}).get("date") or ""))
    return dict(e["retouches"]), n


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
                        "date": datetime.now().strftime("%d/%m/%Y %H:%M"), "traits": bool(travail.get("traits"))}
        e["traits"] = bool(travail.get("traits"))
        if travail.get("retouches"):
            e["retouches"] = dict(travail["retouches"])       # reprises de la série : elles deviennent celles du tome
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


def est_rogne(fichier_reglages, chemin) -> bool:
    """Le fichier est-il celui écrit par le rognage à la main ?"""
    return _entree_produite(_lire(fichier_reglages), chemin)[1] is not None


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


def page_redressee(manga_dir, fichier_reglages, chemin, nom):
    """Page `nom` d'un tome rogné ici (le fichier est celui écrit par le rognage), refaite depuis sa page d'origine redressée avec le même cadre et la même taille :
    {"image", "retouches" (déjà faites sur ce tome), "source" (facteur d'agrandissement)}, ou None."""
    _, e = _entree_produite(_lire(fichier_reglages), chemin)
    if not e or not e.get("source"):
        return None
    ordre = archives.pages(chemin)
    if nom not in ordre:
        return None
    i = ordre.index(nom)
    source = Path(manga_dir) / e["source"]
    p, tailles = e["produit"], e.get("tailles") or []
    b = (p.get("boites") or {}).get(str(i))
    ordre_s = archives.pages(source)
    if b is None or len(ordre_s) != len(ordre) or i >= len(tailles):
        return None
    with zipfile.ZipFile(source) as z:
        im = Image.open(io.BytesIO(z.read(ordre_s[i])))
        im.load()
    taille = cible(tailles[i], p["W"], p["H"])
    return {"image": rendre_redressee(im, b, taille), "retouches": {k: v for k, v in (e.get("retouches") or {}).items() if k != "redresser"},
            "source": facteur(b, taille)}


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
    redresse = bool((travail.get("retouches") or {}).get("redresser"))                   # ✨ « redresser » : refait sur la page d'origine, avant le cadre
    retouches = optimiser.reglages_amelioration({k: v for k, v in (travail.get("retouches") or {}).items() if k in RETOUCHES and k != "redresser"})
    tmp = Path(destination) if destination is not None else chemin.with_name("." + chemin.name + ".rogne")
    attendu, empreintes = {}, {}
    a_ecrire, faites = sum(1 for p in pages if not p["garder"]), 0
    progres = travail.get("progres")
    with zipfile.ZipFile(chemin) as zc, zipfile.ZipFile(source) as zs, zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        for info in zc.infolist():
            i = rang.get(info.filename)
            if i is None or pages[i]["garder"]:
                data = zc.read(info.filename)
            else:
                im = Image.open(io.BytesIO(zs.read(ordre_s[i])))
                im.load()
                sortie = (rendre_redressee if redresse else rendre_page)(im, pages[i]["boite"], pages[i]["taille"], bool(travail.get("traits")))
                if retouches:                              # le tome avait été ✨ amélioré après le rognage : la page refaite reçoit la même retouche que ses voisines
                    sortie = optimiser.ameliorer(sortie, retouches, source=facteur(pages[i]["boite"], pages[i]["taille"]))
                    if list(sortie.size) != list(pages[i]["taille"]):
                        sortie = sortie.resize(tuple(pages[i]["taille"]), Image.LANCZOS)
                data = optimiser._octets_page(sortie, info.filename)
                attendu[info.filename] = list(pages[i]["taille"])
                faites += 1
                if progres:
                    progres(faites, a_ecrire)
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
