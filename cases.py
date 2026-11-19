"""
🧩 Recadrage aux cases d'un tome scanné à plat (deux pages par scan, coupé en deux moitiés), mis au point le 18/11/2026 avec l'utilisateur sur Nori Taka
tome 3. Tout part des pages d'origine (rognage.py) ; rien n'est demandé page par page.

1. Chaque moitié de scan est redressée (reliure.redressement, mesuré dans le cadre réglé à la main s'il y en a un).
2. Taille réelle de la page : le fond noir des flash-backs va d'un bord du papier à l'autre (mesuré : 1037 px de haut sur le tome 3) ; sans flash-back, la
   hauteur du bloc de cases (les traits de cadre sont presque au bord du papier).
3. Une boîte de cette taille est posée sur le trait du haut des cases et le bord extérieur de la page (jamais sur l'autre moitié du scan).
4. Page blanche (couper_cases) : coupée au ras des cadres de cases (le vrai cadre est le plus intérieur des longs traits du bord : la tranche des pages du
   dessous est dehors), cases fermées par leurs traits, gouttières et extérieur en blanc, côté reliure recoupé droit sans jamais couper un texte, un seul
   trait droit refait par côté (l'ancien effacé).
5. Flash-back (fond_cases) : les cases sont des rectangles droits entre les gouttières sombres (gouttières en biais suivies), leur intérieur n'est jamais
   touché, tout le reste devient noir franc sauf les lignes de texte. Demi flash-back (une grande case claire à fond perdu en bas) : remplissage depuis
   les bords puis même découpe, côtés coupés droit quelques px à l'intérieur du dernier trait.
6. Mise en page : page blanche recadrée sur ses cases et en plein écran ; flash-back au zoom médian des pages blanches (ses cases restent plus petites
   dans le cadre noir, comme dans le livre).

Les pages qui ne sont pas une moitié de scan (couverture, doubles pages, page seule) restent celles du tome actuel.
"""
import io
import shutil
import tempfile
import zipfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import archives
import reliure

BORD = 4                       # lignes du bord du scan ignorées (artefacts)
MARGE = 0.985                  # part de la page occupée par les cases d'une page blanche


# --- Outils --------------------------------------------------------------------------------------------------------------------------------

def runs(v):
    """(début, fin) des suites de True."""
    v = np.r_[False, v, False].astype(np.int8)
    dv = np.diff(v)
    return list(zip(np.where(dv == 1)[0], np.where(dv == -1)[0]))


def _suites(v, mini):
    return [(a, b) for a, b in runs(v) if b - a >= mini]


def lignes_fines(g):
    """Traits fins sombres : (horizontaux, verticaux)."""
    bh = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, np.ones((9, 9), np.uint8))
    m = (bh > 40).astype(np.uint8)
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((1, 15), np.uint8)), cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((15, 1), np.uint8))


def redresse(g, boite=None):
    """Moitié de scan redressée ; le redressement est mesuré dans le cadre réglé à la main (la tranche des pages voisines, dehors, fausserait la mesure)."""
    H, W = g.shape
    x, y, w, h = (0, 0, W, H) if not boite else (float(boite[k]) for k in ("x", "y", "w", "h"))
    cx0, cy0, cx1, cy1 = max(0, int(x)), max(0, int(y)), min(W, int(x + w)), min(H, int(y + h))
    if cx1 - cx0 < 200 or cy1 - cy0 < 200:
        cx0, cy0, cx1, cy1 = 0, 0, W, H
    c = reliure.redressement(np.ascontiguousarray(g[cy0:cy1, cx0:cx1]))
    if not c:
        return g
    T = np.array([[1, 0, -cx0], [0, 1, -cy0], [0, 0, 1.]])
    M = np.linalg.inv(T) @ reliure.matrice_redressement(c, cx1 - cx0, cy1 - cy0) @ T
    return cv2.warpPerspective(g, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def fond_sombre(g):
    """Bords du fond sombre d'un flash-back (haut, bas, gauche, droite) : premières lignes/colonnes, depuis le bord, dont la médiane est sombre."""
    h, w = g.shape
    papier = float(np.percentile(g, 95))
    s = 0.62 * papier
    rows = np.median(g[:, int(.2 * w):int(.8 * w)], 1) < s
    cols = np.median(g[int(.2 * h):int(.8 * h), :], 0) < s

    def premier(v, n):
        for k in range(n):
            if v[k] and v[k:k + 6].all():
                return k
        return None
    t, b = premier(rows, int(.1 * h)), premier(rows[::-1], int(.1 * h))
    l, r = premier(cols, int(.12 * w)), premier(cols[::-1], int(.12 * w))
    return {"haut": t, "bas": None if b is None else h - b, "gauche": l, "droite": None if r is None else w - r}


def traits(g):
    """Traits de cadre extérieurs de la page : haut, bas, gauche, droite (bord extérieur du trait) ou None."""
    h, w = g.shape
    hor, ver = lignes_fines(g)
    ch = cv2.dilate(hor, np.ones((3, 1), np.uint8)).sum(1) / w
    cv = cv2.dilate(ver, np.ones((1, 3), np.uint8)).sum(0) / h
    zh, zw = int(0.07 * h), int(0.12 * w)
    ok = lambda rs: [r for r in rs if r[0] >= BORD]
    okb = lambda rs, n: [r for r in rs if r[1] <= n - BORD]
    rt = ok(runs(ch[:zh] >= 0.22))
    rb = okb([(a + h - zh, b + h - zh) for a, b in runs(ch[h - zh:] >= 0.22)], h)
    rl = ok(runs(cv[:zw] >= 0.20))
    rr = okb([(a + w - zw, b + w - zw) for a, b in runs(cv[w - zw:] >= 0.20)], w)
    return {"haut": int(rt[0][0]) if rt else None, "bas": int(rb[-1][1]) if rb else None,
            "gauche": int(rl[0][0]) if rl else None, "droite": int(rr[-1][1]) if rr else None}


def gouttieres_relatives(g):
    """Nombre de gouttières horizontales plus sombres que les cases (flash-back délavé)."""
    h, w = g.shape
    bande = g[:, int(.1 * w):int(.9 * w)].astype(np.float32)
    papier = float(np.percentile(g, 95))
    med = np.median(bande, 1)
    clair = (bande > 0.8 * papier).mean(1)
    sombre = (med < 0.68 * papier) & ((bande < 0.72 * papier).mean(1) > 0.8)
    n, i, fin, m = 0, int(.05 * h), int(.95 * h), int(.03 * h)
    while i < fin:
        if not sombre[i]:
            i += 1
            continue
        j = i
        while j < fin and sombre[j]:
            j += 1
        if 0.006 * h <= j - i <= 0.06 * h and clair[max(0, i - m):i].max(initial=0) > 0.3 and clair[j:j + m].max(initial=0) > 0.3:
            n += 1
        i = j
    return n


def est_flashback(g):
    """Page sur fond noir (gris délavé compris), ou moitié de page (fond sombre en haut et au moins une gouttière sombre)."""
    f = fond_sombre(g)
    h, w = g.shape
    # le fond noir d'un flash-back part du bord du papier : en haut (à moins de 3 % de la hauteur) et sur les deux côtés, ou sur un seul côté sans que
    # l'autre ait de bord sombre (demi flash-back). Une page simplement sombre (grande case noire) commence plus bas ou s'arrête avant un côté
    # (mesuré sur Nori Taka tomes 1 à 3 : tome 3 pages 78 et 94, tome 1 pages 14 et 144)
    if f["haut"] is None or f["haut"] > 0.03 * h:
        return False
    g_bord = f["gauche"] is not None and f["gauche"] <= 8
    d_bord = f["droite"] is not None and f["droite"] >= w - 8
    if g_bord and d_bord:
        return reliure.fond_noir(g) or (f["haut"] > BORD and gouttieres_relatives(g) >= 1)
    if (g_bord and f["droite"] is None) or (d_bord and f["gauche"] is None):
        return f["haut"] > BORD and gouttieres_relatives(g) >= 1
    return False


# --- Taille réelle et boîte --------------------------------------------------------------------------------------------------------------

def hauteur_reelle(pages):
    """Hauteur de la page en px du scan. `pages` : [(image redressée, flash-back ?)]. Fond noir des flash-backs (d'un bord du papier à l'autre), sinon
    bloc de cases des pages blanches (+ 4 px de trait). None si rien de sûr."""
    fb, blocs = [], []
    for g, est_fb in pages:
        h = g.shape[0]
        if est_fb:
            f = fond_sombre(g)
            if f["haut"] is not None and f["bas"] is not None and f["haut"] > BORD and f["bas"] < h - BORD:
                fb.append(f["bas"] - f["haut"])
        else:
            t = traits(g)
            if t["haut"] is not None and t["bas"] is not None:
                blocs.append(t["bas"] - t["haut"])
    if len(fb) >= 2:
        return int(round(float(np.median(fb))))
    if len(blocs) >= 5:
        return int(round(float(np.median(blocs)))) + 4
    return None


def boite(g, cote_ext, fb, HR):
    """(y0, bord extérieur, sûr) de la boîte HR de haut. cote_ext : côté opposé au dos ; sûr : haut ET bas trouvés et cohérents."""
    h, w = g.shape
    t = traits(g)
    f = fond_sombre(g) if fb else {}
    haut = f.get("haut") if fb and f.get("haut") is not None else t["haut"]
    bas = f.get("bas") if fb and f.get("bas") is not None and f["bas"] < h - BORD else t["bas"]
    if haut is not None and bas is not None and abs((bas - haut) - HR) > 30:      # incohérents : on garde le plus proche du bord du scan
        if haut < h - bas:
            bas = None
        else:
            haut = None
    sur = haut is not None and bas is not None
    y0 = haut if haut is not None else (bas - HR if bas is not None else None)
    ext = f.get(cote_ext) if fb else None
    if ext is None or (cote_ext == "gauche" and ext <= BORD) or (cote_ext == "droite" and ext >= w - BORD):
        ext = t[cote_ext]
    if ext is None:
        ext = 0 if cote_ext == "gauche" else w
    return y0, ext, sur


# --- Page blanche ---------------------------------------------------------------------------------------------------------------------------

def cadres(g):
    """Masque des traits de cadre (longs traits droits fins, en biais compris) avec leurs petits trous bouchés."""
    h, w = g.shape
    lisse = cv2.medianBlur(g, 3)
    k = max(9, (min(h, w) // 70) | 1)
    papier = float(np.percentile(g, 95))
    fin = ((cv2.morphologyEx(lisse, cv2.MORPH_BLACKHAT, np.ones((k, k), np.uint8)) > 40) | (lisse < 0.25 * papier)).astype(np.uint8)
    fin &= 1 - cv2.morphologyEx(fin, cv2.MORPH_OPEN, np.ones((11, 11), np.uint8))     # un trait est fin : pas les aplats noirs
    L = max(41, w // 25)
    hor = cv2.morphologyEx(cv2.morphologyEx(fin, cv2.MORPH_OPEN, np.ones((1, L), np.uint8)), cv2.MORPH_CLOSE, np.ones((1, 61), np.uint8))
    ver = cv2.morphologyEx(cv2.morphologyEx(fin, cv2.MORPH_OPEN, np.ones((L, 1), np.uint8)), cv2.MORPH_CLOSE, np.ones((61, 1), np.uint8))
    res = hor | ver
    seg = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(lisse)[0]
    if seg is not None:
        pres = cv2.dilate(fin, np.ones((5, 5), np.uint8))
        for xa, ya, xb, yb in seg.reshape(-1, 4):
            if np.hypot(xb - xa, yb - ya) < max(40, w // 12):
                continue
            xs = np.clip(np.linspace(xa, xb, 12).round().astype(int), 0, w - 1)
            ys = np.clip(np.linspace(ya, yb, 12).round().astype(int), 0, h - 1)
            if pres[ys, xs].mean() >= 0.8:
                cv2.line(res, (int(xa), int(ya)), (int(xb), int(yb)), 1, 3)
    return cv2.dilate(res, np.ones((5, 5), np.uint8)) > 0


def couper_cases(c, rempli, cote_dos, epaisseur=3):
    """Page blanche coupée aux cadres (voir l'en-tête). `rempli` : papier ajouté hors du scan. Retour : image, masque des traits tracés."""
    h, w = c.shape
    papier = 255
    hor, ver = lignes_fines(c)
    pres = cv2.dilate(rempli.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    hor[pres] = 0
    ver[pres] = 0
    ch = cv2.dilate(hor, np.ones((3, 1), np.uint8)).sum(1) / w
    cv = cv2.dilate(ver, np.ones((1, 3), np.uint8)).sum(0) / h
    zh, zw = int(0.10 * h), int(0.12 * w)                 # marge sous le cadre jusqu à 8 % (folio), tranche jusqu à 9 % de la largeur (Nori Taka tome 2 pages 25 et 36)

    def premier(prof):
        """Le plus INTÉRIEUR des longs traits du bord (la tranche des pages du dessous et le bord du scan sont dehors, souvent plus longs)."""
        r = [(a, b, float(prof[a:b].max())) for a, b in runs(prof >= 0.15)]
        if not r:
            return 0
        m = max(x[2] for x in r)
        return int([x for x in r if x[2] >= 0.4 * m][-1][0])
    def cadre_hb(prof):
        """En haut et en bas : le trait du cadre est celui qui couvre le plus de largeur (le bord sombre du scan, collé au bord, est écarté ; un trait du
        dessin, le sol par exemple, est plus court). À couverture égale, le plus extérieur."""
        r = [(a, b, float(prof[a:b].max())) for a, b in runs(prof >= 0.15) if a >= 0.012 * h]
        if not r:
            return 0
        m = max(x[2] for x in r)
        return int([x for x in r if x[2] >= 0.85 * m][0][0])
    lim = {"haut": cadre_hb(ch[:zh]), "bas": cadre_hb(ch[::-1][:zh]), "gauche": premier(cv[:zw]), "droite": premier(cv[::-1][:zw])}
    # le vrai cadre est là où s'arrêtent les traits des cases qui le rejoignent (les traits horizontaux finissent sur le cadre vertical, et l'inverse) :
    # ni la tranche des pages du dessous, ni une trame verticale dans une case n'en reçoivent (Nori Taka tome 1 page 21, tome 2 page 36)
    def bouts(masque, axe, debut):
        n_, lab_, st_, _ = cv2.connectedComponentsWithStats(masque.astype(np.uint8), connectivity=8)
        long_ = 0.12 * (w if axe == 0 else h)
        v = []
        for j in range(1, n_):
            x_, y_, ww_, hh_ = st_[j, 0], st_[j, 1], st_[j, 2], st_[j, 3]
            if axe == 0 and ww_ >= long_:
                v.append(x_ if debut else w - (x_ + ww_))
            elif axe == 1 and hh_ >= long_:
                v.append(y_ if debut else h - (y_ + hh_))
        return v
    for cote, prof, n_zone, (masque, axe, debut) in (("gauche", cv, zw, (hor, 0, True)), ("droite", cv[::-1], zw, (hor, 0, False)),
                                                     ("haut", ch, zh, (ver, 1, True)), ("bas", ch[::-1], zh, (ver, 1, False))):
        b = [x for x in bouts(masque, axe, debut) if x < n_zone]
        if len(b) < 2:
            continue
        cible = float(np.median(b))
        cands = [a for a, b_ in runs(prof[:n_zone] >= 0.1)]
        proches = [a for a in cands if abs(a - cible) <= 8]
        if proches:
            lim[cote] = int(min(proches, key=lambda a: abs(a - cible)))
    # côté reliure : bande parasite (gris lisse ou traits) depuis le bord, coupée juste après
    t = c.T
    lp = ver.T
    if cote_dos == "droite":
        t, lp = t[::-1], lp[::-1]
    f = t.astype(np.float32)
    ecart = np.sqrt(np.maximum(cv2.blur(f * f, (5, 5)) - cv2.blur(f, (5, 5)) ** 2, 0))
    score = (((t > 0.35 * papier) & (t < 0.88 * papier) & (ecart < 8)) | (lp > 0)).mean(1)
    zone = int(0.07 * t.shape[0])
    k0 = 0
    while k0 < zone and t[k0].mean() > 0.97 * papier:
        k0 += 1
    fin = 0
    for k in range(k0, zone + k0):
        if score[k] > 0.45:                              # la bande du dos court sur presque toute la hauteur ; une trame grise dans une case non (Nori Taka tome 1 page 21)
            fin = k + 1
        elif k - max(fin, k0) > 4:
            break
    lim[cote_dos] = max(lim[cote_dos], fin + 3, k0 + int(0.015 * t.shape[0]))
    # jamais de texte coupé : une lettre (avec des voisines sur sa ligne) entre le bord et la coupe fait reculer la coupe juste avant elle
    enc = (c < 0.5 * papier).astype(np.uint8)
    e_ = h / 1040                                         # tailles de lettre mesurées sur une page de 1040 px (scans plus grands : lettres plus grandes)
    nl, labl, stl, cen = cv2.connectedComponentsWithStats(enc, connectivity=8)
    clair_ = c > 0.7 * papier
    encl = cv2.dilate(enc, np.ones((3, 3), np.uint8)).astype(bool)

    def sur_fond_clair(j):
        """Lettre : le liseré juste autour d'elle est clair (fond de bulle), même gras et même dans l'ombre légère du dos."""
        x_, y_, ww_, hh_ = stl[j, 0], stl[j, 1], stl[j, 2], stl[j, 3]
        m_ = max(2, int(3 * e_))
        ya, yb, xa, xb = max(0, y_ - m_), min(h, y_ + hh_ + m_), max(0, x_ - m_), min(w, x_ + ww_ + m_)
        autour = (labl[ya:yb, xa:xb] != j) & ~encl[ya:yb, xa:xb]          # le liseré gris des lettres voisines, collées, ne compte pas
        if not autour.any():
            return False
        fond = c[ya:yb, xa:xb][autour]
        if clair_[ya:yb, xa:xb][autour].mean() > 0.75:
            return 1
        # contre la reliure, le côté dos du liseré tombe dans l'ombre : on regarde seulement l'autre côté (Nori Taka tome 2 page 28)
        if cote_dos == "droite" and x_ + ww_ > 0.88 * w:
            cote_ = autour[:, :max(1, (xb - xa) // 2)]
            if cote_.any() and clair_[ya:yb, xa:xa + cote_.shape[1]][cote_].mean() > 0.75:
                return 1
        if cote_dos == "gauche" and x_ < 0.12 * w:
            k_ = (xb - xa) // 2
            cote_ = autour[:, k_:]
            if cote_.any() and clair_[ya:yb, xa + k_:xb][cote_].mean() > 0.75:
                return 1
        return 2 if (float(np.median(fond)) > 0.5 * papier and float(fond.std()) < 30) else 0    # ombre du dos : fond gris uni (2 : à confirmer)
    fonds = {j: sur_fond_clair(j) for j in range(1, nl) if 5 * e_ <= stl[j, 3] <= 48 * e_ and 2 * e_ <= stl[j, 2] <= 40 * e_}
    lettres = [j for j, f in fonds.items() if f]
    pc = np.array([cen[j] for j in lettres]) if lettres else np.zeros((0, 2))
    texte = []
    for i_, j in enumerate(lettres):
        mini = 1 if fonds[j] == 1 else 2                  # « ET », « OÙ » : deux lettres suffisent sur fond blanc ; sur fond gris, un mot (sinon les
        if np.sum((np.abs(pc[:, 1] - pc[i_, 1]) < 6 * e_) & (np.abs(pc[:, 0] - pc[i_, 0]) < 40 * e_)) - 1 < mini:   # salissures du bord du scan)
            continue
        x_, y_, ww_, hh_ = stl[j, 0], stl[j, 1], stl[j, 2], stl[j, 3]
        texte.append((x_, y_, ww_, hh_))
        dist = {"haut": y_, "bas": h - (y_ + hh_), "gauche": x_, "droite": w - (x_ + ww_)}
        for cote in lim:
            plancher = k0 if cote == cote_dos else 0
            if plancher <= dist[cote] < lim[cote]:
                lim[cote] = max(plancher, dist[cote] - 2)
    y0, y1, x0, x1 = lim["haut"], h - lim["bas"], lim["gauche"], w - lim["droite"]
    # cases fermées par les traits et le cadre de coupe ; le reste relié au cadre devient papier
    tr = cadres(c)
    tr[pres] = False
    bord = np.zeros((h, w), bool)
    bord[y0:y0 + epaisseur, x0:x1] = True
    bord[y1 - epaisseur:y1, x0:x1] = True
    bord[y0:y1, x0:x0 + epaisseur] = True
    bord[y0:y1, x1 - epaisseur:x1] = True
    dedans = np.zeros((h, w), bool)
    dedans[y0:y1, x0:x1] = True
    libre = dedans & ~tr & ~bord
    n, lab, st, _ = cv2.connectedComponentsWithStats(libre.astype(np.uint8), connectivity=4)
    dt = cv2.distanceTransform(libre.astype(np.uint8), cv2.DIST_L2, 3)
    large = np.zeros(n, np.float32)
    np.maximum.at(large, lab.ravel(), dt.ravel())
    case = (large >= 14) & (st[:, cv2.CC_STAT_AREA] >= 0.004 * h * w)
    case[0] = False
    touche = np.zeros(n, bool)
    touche[np.unique(lab[(cv2.dilate(bord.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & libre])] = True
    dehors_lab = touche & ~case
    dehors_lab[0] = False
    s_ = c.copy()
    s_[~dedans] = papier
    s_[dehors_lab[lab]] = papier
    noir = int(np.percentile(c[tr & dedans], 20)) if (tr & dedans).any() else 20
    trace = np.zeros((h, w), bool)
    estcase = case[lab] & libre
    D = max(10, int(0.02 * h))

    def texte_avant(cote):
        d = [{"haut": y_ - y0, "bas": y1 - (y_ + hh_), "gauche": x_ - x0, "droite": x1 - (x_ + ww_)}[cote] for x_, y_, ww_, hh_ in texte
             if x0 <= x_ < x1 and y0 <= y_ < y1]
        d = [v for v in d if v >= 0]
        return min(d) if d else 10 ** 6
    final = {}
    for cote in ("haut", "bas", "gauche", "droite"):
        vues = [s_[y0:y1, x0:x1], tr[y0:y1, x0:x1], estcase[y0:y1, x0:x1], trace[y0:y1, x0:x1]]
        if cote == "bas":
            vues = [v[::-1] for v in vues]
        elif cote == "gauche":
            vues = [v.T for v in vues]
        elif cote == "droite":
            vues = [v.T[::-1] for v in vues]
        vs, vt, vc, tv = vues
        v = vc[:D + epaisseur + 4].any(0)                # une case arrive jusqu'à la coupe
        v = cv2.morphologyEx(v.astype(np.uint8).reshape(1, -1), cv2.MORPH_CLOSE, np.ones((1, 9), np.uint8)).ravel() > 0
        troncons = [(a_, b_) for a_, b_ in runs(v) if b_ - a_ >= 15]
        if not troncons:
            continue
        p = 0                                            # UN trait droit par côté, à la place de l'ancien trait le plus enfoncé ; devant : effacé
        for a_, b_ in troncons:
            prof = np.array([(np.where(vt[:D, j])[0][-1] if vt[:D, j].any() else -1) for j in range(a_, b_)])
            if (prof >= 0).mean() > 0.3:
                p = max(p, int(np.percentile(prof[prof >= 0], 90)) + 1)
        p = max(0, min(p, texte_avant(cote) - epaisseur - 2))
        final[cote] = p
        # le trait n'est tracé que là où le dessin (ou son ancien trait) arrive jusqu'à la coupe : une marge blanche entre la coupe et l'image n'est pas
        # une case (sinon un cadre inventé au bord de la page, à un centimètre du dessin : Nori Taka tomes 1 et 2, moitiés recoupées à la main)
        dessin = (vs[p:p + epaisseur + 8] < 0.6 * papier).any(0) | vt[max(0, p - 6):p + 2].any(0)     # ou un ancien trait de cadre, remplacé
        dessin = cv2.morphologyEx(dessin.astype(np.uint8).reshape(1, -1), cv2.MORPH_CLOSE, np.ones((1, 15), np.uint8)).ravel() > 0
        vs[:p, :] = papier
        for a_, b_ in troncons:
            for c0, c1 in runs(dessin[a_:b_]):
                if c1 - c0 >= 15:
                    vs[p:p + epaisseur, a_ + c0:a_ + c1] = np.minimum(vs[p:p + epaisseur, a_ + c0:a_ + c1], noir)
                    tv[p:p + epaisseur, a_ + c0:a_ + c1] = True
    fy0, fy1 = y0 + final.get("haut", 0), y1 - final.get("bas", 0)
    fx0, fx1 = x0 + final.get("gauche", 0), x1 - final.get("droite", 0)
    # dernier contrôle : une lettre (petite tache d'encre entourée de clair) coupée par le bord gardé fait reculer ce bord jusqu'à la contenir
    # entière (Nori Taka tome 2 page 28 : « SOIT UN » contre la reliure)
    for _ in range(3):
        bouge = False
        for j in range(1, nl):
            x_, y_, ww_, hh_ = stl[j, 0], stl[j, 1], stl[j, 2], stl[j, 3]
            if not (5 * e_ <= hh_ <= 48 * e_ and ww_ <= 40 * e_) or not fonds.get(j):
                continue
            if y_ + hh_ <= fy0 or y_ >= fy1 or x_ + ww_ <= fx0 or x_ >= fx1:
                continue                                  # entièrement dehors
            if x_ < fx0: fx0, bouge = max(0, x_ - 2), True
            if x_ + ww_ > fx1: fx1, bouge = min(w, x_ + ww_ + 2), True
            if y_ < fy0: fy0, bouge = max(0, y_ - 2), True
            if y_ + hh_ > fy1: fy1, bouge = min(h, y_ + hh_ + 2), True
        if not bouge:
            break
    if (fy0, fy1, fx0, fx1) != (y0 + final.get("haut", 0), y1 - final.get("bas", 0), x0 + final.get("gauche", 0), x1 - final.get("droite", 0)):
        s_[fy0:fy1, fx0:fx1] = np.where(trace[fy0:fy1, fx0:fx1], c[fy0:fy1, fx0:fx1], s_[fy0:fy1, fx0:fx1])     # le trait tracé en travers d'une lettre s'efface
        trace[:] = False
    garde = np.zeros((h, w), bool)
    garde[fy0:fy1, fx0:fx1] = True
    s_[~garde] = papier
    trace[~garde] = False
    return s_, trace


def fermer_cases(c, epaisseur=3):
    """Page blanche : chaque case est un rectangle entre les gouttières blanches ; un côté de case qui arrive au bord du dessin sans trait (coupé par le
    scan) reçoit un trait droit sur toute la longueur de la case, juste à l'extérieur. Seulement pour une case qui a déjà un vrai trait sur au moins un
    autre côté (une illustration ou un titre à fond perdu reste ouvert). Retour : image, masque des traits tracés."""
    h, w = c.shape
    papier = float(np.percentile(c, 95))
    encre = c < 0.6 * papier
    fin = encre | (cv2.morphologyEx(c, cv2.MORPH_BLACKHAT, np.ones((7, 7), np.uint8)) > 25)      # un trait de cadre gris pâle du scan compte
    traits = np.zeros((h, w), bool)
    rects = []

    def decouper(y0, y1, x0, x1, prof):
        z = encre[y0:y1, x0:x1]
        for axe in ((0, 1) if prof % 2 == 0 else (1, 0)):
            blanc = z.mean(1 - axe) < 0.004
            for a_, b_ in runs(blanc):                    # une gouttière a une épaisseur : 1 à 3 lignes blanches dans un dessin n'en sont pas une
                if b_ - a_ < 0.006 * (h if axe == 0 else w):
                    blanc[a_:b_] = False
            parts = [(a, b) for a, b in runs(~blanc) if b - a >= (0.04 * h if axe == 0 else 0.06 * w)]
            if len(parts) > 1 and prof < 7:
                for a, b in parts:
                    if axe == 0:
                        decouper(y0 + a, y0 + b, x0, x1, prof + 1)
                    else:
                        decouper(y0, y1, x0 + a, x0 + b, prof + 1)
                return
        rects.append((y0, y1, x0, x1))

    rows, cols = np.where(encre.mean(1) > 0.004)[0], np.where(encre.mean(0) > 0.004)[0]
    if len(rows) < 10 or len(cols) < 10:
        return c, traits
    Y0, Y1, X0, X1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    decouper(Y0, Y1, X0, X1, 0)
    noir = int(np.percentile(c[encre], 10)) if encre.any() else 20
    s_ = c.copy()
    marge = max(4, int(0.03 * min(h, w)))
    for y0, y1, x0, x1 in rects:
        z = encre[y0:y1, x0:x1]
        r_ = np.where(z.mean(1) > 0.02)[0]
        c_ = np.where(z.mean(0) > 0.02)[0]
        if len(r_) < 20 or len(c_) < 20:
            continue
        y0, y1, x0, x1 = y0 + r_[0], y0 + r_[-1] + 1, x0 + c_[0], x0 + c_[-1] + 1
        if y1 - y0 < 0.06 * h or x1 - x0 < 0.08 * w:
            continue
        d = max(4, int(0.02 * min(h, w)))              # un trait existant un peu penché ou interrompu compte aussi (sinon : trait doublé)
        def meilleur(bande, axe):
            return float(bande.mean(axe).max()) if bande.size else 0.0
        cote = {"haut": meilleur(fin[max(0, y0 - d):y0 + d, x0:x1], 1), "bas": meilleur(fin[y1 - d:y1 + d, x0:x1], 1),
                "gauche": meilleur(fin[y0:y1, max(0, x0 - d):x0 + d], 0), "droite": meilleur(fin[y0:y1, x1 - d:x1 + d], 0)}
        cote = {k: (1.0 if v >= 0.3 else v) for k, v in cote.items()}      # un trait déjà là, même pâle ou interrompu : pas de second trait
        pleine = len(rects) == 1 and (y1 - y0) * (x1 - x0) >= 0.8 * (Y1 - Y0) * (X1 - X0)
        if pleine:                                        # une seule image sur toute la page : son cadre en fait tout le tour (Nori Taka tomes 2-3)
            # le bord du dessin touche forcément de l'encre : on cherche un vrai trait droit (long, fin) le long de chaque côté
            lh, lv = lignes_fines(c)
            def trait(bande, axe):
                return float(bande.any(axe).mean()) if bande.size else 0.0
            cote = {"haut": trait(lh[max(0, y0 - d):y0 + d, x0:x1], 0), "bas": trait(lh[y1 - d:y1 + d, x0:x1], 0),
                    "gauche": trait(lv[y0:y1, max(0, x0 - d):x0 + d], 1), "droite": trait(lv[y0:y1, x1 - d:x1 + d], 1)}
            cote = {k: (1.0 if v >= 0.6 else 0.0) for k, v in cote.items()}
        elif max(cote.values()) < 0.9:                    # aucune vraie bordure : case ouverte, on n'invente rien
            continue
        au_bord = {"haut": y0 - Y0 <= marge, "bas": Y1 - y1 <= marge, "gauche": x0 - X0 <= marge, "droite": X1 - x1 <= marge}
        if pleine:
            au_bord = dict.fromkeys(au_bord, True)
        # le trait se pose au bord du dessin de toute la page de ce côté (les cases d'un même bord restent alignées), jamais sur du texte ou du dessin
        bx0, bx1, by0, by1 = x0, x1, y0, y1
        x0 = X0 if au_bord["gauche"] else x0
        x1 = X1 if au_bord["droite"] else x1
        y0 = Y0 if au_bord["haut"] else y0
        y1 = Y1 if au_bord["bas"] else y1
        for k, v in cote.items():
            if v >= 0.9 or not au_bord[k]:
                continue
            if k == "haut":
                ya = max(0, y0 - epaisseur); sl = np.s_[ya:ya + epaisseur, bx0:bx1]
            elif k == "bas":
                ya = min(h - epaisseur, y1); sl = np.s_[ya:ya + epaisseur, bx0:bx1]
            elif k == "gauche":
                xa = max(0, x0 - epaisseur); sl = np.s_[by0:by1, xa:xa + epaisseur]
            else:
                xa = min(w - epaisseur, x1); sl = np.s_[by0:by1, xa:xa + epaisseur]
            s_[sl] = noir
            traits[sl] = True
        x0, x1, y0, y1 = bx0, bx1, by0, by1
    return s_, traits


# --- Flash-back -----------------------------------------------------------------------------------------------------------------------------

def liseres_noirs(g, papier):
    """Le mince liseré clair du bord du scan (papier hors du fond noir) devient noir ; une case claire qui va jusqu'au bord est plus longue."""
    g = g.copy()
    h, w = g.shape
    noir = int(min(25, np.percentile(g, 1)))
    lisse = cv2.medianBlur(g, 5)
    for vue, n in ((lisse, int(0.04 * w)), (lisse.T, int(0.03 * h))):
        cible = g if vue is lisse else g.T
        for sens in (1, -1):
            v, c = vue[:, ::sens], cible[:, ::sens]
            for i in range(v.shape[0]):
                ligne = v[i, :n + 8]
                d0 = 0
                while d0 < n and ligne[d0] < 0.6 * papier:
                    d0 += 1
                k = d0
                while k < n and ligne[k] >= 0.6 * papier:
                    k += 1
                if d0 < k < n and (ligne[k:k + 8] < 0.6 * papier).mean() > 0.7:
                    c[i, d0:k] = noir
    return g


def fond_rempli(g, rempli=None):
    """Fond relié au bord de la page sans traverser un trait de cadre, sombre presque partout autour de lui : noir franc. Une case claire à fond perdu
    (pas fermée) l'arrête. Les restes clairs minces et longs du fond (bord de page, bord du scan) deviennent noirs aussi."""
    h, w = g.shape
    papier = float(np.percentile(g, 95))
    g = liseres_noirs(g, papier)
    tr = cadres(g)
    if rempli is not None:                               # la limite du scan est un bord droit : une case coupée par elle reste fermée
        r = rempli.astype(bool)
        tr |= (cv2.dilate(r.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0) & ~r
    n, lab = cv2.connectedComponents((~tr).astype(np.uint8), connectivity=4)
    touche = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    dehors = np.isin(lab, touche[touche > 0])
    sombre = dehors & (cv2.medianBlur(g, 7) < 0.82 * papier) & (g < 0.88 * papier)
    r = max(25, w // 25) | 1
    D = cv2.blur(sombre.astype(np.float32), (r, r)) / np.maximum(cv2.blur(dehors.astype(np.float32), (r, r)), 1e-3)
    zone = cv2.morphologyEx((sombre & (D > 0.55)).astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    nz0, labz0, stz0, _ = cv2.connectedComponentsWithStats(zone, connectivity=8)
    e = max(4, w // 60)
    bordj = set(np.unique(np.concatenate([labz0[:e].ravel(), labz0[-e:].ravel(), labz0[:, :e].ravel(), labz0[:, -e:].ravel()]))) - {0}
    zone = np.isin(labz0, [j for j in bordj if stz0[j, cv2.CC_STAT_AREA] >= 0.01 * h * w])
    zone = cv2.dilate(zone.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & sombre
    zone |= tr & cv2.dilate(zone.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) & (g < 0.6 * papier)
    noir = int(min(25, np.percentile(g, 1)))
    sortie = g.copy()
    sortie[zone] = noir
    clair = (dehors & (sortie >= 0.35 * papier)).astype(np.uint8)
    nc, labc, stc, _ = cv2.connectedComponentsWithStats(clair, connectivity=8)
    for j in range(1, nc):
        long_ = max(stc[j, cv2.CC_STAT_WIDTH], stc[j, cv2.CC_STAT_HEIGHT])
        if long_ >= 30 and stc[j, cv2.CC_STAT_AREA] <= 12 * long_:
            sortie[labc == j] = noir
    return sortie


def fond_cases(g, rempli=None, seuil_g=0.93):
    """Cases = rectangles droits entre les gouttières sombres (découpe alternée horizontale / verticale, gouttières droites en biais suivies) ; leur
    intérieur n'est jamais touché, tout le reste devient noir sauf les lignes de texte. Retour : image, masque des cases."""
    h, w = g.shape
    papier = float(np.percentile(g, 95))
    sombre = cv2.medianBlur(g, 5) < 0.6 * papier
    if rempli is not None:
        sombre |= rempli.astype(bool)
    cases = np.zeros((h, w), bool)
    rects = []
    mh, mw = int(0.02 * h), int(0.03 * w)

    def decouper(y0, y1, x0, x1, prof, poly=None):
        z = sombre[y0:y1, x0:x1] if poly is None else (sombre | ~poly)[y0:y1, x0:x1]
        for axe in ((0, 1) if prof % 2 == 0 else (1, 0)):
            pr = z.mean(1 - axe) > (seuil_g if prof == 0 else 0.9)
            parts = _suites(~pr, mh if axe == 0 else mw)
            if (len(parts) > 1 or (parts and (parts[0][0] > 0 or parts[-1][1] < len(pr)))) and prof < 6:
                for a_, b_ in parts:
                    if axe == 0:
                        decouper(y0 + a_, y0 + b_, x0, x1, prof + 1, poly)
                    else:
                        decouper(y0, y1, x0 + a_, x0 + b_, prof + 1, poly)
                return
        if poly is not None:
            cases[y0:y1, x0:x1] |= poly[y0:y1, x0:x1]
        elif not biais(y0, y1, x0, x1, prof):
            cases[y0:y1, x0:x1] = True
            rects.append((y0, y1, x0, x1))

    def biais(y0, y1, x0, x1, prof):
        """Gouttière droite en biais qui traverse la case de part en part : la case est coupée le long d'elle, chaque morceau est redécoupé."""
        hh, ww = y1 - y0, x1 - x0
        if hh < 60 or ww < 60:
            return False
        meilleur = None
        for vertical in (True, False):
            L, T = (ww, hh) if vertical else (hh, ww)
            ts = np.arange(0, T, 3)
            pos = np.arange(int(0.08 * L), int(0.92 * L), 3)
            for a in pos:
                for b in pos[np.abs(pos - a) <= 0.35 * T]:
                    if a == b:
                        continue
                    u = (a + (b - a) * ts / T).astype(int)
                    ys, xs = (y0 + ts, x0 + u) if vertical else (y0 + u, x0 + ts)
                    fr = sombre[ys, xs].mean()
                    if fr > 0.95 and (meilleur is None or fr > meilleur[0]):
                        meilleur = (fr, vertical, a, b)
        if meilleur is None:
            return False
        _, vertical, a, b = meilleur
        T = hh if vertical else ww
        ts = np.arange(0, T, 3)
        larg = 1
        while larg < 25:
            ok = True
            for dd in (-larg - 1, larg + 1):
                u = np.clip((a + dd + (b - a) * ts / T).astype(int), 0, (ww if vertical else hh) - 1)
                ys, xs = (y0 + ts, x0 + u) if vertical else (y0 + u, x0 + ts)
                ok &= sombre[ys, xs].mean() > 0.85
            if not ok:
                break
            larg += 1
        if vertical:
            morceaux = (np.array([[x0, y0], [x0 + a - larg, y0], [x0 + b - larg, y1], [x0, y1]], np.int32),
                        np.array([[x0 + a + larg, y0], [x1, y0], [x1, y1], [x0 + b + larg, y1]], np.int32))
        else:
            morceaux = (np.array([[x0, y0], [x1, y0], [x1, y0 + b - larg], [x0, y0 + a - larg]], np.int32),
                        np.array([[x0, y0 + a + larg], [x1, y0 + b + larg], [x1, y1], [x0, y1]], np.int32))
        for morceau in morceaux:
            m = np.zeros((h, w), np.uint8)
            cv2.fillPoly(m, [morceau], 1)
            m[:y0] = 0
            m[y1:] = 0
            m[:, :x0] = 0
            m[:, x1:] = 0
            ys_, xs_ = np.where(m > 0)
            if len(ys_):
                decouper(ys_.min(), ys_.max() + 1, xs_.min(), xs_.max() + 1, prof + 1, m > 0)
        return True

    decouper(0, h, 0, w, 0)
    # une bulle qui déborde de sa case agrandit le rectangle : au-delà du vrai trait de la case, et sur l'aplat du ton du fond qui touche le bord
    # du rectangle, le fond passe au noir
    bh = cv2.morphologyEx(cv2.medianBlur(g, 3), cv2.MORPH_BLACKHAT, np.ones((15, 15), np.uint8)) > 40
    vert = cv2.morphologyEx(bh.astype(np.uint8), cv2.MORPH_OPEN, np.ones((31, 1), np.uint8))
    hori = cv2.morphologyEx(bh.astype(np.uint8), cv2.MORPH_OPEN, np.ones((1, 31), np.uint8))
    a_noircir = np.zeros((h, w), bool)
    for y0, y1, x0, x1 in rects:
        hh, ww = y1 - y0, x1 - x0
        cvv = cv2.dilate(vert[y0:y1, x0:x1], np.ones((1, 3), np.uint8)).mean(0)
        chh = cv2.dilate(hori[y0:y1, x0:x1], np.ones((3, 1), np.uint8)).mean(1)
        for cote in ("gauche", "droite", "haut", "bas"):
            pr, n_ = (cvv, ww) if cote in ("gauche", "droite") else (chh, hh)
            z_ = int(0.3 * n_)
            idx = np.arange(5, z_) if cote in ("gauche", "haut") else np.arange(n_ - 6, n_ - z_, -1)
            ok_ = [i for i in idx if pr[i] >= 0.6]
            if not ok_:
                continue
            i = ok_[0]
            sl = {"gauche": np.s_[y0:y1, x0:x0 + i], "droite": np.s_[y0:y1, x0 + i + 1:x1],
                  "haut": np.s_[y0:y0 + i, x0:x1], "bas": np.s_[y0 + i + 1:y1, x0:x1]}[cote]
            if sombre[sl].size and sombre[sl].mean() >= 0.5:
                a_noircir[sl] = True
    noir = int(min(25, np.percentile(g, 1)))
    dehors = ~cases
    clair = (dehors & (g >= 0.7 * papier)).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(clair, connectivity=8)
    petits = [j for j in range(1, n) if 6 <= max(st[j, cv2.CC_STAT_WIDTH], st[j, cv2.CC_STAT_HEIGHT]) <= 28]
    pc = np.array([cen[j] for j in petits]) if petits else np.zeros((0, 2))
    lettre = np.zeros(n, bool)
    for i_, j in enumerate(petits):                       # une lettre a des voisines sur sa ligne (pas une poussière isolée)
        if np.sum((np.abs(pc[:, 1] - pc[i_, 1]) < 8) & (np.abs(pc[:, 0] - pc[i_, 0]) < 60)) - 1 >= 2:
            lettre[j] = True
    garde = cv2.dilate((lettre[lab] & (clair > 0)).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & dehors
    fondv = g[dehors & sombre & ~(rempli.astype(bool) if rempli is not None else np.zeros_like(sombre))]
    if fondv.size > 1000:
        ton = float(np.median(fondv))
        f32 = cv2.GaussianBlur(g, (0, 0), 1.5).astype(np.float32)
        ecart = np.sqrt(np.maximum(cv2.blur(f32 * f32, (7, 7)) - cv2.blur(f32, (7, 7)) ** 2, 0))
        aplat = (np.abs(f32 - ton) < 28) & (ecart < 9)
        for y0, y1, x0, x1 in rects:
            z = aplat[y0:y1, x0:x1].astype(np.uint8)
            n_, lab_, st_, _ = cv2.connectedComponentsWithStats(z, connectivity=4)
            for j in set(np.unique(np.concatenate([lab_[:3].ravel(), lab_[-3:].ravel(), lab_[:, :3].ravel(), lab_[:, -3:].ravel()]))) - {0}:
                if st_[j, cv2.CC_STAT_AREA] >= 0.01 * z.size:
                    a_noircir[y0:y1, x0:x1] |= lab_ == j
    sortie = g.copy()
    sortie[dehors & ~garde] = noir
    sortie[a_noircir & sombre] = noir
    return sortie, cases


def flashback(a, rempli):
    """Flash-back fini (après les retouches) : (image, masque du contenu)."""
    a = liseres_noirs(a, float(np.percentile(a, 95)))     # le papier au-delà du fond noir n'est pas une case
    fc, cs = fond_cases(a, rempli=rempli)
    if cs.mean() < 0.85:
        return fc, cs
    a = fond_rempli(a, rempli=rempli)                     # demi flash-back : pas de découpe d'emblée
    a, contenu = fond_cases(a, rempli=rempli, seuil_g=0.8)
    h, w = a.shape
    _, ver = lignes_fines(a)
    cv = cv2.dilate(ver, np.ones((1, 3), np.uint8)).sum(0) / h
    noir = int(min(25, np.percentile(a, 1)))
    d = int(0.8 * w) + np.where(cv[int(0.8 * w):] >= 0.3)[0]
    if len(d):                                           # coupe droite quelques px à l'intérieur du dernier groupe de traits (la bande collée part avec)
        k = len(d) - 1
        while k > 0 and d[k] - d[k - 1] <= 6:
            k -= 1
        x = int(d[k]) - 8
        a[:, x:] = noir
        contenu[:, x:] = False
    g_ = np.where(cv[:int(0.2 * w)] >= 0.3)[0]
    if len(g_):
        k = 0
        while k < len(g_) - 1 and g_[k + 1] - g_[k] <= 6:
            k += 1
        x = int(g_[k]) + 8
        a[:, :x] = noir
        contenu[:, :x] = False
    return a, contenu


# --- Une page, un tome -----------------------------------------------------------------------------------------------------------------------

def retoucher(c, regl, taille):
    """Retouches ✨ sur la page coupée mise à la taille finale (l'IA travaille à la résolution du scan, voir optimiser._ia_page). L'IA bouche l'œil des
    petits caractères (récitatifs : « e » lu « o », quel que soit le niveau d'IA ou de noirs, constaté sur Nori Taka tome 2 page 32) : les blocs de
    petit texte sur fond blanc gardent l'agrandissement simple, recalé et rendu net."""
    import optimiser
    import ia
    W, H = taille
    brut = cv2.resize(c, (W, H), interpolation=cv2.INTER_CUBIC)
    out = np.array(optimiser.ameliorer(Image.fromarray(brut), regl, source=H / c.shape[0]).convert("L"))
    if out.shape != (H, W):
        out = cv2.resize(out, (W, H), interpolation=cv2.INTER_AREA)
    if not regl.get("ia"):
        return out
    m = blocs_petit_texte(c)
    if m is None:
        return out
    m = cv2.resize(m.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(np.float32)
    doux = ia._nettete(ia._niveaux(brut), sigma=1.2, force=0.9)
    a = cv2.GaussianBlur(m, (0, 0), 3)
    return np.clip(out * (1 - a) + np.minimum(doux, out.max()) * a, 0, 255).astype(np.uint8)


def blocs_petit_texte(g):
    """Masque des blocs de petits caractères sur fond blanc (au moins deux lignes de lettres alignées), ou None. `g` : page à la résolution du scan."""
    h, w = g.shape
    e = h / 1040
    papier = float(np.percentile(g, 95))
    enc = (g < 0.55 * papier).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(enc, connectivity=8)
    hh, ww, aire = st[:, cv2.CC_STAT_HEIGHT], st[:, cv2.CC_STAT_WIDTH], st[:, cv2.CC_STAT_AREA]
    ok = (hh >= 4) & (hh <= 8 * e) & (ww >= 2) & (ww <= 14 * e) & (aire >= 0.35 * ww * hh)      # petites lettres grasses (pas les traits fins)
    ok[0] = False
    m0 = ok[lab].astype(np.uint8)
    if m0.sum() < 100:
        return None
    lignes = cv2.morphologyEx(m0, cv2.MORPH_CLOSE, np.ones((int(4 * e) | 1, int(9 * e) | 1), np.uint8))
    blocs = cv2.morphologyEx(lignes, cv2.MORPH_CLOSE, np.ones((int(8 * e) | 1, int(5 * e) | 1), np.uint8))
    nb, lb, sb, _ = cv2.connectedComponentsWithStats(blocs, connectivity=8)
    clair = g > 0.8 * papier
    masque = np.zeros((h, w), bool)
    for k in range(1, nb):
        x, y, bw, bh = sb[k, 0], sb[k, 1], sb[k, 2], sb[k, 3]
        if bw < 25 * e or bh < 10 * e or bh > 120 * e:
            continue
        zone = lb[y:y + bh, x:x + bw] == k
        if len(np.unique(lab[y:y + bh, x:x + bw][zone & (m0[y:y + bh, x:x + bw] > 0)])) < 15:      # au moins une quinzaine de lettres
            continue
        fond = ~enc[y:y + bh, x:x + bw].astype(bool) & zone
        if not fond.any() or clair[y:y + bh, x:x + bw][fond].mean() < 0.7:       # du texte posé sur du blanc (liseré gris des lettres compris), pas une trame
            continue
        if m0[y:y + bh, x:x + bw][zone].mean() < 0.2:
            continue
        masque[y:y + bh, x:x + bw] |= zone
    return masque if masque.any() else None


def cote_du_dos(g):
    """Page simple : côté de la reliure, celui dont la bande du bord est la plus grise et lisse (ombre, tranche)."""
    h, w = g.shape
    f = g.astype(np.float32)
    ecart = np.sqrt(np.maximum(cv2.blur(f * f, (5, 5)) - cv2.blur(f, (5, 5)) ** 2, 0))
    gris = (g > 90) & (g < 225) & (ecart < 8)
    b = max(8, int(0.06 * w))
    return "gauche" if gris[:, :b].mean() > gris[:, -b:].mean() else "droite"


def sans_folio(contenu):
    """Le numéro de page (petite tache isolée en haut ou en bas, hors des cases) ne compte pas dans le contenu : sinon une bande blanche restait sous
    les cases (Nori Taka tomes 1 et 3)."""
    h, w = contenu.shape
    n, lab, st, _ = cv2.connectedComponentsWithStats(contenu.astype(np.uint8), connectivity=8)
    grands = [j for j in range(1, n) if st[j, cv2.CC_STAT_AREA] >= 0.002 * h * w]
    if not grands:
        return contenu
    y0 = min(st[j, cv2.CC_STAT_TOP] for j in grands)
    y1 = max(st[j, cv2.CC_STAT_TOP] + st[j, cv2.CC_STAT_HEIGHT] for j in grands)
    sortie = contenu.copy()
    for haut in (True, False):
        bande = [j for j in range(1, n) if (st[j, cv2.CC_STAT_TOP] + st[j, cv2.CC_STAT_HEIGHT] <= min(y0, 0.08 * h)) if haut]
        bande = bande if haut else [j for j in range(1, n) if st[j, cv2.CC_STAT_TOP] >= max(y1, 0.92 * h)]
        if 0 < len(bande) <= 4 and all(st[j, cv2.CC_STAT_AREA] < 0.002 * h * w for j in bande):     # 1 à 4 chiffres ; une ligne de texte : plus
            for j in bande:
                sortie[lab == j] = False
    return sortie


def paires(tailles):
    """[(gauche, droite)] : pages simples consécutives de hauteurs proches (les deux moitiés d'un même scan double page ; recoupées à la main, la
    hauteur peut varier de quelques px et la largeur davantage : constaté sur Nori Taka tome 1)."""
    def cout(i):
        """Écart entre les pages i et i + 1 si ce peuvent être les deux moitiés d'un scan, sinon None."""
        (wa, ha), (wb, hb) = tailles[i], tailles[i + 1]
        if abs(ha - hb) <= 0.02 * max(ha, hb) and abs(wa - wb) <= 0.12 * max(wa, wb) and wa < 0.8 * ha and wb < 0.8 * hb:
            return abs(ha - hb) / max(ha, hb) + abs(wa - wb) / max(wa, wb)
        return None
    # le plus de paires possible et, à nombre égal, les moitiés les plus semblables (un appariement glouton décalait tout après une page seule :
    # Nori Taka tome 3, page 6 laissée de côté)
    n = len(tailles)
    meilleur = [(0, 0.0, None)] * (n + 2)                 # meilleur[i] = (paires, -écart, choix) pour les pages i et suivantes
    for i in range(n - 1, -1, -1):
        sans = meilleur[i + 1][:2]
        choix = (sans[0], sans[1], "seule")
        c = cout(i) if i + 1 < n else None
        if c is not None:
            avec = (meilleur[i + 2][0] + 1, meilleur[i + 2][1] - c)
            if avec > sans:
                choix = (avec[0], avec[1], "paire")
        meilleur[i] = choix
    res, i = [], 0
    while i < n:
        if meilleur[i][2] == "paire":
            res.append((i, i + 1))
            i += 2
        else:
            i += 1
    return res


def placer(gauche, droite, est_gauche, fb, HR, WR, partenaire_y):
    """La page (moitié gauche ou droite du scan) dans sa boîte HR × WR : (image, papier ajouté hors du scan)."""
    g = gauche if est_gauche else droite
    cote_ext = "gauche" if est_gauche else "droite"
    y0, ext, sur = boite(g, cote_ext, fb, HR)
    if partenaire_y is not None and (not sur or y0 is None):
        y0 = partenaire_y                                 # le haut de l'autre moitié du même scan, plus sûr
    if y0 is None:
        y0 = (g.shape[0] - HR) // 2
    planche = np.hstack([gauche, droite])
    dx = 0 if est_gauche else gauche.shape[1]
    m = int(0.05 * g.shape[1])                            # un peu de marge côté extérieur : du texte peut déborder du cadre des cases voisines
    gw = g.shape[1]                                        # (Nori Taka tome 1 page 6), mais seulement si le côté dos reste entier (sinon le
    if est_gauche:                                         # texte près de la reliure était coupé : tome 2 page 28)
        x0 = max(ext - m, min(ext, gw - WR)) + dx
    else:
        x0 = min(ext - WR + m, max(ext - WR, 0)) + dx
    if WR < g.shape[1]:                                   # boîte plus étroite que la page (format différent de la sortie) : elle couvre toute la largeur,
        HR2 = int(np.ceil(g.shape[1] * HR / WR))          # la coupe aux cadres retire les parasites (sinon du texte était coupé : Nori Taka tome 2)
        y0 -= (HR2 - HR) // 2
        HR, WR, x0 = HR2, g.shape[1], dx
    H, W = planche.shape
    c = np.full((HR, WR), int(np.percentile(g, 2)) if fb else int(np.percentile(g, 95)), np.uint8)
    ya, yb, xa, xb = max(0, y0), min(H, y0 + HR), max(0, x0), min(W, x0 + WR)
    lo, hi = (0, gauche.shape[1]) if est_gauche else (gauche.shape[1], W)        # jamais l'autre page du scan
    xa, xb = max(xa, lo), min(xb, hi)
    rempli = np.ones((HR, WR), bool)
    if xb > xa and yb > ya:
        c[ya - y0:yb - y0, xa - x0:xb - x0] = planche[ya:yb, xa:xb]
        rempli[ya - y0:yb - y0, xa - x0:xb - x0] = False
    return c, rempli


def recadrer_tome(chemin, source, boites, taille, retouches, destination, progres=None, retoucher_autres=None, paires_connues=None, seules=None) -> dict:
    """Écrit dans `destination` le tome recadré aux cases. `source` : fichier des pages d'origine ; `boites` : cadres réglés à la main {numéro: boîte}
    (mesure du redressement) ; `taille` : (W, H) des pages finales ; `retouches` : réglages ✨ à appliquer (sans redresser ni flash-back, faits ici).
    Les pages hors paires sont recopiées du tome actuel ; `retoucher_autres` (numéros) : celles-là sont plutôt mises à la taille (double page : 2W × H)
    et retouchées comme les autres (tome refait depuis l'archive d'origine). Retour : {"pages", "flashbacks", "hauteur", "zoom"}."""
    import optimiser
    W, H = int(taille[0]), int(taille[1])
    ordre_s, ordre = archives.pages(source), archives.pages(chemin)
    if len(ordre_s) != len(ordre):
        raise RuntimeError("le tome n'a plus le même nombre de pages que ses pages d'origine")
    with zipfile.ZipFile(source) as zs:
        tailles = [Image.open(io.BytesIO(zs.read(n))).size for n in ordre_s]
    lp = paires_connues if paires_connues is not None else paires(tailles)      # paires sûres (tome refait depuis l'archive) ou devinées
    regl = optimiser.reglages_amelioration({k: v for k, v in (retouches or {}).items() if k not in ("redresser", "flashback", "recadrer")})
    tmp = Path(tempfile.mkdtemp(prefix="cases-"))
    etapes = 3 * len(lp)
    fait = [0]

    def avance():
        fait[0] += 1
        if progres:
            progres(fait[0], etapes)
    try:
        # 1. moitiés redressées, flash-backs, taille réelle
        info = {}
        with zipfile.ZipFile(source) as zs:
            for a, b in lp:
                for i in (a, b):
                    g = np.array(Image.open(io.BytesIO(zs.read(ordre_s[i]))).convert("L"))
                    g = redresse(g, boites.get(str(i)))
                    cv2.imwrite(str(tmp / f"r{i}.png"), g)
                    info[i] = est_flashback(g)
                avance()
        HR = hauteur_reelle([(cv2.imread(str(tmp / f"r{i}.png"), cv2.IMREAD_GRAYSCALE), info[i]) for i in info])
        if not HR:
            raise RuntimeError("taille réelle de la page introuvable (ni flash-back, ni traits de cases nets)")
        WR = round(HR * W / H)
        # 2. chaque page placée, coupée, retouchée ; contenu mesuré
        cadrage = {}
        for a, b in lp:
            gauche = cv2.imread(str(tmp / f"r{a}.png"), cv2.IMREAD_GRAYSCALE)
            droite = cv2.imread(str(tmp / f"r{b}.png"), cv2.IMREAD_GRAYSCALE)
            hm = max(gauche.shape[0], droite.shape[0])        # moitiés recoupées à des hauteurs un peu différentes : complétées en bas
            gauche = cv2.copyMakeBorder(gauche, 0, hm - gauche.shape[0], 0, 0, cv2.BORDER_REPLICATE)
            droite = cv2.copyMakeBorder(droite, 0, hm - droite.shape[0], 0, 0, cv2.BORDER_REPLICATE)
            hauts = {}
            for i, est_g in ((a, True), (b, False)):
                y0, _, sur = boite(gauche if est_g else droite, "gauche" if est_g else "droite", info[i], HR)
                hauts[i] = y0 if sur else None
            for i, est_g in ((a, True), (b, False)):
                autre = b if i == a else a
                c, rempli = placer(gauche, droite, est_g, info[i], HR, WR, hauts[autre])
                if not info[i]:
                    c, _ = couper_cases(c, rempli, "droite" if est_g else "gauche")
                    c, _ = fermer_cases(c)
                rem = cv2.resize(rempli.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
                if regl:
                    out = retoucher(c, regl, (W, H))
                else:
                    out = cv2.resize(c, (W, H), interpolation=cv2.INTER_CUBIC)
                if info[i]:
                    out, contenu = flashback(out, rem)
                else:
                    contenu = sans_folio(out < 128)
                rows, cols = np.where(contenu.sum(1) >= 3)[0], np.where(contenu.sum(0) >= 3)[0]
                if len(rows) < 10 or len(cols) < 10:
                    rows, cols = np.arange(H), np.arange(W)
                cadrage[i] = (int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1)
                cv2.imwrite(str(tmp / f"c{i}.png"), out)
            avance()
        # pages simples sans moitié sœur (tome déjà coupé au scan) : chacune redressée et coupée seule, le côté de la reliure repéré à sa bande grise
        with zipfile.ZipFile(source) as zs:
            for i in sorted(seules or ()):
                g = redresse(np.array(Image.open(io.BytesIO(zs.read(ordre_s[i]))).convert("L")), boites.get(str(i)))
                info[i] = est_flashback(g)
                if not info[i]:
                    if lp:                                # même parité que la moitié gauche d'un scan double : page de gauche, reliure à droite
                        dos = "droite" if (i - lp[0][0]) % 2 == 0 else "gauche"
                    else:
                        dos = cote_du_dos(g)
                    c, _ = couper_cases(g, np.zeros_like(g, bool), dos)
                    c, _ = fermer_cases(c)
                else:
                    c = g
                taille_i = (max(1, round(c.shape[1] * H / c.shape[0])), H)
                out = retoucher(c, regl, taille_i) if regl else cv2.resize(c, taille_i, interpolation=cv2.INTER_CUBIC)
                if info[i]:
                    out, contenu = flashback(out, np.zeros_like(out, np.uint8))
                else:
                    contenu = sans_folio(out < 128)
                rows, cols = np.where(contenu.sum(1) >= 3)[0], np.where(contenu.sum(0) >= 3)[0]
                if len(rows) < 10 or len(cols) < 10:
                    rows, cols = np.arange(out.shape[0]), np.arange(out.shape[1])
                cadrage[i] = (int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1)
                cv2.imwrite(str(tmp / f"c{i}.png"), out)
        # 3. mise en page : page blanche plein écran, flash-back au zoom médian des pages blanches
        zooms = {i: min(W * MARGE / (x1 - x0), H * MARGE / (y1 - y0)) for i, (y0, y1, x0, x1) in cadrage.items()}
        blanches = [z for i, z in zooms.items() if not info[i]]
        zoom = float(np.median(blanches or list(zooms.values())))
        pages = {}
        for i, (y0, y1, x0, x1) in cadrage.items():
            a_ = cv2.imread(str(tmp / f"c{i}.png"), cv2.IMREAD_GRAYSCALE)
            z = min(zoom, zooms[i]) if info[i] else zooms[i]
            fond = int(min(25, np.percentile(a_, 1))) if info[i] else 255
            crop = cv2.resize(a_[y0:y1, x0:x1], None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC if z > 1 else cv2.INTER_AREA)[:H, :W]
            page = np.full((H, W), fond, np.uint8)
            oy, ox = (H - crop.shape[0]) // 2, (W - crop.shape[1]) // 2
            page[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
            pages[i] = Image.fromarray(page)
            if i % 2:
                avance()
        # écriture : pages recadrées, les autres recopiées du tome actuel
        destination = Path(destination)
        part = destination.with_name(destination.name + ".part")
        with zipfile.ZipFile(chemin) as zc, zipfile.ZipFile(part, "w", zipfile.ZIP_STORED) as dst:
            rang = {n: i for i, n in enumerate(ordre)}
            for inf in zc.infolist():
                i = rang.get(inf.filename)
                if i in pages:
                    data = optimiser._octets_page(pages[i], inf.filename)
                elif retoucher_autres and i in retoucher_autres:
                    data = optimiser._octets_page(autre_page(zc.read(inf.filename), (W, H), regl), inf.filename)
                else:
                    data = zc.read(inf.filename)
                z2 = zipfile.ZipInfo(inf.filename, date_time=inf.date_time)
                dst.writestr(z2, data)
        with zipfile.ZipFile(part) as z:
            if z.testzip() is not None or archives._names(z) != ordre:
                raise RuntimeError("archive recadrée illisible")
        part.replace(destination)
        return {"pages": len(pages), "flashbacks": sorted(i for i in pages if info[i]), "hauteur": HR, "zoom": round(zoom, 3)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def autre_page(data, taille, regl):
    """Page hors paires d'un tome refait depuis l'archive (couverture, double page) : mise à la taille finale sans déformation (double page : 2W × H),
    retouchée comme les autres."""
    import optimiser
    import rognage
    im = Image.open(io.BytesIO(data))
    im.load()
    W, H = taille
    cible = (2 * W, H) if im.width > im.height else (W, H)
    sortie = rognage.rendre_page(im, rognage.boite_entiere(list(im.size)), cible)
    if regl:
        sortie = optimiser.ameliorer(sortie, regl, source=rognage.facteur(rognage.boite_entiere(list(im.size)), cible))
        if sortie.size != cible:
            sortie = sortie.resize(cible, Image.LANCZOS)
    return sortie


def depuis_archive(archive, dossier, tome_actuel, destination) -> dict:
    """Pages d'origine d'un tome reconstruites depuis l'archive téléchargée (`dossier` : son dossier dans l'archive) : chaque scan double page est coupé
    en deux moitiés (moitié gauche d'abord, comme les tomes déjà coupés), sauf s'il est resté une double page dans le tome actuel (dessin à cheval sur
    les deux pages : choix de l'utilisateur gardé). Une couverture ajoutée en tête du tome actuel est reprise telle quelle. Écrit `destination` (cbz) ;
    retour : {"pages", "doubles", "couverture" (numéros à recopier tels quels), "autres" (numéros hors paires à retoucher)}."""
    with zipfile.ZipFile(archive) as z:
        noms = sorted(n for n in z.namelist() if n.startswith(dossier.rstrip("/") + "/") and n.lower().endswith((".jpg", ".jpeg", ".png")))
        tailles_a = [Image.open(io.BytesIO(z.read(n))).size for n in noms]
        actuel = [Image.open(io.BytesIO(zipfile.ZipFile(tome_actuel).read(n))).size for n in archives.pages(tome_actuel)]
        for decale in (0, 1):
            plan, k = [], decale
            for n, (w, h) in zip(noms, tailles_a):
                if w <= h:
                    plan.append(("simple", n))
                    k += 1
                elif k < len(actuel) and actuel[k][0] > actuel[k][1]:
                    plan.append(("double", n))
                    k += 1
                else:
                    plan += [("gauche", n), ("droite", n)]
                    k += 2
            if k == len(actuel):
                break
        else:
            raise RuntimeError(f"l'archive ne correspond pas au tome actuel ({len(actuel)} pages)")
        if not decale and plan and plan[0][0] == "simple":
            plan, decale = plan[1:], 1                     # la couverture du tome actuel (remise à la main, meilleure que le scan) est gardée
        destination = Path(destination)
        part = destination.with_name(destination.name + ".part")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_STORED) as dst:
            i = 0
            if decale:
                with zipfile.ZipFile(tome_actuel) as zt:
                    n0 = archives.pages(tome_actuel)[0]
                    dst.writestr(f"{i:04d}{Path(n0).suffix.lower()}", zt.read(n0))
                i += 1
            for genre, n in plan:
                data = z.read(n)
                if genre in ("gauche", "droite"):
                    im = Image.open(io.BytesIO(data))
                    im.load()
                    w = im.width
                    im = im.crop((0, 0, w // 2, im.height) if genre == "gauche" else (w // 2, 0, w, im.height))
                    out = io.BytesIO()
                    im.convert("L" if im.mode in ("L", "1") else "RGB").save(out, "JPEG", quality=97)
                    data = out.getvalue()
                dst.writestr(f"{i:04d}.jpg", data)
                i += 1
        part.replace(destination)
    autres = [j + decale for j, (g, _) in enumerate(plan) if g in ("simple", "double")]
    sures = [(j + decale, j + decale + 1) for j, (g, _) in enumerate(plan) if g == "gauche"]
    # moitiés déjà coupées par le scanneur (pages simples consécutives) : appariées comme d'habitude, entre deux scans doubles
    simples = [j + decale for j, (g, _) in enumerate(plan) if g == "simple"]
    with zipfile.ZipFile(destination) as zd:
        noms_d = archives.pages(destination)
        tailles_d = [Image.open(io.BytesIO(zd.read(n))).size for n in noms_d]
    k = 0
    while k < len(simples):
        bloc = [simples[k]]
        while k + 1 < len(simples) and simples[k + 1] == bloc[-1] + 1:
            k += 1
            bloc.append(simples[k])
        pass        # pages déjà simples dans l'archive : jamais appariées (tailles toutes différentes, ce ne sont pas deux moitiés d'un scan : Nori Taka tome 1)
        k += 1
    sures.sort()
    dans = {j for p_ in sures for j in p_}
    restes = [j for j in autres if j not in dans]
    doubles = {j + decale for j, (g, _) in enumerate(plan) if g == "double"}
    deja_coupees = False
    return {"pages": i, "doubles": len(doubles), "couverture": [0] if decale else [], "paires": sures, "deja_coupees": deja_coupees,
            "autres": [j for j in restes if j in doubles], "seules": [j for j in restes if j not in doubles]}


# --- Dans l'appli (optimiser.lancer_coupes) --------------------------------------------------------------------------------------------------

def ecrire_tome(chemin, indices, sens_manga=True, destination=None, travail=None) -> dict:
    """Opération pour optimiser.lancer_coupes : tome recadré aux cases écrit à côté, relu, mis en place (l'ancien part dans « .avant »).
    `travail` : {"source", "copier_source", "boites", "W", "H", "retouches"} ; reçoit « resultat » et « empreintes »."""
    import rognage
    chemin = Path(chemin)
    source = Path(travail["source"])
    if travail.get("copier_source") and not (source.is_file() and source.stat().st_size == chemin.stat().st_size):
        source.parent.mkdir(parents=True, exist_ok=True)       # première fois : les pages d'origine sont gardées avant de toucher au tome
        part = source.with_name(source.name + ".part")
        shutil.copyfile(chemin, part)
        if part.stat().st_size != chemin.stat().st_size:
            part.unlink()
            raise RuntimeError("copie des pages d'origine incomplète")
        part.replace(source)
    tmp = Path(destination) if destination is not None else chemin.with_name("." + chemin.name + ".cases")
    try:
        travail["resultat"] = recadrer_tome(chemin, source, travail.get("boites") or {}, (travail["W"], travail["H"]), travail.get("retouches"), tmp,
                                            progres=travail.get("progres"))
        with zipfile.ZipFile(tmp) as z:
            travail["empreintes"] = {str(i): rognage.empreinte(z.read(n)) for i, n in enumerate(archives._names(z))}
    except Exception:
        if destination is None:
            tmp.unlink(missing_ok=True)
        raise
    n = len(archives.pages(chemin))
    res = {"carte": {i: i for i in range(n)}, "pages_avant": n, "pages": n}
    if destination is not None:
        return res
    avant = chemin.with_name(chemin.name + ".avant")
    chemin.rename(avant)
    tmp.rename(chemin)
    res["avant"] = avant
    return res


ecrire_tome.reglage = "travail"
ecrire_tome.libelle = lambda pages, tomes: f"{tomes} tome(s) recadré(s) aux cases"


def noter(manga_dir, fichier_reglages, serie, chemin, travail):
    """Après écriture : le rognage garde ses pages d'origine et ses cadres ; le tome écrit devient son « produit » (sinon, à la prochaine ouverture, ses
    pages passeraient pour changées par autre chose et deviendraient de nouvelles pages d'origine)."""
    import rognage
    chemin = Path(chemin)
    with rognage._VERROU:
        d = rognage._lire(fichier_reglages)
        e = (d["tomes"].setdefault(serie, {})).get(chemin.name)
        if e is None:
            e = {"boites": {}, "W": travail["W"], "H": travail["H"]}
            d["tomes"][serie][chemin.name] = e
        if travail.get("copier_source"):
            e["source"] = str(Path(travail["source"]).relative_to(manga_dir))
            e["source_octets"] = Path(travail["source"]).stat().st_size
            e["tailles"] = rognage.tailles_pages(travail["source"])
        e["produit"] = {"octets": chemin.stat().st_size, "W": travail["W"], "H": travail["H"], "boites": dict(e.get("boites") or {}),
                        "empreintes": travail.get("empreintes") or {}, "date": __import__("datetime").datetime.now().strftime("%d/%m/%Y"), "cases": True}
        e["cases"] = dict(travail.get("resultat") or {}, date=e["produit"]["date"])
        rognage._ecrire(fichier_reglages, d)
